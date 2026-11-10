import asyncio
import sqlite3
import zipfile

import pytest

from app.checkpoints import Checkpoints, StateGate, pack, unpack
from app.config import Settings


def test_snapshots_include_wal_and_validate_both_before_replacing(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    connections = []
    for name in ("app.sqlite", "checkpoints.sqlite"):
        db = sqlite3.connect(data / name)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE test(value)")
        db.execute("INSERT INTO test VALUES(42)")
        db.commit()
        connections.append(db)
    target = tmp_path / "state.zip"
    pack(data, target)
    for db in connections:
        db.close()
    restored = tmp_path / "restored"
    restored.mkdir()
    unpack(target, restored)
    for name in ("app.sqlite", "checkpoints.sqlite"):
        with sqlite3.connect(restored / name) as db:
            assert db.execute("SELECT value FROM test").fetchone()[0] == 42
    original = (restored / "app.sqlite").read_bytes()
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(target) as src, zipfile.ZipFile(corrupt, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, b"bad" if name == "checkpoints.sqlite" else src.read(name))
    with pytest.raises(ValueError, match="digest"):
        unpack(corrupt, restored)
    assert (restored / "app.sqlite").read_bytes() == original


def test_gate_waits_for_turns_and_prevents_new_mutations_during_snapshot():
    async def run():
        gate, events = StateGate(), []

        async def snapshot():
            async with gate.snapshot():
                events.append("snapshot")
                await asyncio.sleep(0.01)
                assert events == ["turn", "snapshot"]

        async def mutation():
            async with gate.operation():
                events.append("later")

        async with gate.operation():
            events.append("turn")
            saved = asyncio.create_task(snapshot())
            await asyncio.sleep(0)
            later = asyncio.create_task(mutation())
            await asyncio.sleep(0)
            assert events == ["turn"]
        await asyncio.gather(saved, later)
        assert events == ["turn", "snapshot", "later"]

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["unavailable", "corrupt"])
def test_restore_fails_closed(tmp_path, mode):
    class Store:
        def download(self, url, target):
            if mode == "unavailable":
                raise OSError("storage unavailable")
            if mode == "missing":
                return False
            target.write_bytes(b"corrupt")
            return True

    settings = Settings(_env_file=None, data_dir=tmp_path, checkpoint_url="http://storage/state")
    manager = Checkpoints(settings, StateGate(), Store())
    with pytest.raises((RuntimeError, OSError, zipfile.BadZipFile)):
        asyncio.run(manager.restore())
    assert not (tmp_path / "app.sqlite").exists()


def test_http_upload_has_known_length_for_r2(tmp_path, monkeypatch):
    from app.checkpoints import HttpStore

    source = tmp_path / "state.zip"
    source.write_bytes(b"checkpoint bytes")

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def put(self, url, content, headers):
            assert int(headers["Content-Length"]) == len(b"".join(content))
            return type("Response", (), {"status_code": 204})()

    monkeypatch.setattr("app.checkpoints.httpx.Client", Client)
    HttpStore().upload("http://storage.internal/deepagents-state.zip", source)


def test_first_boot_only_initializes_with_no_local_data(tmp_path):
    class EmptyStore:
        def download(self, url, target):
            return False

    settings = Settings(_env_file=None, data_dir=tmp_path, checkpoint_url="http://storage/state")
    asyncio.run(Checkpoints(settings, StateGate(), EmptyStore()).restore())
    (tmp_path / "app.sqlite").touch()
    with pytest.raises(RuntimeError, match="existing local data"):
        asyncio.run(Checkpoints(settings, StateGate(), EmptyStore()).restore())
