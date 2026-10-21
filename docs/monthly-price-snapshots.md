# Monthly adjusted-price snapshots

`monthly_price_snapshots` adds a bounded Alpha Vantage price path to the shared
raw JSON, SQLite and Parquet store. It supports one-month research inputs without
requiring WRDS or a daily endpoint. It supplies snapshot diagnostics; historical
financial availability, universe membership and security linking remain separate
requirements before the financial-quality market study can run.

## Source and arithmetic contract

The only endpoint is `TIME_SERIES_MONTHLY_ADJUSTED`. Requests contain an explicit
provider symbol and source mode. Source metadata must match the symbol, specify
a recognized market timezone and agree with the latest row's calendar date.
Each month has exactly one row with complete OHLC, adjusted close, volume and
dividend fields. Source amount strings are retained alongside finite numeric
values; invalid prices, volumes, OHLC ranges, dates, JSON duplicates and provider
notices are rejected. Collection validates before committing a capture.

A monthly date is a calendar label. It does not establish an exact market close
or publication timestamp. The latest source month stays unconfirmed even if a
later retrieval date falls in another month: only an observation containing a
later source month confirms it. Both source and observation months are checked
in the declared market timezone. This conservative policy can omit a recently
closed month until a new source month arrives.

`adjusted_close_change_1m` is current adjusted close / preceding adjusted close
minus one. Both endpoints must be confirmed closed months and exactly one month
apart. Missing months are never bridged. `forward_adjusted_close_change_1m`
belongs to the preceding row and retains explicit start/end dates. The dividend
field is preserved, not added again to an already adjusted-close ratio.

These are provider-adjusted changes, not certified delisting-inclusive total
returns. The provider's historical adjustment vintage is unverified. Currency
and stable security ID remain missing; a ticker is not silently mapped to a
historical security or joined to SEC filings. `available_at` remains missing.
No IC, portfolio return or historical eligibility result is produced here.

## Source modes and replay

`user` captures require the existing private credential. `public_demo` is the
official IBM-only provider example and has a distinct cache identity plus an
explicit sample label. It cannot satisfy a user-source cache request. There is
no automatic fallback from a failed user request to a public example.

The whole request budget and cache availability are checked before network
calls. Notices and errors stop collection without retry or credential rotation.
Only the official endpoint receives the credential, redirects are disabled,
and errors omit response bodies and request URLs. No credential belongs in raw
payloads, request metadata, manifests or Git.

Exact replay resolves fixed capture IDs, verifies catalog identity and raw and
Parquet hashes, and makes no request. The derivation identity binds the adapter
source, source request, observation time and month/return policies. Original
captures and prior derivations remain immutable.

## Run

```bash
# Synthetic arithmetic and replay check, with no credentials or network.
PYTHONPATH=src python examples/monthly_price_snapshot_demo.py

# Existing private credential via ALPHAVANTAGE_API_KEY, or use
# --credentials /private/credential.yml --key-slot YOUR_EXISTING_SLOT.
PYTHONPATH=src python examples/ingest_monthly_price_snapshots.py \
  --data-root /private/monthly-data --symbols MSFT AAPL --max-requests 2

# Separate official provider example; does not use a private credential.
PYTHONPATH=src python examples/ingest_monthly_price_snapshots.py \
  --data-root /private/monthly-example --symbols IBM --public-demo --max-requests 1

# Exact pinned replay, independent of the current cache age or credentials.
PYTHONPATH=src python examples/ingest_monthly_price_snapshots.py \
  --data-root /private/monthly-data --snapshot-ids SNAPSHOT_ID
```

Provider source contracts: [monthly adjusted API](https://www.alphavantage.co/documentation/#monthlyadj)
and [adjustment methodology FAQ](https://www.alphavantage.co/support/).
All public arithmetic fixtures are synthetic. Live observations, coverage and
validation evidence stay in private research artifacts.
