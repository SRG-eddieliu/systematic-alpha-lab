"""Read pinned normalized snapshots without collection, credentials or writes.

This facade deliberately does not replay or normalize missing materializations.
Dates select source calendar labels, never historical information availability.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .snapshot_store import SnapshotStore, utc_time

_DATE_COLUMNS = {
    "monthly_prices": "session_date",
    "annual": "period_end",
    "quarterly": "period_end",
    "annual_review": "period_end",
    "quarterly_review": "period_end",
    "reconciliation": "period_end",
    "source_reconciliation": "period_end",
    "facts": "period_end",
    "filings": "filing_date",
}


@dataclass(frozen=True)
class DataRead:
    """Caller-owned frame and the evidence/limits of its exact source selection."""

    frame: pd.DataFrame
    metadata: dict


def _label(value, *, snapshot=False):
    pattern = r"[0-9a-f]{32}" if snapshot else r"[A-Za-z0-9_-]{1,80}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("Invalid snapshot identifier" if snapshot else "Invalid catalog label")
    return value


def _json(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate catalog/source JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite catalog/source JSON constant")

    return json.loads(body, object_pairs_hook=unique, parse_constant=invalid_constant)


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Invalid SHA256 digest")
    return value


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Date bounds require YYYY-MM-DD source calendar dates")
    return pd.Timestamp(value, tz="UTC")


def _bounds(dates):
    if dates is None or dates.dropna().empty:
        return {"start": None, "end": None}
    return {"start": dates.min().strftime("%Y-%m-%d"), "end": dates.max().strftime("%Y-%m-%d")}


class OfflineDataReader:
    """Open an existing, quiescent SnapshotStore root strictly for reading.

    A collection process must not mutate this root during a read. SQLite is
    opened with mode=ro and immutable=1, so neither missing catalogs nor journal
    sidecars are created. Use a separate explicit ingestion action to refresh.
    """

    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Snapshot root must be an existing directory")
        self._catalog = self._path("catalog.sqlite3")

    def _path(self, relative):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError("Invalid snapshot object path")
        path = Path(relative)
        if path.is_absolute() or any(part in ("..", ".") for part in path.parts):
            raise ValueError("Snapshot object path escapes the data root")
        resolved = (self.root / path).resolve(strict=True)
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError("Snapshot object path escapes the data root or is not a file")
        return resolved

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self._catalog.as_uri() + "?mode=ro&immutable=1", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        try:
            yield db
        finally:
            db.close()

    def _bytes(self, relative, digest):
        digest = _digest(digest)
        body = self._path(relative).read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("Snapshot object hash mismatch")
        return body

    def _record(self, db, snapshot_id, state):
        _label(snapshot_id, snapshot=True)
        if snapshot_id in state["records"]:
            return state["records"][snapshot_id]
        rows = db.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchall()
        if not rows:
            raise KeyError("Pinned snapshot is not in this catalog")
        if len(rows) != 1:
            raise ValueError("Pinned snapshot identity is ambiguous")
        record = dict(rows[0])
        request = _json(record["request_json"])
        if not isinstance(request, dict) or not request:
            raise ValueError("Snapshot request must be a nonempty object")
        if SnapshotStore.request_id(record["provider"], request) != record["request_id"]:
            raise ValueError("Snapshot request identity differs from catalog hash")
        utc_time(record["observed_at"])
        payload = _json(self._bytes(record["raw_path"], record["raw_sha256"]))
        if not isinstance(payload, dict) or not payload or any(
            name in payload for name in ("Information", "Note", "Error Message")
        ):
            raise ValueError("Snapshot source is not a successful JSON object")
        # These checks bind catalog identities to the source's explicit labels.
        # No ticker-to-security or CIK-to-ticker inference occurs here.
        if record["provider"] == "alpha_vantage":
            function = request.get("function")
            if function in ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW"):
                if payload.get("symbol") != request.get("symbol"):
                    raise ValueError("Source symbol differs from the catalog request")
            elif function == "TIME_SERIES_MONTHLY_ADJUSTED" and (
                not isinstance(payload.get("Meta Data"), dict)
                or payload["Meta Data"].get("2. Symbol") != request.get("symbol")
            ):
                raise ValueError("Source symbol differs from the catalog request")
        if record["provider"] == "sec" and request.get("kind") in ("companyfacts", "submissions"):
            try:
                same_cik = int(payload["cik"]) == int(request["cik"])
            except (KeyError, TypeError, ValueError):
                same_cik = False
            if not same_cik:
                raise ValueError("Source CIK differs from the catalog request")
        record["request"] = request
        state["records"][snapshot_id] = record
        return record

    def _normalizer_contract(self, db, record, normalizer, provenance, state):
        families = {
            "av_monthly_prices_v1": ("source_request", "source_provider", "source_observed_at"),
            "sec_accession_facts_v1": ("input_snapshots",),
            "sec_quarterly_review_v1": ("source_manifest",),
            "av_statement_review_v1": ("input_manifests",),
            "av_quarterly_review_v1": ("annual_review_manifest",),
            "av_batch_review_v1": ("company_manifests",),
        }
        family = next((name for name in families if normalizer == name or normalizer.startswith(name + "_")), None)
        if family is None:
            return
        suffix = hashlib.sha256(json.dumps(provenance, sort_keys=True, allow_nan=False).encode()).hexdigest()[:20]
        if normalizer != family + "_" + suffix:
            raise ValueError("Normalizer version does not bind its complete provenance")
        if any(name not in provenance for name in families[family]):
            raise ValueError("Known normalizer lacks required dependency provenance")
        if family == "sec_accession_facts_v1":
            items = provenance["input_snapshots"]
            if not isinstance(items, list) or len(items) < 2 or any(not isinstance(item, dict) for item in items):
                raise ValueError("SEC facts require facts and submissions dependencies")
            dependencies = [self._record(db, item.get("id"), state) for item in items]
            requests = [dependency["request"] for dependency in dependencies]
            if dependencies[0]["id"] != record["id"] or any(
                dependency["provider"] != "sec" or request.get("cik") != record["request"].get("cik")
                for dependency, request in zip(dependencies, requests)
            ) or [request.get("kind") for request in requests[:2]] != ["companyfacts", "submissions"] or any(
                request.get("kind") != "submissions_history" for request in requests[2:]
            ):
                raise ValueError("SEC facts dependencies do not match the source contract")
        elif family == "av_statement_review_v1":
            items = provenance["input_manifests"]
            if not isinstance(items, list) or len(items) != 3 or any(not isinstance(item, dict) for item in items):
                raise ValueError("Statement review requires three statement manifests")
            dependencies = [self._record(db, item.get("snapshot_id"), state) for item in items]
            functions = set()
            for item, dependency in zip(items, dependencies):
                request = dependency["request"]
                if item.get("normalizer") != "av_fundamentals_v1" or dependency["provider"] != "alpha_vantage" or (
                    request.get("symbol") != record["request"].get("symbol")
                ):
                    raise ValueError("Statement-review dependency source differs from its anchor")
                functions.add(request.get("function"))
            if functions != {"INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW"}:
                raise ValueError("Statement-review dependencies omit a required endpoint")
        elif family in ("sec_quarterly_review_v1", "av_quarterly_review_v1"):
            name, prefix = ("source_manifest", "sec_accession_facts_v1_") if family.startswith("sec_") else (
                "annual_review_manifest", "av_statement_review_v1_"
            )
            item = provenance[name]
            if not isinstance(item, dict) or item.get("snapshot_id") != record["id"] or not isinstance(
                item.get("normalizer"), str
            ) or not item["normalizer"].startswith(prefix):
                raise ValueError("Quarterly review lacks its required source manifest")
        elif family == "av_batch_review_v1":
            items = provenance["company_manifests"]
            selection = provenance.get("selection")
            if not isinstance(items, dict) or not items or not isinstance(selection, dict) or not selection:
                raise ValueError("Batch review requires company manifests and an explicit selection")
            if not set(items).issubset(selection):
                raise ValueError("Batch company manifests fall outside the explicit selection")
            for symbol, item in items.items():
                if not isinstance(item, dict) or not isinstance(item.get("normalizer"), str) or not item[
                    "normalizer"
                ].startswith("av_quarterly_review_v1_"):
                    raise ValueError("Batch review requires quarterly company manifests")
                dependency = self._record(db, item.get("snapshot_id"), state)
                if dependency["provider"] != "alpha_vantage" or dependency["request"].get("symbol") != symbol:
                    raise ValueError("Batch company dependency differs from its declared symbol")

    def _manifest(self, db, snapshot_id, normalizer, state, expected=None):
        _label(normalizer)
        record = self._record(db, snapshot_id, state)
        rows = db.execute(
            "SELECT manifest_json FROM datasets WHERE snapshot_id=? AND normalizer=?", (snapshot_id, normalizer)
        ).fetchall()
        if not rows:
            raise KeyError("Pinned normalized dataset is not in this catalog")
        if len(rows) != 1:
            raise ValueError("Pinned normalized dataset is ambiguous")
        manifest = _json(rows[0][0])
        if expected is not None and manifest != expected:
            raise ValueError("Embedded source manifest differs from the catalog")
        identity = (snapshot_id, normalizer)
        if identity in state["active"]:
            raise ValueError("Cyclic snapshot manifest dependencies")
        if identity in state["manifests"]:
            return state["manifests"][identity]
        if not isinstance(manifest, dict) or any(
            manifest.get(name) != value for name, value in {
                "snapshot_id": snapshot_id,
                "normalizer": normalizer,
                "raw_sha256": record["raw_sha256"],
                "observed_at": record["observed_at"],
            }.items()
        ):
            raise ValueError("Manifest identity differs from the pinned catalog record")
        tables, provenance = manifest.get("tables"), manifest.get("provenance")
        if not isinstance(tables, dict) or not tables or not isinstance(provenance, dict):
            raise ValueError("Invalid normalized manifest tables/provenance")
        self._normalizer_contract(db, record, normalizer, provenance, state)
        # These fields occur on monthly-price derivations and are exact source
        # identities, not user-supplied historical-availability guarantees.
        for name, expected_value in {
            "source_request": record["request"],
            "source_provider": record["provider"],
            "source_observed_at": record["observed_at"],
        }.items():
            if name in provenance and provenance[name] != expected_value:
                raise ValueError("Manifest provenance differs from source identity")
        for name, table in tables.items():
            _label(name)
            if not isinstance(table, dict) or isinstance(table.get("rows"), bool) or not isinstance(
                table.get("rows"), int
            ) or table["rows"] < 0:
                raise ValueError("Invalid table row-count contract")
            body = self._bytes(table.get("path"), table.get("sha256"))
            parquet_metadata = pq.read_metadata(io.BytesIO(body))
            if parquet_metadata.num_rows != table["rows"]:
                raise ValueError("Normalized table row count differs from manifest")
            state["bodies"][(snapshot_id, normalizer, name)] = body
        state["active"].add(identity)
        self._dependencies(db, provenance, state)
        state["active"].remove(identity)
        state["manifests"][identity] = manifest
        return manifest

    def _dependencies(self, db, value, state):
        if isinstance(value, dict):
            if {"snapshot_id", "normalizer", "tables"}.issubset(value):
                self._manifest(db, value["snapshot_id"], value["normalizer"], state, expected=value)
                return
            if "input_snapshots" in value:
                inputs = value["input_snapshots"]
                if not isinstance(inputs, list) or not inputs:
                    raise ValueError("Invalid input snapshot dependencies")
                ids = []
                for item in inputs:
                    if not isinstance(item, dict) or not {"id", "raw_sha256", "observed_at"}.issubset(item):
                        raise ValueError("Incomplete input snapshot dependency")
                    record = self._record(db, item["id"], state)
                    if any(item[name] != record[name] for name in ("id", "raw_sha256", "observed_at")):
                        raise ValueError("Input snapshot dependency differs from catalog")
                    ids.append(item["id"])
                if len(set(ids)) != len(ids):
                    raise ValueError("Duplicate input snapshot dependencies")
            for key, child in value.items():
                if key != "input_snapshots":
                    self._dependencies(db, child, state)
        elif isinstance(value, list):
            for child in value:
                self._dependencies(db, child, state)

    @staticmethod
    def _state():
        return {"records": {}, "manifests": {}, "bodies": {}, "active": set()}

    def catalog(self, *, provider: str, request: dict) -> list[dict]:
        """List every materialized version for exactly one provider request.

        An empty list means no matching materialization, not permission to fetch.
        Results are ordered by observation, capture ID, normalizer and table;
        callers explicitly select/persist their desired identities.
        """
        if not isinstance(request, dict) or not request:
            raise ValueError("Declare a nonempty exact source request")
        request_id = SnapshotStore.request_id(provider, request)
        result, state = [], self._state()
        with self._db() as db:
            rows = db.execute(
                "SELECT id FROM snapshots WHERE request_id=? ORDER BY observed_at, id", (request_id,)
            ).fetchall()
            for row in rows:
                record = self._record(db, row["id"], state)
                if record["provider"] != provider or record["request"] != request:
                    raise ValueError("Catalog request hash resolves to a different source")
                versions = db.execute(
                    "SELECT normalizer FROM datasets WHERE snapshot_id=? ORDER BY normalizer", (record["id"],)
                ).fetchall()
                for version in versions:
                    normalizer = version["normalizer"]
                    manifest = self._manifest(db, record["id"], normalizer, state)
                    for table, item in sorted(manifest["tables"].items()):
                        result.append({
                            "snapshot_id": record["id"], "normalizer": normalizer, "table": table,
                            "provider": provider, "request": dict(request), "observed_at": record["observed_at"],
                            "raw_sha256": record["raw_sha256"], "table_sha256": item["sha256"], "rows": item["rows"],
                        })
        return result

    def read(self, *, snapshot_id, normalizer, table, start=None, end=None, fields=None) -> DataRead:
        """Read one exact table, preserving empty ranges and source amount strings.

        Projection changes columns only; complete source identities, provenance,
        coverage and readiness diagnostics remain in returned metadata.
        """
        _label(snapshot_id, snapshot=True)
        _label(normalizer)
        _label(table)
        lower, upper = _date(start), _date(end)
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("Date range starts after it ends")
        if fields is not None and (
            not isinstance(fields, (list, tuple)) or not fields
            or any(not isinstance(name, str) or not name for name in fields) or len(set(fields)) != len(fields)
        ):
            raise ValueError("Fields must be a nonempty unique list of column names")
        state = self._state()
        with self._db() as db:
            manifest = self._manifest(db, snapshot_id, normalizer, state)
        if table not in manifest["tables"]:
            raise KeyError("Pinned table is not in this normalized dataset")
        frame = pd.read_parquet(io.BytesIO(state["bodies"][(snapshot_id, normalizer, table)]),
                                use_threads=False, pre_buffer=False)
        if not frame.columns.is_unique or len(frame) != manifest["tables"][table]["rows"]:
            raise ValueError("Normalized table columns/row count differ from manifest")
        record = state["records"][snapshot_id]
        for column, expected in {
            "snapshot_id": snapshot_id, "normalizer": normalizer, "provider": record["provider"],
            "symbol": record["request"].get("symbol"), "cik": record["request"].get("cik"),
            "access_mode": record["request"].get("access_mode"),
        }.items():
            if column in frame and expected is not None and not frame[column].eq(expected).fillna(False).all():
                raise ValueError("Normalized table source identity differs from catalog")
        dependencies = list(state["records"].values())
        provider_requests = [item["request"] for item in dependencies if item["provider"] == record["provider"]]
        if "provider_symbol" in frame:
            symbols = {request["symbol"] for request in provider_requests if "symbol" in request}
            if table == "coverage" and normalizer.startswith("av_batch_review_v1_"):
                # Coverage explicitly retains requested symbols with missing or
                # rejected inputs. They are observations about the selection,
                # not claims of verified source dependencies for those symbols.
                symbols = set(manifest["provenance"]["selection"])
            if not frame.provider_symbol.isin(symbols).all():
                raise ValueError("Normalized table provider symbol is outside its verified dependencies")
        if "source_function" in frame:
            if table in ("reconciliation", "source_reconciliation"):
                # Reconciliation spans three endpoint captures. Validate every
                # function/symbol pair against declared dependencies, not just
                # the anchor income-statement request.
                allowed = {(request.get("symbol"), request.get("function")) for request in provider_requests}
                symbols = frame["provider_symbol"] if "provider_symbol" in frame else [
                    record["request"].get("symbol")
                ] * len(frame)
                if any((symbol, function) not in allowed for symbol, function in zip(symbols, frame.source_function)):
                    raise ValueError("Reconciliation source function is outside its verified dependencies")
            elif record["request"].get("function") is not None and not frame.source_function.eq(
                record["request"]["function"]
            ).fillna(False).all():
                raise ValueError("Normalized table source function differs from catalog")
        requested = list(frame.columns) if fields is None else list(fields)
        missing = [name for name in requested if name not in frame]
        if missing:
            raise KeyError("Requested fields are not in the pinned table: " + ", ".join(missing))
        date_column = _DATE_COLUMNS.get(table)
        dates = None
        if date_column is not None:
            if date_column not in frame:
                raise ValueError("Normalized table lacks its declared source date column")
            dates = pd.to_datetime(frame[date_column], utc=True, errors="raise")
        elif lower is not None or upper is not None:
            raise ValueError("This table has no declared calendar-date filter")
        mask = pd.Series(True, index=frame.index)
        if lower is not None:
            mask &= dates.ge(lower)
        if upper is not None:
            mask &= dates.lt(upper + pd.Timedelta(days=1))
        selected = frame.loc[mask].copy()
        selected_dates = None if dates is None else dates.loc[mask]
        available = selected["available_at"].notna().sum() if "available_at" in selected else 0
        stable_ids = selected["asset_id"].notna().sum() if "asset_id" in selected else 0
        ready = selected["calculation_ready"].eq(True).sum() if "calculation_ready" in selected else 0
        metadata = {
            "snapshot_id": snapshot_id, "normalizer": normalizer, "table": table,
            "provider": record["provider"], "request": record["request"], "observed_at": record["observed_at"],
            "raw_sha256": record["raw_sha256"], "table_sha256": manifest["tables"][table]["sha256"],
            "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, allow_nan=False).encode()).hexdigest(),
            "provenance": manifest["provenance"],
            "verified_dependencies": [
                {name: dependency[name] for name in ("id", "provider", "raw_sha256", "observed_at", "request")}
                for _, dependency in sorted(state["records"].items())
            ],
            "source_rows": len(frame), "returned_rows": len(selected), "date_column": date_column,
            "coverage": {
                "source": _bounds(dates), "returned": _bounds(selected_dates),
                "requested": {"start": start, "end": end},
                "missing_date_rows": 0 if dates is None else int(dates.isna().sum()),
                "date_basis": "source_calendar_labels_not_public_availability",
                "expected_frequency": "not_inferred",
            },
            "missing_fields": [],
            "missingness": {name: int(selected[name].isna().sum()) for name in requested},
            "readiness": {
                "status": "not_certified",
                "available_at_supplied_rows": int(available), "stable_asset_id_supplied_rows": int(stable_ids),
                "calculation_ready_rows": int(ready),
                "reason": "Reader verifies stored evidence integrity, not historical research eligibility",
            },
        }
        return DataRead(frame=selected.loc[:, requested].reset_index(drop=True), metadata=metadata)
