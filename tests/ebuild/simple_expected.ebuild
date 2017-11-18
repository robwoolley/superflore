# Copyright 2017 Open Source Robotics Foundation
# Distributed under the terms of the BSD license

EAPI=6
PYTHON_COMPAT=( python{2_7,3_5} )

inherit ros-cmake

DESCRIPTION="an ebuild"
HOMEPAGE="https://www.website.com"
SRC_URI="https://www.website.com/download/stuff.tar.gz -> ${PN}-lunar-release-${PV}.tar.gz"

LICENSE="LGPL-2"

KEYWORDS=""
RDEPEND="
	ros-lunar/p2os_driver
"
DEPEND="${RDEPEND}
"

SLOT="0"
ROS_DISTRO="lunar"
ROS_PREFIX="opt/ros/${ROS_DISTRO}"