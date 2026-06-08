#!/bin/sh
set -eu

./build/bin/format-test --gtest_filter='format_test.group_digits_view:uint128_test.*'
