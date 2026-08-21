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
"""CI guard for docs/specs/bitbake-export-depends.md Sec. 5.1/5.6's hard
requirement: no test in the export-depends suite may touch the network.

Rather than assert on network *absence* (which proves nothing about tests
that simply forgot to try), this blocks every socket connection attempt for
the duration of the test and then actively drives the offline code paths
the rest of the suite relies on -- the closure engine and the recipe
renderer -- through a real network exception, proving they complete without
ever reaching for one.
"""

import socket
import unittest
from unittest.mock import patch

from superflore.generators.bitbake.export_depends import DependencyClosure
from superflore.generators.bitbake.gen_packages import _gen_recipe_for_package
from superflore.generators.bitbake.yocto_recipe import yoctoRecipe
from tests.bitbake.fixtures import FakeDependencyOracle, FakeDistro, FakeRosPkg


class NetworkAccessAttempted(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkAccessAttempted(
        'A test attempted a real socket connection. The export-depends '
        'suite must be fully offline (spec Sec. 5.1).'
    )


class TestNoNetwork(unittest.TestCase):
    def setUp(self):
        yoctoRecipe.reset()
        self._connect_patch = patch.object(socket.socket, 'connect', _blocked)
        self._connect_ex_patch = patch.object(socket.socket, 'connect_ex', _blocked)
        self._connect_patch.start()
        self._connect_ex_patch.start()
        self.addCleanup(self._connect_patch.stop)
        self.addCleanup(self._connect_ex_patch.stop)

    def test_closure_engine_never_touches_network(self):
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

    def test_recipe_rendering_never_touches_network(self):
        packages = {
            'consumer': {'buildtool': ['toolt']},
            'toolt': {'buildtool_export': ['toolu']},
            'toolu': {},
        }
        distro = FakeDistro('testdistro', packages)
        pkg_name = 'consumer'
        pkg = distro.release_packages[pkg_name]
        repo = distro.repositories[pkg.repository_name]
        pkg_xml = distro.get_release_package_xml(pkg_name)
        ros_pkg = FakeRosPkg(pkg_xml, repository_package_names=[pkg_name])
        src_uri = (
            'https://github.com/example/consumer-release/archive/'
            'release/testdistro/consumer/1.0.0-1.tar.gz'
        )
        srcrev_cache = {src_uri: 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'}

        with patch(
            'superflore.generators.bitbake.yocto_recipe.get_distros',
            return_value={},
        ):
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
            text = pkg_recipe.get_recipe_text('Test')
        self.assertIn('toolu-native', text)


if __name__ == '__main__':
    unittest.main()
