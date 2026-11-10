"""Coordinated two-database snapshots through the container-only Cloudflare R2 bridge."""

import asyncio
import hashlib
import json
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)
DATABASES = ("app.sqlite", "checkpoints.sqlite")


class StateGate:
    """Concurrent mutations normally; a checkpoint waits for turns/extraction to finish."""

    def __init__(self):
        self.condition = asyncio.Condition()
        self.readers = 0
        self.waiting = 0
        self.writing = False

    @asynccontextmanager
    async def operation(self):
        async with self.condition:
            await self.condition.wait_for(lambda: not self.writing and not self.waiting)
            self.readers += 1
        try:
            yield
        finally:
            async with self.condition:
                self.readers -= 1
                self.condition.notify_all()

    @asynccontextmanager
    async def snapshot(self):
        async with self.condition:
            self.waiting += 1
            try:
                await self.condition.wait_for(lambda: not self.readers and not self.writing)
                self.writing = True
            finally:
                self.waiting -= 1
                self.condition.notify_all()
        try:
            yield
        finally:
            async with self.condition:
                self.writing = False
                self.condition.notify_all()


def integrity(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Checkpoint database is corrupt")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def pack(data_dir, target):
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        staged = Path(directory)
        hashes = {}
        for name in DATABASES:
            source = data_dir / name
            backup = staged / name
            with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
                with sqlite3.connect(backup) as dst:
                    src.backup(dst)
                    dst.execute("PRAGMA journal_mode=DELETE")
            integrity(backup)
            hashes[name] = digest(backup)
        manifest = {
            "format": 1,
            "engine": "deepagents",
            "created": datetime.now(UTC).isoformat(),
            "sha256": hashes,
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name in DATABASES:
                archive.write(staged / name, name)
        target.chmod(0o600)


def unpack(source, data_dir):
    # Validate the entire generation before replacing either database.
    with tempfile.TemporaryDirectory(dir=data_dir) as directory:
        staged = Path(directory)
        with zipfile.ZipFile(source) as archive:
            if sorted(archive.namelist()) != sorted([*DATABASES, "manifest.json"]):
                raise ValueError("Unexpected checkpoint members")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != 1 or manifest.get("engine") != "deepagents":
                raise ValueError("Unsupported checkpoint format")
            for name in DATABASES:
                target = staged / name
                with archive.open(name) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                if digest(target) != manifest["sha256"].get(name):
                    raise ValueError("Checkpoint digest mismatch")
                integrity(target)
                target.chmod(0o600)
        for name in DATABASES:
            for suffix in ("-wal", "-shm"):
                (data_dir / (name + suffix)).unlink(missing_ok=True)
            (staged / name).replace(data_dir / name)
        return manifest


class HttpStore:
    def download(self, url, target):
        with httpx.Client(timeout=30, trust_env=False) as client:
            with client.stream("GET", url) as response:
                if response.status_code == 404:
                    return False
                response.raise_for_status()
                with target.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        output.write(chunk)
        target.chmod(0o600)
        return True

    def upload(self, url, source):
        with source.open("rb") as stream, httpx.Client(timeout=30, trust_env=False) as client:
            response = client.put(
                url,
                content=iter(lambda: stream.read(1024 * 1024), b""),
                headers={"Content-Type": "application/zip", "Content-Length": str(source.stat().st_size)},
            )
            if response.status_code != 204:
                raise RuntimeError("Checkpoint upload failed")


class Checkpoints:
    def __init__(self, settings, gate, store=None):
        self.settings, self.gate = settings, gate
        self.store = store or HttpStore()
        self.stop = asyncio.Event()
        self.upload_lock = asyncio.Lock()
        self.task = None
        self.last_success = None
        self.last_error = None

    async def restore(self):
        data = self.settings.data_dir
        data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.zip"
            found = await asyncio.to_thread(self.store.download, self.settings.checkpoint_url, source)
            if found:
                await asyncio.to_thread(unpack, source, data)
                logger.info("Restored Deep Agents checkpoint")
                return
            if any((data / name).exists() for name in DATABASES):
                raise RuntimeError(
                    "Missing remote checkpoint with existing local data; refusing to overwrite"
                )
            # The bridge returns 404 only before initialization; later absence is 503.
            logger.info("Initializing a new checkpoint namespace")

    async def snapshot(self):
        async with self.upload_lock:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "state.zip"
                async with self.gate.snapshot():
                    await asyncio.to_thread(pack, self.settings.data_dir, target)
                # Requests can resume once both standalone DB backups have been captured.
                await asyncio.to_thread(self.store.upload, self.settings.checkpoint_url, target)
                self.last_success = datetime.now(UTC).isoformat()
                self.last_error = None

    async def start(self):
        # Do not accept live traffic until the restored/migrated state is durably stored.
        await self.snapshot()
        self.task = asyncio.create_task(self.run())

    async def run(self):
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=self.settings.checkpoint_interval_seconds)
            except TimeoutError:
                try:
                    await self.snapshot()
                except Exception as error:
                    self.last_error = type(error).__name__
                    logger.warning("Checkpoint failed (%s)", self.last_error)

    async def close(self):
        self.stop.set()
        if self.task:
            await self.task
        await self.snapshot()
