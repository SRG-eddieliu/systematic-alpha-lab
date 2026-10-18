# Provider-only statement review

Alpha Vantage statement snapshots can be used directly for descriptive research
and source checks. SEC is an optional reconciliation source, not an input required
by this path. The [provider documentation](https://www.alphavantage.co/documentation/)
describes annual and quarterly income statements, balance sheets and cash flows
with normalized financial fields. The existing snapshot collector preserves those
responses and their collection times without replacing older observations.

`review_fundamental_snapshots` consumes one immutable capture for each statement
for a single explicit provider symbol. It verifies source/table hashes, aligns
annual periods with outer joins and publishes two versioned Parquet tables:

| Output | Calculation | Interpretation |
| --- | --- | --- |
| Annual review | `-(annual net income - annual operating cash flow) / average adjacent-year total assets` | Descriptive candidate arithmetic using provider amounts |
| Reconciliation | Annual income/cash flow versus the four reported quarters between observed annual boundaries | Source consistency check; differences are retained |
| Balance reconciliation | Annual assets versus the quarter with the same period end | Stock comparison; assets are never summed across quarters |

The annual review also retains the difference between net income in the income
statement and net income in the cash-flow statement. A difference may reflect
definitions, revisions, source mapping or rounding; this implementation does not
assert a cause or overwrite one value with the other. Exact comparisons have no
hidden rounding tolerance.

## Boundaries

- The annual ratio is a descriptive input review, not a change to the locked
  [four-quarter TTM study](financial-quality-study.md). No market returns, IC,
  portfolio result or historical tradability is calculated here.
- Candidate arithmetic assumes income, cash flow and assets share the provider's
  monetary scale within the same reported currency. This remains explicitly
  `provider_common_scale_assumption_unverified`. The data are usable for exploration
  while that assumption and any source differences remain visible.
- Missing or mismatched currency/amounts, nonpositive endpoint assets, missing
  preceding assets and irregular annual gaps leave the ratio missing. Malformed
  or non-finite numeric amounts are rejected. Unmatched annual dates are retained.
- Adjacent annual periods must be 330–400 days apart. Flow reconciliation needs
  four quarters with 60–120 days between boundaries, ending at the annual date.
  These are declared review rules; they do not identify fiscal quarters or prove
  a monetary unit or original-vintage source contract. Noncalendar years use
  observed annual boundaries rather than calendar-year grouping.
- Annual ratios can still be computed when quarterly reconciliation is incomplete
  or shows differences. Such ratios remain `candidate_only`; review both output
  tables together before choosing a research dataset.
- No quarterly cash flow is relabelled as YTD or differenced again. No unavailable
  filing history or SEC data are invented. The symbol remains an unmapped provider
  identifier and `available_at` stays missing.

Each derived version binds all three staging manifests, exact source observations,
normalizer source hash, formula and spacing rules. Replay verifies dependencies
before returning an existing review. Raw inputs and real-data outputs stay private;
public examples and tests use synthetic observations only.

## Run

```bash
# Complete runnable example; no account, credentials or network.
PYTHONPATH=src python examples/av_statement_review_demo.py

# Use already collected provider snapshots, with no credentials or network.
PYTHONPATH=src python examples/review_fundamental_snapshots.py \
  --data-root /path/to/private/srg-data --symbol YOUR_SYMBOL
```

The CLI selects the most recent local captures and emits the manifest needed to
replay those exact versions. It does not refresh sources or contact another provider.
The API also accepts explicitly selected older capture records.
