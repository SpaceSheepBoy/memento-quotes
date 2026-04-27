# Memento Quotes

Weekly auto-generated quote packs for the Memento iOS app. New quotes are generated every Sunday at 00:00 UTC via GitHub Actions and served as static JSON via GitHub Pages.

## Structure

- `quotes/manifest.json` — index of all available week packs
- `quotes/weeks/week-YYYY-WNN.json` — weekly quote pack (35 notification + 7 main quotes × 26 languages)
- `scripts/generate_weekly_quotes.py` — generation script using Claude API
- `scripts/existing_quotes_snapshot.json` — bundled quotes for dedup

## Manual trigger

Go to Actions → "Generate Weekly Quotes" → Run workflow.

## Adding the ANTHROPIC_API_KEY secret

1. Go to repo Settings → Secrets and variables → Actions
2. Add `ANTHROPIC_API_KEY` with your Anthropic API key
