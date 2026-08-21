#!/usr/bin/env python3
"""
M0.4 blast-radius measurement for docs/specs/bitbake-export-depends.md.

Computes the two closures defined in the spec's Section 3.1 ("Design / a
two-space dependency graph") over one or more rosdistro distributions, and
reports, per package:

  * the size of the DEPENDS-completeness closure (Closure A) -- what would be
    added to ROS_TRANSITIVE_EXPORT_DEPENDS / ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS
  * the size of the -native existence closure (Closure B) -- what would be
    added to ROS_SUPERFLORE_GENERATED_BUILDTOOLS
  * the delta against "today's output", i.e. what the generator currently
    computes (direct buildtool_depend/buildtool_export_depend only, plus the
    hard-coded ament_cmake special case from yocto_recipe.py).

This script is standalone measurement tooling for M0 ("no production code")
-- it does not import superflore. It reuses the same rosdistro APIs
(`get_cached_distribution`, `DependencyWalker`) that
superflore/generators/bitbake/gen_packages.py uses, so the closures are
computed against the same data the real generator would see.

Usage:
    python3 blast_radius.py --distro jazzy --distro kilted \
        --out-dir docs/specs/measurements

The first run for a given distro fetches that distro's rosdistro
"distribution cache" (a single compressed file with every release package's
package.xml embedded) over the network and lets rosdistro cache it on disk
(honours ROS_HOME same as any other rosdistro-based tool). Every subsequent
run, and all of the dependency-graph traversal itself, touches no network --
this is the "offline" in "measure the blast radius offline" (spec Task 0.4).

The condition-evaluation context is hard-coded for ROS 2 distributions
(ROS_VERSION=2, ROS_PYTHON_VERSION=3), matching
yoctoRecipe._get_condition_context() for jazzy/kilted. If this script is
ever pointed at a ROS 1 distro, that context must be adjusted.
"""
import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass, field

import rosdistro
from rosdistro.dependency_walker import DependencyWalker

CONDITION_CONTEXT = {
    "ROS_OS_OVERRIDE": "openembedded",
    "ROS_VERSION": "2",
    "ROS_PYTHON_VERSION": "3",
}

DIRECT_TYPES = (
    "build", "buildtool", "build_export", "buildtool_export", "exec",
)


class MemoizedWalker:
    """Wraps DependencyWalker.get_depends with a (pkg, type) cache.

    Closures A and B revisit the same (package, dependency-type) pairs many
    times across the distro-wide sweep (spec Sec. 3.4's performance concern
    applies just as much to this measurement script as to the real
    generator). DependencyWalker already memoizes the parsed package.xml,
    but not the per-type dependency set, so we add that here.
    """

    def __init__(self, distribution_instance, condition_context):
        self._walker = DependencyWalker(
            distribution_instance,
            evaluate_condition_context=dict(condition_context),
        )
        self._cache = {}
        self.errors = {}

    def depends(self, pkg_name, dep_type):
        key = (pkg_name, dep_type)
        if key not in self._cache:
            try:
                self._cache[key] = frozenset(
                    self._walker.get_depends(pkg_name, dep_type))
            except Exception as e:  # noqa: BLE001 -- measurement tool
                self.errors[key] = str(e)
                self._cache[key] = frozenset()
        return self._cache[key]


@dataclass
class ClosureSizes:
    package: str
    direct_native_today: int
    closure_a_target: int
    closure_a_native: int
    closure_b_native: int

    @property
    def native_delta(self):
        return self.closure_b_native - self.direct_native_today


def released_packages(dist):
    return set(dist.release_packages.keys())


def closure_a(mw, released, pkg_name):
    """DEPENDS-completeness closure (spec Sec. 3.1, first closure).

    Returns (target_set, native_set): packages that must be added to
    ROS_TRANSITIVE_EXPORT_DEPENDS / ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS,
    i.e. after subtracting the direct sets already emitted today.
    """
    direct_target = mw.depends(pkg_name, "build") | mw.depends(
        pkg_name, "build_export")
    direct_native = mw.depends(pkg_name, "buildtool") | mw.depends(
        pkg_name, "buildtool_export")

    visited_target = set()
    visited_native = set()
    queue = [(d, "TARGET") for d in direct_target]
    queue += [(d, "NATIVE") for d in direct_native]

    while queue:
        node, space = queue.pop()
        if space == "TARGET":
            if node in visited_target or node == pkg_name:
                continue
            visited_target.add(node)
            if node not in released:
                continue
            for e in mw.depends(node, "build_export"):
                if e not in visited_target:
                    queue.append((e, "TARGET"))
            for e in mw.depends(node, "buildtool_export"):
                if e not in visited_native:
                    queue.append((e, "NATIVE"))
        else:
            if node in visited_native or node == pkg_name:
                continue
            visited_native.add(node)
            if node not in released:
                continue
            for e in (mw.depends(node, "build_export")
                      | mw.depends(node, "buildtool_export")):
                if e not in visited_native:
                    queue.append((e, "NATIVE"))

    transitive_target = visited_target - direct_target - {pkg_name}
    transitive_native = visited_native - direct_native - {pkg_name}
    return transitive_target, transitive_native


def closure_b(mw, released, pkg_name):
    """-native existence closure (spec Sec. 3.1, second closure).

    Returns the full native-space closure (not subtracted against anything
    -- its whole output is "packages that need a -native variant").
    """
    direct_native = mw.depends(pkg_name, "buildtool") | mw.depends(
        pkg_name, "buildtool_export")

    visited = set()
    queue = list(direct_native)
    while queue:
        node = queue.pop()
        if node in visited or node == pkg_name:
            continue
        visited.add(node)
        if node not in released:
            continue
        for dep_type in ("build", "buildtool", "build_export",
                          "buildtool_export", "exec"):
            for e in mw.depends(node, dep_type):
                if e not in visited:
                    queue.append(e)
    return visited


def today_native_set(mw, pkg_name):
    """What yocto_recipe.py puts in generated_native_recipes for this
    package today: direct buildtool_depend + buildtool_export_depend, plus
    the hard-coded ament_cmake special case (Sec. 2.3), which additionally
    native-resolves the package's own direct build_export_depend set."""
    s = mw.depends(pkg_name, "buildtool") | mw.depends(
        pkg_name, "buildtool_export")
    if pkg_name == "ament_cmake":
        s = s | mw.depends(pkg_name, "build_export")
    return s


def measure_distro(distro_name, index):
    print(f"[{distro_name}] fetching cached distribution...", file=sys.stderr)
    t0 = time.time()
    dist = rosdistro.get_cached_distribution(index, distro_name)
    print(f"[{distro_name}] loaded {len(dist.release_packages)} release "
          f"packages in {time.time() - t0:.1f}s", file=sys.stderr)

    mw = MemoizedWalker(dist, CONDITION_CONTEXT)
    released = released_packages(dist)

    rows = []
    t0 = time.time()
    baseline_union = set()
    closure_b_union = set()
    for i, pkg_name in enumerate(sorted(released)):
        direct_native_today = today_native_set(mw, pkg_name)
        baseline_union |= direct_native_today

        closure_a_target, closure_a_native = closure_a(mw, released, pkg_name)
        cb = closure_b(mw, released, pkg_name)
        closure_b_union |= cb

        rows.append(ClosureSizes(
            package=pkg_name,
            direct_native_today=len(direct_native_today),
            closure_a_target=len(closure_a_target),
            closure_a_native=len(closure_a_native),
            closure_b_native=len(cb),
        ))
        if (i + 1) % 500 == 0:
            print(f"[{distro_name}] {i + 1}/{len(released)} packages "
                  f"({time.time() - t0:.1f}s elapsed)", file=sys.stderr)

    print(f"[{distro_name}] closures computed in {time.time() - t0:.1f}s, "
          f"{len(mw.errors)} package(s) errored during traversal",
          file=sys.stderr)
    for (pkg, dep_type), msg in list(mw.errors.items())[:20]:
        print(f"[{distro_name}]   error: {pkg}/{dep_type}: {msg}",
              file=sys.stderr)

    return rows, baseline_union, closure_b_union, len(released)


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "package", "direct_native_today", "closure_a_target_size",
            "closure_a_native_size", "closure_b_native_size",
            "native_delta",
        ])
        for r in sorted(rows, key=lambda r: -r.native_delta):
            w.writerow([
                r.package, r.direct_native_today, r.closure_a_target,
                r.closure_a_native, r.closure_b_native, r.native_delta,
            ])


def summarize(distro_name, rows, baseline_union, closure_b_union,
              total_pkgs):
    deltas = [r.native_delta for r in rows]
    b_sizes = [r.closure_b_native for r in rows]
    a_target_sizes = [r.closure_a_target for r in rows]
    a_native_sizes = [r.closure_a_native for r in rows]

    def pct(v):
        return f"{v:.1f}%"

    lines = []
    lines.append(f"## {distro_name}")
    lines.append("")
    lines.append(f"* Released packages: {total_pkgs}")
    lines.append(
        f"* `ROS_SUPERFLORE_GENERATED_BUILDTOOLS` today (direct "
        f"buildtool_depend/buildtool_export_depend union, incl. the "
        f"ament_cmake special case): **{len(baseline_union)}** packages")
    lines.append(
        f"* `ROS_SUPERFLORE_GENERATED_BUILDTOOLS` under the Sec. 3.1 "
        f"-native existence closure: **{len(closure_b_union)}** packages")
    growth = len(closure_b_union) - len(baseline_union)
    growth_pct = (growth / len(baseline_union) * 100) if baseline_union else 0
    lines.append(
        f"* Growth: **+{growth}** packages ({pct(growth_pct)} relative to "
        f"today; {pct(len(closure_b_union) / total_pkgs * 100)} of the "
        f"whole distro would need a -native variant)")
    lines.append("")
    lines.append("Per-package closure size (Closure B, -native existence):")
    lines.append(
        f"  min={min(b_sizes)} median={statistics.median(b_sizes):.0f} "
        f"mean={statistics.mean(b_sizes):.1f} max={max(b_sizes)} "
        f"p90={statistics.quantiles(b_sizes, n=10)[8]:.0f} "
        f"p99={statistics.quantiles(b_sizes, n=100)[98]:.0f}")
    lines.append("")
    lines.append("Per-package closure size (Closure A target, "
                  "ROS_TRANSITIVE_EXPORT_DEPENDS):")
    lines.append(
        f"  min={min(a_target_sizes)} "
        f"median={statistics.median(a_target_sizes):.0f} "
        f"mean={statistics.mean(a_target_sizes):.1f} "
        f"max={max(a_target_sizes)}")
    lines.append("")
    lines.append("Per-package closure size (Closure A native, "
                  "ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS):")
    lines.append(
        f"  min={min(a_native_sizes)} "
        f"median={statistics.median(a_native_sizes):.0f} "
        f"mean={statistics.mean(a_native_sizes):.1f} "
        f"max={max(a_native_sizes)}")
    lines.append("")
    lines.append("Top 15 packages by native_delta "
                  "(closure_b_native - direct_native_today):")
    for r in sorted(rows, key=lambda r: -r.native_delta)[:15]:
        lines.append(
            f"  {r.package}: today={r.direct_native_today} "
            f"closure={r.closure_b_native} delta=+{r.native_delta}")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--distro", action="append", dest="distros",
                     default=None,
                     help="distro name, repeatable (default: jazzy, kilted)")
    ap.add_argument("--out-dir", default=".",
                     help="directory to write CSVs and the report into")
    args = ap.parse_args()
    distros = args.distros or ["jazzy", "kilted"]

    index = rosdistro.get_index(rosdistro.get_index_url())

    report_sections = [
        "# M0.4 blast-radius measurement\n",
        "Generated by `docs/specs/measurements/blast_radius.py`. See "
        "`docs/specs/bitbake-export-depends.md` Sec. 3.1 and Risk R2.\n",
        "Reproduce: `python3 docs/specs/measurements/blast_radius.py "
        + " ".join(f"--distro {d}" for d in distros)
        + " --out-dir docs/specs/measurements` (requires `rosdistro` and "
        "`catkin_pkg`, both already in requirements.txt; the first run per "
        "distro fetches that distro's rosdistro distribution cache over "
        "the network, everything after that is offline).\n",
    ]
    for distro_name in distros:
        rows, baseline_union, closure_b_union, total_pkgs = measure_distro(
            distro_name, index)
        csv_path = f"{args.out_dir}/{distro_name}_blast_radius.csv"
        write_csv(csv_path, rows)
        print(f"[{distro_name}] wrote {csv_path}", file=sys.stderr)
        report_sections.append(summarize(
            distro_name, rows, baseline_union, closure_b_union, total_pkgs))

    report_path = f"{args.out_dir}/blast_radius_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_sections))
    print(f"wrote {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
