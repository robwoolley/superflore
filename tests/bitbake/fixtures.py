"""Shared offline test fixtures for the bitbake generator's test suite.

See docs/specs/bitbake-export-depends.md Sec. 5.1. Hard requirement: no
fixture here may touch the network.
"""

from typing import Iterable


class FakeDependencyOracle:
    """Dict-backed DependencyOracle for closure unit tests.

    ``deps`` maps package name -> depend_type -> list of dependency names,
    e.g. ``{'C': {'build': ['A']}, 'A': {'build_export': ['B']}}``.

    Deliberately strict: querying a package with no entry at all raises
    KeyError, mirroring rosdistro.DependencyWalker raising for a package
    outside release_packages. Every package DependencyClosure might
    legitimately query must have an explicit entry (even an empty ``{}``),
    so a test whose fixture omits a package it expects to stay unexpanded
    (e.g. a rosdep key, or something pruned by skip_keys) will fail loudly
    with a KeyError if the closure ever mistakenly reaches it.
    """

    def __init__(self, deps: dict) -> None:
        self._deps = deps

    def get_depends(self, pkg_name: str, depend_type: str) -> Iterable[str]:
        if pkg_name not in self._deps:
            raise KeyError(pkg_name)
        return list(self._deps[pkg_name].get(depend_type, []))
