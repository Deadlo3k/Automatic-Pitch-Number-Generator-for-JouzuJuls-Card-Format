# Pitch Fill

An Anki add-on that automatically fills the **Pitch Number** field on Japanese vocabulary cards using the note type created by **[JouzuJuls](https://www.youtube.com/@JouzuJuls)** (YouTuber). This add-on is designed specifically for that note type and is not guaranteed to work with other card formats.

---

## Who is this for?

For those creating cards with Migaku, or migrating from the JouzuJuls Core 2k/6k vocabulary deck and wanting to avoid manually entering pitch accent numbers card by card — this add-on fills the Pitch Number field automatically using a pitch accent database. What would otherwise take hours is done in seconds.

---

## What it does

1. You select a deck from a list inside Anki.
2. The add-on scans every card in that deck, reads the **Reading** field, and looks up the pitch accent number in the Kanjium dataset (with a Wiktionary-derived supplement as a fallback).
3. It writes the result into the **Pitch Number** field — skipping any card that already has a value, unless you tick "Overwrite existing values".
4. A preview mode lets you see exactly what would change before committing.

The add-on only ever writes to the Pitch Number field. Nothing else on your cards is touched.

---

## Installation

1. Download or clone this repository.
2. Copy the `fill_pitch_numbers` folder into your Anki add-ons directory:
   - **Windows:** `%APPDATA%\Anki2\addons21\`
   - **macOS:** `~/Library/Application Support/Anki2/addons21/`
   - **Linux:** `~/.local/share/Anki2/addons21/`
3. Restart Anki.
4. The add-on appears under **Tools → Japanese Pitch → Fill Pitch Numbers…**

On first run, the add-on will automatically download the pitch accent database files (~3 MB total) from their public GitHub sources. An internet connection is required for this one-time setup; after that it works fully offline.

---

## Configuration

Edit `config.json` (inside the add-on folder) to match your card's field names:

```json
{
    "reading_field": "Reading",
    "pitch_field": "Pitch Number",
    "expression_fields": ["Expression", "Word", "Vocabulary", "単語", "Front"],
    "overwrite_existing": false
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `reading_field` | `"Reading"` | Field containing the kana reading of the word |
| `pitch_field` | `"Pitch Number"` | Field to write the pitch number into |
| `expression_fields` | (list) | Fields checked in order for the word/expression |
| `overwrite_existing` | `false` | If `true`, overwrites cards that already have a value |

---

## Tested version

This add-on has been tested on **Anki 25.09.2**. Compatibility with other versions is not guaranteed, though the code includes compatibility shims for both older (Qt5/PyQt5) and newer (Qt6/PyQt6) Anki builds. If you run it on a different version and encounter issues, feel free to open an issue or submit a pull request.

---

## A note on AI

This add-on was created with the assistance of AI. If that is a concern for you, the full source code is available here for review — nothing in these files is obfuscated or malicious. You are also, of course, free not to use it if it does not align with your convictions.

---

## Data sources

The pitch accent data comes from two open sources, both downloaded automatically on first run:

- **Kanjium** by [mifunetoshiro](https://github.com/mifunetoshiro/kanjium) — MIT License
- **Japanese Language Data (Wiktionary supplement)** by [jkindrix](https://github.com/jkindrix/japanese-language-data) — used as a fallback for words absent from Kanjium

Neither dataset is bundled with this repository. They are fetched at runtime and cached locally in your add-on folder.

---

## License

MIT — see [LICENSE](LICENSE). Fork it, improve it, and make it your own.
