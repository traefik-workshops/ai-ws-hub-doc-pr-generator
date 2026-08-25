"""_discover.py — locate the local hub-doc clone.

Same discovery contract and the *same persisted config file* as the sibling
hub-doc-pr-generator skill (`~/.config/hub-doc-pr-generator/config.json`,
`hub_doc_path` key) — an engineer who already set this up for that skill isn't
asked again here. Trimmed to the hub-doc lookup only: this skill never touches
the OSS traefik/traefik flow, so discover_oss() doesn't exist in this copy.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from scripts import _git

HUB_DOC_URL_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/hub-doc(?:\.git)?/?$")

CONFIG_PATH = Path.home() / ".config" / "hub-doc-pr-generator" / "config.json"

COMMON_PARENTS = [
    Path.home() / "code",
    Path.home() / "dev",
    Path.home() / "src",
    Path.home() / "Developer",
    Path.home() / "workspace",
    Path.home() / "projects",
    Path.home() / "git",
]


def _is_hub_doc_clone(path: Path) -> bool:
    if not (path / ".git").exists():
        return False
    try:
        url = _git.run(str(path), ["config", "--get", "remote.origin.url"]).strip()
    except _git.GitError:
        return False
    return bool(HUB_DOC_URL_RE.search(url))


def _load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _siblings_of(cwd: Path, depth: int = 5) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    p = cwd.resolve()
    for _ in range(depth):
        for candidate in (p / "hub-doc", p.parent / "hub-doc"):
            if candidate.is_dir() and candidate not in seen:
                seen.add(candidate)
                found.append(candidate)
        if p.parent == p:
            break
        p = p.parent
    return found


def _scan_common_parents() -> list[Path]:
    found: list[Path] = []
    for parent in COMMON_PARENTS:
        if not parent.is_dir():
            continue
        try:
            for child in parent.iterdir():
                if not child.is_dir():
                    continue
                if child.name == "hub-doc":
                    found.append(child)
                else:
                    nested = child / "hub-doc"
                    if nested.is_dir():
                        found.append(nested)
        except OSError:
            continue
    return found


def discover_hub_doc(*, cwd: Optional[str] = None, env: Optional[dict] = None) -> Optional[str]:
    """Search order: $HUB_DOC_PATH env var, persisted config, cwd siblings, common workspace dirs."""
    env_map = env if env is not None else os.environ
    cwd_p = Path(cwd) if cwd else Path.cwd()

    explicit = env_map.get("HUB_DOC_PATH")
    if explicit and _is_hub_doc_clone(Path(explicit)):
        return str(Path(explicit).resolve())

    saved = _load_config().get("hub_doc_path")
    if saved and _is_hub_doc_clone(Path(saved)):
        return str(Path(saved).resolve())

    for cand in _siblings_of(cwd_p):
        if _is_hub_doc_clone(cand):
            return str(cand.resolve())

    for cand in _scan_common_parents():
        if _is_hub_doc_clone(cand):
            return str(cand.resolve())

    return None


def persist_hub_doc(path: str) -> None:
    cfg = _load_config()
    cfg["hub_doc_path"] = str(Path(path).resolve())
    _save_config(cfg)


def discover_python_path() -> Optional[str]:
    """A previously-resolved Python 3.11+ interpreter path, if one was saved
    (by the sibling hub-doc-pr-generator skill's setup.py, or this skill's
    own equivalent check) after the default `python3` on PATH turned out to
    be too old -- same persisted config file/key as that sibling skill, see
    this module's docstring."""
    return _load_config().get("python_path")


def persist_python_path(path: str) -> None:
    cfg = _load_config()
    cfg["python_path"] = path
    _save_config(cfg)


# Kept in sync with setup.py's check_python_version() gate.
MIN_PYTHON = (3, 11)


def reexec_target(*, current_version: tuple[int, int],
                   persisted_path: Optional[str],
                   current_executable: Optional[str] = None) -> Optional[str]:
    """Pure decision function: which interpreter path (if any) a script
    running under `current_version` should re-exec itself under. See the
    identical function in the sibling hub-doc-pr-generator skill's
    _discover.py for the full rationale (traefik-hub#1435 finding #6) --
    duplicated here rather than imported since this module is a deliberately
    independent, trimmed copy (see module docstring), not a symlink."""
    if current_version >= MIN_PYTHON:
        return None
    if not persisted_path:
        return None
    if current_executable and persisted_path == current_executable:
        return None
    return persisted_path


def maybe_reexec() -> None:
    """Startup guard a script can call before doing any real work: if running
    under a Python older than MIN_PYTHON and a persisted `python_path` exists,
    transparently re-exec the exact same invocation under that interpreter via
    os.execv, so a stray `python3 -m scripts.foo` self-corrects instead of
    failing outright or requiring the operator to retype the full interpreter
    path every session."""
    target = reexec_target(
        current_version=sys.version_info[:2],
        persisted_path=discover_python_path(),
        current_executable=sys.executable,
    )
    if target is None:
        return
    os.execv(target, [target, *sys.argv])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Locate the local hub-doc clone.")
    sub = parser.add_subparsers(dest="target", required=True)
    sub.add_parser("hub-doc", help="Print path to local hub-doc clone, or exit 2 if not found.")
    save = sub.add_parser("save-hub-doc", help="Persist a hub-doc path for future runs.")
    save.add_argument("path")
    args = parser.parse_args(argv)

    if args.target == "hub-doc":
        path = discover_hub_doc()
        if path is None:
            print("hub-doc clone not found", file=sys.stderr)
            return 2
        print(path)
        return 0
    if args.target == "save-hub-doc":
        persist_hub_doc(args.path)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
