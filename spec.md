# Spec: `ai-ws-hub-doc-pr-generator` — Auto-author Traefik Hub & OSS doc PRs from impl PRs

## 1. Context

Today, when a Traefik engineer ships a feature in `traefik/traefik-hub` (or a doc-worthy change in `traefik/traefik` OSS), the corresponding documentation PR is filed manually — often days or weeks later, often by a different person, and often with stale or partial coverage of the feature's real surface area. Tech writers re-read the impl PR, the linked issues, and the diff to figure out what changed; pages get filed in the wrong section; release notes get forgotten; sidebar registrations get missed; screenshots are skipped because no one remembers which sections expect them.

This skill collapses that loop. An engineer (or tech writer) on the impl PR runs `/<skill>`. The skill:

1. Pulls the impl PR + linked issues + sub-issues + diff
2. Pulls grounding from `traefik/reference` (concept registry → narrative-doc mapping)
3. Classifies the change (release-note worthy? UI feature needing screenshots? user guide or reference?)
4. Drafts the doc page following the conventions of neighbor pages
5. Registers it in nav + (when warranted) appends a release-notes entry + (when warranted) inserts screenshot placeholders
6. Previews everything as a `git diff` in the terminal
7. Lets the engineer re-prompt Claude with feedback until happy
8. Opens a **draft** doc PR in `traefik/hub-doc` (Hub flow) or adds a commit to the impl PR branch (OSS flow)

Intended outcome: a draft doc PR (or doc commit) that's good enough to need only review and screenshot capture — not "good enough to need a full rewrite".

## 2. Scope

**In scope (v1):**
- Doc page generation (markdown + front matter)
- Sidebar registration in `sidebars.js` (Hub) — auto-generated nav patch
- Release-notes entry in `docs/api-gateway/release-notes.mdx` when warranted — **Hub-only**, OSS PRs never touch release notes
- Screenshot placeholders + per-screenshot checklist items in the PR body when warranted
- Preview as `git diff` in terminal
- Iterative re-prompt loop (engineer types feedback → Claude regenerates)
- Auto-detect engineer's fork; fall back to per-run prompt
- Run target repo's linter (`yarn docs:markdown`, `mkdocs build --strict`) before push
- Duplicate-doc-PR detection
- **Multi-PR features**: accept N impl PRs (all in the same impl repo) and aggregate them into one doc artefact (see §3, §5, §6.1, §6.9)
- Skill packaged as a Claude Code skill in this repo

**Out of scope (v1, listed so the implementer doesn't drift):**
- Actual screenshot capture (no headless browser)
- Multi-PR features that span impl repos (e.g. one PR in `traefik-hub` and another in `traefik` OSS) — must be the same impl repo
- Cross-version sync (back-porting docs to older release branches)
- Deleting docs for removed features
- Non-English locales
- CI-driven auto-filing (skill is engineer-invoked; CI integration is v2)
- Repos other than `traefik/traefik-hub` and `traefik/traefik` (refuse with a clear message)

## 3. Routing (impl repo → doc target)

| Impl repo | Doc target | Mechanism | Release notes? |
|---|---|---|---|
| `traefik/traefik-hub` | `traefik/hub-doc` | New branch in engineer's fork → draft PR cross-repo against `traefik/hub-doc:master` | Yes, when warranted (see §7) — appended to `docs/api-gateway/release-notes.mdx` |
| `traefik/traefik` | same repo, `docs/content/...` | New commit appended to the impl PR branch (no separate PR) | **Never** — OSS doesn't use this release-notes file |
| anything else | — | Refuse with `unsupported impl repo: <owner>/<name>` | — |

Rationale, validated by exploration: `traefik-hub` has no in-repo `docs/`; `traefik` ships docs in-repo at `docs/content/` and recent PRs (e.g. `#13195`) commit code + docs together in a single combined commit. Release notes are a Hub-doc artefact only.

### Multi-PR aggregation

The skill accepts N impl PRs in a single invocation provided **all N belong to the same impl repo**. Use cases: a Hub feature split across `traefik-hub#1234`, `#1235`, `#1240`; or an OSS refactor that landed as a stack.

- **All-Hub multi-PR**: one doc PR in `hub-doc` whose body lists every source PR. The page is generated once from the merged diff + the union of linked issues; if release notes are warranted, one release-notes bullet/subsection references the feature, not each PR.
- **All-OSS multi-PR**: the skill asks which PR is the **primary** (default: the largest by added lines, or the first arg). The doc commit lands on the primary's branch. The other PRs are noted in the doc commit body (`Refs: traefik#5678, traefik#5680`). If the engineer wants separate doc commits per PR, that's manual — the skill won't fan-out.
- **Cross-repo multi-PR** (Hub PR + OSS PR in one invocation): refuse in v1; instruct the engineer to run the skill twice.

## 4. Architecture

Claude Code skill in this repo, with deterministic helper scripts in Python (stdlib only) so each step is testable and the LLM only does judgment-heavy work.

```
ai-ws-hub-doc-pr-generator/
├── SKILL.md                       # entry point: orchestrator checklist (~250 lines)
├── spec.md                        # this file (after we leave plan mode)
├── scripts/
│   ├── fetch_pr.py                # gh → normalized PR/issue/diff bundle (JSON)
│   ├── fetch_grounding.py         # traefik/reference via gh api (INDEX, DOC_INDEX, concepts)
│   ├── classify.py                # heuristics: release-note? screenshot? user-guide vs reference?
│   ├── locate_targets.py          # propose target file path(s) + neighbor pages for style mirror
│   ├── preview.py                 # render git diff + run target-repo linters
│   ├── open_pr.py                 # fork detect → branch → push → draft PR (Hub) or commit (OSS)
│   └── tests/                     # fixture-driven unittest suite
├── templates/
│   ├── hub-page.md.tmpl           # Docusaurus front matter + skeleton
│   ├── oss-page.md.tmpl           # MkDocs front matter + skeleton
│   ├── sidebar-entry.json.tmpl    # snippet to inject into sidebars.js
│   ├── release-note-item.tmpl     # bullet for release-notes.mdx
│   └── pr-body.md.tmpl            # doc-PR body template
└── references/                    # cached notes the skill loads as context
    ├── hub-doc-conventions.md
    ├── oss-doc-conventions.md
    ├── screenshot-heuristics.md
    └── release-note-heuristics.md
```

The LLM (running Claude session) handles: writing prose, choosing between candidate locations, asking the user-guide-vs-reference question, mirroring neighbor tone, and processing edit-loop feedback. Everything else is a Python script with a stable JSON interface.

## 5. Invocation

Three input modes (skill auto-detects which the engineer used), each accepting one **or more** PRs:

| Form | Example | How skill resolves |
|---|---|---|
| PR URL(s) | `/<skill> https://github.com/traefik/traefik-hub/pull/1234 https://github.com/traefik/traefik-hub/pull/1240` | Parse each URL → list of `{owner, repo, pr}` |
| PR number(s) | `/<skill> 1234 1240` | `git remote -v` in cwd → `{owner, repo}`, apply to each arg |
| no-arg auto-detect | `/<skill>` | `gh pr view --json number,headRepository,baseRepository` for current branch (single PR only) |

All inputs normalize to a list of `{impl_repo, pr_number}` pairs. The skill **validates that all entries share the same `impl_repo`**; if not, it exits with a cross-repo refusal (see §3).

Single-PR is the common case and gets the original UX; multi-PR adds: a brief "Aggregating <N> PRs from <repo>:" header before the kind question, and a "primary PR" prompt for the OSS flow (auto-suggests the largest by added lines).

## 6. Pipeline (data flow)

```
INPUT  → fetch_pr → fetch_grounding → classify → ask kind → locate_targets
       → LLM generate → preview (+ lint) → [edit loop] → open_pr (Hub) | commit (OSS)
```

### 6.1 fetch_pr.py
Inputs: `--repo <owner/name> --pr <N>` (one **or more** `--pr` flags for multi-PR aggregation)
Output: `pr-bundle.json` — a list of per-PR entries plus an aggregate view:
```json
{
  "impl_repo": "traefik/traefik-hub",
  "prs": [
    { "number": 1234, "title": "...", "body": "...", "labels": [...], "author": "...",
      "branch": "...", "base": "master", "head": "abc123",
      "isDraft": false, "mergeable": true,
      "diff": "<unified patch, capped at 2000 lines>",
      "diff_truncated": false,
      "files_changed": [{ "path": "...", "status": "added", "additions": 42, "deletions": 3 }],
      "linked_issues": [...], "sub_issues": [...] }
  ],
  "merged": {
    "files_changed": [...],          // union, deduped
    "linked_issues": [...],          // union by issue number
    "sub_issues": [...],
    "primary_pr": 1234,              // for OSS multi-PR: largest by additions (suggestion)
    "title_synthesis": "..."         // LLM-friendly merged title hint
  },
  "existing_doc_pr": { ... }         // duplicate-detection query result (see §10)
}
```
- `linked_issues`: from `closingIssuesReferences` (GraphQL) + regex `(?:Closes|Fixes|Resolves)\s+#\d+` in body
- `sub_issues`: from `gh api repos/{owner}/{repo}/issues/{n}/sub_issues` (one level deep)
- For each issue: `{number, title, body, comments: [...]}` — comments filtered to drop `*[bot]*` authors and empty bodies
- For multi-PR: each PR's diff is fetched independently, capped independently, then `merged.files_changed` is computed by file-path union

Single-PR mode produces `prs: [<one entry>]` and `merged.primary_pr = prs[0].number` — same downstream contract for both modes.

### 6.2 fetch_grounding.py
Inputs: `--touched-files <list>` (from PR diff)
Always uses `gh api`, no local clone required.
- Fetches `repos/traefik/reference/contents/INDEX.md` (cached in `/tmp/ai-ws-grounding-<sha>/`)
- Fetches `repos/traefik/reference/contents/DOC_INDEX.json`
- For each Go file in the diff: scans `INDEX.md` for entries whose `extracted_from` includes that path; pulls those concept markdown files
- Output: `grounding.json` with `{concepts: [{id, kind, source, fields, narrative_doc_path}], llms_txt_url}`
- If no concept matches: `concepts: []` and the skill falls back to neighbor-page-only grounding (never invents concept IDs)

### 6.3 classify.py
Inputs: `pr-bundle.json`, `grounding.json`
Heuristic rules (see §7 and §8) produce:
```json
{
  "feature_type": "feat|fix|chore|refactor|test|docs",
  "needs_release_note": {"verdict": "yes|no|ask", "signals": [...], "section": "What's New|Breaking|GA|null"},
  "needs_screenshots": {"verdict": "yes|no", "signals": [...], "placeholder_paths": [...]},
  "doc_kind_candidates": [
    {"kind": "user-guide", "confidence": 0.7, "rationale": "..."},
    {"kind": "reference",  "confidence": 0.3, "rationale": "..."}
  ]
}
```

### 6.4 Ask the engineer: user-guide or reference?
The skill **always asks**, but presents the AI's top pick with its rationale plus a `[d]ecide for me` escape hatch (matches the user's explicit ask: "First ask the user … if the user does not know, then decide based on the PR content").

### 6.5 locate_targets.py
Inputs: `pr-bundle.json`, `grounding.json`, chosen `doc_kind`
Output: ranked candidate file paths + 3-5 neighbor pages whose tone/structure the LLM should mirror:
```json
{
  "candidates": [
    {"path": "docs/ai-gateway/middlewares/<slug>.md", "confidence": 0.8,
     "neighbors": ["docs/ai-gateway/middlewares/llm-guard.md",
                   "docs/ai-gateway/middlewares/token-rate-limit.md",
                   "docs/ai-gateway/middlewares/content-guard.md"]}
  ],
  "sidebar_insertion_point": {"file": "sidebars.js", "after_id": "ai-gateway/middlewares/content-guard"}
}
```
The skill shows candidates; the engineer confirms one or types a path.

### 6.6 LLM generation
The orchestrator hands the LLM:
- The chosen target path
- Neighbor pages (full content for ~3 of them; outline-only for the rest)
- Relevant grounding concept(s) from `traefik/reference`
- The PR + linked-issue + sub-issue bundle (single or merged)
- The classify output (so it knows whether to emit release-notes / screenshots)
- For Hub-only: the current `docs/api-gateway/release-notes.mdx` head (last ~150 lines) so the LLM knows whether the current month section already exists and what GA bullets are already there

The LLM produces, in one pass:
- The new markdown page (front matter + body) — front matter exactly matches neighbor convention (`title`, `id`, `description`, `tags`, `toc_min_heading_level`, `toc_max_heading_level`)
- A `sidebars.js` patch (a small block to insert with a unified-diff context, not a regex replace)
- A `release-notes.mdx` patch — **Hub-only**, only when `needs_release_note=yes`. Patches `docs/api-gateway/release-notes.mdx` (never `docs/api-management/release-notes.md`, which is a re-import shim). The patch shape depends on classification:
  - **New feature, Early Access**: insert a `#### <Feature Name>` subsection under the **current month**'s `### What's New`, prefixed with a `:::warning Early Access\n...\n:::` admonition, followed by 1-3 paragraphs of description, ending with `For configuration details, see the [<Feature Name>](<relative-link>) documentation.`
  - **New feature, GA**: same shape but **without** the EA admonition
  - **Graduated to GA**: append a bullet to the existing `#### Graduated to GA` list under the current month, in the form `- **<Feature name>** is now generally available. See the [<doc title>](<relative-link>) documentation.`
  - **Breaking change**: add or append to a `#### Breaking Changes` subsection (the file currently doesn't have one — the patch creates it under the current month and flags the engineer to review the section heading choice)
  - **Compatibility-matrix change** (component version bump): update or insert the `#### Compatibility Matrix` table under the current month
  - If the current month section doesn't exist yet, create `## <Month YYYY>` at the top of the post-header area, populated with `### What's New` and the appropriate subsection
  - Links MUST be relative paths from `docs/api-gateway/` (e.g. `../api-management/api.md#anchor`), matching the existing convention in the file
- Screenshot placeholders inline in the page (if `needs_screenshots=yes`) using:
  ```mdx
  <BrowserWindow url='https://hub.traefik.io/...'>
  <!-- TODO(screenshot): <caption>. Save to /static/img/<feature>/<name>.png -->
  </BrowserWindow>
  ```

For multi-PR aggregation, the LLM is told "These N PRs implement one feature; the linked issues are <list>; generate one cohesive doc page that covers the feature, not a per-PR breakdown." The PR body template lists every source PR.

### 6.7 preview.py
- Writes the generated files to a working branch (`docs/<feature-slug>` for Hub; the existing PR branch for OSS — staged but not committed yet)
- Prints `git diff --stat` then `git diff`
- Runs the target repo's linter:
  - Hub: `cd <hub-doc> && yarn docs:markdown && yarn docs:alex` (skip `yarn build` — too slow for a preview loop; gate on push instead)
  - OSS: `cd <traefik> && mkdocs build --strict -d /tmp/.mkdocs-preview`
- If lint fails: surface the errors and force a re-prompt before allowing push

### 6.8 Edit loop
After preview, prompt:
```
[1] looks good — push
[2] re-prompt Claude with notes
[3] save & exit (don't push)
```
On (2): the engineer types feedback ("make the intro shorter", "add a Kubernetes example", "this section duplicates the LLM Guard page — link to it instead"). The orchestrator passes the feedback + the current draft to the LLM, regenerates affected files, re-runs preview. Unlimited iterations.

### 6.9 open_pr.py — push
**Hub flow (single or multi-PR):**
1. Detect engineer's fork: `gh repo list <gh-user> --fork --json name,parent | jq '.[] | select(.parent.nameWithOwner == "traefik/hub-doc")'`
2. If fork exists: `git push <fork-remote> docs/<slug>:docs/<slug>`
3. If no fork: prompt `[f] create fork via 'gh repo fork traefik/hub-doc --remote=false' / [u] push branch to traefik/hub-doc / [a] abort`
4. Open draft PR: `gh pr create --repo traefik/hub-doc --base master --draft --title "docs: <feature title>" --body-file <generated-body>`
5. The PR body (`pr-body.md.tmpl`) includes:
   - `Source:` — one line per impl PR for multi-PR (`Source: traefik/traefik-hub#1234, #1235, #1240`); single line for single-PR
   - Linked issue summary (union for multi-PR)
   - "Generated by ai-ws-hub-doc-pr-generator" marker
   - Checklist of `TODO(screenshot)` items
   - "Reviewers: please verify config fields against `<concept_id>` in traefik/reference"

**OSS flow (single-PR):**
1. Ensure PR branch is checked out (`gh pr checkout <N>` if cwd's HEAD ≠ PR head)
2. Stage the doc files; commit with `docs: <feature title>` (Co-Authored-By: Claude line)
3. Print `git log -1 --stat`; prompt `[y]push to <branch> / [n]o`
4. On y: `git push origin <branch>`; print updated `gh pr view` URL

**OSS flow (multi-PR):**
1. Determine primary PR — `merged.primary_pr` (largest by additions); confirm with engineer via `AskUserQuestion`
2. `gh pr checkout <primary>`
3. Stage doc files; commit with `docs: <feature title>` and body trailer `Refs: traefik#<other-pr-1>, traefik#<other-pr-2>` for each non-primary PR
4. Same y/n push prompt as single-PR
5. After push: print a follow-up note "doc commit landed on traefik#<primary>; the other PRs (<list>) do not get a doc commit. If you want separate doc commits, run the skill again per PR."

## 7. Heuristic: does this PR need a release-notes entry?

**Hub-only.** OSS PRs short-circuit this step entirely — `needs_release_note = no` is forced for any `traefik/traefik` impl repo regardless of signals.

For Hub PRs, the heuristic table:

| Signal | Verdict |
|---|---|
| PR title starts `feat:` and adds a public config/CRD/API field | Yes — propose `#### <Feature Name>` under "What's New" (with EA admonition by default; see below) |
| Label `breaking-change` or "BREAKING CHANGE:" in body | Yes — under "Breaking Changes" (new subsection if absent; flag for engineer review) |
| Label `release-note` / `needs-release-note` | Yes — let engineer choose shape (EA vs GA vs bullet under existing GA list) |
| Body or title mentions "GA", "graduates to GA", "general availability" | Yes — bullet under `#### Graduated to GA` |
| Linked issue labeled `feature` / `enhancement` | Likely yes — confirm with engineer |
| PR title `fix:` and no other signal | No |
| PR title `chore:` / `refactor:` / `test:` / `docs:` / `style:` | No |
| Only internal package changes (no public surface) | No |
| `feat:` but only adds a new optional config field to an existing middleware | Ask — could be note-worthy or not, depending on how the feature is positioned |
| Otherwise | Ask the engineer; show every signal observed |

**EA vs GA defaulting (Hub):** when "yes" is the verdict, the skill defaults to **Early Access** (with the `:::warning Early Access` admonition) unless the PR signals GA explicitly. Engineers can flip to GA in the edit loop.

Output: `{verdict: yes|no|ask, signals: [...], proposed_shape: "ea-subsection"|"ga-subsection"|"ga-bullet"|"breaking-subsection"|"compat-matrix"|null, proposed_section_heading: "<Feature Name>"|null}`. The engineer can override regardless.

For multi-PR aggregation, the heuristic runs on the **merged** signal set (union of labels, concatenated titles, etc.) — one entry covers the whole feature.

## 8. Heuristic: does this doc need screenshots?

The rule of thumb: **look at the target directory's neighbors**. If the neighbors visualise UI, this one probably should too.

| Signal | Verdict |
|---|---|
| ≥50% of neighbor `.md`/`.mdx` files in the target dir contain `<BrowserWindow>` | Yes — insert placeholders |
| ≥50% of neighbor files reference `/img/` images for UI | Yes — insert placeholders |
| Target dir is `reference/`, `middlewares/`, or any pure API/CLI ref, with no neighbor imagery | No |
| Impl PR touches `/hub/dashboard/` or `/hub/portal/` (UI code) | Yes (strong) |
| Impl PR touches only middleware/config Go packages | No (default) |
| Mixed: some neighbors have imagery, some don't | Insert a single `<!-- TODO(screenshot): consider if this section needs a screenshot -->` marker; do not block |

When yes:
- Insert one `<BrowserWindow>` block per UI surface the page describes
- Add a checklist line per placeholder to the PR body: `- [ ] Capture screenshot for /img/<feature>/<name>.png — <caption>`
- Never claim "screenshot captured" — the engineer must replace placeholders

The skill never captures or modifies images.

## 9. Grounding (traefik/reference) — usage

| Use | How |
|---|---|
| Validate config-field tables match the schema | Pull `oss/<area>/<concept>.md` or `hub/<area>/<concept>.md`; compare LLM-generated table to `fields:` list |
| Cross-link the new doc page to the canonical reference | `DOC_INDEX.json` → narrative doc path → relative link |
| Detect duplicate concept coverage | If the modified Go file maps to a concept whose `narrative_doc` is already populated and recent, warn the engineer |
| Mention `llms.txt` in the PR body | Link to the relevant `llms.txt` (e.g. `https://doc.traefik.io/traefik-hub/llms.txt`) so reviewers can drop the new page into an LLM context |

If `traefik/reference` has no matching concept (rare for new features, common for very new code): fall back to neighbor-page-only grounding. **Never invent concept IDs.**

## 10. Duplicate doc-PR detection

Before generating:
- Hub: `gh pr list --repo traefik/hub-doc --state open --search "traefik-hub#<N>" --json number,title,url`; also search for the feature slug
- OSS: `git diff origin/<base>..HEAD -- docs/content/` — any existing doc changes on the branch?

If a candidate exists:
```
A doc artefact for this PR may already exist:
  #<N>  <title>  <url>
What now?
  [u] update the existing PR (check it out and amend)
  [n] open a new one anyway
  [a] abort
```

## 11. Issue + sub-issue traversal

| Source | Method | Depth |
|---|---|---|
| PR's "closes" links | `gh pr view --json closingIssuesReferences` | direct |
| Body regex `(?:Closes|Fixes|Resolves)\s+#\d+` | regex on PR body | direct |
| GitHub native sub-issues | `gh api repos/{owner}/{repo}/issues/{n}/sub_issues` | one level |
| "Related to #X" in body | regex; **body-only**, no comments | direct |
| Issue comments | `gh issue view <n> --json comments` | direct issues only, **drop `[bot]` authors and empty bodies** |

Deeper than one sub-issue level is dropped to keep context lean.

## 12. Top-level kind decision (user-guide vs reference)

Always ask the engineer. Show the AI's pick + reasoning so they can confirm in one keystroke:

```
Top-level placement?
AI suggests: reference (confidence 0.78)
  Why: PR adds a config field to existing middleware /hub/pkg/middleware/tokenratelimit;
       neighbor pages under /docs/ai-gateway/middlewares/ are all reference-shaped
       (config tables, no narrative).
[c] confirm reference
[s] swap to user-guide
[d] you decide (skill picks the higher-confidence option)
[p] type a custom path
```

## 13. Branch naming

- **Hub**: `docs/<feature-slug>` derived from PR title (kebab-case, strip `feat:`/`fix:` prefix, max 40 chars). Collision: append `-<short-sha>` of the impl PR's head.
- **OSS**: no new branch — add commit on top of the existing PR branch.

## 14. Push semantics — confirmation gates

- Never push without an explicit `y` from the engineer
- Never use `--force` or `--force-with-lease`
- Never `git commit --amend` (always a new commit; matches the user's confirmed preference and avoids overwriting coauthors)
- Never push to a protected branch (master/main) — only to feature branches in the engineer's fork or to the impl PR branch
- If `gh auth status` fails → exit with `gh auth login` instructions; do nothing

## 15. Error handling / edge cases

| Situation | Behaviour |
|---|---|
| No `gh` on PATH | Exit with install instructions |
| `gh auth status` not logged in | Exit with `gh auth login` |
| PR has no linked issues | Proceed PR-only; warn the engineer that issue context is missing |
| Diff > 2000 lines | Truncate, warn, offer `--narrow <dir>` flag |
| Engineer's fork is dirty (uncommitted changes) | Refuse to push; instruct engineer to clean |
| Existing branch name collides | Append `-<short-sha>` |
| `traefik/reference` returns no matching concept | Fall back to neighbor-only grounding; warn |
| Linter fails | Show errors; force a re-prompt; block push |
| Impl repo unsupported | Refuse with explicit message; do not guess |
| Engineer aborts at preview | Leave the working branch in place locally for manual inspection; do not delete |
| Generated doc page duplicates an existing page | Warn with paths; ask `[m]erge into existing / [n]ew page / [a]bort` |

## 16. Testing approach

| Layer | What | How |
|---|---|---|
| Unit | Each script's pure logic (classify rules, target ranking, regex extraction) | Python `unittest`, fixtures under `scripts/tests/fixtures/` |
| Contract | `fetch_pr.py` / `fetch_grounding.py` output shape | JSON schema validation against captured `gh` output |
| Integration | End-to-end against a recorded PR (no live gh calls) | Replay-style fixture: PR JSON + diff + sub-issues frozen; run pipeline; diff generated docs against golden files |
| Smoke | Real recent merged PR with `--dry-run` (no push) | Manual; document the recipe in `references/smoke-test.md` |

The skill itself is tested by running it against real recent PRs (see §17 verification) — golden-file tests catch regressions during iteration.

## 17. Verification (end-to-end)

After implementation, the skill is "done" when all of these pass against real recent PRs:

1. **Hub feat PR** (e.g. a recent `feat:` PR adding a new middleware option): skill opens a draft PR in the engineer's `hub-doc` fork against `traefik/hub-doc:master`. Diff includes the page, `sidebars.js` patch, an EA release-notes `#### <Feature Name>` subsection under the current month's `### What's New` in `docs/api-gateway/release-notes.mdx`, and screenshot TODOs if neighbors have imagery. `yarn docs:markdown` + `yarn docs:alex` pass.
2. **Hub fix PR** (a `fix:` PR): no release-notes entry, no screenshots, just the affected page edits. Draft PR opens cleanly.
3. **Hub GA-graduation PR** (body mentions "graduates to GA"): release-notes patch is a bullet appended to the existing `#### Graduated to GA` list under the current month, not a new subsection.
4. **OSS feat PR** (a recent `traefik/traefik` PR touching `pkg/middlewares/`): skill `gh pr checkout`s the branch, adds a `docs: <title>` commit modifying `docs/content/reference/.../<area>.md`. **No release-notes file is touched.** `mkdocs build --strict` passes. Engineer's `git push` updates the existing PR.
5. **Multi-PR Hub aggregation** (e.g. `/<skill> 1234 1235 1240` for three related Hub PRs): one draft PR opens in hub-doc whose body lists all three source PRs; the page covers the unified feature; one release-notes entry references the feature, not each PR.
6. **Multi-PR OSS aggregation**: skill prompts for primary PR (defaulting to the largest by additions), commits docs to that branch, mentions the other PRs in the commit body (`Refs: traefik#5678, ...`).
7. **Cross-repo multi-PR refusal**: passing a Hub PR and an OSS PR in the same invocation exits cleanly with the refusal message from §3.
8. **Re-prompt loop**: engineer issues "make the intro one paragraph"; regeneration changes only the intro section; diff is small and focused.
9. **Duplicate detection**: re-running the skill against the same impl PR finds the previously-opened doc PR and offers update vs. new.
10. **No-fork engineer**: prompt fires, fork-creation path completes via `gh repo fork`.
11. **Grounding correctness**: for a PR touching a Go file with a corresponding `traefik/reference` concept, the generated config table matches the concept's `fields:` list field-for-field (names, types, descriptions trimmed to one line).
12. **Refusal**: skill against an unsupported impl repo exits with an explicit message and does nothing.

## 18. Open items for v2 (explicitly deferred)

- Auto-screenshot capture (headless Chromium driving the Hub dashboard against a local Hub instance)
- Cross-repo multi-PR (one invocation spanning `traefik-hub` + `traefik` impl PRs)
- Cross-version sync (back-port a doc change to older release branches)
- CI auto-filing (run on impl-PR merge via GitHub Action, no human in the loop)
- Non-English locales when hub-doc adds them
- Detect feature-removal PRs and propose doc deletion
- Use `traefik/reference`'s JSON Schemas to programmatically validate generated config tables (not just inspect)
- Multi-PR with per-PR doc commits in OSS (fan-out instead of single primary)

## 19. Implementation hand-off notes (for the agent that will build this)

- The repo is currently empty (`ai-ws-hub-doc-pr-generator/.git` only). Scaffold under §4's layout.
- Python: stdlib only, no `pip install` step at runtime. If you need `requests`-like ergonomics, use `urllib.request` — the helper scripts shell out to `gh` for all GitHub access anyway, so HTTP code is minimal.
- Every helper reads its inputs from CLI flags and emits JSON to stdout; the orchestrator (SKILL.md) pipes them together. This makes each script independently runnable and testable.
- Keep `SKILL.md` under ~250 lines — it's loaded into every session. Long static content (conventions, heuristics catalogs) goes into `references/*.md` and is loaded on demand.
- Use `git -C <path>` everywhere; the skill should never `cd`. The engineer's cwd is potentially the impl repo, not the doc repo — `git -C <hub-doc-path>` is the safe pattern.
- Fork detection note: GitHub user is in `gh api user --jq .login`. Cache for the session.
- The skill is engineer-invoked, so it can be conversational. Use `AskUserQuestion` for the kind / candidate-path / "looks good?" prompts so they render as nice option lists instead of free-form Y/N.
- `SKILL.md` must start with the standard skill frontmatter so Claude Code can auto-discover it. Suggested:
  ```yaml
  ---
  name: hub-doc-pr-generator
  description: Use when an engineer or tech writer wants to open a documentation PR in traefik/hub-doc (or amend a traefik/traefik PR with docs) from an implementation PR. Invoke as `/hub-doc-pr-generator <pr-url|pr-number>` or with no arg when checked out on the impl branch.
  ---
  ```
  Pick the final `name` slug at scaffolding time; the dir name (`ai-ws-hub-doc-pr-generator`) is fine for the repo but a shorter slug like `hub-doc-pr-generator` is friendlier to type as a slash command.
- The skill is auto-discovered when the user installs the repo as a plugin (e.g. `.claude/skills/<name>/SKILL.md` or via `claude-plugins` cache). Document install steps in the repo's `README.md` (out-of-scope for this spec; the implementer should write it).

## 20. Files this spec is anchored to (exploration evidence)

| Claim | Evidence |
|---|---|
| `hub-doc` uses Docusaurus 3, navigation in `sidebars.js` | `/Users/xxsheddy/Developer/traefik-playground/hub-doc/sidebars.js`, `docusaurus.config.js` |
| Front matter fields: `title`, `id`, `description`, `tags`, `toc_min_heading_level`, `toc_max_heading_level` | `hub-doc/docs/api-management/api.md` (and many others) |
| `<BrowserWindow>` screenshot convention | `hub-doc/docs/operations/installation.md` |
| Release-notes single source of truth at `docs/api-gateway/release-notes.mdx`; `api-management/release-notes.md` re-imports it | Both files read directly; the api-management one is `import ReleaseNotes from '../api-gateway/release-notes.mdx'` + `<ReleaseNotes />` |
| Release-notes structure: `## <Month YYYY>` → `### What's New` → `#### Graduated to GA` bullets and/or `#### <Feature Name>` subsections (with `:::warning Early Access` for EA features) | `hub-doc/docs/api-gateway/release-notes.mdx` lines 26-200 (May 2026, April 2026 entries) |
| Images live under `/static/img/` | `hub-doc/static/img/` |
| Linters: markdownlint, alex, remark, vale | `hub-doc/.markdownlint.json`, `.vale.ini`, `package.json` scripts |
| `traefik-hub` has no in-repo `docs/` | `ls /Users/xxsheddy/Developer/traefik-playground/traefik-hub` |
| Recent Hub feature PR pattern (e.g. messagesapi, onDenyResponse) | `traefik-hub` commit log (`a85e7617`, `5fd0af37`) and matching `hub-doc` commits (`f4a7dce`, `f9bec97`) |
| OSS docs in-repo at `docs/content/` (MkDocs) | `/Users/xxsheddy/Developer/traefik-playground/traefik/docs/mkdocs.yml`, `docs/content/getting-started/kubernetes.md`, `docs/content/reference/install-configuration/entrypoints.md` |
| OSS convention: code + docs in single combined commit | `traefik` commit `4d9031bdb` (PR #13195), `ead1c84fae` |
| `traefik/reference` registry shape (concept_id, kind, source, fields, extracted_from) | `gh repo view traefik/reference`; `INDEX.md`, `DOC_INDEX.json`, `oss/http/routers.md` |
| `llms.txt` published at `doc.traefik.io/{,traefik/,traefik-hub/}llms.txt` | `traefik/reference` `docs/llms/` |
| Recent doc PRs land from `sheddy-traefik` fork | hub-doc PR #896 (`sheddy-traefik:feat/offline-self-service`), #800 |
