# ai-ws-hub-doc-pr-generator

A Claude Code plugin that drafts documentation PRs from implementation PRs in `traefik/traefik-hub` (→ `traefik/hub-doc`) and `traefik/traefik` (→ in-repo `docs/content/`). It ships a single skill, `hub-doc-pr-generator`.

## Install

This repo is a flat Claude Code plugin (`.claude-plugin/plugin.json` at the root, skill under `skills/`).

Clone it and point Claude Code at the directory:

```bash
git clone https://github.com/traefik-workshops/ai-ws-hub-doc-pr-generator.git
claude --plugin-dir ai-ws-hub-doc-pr-generator
```

Once the plugin is published to the TraefikLabs marketplace, install will be a single command:

```text
/plugin install hub-doc-pr-generator@traefiklabs-marketplace
```

Ensure `gh` is authenticated:

```bash
gh auth status   # or gh auth login
```

The skill auto-discovers your local `hub-doc` clone (env var → persisted config → cwd siblings → common workspace dirs). If it can't find one on first run, you'll be prompted for the path and the answer is remembered. For OSS (`traefik/traefik`) work, the skill uses cwd directly — no setup needed.

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
| `.claude-plugin/plugin.json` | Plugin manifest |
| `skills/hub-doc-pr-generator/SKILL.md` | Orchestrator the LLM follows |
| `skills/hub-doc-pr-generator/scripts/` | Deterministic Python helpers (Python stdlib only) |
| `skills/hub-doc-pr-generator/templates/` | Markdown scaffolds the LLM fills in |
| `skills/hub-doc-pr-generator/references/` | Convention catalogs loaded on demand |
| `spec.md` | Full design spec |
