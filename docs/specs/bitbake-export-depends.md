# Specification: `build_export_depend` / `buildtool_export_depend` support in the bitbake generator

Status: **Draft — for review**
Component: `superflore/generators/bitbake/`
Author: Rob Woolley
Date: 2026-08-21

---

## 1. Problem statement

[REP-149](https://raw.githubusercontent.com/ros-infrastructure/rep/refs/heads/master/rep-0149.rst)
defines two *export* dependency tags:

| Tag | Meaning |
| --- | --- |
| `<build_export_depend>` | A package that must be available **to build packages that build against this package**. |
| `<buildtool_export_depend>` | A build tool that must be available **to build packages that build against this package**, executing on the build machine. |

Both are *propagating* declarations: they describe an obligation that a package
imposes on its **consumers**, not on itself. `catkin`/`ament` implement this
directly — `catkin_package(CATKIN_DEPENDS ...)` and
`ament_export_dependencies()` re-emit `find_package()` calls into the consumer's
CMake configure step, so a consumer transparently acquires whatever its
dependencies exported.

Bitbake has no equivalent concept. `DEPENDS` is a flat, per-recipe list, and
under recipe-specific sysroots (RSS, default since Yocto 2.3) each recipe only
sees what OE decides to stage into *its own* sysroot. There is no mechanism by
which recipe `A` can say "anyone who DEPENDS on me also needs `B`".

The practical consequence, as seen in meta-ros and in layers built on top of it:
metapackages whose entire purpose is to export a dependency set — `ament_cmake`,
`rosidl_default_generators`, `rosidl_core_generators` — do not deliver that set
to consumers. Downstream integrators paper over the gap with hand-written
`.bbappend` files that re-add the missing dependencies, which then rot on every
superflore regeneration.

**Goal:** make `superflore-gen-oe-recipes` emit recipes that are complete on
their own, so that no `.bbappend` is required to satisfy an export dependency
declared anywhere in the ROS distribution.

---

## 2. What the generator does today

Superflore already *reads* both tags. `_gen_recipe_for_package()`
([gen_packages.py:178-215](../../superflore/generators/bitbake/gen_packages.py#L178-L215))
collects them via `DependencyWalker.get_depends(pkg, 'build_export')` and
`get_depends(pkg, 'buildtool_export')`, and `yoctoRecipe` emits them as their
own recipe variables
([yocto_recipe.py:479-545](../../superflore/generators/bitbake/yocto_recipe.py#L479-L545)):

```bitbake
DEPENDS = "${ROS_BUILD_DEPENDS} ${ROS_BUILDTOOL_DEPENDS}"
# Bitbake doesn't support the "export" concept, so build them as if we needed them to build this package (even though we actually
# don't) so that they're guaranteed to have been staged should this package appear in another's DEPENDS.
DEPENDS += "${ROS_EXPORT_DEPENDS} ${ROS_BUILDTOOL_EXPORT_DEPENDS}"
```

That comment is the crux of the bug. The exports are added to the **declaring**
recipe's `DEPENDS`. The assumption that this makes them "guaranteed to have been
staged should this package appear in another's `DEPENDS`" is only true for some
edge types, and is false for exactly the type the metapackages use.

Two mechanisms decide what a consumer actually sees.

### 2.1 Sysroot staging is pruned across the target/native boundary

`do_prepare_recipe_sysroot` walks the *whole* dependency tree and filters it
through `setscene_depvalid()` (`meta/classes-global/sstate.bbclass`). For
`do_populate_sysroot -> do_populate_sysroot` edges the rules are:

| Edge (dependency ← dependee) | Result |
| --- | --- |
| native ← native | staged ("Native/Cross populate_sysroot need their dependencies") |
| target ← native | staged ("Target populate_sysroot depended on by cross tools need to be installed") |
| target ← target | staged ("Target populate_sysroot need their dependencies") |
| **native ← target** | **pruned** ("Native/cross tools depended upon by target sysroot are not needed") |

So the current "build it as if we needed it" trick does work for target-space
exports reached through target dependencies, but a **native** dependency of a
**target** dependency is dropped. Any `<buildtool_export_depend>` that a consumer
reaches indirectly is silently missing from that consumer's sysroot.

### 2.2 A `-native` variant only exists if superflore said so

`meta-ros-common/classes/ros_superflore_generated.bbclass`:

```bitbake
BBCLASSEXTEND:append = "${@bb.utils.contains('ROS_SUPERFLORE_GENERATED_BUILDTOOLS', '${BPN}-native', ' native nativesdk', '', d)}"
```

A recipe is only extended with `native`/`nativesdk` when superflore listed
`<bpn>-native` in `ROS_SUPERFLORE_GENERATED_BUILDTOOLS`, which superflore
populates from `yoctoRecipe.generated_native_recipes` — fed **only** by direct
`<buildtool_depend>` and `<buildtool_export_depend>` edges
([yocto_recipe.py:470-480](../../superflore/generators/bitbake/yocto_recipe.py#L470-L480)).

Meanwhile `native.bbclass` rewrites **both** `DEPENDS` and `RDEPENDS` of a native
variant by appending `-native` to every entry
(`map_dependencies()` over `DEPENDS`, `RDEPENDS`, `RRECOMMENDS`, `RSUGGESTS`,
`RPROVIDES`, `RREPLACES`). Therefore, when package `P` is built as
`P-native`, every one of `P`'s `build_depend`, `buildtool_depend`,
`build_export_depend`, `buildtool_export_depend` and `exec_depend` entries must
*also* exist as a `-native` recipe. Superflore never computes that closure, so
whenever a native variant's own dependency was not itself a direct buildtool
somewhere, bitbake fails with `Nothing PROVIDES '<x>-native'` /
`Nothing RPROVIDES '<x>-native'`.

### 2.3 The `ament_cmake` special case is a symptom

[yocto_recipe.py:499-512](../../superflore/generators/bitbake/yocto_recipe.py#L499-L512)
hard-codes one package by name:

```python
if self.name == 'ament_cmake':
    ret += yoctoRecipe.generate_multiline_variable('ROS_EXPORT_DEPENDS', '') + '\n'
    ament_cmake_native_deps, sys_deps = self.get_dependencies(
        self.export_depends, self.export_depends_external, is_native=True)
    ...
```

This blanks `ament_cmake`'s target exports and re-resolves them into native
space, which registers `ament-cmake-core-native`,
`ament-cmake-export-dependencies-native`, … in
`generated_native_recipes`. It is a manual, single-package instance of the
general closure described in §2.2. Any correct general solution must subsume it.

### 2.4 Worked example

`example_interfaces` (jazzy) generates today as:

```bitbake
ROS_BUILD_DEPENDS = ""
ROS_BUILDTOOL_DEPENDS = " \
    ament-cmake-native \
    rosidl-default-generators-native \
"
ROS_EXPORT_DEPENDS = ""
ROS_BUILDTOOL_EXPORT_DEPENDS = ""
ROS_EXEC_DEPENDS = " \
    rosidl-default-runtime \
"
```

Its upstream `package.xml` gives it two buildtools, and those buildtools export
the rest:

```xml
<!-- rosidl_default_generators -->
<buildtool_depend>ament_cmake</buildtool_depend>
<buildtool_export_depend>action_msgs</buildtool_export_depend>
<buildtool_export_depend>service_msgs</buildtool_export_depend>
<buildtool_export_depend>ament_cmake_core</buildtool_export_depend>
<buildtool_export_depend>rosidl_core_generators</buildtool_export_depend>
```

```xml
<!-- ament_cmake -->
<build_export_depend>ament_cmake_core</build_export_depend>
<build_export_depend>ament_cmake_export_definitions</build_export_depend>
… 11 more …
```

None of `action_msgs`, `service_msgs`, `rosidl_core_generators`,
`ament_cmake_export_*` appear anywhere in `example_interfaces`' recipe.
Whether the build succeeds depends entirely on whether those packages happen to
be reachable through a native←native edge and happen to have had a `-native`
variant generated for some unrelated reason. That is the fragility this
specification removes.

---

## 3. Design

### 3.1 Model: a two-space dependency graph

Model the distribution as a directed graph over nodes `(package, space)` where
`space ∈ {TARGET, NATIVE}`. A package may legitimately appear in both spaces.

**Seed set for the recipe being generated, `C`:**

```
(d, TARGET)  for d in build_depend(C) ∪ build_export_depend(C)
(d, NATIVE)  for d in buildtool_depend(C) ∪ buildtool_export_depend(C)
```

**Propagation edges — `DEPENDS`-completeness closure (§2.1):**

```
from (P, TARGET):  (e, TARGET) for e in build_export_depend(P)
                   (e, NATIVE) for e in buildtool_export_depend(P)
from (P, NATIVE):  (e, NATIVE) for e in build_export_depend(P)
                                        ∪ buildtool_export_depend(P)
```

Rationale: an export obligation is inherited by whoever consumes the package,
in the space that consumer is building for; a buildtool export is always native
because it runs on the build host.

**Propagation edges — `-native` existence closure (§2.2):**

```
from (P, NATIVE):  (e, NATIVE) for e in build_depend(P)
                                        ∪ buildtool_depend(P)
                                        ∪ build_export_depend(P)
                                        ∪ buildtool_export_depend(P)
                                        ∪ exec_depend(P)
```

This closure does **not** feed any recipe's `DEPENDS` (OE stages native←native
transitively on its own). Its sole output is the set of packages that need a
`-native` variant, i.e. `generated_native_recipes` →
`ROS_SUPERFLORE_GENERATED_BUILDTOOLS`.

**Walk rules**

* Only packages present in `rosdistro.release_packages` are expanded; anything
  else is a rosdep key and is a leaf (it has no visible `package.xml`).
* `(package, space)` pairs are memoised; cycles terminate on the visited set.
  ROS dependency graphs *do* contain cycles across export edges — this must be
  handled, not assumed away.
* Conditional dependencies are evaluated with the existing
  `yoctoRecipe._get_condition_context(distro)`.
* `skip_keys` are dropped at the same point they are dropped today (inside
  `add_*_depend`), i.e. a skipped key is not expanded and not emitted.

### 3.2 Recipe output

Keep the four existing variables meaning exactly what they mean today: the
package's own direct tags. Add the closure additively, in separate variables, so
that the direct declarations stay diffable and auditable and the propagated set
is visibly attributable.

```bitbake
ROS_BUILD_DEPENDS = "…"                 # direct <build_depend>
ROS_BUILDTOOL_DEPENDS = "…"             # direct <buildtool_depend>, -native
ROS_EXPORT_DEPENDS = "…"                # direct <build_export_depend>
ROS_BUILDTOOL_EXPORT_DEPENDS = "…"      # direct <buildtool_export_depend>, -native

# Propagated from the <build_export_depend>/<buildtool_export_depend> tags of the
# packages above, transitively. Bitbake has no "export" concept, so superflore
# flattens REP-149 export semantics into this recipe.
ROS_TRANSITIVE_EXPORT_DEPENDS = "…"     # target space
ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS = "…"   # native space, -native

DEPENDS = "${ROS_BUILD_DEPENDS} ${ROS_BUILDTOOL_DEPENDS}"
DEPENDS += "${ROS_EXPORT_DEPENDS} ${ROS_BUILDTOOL_EXPORT_DEPENDS}"
DEPENDS += "${ROS_TRANSITIVE_EXPORT_DEPENDS} ${ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS}"
```

Properties this buys us:

* Purely additive — no existing variable changes meaning, so meta-ros tooling
  and any layer reading `ROS_EXPORT_DEPENDS` keeps working.
* The stale `# Bitbake doesn't support the "export" concept…` comment gets
  replaced by an accurate one.
* A reviewer can tell at a glance which dependencies came from the package
  itself and which superflore inferred.
* No change to `meta-ros` is required for the `DEPENDS` half of the fix. The
  `-native` half lands entirely in the generated
  `ROS_SUPERFLORE_GENERATED_BUILDTOOLS`, which is also generated output.

Entries already present in the direct variables are subtracted from the
transitive variables, so each dependency appears exactly once.

### 3.3 Where the code goes

New module `superflore/generators/bitbake/export_depends.py`, containing a
`DependencyClosure` class that is a **pure function of a dependency oracle** —
it takes an object exposing `get_depends(pkg, type)` and the set of released
package names, and returns the four computed sets. No I/O, no network, no
rosdep. This is what makes the whole feature unit-testable offline, and it is
the single most important structural decision in this spec.

`yoctoRecipe` gains `add_transitive_export_depend()` /
`add_transitive_buildtool_export_depend()` mirroring the existing `add_*`
methods, plus the two new emitted variables.

### 3.4 Performance

`_gen_recipe_for_package()` constructs a **new `DependencyWalker` per package**
([gen_packages.py:178](../../superflore/generators/bitbake/gen_packages.py#L178)),
so its `_packages` XML-parse cache is thrown away ~2600 times per distro. Adding
a transitive walk on top of that would multiply `parse_package_string()` calls
by the average closure size. The walker must be hoisted to one instance per
distro, memoised across packages. Generation is a serial loop
([generate_installers.py:41](../../superflore/generate_installers.py#L41)), so a
module-level cache keyed on the distro is safe.

---

## 4. Milestones

### M0 — Ground the design in evidence *(no production code)*

Nothing else starts until we can point at a failing build and a passing one.

| # | Task |
| --- | --- |
| 0.1 | Collect the real-world corpus: every `.bbappend` in meta-ros and in known downstream layers that exists solely to add a missing build/buildtool dependency. Record package, missing dep, and which REP-149 tag it originates from. This is the acceptance corpus for M5. |
| 0.2 | Build a minimal 3-recipe bitbake reproducer (`libA` exporting `libB`; `toolT` buildtool-exporting `toolU`; consumer `C`) confirming the §2.1 staging table empirically on a current Yocto release. Check the result into `docs/specs/reproducers/`. |
| 0.3 | Confirm §2.2 empirically: pick one package whose `-native` variant is currently only generated by luck, and show the `Nothing PROVIDES` failure when it is not in `ROS_SUPERFLORE_GENERATED_BUILDTOOLS`. |
| 0.4 | Measure the blast radius offline: script the §3.1 closures over the jazzy and kilted distribution caches and report, per package, closure size and the delta to today's output. Specifically: how much does `ROS_SUPERFLORE_GENERATED_BUILDTOOLS` grow? |
| 0.5 | Decide, based on 0.4, whether the `-native` existence closure needs bounding (see Risk R2). Record the decision in this document. |

**Exit criteria:** the staging table in §2.1 is confirmed or corrected in this
document; 0.4's numbers are recorded; the corpus from 0.1 exists. **All met —
see results below.**

#### 0.1 results (measured 2026-08-21)

Corpus: [`docs/specs/corpus/`](corpus/README.md). Scanned every `.bbappend`
in [`ros/meta-ros`](https://github.com/ros/meta-ros) (HEAD, all distros);
"known downstream layers" beyond meta-ros itself were not scanned — no such
layer list was supplied, and meta-ros alone was more than enough evidence
(see the corpus README's scope note).

* **935 `.bbappend` files** exist *solely* to re-add a build/buildtool
  dependency (4528 individual dependency tokens across them) — the
  acceptance corpus for M5.
* Cross-checked the `jazzy`/`kilted` subset (1608 pairs) against the actual
  §3.1 closures (reusing `blast_radius.py`, not reimplemented): **64% are
  explained by the closure** — the dependency the maintainer hand-added is
  sitting in the transitive export set this spec proposes computing, meaning
  those bbappends become deletable under M5.3.
* The 28% "not explained" bucket is not a design gap: it decomposes into
  rosdep-key tooling deps (`python3-numpy-native` etc. — not ROS packages,
  never exported by any tag), an `exec_depend`-only pattern
  (`rosidl_default_runtime`, traced on `ackermann_msgs`: declared only as
  `<exec_depend>`, and REP-149 has no runtime export tag — §7 non-goal), test-only
  deps (`ament-cmake-gtest` et al. — closure never traverses `test_depend`),
  and at least one case of plain `package.xml` under-declaration
  (`backward_ros` re-adds `ament_cmake` as a workaround for never declaring
  it as a buildtool at all — no closure over a tag that was never declared
  can fix that).

#### 0.2 results (measured 2026-08-21)

Reproducer: [`docs/specs/reproducers/m0.2-staging-table/`](reproducers/m0.2-staging-table/README.md).
Five real `.bb` recipes (`libA`/`libB`/`toolT`/`toolU`/`C`, shaped exactly
like a generated recipe's `DEPENDS` today) built with real `bitbake` on
**wrynose** (Yocto 6.0.3, the current latest release — set up via
`bitbake-setup`, since the classic single-repo `poky` combo layer has no
`wrynose` branch cut yet, but the split `openembedded-core`/`meta-yocto`
repos `bitbake-setup` composes it from do). Consumer `C` only ever names
`liba` in its own `DEPENDS`, exactly like `example_interfaces` in the §2.4
worked example.

**The §2.1 staging table is confirmed, not corrected**, on 3 of its 4 rows
(the 4th, `target ← native`, is a rare corner case not exercised by any
REP-149 pattern and wasn't reproduced — confirmed by source reading only):

| Row | Observed in `C`'s real, on-disk `recipe-sysroot{,-native}` |
| --- | --- |
| target ← target: staged | `libb-marker.h` present, though `C` never names `libb` |
| native ← target: **pruned** | `toolt-marker`/`toolu-marker` **absent** — `recipe-sysroot-native/sysroot-providers/` contains no trace of `toolT`/`toolU` at all |
| native ← native: staged | (control case, on `toolT-native` itself) `toolu-marker` present |

This is the direct, on-disk confirmation of the bug: `C` legitimately needs
`toolT`/`toolU` (that's what `buildtool_export_depend` means), the *target*
half of the same shape (`libB`) propagates with zero special handling, and
the *native* half silently vanishes.

#### 0.3 results (measured 2026-08-21)

Reproducer: [`docs/specs/reproducers/m0.3-nothing-provides/`](reproducers/m0.3-nothing-provides/README.md).
Byte-for-byte reproduction of `ros_superflore_generated.bbclass`'s
`BBCLASSEXTEND:append = "${@bb.utils.contains('...GENERATED_BUILDTOOLS', ...)}"`
gate, applied to a `toolU`/`toolT` pair on the same wrynose environment.

* `GENERATED_BUILDTOOLS` not listing `toolu-native` →
  `bitbake -c populate_sysroot toolt-native` fails:
  `ERROR: Nothing PROVIDES 'toolu-native' (but ... toolt_1.0.bb DEPENDS on or
  otherwise requires it)`.
* Adding one line, `GENERATED_BUILDTOOLS = "toolu-native"`, with **no other
  change** → same build succeeds cleanly.

Confirms §2.2 exactly: whether a `-native` variant exists is decided by a
signal (today: some *other* package's *direct* `buildtool_depend`/
`buildtool_export_depend`) entirely disconnected from whether anything
actually needs it, and the failure when they diverge is a hard build error,
not a warning.

#### 0.4 results (measured 2026-08-21)

Script: [`docs/specs/measurements/blast_radius.py`](measurements/blast_radius.py).
It computes both §3.1 closures against the real `jazzy` and `kilted` rosdistro
distribution caches (fetched once via `rosdistro.get_cached_distribution`,
then traversed with zero network access — no superflore code is imported).
Per-package results: [`jazzy_blast_radius.csv`](measurements/jazzy_blast_radius.csv),
[`kilted_blast_radius.csv`](measurements/kilted_blast_radius.csv). Full report:
[`blast_radius_report.md`](measurements/blast_radius_report.md).

| Distro | Released pkgs | `GENERATED_BUILDTOOLS` today | under closure | growth |
| --- | --- | --- | --- | --- |
| jazzy | 2265 | 119 | 269 | **+150 (+126%)**, 11.9% of the distro |
| kilted | 1756 | 113 | 271 | **+158 (+140%)**, 15.4% of the distro |

Per-package closure sizes are heavy-tailed, not uniform: median closure size
is ~20-22 packages, but individual packages spike to 150-200+ even when they
declare only 1-4 direct `buildtool_depend`s. Root cause, confirmed by tracing
`rmf_traffic_editor_test_maps` (jazzy): it directly needs
`rmf_building_map_tools` as a buildtool, which alone has 14 direct
`exec_depend`s; because §2.2's `-native` existence closure must traverse
*every* dependency type once a node is in native space (not just exports —
`native.bbclass` rewrites `RDEPENDS` too), the closure keeps recursing through
`exec_depend → exec_depend → …` and pulls in that tool's entire runtime
dependency graph. This is the exact mechanism Risk R2 warns about, not an
artifact of the measurement.

This confirms R2 is real and material: the unbounded `-native` existence
closure roughly doubles (or more) `ROS_SUPERFLORE_GENERATED_BUILDTOOLS` on
both measured distros, and does so unevenly — a handful of packages account
for most of the growth. See the 0.5 decision below for what to do about it —
truncating the traversal turns out to be the wrong fix, for a reason that
only became clear while running M0.3: it would just reintroduce the
`Nothing PROVIDES` failure at a different depth.

#### 0.5 decision (2026-08-21)

**The `-native` existence closure should stay unbounded. Do not truncate
`exec_depend` traversal.**

Two things learned while running M0.2/M0.3 (§0.2/§0.3 results above) change
the calculus from what R2's mitigation text originally proposed:

1. **Truncating the closure is unsound, not just imprecise.** `native.bbclass`
   rewrites *every* dependency type of a native recipe to `-native`,
   including `RDEPENDS`/`exec_depend` — that's not incidental, it's the
   mechanism M0.3 empirically reproduces the failure through. A closure that
   stops following `exec_depend` past the first buildtool hop leaves exactly
   the same class of `Nothing PROVIDES`/`Nothing RPROVIDES` failure
   unresolved one level deeper. Bounding by truncation doesn't shrink the
   real problem, it relocates it to wherever the cut was made.
2. **The growth mostly isn't build-time cost — it's correctness headroom.**
   `ROS_SUPERFLORE_GENERATED_BUILDTOOLS` only feeds
   `BBCLASSEXTEND:append = "... native nativesdk"`
   (`meta-ros-common/classes/ros_superflore_generated.bbclass`), which makes
   a `-native` variant *buildable if something needs it*; it does not force
   it to build. And `ROS_SUPERFLORE_GENERATED_WORLD_PACKAGES` already
   explicitly subtracts `generated_native_recipes`
   ([yocto_recipe.py:672-673](../../superflore/generators/bitbake/yocto_recipe.py#L672-L673)),
   so growth here does not by itself enlarge `packagegroup-ros-world`. Real
   wall-clock cost is incurred only by builds that actually exercise the
   newly-reachable paths — which, per point 1, are paths that were always
   really needed; today's smaller number was under-counting, not a
   deliberately cheaper correct answer.

Given that, the right place to police cost is M5.5's existing ≤20%
wall-clock budget on a real build, not a closure-shape change now. If M5.5
comes in over budget, revisit — but the fix at that point should be
scoped narrowly (e.g. keeping specific test/demo-only packages like
`rmf_traffic_editor_test_maps`, `autoware_testing`, `ros_testing` — the
worst offenders in the M0.4 data — out of `packagegroup-ros-world` on
policy grounds, which is a world-membership question unrelated to this
spec) rather than a general algorithmic cap that would reopen R2's
underlying failure mode.

This also resolves reviewer open question 1 (§6): the unbounded closure is
acceptable, and is in fact the only closure shape that is *correct*.

### M1 — Closure engine

| # | Task |
| --- | --- |
| 1.1 | Add `superflore/generators/bitbake/export_depends.py` with `DependencyClosure(oracle, released_packages, skip_keys)`. |
| 1.2 | Implement `compute(pkg)` returning `TransitiveDeps(target, native, native_variants)`, per §3.1. Deterministic (sorted) output. |
| 1.3 | Cycle handling via a `(pkg, space)` visited set; add an explicit regression test with a mutually-exporting pair. |
| 1.4 | Add the `oracle` adapter over `rosdistro.DependencyWalker`, with the per-distro memoised walker from §3.4. |
| 1.5 | Add the module to `[tool.mypy] files` in `pyproject.toml` — it is new code with no legacy annotations, so it starts type-clean. |

**Exit criteria:** `tests/test_export_depends.py` green; no network access in
those tests; `ruff` and `mypy` clean.

**Status: done (2026-08-21).** `superflore/generators/bitbake/export_depends.py`
implements `DependencyClosure`/`TransitiveDeps` per §3.1 and
`RosdistroDependencyOracle` per §3.4 (memoised one walker per distro name,
class-level cache, `reset()` classmethod for the multi-distro loop). All 14
tests in `tests/test_export_depends.py` (fixtures in `tests/bitbake/fixtures.py`)
pass, confirmed offline under a real network-namespace isolation (`unshare
--net`), not just absence-of-mocked-calls. `ruff check`/`ruff format --check`
clean; `mypy` reports zero issues for the new module (the 4 pre-existing
report-only errors elsewhere are in `nix/`, untouched by this work).
Cross-validated against real `jazzy` rosdistro data via
`RosdistroDependencyOracle`: `compute('example_interfaces')` reproduces the
exact §2.4 worked example — `action_msgs`, `service_msgs`,
`rosidl_core_generators`, and the full `ament_cmake_export_*` set all land in
`native`, matching what M2's exit criteria expects the rendered recipe to
name. This branch was rebased onto `modernize-tooling`
(https://github.com/robwoolley/superflore/tree/modernize-tooling) first,
which is what supplied `pyproject.toml`/`ruff`/`mypy`/pytest — this spec's
M1.5 and M4's exit criteria assumed that tooling but the base branch
predates it.

### M2 — Wire into recipe generation

| # | Task |
| --- | --- |
| 2.1 | `yoctoRecipe`: add `transitive_export_depends{,_external}` and `transitive_buildtool_export_depends{,_external}` sets plus their `add_*` methods, following the existing internal/external convention. |
| 2.2 | `_gen_recipe_for_package()`: run the closure and feed the two new sets, excluding anything already in a direct set. |
| 2.3 | `get_recipe_text()`: emit `ROS_TRANSITIVE_EXPORT_DEPENDS` and `ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS`; extend `DEPENDS`; replace the inaccurate comment block at [yocto_recipe.py:534-538](../../superflore/generators/bitbake/yocto_recipe.py#L534-L538). |
| 2.4 | Fold the transitive native set into `yoctoRecipe.generated_native_recipes` and the union into `generated_non_test_deps`; route newly-resolved external deps into `platform_deps` and `rosdep_cache` exactly as `get_dependencies()` does today. |
| 2.5 | Remove the `if self.name == 'ament_cmake':` special case and prove by golden-file test that the general closure reproduces (a superset of) its output. |
| 2.6 | Confirm `UNRESOLVED_DEP_REF_PREFIX` handling and `convert_to_oe_name()` `-native` placement (`modify_name_if_native`) behave correctly for transitively-discovered deps. |

**Exit criteria:** golden recipe tests green, including a regenerated
`example_interfaces` that names `action-msgs-native`, `service-msgs-native`,
`rosidl-core-generators-native` and the `ament-cmake-*` export set.

**Status: done (2026-08-21).** All six tasks landed in `yocto_recipe.py`/
`gen_packages.py`. One deliberate addition beyond 2.1's literal wording: a
third set, `native_variant_closure{,_external}` (with `add_native_variant()`),
feeding Closure B (`TransitiveDeps.native_variants`) separately from the two
named sets, which only carry Closure A. This is required, not optional —
folding only Closure A's native output into `generated_native_recipes` would
leave the `exec_depend`-reached packages from §2.2/M0.3 out of
`ROS_SUPERFLORE_GENERATED_BUILDTOOLS` entirely, i.e. M1's whole reason for
having two closures would go unused. `RosdistroDependencyOracle` replaces
the per-package `DependencyWalker` construction in `_gen_recipe_for_package()`
(closing out §3.4's hoisting concern as a side effect), and `yoctoRecipe.reset()`
now also clears its walker cache.

Validated two ways:
* **Live, real jazzy data** (network, `rosdep init`/`update` run locally):
  regenerating `example_interfaces` reproduces §2.4's worked example exactly
  — `ROS_TRANSITIVE_BUILDTOOL_EXPORT_DEPENDS` names `action-msgs-native`,
  `service-msgs-native`, `rosidl-core-generators-native`, and all 14 of
  `ament_cmake`'s `ament-cmake-export-*`/etc. entries, native-suffixed.
  Regenerating `ament_cmake` itself shows its `ROS_EXPORT_DEPENDS` is no
  longer blanked (the special case is gone) — confirms M2.5's "superset"
  requirement via the real graph rather than assumption.
* **Offline golden-file tests**, `tests/test_yocto_recipe.py` (7 tests, a
  hand-built `FakeDistro` fixture reproducing the same worked example at
  smaller scale, patching only `get_distros` — no other network seam is
  reached because every dependency in the fixture is internal): DEPENDS
  includes all three new/changed lines in order, no duplicate between a
  direct and transitive variable, empty-closure packages render `""`,
  `skip_keys` excludes from transitive output, and `-native` placement for
  an *unresolved* transitively-discovered dependency lands inside the
  `${ROS_UNRESOLVED_DEP-...}` braces exactly as it does for a direct one
  (M2.6). All pass under real network-namespace isolation.

`ruff check`/`ruff format --check` clean repo-wide; `mypy` unchanged (the
same 4 pre-existing `nix/` errors, unrelated).

### M3 — Distro-level generated files

| # | Task |
| --- | --- |
| 3.1 | Verify `ROS_SUPERFLORE_GENERATED_BUILDTOOLS_<DISTRO>` now contains the full `-native` existence closure from §3.1. |
| 3.2 | Verify `ROS_SUPERFLORE_GENERATED_WORLD_PACKAGES` is unchanged in spirit: packages that are *only* reachable as native must still be excluded from world. |
| 3.3 | Verify `ROS_SUPERFLORE_GENERATED_TESTS` is not polluted — test-only deps must not be dragged in by the closure (the closure never traverses `test_depend`). |
| 3.4 | Verify `ROS_SUPERFLORE_GENERATED_PLATFORM_PACKAGE_DEPENDENCIES` and `rosdep-resolve.yaml` gain the newly-referenced external keys, and only those. |

**Exit criteria:** `tests/test_yocto_distro_inc.py` green.

### M4 — Test suite

See §5. Delivered incrementally alongside M1–M3; this milestone is the gate that
all of it is present and runs offline in CI.

### M5 — Validation and rollout

| # | Task |
| --- | --- |
| 5.1 | Full `--dry-run` regeneration of one ROS 1 and two ROS 2 distros; commit the diff summary for review. |
| 5.2 | Diff against current meta-ros HEAD: every changed recipe must be explainable by a REP-149 export tag. Investigate any that is not. |
| 5.3 | For each entry in the M0.1 bbappend corpus, confirm the generated recipe now supplies the dependency, and mark the bbappend for deletion. |
| 5.4 | Real bitbake build of `packagegroup-ros-world` (or an agreed subset) on a current LTS release, with the M0.1 bbappends removed. |
| 5.5 | Measure generation wall-clock before/after; regression budget: ≤20% slower (§3.4 hoisting should make it faster, not slower). |
| 5.6 | Document the `--only` caveat (below) in `README.md`; update `CHANGELOG.md`. |
| 5.7 | Coordinate the meta-ros PR: the generated output changes shape, so `ros_superflore_generated.bbclass` reviewers should see the design note. |

**The `--only` caveat.** Flattening a transitive relation means a consumer's
recipe now encodes facts about packages it does not itself name. If package `X`
adds a `<build_export_depend>`, every consumer's recipe becomes stale until
regenerated. Full-distro runs handle this automatically; `--only` and
`--preserve-existing` do not. This must be documented, and M5.6 should consider
whether `--only` should warn.

---

## 5. Test plan

The bitbake generator currently has **zero** test coverage — there is no
`tests/test_yocto*.py` at all. This feature cannot be landed responsibly without
first creating that harness, so the harness is part of the deliverable rather
than a follow-up.

### 5.1 Offline fixtures

`tests/bitbake/fixtures.py` provides:

* `FakeDependencyOracle` — a dict-backed `get_depends(pkg, type)`, letting closure
  tests state a dependency graph literally in the test body.
* `FakeDistro` — the minimum `rosdistro` surface `yoctoRecipe` touches:
  `name`, `release_packages`, `repositories[…].release_repository.version`.
* Seams to patch: `yocto_recipe.resolve_dep` (rosdep DB), `yocto_recipe.get_distros`
  (reached via `_get_ros_version` → `get_cached_index` → network), and
  `yocto_recipe.get_license`. `get_srcrev()` needs no patching — pre-seeding
  `srcrev_cache[src_uri]` short-circuits the `git ls-remote`.

Hard requirement: **no test may touch the network.** Add a CI guard that fails
the suite if it does.

### 5.2 `tests/test_export_depends.py` — closure unit tests

| Test | Asserts |
| --- | --- |
| `test_no_exports` | A package whose deps declare no exports produces empty transitive sets. |
| `test_single_build_export` | `C→A`, `A` exports `B` ⟹ `B` in target set. |
| `test_chained_build_export` | `A` exports `B`, `B` exports `E` ⟹ both in target set. |
| `test_buildtool_export_is_native` | `A` buildtool-exports `N` ⟹ `N` in native set, **not** target set, regardless of `A`'s space. |
| `test_buildtool_seed_propagates_in_native_space` | `C` buildtool-depends `T`, `T` build-exports `B` ⟹ `B` native, not target. |
| `test_package_in_both_spaces` | A package reached by both a build and a buildtool path appears in both sets. |
| `test_cycle_terminates` | `A` exports `B`, `B` exports `A` — terminates, both present, no duplicates. |
| `test_self_cycle` | A package exporting itself is dropped, not emitted. |
| `test_external_key_is_leaf` | A rosdep key not in `release_packages` is emitted but never expanded (no `KeyError`). |
| `test_skip_keys_pruned` | A `skip_keys` entry is neither emitted nor traversed *through*. |
| `test_direct_deps_subtracted` | Anything already in a direct set is absent from the transitive set. |
| `test_deterministic_ordering` | Two runs over a shuffled input produce byte-identical output. |
| `test_native_variant_closure` | The `-native` existence closure includes `exec_depend`s of native nodes (§2.2) and is a superset of the DEPENDS native set. |
| `test_condition_context_respected` | A dependency with `condition="$ROS_VERSION == 1"` is excluded for a ROS 2 distro. |

### 5.3 `tests/test_yocto_recipe.py` — recipe rendering

| Test | Asserts |
| --- | --- |
| `test_simple_recipe_golden` | Baseline `.bb` render matches `tests/bitbake/simple_expected.bb`. Establishes the harness and locks current behaviour. |
| `test_transitive_vars_emitted` | Both new variables render with correct formatting, sorting, `\`-continuation and indentation via `generate_multiline_variable`. |
| `test_empty_transitive_vars` | Empty closure renders `VAR = ""`, matching the existing convention for empty lists. |
| `test_depends_line` | `DEPENDS` includes all six variables in the specified order. |
| `test_no_duplicate_between_direct_and_transitive` | No dependency appears in both a direct and a transitive variable. |
| `test_native_suffix_placement` | Transitive native deps render as `foo-native`, and unresolved ones as `${ROS_UNRESOLVED_DEP-foo-native}` (suffix *inside* the braces, per `modify_name_if_native`). |
| `test_ament_cmake_no_longer_special_cased` | Regenerating `ament_cmake` from a fixture produces a superset of the pre-change hard-coded output — the M2.5 proof. |
| `test_example_interfaces_regression` | The §2.4 example: the generated recipe names `action-msgs-native`, `service-msgs-native`, `ament-cmake-core-native`, `rosidl-core-generators-native`. This is the executable form of the bug report. |

Golden files live in `tests/bitbake/*.bb` and are regenerated by a documented
command, following the `tests/ebuild/simple_expected.ebuild` precedent.

### 5.4 `tests/test_yocto_distro_inc.py` — distro-level output

| Test | Asserts |
| --- | --- |
| `test_buildtools_list_complete` | Every `-native` reference in every generated recipe of a fixture distro appears in `ROS_SUPERFLORE_GENERATED_BUILDTOOLS_<DISTRO>`. **This is the invariant that prevents `Nothing PROVIDES`.** |
| `test_world_excludes_native_only` | Native-only packages stay out of `ROS_SUPERFLORE_GENERATED_WORLD_PACKAGES`. |
| `test_tests_list_not_polluted` | The closure adds nothing to `ROS_SUPERFLORE_GENERATED_TESTS`. |
| `test_platform_deps_and_rosdep_cache` | New external keys appear in both, and are byte-identical between the two files. |
| `test_reset_clears_transitive_state` | `yoctoRecipe.reset()` clears any new class-level state — the multi-distro loop in `run.py` depends on this. |

### 5.5 Whole-distro property tests

Run against a small checked-in distribution-cache fixture (a ~30-package
subgraph containing `ament_cmake`, `rosidl_default_generators`,
`rosidl_core_generators`, an interface package and a plain library):

| Test | Asserts |
| --- | --- |
| `test_dependency_closure_is_complete` | For every generated recipe `C` and every export tag reachable from `C`, the exported package appears in `C`'s `DEPENDS` or is legitimately pruned per the §2.1 table. |
| `test_every_native_reference_resolves` | No recipe references a `-native` that no recipe provides. |
| `test_generation_is_idempotent` | Two consecutive runs produce identical output. |
| `test_no_recipe_depends_on_itself` | Self-dependencies are filtered. |

### 5.6 Out-of-band

* **`test_no_network`** — CI guard per §5.1.
* **Reproducer** from M0.2 checked in; not run in CI (needs bitbake), but
  referenced from this document as the empirical basis.
* **M5.4 real build** is the only true end-to-end validation and remains a
  manual release-gate step.

---

## 6. Risks and open questions

| # | Risk | Mitigation |
| --- | --- | --- |
| **R1** | `DEPENDS` lists grow large. `<depend>` expands to `build` + `build_export` + `exec` in catkin_pkg, so export edges are dense and closures may be big. | Measure in M0.4. Bitbake handles long `DEPENDS` fine; the cost is parse time and reviewability, not correctness. Keeping direct and transitive in separate variables preserves reviewability. |
| **R2** | The `-native` existence closure (§3.1, second closure) traverses `exec_depend` and could pull a large fraction of the distro into `ROS_SUPERFLORE_GENERATED_BUILDTOOLS`, greatly increasing build time. | **Decided (§0.5 decision).** M0.4 confirmed real growth (`+126%` jazzy / `+140%` kilted). M0.3 then showed *why* truncating it is the wrong fix: bounding `exec_depend` traversal reintroduces the exact `Nothing PROVIDES` failure M0.3 reproduces, one level deeper. The closure stays unbounded; cost is policed by M5.5's wall-clock budget instead of by the algorithm. |
| **R3** | Flattening makes recipes stale when an unrelated package changes its exports. | Full regeneration is the normal mode; document the `--only` caveat (M5.6). |
| **R4** | Removing the `ament_cmake` special case regresses something it was silently fixing beyond exports. | M2.5 golden-file superset proof, plus M5.4 real build. |
| **R5** | The §2.1 staging table is derived from reading current `sstate.bbclass`; it may differ on older supported releases (kirkstone → wrynose are all in `yocto_releases`). | **Addressed.** M0.2 reproducer built and empirically verified end-to-end on wrynose (6.0.3, current latest, via `bitbake-setup`). `setscene_depvalid()`'s decisive block (the four `isNativeCross` rules) is byte-for-byte identical in kirkstone (4.0, oldest supported), confirmed by direct source diff — the mechanism has been stable across the whole supported range. |
| **R6** | Generation slowdown from the extra graph walk. | §3.4 walker hoisting; M5.5 budget. |
| **R7** | meta-ros consumers may parse the generated recipes with their own tooling and choke on new variables. | Purely additive output; flag in the M5.7 meta-ros PR. |

**Open questions for reviewers**

1. **R2's bound — resolved, see §0.5 decision.** An unbounded native closure
   is acceptable: it only determines how many `-native` recipes are
   *buildable* (`BBCLASSEXTEND`), not how many actually get built
   (`ROS_SUPERFLORE_GENERATED_WORLD_PACKAGES` already excludes native-only
   packages), and truncating it reopens the `Nothing PROVIDES` failure class
   M0.3 reproduces.
2. Should `ROS_TRANSITIVE_*` instead be appended into the existing
   `ROS_EXPORT_DEPENDS` / `ROS_BUILDTOOL_EXPORT_DEPENDS`? That is a smaller diff
   against meta-ros but loses the direct/inferred distinction and changes the
   meaning of variables other layers may read. This spec recommends separate
   variables.
3. Should superflore emit a machine-readable export map (package → exports) as
   an additional generated `.inc`, letting meta-ros do propagation at parse time
   instead? Rejected here — it requires a coordinated bbclass change, costs parse
   time on every build, and is hard to express in bitbake — but it is the
   alternative worth naming.
4. Does any consumer rely on `ROS_EXPORT_DEPENDS` being empty for `ament_cmake`
   specifically (§2.3)?

---

## 7. Non-goals

* Changing how `exec_depend` / `RDEPENDS` are generated. Bitbake's runtime
  dependency resolution is already transitive; REP-149 has no run-time export tag.
* `<doc_depend>` and `<test_depend>` propagation. `ROS_TEST_DEPENDS` remains
  informational, as the generated comment states.
* The Gentoo and Nix generators. Portage and Nix both have working mechanisms for
  propagated dependencies (`RDEPEND`/`PDEPEND`, `propagatedBuildInputs`); whether
  they use them correctly is a separate question.
* Changing meta-ros bbclasses. All changes here are to superflore's generated
  output, which meta-ros consumes verbatim.
