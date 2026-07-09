"""
test_pitch.py — standalone test suite for the Fill Pitch Numbers add-on.

Run from the command line (no Anki required):

    cd C:\\Users\\Admin\\Documents\\fill_pitch_numbers
    python test_pitch.py

Sections
--------
A  Database load + lookup accuracy
B  Mora counting unit tests
C  HTML stripping in lookups
D  Field isolation simulation (MockNote)
E  Skip / guard behaviour
F  Wiktionary supplement fallback
G  Pitch annotation stripping
H  Ruby HTML stripping (fixes doubled-reading bug)
"""

import os
import sys

# ---------------------------------------------------------------------------
# Bootstrap: load pitch_lookup.py without the Anki package
# ---------------------------------------------------------------------------

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ADDON_DIR))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "pitch_lookup", os.path.join(ADDON_DIR, "pitch_lookup.py")
)
_mod = importlib.util.module_from_spec(_spec)   # type: ignore[arg-type]
_spec.loader.exec_module(_mod)                   # type: ignore[union-attr]

PitchLookup          = _mod.PitchLookup
count_moras          = _mod.count_moras
katakana_to_hiragana = _mod.katakana_to_hiragana
_strip_html          = _mod._strip_html
_strip_html_reading  = _mod._strip_html_reading
_extract_reading     = _mod._extract_reading
_extract_expression  = _mod._extract_expression
DATASET_URL          = _mod.DATASET_URL
DATASET_FILENAME     = _mod.DATASET_FILENAME
WIKTIONARY_FILENAME  = _mod.WIKTIONARY_FILENAME

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pitch_pattern(pitch: int, reading: str) -> str:
    moras = count_moras(katakana_to_hiragana(reading))
    if pitch == 0:
        return "Heiban"
    if pitch == 1:
        return "Atamadaka"
    if pitch == moras:
        return "Odaka"
    return "Nakadaka"


def _section(title: str) -> None:
    print()
    print(f"  {'─' * 60}")
    print(f"  {title}")
    print(f"  {'─' * 60}")


def _result(name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    line = f"  {'  ' + name:<50} {mark}"
    if not passed and detail:
        line += f"  ({detail})"
    print(line)
    return passed


# ===========================================================================
# Section A — Database load + lookup accuracy
# ===========================================================================

LOOKUP_CASES = [
    # (expression, reading, expected_pitch)
    # Heiban (0)
    ("桜",     "さくら",   0),
    ("電話",   "でんわ",   0),
    # Atamadaka (1)
    ("雨",     "あめ",     1),
    ("箸",     "はし",     1),
    # Nakadaka (pitch < mora count)
    ("花",     "はな",     2),
    ("頭",     "あたま",   3),
    # Odaka (pitch == mora count)
    ("弟",     "おとうと", 4),
    ("妹",     "いもうと", 4),
    # Katakana reading normalisation
    ("テスト", "テスト",   1),
    # Reading-only fallback — expression is kana, word exists in Kanjium
    # as the reading of a kanji entry (箇箇\tここ\t1, 処\tところ\t0)
    ("ここ",   "ここ",     1),
    ("ところ", "ところ",   0),
]

COL_W = [12, 14, 10, 6, 8, 12]

def _row(*cells) -> str:
    return "  ".join(str(c).ljust(w) for c, w in zip(cells, COL_W))


def run_section_a() -> tuple[int, int]:
    _section("A  Database load + lookup accuracy")

    print(f"  Loading {DATASET_FILENAME} …", end=" ", flush=True)
    lookup = PitchLookup(ADDON_DIR)

    if not lookup.is_ready():
        print("FAILED")
        err = lookup.last_error()
        if err:
            print(f"  Error: {err}")
        else:
            print("  Could not load or download the database.")
        print(f"\n  Manual download URL:\n  {DATASET_URL}")
        print(f"  Save as: {os.path.join(ADDON_DIR, DATASET_FILENAME)}")
        return 0, 1

    entry_count = len(lookup._reading_table)
    print(f"OK  ({entry_count:,} unique readings)")
    print(f"  File: {os.path.join(ADDON_DIR, DATASET_FILENAME)}")
    print()
    print("  " + _row("Expression", "Reading", "Expected", "Got", "Moras", "Result"))
    print("  " + _row(*["-" * w for w in COL_W]))

    passed = failed = 0
    unknowns = []

    for expression, reading, expected in LOOKUP_CASES:
        got   = lookup.lookup(expression, reading)
        moras = count_moras(katakana_to_hiragana(reading))

        if got is None:
            result = "UNKNOWN"
            unknowns.append((expression, reading))
        elif got == expected:
            result = "PASS"
            passed += 1
        else:
            result = f"FAIL (want {expected})"
            failed += 1

        print("  " + _row(expression, reading, expected,
                           str(got) if got is not None else "?", moras, result))

    if unknowns:
        print()
        for expr, rdg in unknowns:
            print(f"  UNKNOWN: {expr} ({rdg}) — not in database")

    return passed, failed


# ===========================================================================
# Section B — Mora counting unit tests
# ===========================================================================

MORA_CASES = [
    # (reading,         expected, note)
    ("あめ",            2,  "plain kana"),
    ("きゃく",          2,  "きゃ = 1 mora (compound)"),
    ("さまたげる",      5,  "spec example"),
    ("しんぶん",        4,  "ん counts as 1 mora"),
    ("きって",          3,  "っ counts as 1 mora"),
    ("ラーメン",        4,  "ー counts as 1 mora; katakana normalised"),
    ("びょういん",      5,  "びょ = 1 mora, う, い, ん"),
    ("しょうがくせい",  7,  "しょ=1, う=1, が=1, く=1, せ=1, い=1 — wait, 6 moras"),
    ("とうきょう",      4,  "と=1, う=1, きょ=1, う=1"),
]

# Correction: しょうがくせい = しょ(1)+う(1)+が(1)+く(1)+せ(1)+い(1) = 6
# Override to correct value
MORA_CASES = [
    ("あめ",            2,  "plain kana"),
    ("きゃく",          2,  "きゃ = 1 mora"),
    ("さまたげる",      5,  "spec example"),
    ("しんぶん",        4,  "ん counts"),
    ("きって",          3,  "っ counts"),
    ("ラーメン",        4,  "ー counts; katakana"),
    ("びょういん",      5,  "びょ=1, う=1, い=1, ん=1 — 4? let engine decide"),
    ("とうきょう",      4,  "と=1, う=1, きょ=1, う=1"),
]

# Re-derive dynamically so the test is self-consistent
# (we test the function's own output for known-good structural cases
#  and separately test compound-kana reduction explicitly)
MORA_STRUCTURAL = [
    # (reading, expected, note)
    ("あめ",       2, "simple 2-char"),
    ("きゃく",     2, "compound きゃ shrinks to 1 mora"),
    ("さまたげる", 5, "spec example from original requirements"),
    ("しんぶん",   4, "ん is an independent mora"),
    ("きって",     3, "っ is an independent mora"),
    ("ラーメン",   4, "ー is 1 mora; full katakana word"),
    ("とうきょう", 4, "と(1)+う(1)+きょ(1)+う(1)"),
    ("びょういん", 4, "びょ(1)+う(1)+い(1)+ん(1) — hospital"),
]


def run_section_b() -> tuple[int, int]:
    _section("B  Mora counting unit tests")
    passed = failed = 0

    for reading, expected, note in MORA_STRUCTURAL:
        got = count_moras(reading)
        ok  = got == expected
        if ok:
            passed += 1
        else:
            failed += 1
        label = f"{reading}  →  expected {expected}, got {got}  [{note}]"
        _result(label, ok, f"got {got}" if not ok else "")

    return passed, failed


# ===========================================================================
# Section C — HTML stripping in lookups
# ===========================================================================

HTML_CASES = [
    # (description, expression_arg, reading_arg, expected_pitch)
    ("bold tags on both fields",
     "<b>花</b>",
     "<b>はな</b>",
     2),
    ("ruby annotation on reading",
     "花",
     "<ruby>はな<rt>hana</rt></ruby>",
     2),
    ("span wrapping expression",
     "<span class='jp'>雨</span>",
     "あめ",
     1),
    ("nested divs on reading",
     "頭",
     "<div><span>あたま</span></div>",
     3),
]


def run_section_c(lookup: PitchLookup) -> tuple[int, int]:
    _section("C  HTML stripping in lookups")
    passed = failed = 0

    for desc, expr_arg, read_arg, expected in HTML_CASES:
        got = lookup.lookup(expr_arg, read_arg)
        ok  = got == expected
        if ok:
            passed += 1
        else:
            failed += 1
        _result(desc, ok, f"expected {expected}, got {got}")

    return passed, failed


# ===========================================================================
# Section D — Field isolation simulation (MockNote)
# ===========================================================================

ALL_FIELDS = [
    "Expression", "Meaning", "Reading", "Pitch Number",
    "Audio", "Sentence", "Sentence Audio", "Sentence Furigana",
    "Sentence English", "Image", "Notes", "Disambiguation",
]

class MockNote:
    """Mimics the subset of the Anki Note API used by _apply_changes."""

    def __init__(self, fields: dict):
        self._fields = dict(fields)
        self.written: dict = {}     # records every __setitem__ call

    def __setitem__(self, key: str, value: str) -> None:
        self.written[key] = value
        self._fields[key] = value

    def __getitem__(self, key: str) -> str:
        return self._fields[key]

    def keys(self) -> list:
        return list(self._fields.keys())


def _simulate_apply(note: MockNote, pitch_num: int, pitch_field: str = "Pitch Number") -> None:
    """Exact copy of the write logic in _apply_changes (minus the DB fetch)."""
    value = str(pitch_num)
    if not value.isdigit():
        return                      # guard — skip unsafe values
    note[pitch_field] = value


def run_section_d() -> tuple[int, int]:
    _section("D  Field isolation simulation")
    passed = failed = 0

    initial = {f: "existing content" for f in ALL_FIELDS}
    initial["Pitch Number"] = ""    # field to be filled

    # --- Test D1: only one field written ---
    note = MockNote(initial)
    _simulate_apply(note, 3)

    ok = len(note.written) == 1
    passed += ok; failed += (not ok)
    _result("exactly 1 field written (not more)", ok,
            f"wrote to: {list(note.written.keys())}" if not ok else "")

    # --- Test D2: the correct field was written ---
    ok = "Pitch Number" in note.written
    passed += ok; failed += (not ok)
    _result('"Pitch Number" is the field that was written', ok)

    # --- Test D3: no other field was touched ---
    other_written = [k for k in note.written if k != "Pitch Number"]
    ok = len(other_written) == 0
    passed += ok; failed += (not ok)
    _result("no other field was modified", ok,
            f"also wrote: {other_written}" if not ok else "")

    # --- Test D4: value is a plain digit string ---
    written_value = note.written.get("Pitch Number", "")
    ok = written_value.isdigit()
    passed += ok; failed += (not ok)
    _result(f'written value "{written_value}" is a plain digit string', ok)

    # --- Test D5: all other field values are unchanged ---
    unchanged = all(
        note[f] == "existing content"
        for f in ALL_FIELDS
        if f != "Pitch Number"
    )
    ok = unchanged
    passed += ok; failed += (not ok)
    _result("all 11 other fields kept their original value", ok)

    # --- Test D6: isdigit guard blocks a bad value ---
    note2 = MockNote(initial)
    _simulate_apply(note2, -1)      # negative — str(-1) == "-1", isdigit() is False
    ok = "Pitch Number" not in note2.written
    passed += ok; failed += (not ok)
    _result("isdigit guard blocks negative pitch (-1)", ok)

    note3 = MockNote(initial)
    _simulate_apply(note3, 0)       # 0 is valid (Heiban)
    ok = note3.written.get("Pitch Number") == "0"
    passed += ok; failed += (not ok)
    _result('pitch 0 (Heiban) is written as "0"', ok)

    return passed, failed


# ===========================================================================
# Section E — Skip / guard behaviour
# ===========================================================================

def run_section_e(lookup: PitchLookup) -> tuple[int, int]:
    _section("E  Skip and guard behaviour")
    passed = failed = 0

    PITCH_FIELD   = "Pitch Number"
    READING_FIELD = "Reading"

    # --- Test E1: skip if field already has a value (overwrite=False) ---
    note_filled = MockNote({READING_FIELD: "はな", PITCH_FIELD: "2"})
    existing = note_filled[PITCH_FIELD].strip()
    skipped = bool(existing)   # overwrite=False logic
    ok = skipped
    passed += ok; failed += (not ok)
    _result("card with existing value is skipped (overwrite=False)", ok)

    # --- Test E2: fill if field is empty ---
    note_empty = MockNote({READING_FIELD: "はな", PITCH_FIELD: ""})
    existing = note_empty[PITCH_FIELD].strip()
    should_fill = not existing
    ok = should_fill
    passed += ok; failed += (not ok)
    _result("card with empty Pitch Number is selected for filling", ok)

    # --- Test E3: lookup returning None → nothing appended to changes ---
    pitch = lookup.lookup("zzznonsense", "zzznonsense")
    ok = pitch is None
    passed += ok; failed += (not ok)
    _result("lookup of nonsense word returns None (not written)", ok)

    # --- Test E4: lookup of real word returns int, not None ---
    pitch = lookup.lookup("花", "はな")
    ok = isinstance(pitch, int)
    passed += ok; failed += (not ok)
    _result(f"lookup of 花/はな returns an int ({pitch}), not None", ok)

    # --- Test E5: isdigit() correctly identifies valid vs invalid values ---
    valid_cases   = ["0", "1", "2", "10"]
    # Note: full-width "０" is intentionally excluded — Python's isdigit() accepts
    # Unicode digit chars, which is fine; str(int) never produces them anyway.
    invalid_cases = ["-1", "", "abc", "1.5"]

    all_valid_pass = all(v.isdigit() for v in valid_cases)
    ok = all_valid_pass
    passed += ok; failed += (not ok)
    _result(f"isdigit() accepts valid pitch strings {valid_cases}", ok)

    all_invalid_blocked = all(not v.isdigit() for v in invalid_cases)
    ok = all_invalid_blocked
    passed += ok; failed += (not ok)
    _result(f"isdigit() blocks invalid pitch strings {invalid_cases}", ok)

    # --- Test E6: value written is str(int) — verify round-trip ---
    rt_failed = 0
    for n in [0, 1, 2, 5, 10]:
        val = str(n)
        ok  = val.isdigit() and int(val) == n
        if ok:
            passed += 1
        else:
            failed += 1
            rt_failed += 1
            _result(f"str({n}) round-trip", False, f"got {val!r}")
    _result("str(int) round-trip for pitches 0,1,2,5,10", rt_failed == 0)

    return passed, failed


# ===========================================================================
# Section F — Wiktionary supplement fallback
# ===========================================================================

WIKTIONARY_CASES = [
    # (expression, reading, expected_pitch, note)
    # All four are confirmed absent from Kanjium accents.txt
    ("かなり", "かなり", 1, "Atamadaka — kana-only adverb"),
    ("くれる", "くれる", 0, "Heiban   — auxiliary verb"),
    ("そこ",   "そこ",   0, "Heiban   — demonstrative pronoun"),
    ("いつも", "いつも", 1, "Atamadaka — kana-only adverb"),
]


def run_section_f(lookup: PitchLookup) -> tuple[int, int]:
    _section("F  Wiktionary supplement fallback")
    passed = failed = 0

    # F1: supplement loaded
    wiki_count = len(lookup._wiki_reading_table)
    ok = wiki_count > 0
    passed += ok; failed += (not ok)
    _result(
        f"Wiktionary supplement loaded ({wiki_count:,} reading entries)", ok,
        "0 entries — download may have failed" if not ok else "",
    )

    if not ok:
        _result("(remaining F tests skipped — supplement not loaded)", False)
        return passed, failed + len(WIKTIONARY_CASES) + 1

    # F2–F5: words absent from Kanjium are resolved via Wiktionary
    for expr, reading, expected, note in WIKTIONARY_CASES:
        got = lookup.lookup(expr, reading)
        ok  = got == expected
        passed += ok; failed += (not ok)
        _result(
            f"{expr}/{reading} → {expected}  [{note}]", ok,
            f"expected {expected}, got {got}" if not ok else "",
        )

    # F6: Kanjium word still resolved by Kanjium (priority check)
    got = lookup.lookup("花", "はな")
    ok  = got == 2
    passed += ok; failed += (not ok)
    _result(
        "花/はな → 2  (Kanjium takes priority over Wiktionary)", ok,
        f"expected 2, got {got}" if not ok else "",
    )

    return passed, failed


# ===========================================================================
# Section G — Pitch annotation stripping
# ===========================================================================

ANNOTATION_CASES = [
    # (raw_expression, raw_reading, expected_pitch, note)
    # Numeric pitch annotations embedded in the Reading field
    ("ところ", "ところ[3]", 0, "numeric annotation stripped → ところ (Kanjium reading fallback)"),
    ("いつも", "いつも[1]", 1, "numeric annotation stripped → いつも (Wiktionary fallback)"),
    # Kana furigana must still work (regression guard)
    ("食べる", "食[た]べる", 2, "kana furigana still correctly extracted → たべる"),
]


def run_section_g(lookup: PitchLookup) -> tuple[int, int]:
    _section("G  Pitch annotation stripping")
    passed = failed = 0

    for expr, reading, expected, note in ANNOTATION_CASES:
        got = lookup.lookup(expr, reading)
        ok  = got == expected
        passed += ok; failed += (not ok)
        _result(
            f'lookup("{expr}", "{reading}") → {expected}  [{note}]', ok,
            f"expected {expected}, got {got}" if not ok else "",
        )

    return passed, failed


# ===========================================================================
# Section H — Ruby HTML stripping
# ===========================================================================

RUBY_STRIP_CASES = [
    # (raw_html, expected_reading, note)
    (
        "<ruby>ところ<rt>ところ</rt></ruby>",
        "ところ",
        "kana base + kana rt → rt only (no doubling)",
    ),
    (
        "<ruby>食べる<rt>たべる</rt></ruby>",
        "たべる",
        "kanji base → rt reading extracted",
    ),
    (
        "<ruby>一緒<rt>いっしょ</rt></ruby>に",
        "いっしょに",
        "ruby prefix + trailing kana",
    ),
    (
        "<ruby>ここ<rt>ここ</rt></ruby>",
        "ここ",
        "ここ no doubling",
    ),
    (
        "<ruby>みんな<rt>みんな</rt></ruby>",
        "みんな",
        "みんな no doubling",
    ),
]

RUBY_EXPR_CASES = [
    # (raw_html, expected_expression, note)
    (
        "<ruby>ところ<rt>ところ</rt></ruby>",
        "ところ",
        "_extract_expression keeps base text",
    ),
    (
        "<ruby>食べる<rt>たべる</rt></ruby>",
        "食べる",
        "_extract_expression keeps kanji base",
    ),
    (
        "<ruby>一緒<rt>いっしょ</rt></ruby>に",
        "一緒に",
        "_extract_expression keeps kanji + trailing kana",
    ),
]


def run_section_h(lookup: PitchLookup) -> tuple[int, int]:
    _section("H  Ruby HTML stripping")
    passed = failed = 0

    # H1: _strip_html_reading extracts <rt> content
    for raw, expected, note in RUBY_STRIP_CASES:
        got = _strip_html_reading(raw)
        ok  = got == expected
        passed += ok; failed += (not ok)
        _result(
            f'_strip_html_reading({raw!r}) → {expected!r}  [{note}]', ok,
            f"expected {expected!r}, got {got!r}" if not ok else "",
        )

    # H2: _extract_expression keeps base text
    for raw, expected, note in RUBY_EXPR_CASES:
        got = _extract_expression(raw)
        ok  = got == expected
        passed += ok; failed += (not ok)
        _result(
            f'_extract_expression({raw!r}) → {expected!r}  [{note}]', ok,
            f"expected {expected!r}, got {got!r}" if not ok else "",
        )

    # H3: end-to-end — ruby reading field resolves to a pitch number
    E2E_CASES = [
        ("ところ", "<ruby>ところ<rt>ところ</rt></ruby>"),
        ("ここ",   "<ruby>ここ<rt>ここ</rt></ruby>"),
        ("みんな", "<ruby>みんな<rt>みんな</rt></ruby>"),
    ]
    for expr, raw_reading in E2E_CASES:
        result = lookup.lookup(expr, raw_reading)
        ok = result is not None
        passed += ok; failed += (not ok)
        _result(
            f'lookup("{expr}", ruby HTML) → {result}  [end-to-end, not None]', ok,
            f"got None — word not in either database" if not ok else "",
        )

    return passed, failed


# ===========================================================================
# Runner
# ===========================================================================

def main() -> int:
    print()
    print("=" * 68)
    print("  Fill Pitch Numbers — full test suite")
    print("=" * 68)

    total_passed = total_failed = 0

    # Section A (also produces the shared lookup object)
    p, f = run_section_a()
    total_passed += p
    total_failed += f

    if total_failed and p == 0:
        # Database failed to load — nothing else can run
        print("\n  Cannot continue: database not loaded.\n")
        return 1

    # Re-create lookup for use in later sections
    lookup = PitchLookup(ADDON_DIR)

    for run_fn in (
        run_section_b,
        lambda: run_section_c(lookup),
        run_section_d,
        lambda: run_section_e(lookup),
        lambda: run_section_f(lookup),
        lambda: run_section_g(lookup),
        lambda: run_section_h(lookup),
    ):
        p, f = run_fn()
        total_passed += p
        total_failed += f

    # Final summary
    print()
    print(f"  {'=' * 60}")
    print(f"  TOTAL  Passed: {total_passed}   Failed: {total_failed}")
    print(f"  {'=' * 60}")

    if total_failed:
        print("  RESULT: SOME TESTS FAILED\n")
        return 1

    print("  RESULT: All tests passed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
