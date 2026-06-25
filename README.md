# ai-ws-hub-doc-pr-generator

A Claude Code plugin that drafts documentation PRs from implementation PRs in `traefik/traefik-hub` (→ `traefik/hub-doc`) and `traefik/traefik` (→ in-repo `docs/content/`). It ships a single skill, `hub-doc-pr-generator`.

## Quick start

New to the plugin? Three steps:

1. **Install** (once):
   ```text
   /plugin marketplace add traefik-workshops/ai-ws-hub-doc-pr-generator
   /plugin install hub-doc-pr-generator
   ```

2. **Run it** from your impl PR branch:
   ```
   /hub-doc-pr-generator:hub-doc-pr-generator
   ```
   On first run, the plugin checks your environment and walks you through any missing setup (gh auth, hub-doc clone location). It remembers the answers — you won't be asked again.

3. **What to expect**: The plugin reads your PR, classifies the doc type, and generates a draft page. If it's confident about the doc kind and file location, it proceeds automatically. Otherwise it asks one combined question. You'll see a `git diff` preview before anything is pushed.

---

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

### Optional: prettier preview

The preview step works out of the box with plain output. If you want a richer preview — syntax-highlighted diffs and rendered Markdown pages — install any of these CLI tools and the skill will use them automatically (it falls back to plain text when they're absent, so none are required):

| Tool | Used for | Install |
|------|----------|---------|
| [`delta`](https://github.com/dandavison/delta#installation) | syntax-highlighted diff | `brew install git-delta` (see link for other platforms) |
| [`glow`](https://github.com/charmbracelet/glow#installation) | rendered Markdown page preview | `brew install glow` |
| [`bat`](https://github.com/sharkdp/bat#installation) | Markdown preview (fallback if `glow` is absent) | `brew install bat` |

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
