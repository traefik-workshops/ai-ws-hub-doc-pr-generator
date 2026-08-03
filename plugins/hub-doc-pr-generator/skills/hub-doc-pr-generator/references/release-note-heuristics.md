# Release-note heuristics (Hub-only)

OSS PRs always short-circuit to `needs_release_note=no`.

## Where the entry goes

Always `docs/api-gateway/release-notes.mdx`. The `docs/api-management/release-notes.md` file is a re-import shim — never patch it.

## Structure of the target file

Reorganized to per-version (semver) sections in [traefik/hub-doc#953](https://github.com/traefik/hub-doc/pull/953) — no longer month-based. Versions from before that change (November 2025 and earlier) are collapsed into an `## Earlier releases` archive and don't concern this skill; it only ever inserts new sections at the top.

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

Unlike the old month-based layout, the target section can't be derived from the
PR's merge date — it depends on which Hub release the change actually ships in,
which isn't knowable from the PR alone. `classify.py::needs_release_note()` no
longer returns a target field at all; when its `verdict` is `yes`, SKILL.md step
6c asks the engineer/tech writer directly ("Which Hub release is this release
note for? e.g. v3.20.7") and the answer becomes `target_version`. Insert the
entry under `## Gateway v<target_version>` (plus `<EarlyAccessBadge />` if it's
an EA version), creating that heading at the top of the post-header area if it
doesn't exist yet. Do **not** simply append to whatever the newest heading
happens to be, and do not guess a version from the date.

**If the engineer/tech writer genuinely doesn't know the version yet** (common —
release cuts often land after the doc PR is drafted), use the literal placeholder
`## Gateway vNEXT` with a `**(version TBD)**` date line, instead of improvising
something like `vTBD` or leaving the version blank. `vNEXT` is a fixed, grep-able
token specifically so it's consistent across runs and can't be mistaken for a real
version number if it ever slipped into `main` unreplaced — `preview.py`
mechanically flags any `vNEXT` occurrence in written files under "Manual checks
required" for exactly this reason (see `preview.py`'s `check_placeholder_version`).

## Insertion order — newest on top

The entry being added is the latest change, so it goes **at the top**, never
appended at the bottom. Concretely:

- **New version section:** create `## Gateway v<target_version>` (with the
  `**<YYYY-MM-DD>**` date line right below it) at the very top of the
  post-header area, above all existing version sections — never inside
  `## Earlier releases`.
- **New `#### <Feature>` subsection:** insert it as the **first** feature
  subsection within that version's `### What's New` — immediately after
  `#### Graduated to GA` if that block exists, otherwise at the very top of
  `### What's New`. It must sit **above** the existing feature subsections and
  **above** the `<Collapse title="Compatibility matrix">` block.
- **New `ga-bullet`:** prepend it to the **top** of the `#### Graduated to GA`
  list, not the end.
- `#### Graduated to GA` always stays first and the compatibility-matrix
  `<Collapse>` always stays last within a version — only the relative order of
  feature subsections changes (newest first).

## Links

Use relative paths from `docs/api-gateway/` (e.g. `../api-management/api.md#anchor`). Matches the existing file convention even though there's a stale comment at the top saying "ALL LINKS … MUST BE COMPLETE URLS".
