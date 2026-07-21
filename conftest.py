import pytest
from pytest_socket import disable_socket
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from geminiportal.app import app as _app
from geminiportal.db import set_sqlite_pragmas
from geminiportal.models import Base


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration")


def pytest_runtest_setup(item):
    if "integration" not in item.keywords:
        disable_socket(allow_unix_socket=True)


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        # Collect all tests, including integration tests
        return

    skip_integration = pytest.mark.skip(reason="integration test")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def app():
    _app.config["DEBUG"] = True
    _app.config["TESTING"] = True
    _app.config["SERVER_NAME"] = "portal.mozz.us"
    return _app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
async def session_factory():
    # An in-memory database is used for testing, sqlalchemy will maintain
    # a single connection to it that's shared between all of the sessions.
    engine = create_async_engine("sqlite+aiosqlite://")
    event.listens_for(engine.sync_engine, "connect")(set_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()
