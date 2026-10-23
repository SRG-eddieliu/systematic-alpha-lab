# Annual Beneish calculator and pinned source review

Implements the [v1 research definition](integrity-research-method-v1.md) after
the method contract's review and merge. This is a strict annual calculator and
a read-only AV candidate bridge. It does not certify external accounting
semantics, authentic publication times, population applicability or alpha.

## Public and synthetic examples first

```bash
python examples/verify_integrity_method_contract.py
python examples/annual_beneish_demo.py
pytest -q tests/test_beneish_standard.py tests/test_beneish_pipeline.py
```

The first example is an independent Decimal reference. The second passes the
author's Sunbeam monetary amounts through the production annual calculator;
its dates, units and scope are explicitly **synthetic API-test declarations**,
not recovered filing metadata. All eight ratios match the author example, with
unrounded M approximately `-1.884184076741574`. A missing depreciation amount
returns a null score and flag. Neither example authenticates a historical source.

## Pair API

```python
from systematic_alpha_lab.factor_research.beneish_standard import annual_beneish

result = annual_beneish(current, previous)  # explicit chronological pair
```

Each mapping has flat canonical financial fields from the
[machine-readable contract](integrity-research-contract-v1.json), plus:

| Field | Contract |
| --- | --- |
| `entity_id` | Same nonempty stable issuer identifier |
| `fiscal_year` | Explicit adjacent integer fiscal years; not inferred from calendar dates |
| `period_type`, `flow_basis` | Both `annual` |
| `period_start`, `period_end` | Real full-year windows as `YYYY-MM-DD`; no inferred start |
| `currency` | Same documented currency |
| `unit_scale` | Same finite positive numeric scale, compared as exact decimal declarations |
| `reporting_scope`, `accounting_basis` | Same nonempty compatible declarations |
| `field_statuses` | Every required canonical field explicitly `verified_exact` |

There are 12 required current amounts and 10 prior amounts. Prior IBEI/CFO are
ignored and cannot make an otherwise valid pair fail. Both annual durations are
inclusive 330–400 days; year-end spacing is 330–400 days and current start is
exactly one day after prior end. The positive-input, margin and residual-asset
domain is the method's conservative SRG policy. All actual intermediate values
and denominators must also remain finite/nonzero. No epsilon, filling, automatic
absolute-value correction, neutral ratios or fitted transformation is applied.

`calculation_ready=true` and `standard_definition_satisfied=true` mean only that
the supplied amounts and **caller declarations** passed these checks. The result
also states `standard_definition_scope=supplied_declarations_only`,
`source_status=not_certified_by_calculator`, `timing_status=not_assessed` and
`research_ready=false`. Missing, invalid or unverified required inputs return
null score/flag with named reasons. Partial ratios never imply a valid score.

There is no default flag or probability. A literal `reference_screen=True`
enables the historical `M > -1.78` screen only for a valid pair. It remains a
reference screen, not fraud ground truth. Other nonboolean values are rejected.
This pair API cannot detect competing versions or duplicates outside its two
selected observations; the source selection layer must reject that ambiguity.

## Read pinned pipeline snapshots

```python
from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.factor_research.beneish_pipeline import review_annual_beneish_snapshots

reader = OfflineDataReader(closed_data_root)
result = review_annual_beneish_snapshots(
    reader,
    symbol="AAPL",
    snapshot_ids={
        "INCOME_STATEMENT": income_snapshot_id,
        "BALANCE_SHEET": balance_snapshot_id,
        "CASH_FLOW": cash_snapshot_id,
    },
)
```

Reads only `av_fundamentals_v1` / `annual`, through the existing shared reader.
There is no latest selection, normalization, collection, credential loading or
refresh. Provider, function and symbol must match the selected source; ambiguous
periods reject the read instead of expanding a join. Keep a union of observed
periods so incomplete statements remain visible. Prior CFO is not required for
the next year's 22-amount formula. All source hashes and the exact context hash
are recorded in the returned receipt. Source rows and declarations are immutable.

Without reviewed metadata, issuer identity, fiscal years, period starts, scales,
scope and field semantics stay unknown, and scores remain null. The adapter
never derives those declarations from ticker strings, period ends or raw
nonmissing values. Missing pure depreciation cannot use D&A, and missing
noncurrent debt cannot use total debt. Recognized provider missing markers
(`None`, `null`, empty) remain missing rather than becoming zero.

Optional context must be a JSON-compatible mapping with this structure:

```text
selection: the exact function -> snapshot_id mapping
periods:
  YYYY-MM-DD:
    entity_id, fiscal_year, period_start, unit_scale,
    reporting_scope, accounting_basis, flow_basis
    metadata_evidence: nonempty reference to the reviewed basis
field_mappings:
  each canonical field:
    status: verified_exact
    evidence: nonempty semantic-mapping reference
income_field: optional explicitly reviewed income-statement bridge field
```

The source supplies the period-end label, annual-table label and currency;
context cannot overwrite them. IS/BS currencies must agree and current CF must
agree with them. A stale context cannot move to different snapshots. Additional
periods and unknown canonical fields reject the context. `income_field` alone
cannot authenticate IBEI: its canonical semantic assertion/evidence is still
required. Other candidates are fixed to the method's named AV fields. Actual
mapping evidence must be reviewed outside this calculator; supplying a string
does not make it authentic. Historical availability remains unverified even
when all mathematical declarations pass.

For a private batch, prepare explicit JSON selection as
`symbol -> function -> snapshot_id`, then:

```bash
python examples/review_beneish_pipeline.py \
  --data-root /private/closed-snapshot-root \
  --selection /private/pinned-selection.json
```

Optional `--contexts` supplies a symbol-to-context mapping. Output contains source
receipts, scores or gaps; keep row-level outputs private. Exit `0` means each
requested issuer has at least one computable pair, still snapshot arithmetic;
`2` means a readable selection contains issuers with no computable pair; `1`
means selection/context/source-integrity rejection. Duplicate JSON keys and
nonfinite JSON constants reject selection/context input. No exit code certifies
historical research readiness.

## Verified real-source boundary

Only **after** the public and synthetic checks passed, the bridge read the closed
fresh AAPL/MSFT/IBM pilot: nine pinned statement snapshots, 60 aligned annual
observations, **zero strict computable scores**. Network access was blocked;
source file hashes and modification times were unchanged. The
[aggregate receipt](validation-annual-beneish-pipeline-2026-10-22.json) records
counts and rejection reasons. Exact snapshot IDs, observation times, source
hashes, raw amounts and local paths remain in private run records.

This is a successful read/rejection-path integration, not successful model-input
acceptance. Pure depreciation and noncurrent debt are missing; IBEI/trade mapping,
issuer, duration, scale and scope remain unverified. These gates are not waived.
The independent engineering chat is collecting the full current S&P 500; its
active catalog is not read by this validation. Full-universe evaluation requires
a closed, versioned handoff and separate coverage accounting.
