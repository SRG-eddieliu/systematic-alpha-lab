"""Offline, explicitly selected multi-company snapshot diagnostics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from .fundamental_snapshots import FUNCTIONS
from .quarterly_review import review_quarterly_snapshots
from .snapshot_store import SnapshotStore

NORMALIZER = "av_batch_review_v1"


def _select(store, symbols, snapshot_ids):
    if not isinstance(symbols, (list, tuple)) or not symbols or any(
        not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol)
        for symbol in symbols
    ) or len(set(symbols)) != len(symbols):
        raise ValueError("Declare explicit, unique provider symbols")
    symbols = sorted(symbols)
    if snapshot_ids is not None and (
        not isinstance(snapshot_ids, dict) or set(snapshot_ids) != set(symbols)
    ):
        raise ValueError("Pinned selection must match the complete symbol list")
    selection, records = {}, {}
    for symbol in symbols:
        pinned = snapshot_ids[symbol] if snapshot_ids is not None else None
        if snapshot_ids is not None and (not isinstance(pinned, dict) or set(pinned) != set(FUNCTIONS)):
            raise ValueError("Pin every statement, using null for absent captures")
        selection[symbol], records[symbol] = {}, []
        for function in FUNCTIONS:
            if pinned is None:
                record = store.latest("alpha_vantage", {"function": function, "symbol": symbol})
                selected_id = record["id"] if record is not None else None
            else:
                selected_id = pinned[function]
                record = store.get(selected_id) if selected_id is not None else None
            if record is not None and (
                record["provider"] != "alpha_vantage"
                or json.loads(record["request_json"]) != {"function": function, "symbol": symbol}
            ):
                raise ValueError("Pinned capture belongs to another company or statement")
            selection[symbol][function] = selected_id
            records[symbol].append(record)
    return selection, records


def _summary(symbol, status):
    return {
        "provider_symbol": symbol, "status": status,
        "annual_rows": None, "annual_candidate_rows": None,
        "quarterly_rows": None, "ttm_candidate_rows": None,
        "quarterly_income_comparable_rows": None, "quarterly_income_difference_rows": None,
        "first_quarter_end": None, "last_quarter_end": None,
        "observed_annual_end_months": None, "reported_currencies": None,
        "timing_status": "snapshot_only_availability_unverified",
    }


def review_fundamental_batch(
    store: SnapshotStore, *, symbols: list[str], snapshot_ids: dict | None = None,
) -> dict:
    """Review cached companies independently; never download or fill source gaps.

    Selection is frozen before computation. Passing a previous result's
    ``selection`` pins exact captures, including explicitly missing inputs.
    A company with absent or rejected inputs stays in the summary and cannot
    silently shrink the requested sample. Unknown programming errors propagate.
    """
    selection, selected = _select(store, symbols, snapshot_ids)
    summaries, dependencies, frames, anchor = [], {}, {}, None
    for symbol, records in selected.items():
        if any(record is None for record in records):
            summaries.append(_summary(symbol, "missing_captures"))
            continue
        try:
            quarterly = review_quarterly_snapshots(store, records)
            annual = quarterly["provenance"]["annual_review_manifest"]
            # The review verifies raw and staged hashes, including on replay.
            tables = {
                "annual_review": pd.read_parquet(store.root / annual["tables"]["annual_review"]["path"]),
                "quarterly_review": pd.read_parquet(store.root / quarterly["tables"]["quarterly_review"]["path"]),
                "reconciliation": pd.read_parquet(store.root / quarterly["tables"]["source_reconciliation"]["path"]),
            }
        except (ValueError, FileNotFoundError):
            # Never echo provider bodies, credentials, local paths or exception
            # text. Inspect the selected source captures privately to diagnose.
            summaries.append(_summary(symbol, "source_rejected"))
            continue
        annual_frame, quarter_frame = tables["annual_review"], tables["quarterly_review"]
        summary = _summary(symbol, "review_ready")
        summary.update(
            annual_rows=len(annual_frame),
            annual_candidate_rows=int(annual_frame.annual_accrual_candidate.notna().sum()),
            quarterly_rows=len(quarter_frame), ttm_candidate_rows=int(quarter_frame.calculation_ready.sum()),
            quarterly_income_comparable_rows=int(quarter_frame.source_income_comparison.isin(
                ["exact_match", "value_difference"]).sum()),
            quarterly_income_difference_rows=int(quarter_frame.source_income_comparison.eq("value_difference").sum()),
            first_quarter_end=quarter_frame.period_end.min().isoformat(),
            last_quarter_end=quarter_frame.period_end.max().isoformat(),
            # Observations, not inferred fiscal-year/quarter assignments.
            observed_annual_end_months=json.dumps(sorted(set(annual_frame.period_end.dt.month))),
            reported_currencies=json.dumps(sorted(set(quarter_frame.currency.dropna()))),
        )
        summaries.append(summary)
        dependencies[symbol] = quarterly
        if anchor is None:
            anchor = records[0]
        for name, frame in tables.items():
            frames.setdefault(name, []).append(frame.assign(provider_symbol=symbol))

    status = "complete" if len(dependencies) == len(selection) else "partial" if dependencies else "no_usable_symbols"
    result = {"status": status, "selection": selection, "summary": summaries, "manifest": None}
    if anchor is None:
        return result
    tables = {name: pd.concat(parts, ignore_index=True) for name, parts in frames.items()}
    for name, frame in tables.items():
        keys = ["provider_symbol", "period_end"] + (["source_function"] if name == "reconciliation" else [])
        if frame.duplicated(keys).any():
            raise ValueError("Combined diagnostic grain is not unique")
    summary = pd.DataFrame(summaries)
    for column in ("annual_rows", "annual_candidate_rows", "quarterly_rows", "ttm_candidate_rows",
                   "quarterly_income_comparable_rows", "quarterly_income_difference_rows"):
        summary[column] = summary[column].astype("Int64")
    tables["coverage"] = summary
    provenance = {
        "selection": selection, "company_manifests": dependencies, "coverage": summaries,
        "normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "explicit_convenience_sample_not_historical_investible_universe",
        "availability": "snapshot_only_not_historical_signals", "network_calls": 0,
    }
    version = NORMALIZER + "_" + hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:20]
    result["manifest"] = store.publish_tables(anchor, version, tables, provenance=provenance)
    return result
