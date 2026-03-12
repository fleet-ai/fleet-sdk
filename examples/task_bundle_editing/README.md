# Task Bundle Editing

Download existing tasks, edit them locally, and upload as new tasks.

## Setup

```bash
pip install requests python-dotenv
```

Set your API key:

```bash
export FLEET_API_KEY=your_api_key_here
```

Or create a `.env` file:

```
FLEET_API_KEY=your_api_key_here
```

By default, scripts talk to production (`https://orchestrator.fleetai.com`).
Override with `FLEET_BASE_URL` for staging/local:

```bash
export FLEET_BASE_URL=https://staging.fleetai.com
```

## Workflow

### 1. Download a task

```bash
python download_task.py --task-key my_existing_task --output-dir ./my_task
```

This creates:

```
my_task/
  task.json      # task metadata, prompt, verifier
  files/         # data files (may be empty)
    notebook.ipynb
    data.csv
```

### 2. Edit the task

A downloaded `task.json` contains the full task definition: `key`, `prompt` (flat string), `verifier` (inline Python with rubric criteria), `environment_id`, and `metadata`. Edit what you need:

- **Prompt:** Modify the `prompt` string. The templates in `templates/` show how prompts are structured (data discovery, task body, output instructions) — use them as a reference for what each section should contain.
- **Verifier/rubric:** The `verifier.code` field is a Python function that defines rubric criteria and calls `env.judge.grade()`. Edit criteria, level descriptions, context, or reference claims as needed.
- **Data files:** Add, remove, or replace files in `files/`. Solver-visible data goes in `files/notebooks/<task_key>/data/`; judge-only reference data goes in `files/solutions/`.
- **Metadata:** Update `metadata` fields (task_name, difficulty, etc.) as needed — these are internal and not shown to the solver.

### 3. Validate before upload

```bash
python validate_task.py ./my_task --new-key my_new_task
```

Checks: valid JSON, required fields, verifier syntax, file sizes, key format.

### 4. Upload as a new task

```bash
python upload_task.py --dir ./my_task --key my_new_task
```

This validates the bundle, uploads files to a new file-set, then creates the task.

The `--key` must differ from the original task key (safety check).

## CLI Reference

### download_task.py

| Flag | Description |
|------|-------------|
| `--task-key` | Task key to download (required) |
| `--output-dir` | Output directory (default: `./<task-key>`) |
| `--api-key` | API key (default: `FLEET_API_KEY` env var) |
| `--team-id` | Team ID override (default: auto-resolved from API key) |

### upload_task.py

| Flag | Description |
|------|-------------|
| `--dir` | Path to task bundle directory (required) |
| `--key` | New task key (default: auto-generated from original key + UUID) |
| `--api-key` | API key (default: `FLEET_API_KEY` env var) |
| `--team-id` | Team ID override (default: auto-resolved from API key) |
| `--allow-overwrite` | Allow overwriting existing files in S3 |

### validate_task.py

| Flag | Description |
|------|-------------|
| `bundle_dir` | Path to task bundle directory (positional, required) |
| `--new-key` | New key to validate against |

### launch_job.py

| Flag | Description |
|------|-------------|
| `--task-key` | Task key(s) to launch (required, accepts multiple) |
| `--api-key` | API key (default: `FLEET_API_KEY` env var) |
| `--models` | Models for the job (default: gemini, claude, gpt) |
| `--pass-k` | pass@k for the job (default: 1) |

---

## Makefile (quick reference)

A Makefile wraps the Python scripts for convenience. Run `make help` for the full list.

```bash
make task TASK=my_task   # set active task (persists in .task)
make download            # download active task to downloaded_tasks/<task>/
make validate            # validate the bundle
make upload              # upload bundle (auto-generates versioned key)
make launch              # launch a job for active task
make env                 # show current config + active task
make clean               # clear active task key
make clean-all           # remove active task bundle + clear key
```

Override defaults with `DIR=`, `KEY=`, `MODELS=`, `PASS_K=`, `TEAM=`, or `OVERWRITE=1`.

## Creating a New Task from Scratch

To create a brand new task (rather than editing an existing one):

**Before you start**, download an existing task (`make download`) to see what a real `task.json` looks like. A downloaded task shows the final format: `key`, a flat `prompt` string, `verifier` with inline Python rubric code, `environment_id`, and `metadata`. This is the best reference for what you're building toward.

You will need:
- A **prompt** — the task description the solver sees
- A **verifier** — Python code defining rubric criteria that the judge uses to score submissions
- **Data files** — input files the solver will work with

1. **Create the bundle directory structure:**

   ```bash
   mkdir -p my_task/files/notebooks/my_task/data/
   ```

2. **Use a template as a design reference:**

   Open `templates/verifier_template.json` as a guide for what your `task.json` needs. The template breaks the prompt and rubric into labeled sections for readability — when building your actual `task.json`, consolidate the prompt sections into a single string and write the verifier as inline Python (see any downloaded task for the final format).

3. **Fill in your task content** — prompt text, verifier criteria, context, reference claims, and metadata fields.

4. **Add data files** to `my_task/files/notebooks/my_task/data/`. These are visible to the solver at runtime.

5. **Validate:**

   ```bash
   make validate DIR=my_task
   # or directly:
   python validate_task.py my_task/
   ```

6. **Upload:**

   ```bash
   make upload DIR=my_task
   # or directly:
   python upload_task.py --dir my_task/ --key my_task --no-launch-job
   ```

## Task Bundle Structure

```
<task_key>/
  task.json                              # prompt, verifier, metadata
  files/
    notebooks/<task_key>/data/           # solver-visible data files
    solutions/                           # judge-only (not visible to solver)
```

- **`files/notebooks/<task_key>/data/`** — files the solver can read during execution (CSVs, images, etc.)
- **`files/solutions/`** — reference outputs used only by the verifier/judge, never exposed to the solver

## Launching and Reviewing Jobs

```bash
# Launch with defaults (all 3 models, pass@1)
make launch

# Or directly
python launch_job.py --task-key my_task_abc12345

# Override models
make launch MODELS="anthropic/claude-opus-4.6 openai/gpt-5.2"

# Run pass@5
make launch PASS_K=5
```

Default models: `google/gemini-3.1-pro-preview`, `anthropic/claude-opus-4.6`, `openai/gpt-5.2`.

## Templates

- `templates/verifier_template.json` — generic task scaffold with prompt sections, rubric criteria, context, and reference claims

This is a **design scaffold** — it breaks the prompt and rubric into labeled sections for readability, with `{PLACEHOLDER}` variables for your content. It is not a directly valid `task.json` file; use it as a reference when building your actual task. Download an existing task (`make download`) to see the final `task.json` format (flat prompt string, inline Python verifier).

## Claude Code Skills

If you use Claude Code, copy the skills from `skills/` to your project's `.claude/skills/` directory. These provide guided workflows for task authoring and job monitoring. See `skills/README.md` for installation instructions.
