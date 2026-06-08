# Deploy Dashboard
1. Regenerate data files (including regime.json, not just source)
2. Verify data block in index.html is updated
3. Check .gitignore is not blocking generated HTML
4. Commit, push to correct branch (confirm main vs staging)
5. Curl the Vercel URL and grep for the new value to confirm render
