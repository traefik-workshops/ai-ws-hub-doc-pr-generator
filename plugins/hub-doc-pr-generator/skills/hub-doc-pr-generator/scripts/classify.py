"""classify.py — heuristics for: needs_release_note?, needs_screenshots?, doc_kind.

Single entry point is `classify(bundle, grounding, hub_doc_path=None)`; returns a dict
shaped as described in spec.md §6.3.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

_PREFIX_RE = re.compile(r"^(?P<type>feat|fix|chore|refactor|test|docs|style|perf|build|ci)\b")

_NON_NOTE_PREFIXES = {"fix", "chore", "refactor", "test", "docs", "style", "perf", "build", "ci"}

# Hub has no maturity labels (only kind/enhancement etc.), so EA/GA is read from
# title/body keywords. New features ship as Early Access by convention and are
# later listed under "Graduated to GA" — so an unmarked feat: defaults to EA.
_EA_MARKERS = ("early access", "experimental", "tech preview", "preview release", " beta ", " alpha ")
_GA_GRADUATION_MARKERS = ("graduat", "now generally available", "promote to ga", "promoted to ga")
_GA_NEW_MARKERS = ("general availability", "generally available", "stable release", " ga ", "(ga)")


def feature_type(title: str) -> str:
    m = _PREFIX_RE.match(title.strip().lower())
    return m["type"] if m else "other"


def needs_release_note(pr: dict, *, impl_repo: str) -> dict:
    # No target_month/target_version field here: since release-notes.mdx moved to
    # per-version (semver) sections (traefik/hub-doc#953), the target section can
    # no longer be derived from the PR's merge date — it depends on which Hub
    # release the change actually ships in, which isn't knowable from the PR
    # alone. SKILL.md asks the engineer/tech writer for it explicitly instead.
    if impl_repo != "traefik/traefik-hub":
        return {
            "verdict": "no",
            "signals": ["oss-short-circuit"],
            "proposed_shape": None,
            "proposed_section_heading": None,
        }

    title = (pr.get("title") or "").lower()
    body = (pr.get("body") or "").lower()
    hay = f" {title} {body} "
    labels = {l.lower() for l in pr.get("labels", [])}

    def _has_label(token: str) -> bool:
        # Use word-boundary matching: token must appear as a whole segment
        # (at start, after "/", or followed by "-" or end-of-string) so that
        # "kind/not-breaking-change" does NOT match _has_label("breaking").
        pat = re.compile(rf"(?:^|/)(?:{re.escape(token)})(?:-|$)", re.IGNORECASE)
        return any(pat.search(l) for l in labels)

    is_feat = feature_type(title) == "feat"
    signals: list[str] = []
    shape: str | None = None

    if _has_label("breaking") or "breaking change" in body:
        signals.append("breaking-change-signal")
        shape = "breaking-subsection"
    elif any(k in hay for k in _GA_GRADUATION_MARKERS):
        signals.append("ga-graduation-marker")
        shape = "ga-bullet"
    elif any(k in hay for k in _EA_MARKERS):
        signals.append("ea-marker")
        shape = "ea-subsection"
    elif is_feat and any(k in hay for k in _GA_NEW_MARKERS):
        signals.append("ga-new-marker")
        shape = "ga-subsection"
    elif is_feat:
        signals.append("feat-default-ea")
        if _has_label("enhancement") or _has_label("feature"):
            signals.append("enhancement-label")
        shape = "ea-subsection"
    elif feature_type(title) in _NON_NOTE_PREFIXES:
        return {
            "verdict": "no",
            "signals": [f"{feature_type(title)}-prefix"],
            "proposed_shape": None,
            "proposed_section_heading": None,
        }
    else:
        return {
            "verdict": "ask",
            "signals": ["no-conclusive-signal"],
            "proposed_shape": None,
            "proposed_section_heading": None,
        }

    return {
        "verdict": "yes",
        "signals": signals,
        "proposed_shape": shape,
        "proposed_section_heading": _title_to_heading(pr.get("title", "")),
    }


_FULL_PREFIX_RE = re.compile(
    r"^(?:feat|fix|chore|refactor|test|docs|style|perf|build|ci)"
    r"(?:\([^)]*\))?:\s*",
    re.IGNORECASE,
)


def _title_to_heading(title: str) -> str:
    # Strip "feat: " / "feat(scope): " / "fix: " etc.; capitalise the remainder.
    stripped = _FULL_PREFIX_RE.sub("", title).strip()
    return stripped[:1].upper() + stripped[1:] if stripped else ""


_UI_MARKER_RE = re.compile(r"<BrowserWindow\b|!\[[^\]]*\]\(/img/")
_UI_DIR_PREFIXES = ("hub/dashboard/", "hub/portal/")


def _is_pure_type_def(p: str) -> bool:
    """A .d.ts file, or a .ts file sitting directly in a `types/` directory,
    carries no rendered UI on its own — e.g. hub/portal/types/api.d.ts. Rule 1
    is reserved for actual component code; a lone type-def touch shouldn't
    force the same strong 'yes' a real .tsx/.jsx change would."""
    if p.endswith(".d.ts"):
        return True
    return Path(p).parent.name == "types" and p.endswith(".ts")


def needs_screenshots(*, neighbor_paths: list[str], touched_paths: list[str]) -> dict:
    signals: list[str] = []
    ui_touch = any(
        p.startswith(_UI_DIR_PREFIXES) and not _is_pure_type_def(p)
        for p in touched_paths
    )
    if ui_touch:
        signals.append("ui-code-touched")
        return {"verdict": "yes", "signals": signals}

    if not neighbor_paths:
        return {"verdict": "no", "signals": ["no-neighbors"]}

    hits = 0
    for p in neighbor_paths:
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _UI_MARKER_RE.search(text):
            hits += 1

    ratio = hits / len(neighbor_paths)
    signals.append(f"neighbor-ui-ratio={ratio:.2f}")
    if ratio >= 0.5:
        return {"verdict": "yes", "signals": signals}
    return {"verdict": "no", "signals": signals}


def doc_kind_candidates(*, title: str, touched_paths: list[str]) -> list[dict]:
    title_l = title.lower()
    score_ref = 0.0
    score_guide = 0.0
    rationale_ref: list[str] = []
    rationale_guide: list[str] = []

    if any(p.startswith("hub/pkg/middleware/") or "/config.go" in p for p in touched_paths):
        score_ref += 0.6
        rationale_ref.append("touches config/middleware Go package")
    if any(p.startswith("hub/dashboard/") or p.startswith("hub/portal/") for p in touched_paths):
        score_guide += 0.6
        rationale_guide.append("touches UI code")
    if any(w in title_l for w in ("guide", "tutorial", "walkthrough", "setup")):
        score_guide += 0.4
        rationale_guide.append("title hints at guide")
    if "reference" in title_l or "crd" in title_l:
        score_ref += 0.4
        rationale_ref.append("title mentions reference/CRD")

    # When no signals fire at all, return a clear default rather than two 0.0 candidates
    # that leave the LLM with no useful ordering. 0.5 is below the auto-accept gate,
    # so this correctly forces a confirmation prompt either way -- the tie-break only
    # decides which candidate is LISTED first (the LLM's default suggestion in that
    # prompt), not an auto-accepted outcome.
    #
    # Tie-break favors reference, not user-guide: confirmed live (traefik-hub#1435
    # finding #4) that a diff with zero doc-adjacent signal at all -- no markdown, UI,
    # or config-schema files, e.g. pure internal Go like license claims, profile
    # resolution, OTel registration -- is exactly the "nothing to build a guide's
    # narrative around" case, and the real answer there was extending an existing
    # reference table, not writing a new user-guide page. A diff that actually reads
    # as guide-shaped (UI code, a "guide"/"tutorial" title) already scores a positive
    # score_guide signal above and never reaches this branch at all.
    if score_ref == 0.0 and score_guide == 0.0:
        return [
            {"kind": "reference", "confidence": 0.5,
             "rationale": "no doc-adjacent signal — defaulting to reference"},
            {"kind": "user-guide", "confidence": 0.5,
             "rationale": "no signal"},
        ]

    # Confidence is an ABSOLUTE measure of signal strength, not a normalised share.
    # The 1.0 floor on the divisor means a lone weak signal (e.g. a single 0.4 title
    # keyword) stays at 0.4 — below the auto-accept gate, so it asks — while
    # corroborating signals add up toward 1.0 (auto-accept). Conflicting signals
    # (total > 1.0) shrink each side, lowering confidence and forcing a prompt.
    # Do NOT drop the floor: dividing by the raw total inflates a single weak
    # signal to 1.0 and silently skips the confirmation prompt.
    total = max(score_ref + score_guide, 1.0)
    cands = [
        {"kind": "reference", "confidence": round(score_ref / total, 2),
         "rationale": "; ".join(rationale_ref) or "no signal"},
        {"kind": "user-guide", "confidence": round(score_guide / total, 2),
         "rationale": "; ".join(rationale_guide) or "no signal"},
    ]
    cands.sort(key=lambda c: c["confidence"], reverse=True)
    return cands


def classify(bundle: dict, *, grounding: dict, neighbor_paths: list[str]) -> dict:
    # A fetch_issue.py bundle (no implementation PR at all) has an empty
    # `prs` list -- bundle["prs"][0] as the `next()` default would IndexError
    # before even checking for a match. Fall back to the issue itself as the
    # title/body signal, and skip the release-note heuristic outright: with
    # no PR, nothing shipped in a release, so it can never be "yes"/"ask".
    if bundle["prs"]:
        primary = next(
            (p for p in bundle["prs"] if p["number"] == bundle["merged"]["primary_pr"]),
            bundle["prs"][0],
        )
        release_note = needs_release_note(primary, impl_repo=bundle["impl_repo"])
    else:
        primary = bundle.get("issue") or {"title": "", "body": "", "labels": []}
        release_note = {
            "verdict": "no",
            "signals": ["no-pr-no-release-note"],
            "proposed_shape": None,
            "proposed_section_heading": None,
        }
    touched = [f["path"] for f in bundle["merged"]["files_changed"]]
    candidates = doc_kind_candidates(title=primary["title"], touched_paths=touched)
    top_confidence = candidates[0]["confidence"] if candidates else 0.5
    return {
        "confidence": top_confidence,
        "feature_type": feature_type(primary["title"]),
        "needs_release_note": release_note,
        "needs_screenshots": needs_screenshots(
            neighbor_paths=neighbor_paths, touched_paths=touched
        ),
        "doc_kind_candidates": candidates,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, help="path to pr-bundle.json")
    parser.add_argument("--grounding", required=True, help="path to grounding.json")
    parser.add_argument("--neighbor", action="append", default=[],
                        help="path to a neighbor doc file; repeat")
    parser.add_argument("--slim", action="store_true",
                        help="strip signals/rationale arrays for LLM generation input")
    args = parser.parse_args(argv)
    bundle = json.loads(Path(args.bundle).read_text())
    grounding = json.loads(Path(args.grounding).read_text())
    out = classify(bundle, grounding=grounding, neighbor_paths=args.neighbor)
    if args.slim:
        out["needs_release_note"].pop("signals", None)
        out["needs_screenshots"].pop("signals", None)
        for cand in out["doc_kind_candidates"]:
            cand.pop("rationale", None)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
