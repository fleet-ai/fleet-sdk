# Task Bundle Editing

Task authoring toolkit for creating, editing, and deploying Fleet evaluation tasks.

## Task bundle structure

```
<task_key>/
  task.json                        # prompt, verifier, rubric, metadata
  files/
    notebooks/<task_key>/data/     # solver-visible data files
    solutions/                     # judge-only reference files
```

**File visibility matters for rubric design:** The solver sees everything under `notebooks/` but never sees `solutions/`. Reference data, correct answers, and comparison baselines belong in `solutions/` so the verifier can grade against them without leaking information to the solver.

## Makefile commands

```
make task TASK=<key>     Set active task
make download            Download task bundle
make upload              Upload as new task (auto-generates versioned key)
make upload KEY=<key>    Upload with explicit key
make launch              Launch job for active task
make launch MODELS="anthropic/claude-opus-4.6"  Launch specific models
make validate            Validate bundle
make env                 Show current config
make clean               Clear active task
make clean-all           Remove bundle + clear task
```

## Task key vs. job name

- **Task key** — permanent identifier for an uploaded task (e.g., `my_task_4ec3452d`). Used with `make launch`.
- **Job name** — Fleet-generated name for an evaluation run (e.g., `sequential-polosukhin-cc90`). Used to query results on the Fleet dashboard.
- Never use one as the other.
- `make upload` (no `KEY=`) auto-generates a versioned key: `<base_key>_<uuid8>`. Use this by default.
- After upload, switch `.task` to the suffixed key before running `make launch`.

## Prompt authoring rules

- State the research question naturally — don't prescribe specific statistical methods
- Don't structure prompts into sub-parts that map to rubric criteria
- Don't hint at traps or tell the solver what to avoid
- Don't include expected answers, difficulty ratings, or analysis type in prompt text
- Use solver-agnostic language ("the analysis", "build a model" — not "the agent")
- Don't reveal which data is reserved for judge evaluation
- Describe the dataset actually provided, not a source dataset it was drawn from
- Use named output files (`findings.txt`, `investigation.txt`), not `submit_final_answer`

## Model names

Use `provider/model` format:
- `anthropic/claude-opus-4.6`
- `google/gemini-3.1-pro-preview`
- `openai/gpt-5.2`

Omit `MODELS=` to launch all available models.

## Rubric iteration cycle

Upload → launch → review results on dashboard → revise rubric → re-upload (no `KEY=` for new version) → relaunch.

Use pass@1 for initial rubric validation. Only run pass@5+ after confirming the rubric discriminates across models.

## Skills (planned)

Claude Code skills for task authoring, rubric design, and job monitoring are planned for a future update.
