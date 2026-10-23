# Supplemental financial statement candidates

Alpha Vantage remains the primary financial-statement source. Supplemental
observations have separate providers, snapshots and normalizers; they do not
replace an AV observation or fill a research field automatically. The existing
[failure-recovery version](statement-failure-recovery.md) remains separate.

The first pilot is bounded to at most three explicit companies, each with two
adjacent actual fiscal-year periods. SEC filings and issuer disclosures supply
the accounting evidence needed to accept a field. Yahoo Finance, accessed
through yfinance, supplies quick candidates for comparison. WRDS access is not a
prerequisite; no paid service is purchased by this workflow.

## Captured evidence

The optional `yahoo` extra pins yfinance 1.7.0. Its financials implementation
casts DataFrame columns to floats and discards parts of the response metadata.
The two capture layers are therefore distinct:

| Provider / normalizer | Evidence preserved | Limits |
| --- | --- | --- |
| `yahoo_financial_timeseries` / `yf_timeseries_cells_v1` | Exact successful financial JSON response bytes, source symbol/type, observation values and supplied per-observation currency/period labels | No inferred issuer bridge, period start, unit scale, accounting scope or original filing vintage |
| `yahoo_yfinance_dataframe` / `yf_statement_cells_v1` | Library-returned ordered axes, dtypes, shape and typed cells, package version and call timestamps; dependencies on captured financial responses | Exact preservation starts at the returned DataFrame; earlier parser precision loss cannot be reversed |
| `supplement_research_contract` / `yf_pilot_capture_v1` | Explicit target/definition contract and complete capture manifests | Execution and integrity evidence only; zero accepted research fields |
| `original_financial_document` / `original_document_bytes_v1` | Exact HTML/PDF bytes inside a declared base64 JSON envelope, original media type/content hash, URL and proposed filing version | The envelope is not the HTTP body; issuer-link, filing-version and accounting-context acceptance remain unreviewed |

Integers use decimal text and finite floats use reversible hexadecimal text in
the DataFrame layer. Missing types, negative zero, duplicate axis labels and
ordering are preserved. Default DataFrame JSON conversion is not used. Raw
financial JSON and its integer types remain available independently.

The collector calls `get_income_stmt`, `get_balance_sheet` and `get_cash_flow`
once per company with `as_dict=False`, `pretty=False`, `freq="yearly"`.
yfinance offers no two-year bound on these getters. Complete returns are saved;
only the two explicitly contracted years are in the pilot's analysis scope.
Returned source dates are never silently remapped to actual fiscal dates.

The SDK may split a getter into requests or change its cookie strategy. A
separate session dispatch counter has a hard ceiling of 40, enforces spacing,
and stops on blocking transport/authentication/rate/schema conditions. This
counter describes observed session dispatches, not a claim about unobserved
network infrastructure. Cookie/crumb/authentication bodies and request query
strings are excluded from the evidence package. Partial results remain partial;
the command does not retry or resume a previous root.

`original_documents.collect_original_documents` separately accepts an explicit
list of approved report URLs and a request budget of at most eight. SEC Archives
requests require an existing authorized organization/contact configuration;
missing configuration produces an explicit zero-dispatch outcome. Planned
issuer-hosted reports can proceed independently. Documents stream under a
30 MiB limit, and redirects or first transport/status failures stop collection.
The `document` table exposes the exact encoded bytes for offline verification;
this adapter does not interpret accounting facts.

## Explicit execution

Prepare a private JSON plan containing `schema_version: 1`, a nonempty
`research_contract` object, and `targets`. Each target declares `symbol`, a
ten-digit `cik`, `company_ref`, and exactly two `periods` in chronological order.
Each period has integer `fiscal_year` and actual ISO `start`/`end`. The second
year must start on the day after the first ends. The validator checks this
execution bound; it does not authenticate an issuer or approve an accounting
definition.

```bash
python -m pip install -e '.[yahoo]'
python examples/yfinance_statement_pilot.py \
  --plan /private/approved-pilot-plan.json \
  --data-root /private/new-yahoo-pilot \
  --code-commit "$(git rev-parse HEAD)" \
  --max-session-requests 40
```

Use a fresh process and a new private output directory. The plan must be fixed
before online execution. No provider data, credentials or private contracts
belong in this repository.

After capture, the same `OfflineDataReader.catalog/read` interface reads the
fixed normalized tables. The pilot verifier checks every receipt table and its
complete manifest, raw dependencies, contract hash and rejected-response hashes:

```bash
python examples/yfinance_statement_pilot.py \
  --data-root /private/new-yahoo-pilot --offline
```

Offline verification does not construct a collector or writable store, import
yfinance, read credentials, select `latest`, or fetch missing materializations.

`supplement_candidate_audit.build_pilot_candidate_audit` is a pure offline
presence audit for the separately frozen research contract. It returns all
59 native alternative fields across six target issuer-periods (354 cells), a
five-concept by six-period review queue (30 rows), and an exclusion ledger for
source rows outside the exact target ends. Missing sources keep their full
denominator. Every cell separates value presence, exact end alignment, unknown
flow start, annual/TTM label, units/scope and review status. Alternative fields
are not all required scoring inputs. Duplicate candidates remain ambiguous;
no field is selected or accepted by this audit.

## Research acceptance

Research must compare company identity, actual duration/instant, currency, unit
scale, accounting/lease/discontinued-operation scope and filing version before
accepting a candidate. A current quote currency is not historical statement
currency. A same-named field is not a definition match. Missing/ambiguous facts
and unaligned period labels remain explicit gaps. Conflicting observations keep
both pins; there is no `fillna`, zero substitution, date fuzzing or automatic
score calculation. Valid, accepted nonmissing AV values retain priority.

Engineering capture integrity, research field acceptance, historical timing and
backup recovery are separate checks. These adapters do not change the frozen
Beneish calculation contract or its source acceptance policy.

Implementation references: [pinned yfinance financials source](https://github.com/ranaroussi/yfinance/blob/3d9d2f0cacb662bff689874cd6113bae3a30a885/yfinance/scrapers/fundamentals.py),
[annual getter API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_income_stmt.html),
[SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
