# Unified offline data access

`OfflineDataReader` reads existing Alpha Vantage and SEC snapshot materializations
through one interface. It does not collect data, construct a security mapping,
recalculate missing tables or certify a historical study. Collection and
normalization remain separate explicit operations.

## Select and pin the source

```python
from systematic_alpha_lab.data_pipeline import OfflineDataReader

reader = OfflineDataReader("/private/srg-data")
entries = reader.catalog(
    provider="alpha_vantage",
    request={
        "function": "TIME_SERIES_MONTHLY_ADJUSTED",
        "symbol": "MSFT",
        "access_mode": "user",
    },
)
# Inspect entries, then retain exact snapshot_id / normalizer / table in the
# research configuration. There is no automatic latest or nearest match.
```

`catalog` matches the complete provider request, including source mode. It returns
one entry per capture, normalizer and materialized table, ordered by observation,
capture ID, normalizer and table. Each entry includes source identity, observation
time, raw/table SHA256 and the manifest row count. An absent match returns an
empty list without a download or fallback to a public provider example. A source
capture with no normalized materialization also produces no entry.

Fundamental requests use their exact endpoint and provider symbol:
`{"function": "INCOME_STATEMENT", "symbol": "EXPLICIT_SYMBOL"}`. Annual and
quarterly tables are separate entries. SEC requests use an explicit source CIK,
for example `{"kind": "companyfacts", "cik": "0000000001"}`. A CIK identifies a
filer; a provider symbol identifies a provider request. The reader does not join
those identifiers or infer stable traded-security links.

```python
result = reader.read(
    snapshot_id=pinned_snapshot_id,
    normalizer=pinned_normalizer,
    table="monthly_prices",
    start="2020-01-01",
    end="2020-12-31",
    fields=["session_date", "adjusted_close", "adjusted_close_text"],
)
prices = result.frame
source = result.metadata
```

Both snapshot and normalizer are required even if only one version exists. A
missing capture, normalizer, table or field raises `KeyError`; the reader never
silently substitutes another version. Missing root/catalog/object files raise
`FileNotFoundError`. Invalid identities, hashes, manifest dependencies, escaping
paths and date contracts raise `ValueError`. Underlying malformed SQLite or
Parquet data can also raise its library's validation error.

## Calendar labels, projection and missingness

Date bounds are inclusive `YYYY-MM-DD` calendar labels. The reader preserves
empty ranges and does not return the unfiltered source when a range is empty.
Filtering uses the following explicit column map:

| Table | Calendar-label column |
| --- | --- |
| `monthly_prices` | `session_date` |
| `annual`, `quarterly`, `annual_review`, `quarterly_review` | `period_end` |
| `reconciliation`, `source_reconciliation`, `facts` | `period_end` |
| `filings` | `filing_date` |

Tables without a declared date column, such as batch `coverage`, can be read
without date bounds. A bounded read of those tables raises. Missing date labels
remain in an unbounded result, and are excluded when they cannot satisfy an
explicit bound. No expected frequency or missing calendar periods are inferred.
Fiscal dates do not become publication dates. Filing dates do not become public
dissemination timestamps. A date-limited read is not an as-of availability query.

Projection preserves requested column order. All source values, amount strings,
dtypes and existing missing values are retained without automatic numeric,
currency or fiscal-period conversion. The returned frame belongs to the caller;
mutating it cannot change a later read. `missingness` counts structural pandas
nulls in returned fields; it does not reclassify strings such as `"None"` or
validate an accounting field's economic meaning.

Complete provenance remains in `metadata` even when projected columns exclude
source columns. Metadata includes:

- Capture/provider/request/normalizer/table identities and observation time;
  raw/table hashes and a canonical manifest digest.
- Full derivation provenance and verified source-dependency identities.
- `source_rows`, `returned_rows`, `date_column`, source/returned date bounds,
  the requested range and missing-date counts.
- Field missingness and supplied availability/stable-ID/calculation-ready counts.
- `readiness.status = "not_certified"` for every result, including empty results.

A nonmissing `available_at` or arithmetic-ready flag does not by itself establish
original vintages, historical membership, effective-dated security links,
delisting-inclusive returns, historical controls or an execution calendar. The
[financial-quality research gate](financial-quality-study.md) remains unchanged.

## Integrity and read-only boundary

The reader opens an existing quiescent SQLite catalog with `mode=ro`,
`immutable=1` and `PRAGMA query_only=ON`; it creates neither the data root nor
journal files. Do not run a collector or mutate the selected root concurrently
with a read. Use separate closed snapshot copies if collection must run in
parallel. The reader is a local reference interface, not a concurrent warehouse.

It checks catalog request hashes, capture/manifest identity, raw and normalized
object hashes, every declared table's Parquet row count and the selected table's
explicit source columns. Known derived normalizer IDs must bind their complete
provenance digest, and their required source-dependency roles cannot be omitted.
Embedded source manifests must exactly match their registered catalog versions.
Declared `input_snapshots` dependencies, including SEC submissions/history, are
resolved by exact capture ID and checked against their recorded hashes/times.
Relative object paths must resolve to files inside the selected root; absolute
paths, parent traversal and symlinks escaping that root are rejected. The table
is parsed from the same bytes whose hash was verified.

These checks detect inconsistent stored evidence. Catalogs and manifests are not
cryptographically authenticated external receipts, and the reader cannot discover
undeclared dependencies, certify provider definitions or reconstruct information
that was not captured. Preserve independent input receipts and source evidence.

Importing the offline entrypoints does not load collection or credential clients.
Legacy package entrypoints are loaded on demand to retain existing imports.
There are no credential, network, write, TTL-expiry or refresh arguments on this
API. A desired refresh must explicitly use the existing
[fundamental](data-snapshot-pipeline.md), [monthly-price](monthly-price-snapshots.md)
or [SEC](sec-filing-snapshots.md) ingestion path; a new capture is then selected
and pinned independently.

## Synthetic example

```bash
PYTHONPATH=src python examples/offline_data_access_demo.py
```

The example prepares synthetic data in a temporary directory and reads it through
this interface. It uses no network, credentials or private research inputs.
