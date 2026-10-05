import logging
import time

from .db import run, transaction
from .ingestion import activate_due, cleanup, process_one


def tick():
    with transaction() as conn:
        workspaces = list(run(conn, "SELECT id FROM workspaces").scalars())
    work = False
    for workspace in workspaces:
        work = process_one(workspace) or work
        activate_due(workspace)
        cleanup(workspace)
    return work


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            if not tick():
                time.sleep(2)
        except Exception:
            logging.exception("worker_tick_failed")
            time.sleep(5)
