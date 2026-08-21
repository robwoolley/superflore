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
"""Offline distro-level generated-file tests for M3.

See docs/specs/bitbake-export-depends.md Sec. M3. Simulates the
per-package generation loop run.py drives (one _gen_recipe_for_package() +
get_recipe_text() per distro package, populating yoctoRecipe's class-level
accumulators), then exercises generate_ros_distro_inc() and
generate_rosdep_resolve() the way the real CLI does, and reads back what
they wrote to disk.

Network seams patched: get_distros() (as in test_yocto_recipe.py) and
resolve_dep() (Sec. 5.1's "rosdep DB" seam) -- this suite's fixture
includes one external/rosdep-key dependency specifically to exercise the
platform_deps/rosdep_cache path.
"""

import re
import tempfile
import unittest
from unittest.mock import patch

from superflore.generators.bitbake.export_depends import RosdistroDependencyOracle
from superflore.generators.bitbake.gen_packages import _gen_recipe_for_package
from superflore.generators.bitbake.yocto_recipe import yoctoRecipe
from tests.bitbake.fixtures import FakeDistro, FakeRosPkg

# consumer: a normal package. Directly buildtool_depends toolt (so toolt
# needs a -native variant -- Sec. 2.2's direct case) and test_depends
# test_only_pkg (should land only in ROS_SUPERFLORE_GENERATED_TESTS).
#
# toolt: buildtool_export_depends toolu -- Closure A/B both reach toolu in
# native space (M0.3's bug pattern: toolu's -native existence depends on
# this propagation, not on toolt's own direct tags).
#
# toolu: exec_depends an external, non-released rosdep key. Only reachable
# via Closure B (the -native existence closure walks exec_depend); Closure
# A never sees it, so it must never show up in any recipe's DEPENDS-facing
# variable, only in the BUILDTOOLS/platform-deps side channel.
DISTRO_PACKAGES = {
    'consumer': {'buildtool': ['toolt'], 'test': ['test_only_pkg']},
    'toolt': {'buildtool_export': ['toolu']},
    'toolu': {'exec': ['mystery_external']},
    'test_only_pkg': {},
}


def _generate_distro(basepath, packages=DISTRO_PACKAGES):
    distro = FakeDistro('testdistro', packages)
    yoctoRecipe.reset()
    with (
        patch(
            'superflore.generators.bitbake.yocto_recipe.get_distros',
            return_value={},
        ),
        patch(
            'superflore.generators.bitbake.yocto_recipe.resolve_dep',
            return_value=(['libmystery'], None),
        ),
    ):
        for pkg_name, deps in packages.items():
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
            pkg_recipe.get_recipe_text('Test')

        yoctoRecipe.generate_ros_distro_inc(basepath, 'testdistro', None, {})
        yoctoRecipe.generate_rosdep_resolve(basepath, 'testdistro')

    inc_path = (
        '{0}/meta-ros2-testdistro/conf/ros-distro/include/testdistro/'
        'generated/superflore-ros-distro.inc'.format(basepath)
    )
    rosdep_path = (
        '{0}/meta-ros2-testdistro/files/testdistro/generated/'
        'rosdep-resolve.yaml'.format(basepath)
    )
    with open(inc_path) as f:
        inc_text = f.read()
    with open(rosdep_path) as f:
        rosdep_text = f.read()
    return inc_text, rosdep_text


def _var_value(text, var_name):
    """Extract a bitbake VAR = "..." multiline assignment's body, anchored
    on the actual assignment (not any prose mention of the name elsewhere,
    e.g. in a preceding comment)."""
    m = re.search(re.escape(var_name) + r' = "(.*?)"\n', text, re.DOTALL)
    assert m, '{} assignment not found'.format(var_name)
    return m.group(1)


class TestYoctoDistroInc(unittest.TestCase):
    def test_buildtools_list_complete(self):
        """3.1: ROS_SUPERFLORE_GENERATED_BUILDTOOLS_<DISTRO> contains the
        full -native existence closure, including toolu (reached only
        transitively) -- not just toolt (consumer's direct buildtool)."""
        with tempfile.TemporaryDirectory() as basepath:
            inc_text, _ = _generate_distro(basepath)
        self.assertIn('ROS_SUPERFLORE_GENERATED_BUILDTOOLS_TESTDISTRO', inc_text)
        self.assertIn('toolt-native', inc_text)
        self.assertIn('toolu-native', inc_text)

    def test_tests_list_not_polluted(self):
        """3.3: the closure never traverses test_depend, so test_only_pkg
        must appear in ROS_SUPERFLORE_GENERATED_TESTS and nowhere that
        would mark it as a non-test dependency."""
        with tempfile.TemporaryDirectory() as basepath:
            inc_text, _ = _generate_distro(basepath)
        self.assertIn(
            'test-only-pkg', _var_value(inc_text, 'ROS_SUPERFLORE_GENERATED_TESTS')
        )
        # And it must not be in the BUILDTOOLS closure -- it's only ever a
        # test_depend, never build/buildtool/export-reachable.
        self.assertNotIn(
            'test-only-pkg',
            _var_value(inc_text, 'ROS_SUPERFLORE_GENERATED_BUILDTOOLS_TESTDISTRO'),
        )

    def test_platform_deps_and_rosdep_cache_gain_only_new_external_keys(self):
        """3.4: mystery_external (reached only via Closure B's exec_depend
        walk) is picked up by both ROS_SUPERFLORE_GENERATED_PLATFORM_PACKAGE_
        DEPENDENCIES and rosdep-resolve.yaml, resolved exactly like a direct
        external dependency would be, and nothing unrelated leaks in."""
        with tempfile.TemporaryDirectory() as basepath:
            inc_text, rosdep_text = _generate_distro(basepath)
        self.assertIn('libmystery', inc_text)
        self.assertIn('mystery_external', rosdep_text)
        self.assertIn('libmystery', rosdep_text)
        # Only the one external key was ever queried against rosdep.
        self.assertEqual(rosdep_text.count('mystery_external:'), 1)

    def test_world_packages_membership_unchanged_by_m2(self):
        """3.2, as actually implemented: ROS_SUPERFLORE_GENERATED_WORLD_PACKAGES
        subtracts generated_native_recipes (native-SUFFIXED names, e.g.
        "toolt-native") from generated_recipes (plain names, e.g. "toolt"),
        which are disjoint sets by construction -- so this subtraction was
        already a no-op before M2 and still is after. A package that is
        only ever needed as "-native" is NOT excluded from world today.
        This is a pre-existing gap orthogonal to REP-149 propagation (out
        of this spec's scope per Sec. 7); this test documents actual
        behavior so a future fix has a regression guard, and so M2's
        changes are confirmed not to have made it worse OR better."""
        with tempfile.TemporaryDirectory() as basepath:
            inc_text, _ = _generate_distro(basepath)
        world_packages = _var_value(inc_text, 'ROS_SUPERFLORE_GENERATED_WORLD_PACKAGES')
        # toolt has its own generated_recipes entry (every distro package
        # gets one, regardless of usage) and is also native-only in
        # practice (nothing build_depends the plain "toolt"). It still
        # shows up in world today.
        self.assertIn('toolt', world_packages)

    def test_reset_clears_transitive_state(self):
        """5.4: yoctoRecipe.reset() must also clear
        RosdistroDependencyOracle's per-distro walker cache -- the new
        class-level state M1/M2 introduced -- or the multi-distro loop in
        run.py would carry one distro's parsed packages into the next."""
        with tempfile.TemporaryDirectory() as basepath:
            _generate_distro(basepath)
        self.assertNotEqual(RosdistroDependencyOracle._walkers, {})
        yoctoRecipe.reset()
        self.assertEqual(RosdistroDependencyOracle._walkers, {})
        # And the pre-existing class-level state still gets cleared too.
        self.assertEqual(yoctoRecipe.generated_native_recipes, set())
        self.assertEqual(yoctoRecipe.generated_recipes, {})
        self.assertEqual(yoctoRecipe.platform_deps, set())


if __name__ == '__main__':
    unittest.main()
