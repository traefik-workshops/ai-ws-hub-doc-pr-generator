"""rename_legacy_fragments.py — one-time rename of pre-underscore fragment
filenames to the current `_<pr-number>-<slug>.mdx` convention.

collect_fragments.py's `_PR_NUMBER_RE` deliberately still reads both the
current underscore-prefixed filename and the older unprefixed one, so a
fragment written before the convention changed is never silently dropped
from a `cut`. That's a one-way transition with no code path that ever closes
it back up -- this script is that closing path: it finds any fragment still
using the old shape and renames it in place, so `collect()`'s
`legacy_filenames` list (see its docstring) actually empties out over time
instead of being permanently accepted debt.

Renaming, not rewriting: the `_` prefix only affects the filename (it's what
Docusaurus's default exclude glob matches on), never the fragment's content,
so this never touches front matter or body text.

Usage:
  python -m scripts.rename_legacy_fragments --release-notes-dir <hub-doc-root>/docs/api-gateway/release-notes.d
  python -m scripts.rename_legacy_fragments --release-notes-dir <dir> --apply
Defaults to a dry run (lists what would be renamed); pass --apply to actually
rename.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from scripts import _discover
from scripts.collect_fragments import _PR_NUMBER_RE


def find_legacy_fragments(fragments_dir: Path) -> list[Path]:
    """Every `*.mdx` fragment in `fragments_dir` whose filename doesn't
    already start with the required underscore -- same shape _PR_NUMBER_RE
    accepts on read, restricted here to the ones that need renaming."""
    if not fragments_dir.is_dir():
        return []
    legacy = []
    for path in sorted(fragments_dir.glob("*.mdx")):
        if path.name.startswith("_"):
            continue
        if _PR_NUMBER_RE.match(path.name):
            legacy.append(path)
    return legacy


def rename(path: Path) -> Path:
    """Returns the new path. Raises FileExistsError rather than silently
    overwriting if `_<name>` somehow already exists (e.g. this script was
    already run and only partially completed)."""
    target = path.with_name(f"_{path.name}")
    if target.exists():
        raise FileExistsError(
            f"{target} already exists -- refusing to overwrite; "
            f"remove or resolve {path} manually"
        )
    path.rename(target)
    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release-notes-dir", required=True)
    parser.add_argument("--apply", action="store_true",
                        help="actually rename; without this, only lists what would change")
    args = parser.parse_args(argv)

    legacy = find_legacy_fragments(Path(args.release_notes_dir))
    if not legacy:
        print("no legacy (pre-underscore) fragment filenames found")
        return 0

    for path in legacy:
        if args.apply:
            try:
                new_path = rename(path)
            except FileExistsError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print(f"renamed {path.name} -> {new_path.name}")
        else:
            print(f"would rename {path.name} -> _{path.name}")

    if not args.apply:
        print(f"\n{len(legacy)} fragment(s) would be renamed -- re-run with --apply to do it")
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
