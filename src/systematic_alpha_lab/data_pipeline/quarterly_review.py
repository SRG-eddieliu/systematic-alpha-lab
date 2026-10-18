"""Provider-only quarterly TTM diagnostics with source assumptions retained."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..factor_research.financial_quality import accrual_from_quarterly_flows
from .fundamental_review import _amount, _difference, review_fundamental_snapshots
from .snapshot_store import SnapshotStore, utc_time

NORMALIZER = "av_quarterly_review_v1"


def review_quarterly_snapshots(store: SnapshotStore, records: list[dict]) -> dict:
    """Use provider quarterly flows directly, never difference them as YTD.

    The monetary scale and quarterly-flow basis remain source assumptions. This
    computes snapshot diagnostics, not historically available market signals.
    """
    annual_manifest = review_fundamental_snapshots(store, records)
    provenance = {
        "normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "calculation_source_sha256": hashlib.sha256(Path(__file__).resolve().parents[1].joinpath(
            "factor_research/financial_quality.py").read_bytes()).hexdigest(),
        "annual_review_manifest": annual_manifest,
        "formula": "-(four_quarter_net_income - four_quarter_operating_cash_flow) / average_assets_t_and_t_minus_4",
        "flow_assumption": "provider_quarterly_reports_are_quarterly_flows_unverified",
        "scale_assumption": "provider_common_monetary_scale_within_currency_unverified",
        "quarter_gap_days": [60, 120],
        "four_interval_span_days": [330, 400],
    }
    version = NORMALIZER + "_" + hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:20]
    inputs = {json.loads(record["request_json"])["function"]: record for record in records}
    anchor = inputs["INCOME_STATEMENT"]
    existing = store.dataset(anchor["id"], version)
    if existing is not None:
        return existing
    source_manifests = {manifest["snapshot_id"]: manifest for manifest in annual_manifest["provenance"]["input_manifests"]}
    columns = {"INCOME_STATEMENT": ("netIncome", "net_income"),
               "CASH_FLOW": ("operatingCashflow", "operating_cash_flow_quarter"),
               "BALANCE_SHEET": ("totalAssets", "total_assets")}
    aligned = []
    for function, (field, name) in columns.items():
        item = source_manifests[inputs[function]["id"]]["tables"]["quarterly"]
        source = pd.read_parquet(store.root / item["path"])
        frame = pd.DataFrame({"period_end": source.period_end,
                              name + "_text": source.get(field, pd.Series(pd.NA, index=source.index)),
                              function.lower() + "_currency": source.currency})
        if function == "CASH_FLOW":
            frame["cash_flow_net_income_text"] = source.get("netIncome", pd.Series(pd.NA, index=source.index))
        aligned.append(frame)
    frame = aligned[0].merge(aligned[1], on="period_end", how="outer", validate="one_to_one").merge(
        aligned[2], on="period_end", how="outer", validate="one_to_one"
    ).sort_values("period_end").reset_index(drop=True)
    currencies = [function.lower() + "_currency" for function in columns]
    frame["currency_consistent"] = frame[currencies].notna().all(axis=1) & frame[currencies].nunique(axis=1).eq(1)
    frame["currency"] = frame[currencies[0]].where(frame.currency_consistent)
    for _, name in columns.values():
        values = frame[name + "_text"].map(_amount)
        frame[name] = values.map(lambda value: float(value) if value is not None else np.nan)
        if np.isinf(frame[name]).any():
            raise ValueError("Provider amount exceeds the numeric calculation range")
    income_currency_matches = frame.income_statement_currency.notna() & frame.cash_flow_currency.notna() & (
        frame.income_statement_currency.eq(frame.cash_flow_currency)
    )
    frame["source_income_difference_text"] = [
        _difference(_amount(left), _amount(right)) if matches else None
        for left, right, matches in zip(frame.net_income_text, frame.cash_flow_net_income_text, income_currency_matches)
    ]
    frame["source_income_comparison"] = frame.source_income_difference_text.map(
        lambda value: "missing" if value is None else "exact_match" if Decimal(value) == 0 else "value_difference"
    )
    frame.loc[~income_currency_matches, "source_income_comparison"] = "currency_missing_or_different"
    symbol = json.loads(anchor["request_json"])["symbol"]
    frame["asset"] = "alpha_vantage:" + symbol
    frame["unit"] = "provider_reported_common_scale_assumption"
    calculated = accrual_from_quarterly_flows(frame.loc[frame.currency_consistent])
    output_columns = ["period_end", "ttm_net_income", "ttm_operating_cash_flow", "average_assets", "accrual_quality",
                      "four_quarter_window_ready", "five_quarter_window_ready", "calculation_ready"]
    frame = frame.merge(calculated[output_columns], on="period_end", how="left", validate="one_to_one")
    for flag in ("four_quarter_window_ready", "five_quarter_window_ready", "calculation_ready"):
        frame[flag] = frame[flag].eq(True)
    frame["calculation_status"] = np.where(frame.calculation_ready, "candidate_only", "incomplete_window_or_amount")
    frame.loc[~frame.currency_consistent, "calculation_status"] = "source_currency_unresolved"
    # Count over the same accepted rows as the arithmetic, so an extra unmatched
    # source date cannot displace a quarter in the diagnostic's coverage count.
    comparisons = frame.loc[frame.currency_consistent, ["period_end", "source_income_comparison"]].copy()
    comparisons["ttm_source_income_difference_count"] = comparisons.source_income_comparison.eq(
        "value_difference"
    ).astype(int).rolling(4, min_periods=4).sum()
    comparisons["ttm_source_income_comparable_quarters"] = comparisons.source_income_comparison.isin(
        ["exact_match", "value_difference"]
    ).astype(int).rolling(4, min_periods=4).sum()
    frame = frame.merge(comparisons.drop(columns="source_income_comparison"), on="period_end", how="left",
                        validate="one_to_one")
    for name in ("ttm_source_income_difference_count", "ttm_source_income_comparable_quarters"):
        frame[name] = frame[name].where(frame.four_quarter_window_ready).astype("Int64")
    item = annual_manifest["tables"]["reconciliation"]
    checks = pd.read_parquet(store.root / item["path"])
    for function in columns:
        statuses = checks.loc[checks.source_function.eq(function), ["period_end", "status"]].rename(
            columns={"status": function.lower() + "_annual_check"}
        )
        frame = frame.merge(statuses, on="period_end", how="left", validate="one_to_one")
        name = function.lower() + "_annual_check"
        frame[name] = frame[name].fillna("not_annual_endpoint")
    frame["provider_symbol"] = symbol
    frame["identifier_basis"] = "provider_symbol_unmapped"
    frame["amount_unit_status"] = "provider_common_scale_assumption_unverified"
    frame["cash_flow_basis"] = "provider_quarterly_flow_assumption_unverified"
    frame["timing_status"] = "snapshot_only_availability_unverified"
    frame["observed_at"] = max(utc_time(record["observed_at"]) for record in records)
    frame["available_at"] = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    return store.publish_tables(anchor, version, {"quarterly_review": frame, "source_reconciliation": checks}, provenance=provenance)
