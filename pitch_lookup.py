"""
Pitch accent lookup module for the Fill Pitch Numbers Anki add-on.

Loads the Kanjium pitch accent dataset and provides lookup by
(expression, reading) or reading alone. Auto-downloads the dataset
from GitHub on first run if the file is not present.
"""

import os
import urllib.request
import urllib.error
from typing import Optional, Dict, Tuple, List

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


def _lookup_by_reading(
    entries: Dict[str, List[Tuple[str, int]]],
    expr_h: str,
    read_h: str,
) -> Optional[int]:
    """
    Disambiguate homonyms sharing the same reading.

    When expression is present, return the pitch for the matching expression.
    When expression is empty, return the sole entry if unambiguous, else None.
    """
    candidates = entries.get(read_h)
    if not candidates:
        return None
    if expr_h:
        for expr, pitch in candidates:
            if expr == expr_h:
                return pitch
        return None
    # Kana-only cards: use first entry (same as legacy reading_table behaviour)
    return candidates[0][1]


class PitchLookup:
    """
    Loads the Kanjium pitch accent dataset and answers lookup queries.

    Lookup priority:
      1. (expression, reading) exact match  — O(1)
      2. reading disambiguation by expression when exact match misses
      3. reading-only when expression is empty (kana-only cards)
    """

    def __init__(self, addon_dir: str):
        self._addon_dir = addon_dir
        self._data_path = os.path.join(addon_dir, DATASET_FILENAME)

        # --- Kanjium tables ---
        # Keys: (expression_hiragana, reading_hiragana) -> pitch_int
        self._expr_table: Dict[Tuple[str, str], int] = {}
        # Keys: reading_hiragana -> [(expression_hiragana, pitch_int), ...]
        self._reading_entries: Dict[str, List[Tuple[str, int]]] = {}

        # --- Wiktionary supplement tables (fallback) ---
        self._wiki_expr_table: Dict[Tuple[str, str], int] = {}
        self._wiki_reading_entries: Dict[str, List[Tuple[str, int]]] = {}

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
        not found.  Falls back to reading disambiguation when exact match misses.
        """
        if not self._loaded:
            return None

        expr_h = katakana_to_hiragana(_extract_expression(expression))
        read_h = katakana_to_hiragana(_extract_reading(reading))

        # 1. Expression + reading exact match — O(1)
        if expr_h and read_h and (expr_h, read_h) in self._expr_table:
            return self._expr_table[(expr_h, read_h)]

        # 2. Reading disambiguation (expression present or kana-only)
        result = _lookup_by_reading(self._reading_entries, expr_h, read_h)
        if result is not None:
            return result

        # 3. Wiktionary supplement fallback
        if expr_h and read_h and (expr_h, read_h) in self._wiki_expr_table:
            return self._wiki_expr_table[(expr_h, read_h)]
        return _lookup_by_reading(self._wiki_reading_entries, expr_h, read_h)

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
                    self._reading_entries.setdefault(read_h, []).append((expr_h, pitch))

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
                if reading:
                    self._wiki_reading_entries.setdefault(reading, []).append((word, pitch))
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


def _classify_pitch_from_heights(mora_cys: list[float], particle_cy: float) -> Optional[int]:
    """Derive a Tokyo-style pitch number from SVG mora/particle circle heights."""
    n = len(mora_cys)
    if n == 0:
        return None

    all_cys = mora_cys + [particle_cy]
    lo, hi = min(all_cys), max(all_cys)
    if lo == hi:
        return None
    threshold = (lo + hi) / 2

    def is_high(cy: float) -> bool:
        return cy < threshold

    mora_h = [is_high(cy) for cy in mora_cys]
    part_h = is_high(particle_cy)

    # Atamadaka — first mora high, the rest low
    if mora_h[0] and not any(mora_h[1:]):
        return 1

    # Heiban — last mora and particle both high
    if mora_h[-1] and part_h:
        return 0

    # Odaka — last mora high, particle low
    if mora_h[-1] and not part_h:
        return n

    # Nakadaka — drop after mora k inside the word
    for k in range(1, n):
        if mora_h[k - 1] and not mora_h[k]:
            return k

    return None


def _extract_svg_pitch(text: str) -> Optional[int]:
    """
    Extract pitch number from a JouzuJuls SVG diagram embedded in the Reading field.

    Parses the block between <!-- user_accent_start --> and <!-- user_accent_end -->,
    reads mora <text> positions and <circle> heights, and derives the pitch accent
    number (0 = Heiban, 1 = Atamadaka, 2..n-1 = Nakadaka, n = Odaka).
    """
    import re

    block_m = re.search(
        r'<!--\s*user_accent_start\s*-->(.*?)<!--\s*user_accent_end\s*-->',
        text, re.DOTALL | re.IGNORECASE,
    )
    if not block_m:
        return None
    block = block_m.group(1)
    if '<svg' not in block.lower():
        return None

    texts: list[tuple[float, str]] = []
    for tm in re.finditer(
        r'<text[^>]*\bx="([^"]+)"[^>]*>([^<]*)</text>',
        block, re.IGNORECASE,
    ):
        texts.append((float(tm.group(1)), tm.group(2).strip()))
    texts.sort(key=lambda t: t[0])
    if not texts:
        return None

    black_circles: list[tuple[float, float]] = []
    particle_cy: Optional[float] = None
    for cm in re.finditer(
        r'<circle\b([^>]*)/?>',
        block, re.IGNORECASE,
    ):
        attrs = cm.group(1)
        cx_m = re.search(r'\bcx="([^"]+)"', attrs, re.I)
        cy_m = re.search(r'\bcy="([^"]+)"', attrs, re.I)
        if not cx_m or not cy_m:
            continue
        cx = float(cx_m.group(1))
        cy = float(cy_m.group(1))
        is_white = bool(re.search(
            r'fill\s*:\s*#fff(?:fff)?|fill="#fff(?:fff)?"|fill=\'#fff(?:fff)?\'',
            attrs, re.I,
        ))
        if is_white:
            particle_cy = cy
        else:
            black_circles.append((cx, cy))

    if particle_cy is None or not black_circles:
        return None

    mora_cys: list[float] = []
    used: set[int] = set()
    for tx, _ in texts:
        best_i: Optional[int] = None
        best_dist: Optional[float] = None
        for i, (bx, by) in enumerate(black_circles):
            if i in used:
                continue
            dist = abs(bx - tx)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_i = i
        if best_i is None:
            return None
        used.add(best_i)
        mora_cys.append(black_circles[best_i][1])

    if len(mora_cys) != len(texts):
        return None

    return _classify_pitch_from_heights(mora_cys, particle_cy)


def _extract_inline_pitch(text: str) -> Optional[int]:
    """
    Extract a numeric pitch annotation from the raw Reading field.

    Handles deck hints like ところ[3] or いう[2].  Ignores kana furigana
    brackets such as 食[た]べる.  Returns None when no numeric hint is found.
    """
    import re
    text = _strip_html_reading(text)
    for m in re.finditer(r'[^\s\[]+\[([^\]]+)\]', text):
        content = m.group(1).strip()
        if content.isdigit():
            return int(content)
    return None


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
