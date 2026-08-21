SUMMARY = "Repro: libB, the target-space thing libA build_export_depends on"
LICENSE = "CLOSED"
inherit allarch

do_install() {
    install -d ${D}${includedir}
    echo "LIBB_MARKER" > ${D}${includedir}/libb-marker.h
}

FILES:${PN} += "${includedir}/libb-marker.h"
