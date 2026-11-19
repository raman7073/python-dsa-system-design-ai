#!/bin/sh
set -e

# Addresses in .env say "localhost" (Postgres on this computer, a local S3
# server), but inside a container localhost is the container itself. Point
# them at the host instead, so the same .env works on the host and here.
to_host() {
    printf '%s' "$1" | sed -E 's#(@|//)(localhost|127\.0\.0\.1)([:/]|$)#\1host.docker.internal\3#'
}
DB_URL=$(to_host "$DB_URL")
export DB_URL
if [ -n "$S3_ENDPOINT_URL" ]; then
    S3_ENDPOINT_URL=$(to_host "$S3_ENDPOINT_URL")
    export S3_ENDPOINT_URL
fi

exec "$@"
