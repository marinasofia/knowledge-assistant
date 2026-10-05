from contextlib import contextmanager

from sqlalchemy import create_engine, text

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def run(conn, sql, **params):
    return conn.execute(text(sql), params)


@contextmanager
def transaction(workspace=None):
    with engine.begin() as conn:
        run(conn, "SET LOCAL statement_timeout = 5000")
        if workspace:
            run(conn, "SELECT set_config('app.workspace', :workspace, true)", workspace=workspace)
        yield conn
