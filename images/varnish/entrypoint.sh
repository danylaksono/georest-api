#!/bin/sh
set -eu

config=/etc/varnish/georest.vcl
diagnostics=$(mktemp)
trap 'rm -f "$diagnostics"' EXIT
if ! varnishd -C -f "$config" >"$diagnostics" 2>&1; then
    cat "$diagnostics" >&2
    exit 1
fi
rm -f "$diagnostics"

exec varnishd -F -a :80 -T none -f "$config" -s "malloc,${VARNISH_SIZE:-1G}"
