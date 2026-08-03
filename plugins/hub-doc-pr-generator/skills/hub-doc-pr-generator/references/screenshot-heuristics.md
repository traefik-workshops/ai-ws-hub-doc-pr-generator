# Screenshot heuristics

The skill should insert screenshot placeholders when neighbor pages visualise UI.

## Inputs

- `neighbor_paths`: 3-5 files in the same target directory
- `touched_paths`: files changed in the impl PR

## Rules (first match wins)

1. Any `touched_paths` starts with `hub/dashboard/` or `hub/portal/` **and is not a pure
   type-definition file** (`*.d.ts`, or a `.ts` file sitting directly in a `types/`
   directory) → **yes** (strong). A lone `hub/portal/types/api.d.ts` touch carries no
   rendered UI on its own and falls through to rule 2/3 instead — only actual component
   code (`.tsx`/`.jsx`/`.vue`, or any other file in the UI dirs) triggers this rule.
2. ≥50% of neighbor files contain `<BrowserWindow>` or `![...]( /img/ ...)` → **yes**
3. Target dir is `reference/`, `middlewares/`, or any pure API/CLI ref with no neighbor imagery → **no**
4. Mixed → **no** but insert a single `<!-- TODO(screenshot): consider this section -->` marker

## Placeholder shape

```mdx
<BrowserWindow url='https://hub.traefik.io/<surface>'>
<!-- TODO(screenshot): <caption>. Save to /static/img/<feature>/<name>.png -->
</BrowserWindow>
```

Add a matching PR-body checklist item: `- [ ] Capture screenshot for /img/<feature>/<name>.png — <caption>`.

The skill **never captures or modifies images**. Engineers replace placeholders before merging.
