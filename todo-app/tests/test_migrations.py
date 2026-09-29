from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db import session as database


def test_migrations_preserve_legacy_data(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    monkeypatch.setattr(database, "engine", engine)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE todos (id INTEGER PRIMARY KEY, title TEXT)"))
        connection.execute(text("INSERT INTO todos VALUES (1, 'legacy todo')"))
    try:
        command.upgrade(config, "head")
        command.upgrade(config, "head")  # Repeat deployment is a no-op.
        assert {"todos", "users", "task_items"}.issubset(inspect(engine).get_table_names())
        command.check(config)  # Model and migration schema agree; legacy table is ignored.
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT title FROM todos WHERE id=1")) == "legacy todo"
        command.downgrade(config, "base")
        assert "task_items" not in inspect(engine).get_table_names()
        assert "todos" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
