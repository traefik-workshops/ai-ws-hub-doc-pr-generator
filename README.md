# ai-ws-hub-doc-pr-generator

A Claude Code skill that drafts documentation PRs from implementation PRs in `traefik/traefik-hub` (→ `traefik/hub-doc`) and `traefik/traefik` (→ in-repo `docs/content/`).

## Install

Clone into the place Claude Code auto-discovers skills:

```bash
mkdir -p ~/.claude/skills
git clone <this-repo-url> ~/.claude/skills/hub-doc-pr-generator
```

Set local-clone paths (the skill reads neighbor pages from disk):

```bash
export HUB_DOC_PATH=~/Developer/traefik-playground/hub-doc
export TRAEFIK_PATH=~/Developer/traefik-playground/traefik
```

Ensure `gh` is authenticated:

```bash
gh auth status   # or gh auth login
```

## Usage

In Claude Code, on the impl PR branch:

```
/hub-doc-pr-generator
```

Or with explicit PRs (multi-PR aggregation):

```
/hub-doc-pr-generator https://github.com/traefik/traefik-hub/pull/1234 1235
```

## Development

```bash
make test    # run unit tests
make lint    # pyflakes
```

See `spec.md` for the design rationale and `docs/superpowers/plans/2026-05-26-hub-doc-pr-generator.md` for the implementation plan.

## Layout

| Path | Purpose |
|---|---|
| `SKILL.md` | Orchestrator the LLM follows |
| `scripts/` | Deterministic Python helpers (Python stdlib only) |
| `templates/` | Markdown scaffolds the LLM fills in |
| `references/` | Convention catalogs loaded on demand |
| `spec.md` | Full design spec |
