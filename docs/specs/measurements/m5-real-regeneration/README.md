# M5.1/M5.2 — real regeneration evidence

Scope decision: a full `--dry-run` regeneration of an entire ROS 1 distro
plus two ROS 2 distros (as M5.1 literally asks) means thousands of packages,
each needing a real GitHub archive fetch for its `package.xml` plus a
`git ls-remote` for its `SRCREV` — many hours of wall-clock time and GitHub
API calls, for validation that M0.1's corpus work and M1's live smoke test
had already covered at the closure-correctness level. Rather than do that
literally, M5.1/M5.2's evidence here comes from two smaller, real checks:

1. **A real, live `superflore-gen-oe-recipes --dry-run --only` run** against
   the actual current `ros/meta-ros` HEAD, for `example_interfaces` and
   `ackermann_msgs` on `jazzy` — the full CLI entry point (`regenerate_pkg`,
   `RosMeta`/`RepoInstance` git-overlay handling, real network fetches),
   not the internal harness M1-M4 used. `--dry-run` guarantees no push and
   no PR filed (confirmed by reading `run.py`: `--dry-run` writes a local
   "saved PR" file and exits before `file_pr()` is ever reached). Diff
   against the pre-run `master` checkout:
   [`jazzy_example_interfaces_ackermann_msgs.diff`](jazzy_example_interfaces_ackermann_msgs.diff).

2. **The M0.1 corpus, re-validated against the shipped production code.**
   [`../validate_corpus_m5.py`](../validate_corpus_m5.py) re-runs the same
   1608 `jazzy`/`kilted` pure-bbappend-corpus check M0.1 did, but through
   the actual `DependencyClosure`/`RosdistroDependencyOracle` classes
   `gen_packages.py` ships, not the standalone measurement script M0.1 used
   before that code existed. Results:
   [`../m5_corpus_validation.csv`](../m5_corpus_validation.csv).

## Result 1: the real diff

Every line the real run added or changed is explained by exactly one of:

* A REP-149 export tag now correctly propagated (the overwhelming majority
  of both diffs — see the `.diff` file for the full `ROS_TRANSITIVE_*`
  blocks).
* One unrelated, pre-existing formatting fix
  (`ROS_BUILD_DEPENDS = " \` → `ROS_BUILD_DEPENDS = "\`, dropping a stray
  space) that predates this branch entirely — it's from the
  `modernize-tooling` branch's "Avoid whitespaces around some variables"
  commit this branch was rebased onto, not from anything in
  `docs/specs/bitbake-export-depends.md`'s scope. Flagging it rather than
  glossing over it is the point of M5.2's "every changed recipe must be
  explainable" check.

`ackermann_msgs` incidentally exercises the *target*-space half of the
closure too (`ROS_TRANSITIVE_EXPORT_DEPENDS = "builtin-interfaces"`, from
its `std_msgs` build_depend), not just the native/buildtool half
`example_interfaces` demonstrates.

## Result 2: the corpus, against production code

| | count | % of 1608 |
| --- | --- | --- |
| Already a direct dependency today (bbappend looks stale regardless) | 120 | 7.5% |
| Explained by the shipped `DependencyClosure` (lands in the recipe's own `DEPENDS`) | 923 | 57.4% |
| Not explained | 565 | 35.1% |

**This refines M0.1's headline number (64%) downward, and the refinement
matters.** M0.1's check accepted a hit from *any* of the three closure
outputs, including `native_variants` (Closure B) — but Closure B is
deliberately never rendered into a recipe's own `DEPENDS` (spec §3.1); it
only feeds `ROS_SUPERFLORE_GENERATED_BUILDTOOLS`. A bbappend entry only
explained via Closure B would *not* actually be fixed by regeneration — the
recipe's `DEPENDS` still wouldn't name it. This script checks only Closure
A (`transitive.target`/`transitive.native`, what actually lands in
`DEPENDS`), which is what M5.3 ("confirm the generated recipe now supplies
the dependency") literally requires. 108 corpus entries that M0.1 counted
as explained flip to unexplained under this stricter check — concentrated
in `rosidl-adapter-native`/`rosidl-parser-native` (a newly-characterized
gap, below).

**File-level (M5.3's actual ask — "mark the bbappend for deletion"):** of
the 349 pure-corpus bbappend files in `jazzy`/`kilted`,

* **99 (28%) are fully explained** — every dependency they add is now
  supplied by the generated recipe. Safe to mark for deletion outright.
* **156 (45%) are partially explained** — at least one added dependency is
  now supplied, but not all. These need trimming to just the
  still-necessary lines, not wholesale deletion.
* **94 (27%) are not explained at all** — see the residual-bucket
  characterization below; these stay as-is.

## The residual, newly-characterized gap: `rosidl_adapter`/`rosidl_parser`

Traced one instance (`ackermann_msgs`, jazzy): `rosidl_generator_c` and
`rosidl_generator_cpp` (both reached in native space via
`rosidl_core_generators`'s `buildtool_export_depend`) declare
`rosidl_parser` only as their own `<exec_depend>` — needed to *run* the
code generator, not exported to whoever the generator serves. Closure A
correctly does not pull `exec_depend`-only reachable packages into a
consumer's `DEPENDS` (that's Closure B's job, and Closure B correctly
registers a `-native` variant for it — confirmed present in the real
`ROS_SUPERFLORE_GENERATED_BUILDTOOLS_JAZZY` this run would produce for the
whole distro). But nothing puts `rosidl-parser-native` into
`ackermann_msgs`'s own `DEPENDS`, because REP-149 has no tag for "the tool
my buildtool exports itself needs this at your build time" — that's a
structurally different obligation than an export tag, and the two together
(85 `rosidl-adapter-native` + 42 `rosidl-parser-native` = 127 corpus
entries) are the single largest newly-identified residual bucket, alongside
the already-known ones from M0.1 (external rosdep-key tooling, `exec_depend`-only
runtime/build split, test-only deps, plain package.xml under-declaration).
This is out of REP-149's tag vocabulary entirely, not a bug in this spec's
closures.
