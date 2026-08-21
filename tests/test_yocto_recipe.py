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
"""Offline recipe-rendering tests for the M2 export-closure wiring.

See docs/specs/bitbake-export-depends.md Sec. 2.4/5.3. Reproduces the
example_interfaces worked example with a small, hand-built, fully offline
distro fixture instead of the real jazzy data -- same package names and
dependency shape, trimmed to what's needed to exercise both closures.

Network seams patched per spec Sec. 5.1:
  * get_distros() -- reached via yoctoRecipe._get_ros_version(), called
    unconditionally from yoctoRecipe.__init__().
No other patching is needed: every dependency in this fixture is internal
(a real FakeDistro package), so get_dependencies() never reaches the
rosdep-resolution path; get_srcrev() is short-circuited by pre-seeding
srcrev_cache.
"""

import unittest
from unittest.mock import patch

from superflore.exceptions import UnresolvedDependency
from superflore.generators.bitbake.gen_packages import _gen_recipe_for_package
from superflore.generators.bitbake.yocto_recipe import yoctoRecipe
from tests.bitbake.fixtures import FakeDistro, FakeRosPkg

# Trimmed to spec Sec. 2.4's worked example: example_interfaces build_depends
# nothing, buildtool_depends ament_cmake + rosidl_default_generators.
# rosidl_default_generators buildtool_export_depends action_msgs,
# service_msgs, ament_cmake_core, rosidl_core_generators (exactly as in the
# spec). ament_cmake build_export_depends a 2-package subset of its real
# 14-package export set -- enough to prove the "ament-cmake-* export set"
# claim without transcribing all 14.
EXAMPLE_INTERFACES_PACKAGES = {
    'example_interfaces': {
        'buildtool': ['ament_cmake', 'rosidl_default_generators'],
        'exec': ['rosidl_default_runtime'],
    },
    'ament_cmake': {
        'buildtool': ['cmake'],
        'build_export': ['ament_cmake_core', 'ament_cmake_export_definitions'],
    },
    'cmake': {},
    'rosidl_default_generators': {
        'buildtool': ['ament_cmake'],
        'buildtool_export': [
            'action_msgs',
            'service_msgs',
            'ament_cmake_core',
            'rosidl_core_generators',
        ],
    },
    'action_msgs': {},
    'service_msgs': {},
    'rosidl_core_generators': {},
    'ament_cmake_core': {},
    'ament_cmake_export_definitions': {},
    'rosidl_default_runtime': {},
}


def _render(pkg_name, packages=EXAMPLE_INTERFACES_PACKAGES, skip_keys=None):
    distro = FakeDistro('testdistro', packages)
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
    pkg_rosinstall = [{'tar': {'uri': src_uri}}]
    srcrev_cache = {src_uri: 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'}

    with patch(
        'superflore.generators.bitbake.yocto_recipe.get_distros', return_value={}
    ):
        pkg_recipe = _gen_recipe_for_package(
            distro,
            'wrynose',
            pkg_name,
            pkg,
            repo,
            ros_pkg,
            pkg_rosinstall,
            srcrev_cache,
            skip_keys or [],
        )
        return pkg_recipe.get_recipe_text('Test')


class TestExampleInterfacesRegression(unittest.TestCase):
    """The executable form of the spec's Sec. 2.4 bug report."""

    def setUp(self):
        yoctoRecipe.reset()

    def test_example_interfaces_names_transitive_native_deps(self):
        text = _render('example_interfaces')
        for expected in (
            'action-msgs-native',
            'service-msgs-native',
            'rosidl-core-generators-native',
            'ament-cmake-core-native',
        ):
            self.assertIn(expected, text)

    def test_ament_cmake_no_longer_special_cased(self):
        # Before M2, ament_cmake's own ROS_EXPORT_DEPENDS was hard-coded
        # blank. It should now render its real, non-native export set.
        text = _render('ament_cmake')
        export_line = [
            line for line in text.splitlines() if line.startswith('ROS_EXPORT_DEPENDS')
        ]
        self.assertNotEqual(export_line[0], 'ROS_EXPORT_DEPENDS = ""')
        self.assertIn('ament-cmake-core', text)
        self.assertIn('ament-cmake-export-definitions', text)

    def test_depends_line_includes_transitive_vars(self):
        text = _render('example_interfaces')
        self.assertIn('DEPENDS = "${ROS_BUILD_DEPENDS} ${ROS_BUILDTOOL_DEPENDS}"', text)
        self.assertIn(
            'DEPENDS += "${ROS_EXPORT_DEPENDS} ${ROS_BUILDTOOL_EXPORT_DEPENDS}"',
            text,
        )
        self.assertIn(
            'DEPENDS += "${ROS_TRANSITIVE_EXPORT_DEPENDS} '
            '${ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS}"',
            text,
        )

    def test_no_duplicate_between_direct_and_transitive(self):
        # example_interfaces directly buildtool_depends rosidl_default_generators;
        # rosidl_default_generators buildtool_export_depends ament_cmake_core,
        # which example_interfaces ALSO reaches transitively through
        # ament_cmake's own build_export. ament_cmake_core must not appear
        # twice.
        text = _render('example_interfaces')
        self.assertEqual(text.count('ament-cmake-core-native'), 1)

    def test_empty_transitive_vars_for_leaf_package(self):
        text = _render('cmake')
        self.assertIn('ROS_TRANSITIVE_EXPORT_DEPENDS = ""', text)
        self.assertIn('ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS = ""', text)

    def test_skip_keys_excluded_from_transitive_output(self):
        text = _render('example_interfaces', skip_keys=['action_msgs'])
        self.assertNotIn('action-msgs-native', text)
        # Unaffected siblings still present.
        self.assertIn('service-msgs-native', text)

    def test_native_suffix_placement_for_unresolved_transitive_dep(self):
        # Sec. 2.6: an external (rosdep-key, non-released) dependency
        # reached only transitively must render with "-native" placed
        # *inside* the ${ROS_UNRESOLVED_DEP-...} braces, per
        # modify_name_if_native -- same as a direct one does today.
        packages = {
            'consumer': {'buildtool': ['toolt']},
            'toolt': {'buildtool_export': ['mystery_external_dep']},
        }
        with patch(
            'superflore.generators.bitbake.yocto_recipe.resolve_dep',
            side_effect=UnresolvedDependency('mystery_external_dep'),
        ):
            text = _render('consumer', packages=packages)
        self.assertIn('${ROS_UNRESOLVED_DEP-mystery-external-dep-native}', text)


if __name__ == '__main__':
    unittest.main()
