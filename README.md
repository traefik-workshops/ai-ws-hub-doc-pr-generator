# ai-ws-hub-doc-pr-generator

A Claude Code plugin that drafts documentation PRs from implementation PRs in `traefik/traefik-hub` (→ `traefik/hub-doc`) and `traefik/traefik` (→ in-repo `docs/content/`). It ships a single skill, `hub-doc-pr-generator`.

## Install

This repo is its own Claude Code plugin marketplace (`traefik-workshops`), containing one plugin: `hub-doc-pr-generator`.

In Claude Code, add the marketplace then install the plugin:

```text
/plugin marketplace add traefik-workshops/ai-ws-hub-doc-pr-generator
/plugin install hub-doc-pr-generator
```

(If the plugin name ever collides with another marketplace you have added, disambiguate with `/plugin install hub-doc-pr-generator@traefik-workshops`.)

For local development, point Claude Code at a clone instead:

```bash
git clone https://github.com/traefik-workshops/ai-ws-hub-doc-pr-generator.git
claude --plugin-dir ai-ws-hub-doc-pr-generator/plugins/hub-doc-pr-generator
```

Ensure `gh` is authenticated:

```bash
gh auth status   # or gh auth login
```

The skill auto-discovers your local `hub-doc` clone (env var → persisted config → cwd siblings → common workspace dirs). If it can't find one on first run, you'll be prompted for the path and the answer is remembered. For OSS (`traefik/traefik`) work, the skill uses cwd directly — no setup needed.

## Usage

The skill auto-triggers when you ask Claude to open a documentation PR from an implementation PR. You can also invoke it explicitly, on the impl PR branch:

```
/hub-doc-pr-generator:hub-doc-pr-generator
```

Or with explicit PRs (multi-PR aggregation):

```
/hub-doc-pr-generator:hub-doc-pr-generator https://github.com/traefik/traefik-hub/pull/1234 1235
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
| `.claude-plugin/marketplace.json` | Marketplace manifest (`traefik-workshops`) |
| `plugins/hub-doc-pr-generator/.claude-plugin/plugin.json` | Plugin manifest |
| `plugins/hub-doc-pr-generator/skills/hub-doc-pr-generator/SKILL.md` | Orchestrator the LLM follows |
| `plugins/hub-doc-pr-generator/skills/hub-doc-pr-generator/scripts/` | Deterministic Python helpers (Python stdlib only) |
| `plugins/hub-doc-pr-generator/skills/hub-doc-pr-generator/templates/` | Markdown scaffolds the LLM fills in |
| `plugins/hub-doc-pr-generator/skills/hub-doc-pr-generator/references/` | Convention catalogs loaded on demand |
| `spec.md` | Full design spec |
