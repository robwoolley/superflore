# Copyright 2026 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Transitive REP-149 export-dependency closures for the bitbake generator.

See docs/specs/bitbake-export-depends.md Sec. 3.1 for the design this
implements. Bitbake has no notion of a dependency a package "exports" to
its consumers; ``build_export_depend``/``buildtool_export_depend`` are
REP-149 tags that impose an obligation on whoever *depends on* the
declaring package, not on the package itself. This module computes what
that obligation actually is, transitively, over a two-space dependency
graph (TARGET vs. NATIVE), so the generator can emit it explicitly instead
of relying on bitbake's own (partial, native/target-asymmetric) sysroot
staging to do it by accident.

``DependencyClosure`` is a pure function of a dependency oracle: it only
ever calls ``oracle.get_depends(pkg_name, depend_type)`` and never touches
the network, rosdep, or rosdistro directly. That is what makes it
unit-testable offline against a literal, hand-written dependency graph
(see tests/test_export_depends.py) -- the single most important structural
decision in this module, carried over unchanged from the spec.
"""

from dataclasses import dataclass
from typing import Iterable, Protocol

TARGET = 'TARGET'
NATIVE = 'NATIVE'

_CLOSURE_A_NATIVE_EDGE_TYPES = ('build_export', 'buildtool_export')
_CLOSURE_B_NATIVE_EDGE_TYPES = (
    'build',
    'buildtool',
    'build_export',
    'buildtool_export',
    'exec',
)


class DependencyOracle(Protocol):
    """The only capability DependencyClosure needs from the outside world.

    ``depend_type`` is one of 'build', 'buildtool', 'build_export',
    'buildtool_export', 'exec' -- the same vocabulary
    rosdistro.DependencyWalker.get_depends() uses.
    """

    def get_depends(self, pkg_name: str, depend_type: str) -> Iterable[str]: ...


@dataclass(frozen=True)
class TransitiveDeps:
    """The result of closing over one recipe's REP-149 export obligations.

    ``target``: packages to add to that recipe's target-space DEPENDS
    (feeds ROS_TRANSITIVE_EXPORT_DEPENDS). Already has the recipe's own
    direct build_depend/build_export_depend subtracted out.

    ``native``: packages to add to that recipe's native-space DEPENDS, i.e.
    with a "-native" suffix once rendered (feeds
    ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS). Already has the recipe's own
    direct buildtool_depend/buildtool_export_depend subtracted out.

    ``native_variants``: the full "-native existence closure" (spec Sec.
    2.2/3.1, second closure) -- every package that needs a "-native" variant
    to exist for this recipe's native-space dependency graph to resolve at
    all. Not subtracted against anything and not fed into DEPENDS; its sole
    consumer is ROS_SUPERFLORE_GENERATED_BUILDTOOLS. It is, by construction,
    a superset of ``native`` (same seed, strictly more edge types walked).

    All three fields are sorted tuples, not sets: the whole closure is
    required to be deterministic regardless of dict/set iteration order in
    the oracle backing it (see test_deterministic_ordering).
    """

    target: tuple[str, ...]
    native: tuple[str, ...]
    native_variants: tuple[str, ...]


class DependencyClosure:
    """Computes REP-149 export closures per bitbake-export-depends.md Sec. 3.1.

    ``oracle``: anything satisfying DependencyOracle -- a real distro-backed
    adapter (see RosdistroDependencyOracle below) in production, or a
    literal dict-backed fake in tests.

    ``released_packages``: the set of package names that have a real
    package.xml behind them (rosdistro.release_packages.keys(), typically).
    Anything else -- a rosdep key -- is a leaf: it is emitted but never
    expanded, and the oracle is never queried for it.

    ``skip_keys``: dependency names to drop entirely -- neither emitted nor
    traversed through, mirroring where skip_keys is applied today (inside
    yoctoRecipe.add_*_depend()).
    """

    def __init__(
        self,
        oracle: DependencyOracle,
        released_packages: Iterable[str],
        skip_keys: Iterable[str] = (),
    ) -> None:
        self._oracle = oracle
        self._released = frozenset(released_packages)
        self._skip_keys = frozenset(skip_keys)

    def _depends(self, pkg_name: str, depend_type: str) -> frozenset[str]:
        raw = self._oracle.get_depends(pkg_name, depend_type)
        return frozenset(raw) - self._skip_keys

    def compute(self, pkg_name: str) -> TransitiveDeps:
        direct_target = self._depends(pkg_name, 'build') | self._depends(
            pkg_name, 'build_export'
        )
        direct_native = self._depends(pkg_name, 'buildtool') | self._depends(
            pkg_name, 'buildtool_export'
        )

        closure_target, closure_native = self._walk_closure_a(
            pkg_name, direct_target, direct_native
        )
        native_variants = self._walk_closure_b(pkg_name, direct_native)

        target = closure_target - direct_target - {pkg_name}
        native = closure_native - direct_native - {pkg_name}
        native_variants = native_variants - {pkg_name}

        return TransitiveDeps(
            target=tuple(sorted(target)),
            native=tuple(sorted(native)),
            native_variants=tuple(sorted(native_variants)),
        )

    def _walk_closure_a(
        self,
        pkg_name: str,
        direct_target: frozenset[str],
        direct_native: frozenset[str],
    ) -> tuple[frozenset[str], frozenset[str]]:
        """DEPENDS-completeness closure (spec Sec. 3.1, first closure)."""
        visited_target: set[str] = set()
        visited_native: set[str] = set()
        queue: list[tuple[str, str]] = [(d, TARGET) for d in direct_target]
        queue += [(d, NATIVE) for d in direct_native]

        while queue:
            node, space = queue.pop()
            visited = visited_target if space == TARGET else visited_native
            if node == pkg_name or node in visited:
                continue
            visited.add(node)
            if node not in self._released:
                continue
            if space == TARGET:
                for e in self._depends(node, 'build_export'):
                    if e != pkg_name and e not in visited_target:
                        queue.append((e, TARGET))
                for e in self._depends(node, 'buildtool_export'):
                    if e != pkg_name and e not in visited_native:
                        queue.append((e, NATIVE))
            else:
                for edge_type in _CLOSURE_A_NATIVE_EDGE_TYPES:
                    for e in self._depends(node, edge_type):
                        if e != pkg_name and e not in visited_native:
                            queue.append((e, NATIVE))

        return frozenset(visited_target), frozenset(visited_native)

    def _walk_closure_b(
        self, pkg_name: str, direct_native: frozenset[str]
    ) -> frozenset[str]:
        """-native existence closure (spec Sec. 3.1, second closure).

        Native-space-only: once a node is native, native.bbclass rewrites
        *every* one of its dependency types (build, buildtool,
        build_export, buildtool_export, exec) to "-native", so all five
        must be walked, not just the export tags.
        """
        visited: set[str] = set()
        queue: list[str] = list(direct_native)

        while queue:
            node = queue.pop()
            if node == pkg_name or node in visited:
                continue
            visited.add(node)
            if node not in self._released:
                continue
            for edge_type in _CLOSURE_B_NATIVE_EDGE_TYPES:
                for e in self._depends(node, edge_type):
                    if e != pkg_name and e not in visited:
                        queue.append(e)

        return frozenset(visited)


class RosdistroDependencyOracle:
    """Adapts rosdistro.DependencyWalker to the DependencyOracle protocol.

    Per spec Sec. 3.4: constructing a DependencyWalker throws away its
    parsed-package.xml cache, and _gen_recipe_for_package() used to build a
    fresh one per package. A transitive walk on top of that would multiply
    parse_package_string() calls by the average closure size, so the
    walker is hoisted to one instance per distro name and memoised across
    every RosdistroDependencyOracle constructed for that distro (generation
    is a serial loop, so a class-level cache keyed on distro name is safe).
    """

    _walkers: dict = {}

    def __init__(self, rosdistro_instance, evaluate_condition_context=None) -> None:
        # Imported lazily so importing this module never requires rosdistro
        # to be installed -- the offline unit tests never take this path.
        from rosdistro.dependency_walker import DependencyWalker

        name = rosdistro_instance.name
        if name not in RosdistroDependencyOracle._walkers:
            RosdistroDependencyOracle._walkers[name] = DependencyWalker(
                rosdistro_instance,
                evaluate_condition_context=evaluate_condition_context,
            )
        self._walker = RosdistroDependencyOracle._walkers[name]

    def get_depends(self, pkg_name: str, depend_type: str) -> Iterable[str]:
        return self._walker.get_depends(pkg_name, depend_type)

    @classmethod
    def reset(cls) -> None:
        """Clear the per-distro walker cache.

        Mirrors yoctoRecipe.reset(); the multi-distro loop in run.py must
        not carry one distro's parsed packages into the next.
        """
        cls._walkers = {}
