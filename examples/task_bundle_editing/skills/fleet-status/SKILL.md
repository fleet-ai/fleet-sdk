---
name: fleet-status
description: Use when checking job status, viewing session scores, querying task details, or debugging Fleet API responses.
---

# Fleet Status

Check job status, session scores, and task details from the Fleet orchestrator API.

## Usage

The user may say "check job status", "fleet status", or reference a specific job name/ID.

## Steps

1. **Load env vars** — `export $(grep -v '^#' .env | xargs)`
2. **Set base URL** — `BASE=${FLEET_BASE_URL:-https://orchestrator.fleetai.com}`
3. **Auth header** — `AUTH="Authorization: Bearer $FLEET_API_KEY"`

### List recent jobs
```bash
curl -s -H "$AUTH" "$BASE/v1/jobs?limit=5" | python3 -m json.tool
```

### Get job sessions with scores (replace JOB_ID)
```bash
curl -s -H "$AUTH" "$BASE/v1/sessions/job/{JOB_ID}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Job: {data[\"job_id\"]}')
for t in data['tasks']:
    print(f'\nTask: {t[\"task\"][\"key\"]}')
    print(f'  Pass rate: {t[\"pass_rate\"]:.0%} ({t[\"passed_sessions\"]}/{t[\"total_sessions\"]})')
    print(f'  Avg score: {t[\"average_score\"]}')
    for s in t['sessions']:
        v = s.get('verifier_execution')
        score = f'{v[\"score\"]:.2f}' if v else 'pending'
        print(f'  {s[\"model\"]:40s} status={s[\"status\"]:12s} score={score}  id={s[\"id\"]}')
"
```

### Get session transcript (replace SESSION_ID)
```bash
curl -s -H "$AUTH" "$BASE/v1/sessions/{SESSION_ID}/transcript" | python3 -m json.tool
```

### Get task details (replace TASK_KEY)
```bash
curl -s -H "$AUTH" "$BASE/v1/tasks/{TASK_KEY}" | python3 -m json.tool
```

### Check account
```bash
curl -s -H "$AUTH" "$BASE/v1/account" | python3 -m json.tool
```

## Key API Endpoints Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/jobs?limit=N` | GET | List recent jobs |
| `/v1/jobs/{job_id}` | GET | Get job details |
| `/v1/sessions/job/{job_id}` | GET | Sessions with scores grouped by task |
| `/v1/sessions/{session_id}/transcript` | GET | Full session transcript with verifier output |
| `/v1/tasks/{task_key}` | GET | Task metadata, prompt, verifier |
| `/v1/file-sets/{key}/download-urls` | POST | Get presigned download URLs for task files |
| `/v1/account` | GET | Team info, instance count |

### Parse per-criterion scores from GRADING_DETAILS

The verifier stdout contains a `>>> GRADING_DETAILS >>>` block with structured JSON. To extract per-criterion scores from a session transcript:

```bash
curl -s -H "$AUTH" "$BASE/v1/sessions/{SESSION_ID}/transcript" | python3 -c "
import json, sys
data = json.load(sys.stdin)
# Find verifier output in transcript messages
for msg in data.get('messages', []):
    stdout = msg.get('stdout', '') or ''
    if '>>> GRADING_DETAILS >>>' in stdout:
        details_text = stdout.split('>>> GRADING_DETAILS >>>')[1].split('<<< GRADING_DETAILS <<<')[0]
        details = json.loads(details_text)
        for c in details.get('criteria', []):
            reasoning = c.get('reasoning', '')
            print(f'  [{c[\"score\"]}/{c[\"max\"]}] {c[\"name\"]}')
            if reasoning:
                print(f'           {reasoning[:200]}')
        break
"
```

Note: The exact location of the GRADING_DETAILS block may vary — it can be in the verifier execution stdout or in the session transcript messages. Check both if one is empty.

Use the session `id` values printed by the job sessions command above as `{SESSION_ID}` here.

## Notes

- All endpoints require `Authorization: Bearer $FLEET_API_KEY`
- The job ID in API paths (e.g., `/v1/sessions/job/{JOB_ID}`) is the Fleet-generated job name (e.g., `sequential-polosukhin-cc90`), not a numeric ID
- Job sessions endpoint is the primary way to see per-model scores
- Verifier output includes detailed rubric scoring in `stdout` field
- If a job is still running, sessions may show `status=running` with no verifier output yet
