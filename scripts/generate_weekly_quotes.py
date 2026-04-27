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

EN_GENERATION_PROMPT = """You write push notifications for "Memento" — a death countdown app that shows users exactly how much time they have left to live. Users opted IN to be confronted with mortality. This is not a wellness app.

GENERATE {notif_count} notification quotes (English only).

VOICE & TONE (study these real examples from the app):
- Confrontational: "STILL ALIVE?", "NOT DEAD YET.", "Ready to die today?", "Will you scroll your life away?"
- Dark wit: "Your inbox will outlive you.", "Social media won't attend your funeral.", "Your password will become a permanent secret."
- Visceral: "Your cells are dying right now.", "Entropy always wins.", "Your scent will fade from your clothes."
- Pointed questions: "How many times do you think you have left?", "Do you remember this day last year?", "When did you last really look at the moon?"
- Direct commands: "Put the phone down.", "Make the call you've been avoiding.", "Write that letter."

RULES:
- Under 100 characters each. Shorter is better.
- 1/3 confrontational (in-your-face, ALL CAPS ok), 1/3 dark/poetic observations, 1/3 pointed questions or commands
- NO religious scripture, NO Buddhist terms, NO generic self-help ("cherish your time", "live your best life")
- NO generic motivational poster language. If it could appear on a yoga studio wall, don't write it.
- Each must be a complete grammatical thought
- Must feel like it belongs alongside "Your shopping cart won't follow you to the grave" — not alongside "Believe in yourself"

ALSO GENERATE {main_count} main quotes with authors.

MAIN QUOTE RULES:
- 1-3 sentences, weighty and memorable
- For real historical figures: use their EXACT published English text (verifiable in Wikiquote/Gutenberg)
- Author field required. Use "Anonymous" only for truly original quotes.
- Prefer: Stoics (Seneca, Marcus Aurelius, Epictetus), existentialists (Camus, Heidegger), writers (Nabokov, Woolf, Borges, Montaigne), scientists (Feynman, Sagan)
- NO Buddhist scripture. NO quotes you're unsure about — if you can't cite the exact source, write an original instead.

THESE QUOTES ALREADY EXIST — do NOT duplicate or rephrase them:
{existing_quotes}

Return ONLY valid JSON (no markdown, no commentary):
{{
  "notification": ["quote1", ...{notif_count} total],
  "main": [{{"text": "Exact quote text.", "author": "Author Name"}}, ...{main_count} total]
}}"""

TRANSLATION_PROMPT = """Translate these English quotes for a death countdown app into {lang_count} languages.

SOURCE (English):
notification: {notif_json}
main: {main_json}

TARGET LANGUAGES: {lang_list}

TRANSLATION RULES:
- Notification quotes must stay under 100 characters in each language
- Preserve the TONE: confrontational, dark, visceral. Do NOT soften or sanitize.
- ALL CAPS quotes should use the equivalent emphasis in each language (ALL CAPS where applicable)
- For quotes by well-known authors (Seneca, Marcus Aurelius, etc.), use the canonical published translation in that language if one exists
- Author names: use the standard form in each language (e.g., 塞涅卡 in zh, セネカ in ja)
- "Anonymous" → translate to each language's equivalent (佚名, 匿名, Anonim, etc.)
- Quality: must read as native-speaker writing, not machine translation

Return ONLY valid JSON (no markdown):
{{
  "zh": {{
    "notification": ["中文1", ...{notif_count}],
    "main": [{{"text": "...", "author": "..."}}, ...{main_count}]
  }},
  ...all {lang_count} languages
}}"""


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


def chat(client: OpenAI, prompt: str, max_tokens: int = 4000, temperature: float = 0.7) -> str:
    """Send a chat completion request and return the text response."""
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def generate_en_quotes(client: OpenAI, existing: set) -> dict:
    """Step 1: Generate EN quotes only."""
    prompt = EN_GENERATION_PROMPT.format(
        notif_count=NOTIFICATION_COUNT,
        main_count=MAIN_COUNT,
        existing_quotes=json.dumps(sorted(list(existing)), ensure_ascii=False),
    )
    text = chat(client, prompt, max_tokens=4000, temperature=0.7)
    data = json.loads(strip_markdown_fences(text))

    # Post-generation dedup: remove any that snuck through
    clean_notifs = []
    for q in data["notification"]:
        if q.lower().strip() not in existing:
            clean_notifs.append(q)
        else:
            print(f"  DEDUP: removed duplicate notification: {q}")
    data["notification"] = clean_notifs

    clean_main = []
    for entry in data["main"]:
        if entry["text"].lower().strip() not in existing:
            clean_main.append(entry)
        else:
            print(f"  DEDUP: removed duplicate main: {entry['text'][:50]}")
    data["main"] = clean_main

    return data


def batch_translate(client: OpenAI, en_pack: dict, languages: list[str]) -> dict[str, dict]:
    """Step 2: Batch-translate EN→all target languages in one call."""
    prompt = TRANSLATION_PROMPT.format(
        lang_count=len(languages),
        notif_json=json.dumps(en_pack["notification"], ensure_ascii=False),
        main_json=json.dumps(en_pack["main"], ensure_ascii=False),
        lang_list=", ".join(languages),
        notif_count=len(en_pack["notification"]),
        main_count=len(en_pack["main"]),
    )
    text = chat(client, prompt, max_tokens=16000, temperature=0.3)
    return json.loads(strip_markdown_fences(text))


def validate_lang_pack(lang: str, pack: dict, expected_notif: int, expected_main: int) -> bool:
    """Validate a single language pack."""
    notifs = pack.get("notification", [])
    mains = pack.get("main", [])

    if len(notifs) != expected_notif:
        print(f"ERROR: {lang} has {len(notifs)} notification quotes, expected {expected_notif}")
        return False
    if len(mains) != expected_main:
        print(f"ERROR: {lang} has {len(mains)} main quotes, expected {expected_main}")
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
    actual_notif = len(en_pack["notification"])
    actual_main = len(en_pack["main"])
    if actual_notif == 0 or actual_main == 0:
        print(f"ERROR: After dedup, only {actual_notif} notification + {actual_main} main remain")
        sys.exit(1)
    print(f"  {actual_notif} notification + {actual_main} main quotes (after dedup)")

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
        if not validate_lang_pack(lang, translations[lang], actual_notif, actual_main):
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
        "notification_count": actual_notif,
        "main_count": actual_main,
    })
    save_manifest(manifest)
    print(f"Updated manifest with {week_id}")
    print("Done!")


if __name__ == "__main__":
    main()
