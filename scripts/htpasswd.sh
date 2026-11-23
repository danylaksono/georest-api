#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 USERNAME" >&2
    exit 2
fi
exec htpasswd -nB "$1"
