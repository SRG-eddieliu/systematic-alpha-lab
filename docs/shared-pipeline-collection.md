# Frozen statement collection and offline replay

This workflow extends the existing `systematic_alpha_lab.data_pipeline`.
It freezes an explicit security scope, records a finite three-statement request
budget, resumes pending jobs and replays exact successful observations through
`OfflineDataReader.catalog/read`. Source data and full receipts stay private.
The [shared data contract](shared-data-contract.md) defines identity, period,
currency, amount and historical-availability limits.

## Runnable synthetic example

```bash
python -m pip install -e '.[dev]'
python examples/shared_pipeline_demo.py
python -m pytest -q
```

The example uses temporary synthetic inputs, an injected clock and a fake
client. It collects six synthetic statement responses, resumes with zero
additional calls, verifies twelve pinned tables and profiles source missing
values without changing the input tree. No account or credential is required.

## Freeze the scope before collection

Use caller-supplied private records and a source receipt. Set the environment
variables below to private locations outside the repository. These are path
placeholders; never put a credential value in a shell command.

```bash
python examples/freeze_universe.py \
  --records-json "$SRG_UNIVERSE_RECORDS" \
  --source-receipt-json "$SRG_UNIVERSE_RECEIPT" \
  --output "$SRG_UNIVERSE_MANIFEST"
```

The manifest distinguishes securities from companies and records exact source
bytes, capture time, membership date and explicit provider mappings. Its
security count determines the budget. Unknown issuer links remain null.
Directory-symbol agreement does not establish a stable issuer identity.
Current membership cannot establish historical membership.

The initial source acquisition used two official ETF holdings files with the
same membership date. The retained security sets agreed after documented
non-equity and stale-residual exclusions. This scope remains `etf_proxy`;
agreement and a matching security count do not turn it into a certified index
constituent list. The private source package preserves both raw files,
exclusions, provider directory/search responses and mapping warnings.

Official references: [S&P 500](https://www.spglobal.com/spdji/en/indices/equity/sp-500/),
[Alpha Vantage listing status](https://www.alphavantage.co/documentation/#listing-status),
[symbol search](https://www.alphavantage.co/documentation/#symbolsearch),
[fundamental endpoints](https://www.alphavantage.co/documentation/#fundamentals),
and [premium plans](https://www.alphavantage.co/premium/).

## Plan a bounded private batch

```bash
python examples/collect_fundamental_batch.py plan \
  --data-root "$SRG_DATA_ROOT" --run-id "$SRG_RUN_ID" \
  --universe "$SRG_UNIVERSE_MANIFEST" \
  --max-total-requests 1530 --max-attempts-per-job 2 --interval 1.1 \
  --import-receipts "$SRG_VERIFIED_PILOT_RECEIPTS" \
  --allow-proxy --allow-unverified-mappings
```

These explicit opt-ins are appropriate only for a declared proxy scope with
recorded unverified mapping candidates. Defaults require an exact verified
current index scope and verified provider mappings. Neither option certifies
membership or identity. Unavailable mappings cannot silently shrink the scope.

For 503 unique mapped symbols the complete plan has 1,509 statement jobs.
Nine explicitly verified pilot receipts leave 1,500 first attempts; a 1,530
request budget reserves at most 30 extra attempts. Every failed or uncertain
attempt consumes that budget. The provider identity preflight used a separate
three-request budget. A reserved second attempt never authorizes an automatic
retry. No purchase, key rotation or fallback source is part of this workflow.

The default interval is 15 seconds. An explicit 1.1-second interval limits one
collector to approximately 54.55 starts per minute, below the currently
published minimum paid plan of 75 per minute. The actual account tier and
other users of the credential must be checked separately; a credential's
configuration slot name does not establish its entitlement. Provider notices,
quota/authentication responses and safety errors halt collection.

Successful imported observations are pinned regardless of their age. They
are not refreshed automatically. The private batch ledger binds the universe,
configuration, collector and normalizer source hashes, job identities,
attempt history, UTC request/response times and successful input fingerprints.
Imported legacy receipts may contain only observation time; an earlier
request-start time is not invented.

## Execute and recover explicitly

Use an independent closed data copy when another research process is using
the pilot catalog. The batch lock coordinates this collector and its replay
entry point; other tools and the general offline reader must independently
honor the quiescent-catalog requirement.

```bash
python examples/collect_fundamental_batch.py run \
  --data-root "$SRG_DATA_ROOT" --run-id "$SRG_RUN_ID" \
  --max-requests 1500 --credentials "$SRG_CREDENTIAL_FILE" \
  --key-slot alphavantage_api_paid

python examples/collect_fundamental_batch.py status \
  --data-root "$SRG_DATA_ROOT" --run-id "$SRG_RUN_ID"
```

The CLI loads the existing credential helper only for an explicit run that
needs requests. It prints aggregate coverage and fingerprints. Raw and
normalized files, request identities and detailed private failure lists stay
outside GitHub. Status and replay require a closed batch lock; a supervising
process may inspect the atomic JSON ledger for progress without opening the
active SQLite catalog.

Interrupted sends become `uncertain` and are charged even if delivery cannot
be established. Resume selects pending jobs. A failed or uncertain job needs
an explicit `--retry-job "$SRG_FAILED_JOB"`; a stopped quota/authentication or
safety event additionally needs `--resume-after-halt` after its cause is
resolved. Both the run-wide and per-job budgets still apply. Source-format
and normalization failures retain their failure state; they are not silently
replaced with a different provider. Ambiguous notices stop conservatively.

To refresh, create a new run ID using `plan --refresh-of "$SRG_PRIOR_RUN_ID"`.
Refresh retains the frozen universe and does not import old observations.
Each successful response is captured as a new immutable observation; identical
raw bytes share their content-addressed object. Changed source code must use
an appropriate new version. To resume an existing collection, restore the
exact recorded collector source; offline replay does not require recollection.

## Close collection and replay with credentials disabled

```bash
env -u ALPHAVANTAGE_API_KEY -u ALPHA_VANTAGE_API_KEY \
  python examples/collect_fundamental_batch.py replay \
  --data-root "$SRG_DATA_ROOT" --run-id "$SRG_RUN_ID"
```

Replay opens only the existing immutable catalog and exact successful pins.
It verifies raw/table hashes, row counts, complete normalized-manifest hash
and observation time. Failed, missing and uncertain jobs remain in coverage;
the successful subset is not reported as the full requested universe.

`statement_quality.profile_fundamental_receipts` uses the same reader and full
manifest pins. It distinguishes finite source amounts, source missing tokens,
malformed values and nonfinite amounts. It preserves original strings and
does not fill missing values, infer units, difference quarterly reports as YTD,
or establish historical availability. Its date bounds describe period-end
labels rather than financial-period start dates.

The public validation record contains allowed counts, code/config/input
fingerprints and the real offline verification result. Private receipts retain
exact selections and detailed failures. Collection success, normalization,
arithmetic readiness, historical point-in-time eligibility and an investable
alpha result remain separate acceptance criteria. The existing SRG main
progress Page remains the only live project checkpoint.
