# OSS-doc conventions

For `traefik/traefik` (the proxy). Docs live in-repo at `docs/content/`.

## Engine

MkDocs (Material theme, `traefik-labs` fork). Build with `mkdocs build --strict`.

## Front matter

```yaml
---
title: "Page Title"
description: "SEO-friendly one-sentence description."
slug: optional-url-slug
---
```

## Headings

H1 (`# Title`) appears in the body. H2 for sections.

## Subtitle marker

```markdown
Listening for Incoming Connections/Requests
{: .subtitle }
```

## Code blocks with tabs

````
```yaml tab="File (YAML)"
...
```

```toml tab="File (TOML)"
...
```

```bash tab="CLI"
--entrypoints.web.address=:80
```
````

## Cross-links

Relative paths. Reference docs link to other reference docs by path:

```markdown
[See HTTP Routers](./reference/routing/http/routers.md)
```

## No release notes in this repo

OSS does not maintain `release-notes.mdx`. The skill must short-circuit release-note logic for `traefik/traefik` impl PRs.

## Branch and commit

- Engineer is already on the impl PR branch when the skill is invoked
- Add a new commit (do not `--amend`) with title `docs: <feature title>` and body trailers as needed
- Push to the existing PR branch (`git push origin <branch>`)
