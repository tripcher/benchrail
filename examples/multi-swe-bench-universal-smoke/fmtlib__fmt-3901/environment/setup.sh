#!/bin/sh
set -eu

cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DFMT_TEST=ON
cmake --build build --target format-test -j2
