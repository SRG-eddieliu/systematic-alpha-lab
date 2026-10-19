# SEC quarterly snapshot diagnostics

`review_sec_quarterly_snapshots` connects strictly verified SEC captures to the
existing quarterly/TTM arithmetic. It reads fixed snapshot IDs, makes no requests,
and retains the source normalizer's filing-date/form conflict rejection.

## Source and duration policy

Use one filer's `us-gaap` Assets, NetIncomeLoss and operating-cash-flow concepts,
with an explicitly selected monetary unit. Original 10-Q/10-K filings at or after
the chosen reporting boundary define the default rows. Amendments are excluded
by default. Multiple filings for one report end are rejected rather than choosing
a version.

For a separately reviewed scenario, supply `filing_accessions` as the complete
list of accessions to include, replacing an original with a specifically reviewed
amendment where appropriate. This list is not an overlay on the default rows.
Every entry must exist, be unique, carry 10-Q/10-K/10-Q/A/10-K/A and have a valid
report date at or after the boundary. Two accessions for one report end are
rejected. No latest-amendment choice or classification of an amendment's purpose
is automated; that assessment requires original source evidence.

Fiscal year and quarter come only from fact metadata in the filing's own report
period. Calendar month and comparative facts never assign fiscal labels. A 10-K
must carry FY, a 10-Q Q1/Q2/Q3; explicitly selected amendments use the same
underlying form check and keep their full amendment form in the output.
Missing/ambiguous labels stay missing.

For each accession, unit and report end:

- A single reported 60–120-day flow is preferred as the quarter value. It is
  never differenced as YTD again. Ambiguous reported quarters are not deduplicated
  or replaced with a derived alternative.
- Select YTD durations explicitly: 60–120, 140–220, 230–310 and 330–400 days for
  Q1, Q2, Q3 and FY. These bounds check source labels; they do not infer them.
- If no reported cash-flow quarter exists, Q2/Q3 can use current YTD minus the
  immediately preceding selected filing's YTD. Q4 income/cash flow can use annual
  minus Q3 YTD. Fiscal year, fiscal start, quarter adjacency, unit and 60–120-day
  endpoint spacing must agree. Missing context/filing/start agreement blocks the
  difference; a new year's Q1 never subtracts the preceding annual value.
- Where an adjacent boundary exists, a reported quarter must start exactly one
  day after it. The rejected quarter is not silently reconstructed from YTD.
- Values, duration starts, basis labels and both accessions for each difference
  remain in the output. If both a reported quarter and a valid cross-filing YTD
  difference exist, their exact difference is retained without replacing either.

TTM uses four quarterly flows and beginning/end assets across five consecutive
observations. Both the existing date/unit rules and every fiscal-quarter label
transition must pass. Missing values, gaps or nonpositive assets leave affected
ratios missing; later complete windows can recover.

`selection_policy` and `filing_is_amendment` identify each selected source.
`quarter_input_involves_amendment` also flags a previous amendment used in a YTD
difference. `ttm_amendment_input_involved` flags amendments in the four quarter
inputs or opening assets; it is unknown for unavailable calculation windows.
The source `filing_date` is retained when present. An amendment never inherits
the original filing's date or availability time.
The operating-cash-flow concept stays exact: a continuing-operations concept is
not substituted for total operating cash flow.

## Snapshot limitation

Cash-flow differencing across filings can mix revised financial bases. All results
retain `current_aggregate_cross_filing_vintages_unverified`, missing `available_at`
and a snapshot-only timing label. A difference between a reported quarter and
cross-filing YTD arithmetic is a source/vintage diagnostic, not proof of an error.
Current companyfacts aggregates and acceptance metadata do not reconstruct an
original filing vintage or establish historical trading availability. No returns,
IC, universe construction or portfolio result is produced here.

The normalizer binds source manifests, requested unit/boundary, the sorted explicit
accession list (or the original-only default), adapter source,
calculation source and version policy. Replay verifies raw, staged and derived
hashes. A filing-date disagreement remains a hard source gate even when one date
seems plausible under general after-hours filing rules; resolving it requires
specific source evidence and a separately recorded policy.

## Run

```bash
# Explicitly synthetic, no credentials or network.
PYTHONPATH=src python examples/sec_quarterly_review_demo.py

# Exact captures returned by the SEC collector; all outputs stay private.
PYTHONPATH=src python examples/review_sec_quarterly_snapshots.py \
  --data-root /path/to/private/sec-data \
  --facts-snapshot FACTS_ID --submissions-snapshot SUBMISSIONS_ID \
  --history-snapshots HISTORY_ID_1 HISTORY_ID_2

# Optional separately reviewed scenario: JSON array with every selected accession.
# Add --filing-accessions-file /path/to/private/selected-accessions.json
```

Public tests and examples contain synthetic entities only. Actual source
captures, company-level coverage and conflict evidence are kept in private
research artifacts.
