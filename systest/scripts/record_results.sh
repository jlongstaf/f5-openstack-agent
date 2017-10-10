#!/usr/bin/env bash

set -ex

# - copy results files to nfs (note that the nfs results directory is mounted
#    inside the CI worker's home directory)
echo INSIDE RECORD RESULTS!!
echo CI_RESULTS_DIR is: ${CI_RESULTS_DIR}
mkdir -p $CI_RESULTS_DIR/
cp -r $WORKSPACE/systest/test_results/* $CI_RESULTS_DIR/
mkdir -p ${COVERAGERESULTS}
mv .coverage* ${COVERAGERESULTS}
