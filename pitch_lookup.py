"""
Pitch accent lookup module for the Fill Pitch Numbers Anki add-on.

Loads the Kanjium pitch accent dataset and provides lookup by
(expression, reading) or reading alone. Auto-downloads the dataset
from GitHub on first run if the file is not present.
"""

import os
import urllib.request
import urllib.error
from typing import Optional, Dict, Tuple

DATASET_URL = (
    "https://raw.githubusercontent.com/mifunetoshiro/kanjium"
    "/master/data/source_files/raw/accents.txt"
)
DATASET_FILENAME = "accents.txt"

WIKTIONARY_URL = (
    "https://raw.githubusercontent.com/jkindrix/japanese-language-data"
    "/main/data/enrichment/pitch-accent-wiktionary.json"
)
WIKTIONARY_FILENAME = "pitch_accent_wiktionary.json"

# Small kana that combine with the preceding character to form one mora.
# These are NOT counted as separate moras.
_SMALL_KANA = frozenset(
    "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ"
)

# Characters that ARE kana (hiragana + katakana + prolonged sound mark).
# ん, っ, ー all count as independent moras.
def _is_kana(ch: str) -> bool:
    cp = ord(ch)
    return (0x3041 <= cp <= 0x3096) or (0x30A1 <= cp <= 0x30FA) or ch == "ー"


def katakana_to_hiragana(text: str) -> str:
    """Convert full-width katakana to hiragana. Leaves everything else unchanged."""
    result = []
    for ch in text:
        cp = ord(ch)
        # Full-width katakana range: ァ (U+30A1) to ヶ (U+30F6)
        if 0x30A1 <= cp <= 0x30F6:
            result.append(chr(cp - 0x60))
        else:
            result.append(ch)
    return "".join(result)


def count_moras(reading: str) -> int:
    """
    Count the number of moras in a Japanese kana string.

    Rules:
      - Each kana character = 1 mora, EXCEPT small kana (ぁぃぅぇぉゃゅょ etc.)
        which attach to the preceding character and add 0 moras.
      - ん, っ, ー each count as 1 independent mora.
    """
    reading = katakana_to_hiragana(reading)
    count = 0
    for ch in reading:
        if _is_kana(ch) and ch not in _SMALL_KANA:
            count += 1
    return count


def _parse_pitch(raw: str) -> Optional[int]:
    """
    Parse the pitch accent field from the dataset.
    Handles single values ('2') and comma-separated multiple values ('1,3').
    Returns the first (most common) accent, or None if unparseable.
    """
    raw = raw.strip()
    if not raw:
        return None
    # Take the first value when multiple are listed
    first = raw.split(",")[0].strip()
    try:
        return int(first)
    except ValueError:
        return None


class PitchLookup:
    """
    Loads the Kanjium pitch accent dataset and answers lookup queries.

    Lookup priority:
      1. (expression, reading) exact match  — O(1)
      2. expression-only match              — O(1)
      3. reading-only match                 — O(1)
    """

    def __init__(self, addon_dir: str):
        self._addon_dir = addon_dir
        self._data_path = os.path.join(addon_dir, DATASET_FILENAME)

        # --- Kanjium tables ---
        # Keys: (expression_hiragana, reading_hiragana) -> pitch_int
        self._expr_table: Dict[Tuple[str, str], int] = {}
        # Keys: expression_hiragana -> pitch_int  (first match per expression wins)
        self._expr_only_table: Dict[str, int] = {}
        # Keys: reading_hiragana -> pitch_int  (first match wins)
        self._reading_table: Dict[str, int] = {}

        # --- Wiktionary supplement tables (fallback) ---
        self._wiki_expr_table:     Dict[Tuple[str, str], int] = {}
        self._wiki_expr_only_table: Dict[str, int] = {}
        self._wiki_reading_table:  Dict[str, int] = {}

        self._loaded = False
        self._load()
        self._load_wiktionary()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        return self._loaded

    def last_error(self) -> str:
        """Return the last download or load error message, or empty string if none."""
        return getattr(self, "_load_error", "") or getattr(self, "_download_error", "")

    def lookup(self, expression: str, reading: str) -> Optional[int]:
        """
        Return the pitch accent number for (expression, reading), or None if
        not found.  Falls back to reading-only lookup when expression misses.
        """
        if not self._loaded:
            return None

        expr_h = katakana_to_hiragana(_extract_expression(expression))
        read_h = katakana_to_hiragana(_extract_reading(reading))

        # 1. Expression + reading exact match — O(1)
        if expr_h and (expr_h, read_h) in self._expr_table:
            return self._expr_table[(expr_h, read_h)]

        # 2. Expression-only match — O(1)
        if expr_h and expr_h in self._expr_only_table:
            return self._expr_only_table[expr_h]

        # 3. Reading-only fallback — O(1)
        if read_h in self._reading_table:
            return self._reading_table[read_h]

        # 4–6. Wiktionary supplement fallback (same three-tier priority)
        if expr_h and (expr_h, read_h) in self._wiki_expr_table:
            return self._wiki_expr_table[(expr_h, read_h)]
        if expr_h and expr_h in self._wiki_expr_only_table:
            return self._wiki_expr_only_table[expr_h]
        if read_h in self._wiki_reading_table:
            return self._wiki_reading_table[read_h]

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self._data_path):
            self._download()
        if not os.path.exists(self._data_path):
            return

        try:
            with open(self._data_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    parts = line.split("\t")
                    if len(parts) < 3:
                        continue
                    expr_raw, read_raw, pitch_raw = parts[0], parts[1], parts[2]
                    pitch = _parse_pitch(pitch_raw)
                    if pitch is None:
                        continue

                    expr_h = katakana_to_hiragana(expr_raw)
                    read_h = katakana_to_hiragana(read_raw)

                    self._expr_table[(expr_h, read_h)] = pitch
                    if expr_h not in self._expr_only_table:
                        self._expr_only_table[expr_h] = pitch
                    if read_h not in self._reading_table:
                        self._reading_table[read_h] = pitch

            self._loaded = True
        except Exception as e:
            self._loaded = False
            self._load_error: str = str(e)

    def _download(self) -> None:
        """
        Download the Kanjium dataset from GitHub and save it locally.
        Stores the last error message in self._download_error for callers to inspect.
        """
        self._download_error: str = ""
        try:
            req = urllib.request.Request(
                DATASET_URL,
                headers={"User-Agent": "AnkiFillPitchNumbers/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            with open(self._data_path, "wb") as fh:
                fh.write(data)
        except urllib.error.HTTPError as e:
            self._download_error = f"HTTP {e.code}: {e.reason} — {DATASET_URL}"
        except urllib.error.URLError as e:
            self._download_error = f"Network error: {e.reason}"
        except OSError as e:
            self._download_error = f"File error: {e}"

    # ------------------------------------------------------------------
    # Wiktionary supplement
    # ------------------------------------------------------------------

    def _load_wiktionary(self) -> None:
        """
        Load the Wiktionary pitch accent supplement (12,788 entries that are
        absent from Kanjium). Downloads the file on first use.
        Silently skips if the file cannot be loaded — Kanjium remains available.
        """
        import json
        path = os.path.join(self._addon_dir, WIKTIONARY_FILENAME)
        if not os.path.exists(path):
            self._download_wiktionary()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for entry in data.get("entries", []):
                word     = katakana_to_hiragana(entry.get("word", "").strip())
                reading  = katakana_to_hiragana(entry.get("reading", "").strip())
                positions = entry.get("pitch_positions", [])
                if not word or not positions:
                    continue
                pitch = positions[0]
                self._wiki_expr_table[(word, reading)] = pitch
                if word not in self._wiki_expr_only_table:
                    self._wiki_expr_only_table[word] = pitch
                if reading and reading not in self._wiki_reading_table:
                    self._wiki_reading_table[reading] = pitch
        except Exception:
            pass

    def _download_wiktionary(self) -> None:
        """Download the Wiktionary supplement from GitHub and cache it locally."""
        path = os.path.join(self._addon_dir, WIKTIONARY_FILENAME)
        try:
            req = urllib.request.Request(
                WIKTIONARY_URL,
                headers={"User-Agent": "AnkiFillPitchNumbers/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            with open(path, "wb") as fh:
                fh.write(data)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            pass


def _strip_html(text: str) -> str:
    """Strip HTML tags. For <ruby> annotations, keeps the BASE text and discards <rt> content."""
    import re
    # Remove <rt>...</rt> blocks entirely so only the ruby base text survives
    text = re.sub(r'<rt[^>]*>.*?</rt>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level separators with a space so adjacent text doesn't merge
    text = re.sub(r'<br\s*/?>|</p>|</div>|</li>', ' ', text, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


def _strip_html_reading(text: str) -> str:
    """Strip HTML tags. For <ruby> annotations, keeps the <rt> reading and discards the base."""
    import re
    # Replace each <ruby>base<rt>reading</rt>...</ruby> with just the reading
    text = re.sub(
        r'<ruby[^>]*>.*?<rt[^>]*>(.*?)</rt>.*?</ruby>',
        r'\1', text, flags=re.DOTALL | re.IGNORECASE,
    )
    # Replace block-level separators with a space so adjacent text doesn't merge
    text = re.sub(r'<br\s*/?>|</p>|</div>|</li>', ' ', text, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


def _is_kana_str(s: str) -> bool:
    """Return True when every character in s is hiragana, katakana, or ー."""
    return bool(s) and all(
        (0x3041 <= ord(c) <= 0x3096) or   # hiragana
        (0x30A1 <= ord(c) <= 0x30FA) or   # katakana
        c == "ー"
        for c in s
    )


def _extract_expression(text: str) -> str:
    """
    Normalize a field value to a plain kanji/kana expression.

    Handles common Anki furigana notation formats:
      - {漢字|かんじ}  →  漢字   (curly-brace pipe format)
      - 食[た]べる     →  食べる  (square-bracket annotation)
    HTML tags are stripped first.
    """
    import re
    text = _strip_html(text)
    text = re.sub(r'\{([^|]+)\|[^}]+\}', r'\1', text)   # {kanji|reading} → kanji
    text = re.sub(r'\[([^\]]+)\]', '', text)              # remove [reading] brackets
    return text.strip()


def _extract_reading(text: str) -> str:
    """
    Normalize a field value to a plain kana reading.

    Handles common Anki furigana notation formats:
      - {漢字|かんじ}  →  かんじ  (curly-brace pipe format)
      - 食[た]べる     →  たべる   (square-bracket annotation)
    If the text contains no furigana markup, it is returned as-is after
    HTML stripping (plain kana fields are the common case).
    HTML tags are stripped first.
    """
    import re
    text = _strip_html_reading(text)
    text = re.sub(r'\{[^|]+\|([^}]+)\}', r'\1', text)        # {kanji|reading} → reading

    def _sub_bracket(m: re.Match) -> str:
        content = m.group(1)
        if _is_kana_str(content):
            return content                              # furigana: 食[た]べる → たべる
        return re.sub(r'\[[^\]]+\]', '', m.group(0))  # annotation: ところ[3] → ところ

    text = re.sub(r'[^\s\[]+\[([^\]]+)\]', _sub_bracket, text)
    # If the field contained repeated text separated by <br> or whitespace,
    # take only the first non-empty token (Japanese readings never contain spaces).
    first_token = text.split()[0] if text.split() else ""
    return first_token
