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
| Static Analyzer | **not yet automated** | the Makefile invokes `hub-static-analyzer` but no version pin for it has been located yet (not in go.mod, not an obvious flake.nix input at a quick look). `compat_matrix.py` always reports this as `null` with a note to carry forward the previous release's value and verify by hand. Whoever wires this up next: find where this tool's version is actually pinned (a separate internal repo? a container image tag? flake.nix more carefully?) and add a lookup function alongside `go_mod_deps`/`traefik_proxy_version` above. |

## Why go.mod over the previous release-notes entry

It's tempting to just carry forward whatever the last patch's compatibility
matrix said and only update the rows a changelog commit obviously touched.
That's exactly the failure mode this plugin ran into by hand: the Kubernetes
Gateway API bump above didn't have its own "bump gateway-api" commit — it
rode along inside a generic "update all patch dependencies" commit, so
nothing in the changelog signaled it changed. Reading `go.mod` at the actual
tag is the only way to catch that class of silent bump.
