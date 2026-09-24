#!/bin/sh
set -u
reward=0
finish() {
  mkdir -p /logs/verifier 2>/dev/null || true
  printf '%s' "$reward" > /logs/verifier/reward.txt 2>/dev/null || true
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
mkdir -p /logs/verifier

python -m pytest -q /tests/test_layout.py --ctrf=/logs/verifier/ctrf.json
status=$?
if [ "$status" -eq 0 ]; then
  reward=1
fi
exit 0
