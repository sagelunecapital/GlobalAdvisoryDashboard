# Verify Dashboard

After making a fix, run all three checks before declaring done:

1. Regenerate any cached JSON the dashboard reads (regime.json, sector_rotation.json, ticker_perf.json, etc.) — not just the source file
2. Grep the deployed HTML for the new value to confirm it appears in the output artifact
3. Curl the live Vercel URL and confirm the value appears in the response body

Do NOT say the fix is done until all three pass.
