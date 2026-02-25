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

Edit `task.json` to change the prompt, verifier, metadata, etc.
Add/remove/modify files in `files/`.

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
| `--key` | New task key (required, must differ from original) |
| `--api-key` | API key (default: `FLEET_API_KEY` env var) |
| `--team-id` | Team ID override (default: auto-resolved from API key) |
| `--allow-overwrite` | Allow overwriting existing files in S3 |

### validate_task.py

| Flag | Description |
|------|-------------|
| `bundle_dir` | Path to task bundle directory (positional, required) |
| `--new-key` | New key to validate against |
