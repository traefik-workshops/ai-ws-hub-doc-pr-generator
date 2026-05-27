# Release-note heuristics (Hub-only)

OSS PRs always short-circuit to `needs_release_note=no`.

## Where the entry goes

Always `docs/api-gateway/release-notes.mdx`. The `docs/api-management/release-notes.md` file is a re-import shim — never patch it.

## Structure of the target file

```mdx
## <Month YYYY>

### What's New

#### Graduated to GA

- **Feature A** is now generally available. See [...](...).

#### Feature B

:::warning Early Access
This feature is currently in early access.
:::

Body...

For configuration details, see the [...](...) documentation.

#### Compatibility Matrix

| Component | Version |
```

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

## Which month

`needs_release_note()` returns `target_month` (e.g. `May 2026`): the PR's **merge
month** (`merged_at`) when known, else the current month for an open/unmerged PR.
Insert the entry under that `## <Month YYYY>` heading, creating it at the top of
the post-header area if it doesn't exist yet. Do **not** simply append to whatever
the newest heading happens to be.

## Insertion order — newest on top

The entry being added is the latest change, so it goes **at the top**, never
appended at the bottom. Concretely:

- **New month section:** create `## <Month YYYY>` at the very top of the
  post-header area, above all existing month sections.
- **New `#### <Feature>` subsection:** insert it as the **first** feature
  subsection within that month's `### What's New` — immediately after
  `#### Graduated to GA` if that block exists, otherwise at the very top of
  `### What's New`. It must sit **above** the existing feature subsections and
  **above** `#### Compatibility Matrix`.
- **New `ga-bullet`:** prepend it to the **top** of the `#### Graduated to GA`
  list, not the end.
- `#### Graduated to GA` always stays first and `#### Compatibility Matrix`
  always stays last within a month — only the relative order of feature
  subsections changes (newest first).

## Links

Use relative paths from `docs/api-gateway/` (e.g. `../api-management/api.md#anchor`). Matches the existing file convention even though there's a stale comment at the top saying "ALL LINKS … MUST BE COMPLETE URLS".
