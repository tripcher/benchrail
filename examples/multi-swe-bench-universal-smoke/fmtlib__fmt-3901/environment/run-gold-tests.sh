#!/bin/sh
set -eu

mkdir -p build/benchrail-gold
${CXX:-c++} -std=c++11 -DFMT_HEADER_ONLY -Iinclude test/benchrail_gold_group_digits_test.cc -o build/benchrail-gold/group-digits-test
./build/benchrail-gold/group-digits-test
