#!/bin/sh
set -eu

cargo test -p tokio --test benchrail_gold_fs_file --features full
