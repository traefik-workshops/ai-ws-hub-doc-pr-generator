"""write_flags.py — deterministic "Needs verification" PR-body section for
low-confidence doc_kind / target-path picks from classify.py / locate_targets.py.

SKILL.md step 6 now always auto-accepts the top candidate; this script is what
carries the paper trail forward when that pick was a low-confidence guess,
instead of blocking on an AskUserQuestion. Reads the un-slimmed classify.json
(rationale intact) — the --slim copy fed to the LLM generation step has no
rationale to report here.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

KIND_THRESHOLD = 0.85
PATH_THRESHOLD = 0.75


def _runner_up(candidates: list[dict]) -> dict | None:
    return candidates[1] if len(candidates) > 1 else None


def render_needs_verification_section(
    *, classify_result: dict, locate_result: dict,
    kind_threshold: float = KIND_THRESHOLD, path_threshold: float = PATH_THRESHOLD,
) -> str:
    entries: list[str] = []

    kind_candidates = classify_result.get("doc_kind_candidates", [])
    if kind_candidates and kind_candidates[0]["confidence"] < kind_threshold:
        picked = kind_candidates[0]
        line = (f"- **Doc kind**: picked `{picked['kind']}` "
                f"(confidence {picked['confidence']}, {picked['rationale']})")
        runner_up = _runner_up(kind_candidates)
        if runner_up:
            line += (f" — runner-up: `{runner_up['kind']}` "
                      f"(confidence {runner_up['confidence']}, {runner_up['rationale']})")
        entries.append(line)

    path_candidates = locate_result.get("candidates", [])
    if path_candidates and path_candidates[0]["confidence"] < path_threshold:
        picked = path_candidates[0]
        line = (f"- **Target path**: picked `{picked['path']}` "
                f"(confidence {picked['confidence']}, {picked['rationale']})")
        runner_up = _runner_up(path_candidates)
        if runner_up:
            line += (f" — runner-up: `{runner_up['path']}` "
                      f"(confidence {runner_up['confidence']}, {runner_up['rationale']})")
        entries.append(line)

    if not entries:
        return ""

    bullets = "\n".join(entries)
    return (
        "\n## Needs verification\n\n"
        "These picks were auto-selected below the confidence threshold — please confirm:\n\n"
        f"{bullets}\n"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classify", required=True, help="path to classify.json (un-slimmed)")
    parser.add_argument("--locate", required=True, help="path to locate.json")
    args = parser.parse_args(argv)
    classify_result = json.loads(Path(args.classify).read_text())
    locate_result = json.loads(Path(args.locate).read_text())
    md = render_needs_verification_section(classify_result=classify_result, locate_result=locate_result)
    print(json.dumps({"needs_verification_md": md}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
