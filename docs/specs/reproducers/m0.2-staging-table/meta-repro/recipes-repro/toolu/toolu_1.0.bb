SUMMARY = "Repro: toolU, the native tool that toolT buildtool_export_depends on"
LICENSE = "CLOSED"
inherit allarch

do_install() {
    install -d ${D}${bindir}
    echo "TOOLU_MARKER" > ${D}${bindir}/toolu-marker
}

FILES:${PN} += "${bindir}/toolu-marker"
BBCLASSEXTEND = "native"
