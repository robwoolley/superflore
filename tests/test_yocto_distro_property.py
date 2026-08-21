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
"""Whole-distro property tests, spec Sec. 5.5.

A ~25-package, hand-curated, fully offline subgraph using real ROS package
names and dependency shapes trimmed from the real jazzy graph (the same
approach as tests/test_yocto_recipe.py's smaller fixture, scaled up and
diversified): the ament_cmake/rosidl_default_generators/rosidl_core_generators
buildtool cluster, two independent consumers of the resulting interface
package (one target-space, one native-space), a plain library with no
exports at all, a mutually-exporting cycle pair, a test-only dependency,
and one external (rosdep-key) dependency -- everything the spec's four
property tests need in one shared fixture.
"""

import unittest
from unittest.mock import patch

from superflore.generators.bitbake.gen_packages import _gen_recipe_for_package
from superflore.generators.bitbake.yocto_recipe import yoctoRecipe
from tests.bitbake.fixtures import FakeDistro, FakeRosPkg

SUBGRAPH_PACKAGES = {
    # --- ament_cmake / rosidl buildtool cluster ---
    'ament_cmake': {
        'buildtool': ['cmake'],
        'build_export': [
            'ament_cmake_core',
            'ament_cmake_export_definitions',
            'ament_cmake_export_libraries',
            'ament_cmake_python',
        ],
    },
    'cmake': {},
    'ament_cmake_core': {'exec': ['python3_setuptools']},
    'ament_cmake_export_definitions': {},
    'ament_cmake_export_libraries': {},
    'ament_cmake_python': {},
    'rosidl_default_generators': {
        'buildtool': ['ament_cmake'],
        'buildtool_export': [
            'action_msgs',
            'service_msgs',
            'ament_cmake_core',
            'rosidl_core_generators',
        ],
    },
    'rosidl_core_generators': {
        'buildtool': ['ament_cmake'],
        'buildtool_export': ['rosidl_generator_c', 'rosidl_generator_cpp'],
    },
    'rosidl_generator_c': {},
    'rosidl_generator_cpp': {},
    'action_msgs': {
        'buildtool': ['rosidl_default_generators'],
        'exec': ['rosidl_default_runtime'],
    },
    'service_msgs': {'buildtool': ['rosidl_default_generators']},
    'rosidl_default_runtime': {'exec': ['rosidl_runtime_c']},
    'rosidl_runtime_c': {},
    # --- the interface package (spec Sec. 2.4's subject) and two
    # independent consumers of it ---
    'example_interfaces': {
        'buildtool': ['ament_cmake', 'rosidl_default_generators'],
        'exec': ['rosidl_default_runtime'],
        'test': ['example_test_only_pkg'],
    },
    'example_test_only_pkg': {},
    'another_interfaces_pkg': {
        'buildtool': ['ament_cmake', 'rosidl_default_generators'],
        'build': ['example_interfaces'],
    },
    'rclcpp_analog': {
        'buildtool': ['ament_cmake'],
        'build': ['example_interfaces'],
    },
    # --- a plain library: no exports of its own, just an ordinary
    # build_depend chain, ending in a mutually-exporting cycle pair ---
    'example_library': {
        'buildtool': ['cmake'],
        'build': ['example_dependency_lib'],
        'exec': ['example_dependency_lib'],
    },
    'example_dependency_lib': {'build_export': ['mutual_a']},
    'mutual_a': {'build_export': ['mutual_b']},
    'mutual_b': {'build_export': ['mutual_a']},
    'example_transitive_lib': {},
}

ALL_PACKAGE_NAMES = list(SUBGRAPH_PACKAGES.keys())


def _generate_all():
    """Runs the same per-package generation loop run.py drives, over every
    package in SUBGRAPH_PACKAGES, and returns {oe_recipe_name: rendered_text}."""
    distro = FakeDistro('testdistro', SUBGRAPH_PACKAGES)
    yoctoRecipe.reset()
    rendered = {}
    with (
        patch(
            'superflore.generators.bitbake.yocto_recipe.get_distros',
            return_value={},
        ),
        patch(
            'superflore.generators.bitbake.yocto_recipe.resolve_dep',
            return_value=(['python3-setuptools'], None),
        ),
    ):
        for pkg_name in ALL_PACKAGE_NAMES:
            pkg = distro.release_packages[pkg_name]
            repo = distro.repositories[pkg.repository_name]
            pkg_xml = distro.get_release_package_xml(pkg_name)
            ros_pkg = FakeRosPkg(pkg_xml, repository_package_names=[pkg_name])
            src_uri = (
                'https://github.com/example/{}-release/archive/'
                'release/testdistro/{}/1.0.0-1.tar.gz'.format(
                    pkg_name.replace('_', '-'), pkg_name
                )
            )
            srcrev_cache = {src_uri: 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'}
            pkg_recipe = _gen_recipe_for_package(
                distro,
                'wrynose',
                pkg_name,
                pkg,
                repo,
                ros_pkg,
                [{'tar': {'uri': src_uri}}],
                srcrev_cache,
                [],
            )
            recipe_name = yoctoRecipe.convert_to_oe_name(pkg_name)
            yoctoRecipe.generated_recipes[recipe_name] = ('1.0.0', pkg_name)
            rendered[recipe_name] = pkg_recipe.get_recipe_text('Test')
    return rendered


def _all_depends_tokens(text):
    """Every bare dependency token (no ${...} wrapper) referenced by any of
    the DEPENDS-family variables in one recipe's rendered text."""
    tokens = set()
    for var in (
        'ROS_BUILD_DEPENDS',
        'ROS_BUILDTOOL_DEPENDS',
        'ROS_EXPORT_DEPENDS',
        'ROS_BUILDTOOL_EXPORT_DEPENDS',
        'ROS_TRANSITIVE_EXPORT_DEPENDS',
        'ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS',
    ):
        block = text.split(var + ' = "')[1].split('"\n')[0]
        for line in block.splitlines():
            token = line.strip().rstrip('\\').strip()
            if token:
                tokens.add(token)
    return tokens


class TestWholeDistroProperties(unittest.TestCase):
    def test_dependency_closure_is_complete(self):
        """Every package reachable from C via a build_export_depend/
        buildtool_export_depend chain (in the appropriate space) appears
        in C's rendered DEPENDS-family variables -- nothing is left for
        bitbake's own (partial) sysroot staging to paper over."""
        rendered = _generate_all()

        def exported_closure(pkg_name, space):
            """Reference walk, independent of DependencyClosure's own
            internals: everything build_export_depend/buildtool_export_depend
            reachable from pkg_name's direct deps, in the given space."""
            direct_target = set(SUBGRAPH_PACKAGES[pkg_name].get('build', [])) | set(
                SUBGRAPH_PACKAGES[pkg_name].get('build_export', [])
            )
            direct_native = set(SUBGRAPH_PACKAGES[pkg_name].get('buildtool', [])) | set(
                SUBGRAPH_PACKAGES[pkg_name].get('buildtool_export', [])
            )
            visited = set()
            queue = [(d, 'target') for d in direct_target]
            queue += [(d, 'native') for d in direct_native]
            while queue:
                node, node_space = queue.pop()
                if node == pkg_name or node not in SUBGRAPH_PACKAGES:
                    continue
                if (node, node_space) in visited:
                    continue
                visited.add((node, node_space))
                deps = SUBGRAPH_PACKAGES[node]
                if node_space == 'target':
                    for e in deps.get('build_export', []):
                        queue.append((e, 'target'))
                    for e in deps.get('buildtool_export', []):
                        queue.append((e, 'native'))
                else:
                    for e in deps.get('build_export', []) + deps.get(
                        'buildtool_export', []
                    ):
                        queue.append((e, 'native'))
            return (
                {n for n, s in visited if s == space} - direct_target - {pkg_name}
                if space == 'target'
                else {n for n, s in visited if s == space} - direct_native - {pkg_name}
            )

        for pkg_name in ALL_PACKAGE_NAMES:
            recipe_name = yoctoRecipe.convert_to_oe_name(pkg_name)
            tokens = _all_depends_tokens(rendered[recipe_name])
            expected_target = exported_closure(pkg_name, 'target')
            expected_native = exported_closure(pkg_name, 'native')
            for dep in expected_target:
                self.assertIn(
                    yoctoRecipe.convert_to_oe_name(dep),
                    tokens,
                    '{} missing target-space export {}'.format(pkg_name, dep),
                )
            for dep in expected_native:
                self.assertIn(
                    yoctoRecipe.convert_to_oe_name(dep, is_native=True),
                    tokens,
                    '{} missing native-space export {}'.format(pkg_name, dep),
                )

    def test_every_native_reference_resolves(self):
        """No recipe references a "-native" that no recipe provides --
        the exact invariant that prevents Nothing PROVIDES (M0.3)."""
        rendered = _generate_all()
        provided_native = set(yoctoRecipe.generated_native_recipes)
        for pkg_name, text in rendered.items():
            for token in _all_depends_tokens(text):
                if token.endswith('-native') and not token.startswith(
                    '${ROS_UNRESOLVED_DEP-'
                ):
                    self.assertIn(
                        token,
                        provided_native,
                        '{} references {} but nothing provides it'.format(
                            pkg_name, token
                        ),
                    )

    def test_generation_is_idempotent(self):
        first = _generate_all()
        second = _generate_all()
        self.assertEqual(first, second)

    def test_no_recipe_depends_on_itself(self):
        rendered = _generate_all()
        for pkg_name in ALL_PACKAGE_NAMES:
            recipe_name = yoctoRecipe.convert_to_oe_name(pkg_name)
            tokens = _all_depends_tokens(rendered[recipe_name])
            self.assertNotIn(recipe_name, tokens)
            self.assertNotIn(recipe_name + '-native', tokens)


if __name__ == '__main__':
    unittest.main()
