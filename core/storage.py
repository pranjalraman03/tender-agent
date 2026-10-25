"""Object storage for tender PDFs and Udyam uploads.

Two backends with the same interface:
- LocalStorage: a folder on disk, for development without bucket credentials.
- S3Storage: any S3-compatible bucket. Production uses Cloudflare R2.
boto3 is synchronous, so its calls run in a worker thread.
"""

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config

from core.config import get_settings


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def signed_url(self, key: str, expires_s: int = 900) -> str | None:
        """A time-limited direct URL, or None if the backend can't make one."""
        ...


def _check_key(key: str) -> None:
    if key.startswith("/") or ".." in key.split("/"):
        raise ValueError(f"invalid storage key {key!r}")


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        _check_key(key)
        return self.root / key

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def signed_url(self, key: str, expires_s: int = 900) -> str | None:
        return None  # served through the API instead


class S3Storage:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",  # R2 ignores regions; "auto" is its documented value
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        _check_key(key)
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        _check_key(key)
        response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body

    async def signed_url(self, key: str, expires_s: int = 900) -> str | None:
        _check_key(key)
        url: str = await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_s,
        )
        return url


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage(
            s.storage_endpoint,
            s.storage_bucket,
            s.storage_access_key.get_secret_value(),
            s.storage_secret_key.get_secret_value(),
        )
    return LocalStorage(s.storage_local_dir)
