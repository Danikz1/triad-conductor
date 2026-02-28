# Triad Conductor Instructions

This repository is the **orchestrator**.  
Your actual coding project can be in any separate folder.

## 0. One-command start (auto project folder under `/Users/daniyarserikson/Projects`)

From any folder (for example where your `project.md` is):

```bash
/Users/daniyarserikson/Projects/triad-conductor/triad-start project.md
```

What it does:
- Uses `project.md` as your project description
- Creates or reuses a project folder at:
  - `/Users/daniyarserikson/Projects/<project-name>`
- Copies task description to `<project-root>/project.md`
- Bootstraps git if missing
- Creates a run id
- Starts Triad Conductor against that project folder

If your description file is named `project.md`, you can run:

```bash
/Users/daniyarserikson/Projects/triad-conductor/triad-start
```

Project name resolution order:
- `--project-name NAME` if provided
- first `# Heading` in the markdown file
- markdown filename without `.md`

Optional flags:

```bash
# Use explicit project folder name
/Users/daniyarserikson/Projects/triad-conductor/triad-start project.md --project-name Mukhtar.AI

# Override projects root
/Users/daniyarserikson/Projects/triad-conductor/triad-start project.md --projects-home /some/other/root

# Legacy behavior: run in current folder
/Users/daniyarserikson/Projects/triad-conductor/triad-start project.md --use-current-dir
```

You can also set the default projects root via env var:

```bash
export TRIAD_PROJECTS_HOME=/Users/daniyarserikson/Projects
```

## 1. Where to paste project description

Paste your project description into a Markdown file.

Recommended location:
- `tasks/my_project_description.md`

Template:
- `tasks/PROJECT_DESCRIPTION_TEMPLATE.md`

You can also pass any absolute path to `--task`.

## 2. How to execute (dry-run first)

From this repository root:

```bash
cd /Users/daniyarserikson/Projects/triad-conductor
./.venv/bin/python conductor.py run \
  --task tasks/my_project_description.md \
  --config config.yaml \
  --project-root /ABS/PATH/TO/YOUR/TARGET-PROJECT \
  --dry-run \
  --run-id dryrun_20260227_001
```

Notes:
- Dry-run uses canned example model outputs.
- Dry-run may finish as `BLOCKED` depending on examples in `examples/`.

## 3. Real execution

```bash
cd /Users/daniyarserikson/Projects/triad-conductor
./.venv/bin/python conductor.py run \
  --task tasks/my_project_description.md \
  --config config.yaml \
  --project-root /ABS/PATH/TO/YOUR/TARGET-PROJECT \
  --run-id run_20260227_001
```

## 4. Where to see results

After a run:
- `runs/<run_id>/state.json`
- `runs/<run_id>/input/task.md`
- `runs/<run_id>/artifacts/master_plan.json`
- `runs/<run_id>/artifacts/master_plan.md`
- `runs/<run_id>/artifacts/tests/`
- `runs/<run_id>/artifacts/review.json`
- `runs/<run_id>/artifacts/qa.json`
- `runs/<run_id>/artifacts/final_report.json` or `blocked_report.json`

## 5. Required prerequisites

- Your target project must be a local git repo.
- Base branch in `config.yaml` must exist in target repo (`project.base_branch`, default `main`).
- For real runs (not dry-run), CLIs must be available:
  - `claude`
  - `codex`
  - `gemini`

## 5.1 Permission automation (no human prompts)

By default, Triad Conductor now runs model CLIs in auto-approval mode:
- Claude: bypass permissions
- Codex: `-a never --sandbox workspace-write`
- Gemini: `--yolo --approval-mode yolo`

Optional env toggles:

```bash
# Disable auto permission bypass (go back to interactive-ish behavior)
export TRIAD_AUTOMATE_PERMISSIONS=0

# EXTREMELY DANGEROUS: Codex without sandbox + no approvals
export TRIAD_DANGEROUS_AUTONOMY=1
```

## 6. Quick troubleshooting

- Error: base branch not found  
Set `project.base_branch` in `config.yaml` to the correct branch in target repo.

- Run blocked at intake due security policy  
Task file path matched denylist in `config.yaml` -> `security.denylist_globs`.

- Merge/commit failures  
Ensure git identity is configured in target repo and repo is in a sane state.

## 7. Optional short alias (one-time setup)

Add this once to your shell profile (`~/.zshrc`):

```bash
alias triad-start='/Users/daniyarserikson/Projects/triad-conductor/triad-start'
```

Then from any project folder:

```bash
triad-start project.md
```
