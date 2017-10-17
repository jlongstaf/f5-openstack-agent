#! /usr/bin/env bash
export TAGINFO=`git describe --long --tags --first-parent`
export TIMESTAMP=`date +"%Y%m%d-%H%M%S"`
# This is approximately the same as GUMBALLS_SESSION
export SESSIONLOGDIR=${TAGINFO}_$TIMESTAMP

export TRTLRESULTSDIR=`pwd`/systest/test_results/f5-openstack-agent_ocata-unit
mkdir -p ${TRTLRESULTSDIR}
sudo -E docker pull docker-registry.pdbld.f5net.com/openstack-test-agentunitrunner-prod/ocata

sudo -E docker run \
                -u jenkins \
                -v ${TRTLRESULTSDIR}:${TRTLRESULTSDIR} \
                -v `pwd`:`pwd` \
                -w `pwd` \
docker-registry.pdbld.f5net.com\
/openstack-test-agentunitrunner-prod/ocata:latest \
${TRTLRESULTSDIR} $SESSIONLOGDIR

sudo -E chown -Rf jenkins:jenkins .
if [ "${RUN_UNIT_STAGE}" != "true" ]; then
    if [ -n "${JOB_BASE_NAME##*smoke*}" ]; then
        mkdir -p ${COVERAGERESULTS}
        mv .coverage ${COVERAGERESULTS}/.coverage_unit
    fi
fi
