#!/usr/bin/env bash
# Offline launcher, worker, UI, and real Diffview checks. No provider or GitHub calls.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../../.."
export TMPDIR="$PWD/.pi/review-test-tmp"
mkdir -p "$TMPDIR"
fish -n fish/.config/fish/functions/review.fish
python3 fish/.config/fish/tests/review_cli.py
node pi/.pi/agent/extensions/review-service/test.mjs
for suite in agent threads anchor workflow guide chunks integration; do
  nvim --headless -u NONE -i NONE -l "nvim/.config/nvim/tests/diffview_review_${suite}.lua"
done
git diff --check
