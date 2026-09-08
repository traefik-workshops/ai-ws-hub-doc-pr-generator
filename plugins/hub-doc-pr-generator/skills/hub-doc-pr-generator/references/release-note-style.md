# Release-note style

Language and tone rules specific to release-notes content — both the
per-PR fragments this skill writes and the patch bullets
`release-notes-generator` writes directly. These sit on top of
`style-guide.md`'s Tier 1 rules (still apply: active voice, banned words,
no em dash as a connector, no semicolons — split into two sentences
instead); this file covers what's specific to the release-notes genre.

Grounded in a "release notes concept" mockup (2026-09) that rewrote a real
past entry against these rules — pull examples from there when in doubt.

## Two genres, two different rules

A release-notes page mixes two kinds of content. Don't apply one style to both.

### 1. Bug-fix and feature-change bullets

Every bullet states the observable consequence, not just the mechanism.
Never stop at restating the commit subject — always close with what a
reader would actually notice changed:

> Fixed a memory usage regression in OpenAPI document loading and
> validation, so gateways parsing large or frequently-updated specs no
> longer see memory grow unbounded.

> Metrics labels are no longer set from user-defined header values,
> preventing unbounded label cardinality from arbitrary headers.

The connector varies (so / making / closing / preventing / cutting) — pick
whichever reads naturally, but the outcome clause itself is not optional.
If you can't state one, that's a signal you don't yet understand what the
change does; go back to the diff/commit before writing the bullet, don't
ship it without one. Plain text throughout — no bold, no code formatting
on the outcome clause. (The examples above are quoted plainly on purpose:
nothing in an actual bullet should be bolded just to highlight the
pattern.)

### 2. Misc bullets (dependency bumps, CVE advisories)

The opposite: no outcome clause, bare fact. The category already carries
the "why" — a reader scanning "Fix Advisory" bullets doesn't need each one
explained.

> Fix Advisory [GHSA-5w68-77r2-r64c](...)
> Update Traefik Proxy to [v3.7.11](...).

Don't pad these with an invented justification just to match rule 1 — that
would be noise, not signal.

### 3. Feature ("What's New") entries

One paragraph, not a bullet dump. The feature name is bold in **two
places**, not one:

1. The heading itself (`#### Feature Name`, an H4 — bold by virtue of
   being a heading).
2. The feature name repeated in explicit `**bold**` as the first word(s)
   of the very next paragraph.

The paragraph itself grounds the feature in a concrete use case in that
same first sentence, then lets technical specifics follow as natural
continuation:

```mdx
#### Bedrock Mantle

**Bedrock Mantle** turns any route into an Anthropic Messages API endpoint
backed by Amazon Bedrock's Anthropic integration. Useful for governing
Claude Code and other coding agents that reach Claude models through
Amazon Bedrock. It builds on the Messages API middleware, reusing the same
model and parameter governance, GenAI metrics, prompt caching, and system
prompt controls, while adding AWS authentication. You can authenticate
with a Bedrock API key (bearer token) or AWS SigV4 request signing, using
static credentials or the default AWS credential chain.

For configuration details and examples, see the [Bedrock Mantle](...) documentation.
```

This is `style-guide.md`'s existing "concrete before abstract" rule,
applied specifically to this genre: use case first, mechanism second, never
the other way around.

## Action-required notices

For a change that's user-impacting but not a schema/API break — something
an existing user must *do*, not just be aware of (a license-token rotation
deadline, a required config migration) — add a `:::warning Action
required` admonition inline, inside the feature's existing body. This is
not a new top-level shape; it's an optional element any shape's body can
carry:

```mdx
:::warning Action required
**Action required for existing online gateways.** Tokens previously lasted
10 years in practice, so renewal was never something you had to think
about. Starting now, all tokens expire after 1 year and must be rotated
before they do.
:::
```

Lead with a bold one-line summary of who's affected and what's required,
then the detail. Don't bury this inside a paragraph where a skimming reader
would miss it — see Reader ID: readers scan for headings and bold terms,
they don't read every line.

## Early Access signal in release notes: badge only, no callout

Inside `release-notes.mdx` (and its fragments) specifically, an EA feature
gets `<EarlyAccessBadge />` next to its heading and nothing else — no
`:::warning Early Access` callout.

```mdx
#### Bedrock Mantle <EarlyAccessBadge />

**Bedrock Mantle** turns any route into...
```

This is a deliberate exception to `style-guide.md`'s general Early Access
rule (badge + callout together, always) — that rule still governs a
feature's own standalone documentation page. It doesn't hold up inside
release notes, where a single EA release routinely bundles 8-10 EA
features into one page: repeating an identical 3-line "This feature is
currently in early access" box that many times is pure noise once the
badge already carries the same signal. One badge per heading is enough
inside this specific document; the callout stays reserved for the page a
reader lands on when they actually go read about the feature.
