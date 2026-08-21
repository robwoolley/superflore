#!/usr/bin/env python3
"""
M5.2/M5.3 validation: re-checks the M0.1 pure-bbappend corpus against the
*actual shipped* superflore.generators.bitbake.export_depends.DependencyClosure
and RosdistroDependencyOracle, not the standalone measurement script
(docs/specs/measurements/blast_radius.py) M0.1 originally used.

M0.1's validate_corpus.py already showed the *design* explains 64% of the
corpus. This script re-answers the same question with the real production
code path (the same DependencyClosure/RosdistroDependencyOracle
gen_packages.py wires into every recipe), which is what M5.2 ("every
changed recipe must be explainable by a REP-149 export tag") and M5.3
("confirm the generated recipe now supplies the dependency") actually ask
for: not "does the algorithm work" (M0.1/M1 already answered that) but
"does the *shipped* implementation, exercised the way gen_packages.py
exercises it, produce the same result for real packages."

Usage:
    python3 validate_corpus_m5.py docs/specs/corpus/pure_dependency_bbappends.csv \
        --out docs/specs/measurements/m5_corpus_validation.csv
"""

import argparse
import csv

import rosdistro

from superflore.generators.bitbake.export_depends import (
    DependencyClosure,
    RosdistroDependencyOracle,
)
from superflore.generators.bitbake.yocto_recipe import yoctoRecipe

DISTRO_DIR_TO_NAME = {
    'meta-ros2-jazzy': 'jazzy',
    'meta-ros2-kilted': 'kilted',
}


def oe_name_to_ros(name):
    is_native = name.endswith('-native')
    if is_native:
        name = name[: -len('-native')]
    return name.replace('-', '_'), is_native


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('corpus_csv')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.corpus_csv)))
    pure = [
        r for r in rows if r['pure'] == 'True' and r['distro_dir'] in DISTRO_DIR_TO_NAME
    ]

    index = rosdistro.get_index(rosdistro.get_index_url())
    closures = {}
    released = {}
    for distro_dir, distro_name in DISTRO_DIR_TO_NAME.items():
        dist = rosdistro.get_cached_distribution(index, distro_name)
        oracle = RosdistroDependencyOracle(
            dist,
            evaluate_condition_context=yoctoRecipe._get_condition_context(distro_name),
        )
        rel = set(dist.release_packages.keys())
        closures[distro_dir] = DependencyClosure(oracle, released_packages=rel)
        released[distro_dir] = rel

    compute_cache = {}
    results = []
    total = 0
    explained = 0
    already_direct = 0
    for r in pure:
        distro_dir = r['distro_dir']
        pkg = r['package'].replace('-', '_')
        if pkg not in released[distro_dir]:
            continue
        ros_name, _ = oe_name_to_ros(r['added_dep'])
        total += 1

        key = (distro_dir, pkg)
        if key not in compute_cache:
            closure = closures[distro_dir]
            oracle = closure._oracle
            direct_all = (
                set(oracle.get_depends(pkg, 'build'))
                | set(oracle.get_depends(pkg, 'buildtool'))
                | set(oracle.get_depends(pkg, 'build_export'))
                | set(oracle.get_depends(pkg, 'buildtool_export'))
            )
            transitive = closure.compute(pkg)
            compute_cache[key] = (direct_all, transitive)
        direct_all, transitive = compute_cache[key]

        if ros_name in direct_all:
            already_direct += 1
            verdict = 'already_direct'
        elif ros_name in transitive.target or ros_name in transitive.native:
            explained += 1
            verdict = 'explained_by_production_closure'
        else:
            verdict = 'unexplained'
        results.append(
            {
                'distro_dir': distro_dir,
                'package': r['package'],
                'added_dep': r['added_dep'],
                'ros_name': ros_name,
                'verdict': verdict,
            }
        )

    print(f'checked: {total}')
    print(f'already a direct dep today: {already_direct}')
    print(f'explained by production DependencyClosure: {explained}')
    print(f'NOT explained: {total - already_direct - explained}')

    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(
            f, fieldnames=['distro_dir', 'package', 'added_dep', 'ros_name', 'verdict']
        )
        w.writeheader()
        w.writerows(results)
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
