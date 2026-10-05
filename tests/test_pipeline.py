"""Test idempotency pipeline (milik Person 3)."""
import importlib
import sys


def test_pipeline_idempotent(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    # pastikan modul baca env baru — reset singleton
    for mod in ["database.connection", "pipeline.run"]:
        sys.modules.pop(mod, None)
    import database.connection as conn

    conn._engine = None
    conn._SessionLocal = None
    conn.DATABASE_URL = f"sqlite:///{db}"
    conn.init_db(f"sqlite:///{db}")

    pr = importlib.import_module("pipeline.run")

    s1 = pr.run(limit_per_query=20)
    # jalankan ulang — inserted harus 0, skipped_dup > 0
    conn._engine = None
    conn._SessionLocal = None
    s2 = pr.run(limit_per_query=20)
    assert s1["inserted"] > 0
    assert s2["inserted"] == 0
