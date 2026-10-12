#!/usr/bin/env bash
# Offline launcher, parser, and real Diffview checks. No live GitHub or Pi calls.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../../.."
export TMPDIR="$PWD/.pi/review-test-tmp"
mkdir -p "$TMPDIR"
fish -n fish/.config/fish/functions/review.fish
python3 fish/.config/fish/tests/review_cli.py
for suite in agent anchor workflow guide skim integration; do
  nvim --headless -u NONE -i NONE -l "nvim/.config/nvim/tests/diffview_review_${suite}.lua"
done
git diff --check
