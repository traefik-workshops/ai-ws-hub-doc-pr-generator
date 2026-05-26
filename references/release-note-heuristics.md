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

| Verdict | Shape | Template |
|---|---|---|
| EA feat (default for `feat:`) | `#### <Feature Name>` under "What's New" with `:::warning Early Access` admonition | `release-note-ea.mdx.tmpl` |
| GA feat | Same shape, no admonition | `release-note-ga-subsection.mdx.tmpl` |
| GA graduation (title/body says "graduates to GA") | Bullet appended to existing `#### Graduated to GA` | `release-note-ga-bullet.mdx.tmpl` |
| Breaking change | `#### Breaking Changes` subsection (new if absent — flag for engineer review) | `release-note-breaking.mdx.tmpl` |

## EA vs GA defaulting

Default to EA when "yes". Engineers flip to GA in the edit loop.

## Links

Use relative paths from `docs/api-gateway/` (e.g. `../api-management/api.md#anchor`). Matches the existing file convention even though there's a stale comment at the top saying "ALL LINKS … MUST BE COMPLETE URLS".
