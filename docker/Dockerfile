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
