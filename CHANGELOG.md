# Changelog

## 0.2 — 2026-09-29
First working release.
- Sunless Sea and Sunless Skies saves detected automatically; byte-exact round-trip of unedited saves.
- Tabs: Resources, Cargo & items, Ship & equipment (ship/locomotive, equipment slots, officers), All qualities.
- Skies quality names read from the game's binary `qualities.bytes`.
- Automatic backups to `%LOCALAPPDATA%\SunlessSaveEditor\backups\`; warns if the game is running.
- Verified in-game: an edited Skies save (Sovereigns) loaded and was carried forward by the game.
- Skies officer assignment format verified against a real save.
