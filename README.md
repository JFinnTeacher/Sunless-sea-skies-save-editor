# Sunless Sea / Sunless Skies save editor

A small desktop editor for *Sunless Sea* and *Sunless Skies* saves. Python 3.10+ only; no extra packages.

```
python -m sunless_editor      # or double-click run.pyw
```

It finds your saves automatically (pick one from the **Save** list, or **Browse…**). Tabs:

- **Resources** — Echoes/Sovereigns, fuel, supplies, hull, crew, terror, Iron/Mirrors/Veils/Hearts (+ Pages / Experience).
- **Cargo & items** — goods and curiosities you carry; set amounts, add or remove.
- **Ship & equipment** — swap ship/locomotive, rename it, change equipment and officers.
- **All qualities** — every quality in the save, searchable; add any quality by name or ID.

**Before saving, quit the game** (or at least go to the main menu) so it doesn't overwrite your edit.
Every save first backs up the original to `%LOCALAPPDATA%\SunlessSaveEditor\backups\`
(File → Open backups folder).

Known limits: some Skies category names are guesses,
and a few Skies qualities may show as "Unknown #id" (still editable). See `claude.md` for details.

Licensed under the GNU GPL v3 — see `LICENSE`.
