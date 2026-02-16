---
name: debug-phoenix-hil-from-gha
description: Debug Phoenix HIL failures from GitHub Actions (URL or English run description) for one specific job attempt. Use when asked to find S3 logs/artifacts, triage validator/alarm/error failures, run internal HIL failure summarization, inspect ZML and journal logs, trace code paths, and produce concise root-cause analysis with evidence and potential fixes.
---

# Debug Phoenix HIL From GHA

## Goal

Given a GitHub Actions HIL job URL, identify the primary failure cause and explain it with artifact and code evidence.

## Auth failure handling

- On `gh` auth failure, stop and ask the user to authenticate (`gh auth login`) before continuing.
- On AWS auth failure, stop and ask the user to authenticate (`aws sso login`, or use `$aws-sso-login`) before continuing.

## Required input

- Preferred: a GitHub Actions job URL in this form:
  - `https://github.com/ZiplineTeam/FlightSystems/actions/runs/<run_id>/job/<job_id>`
- Also accepted: an English run description from the user.
  - Resolve it to one exact job URL before analysis.
- Scope is exactly one job attempt.
  - If multiple run/job candidates match, stop and ask the user to pick one.

## Workflow

0. Run preflight checks.

```bash
command -v gh >/dev/null || { echo "gh CLI not found"; exit 1; }
command -v aws >/dev/null || { echo "aws CLI not found"; exit 1; }
command -v jq >/dev/null || { echo "jq not found"; exit 1; }
command -v rg >/dev/null || { echo "rg not found"; exit 1; }
command -v zml >/dev/null || { echo "zml CLI not found"; exit 1; }

if ! gh auth status >/dev/null 2>&1; then
  echo "AUTH ERROR: gh is not authenticated. Ask user to run: gh auth login"
  exit 1
fi
if ! aws sts get-caller-identity >/tmp/aws_identity.json 2>/tmp/aws_auth_error.log; then
  echo "AUTH ERROR: AWS auth failed. Ask user to run: aws sso login (or use \$aws-sso-login)."
  cat /tmp/aws_auth_error.log
  exit 1
fi
```

1. Resolve one exact job URL.
   - If user gave an English description, enumerate candidates and pick one:

```bash
gh run list --workflow p2-zip-system-hil-build.yml --limit 100 \
  --json databaseId,displayTitle,headBranch,event,status,conclusion,createdAt,url > /tmp/hil_runs.json
# If no candidates are found, broaden search across workflows/runs.
if [ "$(jq 'length' /tmp/hil_runs.json)" -eq 0 ]; then
  gh run list --limit 500 \
    --json databaseId,displayTitle,headBranch,event,status,conclusion,createdAt,url > /tmp/hil_runs.json
fi
jq -r '.[] | "\(.databaseId)\t\(.createdAt)\t\(.headBranch)\t\(.event)\t\(.conclusion)\t\(.displayTitle)\t\(.url)"' /tmp/hil_runs.json
```

   - After selecting `RUN_ID`, list jobs and choose one `JOB_ID`:

```bash
gh run view "$RUN_ID" --json attempt,jobs > /tmp/hil_run_view.json
jq -r '.jobs[] | "\(.databaseId)\t\(.name)\t\(.status)\t\(.conclusion)\t\(.startedAt)"' /tmp/hil_run_view.json
```

   - Build the selected job URL:

```bash
JOB_URL="https://github.com/ZiplineTeam/FlightSystems/actions/runs/${RUN_ID}/job/${JOB_ID}"
```

2. Parse IDs, lock attempt, and fetch metadata/logs.

```bash
RUN_ID="$(echo "$JOB_URL" | sed -E 's#.*actions/runs/([0-9]+)/job/([0-9]+).*#\1#')"
JOB_ID="$(echo "$JOB_URL" | sed -E 's#.*actions/runs/([0-9]+)/job/([0-9]+).*#\2#')"
gh api "repos/ZiplineTeam/FlightSystems/actions/jobs/$JOB_ID" > /tmp/hil_job_api.json
RUN_ID_FROM_JOB="$(jq -r '.run_id // empty' /tmp/hil_job_api.json)"
[ -n "$RUN_ID_FROM_JOB" ] || { echo "ERROR: could not read run_id from job metadata"; exit 1; }
[ "$RUN_ID_FROM_JOB" = "$RUN_ID" ] || {
  echo "ERROR: job URL run_id ($RUN_ID) does not match job metadata run_id ($RUN_ID_FROM_JOB)";
  exit 1;
}
RUN_ATTEMPT="$(jq -r '.run_attempt // empty' /tmp/hil_job_api.json)"
[ -n "$RUN_ATTEMPT" ] || RUN_ATTEMPT="$(gh run view "$RUN_ID" --json attempt --jq '.attempt')"

gh run view "$RUN_ID" --attempt "$RUN_ATTEMPT" --job "$JOB_ID" \
  --json name,status,conclusion,url,headSha,headBranch,startedAt,updatedAt > /tmp/hil_job_meta.json
gh run view "$RUN_ID" --attempt "$RUN_ATTEMPT" --job "$JOB_ID" --log > /tmp/hil_job.log

# Needed because S3 links can contain $RUNNER_NAME placeholders.
RUNNER_NAME="$(jq -r '.runner_name // empty' /tmp/hil_job_api.json)"
```

Fallback if log fetch fails:

```bash
gh api "repos/ZiplineTeam/FlightSystems/actions/jobs/$JOB_ID/logs" > /tmp/hil_job_logs.zip
unzip -oq /tmp/hil_job_logs.zip -d /tmp/hil_job_logs
find /tmp/hil_job_logs -type f -print0 | sort -z | xargs -0 cat > /tmp/hil_job.log
```

3. Extract and validate S3 log location from the job log (fail fast).
   - Prefer `S3_WEB_LINK_IN_SUMMARY=...`.
   - Also look for `https://s3.console.aws.amazon.com/s3/buckets/platform2-testing-logs?...prefix=...`.

```bash
S3_REF="$(python3 - <<'PY'
import re
from pathlib import Path
text = Path('/tmp/hil_job.log').read_text(encoding='utf-8', errors='replace')
m = re.search(r'S3_WEB_LINK_IN_SUMMARY="([^"]+)"', text)
if m:
    print(m.group(1))
else:
    m = re.search(r'https://s3\.console\.aws\.amazon\.com/s3/buckets/platform2-testing-logs[^" \n]+', text)
    if m:
        print(m.group(0))
    else:
        m = re.search(r's3://platform2-testing-logs/[^\s"\'"]+', text)
        if m:
            print(m.group(0))
PY
)"
[ -n "$S3_REF" ] || { echo "ERROR: no S3 link found in selected job log. Do not fall back to run-level artifact download because attempt scoping can be wrong."; exit 1; }

S3_REF="${S3_REF//\$RUNNER_NAME/$RUNNER_NAME}"
```

Normalize reference to S3 URI:

```bash
if [[ "$S3_REF" == s3://* ]]; then
  S3_URI="$S3_REF"
else
  S3_PREFIX="$(python3 -c 'import sys,urllib.parse as u; q=u.parse_qs(u.urlparse(sys.argv[1]).query); print(u.unquote(q.get("prefix",[""])[0]))' "$S3_REF")"
  [ -n "$S3_PREFIX" ] || { echo "ERROR: S3 prefix is empty"; exit 1; }
  S3_URI="s3://platform2-testing-logs/${S3_PREFIX}"
fi

case "$S3_URI" in
  s3://platform2-testing-logs/p2-zip-system-hil/*) ;;
  *) echo "ERROR: unexpected S3 URI scope: $S3_URI"; exit 1 ;;
esac
```

4. Download run artifacts from S3.

```bash
OUT_DIR="/tmp/hil_${RUN_ID}_${JOB_ID}"
mkdir -p "$OUT_DIR"
aws s3 sync "$S3_URI" "$OUT_DIR"
```

5. Build a first-pass failure summary from logs and `test_record.json`.
   - Find the first clear failure markers:
     - `=== FAILURE REASONS ===`
     - `Error Code`
     - `FAIL_TEST` / `FAIL_VALIDATORS`
   - Treat failure reasons/error table as higher-signal than prior LLM summaries in logs.

```bash
rg -n "=== FAILURE REASONS ===|Error Code|FAIL_TEST|FAIL_VALIDATORS|unexpected-alarms" /tmp/hil_job.log

mapfile -t TEST_RECORDS < <(find "$OUT_DIR" -name test_record.json | sort)
[ "${#TEST_RECORDS[@]}" -gt 0 ] || { echo "ERROR: no test_record.json found"; exit 1; }
JOB_NAME="$(jq -r '.name // ""' /tmp/hil_job_meta.json)"
if [ "${#TEST_RECORDS[@]}" -eq 1 ]; then
  TEST_RECORD="${TEST_RECORDS[0]}"
else
  TEST_RECORD="$(python3 - "$JOB_NAME" "${TEST_RECORDS[@]}" <<'PY'
import json
import os
import re
import sys

job_name = sys.argv[1].lower()
paths = sys.argv[2:]

def tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))

job_tokens = tokens(job_name)
ranked = []
for path in paths:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        continue
    test_info = data.get("test_info") or {}
    test_name = str(test_info.get("name") or "")
    result = str(test_info.get("result") or "")
    t_tokens = tokens(test_name)

    score = len(job_tokens & t_tokens) * 10
    if test_name and test_name.lower() in job_name:
        score += 25
    if job_name and job_name in test_name.lower():
        score += 25
    if result and result != "PASS":
        score += 5

    mtime = os.path.getmtime(path) if os.path.exists(path) else 0
    ranked.append((score, mtime, path, test_name, result))

if not ranked:
    raise SystemExit(1)
ranked.sort(reverse=True)
with open('/tmp/test_record_rankings.tsv', 'w', encoding='utf-8') as out:
    for score, mtime, path, test_name, result in ranked:
        out.write(f"{score}\t{int(mtime)}\t{path}\t{test_name}\t{result}\n")
print(ranked[0][2])
PY
)"
  [ -n "$TEST_RECORD" ] || { echo "ERROR: unable to select test_record.json for selected job"; exit 1; }
  echo "Candidate test_record rankings (score, mtime, path, test_name, result):"
  cat /tmp/test_record_rankings.tsv
  TOP_SCORE="$(awk 'NR==1{print $1}' /tmp/test_record_rankings.tsv)"
  SECOND_SCORE="$(awk 'NR==2{print $1}' /tmp/test_record_rankings.tsv)"
  if [ -n "$SECOND_SCORE" ] && [ $((TOP_SCORE - SECOND_SCORE)) -lt 10 ]; then
    echo "ERROR: test_record selection is ambiguous for this job attempt."
    echo "Ask user to choose the exact test_record.json path from the ranking list."
    exit 1
  fi
fi
jq '.test_info | {name, result}' "$TEST_RECORD"
```

Collect failed validators and checks:

```bash
jq -r '
  .phases[]?
  | .validators[]?
  | select(.valid=="FAIL")
  | .name as $v
  | (.checks // {})
  | to_entries[]
  | select(.value.result==false)
  | "\($v)\t\(.key)\t\(.value.criticality // "unknown")\t\(.value.error // "no-error")"
' "$TEST_RECORD"
```

6. Run internal LLM-backed failure categorization (mandatory).
   - Requires configured `HIL_DB_URL` and `OPENAI_API_KEY`.
   - Fail fast if unavailable.

```bash
: "${HIL_DB_URL:?Set HIL_DB_URL before running}"
: "${OPENAI_API_KEY:?Set OPENAI_API_KEY before running}"
if ! GH_TOKEN_FROM_GH="$(gh auth token 2>/tmp/gh_token_error.log)"; then
  echo "AUTH ERROR: unable to get token from gh. Ask user to run: gh auth login"
  cat /tmp/gh_token_error.log
  exit 1
fi
export GH_TOKEN="${GH_TOKEN:-$GH_TOKEN_FROM_GH}"
export GITHUB_TOKEN="${GITHUB_TOKEN:-$GH_TOKEN}"

HIL_REANALYZE_TARGETS="$JOB_URL" \
REANALYZE_FAILURES=true \
LOOKBACK_HOURS=720 \
bazel run //hil/htf/src:hil_failure_summary > /tmp/hil_failure_summary.json
```

7. Inspect ZML and journal logs for evidence.
   - Common compute logs include `zip-a__ipc.zml*`, `zip-b__ipc.zml*`, `droid__ipc.zml*`, `dock__ipc.zml*`.
   - Phoenix sim logs often include `world.zml*`, `physics.zml*`.
   - Journal content may appear as `journalctl_log` in ZML streams.

```bash
find "$OUT_DIR" -type f \( -name "*.zml" -o -name "*.zml.zst" \) | sort
zml -z <log.zml.zst> list
zml -z <log.zml.zst> print '*<topic_or_alarm_hint>*'
zml -z <log.zml.zst> separate '/compute_a.journalctl_log' -o /tmp/zml_sep/
```

If you have direct compute access, inspect live/system logs:

```bash
sudo journalctl -u <service> -n 500 --no-pager
sudo journalctl -u <service> --since "<UTC timestamp>" --no-pager
```

8. Map failing validator/alarm/error to code and confirm causality.
   - Search validator implementation and config paths:

```bash
rg -n "<validator_name>" p2_validation hil ash sim
```

   - Search alarm/error origin and propagation:

```bash
rg -n "<ALARM_OR_ERROR_NAME>" ash p2_zip p2_droid p2_dock gnc p2_validation
```

   - Re-check every major claim against source files before finalizing.
   - Distinguish `confirmed` evidence from `inferred` reasoning.

9. Produce root cause and fixes.
   - Primary cause = earliest signal that explains downstream failures.
   - Separate:
     - Mission/behavior failure that later trips validators
     - Validator-only regression
     - Infra/system failure
   - Do not blame validators unless raw logs contradict the validator output.
   - Propose fixes only when supported by evidence; otherwise list concrete next checks.

## Output contract

Always respond with this structure:

1. `TL;DR`
   - 2-4 bullets: primary issue, failing validator/alarm/error, confidence.
2. `Detailed analysis`
   - Failure timeline, key log findings, validator/alarm mapping, code trace with file references.
3. `Potential fixes`
   - Immediate mitigation, durable fix, and verification ideas.
4. `Artifacts and steps used`
   - Compact table listing artifact/command and what it proved.

Keep it concise. Prefer short evidence-backed statements over broad speculation.

## Evidence rules

- Do not claim root cause without at least one artifact signal and one code reference.
- If data is insufficient, state `unknown` and list missing artifacts needed.
- For multiple simultaneous failures, identify one primary blocker and clearly mark secondary effects.
- In safety-critical contexts, never suggest bypassing alarms/validators without explicit user request.
- Do not treat prior `LLM Bot Summary` text in job logs as primary evidence.

## Helpful local references

- `notes/autokiosk_no_sync_investigation.md`
- `hil/htf/src/zipline/htf/util/hil_failure_summary.py`
- `hil/htf/src/zipline/htf/hil/failure_analyzer.py`
- `hil/tools/fetch_hil_logs.py`
- `hil/tools/test_log_metrics.py`
- `tools/zml/README.md`
- `hil/utils/remote_machine.py`
