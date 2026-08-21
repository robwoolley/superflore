SUMMARY = "Repro: libA, build_export_depends libB and buildtool_depends toolT"
LICENSE = "CLOSED"
inherit allarch

# Mirrors a real superflore-generated recipe:
#   ROS_BUILD_DEPENDS = "libb"              (direct <build_depend>)
#   ROS_BUILDTOOL_DEPENDS = "toolt-native"  (direct <buildtool_depend>, -native)
#   DEPENDS = "${ROS_BUILD_DEPENDS} ${ROS_BUILDTOOL_DEPENDS}"
DEPENDS = "libb toolt-native"

do_install() {
    install -d ${D}${includedir}
    echo "LIBA_MARKER" > ${D}${includedir}/liba-marker.h
}

FILES:${PN} += "${includedir}/liba-marker.h"
