"""classify_commits.py — filter noise commits (merges, lint-only, test/CI-only)
out of a fetch_release_range.py commit list before it reaches release-note
generation.

Two-pass and confidence-gated, same spirit as classify.py in the sibling
hub-doc-pr-generator skill: cheap regex rules resolve the obvious cases (a
"Merge vX.Y into vX.Z" commit is never a release-note bullet); only genuinely
ambiguous commits — message mentions test/e2e wording without being an
obvious merge/lint commit — pay for a per-commit file-list lookup. Nothing is
silently dropped without a reason attached: a low-confidence exclusion still
carries its verdict and reason in the output, so SKILL.md's generation step
can flag it for engineer review instead of it just vanishing.

This intentionally does NOT decide release-note prose or grouping — the
sibling skill's "Generate" step is explicit that wording is an LLM job, not a
script's; this only decides in/out.

Usage:
  python -m scripts.classify_commits --range /tmp/range.json > /tmp/classified.json
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

from scripts import _gh

# A branch-management artifact, never a user-facing change.
_MERGE_RE = re.compile(r"^Merge v\d", re.IGNORECASE)
# Internal CI hygiene with no product behavior attached.
_LINT_RE = re.compile(r"^fix lint error", re.IGNORECASE)
# Commits whose *subject* reads as test/CI-only — worth a file-list check
# before excluding, since "test" can appear in a subject about a real fix
# (e.g. "fix: no policy matchers breaks mcp spans" mentions nothing test-like,
# but "fix: simplify pointer helpers with new() in responsesapi tests" does).
_TEST_HINT_RE = re.compile(r"\b(e2e|unit test|in .*tests?)\b", re.IGNORECASE)
_TEST_FILE_RE = re.compile(r"_test\.go$|^e2e/|^\.github/workflows/")


def _touches_only_test_files(sha: str) -> bool:
    files = _gh.run_json([
        "api", f"repos/traefik/traefik-hub/commits/{sha}", "--jq", "[.files[].filename]",
    ])
    return bool(files) and all(_TEST_FILE_RE.search(f) for f in files)


def classify_commit(commit: dict) -> dict:
    subject = commit["subject"]

    if _MERGE_RE.match(subject):
        return {**commit, "verdict": "exclude", "confidence": 1.0, "reason": "branch merge commit"}

    if _LINT_RE.match(subject):
        return {**commit, "verdict": "exclude", "confidence": 1.0, "reason": "internal lint fix"}

    if _TEST_HINT_RE.search(subject):
        if _touches_only_test_files(commit["sha"]):
            return {**commit, "verdict": "exclude", "confidence": 0.9,
                    "reason": "mentions test/e2e wording and touches only test/CI files"}
        return {**commit, "verdict": "include", "confidence": 0.6,
                "reason": "mentions test/e2e wording but touches non-test files — verify before excluding"}

    return {**commit, "verdict": "include", "confidence": 1.0, "reason": None}


def flagged_for_review(classified: dict) -> list[dict]:
    """Included commits below full confidence — real, but a judgment call on
    whether they belong in customer-facing release notes (see
    references/commit-noise-heuristics.md). dedup_versions.py's per-tag `only`
    dict keeps just {sha: subject} once commits are split shared-vs-per-tag,
    dropping confidence/reason entirely — so this has to be captured here,
    before that information is gone, not reconstructed later."""
    flagged = []
    for tag_entry in classified["tags"]:
        for c in tag_entry["commits"]:
            if c["verdict"] == "include" and c["confidence"] < 1.0:
                flagged.append({
                    "tag": tag_entry["tag"], "sha": c["sha"],
                    "subject": c["subject"], "confidence": c["confidence"], "reason": c["reason"],
                })
    return flagged


def render_needs_verification_section(classified: dict) -> str:
    """Deterministic PR-body section for flagged_for_review()'s commits — same
    principle as the sibling hub-doc-pr-generator skill's write_flags.py:
    never leave a safety-relevant PR-body section to the generation step
    remembering to write it. pr-body.md.tmpl's reviewer checklist references
    this section by name; this is what actually produces it."""
    flagged = flagged_for_review(classified)
    if not flagged:
        return ""
    bullets = "\n".join(
        f"- [ ] `{f['sha'][:7]}` ({f['tag']}, confidence {f['confidence']}): "
        f"{f['subject']} — {f['reason']}"
        for f in flagged
    )
    return (
        "\n## Needs verification\n\n"
        "These commits were included below full confidence — confirm they belong in "
        "customer-facing release notes:\n\n"
        f"{bullets}\n"
    )


def classify_range(range_data: dict) -> dict:
    out = {"repo": range_data["repo"], "tags": []}
    for tag_entry in range_data["tags"]:
        out["tags"].append({
            "tag": tag_entry["tag"],
            "prev_tag": tag_entry["prev_tag"],
            "date": tag_entry["date"],
            "commits": [classify_commit(c) for c in tag_entry["commits"]],
        })
    out["needs_verification_md"] = render_needs_verification_section(out)
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--range", required=True, help="path to fetch_release_range.py output")
    args = parser.parse_args(argv)
    range_data = json.loads(Path(args.range).read_text(encoding="utf-8"))
    print(json.dumps(classify_range(range_data), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
