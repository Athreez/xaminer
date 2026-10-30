"""Test bundles (TECHNICAL_ARCHITECTURE.md § 9.4): a coding version's test cases packed into one
tar file in object storage, for the exec-worker to fetch by a short-lived link.

The tar is built the same way every time (fixed order, names, dates and owners), so equal test
cases give equal bytes. It is stored under its SHA-256, `<institution>/<sha256>.tar`: the key
names the content, a bundle never changes, and the worker can cache it by hash. Results name cases
by position (`001` is the first), which is fixed for a version once it's in use. Any change to the
test cases clears `coding_config.bundle_key` and queues a rebuild on app-worker.
"""

import hashlib
import io
import json
import tarfile
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import Storage
from app.db.session import SessionFactory, system_session
from app.questions.models import CodingConfig, QuestionVersion, TestCase
from app.questions.test_cases import all_test_cases
from workers import queues

BUNDLES = "bundles"
FORMAT = 1


def pack(cases: list[TestCase]) -> tuple[bytes, str]:
    """The tar file of these test cases, and its SHA-256 (hex)."""
    files: list[tuple[str, bytes]] = []
    manifest = {"format": FORMAT, "cases": []}
    for i, case in enumerate(cases, start=1):
        name = f"{i:03d}"
        files += [
            (f"{name}.in", case.input.encode()),
            (f"{name}.out", case.expected_output.encode()),
        ]
        manifest["cases"].append(  # type: ignore[attr-defined]
            {"name": name, "weight": case.weight, "hidden": case.visibility == "HIDDEN"}
        )
    files.append(("manifest.json", json.dumps(manifest, sort_keys=True, indent=1).encode()))

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o444, 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    data = buffer.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def key_for(institution_id: uuid.UUID, digest: str) -> str:
    return f"{institution_id}/{digest}.tar"


def stale(config: CodingConfig) -> None:
    """The test cases changed: the bundle no longer matches (call `queue_build` after commit)."""
    config.bundle_key = None


def queue_build(version_id: uuid.UUID) -> None:
    """Ask app-worker to (re)build this version's bundle. Tests replace this."""
    from workers.celery_app import enqueue  # the API's Celery client, made on first use

    enqueue("questions.build_bundle", queues.DEFAULT, version_id=str(version_id))


async def build(factory: SessionFactory, storage: Storage, version_id: uuid.UUID) -> str | None:
    """Build and store the bundle of a version's current test cases; return its key.

    Safe to repeat and to race with edits: the config row is locked while the cases are read and
    the key saved, and an edit holds the same row. Locked versions are never rebuilt (their bundle
    was made before validation, and the database refuses changes to them).
    """
    async with system_session(factory) as session:
        config = await session.scalar(
            select(CodingConfig).where(CodingConfig.version_id == version_id).with_for_update()
        )
        version = await session.get(QuestionVersion, version_id)
        if config is None or version is None:  # deleted meanwhile
            return None
        if version.is_locked:
            return config.bundle_key
        key = await _store(session, storage, config)
        await session.commit()
        return key


async def ensure(session: AsyncSession, storage: Storage, config: CodingConfig) -> str:
    """The bundle of this config's current test cases, built now if missing or stale. The caller
    holds the config row (locked) and commits."""
    return await _store(session, storage, config)


async def _store(session: AsyncSession, storage: Storage, config: CodingConfig) -> str:
    data, digest = pack(await all_test_cases(session, config.version_id))
    key = key_for(config.institution_id, digest)
    if config.bundle_key != key:
        await storage.put(BUNDLES, key, data, "application/x-tar")
        config.bundle_key = key
    return key
