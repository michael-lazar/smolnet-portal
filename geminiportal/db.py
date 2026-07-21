import asyncio
import logging
import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_logger = logging.getLogger(__name__)

ROOT_PATH = Path(__file__).parent.parent
DEFAULT_DB_PATH = ROOT_PATH / "data" / "gemini-portal.sqlite"

DB_PATH = os.environ.get("DATABASE_PATH", str(DEFAULT_DB_PATH))
DB_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DB_URL)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    # SQLite ships with extremely conservative defaults, and sqlalchemy
    # doesn't override any of them. These need to be applied per-connection
    # (except journal_mode, which is persistent in the database file).
    cursor = dbapi_connection.cursor()
    # Allow concurrent readers/writers across gunicorn workers.
    cursor.execute("PRAGMA journal_mode=WAL")
    # Safe with WAL, and cuts down on fsync() calls per-transaction.
    cursor.execute("PRAGMA synchronous=NORMAL")
    # Wait for locks instead of raising "database is locked" errors.
    cursor.execute("PRAGMA busy_timeout=5000")
    # SQLite doesn't enforce foreign key constraints unless told to.
    cursor.execute("PRAGMA foreign_keys=ON")
    # Increase the page cache from the 2MB default.
    cursor.execute("PRAGMA cache_size=-20000")
    # Keep temporary tables and indices out of the filesystem.
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


# The database schema is versioned using "PRAGMA user_version", which
# counts how many of these statements have been applied. To change the
# schema, append a new SQL statement to the list and restart the server
# (or run ``tools/python -m geminiportal.db``). Statements must never be
# edited or removed once they have been deployed.
MIGRATIONS = [
    """
    CREATE TABLE favicons (
        id INTEGER NOT NULL,
        url VARCHAR NOT NULL,
        emoji VARCHAR,
        expires_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (url)
    )
    """,
    """
    CREATE TABLE sessions (
        id INTEGER NOT NULL,
        token VARCHAR NOT NULL,
        cert_pem VARCHAR NOT NULL,
        key_pem VARCHAR NOT NULL,
        cert_common_name VARCHAR,
        cert_subject VARCHAR NOT NULL,
        cert_issuer VARCHAR NOT NULL,
        cert_not_valid_before DATETIME NOT NULL,
        cert_not_valid_after DATETIME NOT NULL,
        cert_fingerprint VARCHAR NOT NULL,
        created_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (token)
    )
    """,
    """
    CREATE TABLE cert_activations (
        id INTEGER NOT NULL,
        session_id INTEGER NOT NULL,
        scheme VARCHAR NOT NULL,
        hostname VARCHAR NOT NULL,
        port INTEGER NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (session_id, scheme, hostname, port),
        FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE
    )
    """,
]


async def run_migrations() -> None:
    """
    Upgrade the database to the latest schema version.
    """
    async with engine.connect() as conn:
        # Manage the transaction manually so the write lock can be grabbed
        # up-front with BEGIN IMMEDIATE. Otherwise, two gunicorn workers
        # starting at the same time could both read the schema version
        # before either of them has applied the first migration.
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            result = await conn.exec_driver_sql("PRAGMA user_version")
            version = result.scalar_one()
            for i, migration in enumerate(MIGRATIONS[version:], start=version + 1):
                _logger.info(f"Applying database migration {i} of {len(MIGRATIONS)}")
                await conn.exec_driver_sql(migration)
                await conn.exec_driver_sql(f"PRAGMA user_version = {i}")
        except BaseException:
            await conn.exec_driver_sql("ROLLBACK")
            raise
        else:
            await conn.exec_driver_sql("COMMIT")

    _logger.info(f"Database schema is up to date (version {len(MIGRATIONS)})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(run_migrations())
