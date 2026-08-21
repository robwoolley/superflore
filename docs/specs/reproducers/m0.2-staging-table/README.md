# M0.2 — sysroot staging table reproducer

Empirically confirms the §2.1 staging table in
`docs/specs/bitbake-export-depends.md` on **wrynose** (6.0.3), the current
latest Yocto release — the spec's own `yocto_releases` dict names it as the
newest known codename. Set up via `bitbake-setup` (see Reproduce below): the
classic single-repo `poky` combo layer on GitHub/git.yoctoproject.org has not
had a `wrynose` branch cut as of this writing, but the split
`openembedded-core`/`bitbake`/`meta-yocto` repos `bitbake-setup` composes it
from do have one (`openembedded-core` on branch `wrynose`, 157 commits past
the `yocto-6.0.2` tag at the time this was run; `meta-yocto` on branch
`wrynose` at "6.0.3 release").

## The scenario

Five trivial `allarch` recipes in `meta-repro/`, modeling a real
superflore-generated dependency shape:

* **libB** — a plain target library. Installs `/usr/include/libb-marker.h`.
* **libA** — `DEPENDS = "libb toolt-native"`. Mirrors a real generated recipe's
  `DEPENDS = "${ROS_BUILD_DEPENDS} ${ROS_BUILDTOOL_DEPENDS}"`: `libb` is
  libA's direct `<build_depend>`, `toolt-native` its direct
  `<buildtool_depend>`. Installs `/usr/include/liba-marker.h`.
* **toolU** — a native-buildable tool (`BBCLASSEXTEND = "native"`). Installs
  `${bindir}/toolu-marker`.
* **toolT** — `DEPENDS = "toolu-native"`, `BBCLASSEXTEND = "native"`. Mirrors
  today's `yocto_recipe.py` strategy for `ROS_BUILDTOOL_EXPORT_DEPENDS`: the
  export is added directly to the declaring recipe's own `DEPENDS`, native
  (spec §2, the "build it as if we needed it" comment). Installs
  `${bindir}/toolt-marker`.
* **C** — `DEPENDS = "liba"`. The consumer. Deliberately mirrors
  `example_interfaces` from the spec's §2.4 worked example: C only names its
  own direct build dependency and never mentions `toolT`, `toolU`, or `libB`
  anywhere in its own recipe — exactly how a real generated recipe looks
  today.

(Every recipe `inherit`s `allarch` to skip the cross-toolchain build
entirely — these are marker-file-only recipes, not real compiled software,
so there's nothing machine-specific to build. This keeps the reproducer to
a ~3 minute cold build instead of an hour+ toolchain bootstrap.)

## What was checked

After `bitbake -c populate_sysroot c`, the actual filesystem content of `C`'s
own recipe-sysroots (`tmp/work/all-poky-linux/c/1.0/recipe-sysroot{,-native}`)
was inspected directly — not `bitbake -e`, not documentation, the literal
files bitbake put on disk for `C`'s own build. `C` never once directly named
`libb`, `toolT`, or `toolU`; every one of those has to reach `C` (or fail to)
purely through the two-hop chain `C → libA → {libB, toolT-native}` (and, one
hop further, `toolT-native → toolU-native`).

## Results

| Edge under test | §2.1 table says | Observed |
| --- | --- | --- |
| `libb` (target) reaching `C` transitively through `liba` (target←target) | staged | **`libb-marker.h` present** in `C`'s `recipe-sysroot` ([evidence](build_log_excerpt.txt)) |
| `toolt-native` (native) reaching `C` transitively through `liba` (native←target) | **pruned** | **absent.** `C`'s `recipe-sysroot-native/sysroot-providers/` lists only generic build-essential native tools (`patch-native`, `pseudo-native`, `quilt-native`, …) — no `toolt-native`, no `toolu-native`, no marker files anywhere under `recipe-sysroot-native` |
| `toolu-native` (native) reaching `C` transitively through `liba` → `toolt-native` (native←target, 2 hops) | **pruned** | **absent**, same as above — confirms the pruning isn't a one-hop artifact |
| `toolu-native` reaching `toolT-native` directly (native←native) | staged | **`toolu-marker` present** in `toolt-native`'s own `recipe-sysroot-native` (`sysroot-providers` lists `toolu-native`) — proves the *direct* native↔native case works fine; the bug is specific to a native dependency reached *through* a target intermediary |

Three of the table's four rows are empirically exercised and confirmed
exactly as written. The fourth (`target ← native`, "cross tools depended
on by target sysroot") is a rare corner case — e.g. nativesdk toolchains
that need target headers — not exercised by any REP-149 propagation pattern
in this spec and not reproduced here; it's taken on the `setscene_depvalid()`
source reading below.

**This directly confirms the spec's central claim**: `C` legitimately needs
`toolT`/`toolU` staged for a correct build (that's the whole meaning of
`buildtool_export_depend` — libA's build tool requirement is inherited by
anyone who builds against libA), but bitbake's real staging behavior drops
exactly that edge. The `libB` control case shows the equivalent *target*-space
export propagates with no special handling required, which is the asymmetry
the whole spec is about.

## Source of the rule

`meta/classes-global/sstate.bbclass`, function `setscene_depvalid()`
(wrynose, confirmed present at the spec-cited location):

```python
# Native/Cross populate_sysroot need their dependencies
if isNativeCross(taskdependees[task][0]) and isNativeCross(taskdependees[dep][0]):
    return False
# Target populate_sysroot depended on by cross tools need to be installed
if isNativeCross(taskdependees[dep][0]):
    return False
# Native/cross tools depended upon by target sysroot are not needed
# Add an exception for shadow-native as required by useradd.bbclass
if isNativeCross(taskdependees[task][0]) and taskdependees[task][0] != 'shadow-native':
    continue
# Target populate_sysroot need their dependencies
return False
```

`task` is the candidate dependency being considered for staging; `dep` is
something that (transitively) depends on it. Read against the empirical
results above: this is the exact code path being exercised.

## Reproduce

Requires network access and ~3 minutes on a normal machine (no toolchain
build, `allarch` throughout). Uses `bitbake-setup`
(https://docs.yoctoproject.org/brief-yoctoprojectqs/index.html#install-and-use-bitbake-setup)
rather than cloning `poky` directly, since the classic combo repo has no
`wrynose` branch yet:

```sh
python3 -m venv --clear ./bitbake-setup-venv
. ./bitbake-setup-venv/bin/activate
pip install bitbake-setup

mkdir wrynose && cd wrynose
bitbake-setup init --non-interactive poky-wrynose poky distro/poky machine/qemux86-64
source bitbake-builds/poky-wrynose/build/init-build-env  # path bitbake-setup prints

bitbake-layers add-layer ../<this-dir>/meta-repro
bitbake -c populate_sysroot c

WD=bitbake-builds/poky-wrynose/build/tmp/work/all-poky-linux/c/1.0
find $WD/recipe-sysroot -iname '*marker*'
find $WD/recipe-sysroot-native -iname '*marker*'
ls $WD/recipe-sysroot-native/sysroot-providers
```

The first two `find` commands are the whole test: the target one should
print `liba-marker.h` and `libb-marker.h`; the native one should print
nothing.
