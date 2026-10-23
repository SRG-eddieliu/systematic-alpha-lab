# BXP and current-DOC statement availability

Alpha Vantage remains the primary source. This follow-up targets its six still-
failed jobs: income statement, balance sheet and cash flow for BXP and current
DOC. The original AV failures, requests and receipts remain unchanged. Separate
supplemental evidence records what Yahoo can supply; no AV input is overwritten
and no accounting field is accepted automatically.

This change is stacked on [PR 22](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/22),
which supplies the earlier [supplemental candidate pipeline](supplemental-financial-pilot.md).
Its scope is separate from that pilot's three-company, two-year candidate-field
audit. Review this follow-up against the PR 22 branch. The previously captured
v1 collector and normalizer source bytes remain fixed; annual/quarterly support
uses new modules and normalizer names. Neither change implies approval to merge
either pull request.

## Fixed execution contract

The public [availability contract](bxp-doc-statement-availability-contract.json)
defines the complete denominator before collection:

- Exactly `BXP` and current `DOC`, with the contract's explicit current issuer
  declarations; no additional ticker discovery or historical ticker stitching.
- `get_income_stmt`, `get_balance_sheet` and `get_cash_flow`, each once with
  `as_dict=False`, `pretty=False`, at both `freq="yearly"` and
  `freq="quarterly"`: twelve logical jobs in total.
- All six yearly jobs precede the six quarterly jobs in one fresh process and
  one bounded session. All twelve jobs remain in `planned_jobs`, including
  `not_attempted` entries after a stop.
- Full native getter responses are retained. Finite provider history is not
  equivalent to AV's historical range. No statement start date, missing quarter,
  currency or unit is inferred from an annual/quarterly request.
- Any optional original-report capture supports identity and scope review. It
  does not interpret or certify financial fields.

The known terminal dispatch ceiling is **32**: **3 prior issuer-listing
connection attempts + at most 27 new Yahoo session dispatches + at most 2 new
original-report dispatches**. Failed connections and authentication count.
The Yahoo collector's reusable API permits at most 32, but **this contract calls
it with `max_session_requests=27`** to preserve the other allocations. Unused
budget does not authorize extra getters, retries or discovery requests.

Automatic retries are zero, redirects are disabled, and the next session
dispatch waits at least two seconds after the preceding response or transport
error finishes. The inherited guard blocks SDK chunk/cookie fallback after a
financial failure, including failures that the SDK catches internally.

These are instrumented provider/issuer session dispatch counts. Web identity
discovery calls and backend wire exchanges have separately unknown counts.
The ceiling is not a global HTTP, TCP or wire-request claim. SEC requests use
only an existing authorized contact configuration; absence of that configuration
means zero SEC dispatches, rather than an invented contact.

## APIs and evidence layers

| Entry point | Explicit inputs and output |
| --- | --- |
| `yfinance_statement_collection_v2.collect_statement_availability` | The exact two-symbol plan, `max_session_requests=27`, and `min_interval_seconds=2`; returns the full plan, attempted jobs, same-call HTTP bodies, library frames and safe transport observations |
| `yfinance_statement_snapshots_v2.capture_statement_http` | Already received `body` bytes, `symbol`, `statement`, `frequency`, `observed_at` and optional `contract_sha256`; returns an exact `record` and normalized `manifest` |
| `yfinance_statement_snapshots_v2.capture_statement_frame` | Already returned `frame`, `symbol`, `method`, `frequency`, `yfinance_version`, `started_at`, `finished_at`, matching `http_records` and optional `contract_sha256`; returns its own `record` and `manifest` |
| `replay_statement_http` / `replay_statement_frame` | An existing `SnapshotStore` and exact registered record; checks source/helper/policy pins and reuses or materializes that version without fetching |
| `OfflineDataReader.read` | Exact `snapshot_id`, `normalizer` and `table`; reads a closed root and verifies its complete raw/manifest dependencies |
| `statement_availability.build_gap_coverage` | The fixed contract, exact source facts/pins, six unchanged failed primary jobs and all twelve planned logical jobs; returns `coverage` and `periods` tables |

All API modules above live under `systematic_alpha_lab.data_pipeline`.
Statement names are `income`, `balance-sheet` and `cash-flow`. The new request
schemas retain `frequency="yearly"` or `"quarterly"`; only the expected Yahoo
metric prefix maps yearly to `annual`. Quarterly bytes are never rewritten as
annual data.

| Provider | New normalizer | Preserved evidence |
| --- | --- | --- |
| `yahoo_financial_timeseries` | `yf_statement_http_v2` | Exact successful financial JSON bytes; original number tokens/types, item JSON, supplied currency and period labels; `facts` and `audit` tables |
| `yahoo_yfinance_dataframe` | `yf_statement_frames_v2` | Returned ordered axes, dtypes, matrix shape and typed cells, plus exact same-call HTTP dependencies; `facts` and `audit` tables |

The DataFrame is the library representation. Precision already lost by its
parser cannot be recovered from that frame; exact HTTP numbers remain separate.
Frame values use typed strings, including reversible float hexadecimal values.
Missing values, explicit zero, omitted fields and unknown metadata remain
distinct. A metadata-only metric is an unknown observation, not a fabricated
zero.

Every stored frame in this collection must have nonempty matching HTTP records
for the same symbol, statement, frequency, contract and call interval. The
general offline frame API can label an unattached frame `not_captured` and
unverified; that branch does not meet this collection's raw-plus-frame rule.
Valid financial raw bytes remain available if SDK frame construction later
fails. Safe financial JSON schema diagnostics are retained separately from
successful datasets. Authentication, cookie, crumb, HTML and non-200 bodies are
withheld; credential echoes are withheld as well. Logs exclude full URLs,
query strings and provider exception text.

Use the pinned optional yfinance 1.7.0 runtime in a fresh process. The collector
checks the frozen transport and financial-scraper source dependencies, isolates
cookie/timezone/ISIN caches in a temporary directory, and cleans them up at
shutdown. An already initialized SDK singleton/cache is rejected. Collection
and offline reading must operate on separate roots or at separate times after
the writer has stopped.

### Synthetic offline round trip

This fixture does not import yfinance or contact a provider. Its symbol, dates
and value are synthetic. Production inputs come from the bounded collector's
same-call returns, and their actual receipts remain private.

```python
import json
from tempfile import TemporaryDirectory

import pandas as pd

from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.data_pipeline.yfinance_statement_snapshots_v2 import (
    FRAME_NORMALIZER,
    HTTP_NORMALIZER,
    capture_statement_frame,
    capture_statement_http,
)

body = json.dumps({"timeseries": {"error": None, "result": [{
    "meta": {"symbol": ["SYNTH"], "type": ["quarterlyNetIncome"]},
    "quarterlyNetIncome": [{
        "asOfDate": "1999-12-31", "periodType": "3M",
        "reportedValue": {"raw": 42},
    }],
}]}}).encode()

with TemporaryDirectory() as demo_root:
    store = SnapshotStore(demo_root)
    raw = capture_statement_http(
        store, symbol="SYNTH", statement="income", frequency="quarterly",
        body=body, observed_at="2000-01-02T00:00:01Z",
    )
    frame = pd.DataFrame([[42.0]], index=["NetIncome"],
                         columns=[pd.Timestamp("1999-12-31")])
    derived = capture_statement_frame(
        store, frame, symbol="SYNTH", method="get_income_stmt",
        frequency="quarterly", yfinance_version="1.7.0",
        started_at="2000-01-02T00:00:00Z",
        finished_at="2000-01-02T00:00:02Z",
        http_records=[raw["record"]],
    )

    # Writes are finished before constructing the read-only reader.
    reader = OfflineDataReader(demo_root)
    source = reader.read(snapshot_id=raw["record"]["id"],
                         normalizer=HTTP_NORMALIZER, table="facts")
    cells = reader.read(snapshot_id=derived["record"]["id"],
                        normalizer=FRAME_NORMALIZER, table="facts")
    assert source.frame.source_frequency.eq("quarterly").all()
    assert cells.frame.source_frequency.eq("quarterly").all()
```

No `latest` lookup, refresh, credential access or SDK call occurs in this
offline read. Replay requires the original source/helper/policy versions;
changing those pins requires a separately reviewed normalizer version.

## Availability is a presence threshold

Readability means at least one numeric source fact. The stronger native-core
presence threshold checks the contract's target annual end with source
`periodType="12M"`, plus a sufficiently recent quarterly end with
`periodType="3M"`. Each native probe must occur once as a finite number at the
same source end:

| Statement | Native presence probes |
| --- | --- |
| Income | `TotalRevenue`, `NetIncome` |
| Balance sheet | `TotalAssets`, `TotalLiabilitiesNetMinorityInterest` |
| Cash flow | `OperatingCashFlow`, `InvestingCashFlow`, `FinancingCashFlow` |

A finite explicit zero counts as presence; no missing value is replaced with
zero. Source labels `12M` and `3M` do not prove an actual flow start/duration.
Balance-sheet end observations remain distinct from flow contexts. Missing,
repeated, wrong-frequency or out-of-window candidates remain explicit gaps.

Passing these probes does not establish a complete statement, all required
research inputs, source-history parity, issuer history, unit/currency
compatibility or accounting-definition equivalence. No annual-minus-YTD
quarter construction, field substitution, factor or score calculation is
performed. Accounting field acceptance remains zero and semantic review
remains unreviewed.

## Current issuer boundaries

`BXP` is the contract-declared **BXP, Inc.**, CIK `0001037540`. Its combined
reporting package also contains Boston Properties Limited Partnership; the
corporate and partnership financial statements must be distinguished. A
matching provider ticker alone does not settle that accounting scope.

Current `DOC` is **Healthpeak Properties, Inc.**, CIK `0000765880`, rather than
the former DOC issuer Physicians Realty Trust, CIK `0001574540`. The merger,
earlier holding-company reorganization and ticker change leave historical
issuer/scope bridges unreviewed. Do not stitch former-DOC histories into current
DOC from a ticker match. Exact identity and filing references are retained in
the public contract; period-level historical binding still requires review.

## Execution results

The completed capture returned all **12 logical jobs**, with **12 exact HTTP
financial responses** and **12 typed library DataFrames**. It used **14 Yahoo
session dispatches: 12 financial and 2 authentication**, with zero retries,
redirects or new AV requests. The HTTP facts contain **3,045 numeric source
observations**. These are source metric/period rows, not accepted fields or a
count of complete statements.

All six supplemental availability decisions pass the native-core presence rule
for the contracted annual target and a recent quarterly source end. Source end
label coverage is:

| Source | Annual source end labels per statement | Quarterly source end labels |
| --- | --- | --- |
| BXP | Five, spanning 2021–2025 | Six per statement, spanning 2025 Q1–2026 Q2 |
| Current DOC | Five, spanning 2021–2025 | Income: five, spanning 2025 Q2–2026 Q2; balance sheet and cash flow: six each, spanning 2025 Q1–2026 Q2 |

These quarter names describe returned end labels. They do not certify actual
flow start/duration, completeness of every field at those ends, or unchanged
historical issuer scope. Per-field sparsity and accounting acceptance remain
separate checks.

Of the **65** source statement/end-label groups, **54** pass the native-core
probe. The six 2021 annual groups and the five returned 2025 Q1 groups are
sparse and fail that probe; DOC income has no 2025 Q1 group. Core presence holds
across 2022–2025 annual ends and the five quarterly ends from 2025 Q2 through
2026 Q2 for both companies' three statements. This remains a probe for a small
set of native fields, rather than full-statement certification.

Independent comparison matched all 3,045 raw numbers to the same library
metric/end label. The frame has 814 further missing cells; none has a raw
observation or was filled with zero. Seventy SDK numbers reflect decimal-to-
binary float rounding. Their original decimal tokens are retained in the
HTTP layer, so a consumer can distinguish source precision from SDK precision.

Optional issuer reports were not requested after the Yahoo availability stage
succeeded. SEC requests were zero; no authorized SEC contact was configured and
no identification was invented. Including the three earlier failed issuer-
listing connections, the **known terminal count is 17 against the ceiling of
32**. The 15 unused slots do not authorize further collection. Web discovery
and backend wire counts remain separately unknown.

The closed root has **106 files, 25 snapshots/datasets and 50 materialized
tables**. Read-only verification rederived all 12 raw and 12 frame datasets,
then rebuilt the six coverage decisions and 65 source statement/period rows
from exact reader pins. Network, writer and latest-selection guards remained
unused; target file hashes/mtimes and all 9,272 files in five preceding closed
roots remained unchanged. Full local regression passed **1,369 tests**, plus
scoped Ruff and the offline synthetic example.

The original six AV jobs remain failed; these results are independent,
unaccepted supplemental candidates. Private closed receipts carry the exact
data pins and verification evidence; raw financial values are not published.
