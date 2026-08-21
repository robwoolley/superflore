"""Shared offline test fixtures for the bitbake generator's test suite.

See docs/specs/bitbake-export-depends.md Sec. 5.1. Hard requirement: no
fixture here may touch the network.
"""

from typing import Iterable, Optional


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


_DEP_TAG_BY_TYPE = {
    'build': 'build_depend',
    'buildtool': 'buildtool_depend',
    'build_export': 'build_export_depend',
    'buildtool_export': 'buildtool_export_depend',
    'exec': 'exec_depend',
    'test': 'test_depend',
}


def make_package_xml(name: str, deps: Optional[dict] = None) -> bytes:
    """A minimal, real, catkin_pkg-parseable package.xml (format 3).

    ``deps`` maps depend_type ('build', 'buildtool', 'build_export',
    'buildtool_export', 'exec', 'test') -> list of dependency names, using
    the same vocabulary as DependencyOracle/DependencyWalker.
    """
    deps = deps or {}
    tags = ''.join(
        '  <{0}>{1}</{0}>\n'.format(_DEP_TAG_BY_TYPE[dep_type], dep)
        for dep_type, names in deps.items()
        for dep in names
    )
    xml = (
        '<?xml version="1.0"?>\n'
        '<package format="3">\n'
        '  <name>{name}</name>\n'
        '  <version>1.0.0</version>\n'
        '  <description>Test fixture for {name}</description>\n'
        '  <maintainer email="test@example.com">Test Maintainer</maintainer>\n'
        '  <license>Apache-2.0</license>\n'
        '{tags}'
        '</package>\n'
    ).format(name=name, tags=tags)
    return xml.encode('utf-8')


class _FakeReleaseRepository:
    def __init__(self, version: str, url: str):
        self.version = version
        self.url = url
        self.tags = ['release']


class _FakeRepository:
    def __init__(self, release_repository):
        self.release_repository = release_repository


class _FakePackage:
    def __init__(self, repository_name: str):
        self.repository_name = repository_name


class FakeDistro:
    """The minimum rosdistro.Distribution surface yoctoRecipe/DependencyWalker
    touch: name, release_packages, repositories[...].release_repository, and
    get_release_package_xml(). See spec Sec. 5.1.

    ``packages`` maps package name -> depend_type dict (as make_package_xml
    takes). Every package gets its own single-package "repository" named
    after itself, versioned "1.0.0-1", so callers never need to think about
    repository grouping.
    """

    def __init__(self, name: str, packages: dict):
        self.name = name
        self.release_packages = {}
        self.repositories = {}
        self._package_xml = {}
        for pkg_name, deps in packages.items():
            repo_name = pkg_name
            self.release_packages[pkg_name] = _FakePackage(repo_name)
            url = 'https://github.com/example/{}-release'.format(
                pkg_name.replace('_', '-')
            )
            self.repositories[repo_name] = _FakeRepository(
                _FakeReleaseRepository('1.0.0-1', url)
            )
            self._package_xml[pkg_name] = make_package_xml(pkg_name, deps)

    def get_release_package_xml(self, pkg_name: str) -> bytes:
        return self._package_xml[pkg_name]


class FakeRosPkg:
    """Stands in for rosdistro.rosdistro.RosPackage: avoids the network
    fetch _gen_recipe_for_package() would otherwise do for a package's own
    package.xml."""

    def __init__(self, pkg_xml: bytes, repository_package_names):
        self._pkg_xml = pkg_xml

        class _Repo:
            package_names = list(repository_package_names)

        self.repository = _Repo()

    def get_package_xml(self, distro_name: str) -> bytes:
        return self._pkg_xml
