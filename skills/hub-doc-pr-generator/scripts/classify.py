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


def feature_type(title: str) -> str:
    m = _PREFIX_RE.match(title.strip().lower())
    return m["type"] if m else "other"


def needs_release_note(pr: dict, *, impl_repo: str) -> dict:
    if impl_repo != "traefik/traefik-hub":
        return {
            "verdict": "no",
            "signals": ["oss-short-circuit"],
            "proposed_shape": None,
            "proposed_section_heading": None,
        }

    title = (pr.get("title") or "").lower()
    body = (pr.get("body") or "").lower()
    labels = {l.lower() for l in pr.get("labels", [])}
    signals: list[str] = []
    shape: str | None = None

    if "breaking-change" in labels or "breaking change:" in body:
        signals.append("breaking-change-signal")
        shape = "breaking-subsection"
    elif any(k in title or k in body for k in ("graduates to ga", "general availability", " ga ", "now generally available")):
        signals.append("ga-graduation-signal")
        shape = "ga-bullet"
    elif feature_type(title) == "feat":
        signals.append("feat-prefix")
        if "feature" in labels or "enhancement" in labels:
            signals.append("feature-label")
        shape = "ea-subsection"
    elif feature_type(title) in {"fix", "chore", "refactor", "test", "docs", "style", "perf", "build", "ci"}:
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


def _title_to_heading(title: str) -> str:
    # Strip "feat: " / "fix: " etc.; Title-Case the remainder.
    stripped = _PREFIX_RE.sub("", title, count=1).lstrip(":").strip()
    return stripped[:1].upper() + stripped[1:] if stripped else ""


_UI_MARKER_RE = re.compile(r"<BrowserWindow\b|!\[[^\]]*\]\(/img/")


def needs_screenshots(*, neighbor_paths: list[str], touched_paths: list[str]) -> dict:
    signals: list[str] = []
    ui_touch = any(
        p.startswith("hub/dashboard/") or p.startswith("hub/portal/")
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


def doc_kind_candidates(
    *, title: str, touched_paths: list[str], neighbor_paths: list[str]
) -> list[dict]:
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

    # Normalise to [0,1]
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
    primary = next(
        (p for p in bundle["prs"] if p["number"] == bundle["merged"]["primary_pr"]),
        bundle["prs"][0],
    )
    touched = [f["path"] for f in bundle["merged"]["files_changed"]]
    return {
        "feature_type": feature_type(primary["title"]),
        "needs_release_note": needs_release_note(primary, impl_repo=bundle["impl_repo"]),
        "needs_screenshots": needs_screenshots(
            neighbor_paths=neighbor_paths, touched_paths=touched
        ),
        "doc_kind_candidates": doc_kind_candidates(
            title=primary["title"], touched_paths=touched, neighbor_paths=neighbor_paths
        ),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, help="path to pr-bundle.json")
    parser.add_argument("--grounding", required=True, help="path to grounding.json")
    parser.add_argument("--neighbor", action="append", default=[],
                        help="path to a neighbor doc file; repeat")
    args = parser.parse_args(argv)
    bundle = json.loads(Path(args.bundle).read_text())
    grounding = json.loads(Path(args.grounding).read_text())
    out = classify(bundle, grounding=grounding, neighbor_paths=args.neighbor)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
