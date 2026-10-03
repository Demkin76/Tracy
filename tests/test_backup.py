import pytest

from scripts.backup import backup, validate


def test_online_backup_and_restore_preserve_verified_receipts(env, tmp_path):
    result = env.client.post("/v1/actions", json=env.signed()).json()
    saved = tmp_path / "saved.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    assert backup(env.settings.database_path, saved) == 1
    assert backup(saved, restored) == 1
    assert validate(restored) == 1
    with pytest.raises(FileExistsError):
        backup(saved, restored)
    from backend.database.db import Database

    db = Database(restored)
    with db.connect() as conn:
        import json

        body = json.loads(conn.execute("SELECT body FROM receipts").fetchone()[0])
    assert body == result["receipt"]
