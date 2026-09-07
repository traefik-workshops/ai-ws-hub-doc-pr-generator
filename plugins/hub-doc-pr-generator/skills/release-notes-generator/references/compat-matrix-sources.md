# Compatibility-matrix sources

None of these are derivable from a commit changelog — they have to be pulled
from the actual release artifacts. `compat_matrix.py` automates the ones with
a known source; this documents where each row comes from, and flags the one
that isn't automated yet.

| Row | Source | How |
|---|---|---|
| Traefik Hub | the tag itself | no lookup needed |
| Helm Chart | `traefik/traefik-helm-chart`, `traefik/Chart.yaml` | scans recent chart tags for one whose `annotations.traefik.io/hub-min-version` / `hub-max-version` bracket the target Hub tag; reports the chart's own `version:` field. Can legitimately come back empty — the chart repo doesn't tag in lockstep with Hub, and a patch release can ship a day or more before the matching chart bump exists. Don't guess a value when this happens; leave it TBD in the PR and flag it for the hub-doc team / whoever owns the chart release. |
| Traefik Proxy | `traefik/traefik-hub`, `go.mod`'s `github.com/traefik/traefik/v3` pin at the release tag | Not `hub/pkg/version/traefik.version`, even though that file exists specifically to track this (commit `e9bb444`, "fix: align traefik.version with the pinned Traefik version") and looks like the obvious source. Verified live against both v3.19.13 and v3.20.8: the file read one patch *behind* go.mod both times (v3.6.24 vs. go.mod's v3.6.25; v3.7.9 vs. go.mod's v3.7.10). go.mod often pins a pre-release pseudo-version (`vX.Y.Z-0.<timestamp>-<hash>`); confirmed the embedded hash matches the real upstream `traefik/traefik` tag's commit exactly in both cases, so the `vX.Y.Z` prefix is a trustworthy release version, not a guess. `traefik_proxy_version()` reads both sources and returns a `note` when they disagree, rather than silently trusting either — treat that note as a nudge to flag the drift to whoever owns that file, since its whole purpose is to not need this cross-check. |
| Coraza WAF | `traefik/traefik-hub`, `go.mod` at the release tag | regex match on `github.com/corazawaf/coraza/v3` |
| OWASP CRS | `traefik/traefik-hub`, `go.mod` at the release tag | regex match on `github.com/corazawaf/coraza-coreruleset/v4` |
| Kubernetes Gateway API | `traefik/traefik-hub`, `go.mod` at the release tag | regex match on `sigs.k8s.io/gateway-api`. This is the row that was verifiably wrong in a hand-drafted entry — a stale v1.5.1 carried forward when go.mod at the tag actually pinned v1.6.1 — which is the whole reason this script reads go.mod directly instead of trusting the previous entry. |
| Static Analyzer | `traefik/hub-static-analyzer` releases, plus `traefik/traefik-hub`'s tag commit date | not a go.mod dependency — traefik-hub never pins a version for it anywhere (checked go.mod, the Makefile, CI, flake.nix). It ships from its own repo with its own release cadence. Verified live: hub-doc's published v3.20.12 entry (traefik-hub tagged 2026-08-26) lists Static Analyzer v1.9.4, exactly that repo's own latest release as of that date (published 2026-08-19) — so `static_analyzer_version()` looks up the target tag's commit date in `traefik-hub`, then scans `hub-static-analyzer`'s releases for the newest one published at or before it. Can still come back `null` if no release predates the tag among the last `max_releases` checked — don't guess when that happens, same rule as every other row here. |
| MCP specification | **not yet possible to automate — there's no value yet, not just an unlocated pin** | `traefik-hub`'s MCP middleware (`hub/pkg/middleware/mcp/middleware.go`) reads the client's `Mcp-Protocol-Version` header and passes it straight through to telemetry (`telemetry.go`'s `buildSemConvAttributes`) with no comparison, allow-list, or rejection — confirmed live against `main`. `go.mod` pins `github.com/modelcontextprotocol/go-sdk`, but only `e2e/middlewares/mcp_test.go` imports it, not any production package, so it enforces nothing at runtime either. `compat_matrix.py` always reports this as `null`. Unlike Static Analyzer, do **not** carry forward a previous release's value when this comes back unknown — there is no previous real value, since nothing in the codebase has ever declared a supported revision. This is exactly what [hub-issues#3152](https://github.com/traefik/hub-issues/issues/3152) is tracking: engineering has to confirm the supported revision(s) first (its technical proposal 1) before this row can report anything but TBD, ideally via a source constant the same issue suggests wiring up so this becomes as automatable as the go.mod-derived rows above. |

## Why go.mod over the previous release-notes entry

It's tempting to just carry forward whatever the last patch's compatibility
matrix said and only update the rows a changelog commit obviously touched.
That's exactly the failure mode this plugin ran into by hand: the Kubernetes
Gateway API bump above didn't have its own "bump gateway-api" commit — it
rode along inside a generic "update all patch dependencies" commit, so
nothing in the changelog signaled it changed. Reading `go.mod` at the actual
tag is the only way to catch that class of silent bump.
