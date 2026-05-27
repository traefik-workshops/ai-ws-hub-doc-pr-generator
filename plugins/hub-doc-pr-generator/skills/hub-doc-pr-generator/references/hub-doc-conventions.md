# Hub-doc conventions

Cheat-sheet the LLM consults when generating pages for `traefik/hub-doc`.

## Engine

Docusaurus 3.9.x. Navigation in `sidebars.js`. Build with `yarn dev` (local), `yarn build` (prod).

## Front matter (required)

```yaml
---
title: 'Feature Name'
sidebar_label: 'Feature Name'
id: feature-id
description: 'One-sentence description for the page meta description.'
tags:
- Feature Area
- Sub-area
toc_min_heading_level: 2
toc_max_heading_level: 4
---
```

- `title`: page H1. Body **does not** repeat the title as `# H1`.
- `id`: matches the sidebars.js entry (e.g. `ai-gateway/middlewares/token-rate-limit`).
- `description`: under 160 chars; goes into `<meta name="description">`.

## Headings

H2 (`##`) for top-level sections (Overview, Configuration, Examples, Reference).
H3 (`###`) for sub-sections.
Never repeat the page title as an H1 in the body.

## Admonitions

```mdx
:::info ... :::
:::tip ... :::
:::warning ... :::    <!-- also used for ":::warning Early Access" -->
:::note ... :::
```

## Code blocks

````
```yaml showLineNumbers title="YAML"
...
```

```bash
$ kubectl apply -f ...
```
````

## Cross-links

Relative paths from the current file:

```markdown
[Token Rate Limit](../middlewares/token-rate-limit.md "Token Rate Limit")
```

## Screenshots

```mdx
<BrowserWindow url='https://hub.traefik.io/...'>
![Caption](/img/<feature>/<name>.png "Tooltip")
</BrowserWindow>
```

Images live under `/static/img/<feature>/`. Reference them as `/img/<feature>/...` (absolute).

## Linting

- `yarn docs:markdown` (markdownlint, MD013 line length 225)
- `yarn docs:alex` (inclusive language)
- `yarn build` (link integrity, only in CI; too slow for preview)

## Branch and PR

- Branch from `main`
- PR base: `main`
- Open as **draft** so screenshots can be added before review
- PR body must include `Source: traefik/traefik-hub#<N>` line
