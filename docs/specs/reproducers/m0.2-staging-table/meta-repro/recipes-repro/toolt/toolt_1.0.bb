SUMMARY = "Repro: toolT, a buildtool that buildtool_export_depends on toolU"
LICENSE = "CLOSED"
inherit allarch

# Mirrors yocto_recipe.py's current strategy for ROS_BUILDTOOL_EXPORT_DEPENDS:
# the export is added directly to the declaring recipe's own DEPENDS, native.
DEPENDS = "toolu-native"

do_install() {
    install -d ${D}${bindir}
    echo "TOOLT_MARKER" > ${D}${bindir}/toolt-marker
}

FILES:${PN} += "${bindir}/toolt-marker"
BBCLASSEXTEND = "native"
