"""assign_target_version.py — rewrite one fragment's target_version in place.

Used by `cut` mode step 2 (see SKILL.md) after the writer confirms which
`unassigned` fragments belong to the release being cut. Pulled out of inline
SKILL.md prose (a `python3 -c` one-liner previously did a literal
`.replace('target_version: unassigned', ...)`) because that literal-string
match silently no-ops on any front-matter form it doesn't expect byte-for-byte
-- verified live: a fragment written as `target_version: "unassigned"` (quoted,
which collect_fragments.parse_fragment already tolerates when reading a
fragment back) left the string completely unchanged, no error, permanently
stranding that fragment as unassigned with zero visible failure. A real,
tested function can raise loudly instead of silently doing nothing.

Usage:
  python -m scripts.assign_target_version --fragment <path> --version <version>
Exits non-zero (with a clear message) if the fragment has no unassigned
target_version line to replace -- never silently no-ops.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

from scripts import _discover, _git
from scripts._frontmatter import UNASSIGNED_TARGET_VERSION_RE, split_front_matter


def assign(content: str, version: str) -> str:
    """Replace the fragment's `target_version: unassigned` line (bare or
    quoted) with `target_version: <version>` (always written unquoted, matching
    templates/release-note-fragment.mdx.tmpl's convention). Raises ValueError
    if no such line is found -- never returns `content` unchanged.

    Also raises if MORE than one such line is found, rather than quietly fixing
    just the first: a well-formed fragment has exactly one `target_version:`
    key, so two is itself malformed front matter (a bad hand-edit or merge),
    not something to guess a "right one" for. Confirmed live that silently
    replacing only the first left the fragment still parsing back as
    `unassigned` (parse_fragment's dict-assignment walk takes the LAST
    occurrence), while this function had already reported success.

    The search is scoped to the front-matter block only, not the whole file --
    confirmed live that scanning the whole content let a coincidental match in
    the fragment's own BODY prose (e.g. documentation text that happens to
    contain the literal string "target_version: unassigned") count as a second
    "duplicate key", permanently blocking assignment with a false "malformed
    front matter" error even though the front matter itself was perfectly
    well-formed."""
    try:
        fm_text, body = split_front_matter(content)
    except ValueError:
        raise ValueError("fragment has no '---' front matter block")

    matches = list(UNASSIGNED_TARGET_VERSION_RE.finditer(fm_text))
    if not matches:
        raise ValueError(
            "no 'target_version: unassigned' line found in this fragment's front matter "
            "-- it may already be assigned, or its front matter doesn't match the expected shape"
        )
    if len(matches) > 1:
        raise ValueError(
            f"found {len(matches)} 'target_version: unassigned' lines in this fragment's front "
            "matter -- that's a duplicate key and needs a human to fix it by hand before it can "
            "be assigned a version"
        )
    # A callable replacement, not an f-string passed straight to `sub`'s `repl`
    # argument -- re.sub treats a STRING repl's backslash-digit sequences
    # (\1, \g<name>, ...) as backreferences, so a version containing one
    # (a plausible typo, e.g. an accidentally-pasted regex fragment) would
    # raise a raw `re.error: invalid group reference` instead of this
    # module's documented clean non-zero exit. A callable's return value is
    # inserted literally -- no backreference processing.
    new_fm = UNASSIGNED_TARGET_VERSION_RE.sub(lambda m: f"target_version: {version}", fm_text, count=1)
    return f"---\n{new_fm}\n---\n{body}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fragment", required=True, help="path to the fragment file to rewrite")
    parser.add_argument("--version", required=True, help="the confirmed target_version to assign")
    parser.add_argument(
        "--doc-repo-root",
        help="path to the hub-doc clone this fragment lives in -- if given, `git add`s the "
             "rewritten fragment there so the reassignment rides along with whatever this cut "
             "eventually commits, instead of staying an uncommitted, easy-to-lose local edit "
             "(cutmode audit finding F: a re-cut of the same still-open version from a "
             "different or fresh clone previously saw this fragment as still `unassigned`, "
             "since nothing in the pipeline ever committed the reassignment). Omit for a "
             "fragment that isn't inside a git repo (e.g. in tests).",
    )
    args = parser.parse_args(argv)
    path = Path(args.fragment)

    # Validate --doc-repo-root and compute rel_path BEFORE writing anything --
    # PR #32 review finding 8: the original fix wrote the fragment's new
    # target_version to disk first and only attempted staging afterward, so a
    # bad --doc-repo-root (not a git repo, or a fragment that isn't actually
    # inside it) left the fragment rewritten-but-unstaged: a broken,
    # re-run-unsafe state, since the unassigned sentinel is already gone and
    # a re-run of this command will just fail with "no unassigned line
    # found". Catching the likely failure classes here, before the write,
    # means those two mistakes leave the fragment completely untouched.
    rel_path: str | None = None
    if args.doc_repo_root:
        repo_root = Path(args.doc_repo_root)
        if not (repo_root / ".git").exists():
            print(f"{args.fragment}: --doc-repo-root {args.doc_repo_root!r} has no .git -- "
                  "not a git repo. Refusing to touch the fragment until this is fixed.",
                  file=sys.stderr)
            return 1
        rel_path = os.path.relpath(path.resolve(), repo_root.resolve())
        if rel_path.startswith(".."):
            print(f"{args.fragment}: is not inside --doc-repo-root {args.doc_repo_root!r} "
                  f"(computed relative path {rel_path!r}). Refusing to touch the fragment "
                  "until this is fixed.", file=sys.stderr)
            return 1

    try:
        path.write_text(assign(path.read_text(encoding="utf-8"), args.version), encoding="utf-8")
    except ValueError as e:
        print(f"{args.fragment}: {e}", file=sys.stderr)
        return 1

    if rel_path is not None:
        try:
            _git.run(args.doc_repo_root, ["add", "--", rel_path])
        except _git.GitError as e:
            # The write already happened and can't be undone here without
            # its own risk of clobbering a concurrent change -- give the
            # operator the exact recovery command instead of a bare "failed
            # to stage" message that leaves the next step a mystery. Do NOT
            # re-run this command: the unassigned sentinel is already gone,
            # so a re-run would just fail with "no unassigned line found".
            print(
                f"{args.fragment}: rewrote target_version -> {args.version} on disk, but failed "
                f"to stage it in {args.doc_repo_root!r}: {e}\n"
                f"Fix the git issue, then run `git -C {args.doc_repo_root} add -- {rel_path}` "
                "manually -- don't re-run this command.",
                file=sys.stderr,
            )
            return 1
    print(f"{args.fragment}: target_version -> {args.version}")
    return 0


if __name__ == "__main__":
    _discover.maybe_reexec()
    sys.exit(main(sys.argv[1:]))
