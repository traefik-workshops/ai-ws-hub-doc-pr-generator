"""_discover.py — locate local hub-doc clone and the OSS impl repo from cwd.

Discovery is best-effort. If hub-doc can't be auto-found, the orchestrator
prompts the engineer via AskUserQuestion and calls persist_hub_doc() with the
answer so future runs skip discovery.
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

HUB_DOC_URL_RE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/hub-doc(?:\.git)?/?$"
)

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
    """True iff path is a git repo whose origin matches traefik/hub-doc or a fork of it."""
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
    """Walk up cwd looking for a sibling 'hub-doc' directory at each level."""
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
    """Look for a 'hub-doc' directory under common workspace dirs (one level deep + one nested)."""
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
    """Return an absolute path to a local hub-doc clone, or None if not found.

    Search order:
      1. $HUB_DOC_PATH env var (escape hatch)
      2. Persisted config at ~/.config/hub-doc-pr-generator/config.json
      3. Sibling dirs of cwd (walks up to depth 5)
      4. Common workspace parents (~/code, ~/dev, ~/src, ~/Developer, etc.)
    """
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
    """Save a confirmed hub-doc path so future runs skip discovery."""
    cfg = _load_config()
    cfg["hub_doc_path"] = str(Path(path).resolve())
    _save_config(cfg)


def discover_python_path() -> Optional[str]:
    """A previously-resolved Python 3.11+ interpreter path, if one was saved
    after the default `python3` on PATH turned out to be too old."""
    return _load_config().get("python_path")


def persist_python_path(path: str) -> None:
    """Save a confirmed Python 3.11+ interpreter path so future runs (and the
    rest of this run's script invocations) don't have to rediscover it."""
    cfg = _load_config()
    cfg["python_path"] = path
    _save_config(cfg)


# Kept in sync with setup.py's check_python_version()/find_compatible_python()
# gate -- this is the same minimum, just consulted by the re-exec guard below
# instead of by the interactive preflight check.
MIN_PYTHON = (3, 11)

# Set in os.environ (inherited automatically by os.execv's child process
# image, since it replaces the process but not its environment) the first
# time maybe_reexec() actually re-execs. A hard, structural one-shot guard
# against an infinite re-exec loop -- independent of reexec_target()'s own
# path-equality check below, which can be defeated by a symlink/PATH
# mismatch that points at the same physical binary under two different
# strings. See maybe_reexec()'s docstring.
_REEXEC_ENV_SENTINEL = "_HUB_DOC_PR_GEN_REEXECED"


def _default_probe_version(path: str) -> Optional[tuple[int, int]]:
    """Real-world probe used by reexec_target() in production: shells out to
    `path -c ...`, the same technique setup.py's own preflight uses to
    discover a candidate in the first place. Kept as an injectable default
    (not hardcoded into reexec_target()) so tests can substitute a fake and
    keep exercising the decision logic without actually spawning a process."""
    from scripts.setup import python_version_at
    return python_version_at(path)


def reexec_target(*, current_version: tuple[int, int],
                   persisted_path: Optional[str],
                   current_executable: Optional[str] = None,
                   probe_version=_default_probe_version) -> Optional[str]:
    """Pure(ish) decision function: which interpreter path (if any) a script
    running under `current_version` should re-exec itself under.

    Extracted from the actual re-exec side effect (os.execv, in
    maybe_reexec() below) so the decision itself -- "should I re-exec, and to
    what path" -- is unit-testable without actually replacing the process.
    `probe_version` is the one real-world side effect left in this function
    (it shells out to the candidate interpreter) -- it's injectable for the
    same reason, so tests can fake "the persisted path reports version X"
    without a real interpreter at that path.

    Returns None (no re-exec) when:
    - `current_version` already meets MIN_PYTHON (nothing to fix), or
    - no `persisted_path` is on file (setup.py's preflight hasn't discovered
      and saved one yet -- nothing to re-exec to), or
    - `persisted_path` is the same interpreter already running (would
      re-exec into an identical, still-too-old process forever). Compared via
      realpath, not raw string equality, so a symlink or PATH-resolved alias
      pointing at the same physical binary is still recognized as "same
      interpreter" -- plain string comparison could miss that and loop.
    - `persisted_path` no longer actually reports a MIN_PYTHON-or-newer
      version when probed right now. A persisted path records where a
      compatible interpreter WAS found, not a standing guarantee it still is
      one -- it can go stale (moved, removed, downgraded, or the discovery
      that saved it was itself wrong) between when setup.py saved it and this
      run. Re-exec'ing into it anyway would still fire the one-shot
      _REEXEC_ENV_SENTINEL guard below and burn a wasted process replacement
      before the same too-old-Python problem surfaces again -- checking here
      catches it up front instead."""
    if current_version >= MIN_PYTHON:
        return None
    if not persisted_path:
        return None
    if current_executable and os.path.realpath(persisted_path) == os.path.realpath(current_executable):
        return None
    persisted_version = probe_version(persisted_path)
    if persisted_version is None or persisted_version < MIN_PYTHON:
        return None
    return persisted_path


def _reexec_argv(target: str, *, orig_argv: list[str],
                  main_module_name: Optional[str]) -> list[str]:
    """Build the argv for os.execv(target, ...) that preserves the ORIGINAL
    invocation's -m semantics, rather than replaying sys.argv verbatim.

    Under `python -m scripts.foo ...`, sys.argv[0] is the resolved absolute
    path to scripts/foo.py -- there is no "-m" in argv to reuse. Naively
    building [target, *sys.argv] therefore re-execs as a BARE script
    (`target /abs/path/scripts/foo.py ...`), not the original `-m
    scripts.foo` invocation. That changes what Python puts at sys.path[0]:
    -m sets it to the current working directory, so `from scripts import
    ...` resolves relative to cwd (plus PYTHONPATH); a bare script path sets
    it to the script's OWN containing directory instead, which does not
    contain the `scripts` package. The only reason a bare re-exec works
    today is that SKILL.md always sets PYTHONPATH="${CLAUDE_SKILL_DIR}"
    before invoking these scripts, so `scripts` stays importable via
    PYTHONPATH regardless of sys.path[0] -- any invocation that reaches
    maybe_reexec() without that prefix set breaks with ModuleNotFoundError
    immediately after re-exec fires (traefik/hub-doc PR #988 round-3 finding
    #3). `main_module_name` -- from sys.modules["__main__"].__spec__.name,
    which is only populated when the process was actually started via -m --
    lets the re-exec faithfully reproduce -m semantics instead of assuming
    PYTHONPATH will paper over the difference."""
    if main_module_name:
        return [target, "-m", main_module_name, *orig_argv[1:]]
    return [target, *orig_argv]


def _current_main_module_name() -> Optional[str]:
    """The dotted module name this process was started as via `-m`, e.g.
    "scripts.locate_targets" -- read from sys.modules["__main__"].__spec__,
    which runpy populates only for a `-m` invocation. None for a bare
    `python scripts/foo.py` run, a REPL, or anything else that leaves
    __main__ without a __spec__. Split out from maybe_reexec() as its own
    seam so tests can fake "this was/wasn't a -m invocation" directly,
    without having to fight a wholesale `sys` mock's auto-generated
    attributes on sys.modules."""
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    return getattr(spec, "name", None) if spec is not None else None


def maybe_reexec() -> None:
    """Startup guard a script can call before doing any real work: if running
    under a Python older than MIN_PYTHON and a persisted `python_path` exists
    (saved by setup.py's check_python_version() after a previous run
    discovered it), transparently re-exec the exact same invocation under
    that interpreter via os.execv, so a stray `python3 -m scripts.foo`
    self-corrects instead of failing outright or requiring the operator to
    remember and retype the full interpreter path every session (see
    traefik-hub#1435 finding #6).

    Deliberately narrow: this does not restructure the CLI surface, and does
    nothing at all when there's no persisted path to fall back to -- the
    existing "Python 3.11+ required" error from setup.py's own preflight
    still fires normally in that case. It DOES rebuild argv (see
    _reexec_argv()) to preserve the original `-m scripts.foo` invocation
    style rather than replaying sys.argv byte-for-byte, so the re-exec'd
    process resolves imports the same way the original invocation did
    instead of quietly depending on PYTHONPATH to paper over the difference.

    Version check runs first and returns immediately when already
    compatible, before discover_python_path() (a file read + JSON parse) is
    even called -- that I/O is wasted work on every invocation of every
    wired-in script when the interpreter is already fine, which is the
    common case.

    Two independent guards against ever looping forever:
    - reexec_target()'s own realpath-based "already this interpreter" check, and
    - the _REEXEC_ENV_SENTINEL env var below: set right before the one
      os.execv attempt this process will ever make, and inherited by the
      child process image os.execv replaces this one with. If it's already
      set, this process IS the result of a prior re-exec earlier in this same
      invocation chain -- re-exec'ing again, no matter what reexec_target()
      says, would risk looping. This is the load-bearing guard: it holds even
      if something outside reexec_target()'s own comparison caused it to keep
      returning a target.

    If the persisted interpreter path turns out to be stale (e.g. moved or
    removed since it was discovered), os.execv raises OSError; that's caught
    so a confusing raw traceback doesn't replace the clear diagnostic below,
    and this process simply continues running under the current (too-old)
    interpreter -- the same fallback behavior that existed before
    maybe_reexec() did, when a script just ran under whatever interpreter
    invoked it."""
    current_version = sys.version_info[:2]
    if current_version >= MIN_PYTHON:
        return

    if os.environ.get(_REEXEC_ENV_SENTINEL):
        print(
            "[hub-doc-pr-generator] Already re-exec'd once this invocation chain "
            f"and still running under Python {current_version[0]}.{current_version[1]} "
            f"(need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+) -- the persisted interpreter "
            "path still isn't new enough, or re-exec didn't fix the version. "
            "Re-run setup.py to rediscover a valid Python 3.11+ interpreter. "
            "Continuing under the current interpreter, which may not work correctly.",
            file=sys.stderr,
        )
        return

    target = reexec_target(
        current_version=current_version,
        persisted_path=discover_python_path(),
        current_executable=sys.executable,
    )
    if target is None:
        return

    os.environ[_REEXEC_ENV_SENTINEL] = "1"
    try:
        os.execv(target, _reexec_argv(
            target, orig_argv=sys.argv, main_module_name=_current_main_module_name(),
        ))
    except OSError as e:
        print(
            f"[hub-doc-pr-generator] Could not re-exec into the persisted interpreter "
            f"{target!r} ({e}) -- it may have been moved or removed. Re-run setup.py "
            "to rediscover a valid Python 3.11+ interpreter. Continuing under the "
            "current interpreter, which may not work correctly.",
            file=sys.stderr,
        )
        return


def discover_oss(*, cwd: Optional[str] = None) -> Optional[str]:
    """Return the OSS impl repo root by walking up from cwd. None if cwd isn't in a git repo."""
    cwd_p = Path(cwd) if cwd else Path.cwd()
    try:
        return _git.run(str(cwd_p), ["rev-parse", "--show-toplevel"]).strip()
    except _git.GitError:
        return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Locate local clones used by the skill.")
    sub = parser.add_subparsers(dest="target", required=True)
    sub.add_parser("hub-doc", help="Print path to local hub-doc clone, or exit 2 if not found.")
    sub.add_parser("oss", help="Print the OSS impl repo root from cwd, or exit 2 if cwd isn't a git repo.")
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
    if args.target == "oss":
        path = discover_oss()
        if path is None:
            print("not a git repo (cwd)", file=sys.stderr)
            return 2
        print(path)
        return 0
    if args.target == "save-hub-doc":
        persist_hub_doc(args.path)
        return 0
    return 1


if __name__ == "__main__":
    maybe_reexec()
    sys.exit(main(sys.argv[1:]))
