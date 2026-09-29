# Development notes — state at v0.2 (2026-09-29)

Handoff for anyone (human or Claude session) continuing work on this editor. Read this together
with [`claude.md`](../claude.md), which holds the save-format reference. This file covers **how we
got here, what is verified, and what's next**.

## Where things are

| What | Where |
|---|---|
| Repo | https://github.com/JFinnTeacher/Sunless-sea-skies-save-editor (`main`, tag `v0.2`) |
| Local clone | `D:\Documents\GitHub\Sunless-sea-skies save editor` |
| Sea saves | `%USERPROFILE%\AppData\LocalLow\Failbetter Games\Sunless Sea\saves\` |
| Skies saves | `%USERPROFILE%\AppData\LocalLow\Failbetter Games\Sunless Skies\storage\characterrepository\Lineage-N\` |
| Skies game data | `E:\GOG Games\Sunless Skies\Sunless Skies_Data\StreamingAssets\BuildInStorage\data\qualities.bytes` (GOG install; Player.log says `D:` — drive letter changed, so `paths.py` scans all drives) |
| Editor backups | `%LOCALAPPDATA%\SunlessSaveEditor\backups\<game>\<folder>\` |

History: v0.2 was built in the `Coding-Projects` monorepo, then moved here (same as pdf-renamer).
The only commits are GitHub's "Initial commit" (GPL-3.0 licence, `.gitattributes`) and the v0.2
import. v0.2 is the baseline to return to if an update goes wrong: `git checkout v0.2`.

## How it was built

1. **Reference:** studied https://github.com/grmcdorman/SunlessSeaSaveEditor (Java/Swing, Sea only,
   last updated ~2016). Took the core idea (qualities list + `EquippedPossession` slots, names from
   `entities/qualities.json`); nothing is copied from it.
2. **Stack chosen by the user:** Python desktop app with Tkinter — standard library only (Pillow is
   *not* installed; don't add dependencies without asking).
3. **Scope chosen by the user for v1:** core resources, cargo & items, any quality by name,
   ship & equipment. All four are implemented.
4. **Save format** was worked out from the user's real saves (1 Sea, 2 Skies lineages), not docs.
5. **Skies names** required reverse-engineering the binary `qualities.bytes` (game is IL2CPP — no
   managed DLL to decompile). Details in `claude.md` and `sunless_editor/skies_bytes.py`.

## Verification status

| Claim | Status | Evidence |
|---|---|---|
| Unedited saves are written back byte-identical | ✅ verified | `test_unmodified_real_saves_are_byte_identical` on all real saves |
| Edited Skies save loads in-game | ✅ verified | User set Sovereigns 36 → higher with the editor (21:25); game autosaved at 21:33/21:35 with 4150 Sovereigns |
| Skies officer assignment format | ✅ verified | Real save: Incautious Driver (132923) as Chief Engineer; editor output byte-equal to game's. Test `test_officer_assignment_matches_game` |
| Skies charters are category 150 hold items | ✅ verified | Fastidious Inspector (137000) appeared after taking a charter |
| Skies quality names for all qualities in real saves | ✅ verified | Test `test_skies_catalog_names_every_quality_in_real_saves` |
| Edited **Sea** save loads in-game | ❌ not yet tested | Only the byte-level format has been checked |
| Sea/Skies ship/locomotive swap in-game | ❌ not yet tested | Format mirrors game output, not played |
| Skies equipment slot swap in-game | ❌ not yet tested | |
| Skies category labels 5000–60000, 70004–70006, 70008 | ⚠️ guesses | Labelled with `?` in `catalog.py` |
| Skies catalog completeness | ⚠️ partial | 2079 of 2109 declared records parsed; unknown ids show as "Unknown #id" |

## Open work (agreed or noted, not started)

1. **Fix Skies equipment slot labels.** Category 70006 contains "In Possession of a Driver"
   (officer-tracking), so the "Cabin?" label is probably wrong. Ask the user for the slot names shown
   on the in-game locomotive screen, then fix `SKIES_CATEGORIES` in `catalog.py`. The *slot qualities*
   in category 1 are named Auxiliary 131179, Bridge 131178, Engine 140435, Plating 131177,
   Primary Weapon 131180, Secondary Weapon 131181, Scout 133639 — likely a mapping hint.
   `Slots[].Type` (1/2) meaning is also unknown (fore/aft?). `Active` is shown as "slot inactive".
2. ~~**Hide non-items from Cargo & items (Skies).**~~ Done: `SkiesSave.is_cargo` requires nature
   Thing and skips `SkiesSave.NOT_ITEMS` (138302 Minimum Safe Manning Number). Add ids there if
   other stats turn up in the hold list.
3. **Charters:** deliberately not editable beyond the hold item. A charter also sets story
   qualities (e.g. "The Fastidious Inspector" 134078 = 10, "A Broken Clock" 134079 = 16 timer,
   "Locks Fastidious Inspector" 139614). If adding charter support, change these together.
4. **Market deals** (`PlayerProspects[]`, `PlayerBargains[]`) are not edited.
5. **Decode the remaining ~30 Skies records** (header says 2109, parser finds 2079; all records
   parsed are real — the gap is unexplained). Only matters for adding rarely used qualities.
6. **Test a Sea edit in-game** (e.g. change Echoes, load the Sea autosave).
7. Possible later: packaged `.exe` on GitHub Releases (PyInstaller) — not discussed in detail.

## Working methods that worked well

- **Never touch real saves in tests.** Copy to a temp dir; `paths.backup_dir` is patched in tests.
- **Diff saves to learn formats:** ask the user to do one thing in-game (hire an officer, take a
  charter), then compare the new `autosave.json` with the previous one — either the editor's backup
  in `%LOCALAPPDATA%\SunlessSaveEditor\backups\` or the game's own `autosave_backup.json` (often
  only minutes older, so less useful).
- **Check game output, then match it byte-for-byte** in a test (see the Skies tests in
  `tests/test_saves.py`).
- **GUI check:** `python tools/smoke_gui.py <screenshot_dir>` drives the real window against temp
  copies of every save and screenshots each tab (Windows).
- Skies serialiser omits 0/null keys and orders keys
  `EquippedPossession, Name, EffectiveLevel, EffectiveLevelModifier, Level, AssociatedQuality` —
  always go through `SkiesSave._rebuild` when changing an entry.

## Commands

```
python -m sunless_editor                     # run (or double-click run.pyw)
python -m unittest discover -s tests -v      # 15 tests, ~1.5 s
python tools/smoke_gui.py shots              # GUI smoke test + screenshots
```

When releasing: bump `__version__` in `sunless_editor/__init__.py`, add a `CHANGELOG.md` entry,
tag `vX.Y`.
