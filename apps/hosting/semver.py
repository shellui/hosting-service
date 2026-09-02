"""Minimal semantic version parsing and comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_RE = re.compile(
    r'^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$'
)


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: str = ''

    @classmethod
    def parse(cls, value: str) -> SemVer:
        raw = (value or '').strip()
        if not raw:
            raise ValueError('Version is required.')
        match = _VERSION_RE.fullmatch(raw)
        if not match:
            raise ValueError(f'Invalid semver: {value!r}')
        return cls(
            major=int(match.group('major')),
            minor=int(match.group('minor')),
            patch=int(match.group('patch')),
            prerelease=match.group('prerelease') or '',
        )

    def satisfies(self, *, minimum: str, maximum: str | None = None) -> bool:
        current = self
        lower = SemVer.parse(minimum)
        if current < lower:
            return False
        if not maximum:
            return True
        upper = SemVer.parse(maximum)
        return current <= upper


def compare_versions(a: str, b: str) -> int:
    va = SemVer.parse(a)
    vb = SemVer.parse(b)
    if va < vb:
        return -1
    if va > vb:
        return 1
    return 0
