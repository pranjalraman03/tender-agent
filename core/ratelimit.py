"""Fixed-window rate limiting in Postgres (no Redis in v1). Each check runs in its own short
transaction so a rejected or long-running request can't hold the counter row."""

from datetime import UTC, datetime

from sqlalchemy import text

from core.db.session import system_transaction


class RateLimited(Exception):
    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"rate limited; retry after {retry_after_s}s")
        self.retry_after_s = retry_after_s


async def hit(bucket: str, limit: int, window_s: int) -> None:
    """Count one request for `bucket`; raise RateLimited if the window's limit is exceeded."""
    now = datetime.now(UTC)
    start = datetime.fromtimestamp(now.timestamp() // window_s * window_s, UTC)
    async with system_transaction() as s:
        count = (
            await s.execute(
                text("""
                INSERT INTO rate_limits (bucket, window_start, count) VALUES (:b, :w, 1)
                ON CONFLICT (bucket, window_start) DO UPDATE SET count = rate_limits.count + 1
                RETURNING count
            """),
                {"b": bucket, "w": start},
            )
        ).scalar_one()
        if count == 1:  # first hit of a new window: tidy windows that ended an hour ago
            await s.execute(
                text(
                    "DELETE FROM rate_limits WHERE window_start < now() - "
                    "interval '1 hour' * greatest(1, :w / 3600.0)"
                ),
                {"w": window_s},
            )
    if count > limit:
        raise RateLimited(int(start.timestamp() + window_s - now.timestamp()) + 1)
