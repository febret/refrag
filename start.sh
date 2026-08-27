#!/bin/sh
# Launch the Refrag server.
cd "$(dirname "$0")"
exec python -m server.app
