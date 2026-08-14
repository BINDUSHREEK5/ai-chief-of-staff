"""Shared pytest fixtures.

Each test gets its own file-backed SQLite database in pytest's tmp_path
(not `:memory:` — a real file behaves the same as production under
SQLAlchemy's async engine, whereas an in-memory DB can behave subtly
differently across connections).
"""
from __future__ import annotations

import pytest_asyncio

from app.memory import Memory


@pytest_asyncio.fixture
async def memory(tmp_path):
    db_path = tmp_path / "test.db"
    store = Memory(database_url=f"sqlite+aiosqlite:///{db_path}")
    await store.init()
    yield store
    await store.close()