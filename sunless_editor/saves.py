"""Save file models for Sunless Sea and Sunless Skies.

Edits are applied directly to the loaded JSON tree, so anything the editor does not understand is
written back untouched. Serialisation matches the games' own output byte-for-byte for an
unmodified save (compact separators, raw UTF-8, original key order).
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths
from .catalog import SKIES_CATEGORIES, Catalog, QualityDef, load_sea_catalog, load_skies_catalog

_catalogs: dict[str, Catalog] = {}


def get_catalog(game: str) -> Catalog:
    if game not in _catalogs:
        _catalogs[game] = load_sea_catalog() if game == paths.SEA else load_skies_catalog()
    return _catalogs[game]


def detect_game(data: dict) -> str:
    qualities = data.get("QualitiesPossessedList")
    if isinstance(qualities, list):
        for q in qualities:
            if isinstance(q, dict):
                if "AssociatedQualityId" in q:
                    return paths.SEA
                if isinstance(q.get("AssociatedQuality"), dict):
                    return paths.SKIES
    raise ValueError("This doesn't look like a Sunless Sea or Sunless Skies save file.")


def dumps(data) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def load_save(path: str | Path, catalog: Catalog | None = None) -> "GameSave":
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    game = detect_game(data)
    cls = SeaSave if game == paths.SEA else SkiesSave
    return cls(path, data, catalog or get_catalog(game))


def game_running(game: str) -> bool:
    """Best-effort check whether the game is running (Windows only)."""
    if sys.platform != "win32":
        return False
    exe = f"{paths.GAME_TITLES[game]}.exe"
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"], capture_output=True,
                             text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return exe.lower() in out.stdout.lower()


@dataclass
class EquipSlot:
    key: object            # opaque; pass back to GameSave.equip()
    label: str
    current: int | None    # equipped quality id
    candidates: list[QualityDef] = field(default_factory=list)
    note: str = ""


class GameSave:
    game: str = ""
    # (label, quality id) pairs shown on the Resources tab.
    CORE: list[tuple[str, int]] = []
    # Categories (catalog labels) that count as cargo/items.
    CARGO_CATEGORIES: set = set()

    def __init__(self, path: Path, data: dict, catalog: Catalog):
        self.path = path
        self.data = data
        self.catalog = catalog
        self.dirty = False

    # --- per-game primitives -------------------------------------------------
    def entry_id(self, e: dict) -> int: raise NotImplementedError
    def get_level(self, e: dict) -> int: raise NotImplementedError
    def _set_level_raw(self, e: dict, level: int) -> None: raise NotImplementedError
    def _new_entry(self, qid: int, level: int) -> dict: raise NotImplementedError
    def equipment_slots(self) -> list[EquipSlot]: raise NotImplementedError
    def equip(self, key, qid: int | None) -> None: raise NotImplementedError
    def summary(self) -> str: raise NotImplementedError

    # --- shared behaviour ----------------------------------------------------
    @property
    def title(self) -> str:
        return paths.GAME_TITLES[self.game]

    def entries(self) -> list[dict]:
        return self.data["QualitiesPossessedList"]

    def find(self, qid: int) -> dict | None:
        for e in self.entries():
            if self.entry_id(e) == qid:
                return e
        return None

    def level_of(self, qid: int) -> int | None:
        e = self.find(qid)
        return None if e is None else self.get_level(e)

    def define(self, qid: int) -> QualityDef:
        return self.catalog.get(qid)

    def set_level(self, e: dict, level: int) -> None:
        level = int(level)
        if self.get_level(e) == level:
            return
        self._set_level_raw(e, level)
        self._sync_equipped_copies(self.entry_id(e))
        self.dirty = True

    def set_quality(self, qid: int, level: int) -> dict:
        """Set a quality's level, adding it to the save if missing."""
        e = self.find(qid)
        if e is None:
            return self.add(qid, level)
        self.set_level(e, level)
        return e

    def add(self, qid: int, level: int = 1) -> dict:
        existing = self.find(qid)
        if existing is not None:
            self.set_level(existing, level)
            return existing
        e = self._new_entry(qid, int(level))
        self.entries().append(e)
        self.dirty = True
        return e

    def remove(self, qid: int) -> None:
        e = self.find(qid)
        if e is None:
            return
        self._unequip_everywhere(qid)
        self.entries().remove(e)
        self.dirty = True

    def is_cargo(self, d: QualityDef) -> bool:
        core = {qid for _, qid in self.CORE}
        return d.category in self.CARGO_CATEGORIES and d.id not in core

    def _possessed_copy(self, e: dict) -> dict:
        c = copy.deepcopy(e)
        if "EquippedPossession" in c:
            c["EquippedPossession"] = None
        return c

    def _sync_equipped_copies(self, qid: int) -> None:
        """Keep slot copies (EquippedPossession) in line with the owned entry."""
        owned = self.find(qid)
        for e in self.entries():
            ep = e.get("EquippedPossession")
            if isinstance(ep, dict) and self.entry_id(ep) == qid and owned is not None:
                replacement = self._possessed_copy(owned)
                if self.game == paths.SKIES:
                    replacement.pop("EquippedPossession", None)
                ep.clear()
                ep.update(replacement)

    def _unequip_everywhere(self, qid: int) -> None:
        for e in self.entries():
            ep = e.get("EquippedPossession")
            if isinstance(ep, dict) and self.entry_id(ep) == qid:
                self._clear_equipped(e)

    def _clear_equipped(self, slot_entry: dict) -> None:
        raise NotImplementedError

    def _equip_copy(self, slot_qid: int, qid: int | None, *, replaces_owned: bool) -> None:
        """Equip via EquippedPossession (Sea slots, Skies locomotive/officer roles).

        ``replaces_owned``: the previously equipped item is removed from the save (used for the
        ship/locomotive, which you don't keep in the hold when you swap).
        """
        slot = self.find(slot_qid)
        if slot is None:
            raise KeyError(f"Slot quality #{slot_qid} is not in this save")
        prev = slot.get("EquippedPossession")
        prev_id = self.entry_id(prev) if isinstance(prev, dict) else None
        if qid is None:
            self._clear_equipped(slot)
            self.dirty = True
            return
        item = self.find(qid) or self.add(qid, 1)
        if self.get_level(item) < 1:
            self._set_level_raw(item, 1)
        if replaces_owned and isinstance(prev, dict) and prev.get("Name") and not item.get("Name"):
            self._set_name(item, prev["Name"])  # keep the ship's name
        replacement = self._possessed_copy(item)
        if self.game == paths.SKIES:
            replacement.pop("EquippedPossession", None)
        self._set_equipped(slot, replacement)
        if replaces_owned and prev_id is not None and prev_id != qid:
            e = self.find(prev_id)
            if e is not None:
                self.entries().remove(e)
        self.dirty = True

    def _set_equipped(self, slot_entry: dict, item_copy: dict) -> None:
        slot_entry["EquippedPossession"] = item_copy

    def _set_name(self, e: dict, name: str) -> None:
        e["Name"] = name

    def ship_slot_qid(self) -> int:
        raise NotImplementedError

    def ship_name(self) -> str:
        slot = self.find(self.ship_slot_qid())
        ep = slot.get("EquippedPossession") if slot else None
        return (ep or {}).get("Name") or ""

    def set_ship_name(self, name: str) -> None:
        slot = self.find(self.ship_slot_qid())
        ep = slot.get("EquippedPossession") if slot else None
        if not isinstance(ep, dict) or ep.get("Name") == name:
            return
        owned = self.find(self.entry_id(ep))
        if owned is not None:
            self._set_name(owned, name)
            self._sync_equipped_copies(self.entry_id(ep))
        else:
            self._set_name(ep, name)
        self.dirty = True

    # --- writing -------------------------------------------------------------
    def serialize(self) -> str:
        return dumps(self.data)

    def write(self, path: Path | None = None) -> Path | None:
        """Write the save; returns the backup path (or None if there was nothing to back up)."""
        target = Path(path or self.path)
        backup = None
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            folder = paths.backup_dir() / self.game / _safe(target.parent.name)
            folder.mkdir(parents=True, exist_ok=True)
            backup = folder / f"{target.stem}-{stamp}{target.suffix}"
            shutil.copy2(target, backup)
        tmp = target.with_name(target.name + ".editing")
        tmp.write_bytes(self.serialize().encode("utf-8"))
        os.replace(tmp, target)
        self.path = target
        self.dirty = False
        return backup


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name) or "save"


# =============================================================== Sunless Sea

class SeaSave(GameSave):
    game = paths.SEA
    CURRENT_SHIP = 102889
    CORE = [
        ("Echoes", 102028), ("Fuel", 102027), ("Supplies", 102026),
        ("Hull", 102029), ("Crew", 102030), ("Terror", 102025),
        ("Iron", 102894), ("Mirrors", 102895), ("Veils", 102896), ("Hearts", 102897), ("Pages", 102898),
    ]
    CARGO_CATEGORIES = {"Goods", "Curiosity"}

    def entry_id(self, e):
        return e.get("AssociatedQualityId")

    def get_level(self, e):
        return e.get("Level") or 0

    def _set_level_raw(self, e, level):
        e["Level"] = level

    def _new_entry(self, qid, level):
        # Same keys, in the same order, as the game writes.
        return {
            "Name": None, "EquippedPossession": None, "Relationships": [], "XP": 0,
            "EffectiveLevelModifier": 0, "TargetQuality": None, "TargetLevel": None,
            "CompletionMessage": None, "Level": level, "AssociatedQuality": None,
            "AssociatedQualityId": qid, "QualityName": None, "QualityDescription": None,
            "QualityImage": None, "QualityNature": None, "QualityCategory": None,
            "QualityAllowedOn": None, "Id": 0,
        }

    def _clear_equipped(self, slot_entry):
        slot_entry["EquippedPossession"] = None

    def ship_slot_qid(self):
        return self.CURRENT_SHIP

    def is_cargo(self, d):
        return super().is_cargo(d) and d.nature == "Thing" and d.slot_id is None and d.id not in self._slot_ids()

    def _slot_ids(self) -> set[int]:
        return {d.slot_id for d in self.catalog.defs.values() if d.slot_id}

    def equipment_slots(self):
        slots = []
        slot_ids = self._slot_ids() | {self.CURRENT_SHIP}
        for e in self.entries():
            sid = self.entry_id(e)
            if sid not in slot_ids:
                continue
            ep = e.get("EquippedPossession")
            candidates = self.catalog.where(lambda d, sid=sid: d.slot_id == sid)
            note = "Swapping ships removes the old ship." if sid == self.CURRENT_SHIP else ""
            slots.append(EquipSlot(sid, self.define(sid).name, self.entry_id(ep) if ep else None, candidates, note))
        order = [self.CURRENT_SHIP]
        slots.sort(key=lambda s: (s.key not in order, self._is_officer_slot(s), s.label))
        return slots

    def _is_officer_slot(self, s: EquipSlot) -> bool:
        return any(c.category == "Companion" for c in s.candidates)

    def equip(self, key, qid):
        self._equip_copy(key, qid, replaces_owned=(key == self.CURRENT_SHIP))

    def summary(self):
        d = self.data
        port = (d.get("CurrentPort") or {}).get("Name") if isinstance(d.get("CurrentPort"), dict) else None
        bits = [f"Captain {d.get('Name') or '?'}"]
        if port:
            bits.append(f"at {port}")
        if d.get("InGameDate"):
            bits.append(f"in-game date {str(d['InGameDate'])[:10]}")
        return ", ".join(bits)


# ============================================================ Sunless Skies

class SkiesSave(GameSave):
    game = paths.SKIES
    CURRENT_LOCOMOTIVE = 132796
    OFFICER_ROLES = [131168, 131169, 131170, 131171, 131172]  # First Officer, Chief Engineer, Signaller, Quartermaster, Mascot
    CORE = [
        ("Sovereigns", 131137), ("Fuel", 132096), ("Supplies", 132186),
        ("Hull", 131237), ("Crew", 131235), ("Terror", 131232), ("Experience", 131234),
        ("Iron", 131139), ("Mirrors", 131141), ("Veils", 131140), ("Hearts", 131138),
    ]
    CARGO_CATEGORIES = {"Goods", "Contraband", "Hold item / passenger"}
    KEY_ORDER = ["EquippedPossession", "Name", "EffectiveLevel", "EffectiveLevelModifier", "Level", "AssociatedQuality"]

    def entry_id(self, e):
        aq = e.get("AssociatedQuality")
        return aq.get("Id") if isinstance(aq, dict) else None

    def get_level(self, e):
        return e.get("Level") or 0

    def _set_level_raw(self, e, level):
        # The game omits zero-valued keys, and EffectiveLevel = Level + EffectiveLevelModifier.
        modifier = e.get("EffectiveLevelModifier") or 0
        values = dict(e)
        values["Level"] = level
        values["EffectiveLevel"] = level + modifier
        self._rebuild(e, values)

    def _rebuild(self, e: dict, values: dict) -> None:
        ordered = {}
        for k in self.KEY_ORDER:
            if k in values and values[k] not in (0, None):
                ordered[k] = values[k]
        for k, v in values.items():  # anything we don't know about, kept as-is
            if k not in ordered and k not in self.KEY_ORDER:
                ordered[k] = v
        if "AssociatedQuality" in ordered:  # always last, as the game writes it
            ordered["AssociatedQuality"] = ordered.pop("AssociatedQuality")
        e.clear()
        e.update(ordered)

    def _new_entry(self, qid, level):
        e = {"AssociatedQuality": {"Tag": "", "Id": qid}}
        self._rebuild(e, {"EffectiveLevel": level, "Level": level, **e})
        return e

    def _clear_equipped(self, slot_entry):
        values = dict(slot_entry)
        values.pop("EquippedPossession", None)
        self._rebuild(slot_entry, values)

    def _set_equipped(self, slot_entry, item_copy):
        values = dict(slot_entry)
        values["EquippedPossession"] = item_copy
        self._rebuild(slot_entry, values)

    def _set_name(self, e, name):
        # _rebuild keeps "" (the game writes "Name":"" for some items) but drops None.
        values = dict(e)
        values["Name"] = name
        self._rebuild(e, values)

    def ship_slot_qid(self):
        return self.CURRENT_LOCOMOTIVE

    def remove(self, qid):
        super().remove(qid)
        for slot in self.data.get("Slots") or []:
            if slot.get("EquipmentQualityId") == qid:
                slot.pop("EquipmentQualityId", None)

    def equipment_slots(self):
        slots: list[EquipSlot] = []
        loco = self.find(self.CURRENT_LOCOMOTIVE)
        if loco is not None:
            ep = loco.get("EquippedPossession")
            slots.append(EquipSlot(("copy", self.CURRENT_LOCOMOTIVE), "Current Locomotive",
                                   self.entry_id(ep) if ep else None,
                                   self.catalog.where(lambda d: d.raw_category == 10000 and d.nature == "Thing"),
                                   "Swapping locomotives removes the old one."))
        for i, s in enumerate(self.data.get("Slots") or []):
            cat = s.get("Category")
            label = _skies_slot_label(cat, s.get("Type"))
            note = "" if s.get("Active") else "slot inactive"
            slots.append(EquipSlot(("slot", i), f"Slot {i + 1}: {label}", s.get("EquipmentQualityId"),
                                   self.catalog.where(lambda d, cat=cat: d.raw_category == cat), note))
        officers = self.catalog.where(lambda d: d.raw_category == 106)
        for role in self.OFFICER_ROLES:
            e = self.find(role)
            if e is None:
                continue
            ep = e.get("EquippedPossession")
            slots.append(EquipSlot(("copy", role), f"Officer: {self.define(role).name}",
                                   self.entry_id(ep) if ep else None, officers))
        return slots

    def equip(self, key, qid):
        kind, ref = key
        if kind == "copy":
            self._equip_copy(ref, qid, replaces_owned=(ref == self.CURRENT_LOCOMOTIVE))
            return
        slot = self.data["Slots"][ref]
        if qid is None:
            slot.pop("EquipmentQualityId", None)
        else:
            if (self.level_of(qid) or 0) < 1:
                self.set_quality(qid, 1)
            ordered = {}
            for k, v in slot.items():
                if k == "EquipmentQualityId":
                    continue
                ordered[k] = v
                if k == "Category":
                    ordered["EquipmentQualityId"] = qid
            ordered.setdefault("EquipmentQualityId", qid)
            slot.clear()
            slot.update(ordered)
        self.dirty = True

    def summary(self):
        snippet = self.path.parent / "saveSnippet.json"
        try:
            s = json.loads(snippet.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            s = {}
        bits = [f"Captain {s.get('Name') or self.data.get('Name') or '?'}"]
        if s.get("Location"):
            bits.append(f"at {s['Location']} ({s.get('Region', '')})".replace(" ()", ""))
        if s.get("LegacyMode"):
            bits.append(s["LegacyMode"].strip(" ()"))
        return ", ".join(bits)


def _skies_slot_label(category, slot_type) -> str:
    label = SKIES_CATEGORIES.get(category, f"Category {category}").replace("Equipment: ", "")
    return f"{label} (type {slot_type})" if slot_type is not None else label
