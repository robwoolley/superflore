# Mirrors meta-ros-common/classes/ros_superflore_generated.bbclass exactly:
# a recipe only gets extended to native/nativesdk if the generator listed
# "<BPN>-native" in a distro-wide "what's a buildtool" variable.
BBCLASSEXTEND:append = "${@bb.utils.contains('GENERATED_BUILDTOOLS', '${BPN}-native', ' native nativesdk', '', d)}"
