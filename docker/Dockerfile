# superflore-devel
# Copyright (C) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: MIT
#

FROM osrf/ros2:devel

ENV ROS_HOME "/usr/share/ros"
ENV ROS_DISTRO "rolling"
ENV ROSDISTRO_URL "https://raw.githubusercontent.com/ros/rosdistro/master/rosdep"
ENV GIT_FULLNAME "Firstname Lastname"
ENV GIT_EMAIL "firstname.lastname@example.com"

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        apt-utils \
        curl \
        locales \
        python3 \
        python3-pip \
        python3.10-venv \
        python3-virtualenv \
        vim \
        wget && \
    apt-get clean && \
    locale-gen en_US en_US.UTF-8 && \
    update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 && \
    useradd -U -m rosuser && \
    usermod -aG sudo rosuser && \
    echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

#    DEBIAN_FRONTEND=noninteractive apt-get -y install software-properties-common && \
#    add-apt-repository universe && \
#    curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros2-latest-archive-keyring.gpg && \
#    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros2-latest-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | tee /etc/apt/sources.list.d/ros2.list > /dev/null && \

COPY setup_superflore.sh /usr/local/bin
RUN chmod +x /usr/local/bin/setup_superflore.sh

RUN mkdir -p ${ROS_HOME} && \
    chmod 0755 ${ROS_HOME} && \
    chown rosuser ${ROS_HOME}

USER rosuser
WORKDIR /home/rosuser

RUN git config --global user.email "${GIT_EMAIL}" && \
    git config --global user.name "${GIT_FULLNAME}"

CMD /bin/bash
