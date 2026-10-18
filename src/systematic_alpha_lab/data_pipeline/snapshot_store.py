"""Immutable local JSON/Parquet objects and a small SQLite provenance catalog."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from uuid import uuid4

import pandas as pd


def utc_time(value=None) -> datetime:
    stamp = pd.Timestamp(datetime.now(timezone.utc) if value is None else value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("An aware observation timestamp is required")
    return stamp.tz_convert("UTC").to_pydatetime()


def _label(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("Invalid catalog label")
    return value


def _safe_metadata(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if any(token in str(key).lower() for token in ("key", "token", "password", "secret", "authorization")):
                raise ValueError("Credentials cannot be stored in request metadata")
            _safe_metadata(child)
    elif isinstance(value, list):
        for child in value:
            _safe_metadata(child)


class SnapshotStore:
    """Private data root; source observations never replace an older version."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.catalog = self.root / "catalog.sqlite3"
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL, provider TEXT NOT NULL,
                request_json TEXT NOT NULL, observed_at TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL, raw_path TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS request_observed ON snapshots(request_id, observed_at)")
            db.execute("""CREATE TABLE IF NOT EXISTS datasets (
                snapshot_id TEXT NOT NULL, normalizer TEXT NOT NULL, manifest_json TEXT NOT NULL,
                PRIMARY KEY(snapshot_id, normalizer))""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.catalog)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def request_id(provider: str, request: dict) -> str:
        _label(provider)
        _safe_metadata(request)
        return hashlib.sha256(json.dumps([provider, request], sort_keys=True, allow_nan=False).encode()).hexdigest()

    def _write(self, relative: str, content: bytes) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = hashlib.sha256(content).hexdigest()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("Immutable object already exists with different content") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return digest

    def capture(self, provider: str, request: dict, body: bytes, *, observed_at=None) -> dict:
        request_id = self.request_id(provider, request)
        observed = utc_time(observed_at).isoformat()
        payload = json.loads(body)
        if not isinstance(payload, dict) or not payload or any(
            key in payload for key in ("Information", "Note", "Error Message")
        ):
            raise ValueError("Only successful JSON objects can enter the snapshot catalog")
        _safe_metadata(payload)
        digest = hashlib.sha256(body).hexdigest()
        relative = f"raw/{digest[:2]}/{digest}.json"
        self._write(relative, body)
        record = {"id": uuid4().hex, "request_id": request_id, "provider": provider,
                  "request_json": json.dumps(request, sort_keys=True, allow_nan=False),
                  "observed_at": observed, "raw_sha256": digest, "raw_path": relative}
        with self._db() as db:
            db.execute("""INSERT INTO snapshots
                (id, request_id, provider, request_json, observed_at, raw_sha256, raw_path)
                VALUES (:id, :request_id, :provider, :request_json, :observed_at, :raw_sha256, :raw_path)""", record)
        return record

    def latest(self, provider: str, request: dict) -> dict | None:
        request_id = self.request_id(provider, request)
        with self._db() as db:
            record = db.execute("SELECT * FROM snapshots WHERE request_id=? ORDER BY observed_at DESC, rowid DESC LIMIT 1",
                                (request_id,)).fetchone()
        return dict(record) if record is not None else None

    def read_payload(self, record: dict) -> dict:
        body = (self.root / record["raw_path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != record["raw_sha256"]:
            raise ValueError("Raw snapshot hash mismatch")
        return json.loads(body)

    def dataset(self, snapshot_id: str, normalizer: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT manifest_json FROM datasets WHERE snapshot_id=? AND normalizer=?",
                             (snapshot_id, normalizer)).fetchone()
        if row is None:
            return None
        manifest = json.loads(row[0])
        for table in manifest["tables"].values():
            if hashlib.sha256((self.root / table["path"]).read_bytes()).hexdigest() != table["sha256"]:
                raise ValueError("Normalized table hash mismatch")
        return manifest

    def publish_tables(self, record: dict, normalizer: str, tables: dict[str, pd.DataFrame], *, provenance=None) -> dict:
        _label(normalizer)
        existing = self.dataset(record["id"], normalizer)
        if existing is not None:
            return existing
        if not tables:
            raise ValueError("Cannot publish an empty dataset")
        manifest = {"snapshot_id": record["id"], "normalizer": normalizer,
                    "raw_sha256": record["raw_sha256"], "observed_at": record["observed_at"],
                    "pandas_version": pd.__version__, "provenance": provenance or {}, "tables": {}}
        _safe_metadata(manifest["provenance"])
        for name, frame in tables.items():
            _label(name)
            buffer = io.BytesIO()
            frame.to_parquet(buffer, index=False)
            body = buffer.getvalue()
            relative = f"normalized/{record['id']}/{normalizer}/{name}.parquet"
            digest = self._write(relative, body)
            manifest["tables"][name] = {"path": relative, "sha256": digest, "rows": len(frame)}
        with self._db() as db:
            db.execute("INSERT INTO datasets VALUES (?, ?, ?)",
                       (record["id"], normalizer, json.dumps(manifest, sort_keys=True)))
        return manifest
