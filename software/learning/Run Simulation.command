#!/bin/zsh
set -eu
ROOT="${0:A:h}"
cd "$ROOT/project"
export MUJOCO_GL=cgl
export PYTHONDONTWRITEBYTECODE=1
if [[ ! -x "$ROOT/runtime/.venv/bin/python" ]]; then
  print "The copied Python runtime is missing. See START HERE.md."
  exit 1
fi
exec "$ROOT/runtime/.venv/bin/python" software/learning/offline_server.py
