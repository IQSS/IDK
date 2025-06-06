#!/bin/sh
PYVER=$(grep '^python ' .tool-versions | awk '{print $2}')
docker build \
  --build-arg PYTHON_VERSION=$PYVER \
  -t idk:latest .