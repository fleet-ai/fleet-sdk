# Fleet Task Authoring Skills

Claude Code skills for guided task creation and job monitoring workflows.

## Installation

Copy the skill directories to your project's `.claude/skills/` or your user-level `~/.claude/skills/`:

```bash
# Project-level (recommended — scoped to one project)
cp -r skills/task-authoring .claude/skills/
cp -r skills/fleet-status .claude/skills/

# User-level (available across all projects)
cp -r skills/task-authoring ~/.claude/skills/
cp -r skills/fleet-status ~/.claude/skills/
```

## Available Skills

| Skill | Triggers on | What it does |
|-------|-------------|-------------|
| `task-authoring` | Creating task bundles, setting up directories, writing prompts | Guides bundle structure, file visibility, naming, prompt rules, pre-upload leakage checks |
| `fleet-status` | Checking job status, viewing scores, querying the Fleet API | API endpoint reference with ready-to-use curl commands and response parsing |

## How Skills Work

Skills are loaded automatically by Claude Code when your request matches the skill's trigger conditions. You don't need to invoke them manually — just describe what you want to do and the relevant skill activates.

For more on Claude Code skills, see the [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code).
