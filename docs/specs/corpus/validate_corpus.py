#!/usr/bin/env python3
"""Cross-check the pure-bbappend corpus (jazzy/kilted subset) against the
real §3.1 closures: for each (package, added_dep) pair, does the closure
this spec proposes actually contain the dep the bbappend hand-adds?

This turns "here's a pile of hand-written .bbappends" into "here's proof
the proposed closure would have made every one of these unnecessary."
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'measurements'))
import rosdistro  # noqa: E402
from blast_radius import (  # noqa: E402
    MemoizedWalker, CONDITION_CONTEXT, released_packages, closure_a,
    closure_b,
)

DISTRO_DIR_TO_NAME = {
    'meta-ros2-jazzy': 'jazzy',
    'meta-ros2-kilted': 'kilted',
}


def oe_name_to_ros(name):
    """Best-effort reverse of yoctoRecipe.convert_to_oe_name for the common
    case (no '@', not ending in original _native/_dev, no ${OE_VAR})."""
    is_native = name.endswith('-native')
    if is_native:
        name = name[:-len('-native')]
    return name.replace('-', '_'), is_native


def main():
    corpus_csv = sys.argv[1]
    out_csv = sys.argv[2] if len(sys.argv) > 2 else None
    rows = list(csv.DictReader(open(corpus_csv)))
    pure = [r for r in rows if r['pure'] == 'True'
            and r['distro_dir'] in DISTRO_DIR_TO_NAME]

    index = rosdistro.get_index(rosdistro.get_index_url())
    walkers = {}
    released = {}
    for distro_dir, distro_name in DISTRO_DIR_TO_NAME.items():
        dist = rosdistro.get_cached_distribution(index, distro_name)
        walkers[distro_dir] = MemoizedWalker(dist, CONDITION_CONTEXT)
        released[distro_dir] = released_packages(dist)

    closure_cache = {}

    def get_closures(distro_dir, pkg):
        key = (distro_dir, pkg)
        if key not in closure_cache:
            mw = walkers[distro_dir]
            rel = released[distro_dir]
            a_target, a_native = closure_a(mw, rel, pkg)
            b_native = closure_b(mw, rel, pkg)
            direct_all = (
                mw.depends(pkg, 'build') | mw.depends(pkg, 'buildtool')
                | mw.depends(pkg, 'build_export')
                | mw.depends(pkg, 'buildtool_export'))
            closure_cache[key] = (a_target, a_native, b_native, direct_all)
        return closure_cache[key]

    total = 0
    explained = 0
    already_direct = 0
    results = []
    for r in pure:
        distro_dir = r['distro_dir']
        pkg = r['package'].replace('-', '_')
        if pkg not in released[distro_dir]:
            continue
        ros_name, is_native = oe_name_to_ros(r['added_dep'])
        total += 1
        a_target, a_native, b_native, direct_all = get_closures(
            distro_dir, pkg)
        if ros_name in direct_all:
            already_direct += 1
            verdict = 'already_direct'
        elif ros_name in a_target or ros_name in a_native \
                or ros_name in b_native:
            explained += 1
            verdict = 'explained_by_closure'
        else:
            verdict = 'unexplained'
        results.append({
            'distro_dir': distro_dir, 'package': r['package'],
            'added_dep': r['added_dep'], 'ros_name': ros_name,
            'verdict': verdict,
        })

    unexplained = [r for r in results if r['verdict'] == 'unexplained']
    print(f"checked: {total}")
    print(f"already a direct dep today (stale bbappend?): {already_direct}")
    print(f"explained by §3.1 closure: {explained}")
    print(f"NOT explained by closure: {len(unexplained)}")

    if out_csv:
        with open(out_csv, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=[
                'distro_dir', 'package', 'added_dep', 'ros_name', 'verdict'])
            w.writeheader()
            w.writerows(results)
        print(f"wrote {out_csv}")


if __name__ == '__main__':
    main()
