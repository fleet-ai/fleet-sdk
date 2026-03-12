---
name: task-authoring
description: Use when creating a new Fleet task bundle, setting up bundle directories, writing task.json, or validating before upload.
---

# Fleet Task Authoring

Guide for creating a Fleet evaluation task bundle: directory setup, prompt writing, verifier integration, and pre-upload validation.

## Bundle structure

A Fleet task bundle is a self-contained directory with exactly this layout:

```
<task_key>/
  task.json
  files/
    notebooks/<task_key>/data/    # solver-visible input files
    solutions/                     # judge-only (holdout, reference answers)
```

`task.json` holds the prompt, verifier (rubric), and metadata. The `files/` directory holds all supporting files, split by visibility.

### File visibility

Fleet uploads everything in `files/`, but only exposes certain paths to the solver:

| Location | Uploaded? | Solver sees it? | Use for |
|----------|-----------|-----------------|---------|
| `files/notebooks/<task_key>/data/*` | Yes | Yes | Input files the solver works with |
| `files/solutions/*` | Yes | No (judge-only) | Reference answers, holdout data |
| `task.json` | Yes (as metadata) | Solver sees `prompt`; verifier runs server-side | Prompt + rubric |

**Key rule:** Never put judge-only files in `files/notebooks/` -- everything there is visible to the solver. Use `files/solutions/` for anything the judge needs but the solver should not see.

## Task naming

- **Fleet task key format:** `<problem_name>_taskNN` with underscores (e.g., `my_task_01`)
- Fleet auto-generates a suffixed key on upload (e.g., `my_task_01_4ec3452d`) -- never manually add hash suffixes
- The base key lives in your local `task.json`; the suffixed key is what you use for `make launch` and job tracking
- After upload, switch to the suffixed key for launching jobs

## task.json structure

Required fields:

```json
{
  "key": "<task_key>",
  "prompt": "...",
  "verifier": {
    "code": "def verify(env, final_answer=None, conversation=None):\n    ...",
    "comment": "Summary of what the rubric evaluates"
  },
  "metadata": {
    "task_name": "Human-readable task name"
  }
}
```

- **`key`**: matches the directory name (base key, no hash suffix)
- **`prompt`**: the complete text the solver sees
- **`verifier.code`**: inline Python defining a `verify()` function
- **`verifier.comment`**: designer-facing note (never shown to the solver)
- **`metadata`**: internal fields for task management

## Fleet prompt conventions

Fleet tasks follow certain boilerplate conventions. Include these in your prompt:

- **File discovery:** `Use list_workspace_files(pattern="<task_key>/data/*") to discover available files, then read them as needed.`
- **Artifact saving:** `Save files to /artifacts/ as well for evaluation.`
- **Output files:** Specify named output files for the solver to produce.

See the template in `templates/` for the full boilerplate structure.

## Prompt guidelines

- State the task clearly and openly
- Describe the input files and their structure as they appear in the provided data
- Use solver-agnostic language -- not "the agent" or "the AI"
- Specify named output files for the solver to produce

## Pre-upload checklist

- [ ] Prompt is clear and self-contained
- [ ] Solver-agnostic language throughout
- [ ] Named output files specified
- [ ] File visibility is correct: judge-only data in `solutions/`, not `notebooks/`
- [ ] Bundle validates: `python validate_task.py <task_dir>`
- [ ] `key` field in task.json matches the directory name

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Judge-only data in `notebooks/` | Move to `solutions/` |
| Manual hash suffix on task key | Let Fleet auto-generate the suffix on upload |

## Validation

Before uploading, validate the bundle structure:

```bash
python validate_task.py <task_dir>
```

This checks that `task.json` is well-formed, required fields are present, the verifier code parses, and the file paths referenced in the bundle exist.

After upload, Fleet returns a suffixed task key. Use that key (not the base key) for launching jobs and tracking results.
