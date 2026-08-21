SUMMARY = "Repro: consumer C, build_depends only on libA (mirrors example_interfaces)"
LICENSE = "CLOSED"
inherit allarch

# C only knows about libA -- exactly like example_interfaces (spec Sec. 2.4)
# only lists ament_cmake/rosidl_default_generators, never the packages THEY
# buildtool_export/build_export. C never mentions toolT, toolU or libB.
DEPENDS = "liba"

do_install() {
    install -d ${D}${includedir}
    echo "C_MARKER" > ${D}${includedir}/c-marker.h
}

FILES:${PN} += "${includedir}/c-marker.h"
