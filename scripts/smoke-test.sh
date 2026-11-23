#!/bin/sh
set -eu
exec "${PYTHON:-python3}" "$(dirname "$0")/smoke_test.py" \
    --level "${1:-1}" --url "${2:-${PUBLIC_URL:-http://localhost}}"
