# Smoke-test recipe

End-to-end check that the skill produces something sensible against a real recent PR.

## Prerequisites

- Local clones at `$HUB_DOC_PATH` (default `~/Developer/traefik-playground/hub-doc`) on a clean `main`.
- `gh` authenticated.

## Steps

1. Pick a recent merged `feat:` PR in `traefik/traefik-hub`: `gh pr list --repo traefik/traefik-hub --state merged --search "feat:" --limit 5`.
2. Run the skill: `/hub-doc-pr-generator https://github.com/traefik/traefik-hub/pull/<N>`.
3. At the kind question, pick the AI suggestion.
4. At the path question, accept the top candidate.
5. Preview prints a diff and lint result; lint should pass.
6. Choose `[3] save and exit (no push)`.
7. Inspect the generated branch in `$HUB_DOC_PATH`: `git -C $HUB_DOC_PATH log -1 --stat docs/<branch>`.
8. Compare against the actual merged doc PR for the same feature (if any).

## Expected results

- Page front matter matches neighbor pages
- `sidebars.js` patch is a small block under the right category
- Release-notes patch is in `docs/api-gateway/release-notes.mdx` only (never the api-management one)
- Lint passes
- For `fix:` or `chore:` PRs: no release-notes patch
