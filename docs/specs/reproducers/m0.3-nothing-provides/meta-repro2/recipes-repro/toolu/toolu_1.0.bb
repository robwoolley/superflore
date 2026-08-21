SUMMARY = "Repro: toolU, native-extended only if listed in GENERATED_BUILDTOOLS"
LICENSE = "CLOSED"
inherit allarch
inherit repro_native_gate

do_install() {
    install -d ${D}${bindir}
    echo "TOOLU_MARKER" > ${D}${bindir}/toolu-marker
}

FILES:${PN} += "${bindir}/toolu-marker"
