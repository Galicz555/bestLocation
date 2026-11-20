#!/bin/sh
# The pre-commit gate: everything that can run without network access or rewriting data/out.
#
#   sh tools/check.sh            scoring tests, Python compile check, and the capture smoke test
#                                when the server answers on :8731 (start it with tools/serve.py)
#
# Simplification: a local script, not a CI service. As a workflow it is this file's three steps;
# on a fresh checkout the capture step runs against the committed sample in data/sample/.
set -e
cd "$(dirname "$0")/.."

echo "=== scoring math and summaries"
node tools/test_score.mjs

echo "=== python compiles"
./.venv/bin/python -m py_compile tools/*.py

URL=http://127.0.0.1:8731/app/index.html
if curl -s -o /dev/null --max-time 3 "$URL"; then
  echo "=== capture smoke test"
  PLAYWRIGHT_BROWSERS_PATH=./.pw-browsers node tools/capture.mjs "$URL" "${TMPDIR:-/tmp}/check_capture.png" 1680x1000
else
  # loud on purpose: a skipped app check must not read as a passed one
  echo "!!! capture SKIPPED: no server on :8731 — app.js is untested by this run" >&2
fi
echo "=== check OK"
