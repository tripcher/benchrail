#!/bin/bash

set -euo pipefail

/opt/benchrail/setup_universal.sh
/opt/benchrail/setup_agents.sh

if [ "$#" -eq 0 ]; then
    exec bash --login
fi

if [[ "$1" == -* ]]; then
    exec bash --login "$@"
fi

exec "$@"
