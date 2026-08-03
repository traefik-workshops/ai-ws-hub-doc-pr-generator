---
name: release-notes-generator
description: Use when drafting the traefik/hub-doc release-notes.mdx entry for one or more just-tagged Traefik Hub patch releases. Invoke as `/release-notes-generator <tag> [<tag> ...]`, e.g. `/release-notes-generator v3.19.13 v3.20.8`. Pulls the commit range from GitHub instead of a hand-pasted changelog, dedups fixes shared across lines that release close together, and fills the compatibility matrix from go.mod/traefik.version/traefik-helm-chart instead of carrying forward the previous entry's numbers.
allowed-tools: "AskUserQuestion Read Bash(python3:*) Bash(git:*) Bash(gh:*) Bash(jq:*)"
---

# release-notes-generator

Turns one or more Traefik Hub release tags into a draft release-notes.mdx PR.

## Why this is a separate skill from hub-doc-pr-generator

The sibling `hub-doc-pr-generator` skill turns a single implementation PR into
a feature doc page — its whole pipeline (fetch PR → classify doc kind →
locate target page → find neighbor pages for tone) exists to answer "given
this PR, what page does it touch and what should that page say?" A patch
release doesn't have any of that: there's no single PR, no target-page
guessing (it's always `docs/api-gateway/release-notes.mdx`), and the actual
work — diffing a commit range between two tags, working out which commits are
shared between two release lines vs. unique to one, and pulling version
numbers out of `go.mod` and a separate `traefik-helm-chart` repo — has almost
no overlap with that pipeline. Forcing it through the same steps would mean
threading a parallel special case through nearly all of them for little
shared logic.

## Shared code (duplicated for now, by design)

`scripts/_gh.py`, `_git.py`, and the shape of `setup.py`/`_discover.py` are
copied from the sibling skill rather than imported — each Claude Code skill
gets `${CLAUDE_SKILL_DIR}` pointed at its own directory, so there's no clean
way to share a Python package across skill directories without a plugin-level
`lib/` and updating both skills' invocation lines to a wider `PYTHONPATH`.
That's a reasonable follow-up once both skills are being touched in the same
pass — worth doing then, not as a side effect of adding this one. Until then:
if you change `_git.py`/`_gh.py` behavior in one skill, check whether the copy
here needs the same fix.

`references/style-guide.md` and `references/hub-doc-conventions.md` are
**not** copied — step 6 below reads the sibling skill's copies directly by
path, since those are Hub-doc-wide style rules, not PR-generator-specific.

## Bundled resources

- Scripts: `${CLAUDE_SKILL_DIR}/scripts/` — invoked as a package: every
  command below is prefixed with `PYTHONPATH="${CLAUDE_SKILL_DIR}"`
- Templates: `${CLAUDE_SKILL_DIR}/templates/`
- Reference catalogs: `${CLAUDE_SKILL_DIR}/references/`
- Sibling skill's style references (read, not copied):
  `${CLAUDE_SKILL_DIR}/../hub-doc-pr-generator/references/style-guide.md`
  `${CLAUDE_SKILL_DIR}/../hub-doc-pr-generator/references/hub-doc-conventions.md`
  `${CLAUDE_SKILL_DIR}/../hub-doc-pr-generator/references/release-note-heuristics.md`
  (for the general per-version file structure and insertion-order rule this
  skill's `render_entry.py` enforces mechanically)

Never `cd` into the skill directory. Always use `${CLAUDE_SKILL_DIR}`-anchored
paths and `git -C <path>` for git operations.

## Scope

Always targets `traefik/hub-doc`'s `docs/api-gateway/release-notes.mdx`.
Always sources commits from `traefik/traefik-hub` (hardcoded `REPO` in
`fetch_release_range.py`). There's no OSS equivalent — Traefik Proxy patch
releases aren't documented in this file, so this skill has no OSS flow to
route to, unlike the sibling skill. A tag that doesn't exist in
`traefik/traefik-hub` (e.g. a Proxy-only version) fails naturally at step 2
with a 404 from `fetch_release_range.py` — no separate validation needed.

## Required environment

- `gh` CLI on PATH, authenticated (`gh auth status` succeeds)
- Python 3.11+
- Local clone of `traefik/hub-doc` somewhere on disk

Same discovery order and same persisted config file as the sibling skill
(`~/.config/hub-doc-pr-generator/config.json`) — if you've already configured
that clone path for `hub-doc-pr-generator`, this skill finds it too.

## Pipeline

0. **Preflight.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.setup --check
   ```
   If it exits non-zero, the error message says exactly what to fix. If the
   hub-doc clone isn't found, run the interactive provisioner once:
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.setup
   ```

1. **Fetch the commit range(s).** One `--tag` per release tag being drafted
   (repeatable for a combined entry):
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.fetch_release_range \
     --tag v3.19.13 --tag v3.20.8 > /tmp/range.json
   ```
   This resolves each tag's previous tag on the same X.Y line automatically
   and pulls the commit list via GitHub's compare API — no more hand-pasting
   a raw changelog. If it errors because no earlier tag was found on that
   line (first patch after a branch cut, or a gap in tag history), ask the
   engineer for the right base and re-run with
   `--prev-tag <tag>:<prev>` for the affected tag(s).

2. **Classify commits.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.classify_commits \
     --range /tmp/range.json > /tmp/classified.json
   ```
   Drops branch-merge and lint-only commits automatically; excludes
   test/CI-only commits after checking their touched files. See
   `references/commit-noise-heuristics.md` — some commits that survive this
   pass (confidence 0.6, e.g. test-infra fixes, internal process docs) are
   real but arguably not customer-facing. These are deterministically captured
   in `classified.json`'s own `needs_verification_md` field (not left to step 6
   to remember) — step 9 appends it to the PR body alongside `manual_checks_md`.

3. **Dedup across tags.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.dedup_versions \
     --classified /tmp/classified.json > /tmp/dedup.json
   ```
   Computes the shared-vs-per-tag-only split by commit SHA and recommends
   whether to combine into one heading (`"combine": true/false` plus
   `"reason"`). **Only relevant when 2+ tags were given.**

4. **Confirm the combine decision (2+ tags only).** This determines the whole
   document's structure — one heading vs. two — so it's never auto-applied
   silently, unlike the sibling skill's confidence-gated doc-kind/path picks.
   Use `AskUserQuestion`, showing `dedup.json`'s `reason`:
   - `[1] combine into one entry ("vX.Y.Z & vA.B.C")`
   - `[2] keep as separate entries`
   If the engineer picks separate entries, treat each tag as its own
   single-tag pass through steps 5–9 (no `only`/`shared` split, no "vX.Y.Z
   only:" prefixes — every included commit for that tag is just a bullet).

5. **Compatibility matrix.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.compat_matrix \
     --tag v3.19.13 --tag v3.20.8 > /tmp/compat.json
   ```
   Reads `go.mod` and `hub/pkg/version/traefik.version` at each tag directly
   — never carries forward the previous release's numbers (see
   `references/compat-matrix-sources.md` for why: a real past draft carried
   forward a stale Kubernetes Gateway API version this way). `helm_chart` and
   `static_analyzer` can legitimately come back `{"version": null, "note":
   "..."}` — that's not a bug, it means the value isn't known yet. Carry the
   `note` into the PR body's TBD checklist in step 8; never fill in a number
   the script didn't return.

6. **Generate.** This is the LLM step — no script decides bullet wording.
   Read:
   - `/tmp/classified.json` and `/tmp/dedup.json` (which commits, shared vs.
     per-tag-only, and any confidence < 1.0 items to flag)
   - `/tmp/compat.json` (compatibility-matrix values, including any TBD notes)
   - `${CLAUDE_SKILL_DIR}/templates/release-note-patch.mdx.tmpl` (read the
     comment at the top for the single-tag vs. combined-entry shape)
   - `${CLAUDE_SKILL_DIR}/../hub-doc-pr-generator/references/style-guide.md`
     Tier 1 — Core rules
   - `${CLAUDE_SKILL_DIR}/../hub-doc-pr-generator/references/hub-doc-conventions.md`
     for MDX admonition/heading conventions
   - The current top of `docs/api-gateway/release-notes.mdx` in the hub-doc
     clone (first ~30 lines, to confirm nothing about the file's preamble has
     changed) — do not read the whole file; `render_entry.py` in step 7
     handles the splice mechanically

   Write each classified/deduped commit as one flat bullet under
   `### Bug fixes` — no bolded subsection headers (no "API management" / "LLM
   Guard" / etc.) and no separate `### Security` section; those only exist in
   the sibling skill's feature templates. Prefix version-specific bullets
   `vX.Y.Z only:` / `vX.Y.Z:` per the template. Write the wording from the
   commit subject and your understanding of what it actually does — don't
   just retitle-case the raw subject line, and don't invent behavior the
   commit doesn't describe.

   Write the new entry to `/tmp/new-entry.mdx`.

7. **Splice into release-notes.mdx.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.render_entry \
     --release-notes <hub-doc-root>/docs/api-gateway/release-notes.mdx \
     --entry /tmp/new-entry.mdx | jq -r '.content' > /tmp/full-content.mdx
   ```
   Always inserts above the first existing `## Gateway v...` heading —
   mechanical, not a generation-step judgment call (see
   `render_entry.py`'s docstring).

8. **Render the PR body.** Read `${CLAUDE_SKILL_DIR}/templates/pr-body.md.tmpl`
   and fill in: source tags, shared/per-tag-only counts from `/tmp/dedup.json`,
   and a checklist item for every `null`-valued row in `/tmp/compat.json`
   (e.g. "Helm Chart version for v3.20.8: <note from compat.json>"). Write to
   `/tmp/pr-body.md`.

9. **Preview.**
   ```bash
   PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.preview \
     --repo-path <hub-doc-root> --branch <branch> --content-file /tmp/full-content.mdx \
     > /tmp/preview.json
   ```
   Runs `yarn docs:markdown --fix` automatically, flags what it can't fix
   (`docs:markdown`/`docs:alex` failures, truncated-looking table rows) in
   `manual_checks_md`.

   Append both `manual_checks_md` and `classified.json`'s `needs_verification_md` (from
   step 2's confidence-flagged commits) to `/tmp/pr-body.md` now — a plain string append,
   not an LLM step, so the reviewer checklist's "(see 'Needs verification' below, if
   present)" line always has something real to point to instead of depending on step 6
   remembering to write it:
   ```bash
   python3 -c "
   import json
   parts = []
   classified = json.load(open('/tmp/classified.json'))
   if classified.get('needs_verification_md'):
       parts.append(classified['needs_verification_md'])
   preview = json.load(open('/tmp/preview.json'))
   if preview.get('manual_checks_md'):
       parts.append(preview['manual_checks_md'])
   if parts:
       open('/tmp/pr-body.md', 'a').write(''.join(parts))
   "
   ```

   Present the result:
   - If `pretty_tools.diff` is non-null (`delta` installed), re-run with
     `--render` for a colorized diff in the terminal.
   - Otherwise, show `diff_stat` and `diff` in a ` ```diff ` fenced block,
     then the new entry's rendered markdown.

10. **Edit loop.** `AskUserQuestion`:
    - `[1] push`
    - `[2] re-prompt with notes` → back to step 6 with the feedback in context
    - `[3] save and exit (no push)`

11. **Push.**
    ```bash
    PYTHONPATH="${CLAUDE_SKILL_DIR}" python3 -m scripts.push \
      --doc-repo-root <hub-doc-root> --branch <branch> \
      --title "docs: release notes for v3.20.8 & v3.19.13" --body-file /tmp/pr-body.md
    ```

## Confirmation gates

- Never push without explicit `y` from the engineer
- Never `--force` or `--force-with-lease`
- Never `git commit --amend`
- If `gh auth status` fails: stop with `gh auth login` instructions
- Never fill in a compatibility-matrix value the scripts reported as
  unknown/`null` — surface it as a TBD checklist item instead

## When to use the AskUserQuestion tool

- Step 4: combine vs. separate entries — always asked when 2+ tags are given,
  regardless of confidence, because it decides document structure
- Step 10: edit-loop choice
- Step 11: push confirmation
