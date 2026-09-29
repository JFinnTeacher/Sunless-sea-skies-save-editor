# Sunless Sea / Sunless Skies save editor

Python 3 + Tkinter desktop app (no third-party dependencies) that edits save files for
Failbetter's *Sunless Sea* and *Sunless Skies*. Inspired by the (abandoned, Sea-only)
Java editor at https://github.com/grmcdorman/SunlessSeaSaveEditor.

- Run: `python -m sunless_editor` (or double-click `run.pyw`)
- Tests: `python -m unittest discover -s tests -v` — tests only ever touch temp copies of saves.

## Layout
- `sunless_editor/paths.py` — locates save files and game data on Windows/macOS/Linux.
- `sunless_editor/skies_bytes.py` — reader for Skies' binary `qualities.bytes`.
- `sunless_editor/catalog.py` — quality definitions (id → name/category/nature/slot) for both games.
- `sunless_editor/saves.py` — `SeaSave` / `SkiesSave` models: load, edit, backup, write.
- `sunless_editor/gui.py` — Tkinter UI.

## Save file facts (verified against real saves, Sept 2026)
- Both games save **compact UTF-8 JSON with no BOM**. `json.dumps(data, separators=(",", ":"),
  ensure_ascii=False)` reproduces an untouched save **byte-for-byte** — keep it that way
  (don't pretty-print, don't reorder keys). There is a round-trip test for this.
- Save locations (Windows, under `%USERPROFILE%\AppData\LocalLow\Failbetter Games\`):
  - Sea: `Sunless Sea\saves\*.json`
  - Skies: `Sunless Skies\storage\characterrepository\Lineage-N\autosave.json`
    (+ `autosave_backup.json`, `saveSnippet.json` = summary shown in the load menu).
- Backups made by the editor go to `%LOCALAPPDATA%\SunlessSaveEditor\backups\` — never into the
  game folders, in case the game enumerates extra files there.

### Sunless Sea
- `QualitiesPossessedList[]`: every entry has the same 18 keys; id = `AssociatedQualityId`,
  value = `Level`.
- Slots (Current Ship 102889, Engines, Deck, Bridge, Auxiliary, Forward, Aft, officer roles
  like First Officer 102769…) are qualities whose `EquippedPossession` is an **exact copy** of the
  owned item's entry. The item must also be in the list itself.
- Definitions: `LocalLow\...\Sunless Sea\entities\qualities.json` (plain JSON). An item's
  `AssignToSlot.Id` says which slot it fits. Ship stats (Hold, MaxHull…) are 0 in the save —
  the game derives them from the ship's `Enhancements`.

### Sunless Skies
- `QualitiesPossessedList[]` entries: `{EquippedPossession?, Name?, EffectiveLevel?,
  EffectiveLevelModifier?, Level?, AssociatedQuality: {Tag, Id}}`. The serializer **omits keys
  whose value is 0/null**. `EffectiveLevel = Level + EffectiveLevelModifier` — keep both in sync.
- Equipment lives in top-level `Slots[]`: `{Type, Category, EquipmentQualityId?, Active?}`;
  `Category` = the item category that fits (70004–70010). Equipped items are also possessed.
- Current Locomotive (132796) uses `EquippedPossession` like Sea's Current Ship.
- Officer role qualities (First Officer 131168, Chief Engineer 131169, Signaller 131170,
  Quartermaster 131171, Mascot 131172) use `EquippedPossession` like Sea — **verified** against a
  real save (Incautious Driver 132923 as Chief Engineer): the copy is `{EffectiveLevel, Level,
  AssociatedQuality}` with no Name. Officers are category 106 and are also possessed.
- Category 150 = anything carried in the hold: passengers/charters (e.g. Fastidious Inspector
  137000, verified), keepsakes, trophies, amber. A charter also has story qualities
  (e.g. "The Fastidious Inspector" 134078, "Locks Fastidious Inspector" 139614), so adding or
  removing only the hold item can leave the storyline inconsistent.
- Market trade deals are in top-level `PlayerProspects[]` / `PlayerBargains[]`
  (`{Setting, ProspectId|BargainId, DateTimer, DemandLeft|StockLeft}`) — not edited yet.
- Definitions are only in binary `qualities.bytes` (game install
  `Sunless Skies_Data\StreamingAssets\BuildInStorage\data\` and a cached copy in
  `LocalLow\...\Sunless Skies\storage\data\`). The game is IL2CPP, so no DLL to decompile.
  Format reverse-engineered: int32 count, then records; strings are `00` (null) or
  `01 <7-bit varint len> <utf8>`. Each record ends with
  `int32 DifficultyScaler, int32 AllowedOn, int32 Nature, int32 Category, 5 × string,
  string Name, int32 Id`. `skies_bytes.py` anchors on that tail. It finds ~2080 of the 2109
  declared records (every quality in the test saves resolves); unknown ids are shown as
  "Unknown #id" and stay editable.
- Nature: 1 = Status, 2 = Thing, 3 = (unknown/other). Category numbers are labelled in
  `catalog.py`; labels for 5000–60000 and 70004–70006 are best guesses.
