#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
fail() { printf '\n%s\n' "$1"; if [ -t 0 ]; then read -r -p 'Press Return to close.' _reply; fi; exit 1; }
trap 'fail "Setup stopped. Read the error above; your settings were preserved."' ERR
[ "$(uname -s)" = Darwin ] || fail 'STARK requires macOS.'
xcrun --find clang >/dev/null 2>&1 || fail 'Install Apple Command Line Tools: run xcode-select --install in Terminal, then rerun this installer.'
if [ ! -x .venv/bin/python ]; then
  PY=''
  for candidate in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert (3,9) <= sys.version_info[:2] <= (3,13)' 2>/dev/null; then
      PY="$(command -v "$candidate")"; break
    fi
  done
  [ -n "$PY" ] || fail 'Install Python 3.12 from python.org, then run this installer again.'
  "$PY" -m venv .venv
fi
printf '\nSetting up STARK. The first installation takes a few minutes.\n'
.venv/bin/python -m pip install --upgrade pip --no-compile
.venv/bin/python -m pip install --no-compile -r requirements.txt
.venv/bin/python -m pip check
for test_file in tests/test_*.py; do .venv/bin/python "$test_file"; done
.venv/bin/python build_macos_app.py --output "$HOME/Desktop/STARK.app"
printf '\nSTARK is ready on your Desktop. Keep this source folder in place.\nDrag STARK.app into your Dock.\n'
open "$HOME/Desktop/STARK.app"
