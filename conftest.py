import os
import tempfile

import pytest

# Ensure import-time load_dotenv() runs once before per-test env scrubbing.
import backend.core.planner.call_llm  # noqa: F401


_collection_db_dir = tempfile.TemporaryDirectory(prefix="agenticliner-pytest-")
_collection_db_path = os.path.join(_collection_db_dir.name, "collection.sqlite3")
os.environ["DATABASE_PATH"] = _collection_db_path
os.environ["DATABASE_URL"] = f"sqlite:///{_collection_db_path}"

_PROVIDER_ENV_VARS = (
    "PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "OLLAMA_MODEL",
    "OLLAMA_HOST",
    "GROQ_REASONING_EFFORT",
)


@pytest.fixture(autouse=True)
def isolated_provider_env(monkeypatch):
    """Strip ambient provider and API-key env vars so tests stay hermetic."""
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

TEST_PASSWORDS = {
    "SUPERVISOR_PASSWORD": "test-supervisor-password",
    "ORGANISER_PASSWORD": "test-organiser-password",
    "DATA_MANAGER_PASSWORD": "test-data-manager-password",
    "PARTICIPANT_PASSWORD": "test-participant-password",
}


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    database_path = tmp_path / "agenticliner-test.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    for name, password in TEST_PASSWORDS.items():
        monkeypatch.setenv(name, password)
        monkeypatch.setenv(f"TEST_{name}", password)

    from backend.core.database.init_db import init_database, seed_campus_data
    from backend.services.seed_users import seed_users

    init_database()
    seed_campus_data()
    seed_users(force=True)


def pytest_unconfigure(config):
    _collection_db_dir.cleanup()
