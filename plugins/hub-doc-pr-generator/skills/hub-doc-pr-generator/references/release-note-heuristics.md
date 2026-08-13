# Release-note heuristics (Hub-only)

OSS PRs always short-circuit to `needs_release_note=no`.

## Where the entry goes

**Never `docs/api-gateway/release-notes.mdx` directly.** This skill writes a
fragment file instead: `docs/api-gateway/release-notes.d/<pr-number>-<feature-slug>.mdx`
(`create` mode, front matter + the shape body — see `templates/release-note-fragment.mdx.tmpl`).

This exists because per-PR full-file overwrites of `release-notes.mdx` caused real merge
conflicts and silent duplicate subsections: every concurrently-open PR during an EA
window regenerated the *entire* version section from scratch (including every sibling
feature that had already merged), so two PRs branching at different times would mutate
the exact same lines with slightly different snapshots. Verified against the real
`v3.21.0-ea.1` batch (8 PRs, 5+ feature subsections reconstructed independently across
them). A fragment file is unique per PR (the PR-number prefix makes filename collisions
structurally impossible), so two PRs can never touch the same lines, or even the same
file.

The sibling `release-notes-generator` skill's `cut <version> <date>` command is the
**only** thing that ever writes `release-notes.mdx` directly — it assembles all fragments
for a confirmed release into one clean PR, once, centrally (see that skill's SKILL.md).
This skill's job stops at writing one correct fragment.

The `docs/api-management/release-notes.md` file is a re-import shim — never patch it.

## Structure of the target file

This describes the **assembled** `release-notes.mdx` output that `release-notes-generator
cut` produces from fragments — useful context for writing a fragment body correctly, but
this skill never renders this full structure itself anymore (see "Where the entry goes").

Reorganized to per-version (semver) sections in [traefik/hub-doc#953](https://github.com/traefik/hub-doc/pull/953) — no longer month-based. Versions from before that change (November 2025 and earlier) are collapsed into an `## Earlier releases` archive and don't concern this skill; `cut` only ever inserts new sections at the top.

```mdx
## Gateway v<X.Y.Z>

**<YYYY-MM-DD>**

### What's New

#### Graduated to GA

- **Feature A** is now generally available. See [...](...).

#### Feature B

:::warning Early Access
This feature is currently in early access.
:::

Body...

For configuration details, see the [...](...) documentation.

<Collapse title="Compatibility matrix">

| Component | Version |

</Collapse>
```

Early Access versions get an `<EarlyAccessBadge />` right after the version in the
heading: `## Gateway v3.20.0-ea.8 <EarlyAccessBadge />`. Some sections cover more than
one simultaneous patch release, e.g. `## Gateway v3.19.4 & v3.18.8` with a combined date
line (`**2026-04-02 & 2026-04-01**`) and one `**v3.x.x**`-labeled compatibility table per
version inside the same `<Collapse>` — this skill never constructs a combined heading
itself (see "Which version" below); it's a hub-doc-team curation step for when multiple
patch tags land close together.

The `#### Compatibility Matrix` heading from the old format is gone — the table is
wrapped directly in `<Collapse title="Compatibility matrix">`, no heading of its own.

## Shape selection

`classify.py:needs_release_note()` picks a shape from the signals below, checked
**in this order** (first match wins). Hub has no maturity labels (only
`kind/enhancement` etc.), so EA/GA is read from title/body keywords, not labels.

| # | Signal | Shape | Template |
|---|---|---|---|
| 1 | label contains `breaking` **or** body has "breaking change" | `breaking-subsection` (new if absent — flag for engineer review) | `release-note-breaking.mdx.tmpl` |
| 2 | title/body matches a graduation marker (`graduat`, "now generally available", "promote(d) to ga") | `ga-bullet` appended to existing `#### Graduated to GA` | `release-note-ga-bullet.mdx.tmpl` |
| 3 | title/body matches an EA marker ("early access", "experimental", "tech preview", " beta ", " alpha ") | `ea-subsection` with `:::warning Early Access` admonition | `release-note-ea.mdx.tmpl` |
| 4 | `feat:` **and** a new-GA marker ("general availability", "generally available", "stable release", " ga ", "(ga)") without graduation wording | `ga-subsection` (same shape, no admonition) | `release-note-ga-subsection.mdx.tmpl` |
| 5 | `feat:` with no maturity marker | `ea-subsection` (signal `feat-default-ea`) | `release-note-ea.mdx.tmpl` |
| 6 | `fix:`/`chore:`/`refactor:`/etc. | none | — |
| 7 | otherwise | `ask` the engineer | — |

## EA vs GA defaulting

EA is only the fallback (#5) for an unmarked `feat:` — which matches the Hub
convention that new features ship as Early Access and are later listed under
"Graduated to GA". Explicit EA/GA wording (#2–#4) is detected and wins over the
default. Either way the engineer can flip the shape in the edit loop.

New-GA (#4, a feature shipping straight to GA) vs graduation (#2, an existing EA
feature promoted) is a fuzzy call from text alone; when both readings are
plausible the engineer corrects it in the edit loop.

## Which version

Unlike the old month-based layout, the target version can't be derived from the
PR's merge date — it depends on which Hub release the change actually ships in,
which isn't knowable from the PR alone. `classify.py::needs_release_note()` no
longer returns a target field at all; when its `verdict` is `yes`, SKILL.md step
6c asks the engineer/tech writer directly ("Which Hub release is this release
note for? e.g. v3.20.7") and the answer becomes the fragment's `target_version`
front-matter field. Do not guess a version from the date.

**If the engineer/tech writer genuinely doesn't know the version yet** (common —
release cuts often land after the doc PR is drafted), set `target_version:
unassigned` in the fragment's front matter, instead of improvising something
like `vTBD` or leaving it blank. `unassigned` is a fixed, grep-able token so
`release-notes-generator cut` can reliably find every fragment that still needs
a version and prompt for it interactively — see that skill's SKILL.md. (This is
a different placeholder from `vNEXT`, which is still used, unchanged, for this
PR's own page-level Early Access callout — see `style-guide.md`'s "Early Access
features" section; `preview.py`'s `check_placeholder_version` still flags that
one, in the page content, not in fragment front matter.)

## Insertion order — newest on top

**Not this skill's concern anymore.** Each PR's fragment is one small, independently
merged file — there's no shared "top of the file" to insert into per-PR now, so this
section moved to `release-notes-generator`'s `cut` command, which assembles the fragments
for a confirmed release into the right order (`#### Graduated to GA` first, newest feature
subsections next, compatibility-matrix `<Collapse>` last) once, centrally, when it renders
the real `## Gateway v<version>` section. See that skill's SKILL.md and `assemble_section.py`.

## Links

Use relative paths from `docs/api-gateway/` (e.g. `../api-management/api.md#anchor`). Matches the existing file convention even though there's a stale comment at the top saying "ALL LINKS … MUST BE COMPLETE URLS".
