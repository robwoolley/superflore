# M0.1 — real-world `.bbappend` corpus

Acceptance corpus for M5 (`docs/specs/bitbake-export-depends.md`). Records
every hand-written `.bbappend` in [`ros/meta-ros`](https://github.com/ros/meta-ros)
that exists solely to re-add a build/buildtool dependency the generator
should have emitted itself, and checks how many of them the §3.1 closure
would actually have supplied automatically.

**Scope note:** only `meta-ros` itself was scanned, not "known downstream
layers" as Task 0.1 also asks for — no such layer list was supplied, and
`meta-ros` alone already yields 935 pure corpus entries, a large enough
sample to ground the M1 design and the M5.3 rollout check. A downstream-layer
scan is a reasonable follow-up if the M5 gate needs more evidence, but wasn't
necessary to reach a decision here.

## Method

`scan_bbappends.py <meta-ros checkout> <out.csv>` walks every `*.bbappend`
under a `ros/meta-ros` clone (excluding `generated-recipes/`, which is
superflore's own output, not a hand-written fix) and flags the ones that
append to `DEPENDS` / `ROS_BUILD_DEPENDS` / `ROS_BUILDTOOL_DEPENDS` /
`ROS_EXPORT_DEPENDS` / `ROS_BUILDTOOL_EXPORT_DEPENDS` via `+=` or `:append`.
A bbappend is marked **pure** if, after stripping comments and blank lines,
a dependency addition (and optionally a bare `BBCLASSEXTEND` line) is the
*only* thing left in the file — i.e. nothing else it could plausibly exist
for. Non-pure bbappends (dependency add mixed with patches, QA fixups, etc.)
are recorded too but excluded from the headline corpus since their existence
isn't solely attributable to the export-propagation bug.

`validate_corpus.py` then re-derives the §3.1 closures (reusing
`docs/specs/measurements/blast_radius.py`, no code duplicated) for every pure
corpus entry in the `jazzy`/`kilted` subset and checks whether the
hand-added dependency is a member of the closure the spec proposes computing.
This is the corpus's real payoff: it turns "here is a pile of workarounds"
into "here is proof the proposed closure would have made most of them
unnecessary."

Reproduce (from a repo checkout with `rosdistro`/`catkin_pkg` installed,
already in `requirements.txt`):

```
git clone --depth 1 https://github.com/ros/meta-ros.git /tmp/meta-ros
python3 docs/specs/corpus/scan_bbappends.py /tmp/meta-ros \
    docs/specs/corpus/all_dependency_bbappends.csv
python3 docs/specs/corpus/validate_corpus.py \
    docs/specs/corpus/all_dependency_bbappends.csv \
    docs/specs/corpus/closure_validation.csv
```

The clone step touches the network; the scan and validation are pure text
processing plus the already-offline `blast_radius.py` closures.

## Headline numbers (measured 2026-08-21, meta-ros HEAD)

* 3834 `.bbappend` files total (excluding `generated-recipes/`).
* 1836 touch a `DEPENDS`-family variable at all.
* **935 are "pure"** — their entire reason to exist is adding a dependency.
  This is the acceptance corpus. Full listing:
  [`pure_dependency_bbappends.csv`](pure_dependency_bbappends.csv) (4528 rows,
  one per added dependency token — a single bbappend often adds several).
  The unfiltered superset (including non-pure, for context) is
  [`all_dependency_bbappends.csv`](all_dependency_bbappends.csv).

By inferred REP-149 origin (pure corpus, 4528 tokens):

| Inferred origin | Count |
| --- | --- |
| `buildtool_export_depend`, direct-native gap (added to `ROS_BUILDTOOL_DEPENDS`) | 2198 |
| `build_export_depend`, target-space gap (added to `ROS_BUILD_DEPENDS`/`DEPENDS`, non-native) | 1419 |
| `buildtool_export_depend`, native tool reached via a target recipe (added to `ROS_BUILD_DEPENDS`/`DEPENDS`, native-suffixed — the `vision_msgs` pattern in spec §2.1) | 904 |
| `build_export_depend`, re-declared as if direct (`ROS_EXPORT_DEPENDS`) | 7 |

By distro (pure corpus, files):

| Distro dir | Pure bbappends |
| --- | --- |
| meta-ros2-humble | 188 |
| meta-ros2-kilted | 175 |
| meta-ros2-jazzy | 174 |
| meta-ros2-rolling | 162 |
| meta-ros2-lyrical | 159 |
| meta-spaceros-jazzy | 59 |
| meta-ros1-noetic | 18 |

Top added dependencies (pure corpus) — dominated by exactly the `rosidl`/
`ament_cmake` export-metapackage cluster called out in spec §2.4's worked
example:

| Dependency | Times re-added |
| --- | --- |
| rosidl-typesupport-fastrtps-c-native | 369 |
| rosidl-typesupport-fastrtps-cpp-native | 368 |
| python3-numpy-native | 280 |
| rosidl-adapter-native | 263 |
| rosidl-default-generators-native | 178 |
| service-msgs | 156 |
| rosidl-generator-cpp-native | 147 |
| rosidl-default-runtime(-native) | 142 + 141 |
| rosidl-typesupport-cpp-native | 142 |
| rosidl-generator-py-native | 141 |

## Closure validation (jazzy + kilted subset)

Of the 1608 pure-corpus (package, added-dependency) pairs in `jazzy`/`kilted`
whose recipe is a released package in that distro:

| Verdict | Count | % |
| --- | --- | --- |
| Explained by the §3.1 closure (Closure A or B contains it) | 1031 | 64% |
| Already a direct dependency today (bbappend looks stale) | 120 | 7% |
| **Not** explained by the closure | 457 | 28% |

Full row-level results: [`closure_validation.csv`](closure_validation.csv).

**The 64% is the corpus's core finding**: for nearly two-thirds of these
hand-written workarounds, the dependency the maintainer manually re-added is
sitting right there in the transitive export closure this spec proposes
computing. Those bbappends become deletable under M5.3 without meta-ros
losing anything.

**The 28% "not explained" bucket is not a hole in the design — it's mostly a
different bug, correctly out of scope.** Breaking down the top unexplained
entries:

* `python3-numpy-native` (93), `python3-lark-parser-native` (40),
  `python3-empy-native` (4) — these are rosdep keys (external Python
  tooling), not ROS packages. They're leaves in the closure graph and are
  never *exported* by any package.xml tag; a downstream message package that
  needs the `rosidl` code-generator's own Python dependencies at build time
  has no REP-149 tag that would carry that. Different bug, not addressed by
  this spec.
* `rosidl-default-runtime`/`-native` (121 combined) — traced one instance
  (`ackermann_msgs`, jazzy): `rosidl_default_runtime` is declared only as
  an `<exec_depend>`, never `<build_depend>` or any export tag. REP-149 has
  no export tag for runtime deps, and §7 explicitly excludes changing
  `exec_depend`/`RDEPENDS` handling. This is a message-package-specific
  build/runtime split issue, orthogonal to the propagation bug this spec
  fixes.
* `ament-cmake-gtest`/`ament-cmake-gmock`/`ament-cmake-pytest` (25 combined)
  — test-only dependencies. The closure never traverses `test_depend` by
  design (§7 non-goal, confirmed by `test_tests_list_not_polluted` in the
  M4 test plan).
* `ament-cmake-native`/`ament-cmake-ros(-native)` (backward_ros traced as an
  example) — the consuming package's own `package.xml` doesn't declare the
  buildtool at all (`backward_ros` declares only `cmake`, not
  `ament_cmake`). This is upstream package.xml under-declaration, not a
  propagation gap — no closure over correctly-declared tags can fix a tag
  that was never declared.

The remaining unexplained entries (a few dozen, e.g. `rosidl-adapter-native`,
`action-msgs`, `fastrtps` outside the buckets above) weren't individually
traced; they're flagged in `closure_validation.csv` for anyone doing the
M5.2/M5.3 rollout diff to check by hand.
