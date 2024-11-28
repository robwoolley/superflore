#!/bin/bash
PROJECT_DIR=$PWD

SUPERFLORE_GIT="https://github.com/ros-infrastructure/superflore.git"
SUPERFLORE_DIR=superflore
git clone ${SUPERFLORE_GIT} ${SUPERFLORE_DIR}

cd ${SUPERFLORE_DIR}

python3 -m venv venv
source venv/bin/activate
python3 ./setup.py install

export ROSDEP_SOURCE_PATH=${PROJECT_DIR}/rosdep
mkdir ${ROSDEP_SOURCE_PATH}

rosdep init
rosdep update

cd ${PROJECT_DIR}
ROSDISTRO_GIT="https://github.com/ros/rosdistro"
git clone ${ROSDISTRO_GIT}

ROSDISTRO_URL="https://raw.githubusercontent.com/ros/rosdistro/master/rosdep"
sed -i -e "s|${ROSDISTRO_URL}|file://${PROJECT_DIR}/rosdistro/rosdep|" ${ROSDEP_SOURCE_PATH}/20-default.list

cd ${PROJECT_DIR}

