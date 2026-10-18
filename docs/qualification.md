# Optional second-pass qualification

Collection, rule scores, thresholds, SQLite rows and outreach behavior are unchanged.
This is a separate manual command over a JSON export, not a collector hook or scheduler.
It emits the original record under `baseline` and a separate research assessment.

```sh
# Offline/default: no network call, baseline retained
python -m listener.qualification exported-signals.json > reviewed-signals.json

# Explicit opt-in; configure an approved OpenAI-compatible endpoint privately
export LEAD_QUALIFIER_BASE_URL='https://your-approved-host/v1'
export LEAD_QUALIFIER_MODEL='your-model-name'
export LEAD_QUALIFIER_API_KEY='your-key'
export LEAD_QUALIFIER_TIMEOUT='20'
python -m listener.qualification exported-signals.json --enable-model > reviewed-signals.json
```

Do not overwrite the input file through shell redirection. The command accepts at most
100 signals per run. Each enabled, configured signal makes at most one request; there
is no fallback, provider discovery, or automatic hosted API call. No configuration has
been deployed or enabled by this change. Inference may cost money on a paid endpoint;
configuration is not spending authorization.

Only `title`, `text`, and `community` are sent, not usernames, URLs, scores, or other
metadata. Source text itself can contain private information: review/redact it first.
Keep output alongside private listener data, not in git. HTTPS is required by default.
`--allow-insecure-http` exists only for explicitly reviewed synthetic test fixtures;
never use plain HTTP for personal, client or confidential data. No IP or provider URL
is baked into the code. Qwen-compatible requests use `reasoning_effort=medium`.

## Output and failure policy

- `status`: `disabled`, `unconfigured`, `failed`, or `qualified` (schema-valid assessment,
  **not** a verified buyer). `baseline` is always unchanged.
- `qualification.verdict`: `review`, `not_a_fit`, or `unknown`.
- `evidence`: exact, nonempty quotes tied to the supplied source field. Invented quotes,
  unexpected fields, invalid JSON and unsupported verdicts are rejected.
- `missing`: bounded enum of `budget`, `authority`, `timeline`, `need`, `fit`.
- `outreach`: always `manual_only`; no messages or contact drafts are sent.

Quotes prove textual presence, not truth, relevance or buying intent. Humans must
check the full source, including negation, context and whether the poster is selling
rather than buying. Model verdicts never replace rule scores or filter out baseline rows.

Timeouts, HTTP errors, redirects, oversized/truncated completions and invalid schemas
produce a failed assessment with the original baseline. Errors do not expose provider
bodies or secrets. Missing URL/model/key skips inference. Exit 2 signals a failed or
unconfigured enabled pass; its baseline JSON is still emitted. Invalid export input
also exits 2 with a generic stderr message. Default/offline success exits 0.

## Verification

`python -m unittest discover tests -v` runs offline in GitHub Actions, including a local
HTTP server for the real transport, malformed/hallucinated output, failure fallback,
source-field minimization and a subprocess invocation of the command. No live provider
is required in CI. No dependency installation is needed for this feature.
