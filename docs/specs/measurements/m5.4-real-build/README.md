# M5.4 — real bitbake build

**Result: success.** A real `bitbake ros-core` build (`ros-core`'s full
445-package `RDEPENDS` closure — `rclcpp`, `rclpy`, `launch`, `sros2`, the
`ament`/`rosidl` toolchain, etc. — not just the empty metapackage shell;
confirmed via `bitbake -g ros-core` before running) completed with **5850
tasks attempted, all succeeded**, on Yocto **wrynose** (6.0) + ROS 2
**jazzy**, `qemux86-64`, `DISTRO = "ros2"` (`meta-ros2`'s own distro conf).
5 real packages regenerated with the fixed superflore, their now-redundant
`.bbappend` files removed, as part of that build.

Scope note on where M5.4's package-set decision came from: the original
ask ("packagegroup-ros-world or an agreed subset") was narrowed to
`ros-core`, an explicit user decision after `packagegroup-ros-world`'s
likely multi-hour, thousands-of-package cost was flagged — `ros-core` is
still the *real* dependency closure of a genuine, meaningful ROS 2
metapackage (not a token stand-in), just bounded to something that
completes in hours, not days.

## Setup

* Environment: `bitbake-setup init poky-wrynose poky distro/poky machine/qemux86-64`,
  then `distro/poky` swapped for `DISTRO = "ros2"` (meta-ros requires its
  own distro conf) and `machine/qemux86-64` kept.
* Layers added on top: `meta-openembedded` (`meta-oe`, `meta-python`,
  `meta-networking`, `meta-perl`, `meta-filesystems`, all `wrynose` branch)
  and `meta-ros` (`meta-ros-common`, `meta-ros2`, `meta-ros2-jazzy`, `wrynose`
  branch) — the layer set `meta-ros2-jazzy/conf/layer.conf`'s own
  `LAYERDEPENDS` declares, cross-checked against `ros/meta-ros`'s own `kas/`
  configs (`kas/yocto/wrynose.yml`, `kas/ros2/jazzy.yml`) for the minimum
  non-GUI set (`kas`'s full config additionally pulls in `qt5`/`meta-gnome`/
  `meta-xfce`/`zenoh` for a bootable image with a desktop, none of which
  `ros-core` itself needs).
* `BB_NUMBER_THREADS = "4"`, `PARALLEL_MAKE = "-j 2"` — deliberately
  conservative for the available 8 cores / ~15GB RAM, to avoid OOM/thrashing
  on heavy C++ template compiles (rclcpp, fastrtps) rather than maximizing
  throughput.
* **Everything under `/opt` (persistent disk), nothing under `/tmp`.** An
  earlier attempt at this same build was started under `/tmp` (tmpfs,
  RAM-backed, 7.8GB total) and was stopped mid-build once that was flagged
  as wrong — the eventual real build consumed **~74GB**, which would never
  have fit in `/tmp` regardless of how it failed. Rebuilt from scratch
  under `/opt/bitbake-export-depends/scratch` (gitignored) instead.

## What was tested

The same 5 packages from the `ros-core` dependency closure that M5.1/M5.3
found have fully-explained `.bbappend`s (every dependency they add is now
supplied by the closure fix): `iceoryx_binding_c`, `composition_interfaces`,
`rosidl_typesupport_fastrtps_c`, `rosidl_typesupport_fastrtps_cpp`,
`unique_identifier_msgs`. Regenerated with the fixed superflore
(`--only <these 5> --dry-run --skip-keys libatomic`, see below), their
corresponding `.bbappend` files deleted, then `bitbake ros-core` run for
real against the resulting tree — the actual thing M5.4 asks for: does a
real build succeed with the compensating hand-written workarounds gone,
now that the generator supplies what they used to supply.

All 5 built successfully, both target and native variants where
applicable (confirmed directly in the log, not just inferred from the
overall summary):

```
recipe unique-identifier-msgs-native-2.5.1-1-r0: task do_populate_sysroot: Succeeded
recipe iceoryx-binding-c-native-2.0.6-1-r0: task do_populate_sysroot: Succeeded
recipe iceoryx-binding-c-2.0.6-1-r0: task do_populate_sysroot: Succeeded
recipe unique-identifier-msgs-2.5.1-1-r0: task do_populate_sysroot: Succeeded
recipe composition-interfaces-2.0.4-1-r0: task do_populate_sysroot: Succeeded
recipe rosidl-typesupport-fastrtps-cpp-native-3.6.4-1-r0: task do_populate_sysroot: Succeeded
recipe rosidl-typesupport-fastrtps-c-native-3.6.4-1-r0: task do_populate_sysroot: Succeeded
recipe rosidl-typesupport-fastrtps-cpp-3.6.4-1-r0: task do_populate_sysroot: Succeeded
recipe rosidl-typesupport-fastrtps-c-3.6.4-1-r0: task do_populate_sysroot: Succeeded
```

## A genuine finding along the way: `libatomic` → `gcc-runtime`

The first attempt (before the `/tmp`→`/opt` redo, same 5 packages, no
`--skip-keys`) failed with `Nothing PROVIDES 'gcc-runtime-native'`. Traced
to a real, structural edge case, not a bug in the closure logic:

* `rcutils` (a foundational ROS 2 C library, reached in native space by
  every one of these 5 packages through the ordinary `ament_cmake`/
  `rosidl_default_generators` chain) genuinely declares
  `<build_export_depend>libatomic</build_export_depend>` in its real
  upstream `package.xml`. The closure correctly discovers this — that's
  Closure A working exactly as designed.
* `libatomic` is a rosdep key that resolves (`resolve_dep('libatomic',
  'openembedded', 'jazzy')`) to `gcc-runtime@openembedded-core` — a real,
  normal, buildable *target*-space OE-core recipe. But `gcc-runtime` has no
  `-native` variant, structurally: a native build links against the *host
  compiler's own* libatomic/libgcc, not a cross-built OE one, so
  `BBCLASSEXTEND = "native"` was never added to it and conceptually
  shouldn't be.
* Superflore's existing `get_dependencies(..., is_native=True)` /
  `convert_to_oe_name(..., is_native=True)` machinery — used for *every*
  native-space rendering, direct or transitive, unchanged by this spec —
  blindly appends `-native` to whatever a rosdep key resolves to. This
  latent gap predates this work; the closure fix didn't introduce it, it
  just reaches far enough into the graph (`rcutils` is reached by nearly
  everything) to actually trigger it for the first time in practice.
* **Fix used to complete this validation:** `--skip-keys libatomic` on the
  regeneration command — the existing, designed-for-exactly-this escape
  hatch (already a first-class superflore feature, used throughout real
  meta-ros `.bbappend`s and `ROS_SUPERFLORE_GENERATION_SKIP_LIST` today).
  Not a workaround invented for this validation; it's the intended
  mechanism for "OE doesn't have a good story for this specific
  dependency."

This is a real, useful thing to flag for whoever picks up the actual
meta-ros regeneration (M5.7): a full-distro run will hit this same
`gcc-runtime-native` wall on *every* package whose native-space closure
reaches `rcutils` — which, given `rcutils`'s centrality, is likely most of
the distro. `libatomic` should go in that regeneration's `--skip-keys`
(or wherever meta-ros's existing skip-list lives) from the start, not be
discovered mid-run.

## Reproduce

```sh
python3 -m venv bitbake-setup-venv && . bitbake-setup-venv/bin/activate
pip install bitbake-setup
mkdir yocto-ros-core && cd yocto-ros-core
bitbake-setup init --non-interactive poky-wrynose poky distro/poky machine/qemux86-64
sed -i 's#OE_FRAGMENTS += "distro/poky machine/qemux86-64"#OE_FRAGMENTS += "machine/qemux86-64"#' \
    bitbake-builds/poky-wrynose/build/conf/toolcfg.conf
cat >> bitbake-builds/poky-wrynose/build/conf/local.conf <<'EOF'
DISTRO = "ros2"
BB_NUMBER_THREADS = "4"
PARALLEL_MAKE = "-j 2"
EOF

mkdir layers && cd layers
git clone --depth 1 --branch wrynose https://github.com/openembedded/meta-openembedded.git
git clone --depth 1 --branch wrynose https://github.com/ros/meta-ros.git
cd ..

. bitbake-builds/poky-wrynose/layers/oe-init-build-env-dir/oe-init-build-env bitbake-builds/poky-wrynose/build
bitbake-layers add-layer \
  layers/meta-openembedded/meta-oe layers/meta-openembedded/meta-python \
  layers/meta-openembedded/meta-networking layers/meta-openembedded/meta-perl \
  layers/meta-openembedded/meta-filesystems \
  layers/meta-ros/meta-ros-common layers/meta-ros/meta-ros2 layers/meta-ros/meta-ros2-jazzy

# regenerate the 5 packages with the fixed superflore against layers/meta-ros,
# remove their now-redundant .bbappend files (see docs/specs/measurements/
# m5-real-regeneration/ for the equivalent --dry-run command), then:
bitbake ros-core
```
