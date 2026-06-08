#!/bin/sh
set -eu

cargo test -p tokio --test fs_file --features full
