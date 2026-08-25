---
name: hub-doc-pr-generator
description: Use when an engineer or tech writer wants to open a documentation PR in traefik/hub-doc (or amend a traefik/traefik PR with docs) — either from one or more implementation PRs, or from a GitHub issue alone when there is no implementation PR to point at. The issue-only path covers any case where a doc update is needed without a code change: a content gap or inconsistency a PM/writer/support filed directly, a QA finding closed as working-as-intended, a config/usage gotcha that never needed a fix. Invoke as `/hub-doc-pr-generator <pr-url|pr-number|issue-url>...`, or with no arg when checked out on the impl branch.
allowed-tools: "AskUserQuestion Read Bash(python3:*) Bash(git:*) Bash(gh:*) Bash(jq:*)"
---

# hub-doc-pr-generator

Turns implementation PRs into draft documentation PRs — or, when there's no
implementation PR at all, turns a plain GitHub issue describing a doc gap into
one instead (see step 1's issue-URL input form).

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

   **If the failure is specifically the Python-version check** and the output reports a
   discovered compatible interpreter (e.g. `Found a compatible interpreter:
   /opt/homebrew/bin/python3.11`), re-run the check with that exact path in place of
   `python3` to confirm it passes, then use that path — not the literal `python3` — for
   every `python3 -m scripts.X` command for the rest of this run. This may prompt for a
   one-time Bash permission approval for the new interpreter path, since it differs from
   the plugin's default `python3:*` allowlist — that's expected and much cheaper than
   rediscovering the path by hand every session.

1. **Parse inputs.** Resolve each argument to `{impl_repo, pr_number}`. Forms:
   - PR URL: `https://github.com/<owner>/<repo>/pull/<N>`
   - PR number: requires being inside the impl repo, or `--repo` flag
   - No-arg: auto-detect from current branch (`gh pr view --json number,headRepository`)
   - Issue URL, no PR: `https://github.com/<owner>/<repo>/issues/<N>` — use for **any**
     issue that should produce a doc update but has no implementation PR to fetch a diff
     from. This is broader than one scenario: a QA finding investigated and closed as
     working-as-intended, a config/usage gotcha that never needed a code fix, or — just
     as commonly — a content gap, inconsistency, or correction someone (a PM, support, a
     fellow writer) filed directly against the docs with no code involved at all. Nothing
     about this path is gated on the issue's labels, state, or who filed it —
     `fetch_issue.py` accepts any issue URL and hands it to the same pipeline. Step 2
     becomes `scripts.fetch_issue` instead of `scripts.fetch_pr`; every later step still
     runs, just against a bundle with no diff and no touched files (see step 2 for what
     that changes about confidence).
   - `--context <url>`: a supplementary reference (an issue URL, or a PR in a different repo)
     the engineer wants available as background — NOT a primary aggregation PR. Fetch it
     read-only (`gh issue view`/`gh pr view` as appropriate) for context in step 8's
     generation step; never subject it to the "same impl_repo" check below, never treat it
     as a diff source for the generated page, never count it toward multi-PR aggregation.
   Validate all PRs (excluding `--context` references) share the same `impl_repo`. If not, refuse.

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

2. **Fetch the PR bundle** — or the issue bundle, if step 1 resolved an issue-only input.
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.fetch_pr --pr <N> [--pr <M> ...] > /tmp/bundle.json
   ```
   Inspect `existing_doc_pr`; if non-null, ask the engineer `[u]pdate / [n]ew / [a]bort` via `AskUserQuestion`.

   **Issue-only input:** run `scripts.fetch_issue` instead —
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.fetch_issue --issue <url|N> [--repo <owner/name>] [--impl-repo <owner/name>] > /tmp/bundle.json
   ```
   The resulting bundle has `prs: []`, empty `merged.files_changed`, and an `issue` key
   carrying the issue's title/body/labels/state/comments — `classify.py` and
   `locate_targets.py` both already handle this shape (no diff to reason about, no
   touched-path signal), just with lower confidence than a PR-backed bundle. There's no
   `existing_doc_pr` check for this path.

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
     > /tmp/classify_full.json

   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.classify --bundle /tmp/bundle.json \
     --grounding /tmp/grounding.json $(printf -- '--neighbor %s ' "${neighbors[@]}") \
     --slim > /tmp/classify.json
   ```
   Run twice: `classify_full.json` keeps signals/rationale (step 6 needs them to explain a
   low-confidence pick); the `--slim` copy strips them for the LLM generation step, which
   doesn't need them. Both are otherwise identical and cheap to recompute.

6. **Confirm doc kind and target path (confidence-gated, never blocks).**

   Always auto-accept `doc_kind_candidates[0].kind` from `classify_full.json`. Log:
   `Auto-selected doc kind: <kind> (confidence: <N>)` — unconditional, not just when
   confident. The 0.85 threshold still exists, but only decides whether the pick gets
   flagged (below), never whether it blocks.

   Run locate_targets with the selected kind:
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.locate_targets \
     --impl-repo <repo> --doc-repo-root <path> --doc-kind <kind> \
     --feature-slug <slug> --touched-files ... --bundle /tmp/bundle.json > /tmp/locate.json
   ```
   `--bundle` lets locate_targets check the linked issue's own text for an existing page
   it already points to (a `doc.traefik.io/...` URL or a literal `docs/...` path) — when
   found and verified to exist, that page outranks any path-heuristic guess. A human
   naming the target is stronger evidence than inferring it from touched Go paths.

   Always auto-accept `candidates[0]`. Log: `Auto-selected path: <path> (confidence: <N>)`
   — same, unconditional. The 0.75 threshold likewise only gates the flag below.

   Write the low-confidence paper trail:
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.write_flags \
     --classify /tmp/classify_full.json --locate /tmp/locate.json > /tmp/flags.json
   ```
   `flags.json`'s `needs_verification_md` names what was picked below threshold, the
   runner-up that was passed over, and why — it's appended to `/tmp/pr-body.md` in step 8,
   alongside `preview.json`'s `manual_checks_md`.

   **If you (the agent) override a script's pick** — e.g. you have direct evidence a
   `locate_targets.py` candidate is wrong, beyond what `--bundle`'s issue-text scan already
   catches — don't hand-edit `flags.json`/`pr-body.md`. Re-run `write_flags` with
   `--override "<path-you-chose>:<why>"` (repeatable) so the override gets the same
   consistent PR-body treatment as an auto-flagged low-confidence pick, instead of being
   recorded ad hoc or not at all.

6b. **Re-sync neighbors if locate_targets disagreed with step 4's guess.**

   `locate.json`'s `candidates[0].neighbors` is computed from the CONFIRMED target
   directory (`propose_paths`/`select_neighbors`), which can differ from step 4's early
   guess — that one was made before `doc_kind` was even known, purely to give
   `classify.py`'s screenshot heuristic something to look at. If the two lists differ,
   re-extract structures from the confirmed list so step 7 never reads structural
   summaries for a different set of files than `locate.json` names:
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.extract_neighbor_structure \
     $(jq -r '.candidates[0].neighbors[]' /tmp/locate.json) > /tmp/neighbor_structures.json
   ```

6c. **Ask for the target release version (Hub only, when a release note is needed).**

   `docs/api-gateway/release-notes.mdx` is organized into per-version (semver) sections,
   not monthly ones (see `${CLAUDE_SKILL_DIR}/references/release-note-heuristics.md`) —
   there is no way to derive which Hub release this change ships in from the PR alone (no
   merge-date shortcut like the old month-based layout had). If `classify_full.json`'s
   `needs_release_note.verdict` is `yes`, ask once via `AskUserQuestion`:
   > "Which Hub release is this release note for? (e.g. v3.20.7)"

   Store the answer as `target_version`. Unlike step 6's picks, this is a genuinely
   unknowable fact rather than a confidence-gated guess, so it stays a real prompt.

   **If the engineer/tech writer doesn't know the version yet**, use `unassigned` as
   `target_version` — this PR writes a release-note *fragment* (see step 7), not the
   shared `release-notes.mdx` file directly, so there's no heading to park a placeholder
   on anymore. `release-notes-generator`'s `cut` command prompts interactively over
   unassigned fragments once a real version is confirmed, instead of requiring anyone to
   guess it here. This page's own Early Access callout (if the doc kind needs one — see
   `style-guide.md`'s "Early Access features" section) still uses the literal `vNEXT`
   placeholder for the same unknown-version case, since that text lives in a real page
   `preview.py` can grep — `check_placeholder_version` flags any `vNEXT` left in written
   files under "Manual checks required" in step 8.

7. **Generate.** This is the LLM step — no script. Read:
   - `/tmp/bundle.json` (the PR + diff, linked issues with their `parent`/`siblings`, and `merged.related_prs` — use the parent epic and sibling issues to understand the feature's intent and scope, not just the single PR's diff)
   - `/tmp/grounding.json` (concept fields)
   - `/tmp/classify.json` (release-note shape via `needs_release_note.proposed_shape`, target release version from step 6c's `target_version`, screenshot verdict)
   - `/tmp/locate.json` (target path + neighbors). **If `target_exists` is `true`**, the
     target path is an EXISTING page being extended, not a fresh create — Read its full
     current content before generating the `overwrite` edit. It is the file being changed,
     not a tone/structure reference, so the "don't read full neighbor pages" rule below
     does not apply to it: dropping existing rows/sections because they were never read is
     exactly the failure this guards against.
   - Template files from `${CLAUDE_SKILL_DIR}/templates/` (Hub or OSS depending on impl repo)
   - `/tmp/neighbor_structures.json` (structural summaries of neighbor pages — headings and first sentences). Do NOT read full neighbor pages; the summaries are sufficient for matching structure and tone. (This is about OTHER pages consulted for tone — see the `target_exists` carve-out above for the page actually being edited.)
   - `${CLAUDE_SKILL_DIR}/references/style-guide.md` **Tier 1 — Core rules** (always load). Additionally load on demand:
     - `## Procedure pages` section — if doc kind is a how-to guide or tutorial
     - `## Screenshots and media` section — if `classify.needs_screenshots.verdict == "yes"`
     - `## Tables` section — if the page will include a parameter table, **or** `target_exists` is `true` and the existing page has one being extended (enumerate every row — see that section's completeness rule; `preview.py` also mechanically flags "…"/"etc." placeholders in step 8)
     - `## Early Access features` section — if `classify.needs_release_note.proposed_shape == "ea-subsection"`. Use `locate.json`'s `target_exists` to pick sidebar-badge-plus-top-of-page-callout (`false`, brand-new topic) vs. inline-heading-badge-plus-callout-under-it (`true`, existing page). State `target_version` in the callout (or the `vNEXT` placeholder if step 6c's answer was `unassigned`).
   - `${CLAUDE_SKILL_DIR}/references/<convention>.md` files on demand (hub-doc-conventions, oss-doc-conventions, release-note-heuristics)

   Produce a JSON file `/tmp/edits.json` shaped:
   ```json
   [
     {"path": "docs/...", "content": "...", "mode": "create"},
     {"path": "sidebars.js", "content": "<full new file>", "mode": "overwrite"},
     {"path": "docs/api-gateway/release-notes.d/_<pr-number>-<feature-slug>.mdx", "content": "<fragment>", "mode": "create"}
   ]
   ```
   The release-note edit is a **fragment file**, never a `release-notes.mdx` overwrite — see
   `${CLAUDE_SKILL_DIR}/references/release-note-heuristics.md` ("Where the entry goes") for
   why per-PR full-file overwrites were removed. Use
   `${CLAUDE_SKILL_DIR}/templates/release-note-fragment.mdx.tmpl` for the front matter
   wrapper and the matching shape template (`release-note-ea.mdx.tmpl` etc., picked per
   `${CLAUDE_SKILL_DIR}/references/release-note-heuristics.md`'s shape-selection table) for
   the body. The filename MUST start with a leading underscore —
   `_<pr-number>-<feature-slug>.mdx` — so Docusaurus's default `**/_*.{md,mdx}` exclude glob
   skips the fragment during the docs build (fragments contain relative links written for
   their *post-assembly* location one directory up, which don't resolve from the fragment's
   own location — omitting the underscore breaks the site build, see
   `release-note-heuristics.md`). `<pr-number>` is the primary PR's number
   (`bundle.json → merged.primary_pr`); `<feature-slug>` is the same slug used for the page
   path. Set the fragment's `compat:` front-matter field only when the diff/grounding
   clearly shows a component version bump (e.g. a Traefik Proxy dependency update) — leave
   it out otherwise, don't guess a value. **Skip release notes entirely for OSS impl repos.**

   Also render the PR body: read `${CLAUDE_SKILL_DIR}/templates/pr-body.md.tmpl` (its inline
   comments cover the exact shape expected for each section) and fill in the feature title,
   source PR numbers (`bundle.json → prs[].number`), a 2-3 sentence summary of which files
   changed and why in plain language, one `Closes:` line per issue in
   `bundle.merged.linked_issues`/`sub_issues`, and the reviewer checklist from the template.
   Write the rendered result to `/tmp/pr-body.md`. (This file is consumed by `open_pr.py` in
   step 10.)

   **Before finalizing `/tmp/edits.json`**, if the page adds a row to an existing table for
   a value with documented siblings (see style-guide.md's Tables section), re-check: are
   the siblings each on their own row, or grouped under one umbrella entry? Match whatever
   the table already does — don't introduce a new row granularity it doesn't use elsewhere.
   This is a quick self-consistency pass against the page's own existing conventions, not a
   new research step.

8. **Preview.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.preview \
     --repo-path <doc-repo> --impl-repo <impl-repo> --branch <branch> \
     --edits /tmp/edits.json > /tmp/preview.json
   ```
   `preview.py` runs a lint auto-fix pass before computing the diff: file permissions are
   corrected and (Hub only) markdownlint `--fix` resolves what's mechanical, fully
   automatically — never asks the engineer to confirm a fix. Both markdownlint and alex
   are scoped to only the files this run actually wrote, never the whole doc repo.
   Whatever it can't fix locally (alex inclusive-language flags, remaining markdownlint
   errors, `mkdocs build --strict` failures for OSS) comes back in `lint_unresolved` and
   never blocks the pipeline — there is no re-prompt on lint state.

   If `preview.py` ever raises a `GitError` mentioning a stash-pop conflict (a stale
   leftover from before this scoping fix, or from an unrelated in-progress edit in the
   clone), recover with `git checkout -- . && git stash drop` in the doc repo, then retry
   — the error message itself says this.

   `preview.py` also mechanically flags table rows abbreviated with "…"/"etc." (see the
   Tables completeness rule) — those surface in `lint_unresolved`/`manual_checks_md` too,
   no separate check needed.

   Append `flags.json`'s `needs_verification_md` (from step 6) and `preview.json`'s
   `manual_checks_md` to `/tmp/pr-body.md` now, before step 10 — both are plain string
   appends, not an LLM step, so these sections never depend on the generation step
   remembering to include them:
   ```bash
   python3 -c "
   import json
   parts = []
   flags = json.load(open('/tmp/flags.json'))
   if flags.get('needs_verification_md'):
       parts.append(flags['needs_verification_md'])
   preview = json.load(open('/tmp/preview.json'))
   if preview.get('manual_checks_md'):
       parts.append(preview['manual_checks_md'])
   if parts:
       open('/tmp/pr-body.md', 'a').write(''.join(parts))
   "
   ```

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

Use it for: edit-loop choices (step 9), push confirmation (step 10). Each renders a labelled option list instead of a free-form y/N. Step 6 (doc kind / target path) never asks anymore — it always auto-accepts the top candidate and, when confidence is below threshold, records the pick in the PR body's "Needs verification" section instead of prompting.
