"""Run one job handler directly, in one transaction, without the queue (debugging).

uv run python scripts/run_job.py crawl --portal cppp
"""

import argparse
import asyncio

from core.db.session import system_transaction
from core.jobs import HANDLERS
from core.observability import configure_logging


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(HANDLERS))
    parser.add_argument("--portal")
    parser.add_argument("--tender-id", type=int)
    args = parser.parse_args()
    payload = {k: v for k, v in {"portal": args.portal, "tender_id": args.tender_id}.items() if v}

    configure_logging(json_logs=False)
    async with system_transaction() as session:
        await HANDLERS[args.kind](payload, session)


if __name__ == "__main__":
    asyncio.run(main())
