---
name: hub-doc-pr-generator
description: Use when an engineer or tech writer wants to open a documentation PR in traefik/hub-doc (or amend a traefik/traefik PR with docs) from one or more implementation PRs. Invoke as `/hub-doc-pr-generator <pr-url|pr-number>...` or with no arg when checked out on the impl branch.
allowed-tools: "AskUserQuestion Read Bash(python3:*) Bash(git:*) Bash(gh:*) Bash(jq:*)"
---

# hub-doc-pr-generator

Turns implementation PRs into draft documentation PRs.

## Bundled resources

The Python helpers, templates, and reference catalogs ship inside this skill directory, referenced via `${CLAUDE_SKILL_DIR}` (Claude Code expands this to the skill's absolute path):

- Scripts: `${CLAUDE_SKILL_DIR}/scripts/` — invoked as a package, so every command below is prefixed with `PYTHONPATH="${CLAUDE_SKILL_DIR}"`
- Templates: `${CLAUDE_SKILL_DIR}/templates/`
- Reference catalogs: `${CLAUDE_SKILL_DIR}/references/`

Never `cd` into the skill directory — the engineer's cwd is their own repo. Always use the `${CLAUDE_SKILL_DIR}`-anchored paths above and `git -C <path>` for git operations.

## Routing

- `traefik/traefik-hub` → draft PR in `traefik/hub-doc` from the engineer's fork
- `traefik/traefik` → new commit appended to the impl PR branch (docs are in-repo for OSS)
- Anything else → refuse with `unsupported impl repo: <owner>/<name>`

For multi-PR aggregation: all PRs must be in the same impl repo. Cross-repo invocations are refused.

## Required environment

- `gh` CLI on PATH, authenticated (`gh auth status` succeeds)
- Python 3.11+
- Local clone of `traefik/hub-doc` somewhere on disk (only when the impl repo is `traefik/traefik-hub`)

The skill auto-discovers the hub-doc clone in this order:

1. `$HUB_DOC_PATH` env var (escape hatch)
2. Persisted answer at `~/.config/hub-doc-pr-generator/config.json` (filled after the first prompt)
3. Sibling directories of cwd (walks up to depth 5 looking for `hub-doc/`)
4. Common workspace dirs (`~/code`, `~/dev`, `~/src`, `~/Developer`, `~/workspace`, `~/projects`, `~/git`) one level deep plus one nested level

If none match, the orchestrator asks via `AskUserQuestion` and saves the answer for next time.

For the OSS flow (`traefik/traefik`), no path is needed — the engineer invokes the skill from the impl PR branch, so `cwd`'s git root IS the impl repo.

## Pipeline (the agent follows this checklist)

0. **Preflight.** Run `gh auth status` via Bash. If it fails, stop and tell the engineer to run `gh auth login`.

   For the Hub flow: discover the hub-doc clone via `PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts._discover hub-doc`. If it exits non-zero, ask the engineer via `AskUserQuestion` for the path (offer a "create a fresh clone in ~/code/hub-doc" option that runs `gh repo clone traefik/hub-doc`). Persist the answer with `PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts._discover save-hub-doc <path>`. Confirm the working tree is clean (`git -C <path> status --porcelain`); if dirty, ask the engineer to stash/commit.

   For the OSS flow: discover the impl repo via `PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts._discover oss` (uses cwd). Confirm clean working tree.

1. **Parse inputs.** Resolve each argument to `{impl_repo, pr_number}`. Forms:
   - PR URL: `https://github.com/<owner>/<repo>/pull/<N>`
   - PR number: requires being inside the impl repo, or `--repo` flag
   - No-arg: auto-detect from current branch (`gh pr view --json number,headRepository`)
   Validate all PRs share the same `impl_repo`. If not, refuse.

2. **Fetch the PR bundle.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.fetch_pr --pr <N> [--pr <M> ...] > /tmp/bundle.json
   ```
   Inspect `existing_doc_pr`; if non-null, ask the engineer `[u]pdate / [n]ew / [a]bort` via `AskUserQuestion`.

3. **Fetch grounding.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.fetch_grounding --touched-files $(jq -r '.merged.files_changed[].path' /tmp/bundle.json) > /tmp/grounding.json
   ```

4. **Compute neighbor paths for classification** by scanning a likely candidate directory in the doc repo. The neighbor list is also reused in step 6.

5. **Classify.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.classify --bundle /tmp/bundle.json --grounding /tmp/grounding.json $(printf -- '--neighbor %s ' "${neighbors[@]}") > /tmp/classify.json
   ```

6. **Ask the engineer for the doc kind.** Show `doc_kind_candidates[0]` with its rationale via `AskUserQuestion`:
   - `[c]` confirm AI pick
   - `[s]` swap (pick the other candidate)
   - `[d]` you decide (pick higher confidence)
   - `[p]` custom path

7. **Locate targets.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.locate_targets \
     --impl-repo <repo> --doc-repo-root <path> --doc-kind <kind> \
     --feature-slug <slug> --touched-files ... > /tmp/locate.json
   ```
   Show the top candidate; confirm or accept a custom path.

8. **Generate.** This is the LLM step — no script. Read:
   - `/tmp/bundle.json` (the PR + issues + diff)
   - `/tmp/grounding.json` (concept fields)
   - `/tmp/classify.json` (release-note shape, screenshot verdict)
   - `/tmp/locate.json` (target path + neighbors)
   - Template files from `${CLAUDE_SKILL_DIR}/templates/` (Hub or OSS depending on impl repo)
   - For Hub: last ~150 lines of `docs/api-gateway/release-notes.mdx` (so you know the current month section)
   - Up to 3 neighbor pages in full (read with the Read tool)
   - `${CLAUDE_SKILL_DIR}/references/<convention>.md` files on demand

   Produce a JSON file `/tmp/edits.json` shaped:
   ```json
   [
     {"path": "docs/...", "content": "...", "mode": "create"},
     {"path": "sidebars.js", "content": "<full new file>", "mode": "overwrite"},
     {"path": "docs/api-gateway/release-notes.mdx", "content": "<full new file>", "mode": "overwrite"}
   ]
   ```
   For each release-note shape (see `${CLAUDE_SKILL_DIR}/references/release-note-heuristics.md`), pick the right template and instantiate it. **Skip release notes entirely for OSS impl repos.**

9. **Preview.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.preview \
     --repo-path <doc-repo> --impl-repo <impl-repo> --branch <branch> \
     --edits /tmp/edits.json > /tmp/preview.json
   ```
   Print the `diff_stat` and `diff` to the engineer. If `lint_ok` is false, surface `lint_errors` and force a re-prompt.

10. **Edit loop.** Use `AskUserQuestion`:
    - `[1] push`
    - `[2] re-prompt with notes` → engineer types feedback; regenerate affected files (step 8 again with the feedback in context); back to step 9
    - `[3] save and exit (no push)`

11. **Push.**
    - **Hub:**
      ```bash
      PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.open_pr hub --doc-repo-root <path> --branch <branch> \
        --title "docs: <feature title>" --body-file /tmp/pr-body.md
      ```
    - **OSS (single):**
      ```bash
      PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.open_pr oss --impl-repo-root <path> \
        --title "<feature title>" --doc-file docs/content/... [--doc-file ...]
      ```
    - **OSS (multi):** same as single, plus `--ref-pr <N>` for each non-primary PR. Ensure the primary PR's branch is checked out first via `gh pr checkout <primary>`.

## Confirmation gates

- Never push without explicit `y` from the engineer
- Never `--force` or `--force-with-lease`
- Never `git commit --amend`
- If `gh auth status` fails: stop with `gh auth login` instructions

## When to use the AskUserQuestion tool

Use it for: kind selection (step 6), candidate-path confirmation (step 7), edit-loop choices (step 10), push confirmation (step 11). Each renders a labelled option list instead of a free-form y/N.
