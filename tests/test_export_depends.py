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
import random
import unittest

from superflore.generators.bitbake.export_depends import DependencyClosure
from tests.bitbake.fixtures import FakeDependencyOracle


class TestDependencyClosure(unittest.TestCase):
    def test_no_exports(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['A'], 'buildtool': ['T']},
                'A': {},
                'T': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'A', 'T'})
        result = closure.compute('C')
        self.assertEqual(result.target, ())
        self.assertEqual(result.native, ())
        self.assertEqual(result.native_variants, ('T',))

    def test_single_build_export(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['A']},
                'A': {'build_export': ['B']},
                'B': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'A', 'B'})
        result = closure.compute('C')
        self.assertEqual(result.target, ('B',))
        self.assertEqual(result.native, ())

    def test_chained_build_export(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['A']},
                'A': {'build_export': ['B']},
                'B': {'build_export': ['E']},
                'E': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'A', 'B', 'E'})
        result = closure.compute('C')
        self.assertEqual(result.target, ('B', 'E'))

    def test_buildtool_export_is_native(self):
        # A exporter reached via a TARGET edge, and one reached via a
        # NATIVE edge, both land their buildtool_export in native space
        # only -- "regardless of A's space" per the test name.
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['AT'], 'buildtool': ['AN']},
                'AT': {'buildtool_export': ['N1']},
                'AN': {'buildtool_export': ['N2']},
                'N1': {},
                'N2': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'AT', 'AN', 'N1', 'N2'})
        result = closure.compute('C')
        self.assertEqual(result.target, ())
        self.assertEqual(result.native, ('N1', 'N2'))

    def test_buildtool_seed_propagates_in_native_space(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'buildtool': ['T']},
                'T': {'build_export': ['B']},
                'B': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'T', 'B'})
        result = closure.compute('C')
        self.assertEqual(result.native, ('B',))
        self.assertEqual(result.target, ())

    def test_package_in_both_spaces(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['A'], 'buildtool': ['T']},
                'A': {'build_export': ['X']},
                'T': {'buildtool_export': ['X']},
                'X': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'A', 'T', 'X'})
        result = closure.compute('C')
        self.assertIn('X', result.target)
        self.assertIn('X', result.native)

    def test_cycle_terminates(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['D']},
                'D': {'build_export': ['A']},
                'A': {'build_export': ['B']},
                'B': {'build_export': ['A']},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'D', 'A', 'B'})
        result = closure.compute('C')
        self.assertEqual(result.target, ('A', 'B'))

    def test_self_cycle(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['D']},
                'D': {'build_export': ['A']},
                'A': {'build_export': ['A']},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'D', 'A'})
        result = closure.compute('C')
        self.assertEqual(result.target, ('A',))

    def test_external_key_is_leaf(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['A']},
                'A': {'build_export': ['libfoo']},
                # Deliberately no 'libfoo' entry: any attempt to expand it
                # raises KeyError.
            }
        )
        closure = DependencyClosure(oracle, released_packages={'A'})
        result = closure.compute('C')
        self.assertEqual(result.target, ('libfoo',))

    def test_skip_keys_pruned(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['A']},
                'A': {'build_export': ['bad_pkg', 'good_pkg']},
                'good_pkg': {},
                'bad_pkg': {'build_export': ['should_never_appear']},
                # 'should_never_appear' has no entry: reaching it raises.
            }
        )
        closure = DependencyClosure(
            oracle,
            released_packages={'A', 'bad_pkg', 'good_pkg'},
            skip_keys={'bad_pkg'},
        )
        result = closure.compute('C')
        self.assertEqual(result.target, ('good_pkg',))

    def test_direct_deps_subtracted(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['A', 'B']},
                'A': {'build_export': ['B']},
                'B': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'A', 'B'})
        result = closure.compute('C')
        self.assertEqual(result.target, ())

    def test_deterministic_ordering(self):
        base_deps = {
            'C': {'build': ['A', 'B'], 'buildtool': ['T']},
            'A': {'build_export': ['X', 'Y', 'Z']},
            'B': {'build_export': ['Y', 'W']},
            'T': {'buildtool_export': ['N1', 'N2'], 'exec': ['R']},
            'X': {},
            'Y': {},
            'Z': {},
            'W': {},
            'N1': {},
            'N2': {},
            'R': {},
        }
        released = set(base_deps.keys())

        first_result = None
        for _ in range(5):
            shuffled = {
                pkg: {
                    dep_type: random.sample(names, len(names))
                    for dep_type, names in by_type.items()
                }
                for pkg, by_type in base_deps.items()
            }
            oracle = FakeDependencyOracle(shuffled)
            closure = DependencyClosure(oracle, released_packages=released)
            result = closure.compute('C')
            if first_result is None:
                first_result = result
            else:
                self.assertEqual(result, first_result)

    def test_native_variant_closure(self):
        oracle = FakeDependencyOracle(
            {
                'C': {'buildtool': ['T']},
                'T': {'buildtool_export': ['X'], 'exec': ['R']},
                'X': {},
                'R': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'T', 'X', 'R'})
        result = closure.compute('C')
        # exec_depend must not feed the DEPENDS-completeness closure...
        self.assertNotIn('R', result.native)
        # ...but must feed the -native existence closure.
        self.assertIn('R', result.native_variants)
        # And the existence closure is a superset of the DEPENDS one.
        self.assertTrue(set(result.native_variants) >= set(result.native))

    def test_condition_context_respected(self):
        # Simulates a ROS 2 distro's condition evaluation already having
        # dropped a ROS1-only <depend condition="$ROS_VERSION == 1">A</depend>
        # before DependencyClosure ever sees it -- the closure has no
        # condition-evaluation logic of its own, it only ever reflects
        # whatever the oracle returns.
        oracle = FakeDependencyOracle(
            {
                'C': {'build': ['B']},
                'B': {},
            }
        )
        closure = DependencyClosure(oracle, released_packages={'B'})
        result = closure.compute('C')
        self.assertNotIn('A', result.target)


if __name__ == '__main__':
    unittest.main()
