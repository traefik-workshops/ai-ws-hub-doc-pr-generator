"""_semver.py — minimal semver parsing/comparison, stdlib-only.

The rest of this plugin deliberately avoids third-party dependencies (see
preview.py's "no hard dependency" rule in the sibling skill), so this doesn't
reach for `packaging`. Handles the `vX.Y.Z` and `vX.Y.Z-suffix` forms used by
Traefik Hub tags (e.g. `v3.20.0-ea.8`); a final release sorts after any
pre-release of the same X.Y.Z, matching semver precedence.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(.+))?$")


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: Optional[str]
    raw: str

    def key(self) -> tuple:
        # `prerelease is None` sorts True (1) after False (0), so a final
        # release (no prerelease) correctly outranks a pre-release of the
        # same major.minor.patch.
        return (self.major, self.minor, self.patch, self.prerelease is None, self.prerelease or "")


def parse(tag: str) -> Optional[SemVer]:
    m = _RE.match(tag.strip())
    if not m:
        return None
    major, minor, patch, prerelease = m.groups()
    return SemVer(int(major), int(minor), int(patch), prerelease, tag.strip())


def sorted_tags(tags: list[str]) -> list[SemVer]:
    parsed = [p for t in tags if (p := parse(t)) is not None]
    return sorted(parsed, key=lambda s: s.key())


def same_line(a: SemVer, b: SemVer) -> bool:
    return a.major == b.major and a.minor == b.minor
