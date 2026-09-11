# Style Guide

Existing documentation may not follow these rules. Do not mirror patterns from neighbor pages that contradict these rules — these rules take precedence.

<!-- TIER 1 — Core (always loaded) -->

## Core rules

### Voice and language
- Use active voice with simple present tense.
- Use imperative voice in procedures and instructions.
- Omit "please" in technical docs.
- Replace "should" with direct declarative sentences.
- Replace "it is recommended" with specific guidance on available options.
- Focus on users and actions, not products: write "You can do X on this page", not "This page allows you to X".
- Write "click this button", not "click on this button".
- Use simple, universally understood words; avoid jargon.
- Do not attribute human characteristics to inanimate objects.
- Never carry over customer names or customer-specific details from the source PR or issue — generalize the use case, or omit it entirely.

### Numbers
- Spell out numbers one through ten; use numerals for 11 and above.
- Always use numerals for parameter example values.

### Titles and headings
- H1 (page title): Title Case, action-based (not feature-name-based).
- H2 and H3: Sentence case, action-based, and descriptive.
- Make each section as self-sufficient as possible.

### Formatting
- UI field names: **bold**.
- Field options and example values: `code case` (backticks).
- Each field must document: description, example values, expected format, and default value.
- Use bullet points for feature descriptions; numbered lists for procedures.
- Limit nested lists to two levels maximum.
- Use clear paragraphs; avoid fragmented sentences on separate lines.
- Progressive disclosure: basic/typical use first, then advanced, caveats, edge cases.
- Verify all reference links are present and working.
- Number code lines in code blocks. Highlight specific code lines to bring attention to the parameter placement and implementation.

### Callouts
- Use callouts sparingly; overuse reduces reader attention.
- `:::note` — additional details (extra options, alternatives) that may be lost within body text.
- `:::warning` — restrictions users must know before or after a step to avoid errors.
- Label callouts as Note, Tip, or Warning based on content.

### Natural writing

**Banned words — never use these:**

- leverage, utilize, harness → use **use**
- streamline → describe what it simplifies
- robust, comprehensive, powerful → describe the specific capability
- seamless, seamlessly → omit; describe the outcome instead
- empower → say what the user can do
- facilitate → help, let, enable
- delve into → explore, look at
- cutting-edge, innovative → omit

**Banned phrases — rewrite or cut:**

- `—` (em dash as connector) → comma, period, or split into two sentences. Don't mechanically swap it for a semicolon or colon either — those are just a disguised em dash. Actually restructure: split into two full sentences, or let it run as one sentence joined by a conjunction ("so", "and", "but").
- "It's worth noting that…" / "It's important to note that…" → use `:::note` callout or state directly
- "In order to" → "To"
- "Furthermore" / "Moreover" / "Additionally" → "Also" or restructure
- "In conclusion" / "To summarize" / "To recap" → omit entirely
- "As mentioned above" / "As described earlier" → omit or restructure
- "Could potentially" → "can" or "might"
- Rhetorical questions ("But what if you need X?") → rewrite as a statement
- Narrative or dramatizing framing ("This record doesn't stand alone: …", "without asking anyone to take your word for it") → state the fact plainly. If the sentence would read fine as a line in a blog post's opening paragraph, it's too rhetorical for a doc; cut the flourish and keep the fact.
- "Prior to this release" / "From this release" → use the specific version number ("Before v3.20" / "Starting in v3.21") — outside the PR/release-note context, "this" has no referent

**Voice principles:**

1. **Write to one reader.** "You can configure…" not "Users can configure…"
2. **Short sentences.** If a sentence needs a semicolon or em dash, split it into two.
3. **Concrete before abstract.** Lead with what it does, then explain how.
4. **Don't explain what the reader already knows.** Skip definitions of concepts the page's audience uses daily.
5. **Specifics over vague descriptors.** "Supports up to 100 rules" not "supports many rules."
6. **Imperative in steps.** "Set the timeout to…" not "You should set the timeout to…"
7. **Don't gesture at a category with one or two examples unless the reader already knows the category.** "Standard MCP methods such as `tools/list` and `tools/call`" doesn't tell a reader unfamiliar with the MCP spec what else counts as "standard" — either name the full set, link to where it's defined, or drop the category label and state the concrete fact directly ("Most MCP methods already have a default mapping built in").
8. **Don't make a sentence depend on a term defined many paragraphs earlier on the same page.** If a word was given a specific meaning much earlier (e.g. "decision" as the PDP's allow/deny answer), a sentence using it again later should either restate the meaning briefly or be phrased so it doesn't need the callback at all. This is the concrete form of "make each section self-sufficient" (Titles and headings, above).
9. **Multi-item exceptions and caveats lead with the action, not the explanation.** When documenting several exceptions to a rule, structure each one as a bolded, imperative lead sentence stating what the reader does, followed by why — not a paragraph of explanation with the action buried at the end. Example:
   - Avoid: "`initialize` has no built-in default, so a route with only the built-in defaults denies it and no client can complete a handshake. Write a policy for it."
   - Prefer: "**Write a policy for `initialize`.** It has no built-in default, so a route with only the built-in defaults denies it and no client can complete a handshake."
10. **`id` vs. `identifier`.** Never write the bare English word "id" or "ID" in prose. When referring to the literal field, use its exact code-formatted name (`` `resource.id` ``). When speaking about the concept in plain English, write "identifier."
11. **Name the concrete noun instead of a vague placeholder.** Don't write "something delegates authority" or "this happens" when a specific, already-established noun is available — use it. This is especially easy to miss right after introducing a diagram or table that already names the thing precisely; the connecting prose should reuse that exact name, not fall back to "something"/"this"/"it."
12. **A worked example is not the feature's scope.** When a procedure page picks one concrete scenario to walk through (a payments API's refund endpoint, an e-commerce order lookup, etc.), say so explicitly — "using X as the example" — rather than writing the intro as though the feature exists only for that scenario ("this guide sets up the middleware so a payments API only allows a refund…"). A reader skimming the intro should immediately see the scenario is illustrative, not the boundary of what the feature does.
13. **Setup specifics belong where the setup happens, not in a concept intro.** A concept or overview page's introduction states what a feature is and why it exists. Field names, exact values, and "where to set this" instructions belong in that page's Prerequisites section or the linked reference/procedure page — even one sentence of configuration detail in an intro paragraph reads as out of place and is a sign it should move.

---

<!-- TIER 2 — Extended sections (loaded on demand) -->

## Procedure pages

Use this structure for how-to guides, tutorials, and use-case pages.

```
# Title (Title Case, action-based)

<introduction>
Brief feature description, what readers find on this page, why this process is done, and when.

## Prerequisites
List of required tools. Use bullet points when order does not matter.

## Step 1: Step title (sentence case)
Numbered list of actions:
1. First action.
2. ...

State the expected outcome at the end of this step.

## Step 2: Step title
1. ...

End the page by stating what was accomplished and the outcome. Do not summarize; close clearly.

## Next steps
Bullet points linking to related content.

## Troubleshooting
Accordions containing possible errors and their solutions.
```

Additional rules:
- Number steps sequentially; each step covers one coherent action or milestone.
- Start each numbered action with an imperative verb.
- Confirm the expected state or result at the end of each major step.
- Do not end with a summary paragraph; close with outcome or next steps.

## Diagrams

Use Mermaid (already enabled via `@docusaurus/theme-mermaid`) for flow/relationship
diagrams, not a static image export — it's diffable in the PR, stays in sync with
edits, and (unlike a raster/vector image) adapts to the site's light/dark theme
automatically, as long as no node gets a hardcoded `classDef fill:#...` color
(that color is literal and won't adapt either).

- **Bridge prose to diagram with one short sentence directly above it, reusing
  the diagram's own labels verbatim.** Don't introduce a diagram cold, and don't
  paraphrase its node names in the connecting sentence — if the diagram says
  "AuthZEN," the sentence above it says "AuthZEN," not "the authorization step."
  This is what lets a reader map the sentence to the picture.
- **Never make a diagram node into a link with Mermaid's `click` directive.**
  It writes a raw URL that this repo's build-time link checker (`check-relative-paths`)
  does not validate, so a stale or mistyped path fails silently instead of failing
  CI. Put every link in ordinary prose/Markdown near the diagram instead, where
  the existing link checker actually covers it.
- **Center a standalone diagram** by wrapping the fenced ` ```mermaid ` block in
  `<div style={{textAlign: 'center'}}>...</div>` (already used for other inline
  styling in this repo, e.g. `<Details style={{ backgroundColor: ... }}>`) — Mermaid's
  own output has no default centering.
- **A cross-reference inside body prose needs the same existence check as a
  structural link.** Before linking to another page from inside a sentence (not
  just a "Next steps" bullet), confirm that page actually exists on the target
  branch — a page still on another open PR's branch, or only merged to `main`
  after this branch forked, will build locally but fail this repo's Docusaurus
  link check in CI. If it doesn't exist yet, use a plain-text mention instead of
  a broken link, and note the missing link as a follow-up once both branches merge.

## Screenshots and media

- Reduce dependency on media. Use text to instruct; media enhances, not replaces.
- Screenshots must enhance text, not replace it. Add a supporting description for every screenshot.
- Minimize total screenshot count.
- Capture screenshots in both light and dark modes.
- Annotate screenshots where they help readers locate a UI element.
- Record videos in dark mode for Traefik-related UI.

Use this MDX template for all screenshots:

```mdx
import useBaseUrl from '@docusaurus/useBaseUrl';
import ThemedImage from '@theme/ThemedImage';
import BrowserWindow from '@site/src/components/BrowserWindow';

<BrowserWindow url="https://hub.traefik.io">
<ThemedImage
  alt="<Enter helpful alt text>"
  sources={{
    light: useBaseUrl('/img/<path-to-image-light>.png'),
    dark: useBaseUrl('/img/<path-to-image-dark>.png'),
  }}
/>
</BrowserWindow>
```

## Early Access features

Load this section when `classify.json`'s `needs_release_note.proposed_shape == "ea-subsection"`.
Every EA feature needs both the `<EarlyAccessBadge />` component and the
`:::warning Early Access` callout together — never just one. Which shape depends on
whether the whole topic is new or an existing page is gaining a new EA section
(`locate.json`'s `target_exists`):

- **Brand-new topic** (`target_exists: false`, e.g. a whole new middleware page):
  badge goes in the **sidebar entry** via `customProps: { "badge": "Early Access" }`
  (see `sidebar-entry.json.tmpl`) — not inline on the page, since the page body never
  repeats the title as an `# H1` to put a badge next to. The callout goes at the
  **beginning of the topic**, right after the imports, before the intro:

  ```mdx
  :::warning Early Access
  This feature is currently in early access. Available starting v3.21.0-ea.1.
  :::
  ```

- **New EA section on an existing page** (`target_exists: true`, e.g. adding a new
  subsection to an already-published page): badge goes **inline, next to the
  heading** for that section; the callout goes **directly under that heading**:

  ```mdx
  ## Generative AI Span Attributes <EarlyAccessBadge />

  :::warning Early Access
  This feature is currently in early access. Available starting v3.21.0-ea.1.
  :::
  ```

Both shapes state the release version inside the callout (unlike the release-notes
entry itself, where the heading already carries the version — see
`release-note-heuristics.md`, restating it there would be redundant). Use the same
`target_version` collected in SKILL.md step 6c. **If it isn't known yet**, use the
same `vNEXT` placeholder convention as the release note ("Available starting
vNEXT.") — `preview.py`'s `check_placeholder_version` already flags any `vNEXT`
left in written files under "Manual checks required," so it can't merge unresolved
without at least one visible flag in the PR body.

## Tables

- Use sentence case for row headings.
- Sort alphabetically when a table contains a long parameter list.
- Avoid tables that require horizontal scrolling; break into smaller tables or use lists instead.
- When extending an existing table (adding a row for a new enum value, parameter, format,
  etc.), enumerate every row explicitly. Never abbreviate existing rows with "…" or "etc."
  to save space — that silently drops content a reader depends on. If unsure of another
  row's exact values, look them up in the touched source or `grounding.json` rather than
  guessing or omitting it.
- Before adding a new row for a value that has siblings already documented (e.g. a new
  auth method alongside existing `apiKey`/`jwt`/`ldap` entries), check how those siblings
  are actually treated in the table first. If they share one umbrella row rather than
  getting individual rows each, mirror that exact treatment — extend the umbrella entry,
  don't add a standalone row duplicating what it already covers. Don't invent a new
  granularity the table doesn't already use elsewhere.
- Never follow a table with a prose list that breaks down the same rows by a different
  grouping (e.g. a table of methods and their behavior, followed by a bulleted list of
  those same methods grouped by category). Fold the extra dimension into the table itself
  as another column instead — one structure, not two competing ones covering the same data.
