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

- `—` (em dash as connector) → comma, period, or split into two sentences
- "It's worth noting that…" / "It's important to note that…" → use `:::note` callout or state directly
- "In order to" → "To"
- "Furthermore" / "Moreover" / "Additionally" → "Also" or restructure
- "In conclusion" / "To summarize" / "To recap" → omit entirely
- "As mentioned above" / "As described earlier" → omit or restructure
- "Could potentially" → "can" or "might"
- Rhetorical questions ("But what if you need X?") → rewrite as a statement
- "Prior to this release" / "From this release" → use the specific version number ("Before v3.20" / "Starting in v3.21") — outside the PR/release-note context, "this" has no referent

**Voice principles:**

1. **Write to one reader.** "You can configure…" not "Users can configure…"
2. **Short sentences.** If a sentence needs a semicolon or em dash, split it into two.
3. **Concrete before abstract.** Lead with what it does, then explain how.
4. **Don't explain what the reader already knows.** Skip definitions of concepts the page's audience uses daily.
5. **Specifics over vague descriptors.** "Supports up to 100 rules" not "supports many rules."
6. **Imperative in steps.** "Set the timeout to…" not "You should set the timeout to…"

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

## Tables

- Use sentence case for row headings.
- Sort alphabetically when a table contains a long parameter list.
- Avoid tables that require horizontal scrolling; break into smaller tables or use lists instead.
- When extending an existing table (adding a row for a new enum value, parameter, format,
  etc.), enumerate every row explicitly. Never abbreviate existing rows with "…" or "etc."
  to save space — that silently drops content a reader depends on. If unsure of another
  row's exact values, look them up in the touched source or `grounding.json` rather than
  guessing or omitting it.
