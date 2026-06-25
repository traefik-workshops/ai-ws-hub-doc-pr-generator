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

0. **Preflight (universal gate).** Verify Python and `gh` before anything else. This phase is flow-independent — it does **not** require a hub-doc clone (that's checked in step 1, once the impl repo is known) — and it must pass first because PR auto-detection in step 1 shells out to `gh`:
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.setup --check
   ```
   If it exits non-zero, the error message says exactly what to fix (`gh auth login`, etc.). Stop here.

1. **Parse inputs.** Resolve each argument to `{impl_repo, pr_number}`. Forms:
   - PR URL: `https://github.com/<owner>/<repo>/pull/<N>`
   - PR number: requires being inside the impl repo, or `--repo` flag
   - No-arg: auto-detect from current branch (`gh pr view --json number,headRepository`)
   Validate all PRs share the same `impl_repo`. If not, refuse.

   Once `impl_repo` is known, provision the flow's resources (only now is this knowable):
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.setup --check --impl-repo <impl_repo>
   ```
   - **Hub** (`traefik/traefik-hub`): verifies a local hub-doc clone (+ clean-tree advisory). If it exits non-zero because the clone is missing, run the interactive provisioner once to discover/clone/persist it, then re-run the check:
     ```bash
     PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.setup --impl-repo traefik/traefik-hub
     ```
   - **OSS** (`traefik/traefik`): confirms cwd is the impl repo (where the doc commit lands). No hub-doc clone is required, so an OSS-only engineer is never blocked on one.
   Only proceed once it exits 0.

2. **Fetch the PR bundle.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.fetch_pr --pr <N> [--pr <M> ...] > /tmp/bundle.json
   ```
   Inspect `existing_doc_pr`; if non-null, ask the engineer `[u]pdate / [n]ew / [a]bort` via `AskUserQuestion`.

   The bundle gathers issue context in both directions: each linked issue carries its `parent` epic (with body) and `siblings` (the parent's other sub-issues), and `merged.related_prs` lists the other PRs that implement the same feature (the PRs closing the linked issue and its siblings). Use this for the *why* behind the feature in step 8. If a `related_prs` entry looks load-bearing for the docs and the bundle's diff isn't enough, fetch that specific PR with `PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.fetch_pr --pr <related-N>` — don't pull them all by default.

3. **Fetch grounding.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.fetch_grounding --impl-repo "$(jq -r '.impl_repo' /tmp/bundle.json)" --touched-files $(jq -r '.merged.files_changed[].path' /tmp/bundle.json) > /tmp/grounding.json
   ```

4. **Compute neighbor paths and extract structural summaries.**

   Find 3–5 neighbor pages by listing the likely target directory in the doc repo. Infer the sub-directory from the PR's touched file paths and title:

   - **Hub** (`traefik/traefik-hub`): docs live under `<hub-doc-root>/docs/`. Common mappings:
     - Middleware / config Go code → `docs/api-gateway/middlewares/`
     - Dashboard / portal UI code → `docs/api-gateway/dashboard/` or `docs/api-gateway/portal/`
     - Ingress / routing code → `docs/api-gateway/routing/`
     - When unsure, list `docs/api-gateway/` and pick from there.
   - **OSS** (`traefik/traefik`): docs live under `docs/content/`. Use the same category inference.

   List the inferred directory:
   ```bash
   ls <doc-repo-root>/docs/<likely-category>/
   ```
   Pick the 3–5 `.md` / `.mdx` files closest in topic to the feature. Store their absolute paths in `neighbors`.

   Extract structural summaries:
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.extract_neighbor_structure \
     ${neighbors[@]} > /tmp/neighbor_structures.json
   ```

   The `neighbors` array is reused in step 5.

5. **Classify.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.classify --bundle /tmp/bundle.json \
     --grounding /tmp/grounding.json $(printf -- '--neighbor %s ' "${neighbors[@]}") \
     --slim > /tmp/classify.json
   ```
   The `--slim` flag strips the internal signals/rationale arrays — the LLM does not need them.

6. **Confirm doc kind and target path (confidence-gated).**

   Read `classify.json`:
   - If `confidence >= 0.85`: auto-accept `doc_kind_candidates[0].kind` silently. Log: `Auto-selected doc kind: <kind> (confidence: <N>)`.
   - If `confidence < 0.85`: confirmation required — see the `AskUserQuestion` prompt below.

   Run locate_targets with the selected kind:
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.locate_targets \
     --impl-repo <repo> --doc-repo-root <path> --doc-kind <kind> \
     --feature-slug <slug> --touched-files ... > /tmp/locate.json
   ```

   Read `locate.json`:
   - If `candidates[0].confidence >= 0.75`: auto-accept silently. Log: `Auto-selected path: <path> (confidence: <N>)`.
   - If `candidates[0].confidence < 0.75`: confirmation required — see the `AskUserQuestion` prompt below.

   If either needs confirmation, ask once via `AskUserQuestion` covering both in a single prompt:
   > "I'll create `<path>` as a `<kind>` page — confirm, change kind, or change path?"
   - `[y]` confirm both
   - `[k]` change kind (show the other candidate)
   - `[p]` custom path

7. **Generate.** This is the LLM step — no script. Read:
   - `/tmp/bundle.json` (the PR + diff, linked issues with their `parent`/`siblings`, and `merged.related_prs` — use the parent epic and sibling issues to understand the feature's intent and scope, not just the single PR's diff)
   - `/tmp/grounding.json` (concept fields)
   - `/tmp/classify.json` (release-note shape via `needs_release_note.proposed_shape`, target month via `needs_release_note.target_month`, screenshot verdict)
   - `/tmp/locate.json` (target path + neighbors)
   - Template files from `${CLAUDE_SKILL_DIR}/templates/` (Hub or OSS depending on impl repo)
   - For Hub: locate the target month's section in `docs/api-gateway/release-notes.mdx` by running:
     ```bash
     grep -n "## <target_month>\|### What's New\|#### Graduated to GA" \
       <doc-repo>/docs/api-gateway/release-notes.mdx | head -20
     ```
     Then read only that section (typically 30–60 lines) with the Read tool, not the full file. If the target month heading doesn't exist, read the first 30 lines to understand the file structure and create the heading. The new entry goes **on top, never at the bottom** — see `${CLAUDE_SKILL_DIR}/references/release-note-heuristics.md` ("Insertion order").
   - `/tmp/neighbor_structures.json` (structural summaries of neighbor pages — headings and first sentences). Do NOT read full neighbor pages; the summaries are sufficient for matching structure and tone.
   - `${CLAUDE_SKILL_DIR}/references/style-guide.md` **Tier 1 — Core rules** (always load). Additionally load on demand:
     - `## Procedure pages` section — if doc kind is a how-to guide or tutorial
     - `## Screenshots and media` section — if `classify.needs_screenshots.verdict == "yes"`
     - `## Tables` section — only if the page will include a parameter table
   - `${CLAUDE_SKILL_DIR}/references/<convention>.md` files on demand (hub-doc-conventions, oss-doc-conventions, release-note-heuristics)

   Produce a JSON file `/tmp/edits.json` shaped:
   ```json
   [
     {"path": "docs/...", "content": "...", "mode": "create"},
     {"path": "sidebars.js", "content": "<full new file>", "mode": "overwrite"},
     {"path": "docs/api-gateway/release-notes.mdx", "content": "<full new file>", "mode": "overwrite"}
   ]
   ```
   For each release-note shape (see `${CLAUDE_SKILL_DIR}/references/release-note-heuristics.md`), pick the right template and instantiate it. **Skip release notes entirely for OSS impl repos.**

   Also render the PR body: read `${CLAUDE_SKILL_DIR}/templates/pr-body.md.tmpl`, fill in the feature title, source PR numbers (`bundle.json → prs[].number`), a one-paragraph summary of what the new or updated docs cover, the linked issue numbers, and the reviewer checklist from the template. Write the rendered result to `/tmp/pr-body.md`. (This file is consumed by `open_pr.py` in step 10.)

8. **Preview.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.preview \
     --repo-path <doc-repo> --impl-repo <impl-repo> --branch <branch> \
     --edits /tmp/edits.json > /tmp/preview.json
   ```
   If `lint_ok` is false, surface `lint_errors` and force a re-prompt.

   Present the result to the engineer (the default run above stages the files; this is display-only):
   - **If `preview.json`'s `pretty_tools.diff` or `pretty_tools.page` is non-null**, the engineer has `delta`/`glow`/`bat` installed — run the render mode so its colorized output shows directly in the terminal:
     ```bash
     PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.preview \
       --repo-path <doc-repo> --impl-repo <impl-repo> --branch <branch> \
       --edits /tmp/edits.json --render
     ```
   - **Otherwise** (no tools), present it yourself with no dependency: show `diff_stat` and `diff` inside a ` ```diff ` fenced block (Claude Code highlights +/− lines), then show each new/changed `.md`/`.mdx` page's content as rendered markdown (not fenced) so the engineer sees the formatted page.

9. **Edit loop.** Use `AskUserQuestion`:
    - `[1] push`
    - `[2] re-prompt with notes` → engineer types feedback; regenerate affected files (step 7 again with the feedback in context); back to step 8
    - `[3] save and exit (no push)`

10. **Push.**
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

Use it for: combined kind/path confirmation when confidence is below threshold (step 6), edit-loop choices (step 9), push confirmation (step 10). Each renders a labelled option list instead of a free-form y/N. Do not ask when the classifier is confident — let the pipeline proceed automatically and log what was auto-selected.
