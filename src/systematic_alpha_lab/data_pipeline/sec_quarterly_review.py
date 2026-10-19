"""Explicit SEC filing contexts to snapshot quarterly/TTM diagnostics."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from ..factor_research.financial_quality import accrual_from_quarterly_flows
from .fundamental_review import _amount
from .sec_snapshots import replay_sec_facts
from .snapshot_store import SnapshotStore

NORMALIZER = "sec_quarterly_review_v1"
NI = "NetIncomeLoss"
CFO = "NetCashProvidedByUsedInOperatingActivities"


def _one(frame, tag, low=None, high=None):
    matches = frame.loc[frame.tag.eq(tag)]
    if low is None:
        matches = matches.loc[matches.period_start.isna()]
    else:
        matches = matches.loc[matches.duration_days.between(low, high)]
    if len(matches) != 1:
        return None, "missing" if len(matches) == 0 else "ambiguous"
    return matches.iloc[0], "selected"


def _text(context):
    if context is None:
        return None
    amount = _amount(context.value_text)
    return str(amount) if amount is not None else None


def _number(value):
    if value is None:
        return np.nan
    result = float(Decimal(value))
    if not np.isfinite(result):
        raise ValueError("SEC calculation amount exceeds the finite float range")
    return result


def _selection(filing_accessions):
    if filing_accessions is None:
        return None
    if not isinstance(filing_accessions, (list, tuple)) or not filing_accessions:
        raise ValueError("Declare a nonempty list of filing accessions")
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", value)
        for value in filing_accessions
    ):
        raise ValueError("Invalid selected filing accession")
    if len(set(filing_accessions)) != len(filing_accessions):
        raise ValueError("Duplicate selected filing accession")
    return sorted(filing_accessions)


def sec_quarterly_diagnostic(
    facts: pd.DataFrame, filings: pd.DataFrame, *, unit="USD", min_report_end="2009-01-01", filing_accessions=None
):
    """Use reported quarters first; difference explicit YTD contexts if needed.

    Fiscal labels come only from facts in the filing's own report period.
    Differences use adjacent selected filings of the same fiscal year/start,
    retain both accessions and remain unverified snapshot-vintage arithmetic.
    Defaults use originals only. A complete explicit accession list can select
    amendments, without assigning them the original filing's availability.
    No source value, filing date, availability time or missing quarter is filled.
    """
    required = {
        "cik",
        "namespace",
        "tag",
        "unit",
        "accession",
        "period_start",
        "period_end",
        "duration_days",
        "source_fy",
        "source_fp",
        "value_text",
    }
    if not required.issubset(facts) or not {"accession", "report_date", "form"}.issubset(filings):
        raise ValueError("Missing SEC fact or filing fields")
    if not isinstance(unit, str) or not re.fullmatch(r"[A-Z]{3}", unit):
        raise ValueError("Declare an exact monetary SEC unit")
    if facts.empty or facts.cik.nunique(dropna=False) != 1 or facts.cik.isna().any():
        raise ValueError("Require one nonempty SEC filer series")
    if filings.accession.duplicated().any():
        raise ValueError("Duplicate filing metadata")
    boundary = pd.Timestamp(min_report_end)
    boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
    if pd.isna(boundary):
        raise ValueError("Invalid reporting boundary")
    selected = _selection(filing_accessions)
    if selected is None:
        scope = filings.loc[filings.form.isin(["10-K", "10-Q"]) & filings.report_date.ge(boundary)].copy()
    else:
        if not set(selected).issubset(set(filings.accession)):
            raise ValueError("Selected filing accession missing from metadata")
        scope = filings.loc[filings.accession.isin(selected)].copy()
        if not scope.form.isin(["10-K", "10-Q", "10-K/A", "10-Q/A"]).all():
            raise ValueError("Selected filing form is unsupported")
        if not scope.report_date.ge(boundary).all():
            raise ValueError("Selected filing report date is missing or before the boundary")
    if scope.report_date.duplicated().any():
        raise ValueError("Multiple original or selected filings for one report end; choose one accession")
    if scope.empty:
        raise ValueError("No original quarterly or annual filings in scope")
    rows = []
    for _, filing in scope.sort_values("report_date").iterrows():
        current = facts.loc[
            facts.accession.eq(filing.accession)
            & facts.namespace.eq("us-gaap")
            & facts.unit.eq(unit)
            & facts.period_end.eq(filing.report_date)
        ]
        row = {
            "asset": "sec:" + str(facts.cik.iloc[0]),
            "cik": str(facts.cik.iloc[0]),
            "accession": filing.accession,
            "form": filing.form,
            "filing_date": filing.get("filing_date", pd.NaT),
            "selection_policy": "original_only" if selected is None else "explicit_accession_list",
            "filing_is_amendment": filing.form.endswith("/A"),
            "period_end": filing.report_date,
            "currency": unit,
            "unit": unit,
            "fiscal_year": None,
            "fiscal_quarter": None,
            "fiscal_label_status": "missing_or_ambiguous",
            "net_income_ytd_text": None,
            "cash_flow_ytd_text": None,
            "income_ytd_start": pd.NaT,
            "cash_flow_ytd_start": pd.NaT,
            "net_income_quarter_text": None,
            "cash_flow_quarter_text": None,
            "total_assets_text": None,
            "income_quarter_start": pd.NaT,
            "cash_flow_quarter_start": pd.NaT,
            "income_quarter_context": "missing",
            "cash_flow_quarter_context": "missing",
            "income_basis": "missing",
            "cash_flow_basis": "missing",
            "income_reported_minus_ytd_difference_text": None,
            "cash_flow_reported_minus_ytd_difference_text": None,
            "income_previous_accession": None,
            "cash_flow_previous_accession": None,
        }
        metadata = current[["source_fy", "source_fp"]].drop_duplicates()
        if len(metadata) == 1:
            year = pd.to_numeric(metadata.source_fy.iloc[0], errors="coerce")
            label = metadata.source_fp.iloc[0]
            quarter = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}.get(label)
            if (
                not isinstance(year, (bool, np.bool_))
                and pd.notna(year)
                and np.isfinite(year)
                and 1 <= year <= 9999
                and year == int(year)
                and (
                    (filing.form.removesuffix("/A") == "10-K" and quarter == 4)
                    or (filing.form.removesuffix("/A") == "10-Q" and quarter in (1, 2, 3))
                )
            ):
                row.update(fiscal_year=int(year), fiscal_quarter=quarter, fiscal_label_status="filing_current_period")
        assets, _ = _one(current, "Assets")
        row["total_assets_text"] = _text(assets)
        for tag, prefix in ((NI, "income"), (CFO, "cash_flow")):
            quarter_context, status = _one(current, tag, 60, 120)
            row[prefix + "_quarter_context"] = status
            if quarter_context is not None:
                row[("net_income" if prefix == "income" else "cash_flow") + "_quarter_text"] = _text(quarter_context)
                row[prefix + "_quarter_start"] = quarter_context.period_start
                row[prefix + "_basis"] = "reported_quarter"
        if row["fiscal_quarter"] is not None:
            low, high = {1: (60, 120), 2: (140, 220), 3: (230, 310), 4: (330, 400)}[row["fiscal_quarter"]]
            for tag, prefix, amount_name in ((NI, "income", "net_income"), (CFO, "cash_flow", "cash_flow")):
                context, status = _one(current, tag, low, high)
                row[prefix + "_ytd_context"] = status
                if context is not None:
                    row[amount_name + "_ytd_text"] = _text(context)
                    row[prefix + "_ytd_start"] = context.period_start
        rows.append(row)

    for i, row in enumerate(rows):
        quarter = row["fiscal_quarter"]
        previous = rows[i - 1] if i else None
        adjacent = (
            previous is not None
            and quarter is not None
            and previous["fiscal_quarter"] is not None
            and (
                row["fiscal_year"] == previous["fiscal_year"]
                and quarter == previous["fiscal_quarter"] + 1
                and 60 <= (row["period_end"] - previous["period_end"]).days <= 120
            )
        )
        for prefix, amount in (("income", "net_income"), ("cash_flow", "cash_flow")):
            left = row[amount + "_ytd_text"]
            right = previous[amount + "_ytd_text"] if adjacent else None
            starts_equal = (
                adjacent
                and pd.notna(row[prefix + "_ytd_start"])
                and (row[prefix + "_ytd_start"] == previous[prefix + "_ytd_start"])
            )
            # A reported quarter must cover the interval after the adjacent
            # filing, whenever that exact preceding boundary is available.
            if (
                adjacent
                and row[prefix + "_basis"] == "reported_quarter"
                and (row[prefix + "_quarter_start"] != previous["period_end"] + pd.Timedelta(days=1))
            ):
                row[amount + "_quarter_text"] = None
                row[prefix + "_basis"] = "reported_quarter_start_mismatch"
            if row[prefix + "_basis"] == "reported_quarter" and left is not None and right is not None and starts_equal:
                reported = row[amount + "_quarter_text"]
                if reported is not None:
                    row[prefix + "_reported_minus_ytd_difference_text"] = str(
                        Decimal(reported) - (Decimal(left) - Decimal(right))
                    )
            if row[prefix + "_quarter_context"] != "missing":
                continue  # Never replace an ambiguous/rejected reported context.
            allowed = prefix == "cash_flow" or quarter == 4
            if not allowed or not adjacent:
                continue
            if left is not None and right is not None and starts_equal:
                row[amount + "_quarter_text"] = str(Decimal(left) - Decimal(right))
                row[prefix + "_basis"] = "annual_minus_q3_ytd" if quarter == 4 else "adjacent_ytd_difference"
                row[prefix + "_previous_accession"] = previous["accession"]
        if row["fiscal_label_status"] != "filing_current_period":
            row["net_income_quarter_text"] = row["cash_flow_quarter_text"] = None

    frame = pd.DataFrame(rows)
    for name in ("fiscal_year", "fiscal_quarter"):
        frame[name] = frame[name].astype("Int64")
    for source, target in (
        ("net_income_quarter_text", "net_income"),
        ("cash_flow_quarter_text", "operating_cash_flow_quarter"),
        ("total_assets_text", "total_assets"),
    ):
        frame[target] = frame[source].map(_number)
    calculated = accrual_from_quarterly_flows(frame)
    output = [
        "ttm_net_income",
        "ttm_operating_cash_flow",
        "average_assets",
        "accrual_quality",
        "four_quarter_window_ready",
        "five_quarter_window_ready",
        "calculation_ready",
    ]
    for column in output:
        frame[column] = calculated[column].to_numpy()
    ordinal = frame.fiscal_year * 4 + frame.fiscal_quarter
    four = ordinal.eq(ordinal.shift(3) + 3).fillna(False)
    five = ordinal.eq(ordinal.shift(4) + 4).fillna(False)
    # Check each transition too: endpoint equality alone can hide a bad interior label.
    pair = ordinal.eq(ordinal.shift(1) + 1).fillna(False).astype(int)
    four &= pair.rolling(3).sum().eq(3)
    five &= pair.rolling(4).sum().eq(4)
    frame["four_quarter_window_ready"] &= four
    frame["five_quarter_window_ready"] &= five
    for column in ("ttm_net_income", "ttm_operating_cash_flow"):
        frame[column] = frame[column].where(frame.four_quarter_window_ready)
    frame["average_assets"] = frame.average_assets.where(frame.five_quarter_window_ready)
    frame["accrual_quality"] = frame.accrual_quality.where(four & five)
    frame["calculation_ready"] &= four & five
    frame["cross_filing_differencing"] = (
        frame.income_previous_accession.notna() | frame.cash_flow_previous_accession.notna()
    )
    amendments = set(frame.loc[frame.filing_is_amendment, "accession"])
    frame["quarter_input_involves_amendment"] = (
        frame.filing_is_amendment
        | frame.income_previous_accession.isin(amendments)
        | frame.cash_flow_previous_accession.isin(amendments)
    )
    # Four quarterly flows plus the opening asset observation can depend on
    # an amendment. Keep unavailable windows unknown instead of marking false.
    amendment_input = frame.quarter_input_involves_amendment.rolling(4).max().eq(1) | frame.filing_is_amendment.shift(
        4, fill_value=False
    )
    frame["ttm_amendment_input_involved"] = amendment_input.astype("boolean").where(frame.calculation_ready)
    frame["version_status"] = "current_aggregate_cross_filing_vintages_unverified"
    frame["timing_status"] = "snapshot_only_availability_unverified"
    frame["available_at"] = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    return frame


def review_sec_quarterly_snapshots(
    store: SnapshotStore,
    facts_record: dict,
    submissions_record: dict,
    *,
    history_records=(),
    unit="USD",
    min_report_end="2009-01-01",
    filing_accessions=None,
):
    """Strict source verification, including filing-date conflict rejection."""
    selected = _selection(filing_accessions)
    source = replay_sec_facts(store, facts_record, submissions_record, history_records=history_records)
    provenance = {
        "source_manifest": source,
        "unit": unit,
        "min_report_end": min_report_end,
        "filing_accessions": selected,
        "selection_policy": "original_only" if selected is None else "explicit_accession_list",
        "normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "calculation_source_sha256": hashlib.sha256(
            Path(__file__).resolve().parents[1].joinpath("factor_research/financial_quality.py").read_bytes()
        ).hexdigest(),
        "quarter_policy": "reported_quarter_first_else_adjacent_same_start_ytd_difference",
        "version_policy": "cross_filing_snapshot_differences_unverified",
    }
    version = NORMALIZER + "_" + hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:20]
    existing = store.dataset(facts_record["id"], version)
    if existing is not None:
        return existing
    tables = {
        name: pd.read_parquet(store.root / item["path"], use_threads=False, pre_buffer=False)
        for name, item in source["tables"].items()
    }
    result = sec_quarterly_diagnostic(
        tables["facts"], tables["filings"], unit=unit, min_report_end=min_report_end, filing_accessions=selected
    )
    return store.publish_tables(facts_record, version, {"quarterly_review": result}, provenance=provenance)
