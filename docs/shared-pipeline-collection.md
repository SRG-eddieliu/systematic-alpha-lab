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

The following `plan` and `run` commands use the current implementation to
create and collect a new batch. They do not reproduce the execution policy of
the original batch, whose collector source and private transport executor are
pinned separately below.

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

The default interval is 15 seconds after the preceding response or error
completes. The persisted completion time is used across restarts and batches;
an interrupted or legacy request without a completion time waits a full
interval from recovery. Slow responses therefore cannot be followed by an
immediate send. An explicit 1.1-second interval has an upper bound of about
54.55 starts per minute, below the currently published minimum paid plan of
75 per minute; actual throughput also includes response latency. The actual
account tier and other users of the credential must be checked separately.
A credential's configuration slot name does not establish its entitlement.
Provider notices, quota/authentication responses and safety errors halt
collection.

Successful imported observations are pinned regardless of their age. They
are not refreshed automatically. The private batch ledger binds the universe,
configuration, collector and normalizer source hashes, job identities,
attempt history, UTC request/response times and successful input fingerprints.
Imported legacy receipts may contain only observation time; an earlier
request-start time is not invented. The first implementation paced request
starts; its source is preserved by the initial collection commit. The final
implementation additionally persists request completion and waits after it.
The original batch uses its exact recorded collector source plus an archived
private transport executor that additionally waits two seconds after a response
completes. Its private execution receipts retain actual HTTP start and finish
times. This additional execution policy does not rewrite the original batch
configuration, its hash, or its collector source pin. Collection and diagnostic
phases must be recorded separately, with their actual policies and budgets.

## Execute and recover explicitly

Use an independent closed data copy when another research process is using
the pilot catalog. The batch lock coordinates this collector and its replay
entry point; other tools and the general offline reader must independently
honor the quiescent-catalog requirement.

```bash
# Current implementation: collect a new batch created by the plan command above.
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

### Resume the original batch from its archived execution handoff

The original collector is preserved at commit
`e3dd34288c0fd959909169dc75ee903ebdcb4161`, with collector source SHA256
`a9be4edcde6a16c1a81004fff0aa2b7736cce0d5ee6cbcf5f594735f29be2002`.
These execution pins stay unchanged. The final collector source has separate
fingerprints under `validation_code_fingerprints` in the public validation
record; those hashes describe the code being validated, not the collector
that produced the original observations. The current collection CLI rejects
an original batch with a different collector source hash. It cannot be used
as a substitute for the archived original execution command.

Create this independent detached checkout once, then reuse it only at the
recorded commit. Use the runtime, private configuration and archived executor
from the original execution handoff. All variables below are private path or
budget placeholders; no private run identifier or local path belongs in public
documentation.

```bash
git worktree add --detach "$SRG_PINNED_EXEC_CHECKOUT" \
  e3dd34288c0fd959909169dc75ee903ebdcb4161

git -C "$SRG_PINNED_EXEC_CHECKOUT" rev-parse HEAD
shasum -a 256 \
  "$SRG_PINNED_EXEC_CHECKOUT/src/systematic_alpha_lab/data_pipeline/fundamental_batch.py" \
  "$SRG_ARCHIVED_TRANSPORT_EXECUTOR"

cd "$SRG_PINNED_EXEC_CHECKOUT"
PYTHONPATH="$SRG_PINNED_EXEC_CHECKOUT/src" \
  python "$SRG_ARCHIVED_TRANSPORT_EXECUTOR" "$SRG_MAX_NEW_ATTEMPTS"
```

Before invoking the executor, verify the commit, collector source hash and
executor source hash against the private execution receipt. Archive the exact
executor source and reference its SHA256 and execution receipt in the public
validation record. The executor uses the original private root and manifest
configuration and accepts one integer argument limiting additional attempts.
At startup it selects existing `failed` jobs with `provider_notice_or_error`
whose attempt count remains below the frozen per-job budget, passes that set
as `retry_jobs`, and acknowledges the prior halt with `resume_after_halt=True`.
Before invocation, review the closed ledger and explicitly authorize that
startup retry set and halt acknowledgement. The collector does not retry
automatically during execution. Diagnostic and recovery stages retain their
separate retry selections, authorizations and execution receipts. In the final
1,316-attempt stage, the eligible startup retry set was empty; all 1,316
attempts were pending jobs.
The frozen run-wide budget still applies; increasing a per-invocation argument
cannot increase that budget. Record the two-second response-completion policy
and its actual execution receipts separately from the unchanged collector pin.

Offline replay of this original batch uses the current read-only API below.
It does not require the archived transport executor, credentials, or a new
collection request.

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
