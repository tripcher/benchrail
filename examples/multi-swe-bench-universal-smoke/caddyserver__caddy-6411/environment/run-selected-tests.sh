#!/bin/sh
set -eu

go test . -run '^(TestReplacerNew|TestReplacerNewWithoutFile)$'
