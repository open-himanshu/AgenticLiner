import os
import tempfile

import pytest


_collection_db_dir = tempfile.TemporaryDirectory(prefix="agenticliner-pytest-")
_collection_db_path = os.path.join(_collection_db_dir.name, "collection.sqlite3")
os.environ["DATABASE_PATH"] = _collection_db_path
os.environ["DATABASE_URL"] = f"sqlite:///{_collection_db_path}"


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    database_path = tmp_path / "agenticliner-test.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    from backend.core.database.init_db import init_database, seed_campus_data
    from backend.services.seed_users import seed_users

    init_database()
    seed_campus_data()
    seed_users(force=True)


def pytest_unconfigure(config):
    _collection_db_dir.cleanup()
