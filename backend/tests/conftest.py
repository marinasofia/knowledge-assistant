import os

import pytest
from sqlalchemy.engine import make_url

from app.config import settings

DEVELOPMENT_DATABASE = "knowledge"


def pytest_configure(config):
    # Tests write fixtures. Never let a missing environment point them at the dev database.
    targets = {make_url(settings.database_url).database, make_url(settings.migration_url).database}
    allowed = os.environ.get("CI") or os.environ.get("KA_ALLOW_DEV_DATABASE_TESTS")
    if DEVELOPMENT_DATABASE in targets and not allowed:
        pytest.exit(
            "Refusing to run tests against the development database. Point KA_DATABASE_URL and "
            "KA_MIGRATION_URL at a disposable database (see README), or set "
            "KA_ALLOW_DEV_DATABASE_TESTS=1.",
            returncode=2,
        )


@pytest.fixture(scope="session", autouse=True)
def generous_limits():
    # The suite sends hundreds of requests from one client address and a few users within a
    # minute. Rate limit behavior itself is tested with explicit low limits.
    settings.auth_rate_per_minute = 10_000
    settings.query_rate_per_minute = 10_000
    settings.upload_rate_per_minute = 10_000
    # Daily quota counters persist in the database for the whole day, across runs.
    settings.user_daily_limit = 100_000
    settings.workspace_daily_limit = 100_000
    settings.daily_limit = 100_000
