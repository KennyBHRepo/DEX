#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  printf 'Run Install STARK.command first.\n'
  exit 1
fi
if [ "${1:-}" = --here ]; then shift; fi
exec .venv/bin/python handcontrol.py "$@"
