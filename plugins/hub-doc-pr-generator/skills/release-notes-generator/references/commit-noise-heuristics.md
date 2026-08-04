# Commit noise heuristics

What `classify_commits.py` excludes, and why — plus two judgment calls found
by hand while verifying a real v3.19.13/v3.20.8 draft that the script
deliberately does NOT auto-resolve, because they're closer to editorial
policy than mechanical filtering.

## Always excluded (confidence 1.0)

- **Branch merges** — `Merge vX.Y into vX.Z`. Pure branch-management
  artifacts; the commits they bring in are already present individually in
  the compare range, so nothing is lost by dropping the merge commit itself.
- **Internal lint fixes** — `fix lint error`. No product behavior attached.

## Excluded after a file-list check (confidence 0.9)

- A commit whose subject mentions test/e2e wording (`e2e`, `unit test`, "in
  ... tests") gets its touched files checked before being excluded — only
  when *every* touched file matches `_test.go`, `e2e/`, or
  `.github/workflows/` is it dropped. A subject that merely mentions "tests"
  in passing but touches production code is kept, at reduced confidence
  (0.6), for the engineer to double check rather than silently including or
  excluding it.

## Judgment calls this script does NOT make (left for the engineer)

These came up verifying an earlier hand-drafted entry and don't fit a clean
regex — they're a policy question about what belongs in *customer-facing*
release notes, not a noise/signal question:

- **Test-infrastructure fixes that don't cleanly resolve to "test files only"**
  — e.g. `fix: dns issues in e2e tests on linux`. The test-hint regex does
  catch this one (it mentions "e2e"), so it lands in the 0.6-confidence
  bucket rather than being silently included at full confidence — but
  whether a CI-reliability fix like this belongs in *customer-facing*
  release notes at all is still a call for the engineer, not something a
  file-touch check can settle. Treat anything landing in that 0.6 bucket as
  a prompt to ask "does a Hub customer care about this," not just "did this
  touch test files."
- **Internal process documentation** — e.g. `docs: document the release
  process`. Real, but about the *team's* process, not the product. No real
  patch entry in traefik/hub-doc has ever included a bullet like this — worth
  a second look before publishing rather than including by default just
  because a script didn't flag it.

Neither of these is auto-excluded, because a false negative here silently
removes something a future release actually should mention, and it's cheaper
for a human to skip an irrelevant bullet at review time than to notice a
missing one after the fact.
