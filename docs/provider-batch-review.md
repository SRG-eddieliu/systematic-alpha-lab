# Offline multi-company statement diagnostics

`review_fundamental_batch` extends the [quarterly review](provider-quarterly-review.md)
to an explicitly declared company sample. It reuses cached Alpha Vantage
statements and their existing annual/TTM arithmetic. It makes no network requests
and does not require SEC input.

## Selection and output

The complete selection is frozen before computation. By default, each statement
uses its latest locally observed capture. A returned `selection` maps every
requested symbol and statement to its exact snapshot ID, or `null` when absent.
Pass that selection back to replay the same inputs after newer captures arrive.
Pinned missing IDs and `null` entries never fall back to a newer capture.

Each company is reviewed independently. Combined annual and quarterly tables
have grain `(provider_symbol, period_end)`; reconciliation adds `source_function`.
The batch never pools money, converts currencies, fills another company's gaps,
or infers fiscal-quarter labels from calendar months.

Coverage contains one row for **every requested symbol**, with:

- `review_ready`, `missing_captures` or `source_rejected` status;
- annual/quarterly row counts and arithmetic candidate counts;
- comparable cross-statement income counts and observed differences;
- first/last quarterly dates, observed annual endpoint months and currencies.

Counts for missing or rejected sources remain null, rather than pretending the
company has zero observations. Observed endpoint months are descriptive: a
52/53-week calendar can move an endpoint into an adjacent calendar month.

Missing files, source-contract rejection and raw/derived hash failures quarantine
the affected company. Error receipts use fixed status codes and exclude exception
text or provider bodies. Unexpected programming errors still fail the workflow.
Accepted company tables retain all underlying source/assumption/timing flags.

A successful aggregate publishes immutable `coverage`, `annual_review`,
`quarterly_review` and `reconciliation` Parquet tables. Its version binds the full
selection, company manifests, coverage outcomes and batch source hash. Replay
revalidates dependencies before checking the combined table hashes. If no company
is usable, the returned receipt has no aggregate manifest; preserve that receipt
to retain the unsuccessful selection.

## Run

```bash
# Three explicitly synthetic calendars and exact replay; no credentials/network.
PYTHONPATH=src python examples/av_batch_review_demo.py

# Diagnose existing captures, regardless of the collection cache's freshness TTL.
# Keep all real-data receipts and derived tables outside this repository.
PYTHONPATH=src python examples/review_fundamental_batch.py \
  --data-root /path/to/private/srg-data --symbols IBM MSFT AAPL \
  > /path/to/private/three-company-review.json

# Pin all original captures, including absent inputs. This never downloads.
PYTHONPATH=src python examples/review_fundamental_batch.py \
  --data-root /path/to/private/srg-data \
  --replay-receipt /path/to/private/three-company-review.json
```

CLI exit statuses are `0` for a complete diagnostic sample, `2` for a partial
sample and `1` for no usable company or an invalid request. Complete means source
review succeeded; it does **not** mean all arithmetic windows are populated or
that any result is historically tradable. Inspect per-company coverage.

When private credentials are available, the existing bounded collector can add
two further companies with at most six requests before the offline review:

```bash
PYTHONPATH=src python examples/ingest_fundamental_snapshots.py \
  --data-root /path/to/private/srg-data --symbols MSFT AAPL \
  --credentials /path/to/local/credential.yml --key-slot alphavantage_api_paid \
  --max-requests 6
```

The collector preflights the full budget, reuses fresh caches and stops on
provider failure without retries or key rotation. An older cached IBM capture
can be reviewed without refreshing it. Different capture times remain visible in
the selected source manifests; this batch is not a synchronized as-of panel.

## Verified scope and pending live work

The runnable synthetic sample covers December, June and weekly year-end dates,
including a 371-day/53-week annual interval. Regression tests cover company and
currency isolation, gaps, currency transitions, missing sources, pinned replay
after new observations, cross-company/statement misselection, source corruption,
combined-table corruption and CLI status handling.

Local verification: **287 tests passed**, including **24 batch cases**, on
Python 3.12.14, pandas 2.2.3 and pyarrow 26.0.0. Both the batch demo and consolidated
import demo passed; the batch demo verified exact replay with zero network calls.
Hosted Python 3.10/3.11 verification is tracked separately by the pull request.

This change has **not** collected or evaluated a new real-company sample. The
execution environment does not have the earlier private Alpha Vantage snapshots
or credential file. The real expansion commands above remain to be executed
where those inputs are available. Prior IBM results are not rerun or re-certified
by the synthetic checks here.

All candidates retain unknown historical `available_at`, unverified provider
amount-scale/quarterly-flow assumptions and unmapped provider symbols. This
convenience sample establishes pipeline behavior, not an investible historical
universe or evidence of alpha. Returns, IC and portfolio tests remain pending.
