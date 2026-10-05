from alembic import context
from sqlalchemy import create_engine

from app.config import settings

with create_engine(settings.migration_url).connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
