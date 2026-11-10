"""RQ worker entry point:  python -m app.worker  [cleanup]"""

import logging
import sys

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.core.database import get_engine, init_db
from app.jobs import fail_stale_audits, purge_expired_workspaces


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        print(f"purged {purge_expired_workspaces()} workspace(s)")
        return
    stale = fail_stale_audits()
    if stale:
        logging.getLogger(__name__).warning("marked %d stale audit(s) as failed", stale)
    # The parent only talks to Redis from here on; hold no DB connections across fork().
    get_engine().dispose()
    conn = Redis.from_url(get_settings().redis_url)
    Worker([Queue("audits", connection=conn)], connection=conn).work(with_scheduler=False)


if __name__ == "__main__":
    main()
