"""Use the same SQLite configuration as the runtime, including transactional DDL."""

from alembic import context

from andromeda.database import database_path, make_engine, write_transaction

config = context.config
engine = make_engine(config.attributes.get("path", database_path()), mode="rwc")
try:
    with write_transaction(engine) as conn:
        context.configure(connection=conn, transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
