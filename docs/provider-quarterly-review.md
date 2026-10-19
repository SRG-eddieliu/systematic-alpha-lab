# Provider-only quarterly financial-quality diagnostics

For an explicit multi-company sample and exact capture replay, use the
[offline batch review](provider-batch-review.md). It preserves company isolation
and reports missing or rejected sources without silently reducing the sample.

The [statement review](provider-statement-review.md) now includes a quarterly TTM
path using existing Alpha Vantage captures. The provider's
[documentation](https://www.alphavantage.co/documentation/) describes annual and
quarterly financial reports. This adapter uses the `quarterlyReports` arrays as
quarterly flows under an explicit unverified source assumption. It requires no
SEC input, new download, contact identity or credentials.

## Calculation

`accrual_from_quarterly_flows` computes the protocol's arithmetic:

`-(sum of four quarterly net-income values - sum of four quarterly operating-cash-flow values) / average assets at t and t-4`.

Income comes from the income statement, operating cash flow from the cash-flow
statement and assets from the balance sheet. Both flows are already quarterly;
the adapter does not run the separate YTD conversion routine on them. Missing
quarters are not reconstructed from annual statements.

Four reported flow observations need three consecutive date intervals. The
denominator needs five observations/four intervals, with positive opening and
closing assets. Each interval must be 60–120 days and the four-interval span must
be 330–400 days. Currency and unit must agree within the relevant window. The
rules accommodate observed noncalendar reporting dates without inventing fiscal
year or quarter labels; they do not prove a source's true duration definitions.

Missing values, currency changes, gaps and invalid assets leave affected ratios
missing. Windows recover when enough valid consecutive observations exist.
Malformed/infinite input amounts are rejected and non-finite output arithmetic
is not emitted as a usable ratio. Source series are isolated from one another.

## Source checks and output contract

`review_quarterly_snapshots(store, records)` verifies the three source captures and
their existing annual review, aligns all quarterly dates with outer joins and
publishes immutable `quarterly_review` and `source_reconciliation` Parquet tables.
Unmatched dates remain visible. A row without consistent currencies across all
three statements is excluded from the calculation and explicitly marked in the
output; it is not assigned a fabricated currency.

The quarterly table includes raw amount strings, calculation inputs, TTM sums,
average assets, the ratio, window/readiness flags and source checks:

- Net-income differences between the income and cash-flow statements, with
  exact decimal differences retained. Different definitions, revisions or source
  mapping remain possible causes; none is assumed or automatically corrected.
- Counts of comparable net-income fields and observed differences over the same
  four accepted rows used by the arithmetic. A missing comparison is not evidence
  that the source fields agree. Extra unmatched dates cannot displace a quarter
  in these counts.
- Annual/quarterly reconciliation status at each observed annual endpoint. Other
  dates are labelled `not_annual_endpoint`; annual reconciliation does not fill
  or change quarterly values.

`calculation_ready` describes arithmetic coverage only. Every result retains an
unmapped provider identifier, `provider_common_scale_assumption_unverified`,
`provider_quarterly_flow_assumption_unverified`, missing `available_at` and
`snapshot_only_availability_unverified`. A source-field difference does not by
itself disable candidate arithmetic or establish that the provider is wrong.

This connects current provider snapshots to the existing TTM calculation. It
does not authenticate historical statement vintages, prove publication times,
construct an investible universe or compute any return/IC/portfolio result.
Those remain separate from the [market study](financial-quality-study.md).

## Reproduce

```bash
# Annual and quarterly synthetic diagnostics; no network or credentials.
PYTHONPATH=src python examples/av_statement_review_demo.py

# Quarterly review of three existing captures; no network or credentials.
PYTHONPATH=src python examples/review_fundamental_snapshots.py \
  --data-root /path/to/private/srg-data --symbol YOUR_SYMBOL --period quarterly
```

The default CLI period remains `annual`. Each quarterly manifest binds the
annual/source manifests, selected observations, adapter source, arithmetic source,
formula, spacing rules and flow/unit assumptions. Replay verifies all dependencies
and derived hashes. Actual provider data and receipts stay private; public tests
and the runnable demo use synthetic inputs only.

The full local suite passes **263 cases**, including **25 new quarterly cases**.
They cover direct-flow versus explicit YTD arithmetic, gaps, noncalendar dates,
currency/unit transitions, missing values, source isolation, future mutation,
unmatched dates, comparison coverage, overflow and cache corruption.
