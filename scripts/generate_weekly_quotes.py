#!/usr/bin/env python3
"""Generate weekly memento mori quotes using OpenAI GPT-4o.

Token-efficient: generates EN first, then batch-translates to 25 languages.
Outputs per-language files: weeks/week-YYYY-WNN/en.json, zh.json, etc.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "quotes" / "manifest.json"
WEEKS_DIR = REPO_ROOT / "quotes" / "weeks"
SNAPSHOT_PATH = REPO_ROOT / "scripts" / "existing_quotes_snapshot.json"

LANGUAGES = [
    "ar", "cs", "de", "el", "en", "es", "fi", "fr", "hi", "id",
    "it", "ja", "ko", "ms", "nl", "pl", "pt", "ro", "ru", "sv",
    "th", "tr", "uk", "vi", "zh", "zh-Hant"
]

TARGET_LANGUAGES = [l for l in LANGUAGES if l != "en"]

NOTIFICATION_COUNT = 35
MAIN_COUNT = 7


def get_current_week_id() -> str:
    """Return ISO week ID like '2026-W18'."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def load_manifest() -> dict:
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def save_manifest(manifest: dict):
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_existing_en_quotes() -> set:
    """Load existing bundled English quotes for dedup."""
    existing = set()
    if SNAPSHOT_PATH.exists():
        with open(SNAPSHOT_PATH) as f:
            data = json.load(f)
        for q in data.get("notification_en", []):
            existing.add(q.lower().strip())
        for q in data.get("main_en", []):
            existing.add(q.lower().strip())
    # Also check previously generated weeks
    for week_dir in WEEKS_DIR.glob("week-*/"):
        en_file = week_dir / "en.json"
        if en_file.exists():
            with open(en_file) as f:
                pack = json.load(f)
            for text in pack.get("notification", []):
                existing.add(text.lower().strip())
            for entry in pack.get("main", []):
                existing.add(entry.get("text", "").lower().strip())
    return existing


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


def chat(client: OpenAI, prompt: str, max_tokens: int = 4000) -> str:
    """Send a chat completion request and return the text response."""
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=max_tokens,
        temperature=0.9,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def generate_en_quotes(client: OpenAI, existing: set) -> dict:
    """Step 1: Generate EN quotes only."""
    prompt = f"""Generate quotes for a memento mori / death countdown app. English only.

PART A: {NOTIFICATION_COUNT} short notification quotes
- Under 100 characters each
- Themes: mortality awareness, time passing, living fully, impermanence, carpe diem
- Tone: contemplative, thought-provoking, sometimes poetic — NOT depressing
- Mix: original aphorisms, reworded classical wisdom, modern reflections
- NO religious scripture or Buddhist terminology
- Each must be grammatically complete

PART B: {MAIN_COUNT} main quotes with authors
- 1-3 sentences each, meaningful and profound
- Include author name ("Anonymous" for originals)
- Themes: mortality, time, meaning of life, legacy, living authentically
- Mix: real historical figures (EXACT canonical text) and originals
- NO Buddhist scripture

Do NOT duplicate any of these existing quotes:
{json.dumps(sorted(list(existing))[:50], ensure_ascii=False)}
(first 50 of {len(existing)} existing)

Return ONLY valid JSON (no markdown):
{{
  "notification": ["quote1", ...{NOTIFICATION_COUNT} total],
  "main": [{{"text": "Quote text", "author": "Author"}}, ...{MAIN_COUNT} total]
}}"""

    text = chat(client, prompt, max_tokens=4000)
    return json.loads(strip_markdown_fences(text))


def batch_translate(client: OpenAI, en_pack: dict, languages: list[str]) -> dict[str, dict]:
    """Step 2: Batch-translate EN→all target languages in one call."""
    prompt = f"""Translate these English quotes into {len(languages)} languages.

SOURCE (English):
notification: {json.dumps(en_pack["notification"], ensure_ascii=False)}
main: {json.dumps(en_pack["main"], ensure_ascii=False)}

TARGET LANGUAGES: {', '.join(languages)}

Rules:
- Notification quotes must stay under 100 characters in each language
- For quotes from well-known authors, use the canonical published translation if one exists
- Author names: use the standard form in each language (e.g., 马可·奥勒留 in zh)
- "Anonymous" → translate to each language's equivalent
- Quality: natural, native-speaker level — no literal word-for-word translation

Return ONLY valid JSON (no markdown). One key per language:
{{
  "zh": {{
    "notification": ["中文1", ...{NOTIFICATION_COUNT}],
    "main": [{{"text": "...", "author": "..."}}, ...{MAIN_COUNT}]
  }},
  "ja": {{
    "notification": ["日本語1", ...],
    "main": [...]
  }},
  ...all {len(languages)} languages
}}"""

    text = chat(client, prompt, max_tokens=16000)
    return json.loads(strip_markdown_fences(text))


def validate_lang_pack(lang: str, pack: dict) -> bool:
    """Validate a single language pack."""
    notifs = pack.get("notification", [])
    mains = pack.get("main", [])

    if len(notifs) != NOTIFICATION_COUNT:
        print(f"ERROR: {lang} has {len(notifs)} notification quotes, expected {NOTIFICATION_COUNT}")
        return False
    if len(mains) != MAIN_COUNT:
        print(f"ERROR: {lang} has {len(mains)} main quotes, expected {MAIN_COUNT}")
        return False

    for i, q in enumerate(notifs):
        if not q or not q.strip():
            print(f"ERROR: {lang} notification[{i}] is empty")
            return False
        if len(q) > 150:
            print(f"WARNING: {lang} notification[{i}] is {len(q)} chars: {q[:50]}...")

    for i, entry in enumerate(mains):
        if not isinstance(entry, dict) or "text" not in entry:
            print(f"ERROR: {lang} main[{i}] invalid structure")
            return False
        if not entry["text"] or not entry["text"].strip():
            print(f"ERROR: {lang} main[{i}] has empty text")
            return False

    return True


def write_lang_pack(week_dir: Path, lang: str, pack: dict):
    """Write a per-language JSON file."""
    with open(week_dir / f"{lang}.json", "w") as f:
        json.dump(pack, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    week_id = get_current_week_id()

    # Check if this week already exists
    manifest = load_manifest()
    existing_week_ids = {w["id"] for w in manifest["weeks"]}
    if week_id in existing_week_ids:
        print(f"Week {week_id} already exists in manifest, skipping")
        return

    print(f"Generating quotes for {week_id}...")
    existing = load_existing_en_quotes()
    print(f"Loaded {len(existing)} existing EN quotes for dedup")

    # Step 1: Generate EN quotes
    print("Step 1: Generating English quotes...")
    en_pack = generate_en_quotes(client, existing)
    if not validate_lang_pack("en", en_pack):
        sys.exit(1)
    print(f"  {NOTIFICATION_COUNT} notification + {MAIN_COUNT} main quotes generated")

    # Step 2: Batch translate to all other languages
    print(f"Step 2: Translating to {len(TARGET_LANGUAGES)} languages...")
    translations = batch_translate(client, en_pack, TARGET_LANGUAGES)

    # Validate all translations
    all_valid = True
    for lang in TARGET_LANGUAGES:
        if lang not in translations:
            print(f"ERROR: Missing language '{lang}' in translations")
            all_valid = False
            continue
        if not validate_lang_pack(lang, translations[lang]):
            all_valid = False

    if not all_valid:
        sys.exit(1)
    print(f"  All {len(TARGET_LANGUAGES)} translations validated")

    # Write per-language files
    week_dir = WEEKS_DIR / f"week-{week_id}"
    week_dir.mkdir(parents=True, exist_ok=True)

    write_lang_pack(week_dir, "en", en_pack)
    for lang in TARGET_LANGUAGES:
        write_lang_pack(week_dir, lang, translations[lang])
    print(f"Wrote {len(LANGUAGES)} language files to {week_dir}")

    # Update manifest
    manifest["latest_week"] = week_id
    manifest["weeks"].append({
        "id": week_id,
        "url": f"weeks/week-{week_id}",
        "notification_count": NOTIFICATION_COUNT,
        "main_count": MAIN_COUNT,
    })
    save_manifest(manifest)
    print(f"Updated manifest with {week_id}")
    print("Done!")


if __name__ == "__main__":
    main()
