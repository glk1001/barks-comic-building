#!/bin/bash

set -u

# shellcheck disable=SC2155
# shellcheck disable=SC2164
declare -r THIS_SCRIPT_PATH="$(cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P)"

DIRECTORY1=$1
DIRECTORY2=$2
COMPARE_FUZZ="0%"

if [[ ! -d "${DIRECTORY1}" ]]; then
  echo "Error: Could not find build directory1: \"${DIRECTORY1}\"."
  exit 1
fi
if [[ ! -d "${DIRECTORY2}" ]]; then
  echo "Error: Could not find build directory2: \"${DIRECTORY2}\"."
  exit 1
fi

ERRORS=0

diff -r --exclude=images -I "ini file"   -I "time of run" -I "time taken" -I "Created:" -I "timestamp" "${DIRECTORY1}" "${DIRECTORY2}"
if [[ $? != 0 ]]; then
  echo "Error in files diff in  \"${DIRECTORY1}\"."
  ERRORS=1
fi

bash "${THIS_SCRIPT_PATH}"/compare-images.sh "${DIRECTORY1}/images" "${DIRECTORY2}/images" "${COMPARE_FUZZ}"
if [[ $? != 0 ]]; then
  echo "There were image compare errors in \"${DIRECTORY1}/images\"."
  ERRORS=$((ERRORS+1))
fi

exit ${ERRORS}
