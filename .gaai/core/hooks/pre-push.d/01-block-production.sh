#!/usr/bin/env bash
# ── GAAI Pre-Push Guard ───────────────────────────────────────────────
# Blocks all pushes to protected branches.
# AI agents must work exclusively on staging. Promotion to protected
# branches is a human action via GitHub PR.
#
# PROJECT DIVERGENCE (Lance, 2026-07-03): 'main' removed from the
# protected list for this repo. The dashboard deploys from main
# (Vercel) and the daily data pipeline + screener enrichment push to
# main by design. Only 'production' remains protected.
# ─────────────────────────────────────────────────────────────────────

PROTECTED_BRANCHES="production"

while read local_ref local_sha remote_ref remote_sha; do
  branch="${remote_ref#refs/heads/}"
  if [[ "$branch" =~ ^($PROTECTED_BRANCHES)$ ]]; then
    echo ""
    echo "BLOCKED: Push to '$branch' is not allowed from this environment."
    echo "Use GitHub PR to promote staging → $branch."
    echo ""
    exit 1
  fi
done

exit 0
