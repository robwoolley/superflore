SUMMARY = "Repro: toolT, buildtool_export_depends on toolU (native)"
LICENSE = "CLOSED"
inherit allarch
DEPENDS = "toolu-native"
BBCLASSEXTEND = "native"

do_install() {
    install -d ${D}${bindir}
    echo "TOOLT_MARKER" > ${D}${bindir}/toolt-marker
}

FILES:${PN} += "${bindir}/toolt-marker"
