"""Use provider snapshots directly for descriptive annual statement diagnostics.

Source differences remain visible. This is neither historical alpha evaluation
nor a replacement for the locked four-quarter financial-quality specification.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from .fundamental_snapshots import FUNCTIONS, replay_fundamentals
from .snapshot_store import SnapshotStore, utc_time

NORMALIZER = "av_statement_review_v1"
FIELDS = {"INCOME_STATEMENT": "netIncome", "CASH_FLOW": "operatingCashflow", "BALANCE_SHEET": "totalAssets"}


def _amount(value):
    if value is None or pd.isna(value) or str(value).strip() in {"", "None", "null", "NaN", "nan"}:
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Non-numeric provider amount; do not silently coerce") from None
    if not result.is_finite():
        raise ValueError("Non-finite provider amount")
    return result


def _difference(left, right):
    return str(left - right) if left is not None and right is not None else None


def _reconcile(function, annual, quarterly):
    rows = []
    field = FIELDS[function]
    annual = annual.sort_values("period_end")
    previous_end = None
    for _, row in annual.iterrows():
        end = row.period_end
        if function == "BALANCE_SHEET":
            observed = quarterly.loc[quarterly.period_end.eq(end)]
        elif previous_end is not None:
            observed = quarterly.loc[quarterly.period_end.gt(previous_end) & quarterly.period_end.le(end)]
        else:
            observed = quarterly.iloc[:0]
        status = "checked"
        if function != "BALANCE_SHEET":
            if previous_end is None:
                status = "no_preceding_annual_boundary"
            elif not 330 <= (end - previous_end).days <= 400:
                status = "irregular_annual_gap"
            elif len(observed) != 4:
                status = "incomplete_quarter_window"
            else:
                dates = [previous_end, *observed.sort_values("period_end").period_end.tolist()]
                if any(not 60 <= (right - left).days <= 120 for left, right in zip(dates, dates[1:])) or dates[-1] != end:
                    status = "irregular_quarter_spacing"
        elif len(observed) != 1:
            status = "missing_quarter_endpoint"
        amounts = [_amount(value) for value in observed.get(field, pd.Series(pd.NA, index=observed.index))]
        annual_amount = _amount(row.get(field))
        compared = None
        if status == "checked":
            if not observed.currency.eq(row.currency).all():
                status = "currency_difference"
            elif annual_amount is None or any(value is None for value in amounts):
                status = "missing_amount"
            else:
                compared = sum(amounts, Decimal(0))
                status = "exact_match" if annual_amount == compared else "value_difference"
        rows.append({
            "source_function": function, "field": field, "period_end": end,
            "comparison": "annual_vs_same_end_quarter" if function == "BALANCE_SHEET" else "annual_vs_four_quarter_sum",
            "annual_value_text": None if annual_amount is None else str(annual_amount),
            "compared_value_text": None if compared is None else str(compared),
            "difference_text": _difference(annual_amount, compared),
            "quarter_rows": len(observed), "status": status,
        })
        previous_end = end
    return pd.DataFrame(rows)


def review_fundamental_snapshots(store: SnapshotStore, records: list[dict]) -> dict:
    """Align all annual periods and retain source checks and candidate arithmetic.

    Candidate = -(annual NI - annual CFO) / average adjacent-year assets.
    Provider numeric amounts are assumed to share a scale within their reported
    currency; that assumption remains explicitly unverified. No quarterly/YTD
    conversion, fiscal-quarter inference or SEC input is needed by this review.
    """
    if not isinstance(records, (list, tuple)) or len(records) != 3:
        raise ValueError("Require one snapshot for each of the three statements")
    inputs = {}
    for record in records:
        request = json.loads(record["request_json"])
        function = request.get("function")
        if record["provider"] != "alpha_vantage" or function not in FUNCTIONS or function in inputs:
            raise ValueError("Require unique Alpha Vantage statement observations")
        inputs[function] = (record, request)
    symbols = {request.get("symbol") for _, request in inputs.values()}
    if len(symbols) != 1:
        raise ValueError("Cannot combine different provider symbols")
    tables, source_manifests = {}, []
    for function in FUNCTIONS:
        record, request = inputs[function]
        manifest = replay_fundamentals(store, record)
        if not {"annual", "quarterly"}.issubset(manifest["tables"]):
            raise ValueError("Review requires annual and quarterly staging for each statement")
        source_manifests.append(manifest)
        tables[function] = {kind: pd.read_parquet(store.root / table["path"])
                            for kind, table in manifest["tables"].items()}
    provenance = {
        "normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_manifests": source_manifests,
        "formula": "-(annual_net_income - annual_operating_cash_flow) / average_adjacent_year_assets",
        "scale_assumption": "provider_amounts_share_scale_within_currency_unverified",
        "annual_gap_days": [330, 400], "quarter_gap_days": [60, 120],
    }
    version = NORMALIZER + "_" + hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:20]
    anchor = inputs["INCOME_STATEMENT"][0]
    existing = store.dataset(anchor["id"], version)
    if existing is not None:
        return existing
    aligned = []
    names = {"INCOME_STATEMENT": "net_income", "CASH_FLOW": "operating_cash_flow", "BALANCE_SHEET": "total_assets"}
    for function in FUNCTIONS:
        source = tables[function]["annual"]
        target = pd.DataFrame({"period_end": source.period_end,
                               names[function] + "_text": source.get(FIELDS[function], pd.Series(pd.NA, index=source.index)),
                               function.lower() + "_currency": source.currency})
        if function == "CASH_FLOW":
            target["cash_flow_net_income_text"] = source.get("netIncome", pd.Series(pd.NA, index=source.index))
        aligned.append(target)
    frame = aligned[0].merge(aligned[1], on="period_end", how="outer", validate="one_to_one").merge(
        aligned[2], on="period_end", how="outer", validate="one_to_one"
    ).sort_values("period_end").reset_index(drop=True)
    currencies = [function.lower() + "_currency" for function in FUNCTIONS]
    frame["currency_consistent"] = frame[currencies].notna().all(axis=1) & frame[currencies].nunique(axis=1).eq(1)
    frame["currency"] = frame[currencies[0]].where(frame.currency_consistent)
    amounts = {name: frame[name + "_text"].map(_amount) for name in names.values()}
    income_currency_matches = frame.income_statement_currency.notna() & frame.cash_flow_currency.notna() & (
        frame.income_statement_currency.eq(frame.cash_flow_currency)
    )
    frame["source_income_difference_text"] = [
        _difference(income, _amount(other)) if currency_matches else None
        for income, other, currency_matches in zip(
            amounts["net_income"], frame.cash_flow_net_income_text, income_currency_matches
        )
    ]
    frame["source_income_comparison"] = frame.source_income_difference_text.map(
        lambda value: "missing" if value is None else "exact_match" if Decimal(value) == 0 else "value_difference"
    )
    frame.loc[~income_currency_matches, "source_income_comparison"] = "currency_missing_or_different"
    ratios, statuses = [], []
    for i, row in frame.iterrows():
        ni, cfo, assets = [amounts[name].iloc[i] for name in ("net_income", "operating_cash_flow", "total_assets")]
        previous_assets = amounts["total_assets"].iloc[i - 1] if i else None
        status = "candidate_only"
        if not row.currency_consistent:
            status = "missing_or_different_currency"
        elif i == 0:
            status = "no_preceding_annual_assets"
        elif not 330 <= (row.period_end - frame.period_end.iloc[i - 1]).days <= 400:
            status = "irregular_annual_gap"
        elif not frame.currency_consistent.iloc[i - 1] or frame.currency.iloc[i - 1] != row.currency:
            status = "different_preceding_currency"
        elif any(value is None for value in (ni, cfo, assets, previous_assets)):
            status = "missing_amount"
        elif assets <= 0 or previous_assets <= 0:
            status = "nonpositive_assets"
        ratio = float(-(ni - cfo) / ((assets + previous_assets) / 2)) if status == "candidate_only" else float("nan")
        if status == "candidate_only" and not math.isfinite(ratio):
            status, ratio = "outside_float_range", float("nan")
        ratios.append(ratio)
        statuses.append(status)
    frame["annual_accrual_candidate"] = ratios
    frame["arithmetic_status"] = statuses
    frame["provider_symbol"] = next(iter(symbols))
    frame["identifier_basis"] = "provider_symbol_unmapped"
    frame["amount_unit_status"] = "provider_common_scale_assumption_unverified"
    frame["timing_status"] = "snapshot_only_availability_unverified"
    frame["observed_at"] = max(utc_time(record["observed_at"]) for record in records)
    frame["available_at"] = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    checks = pd.concat([_reconcile(function, tables[function]["annual"], tables[function]["quarterly"])
                        for function in FUNCTIONS], ignore_index=True)
    return store.publish_tables(anchor, version, {"annual_review": frame, "reconciliation": checks}, provenance=provenance)
