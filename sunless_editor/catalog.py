"""Quality definitions (id -> name, category, nature) for both games."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .skies_bytes import read_qualities


@dataclass
class QualityDef:
    id: int
    name: str
    category: str          # human-readable category label
    nature: str            # "Status", "Thing" or "Other"
    raw_category: object = None   # Sea: category string; Skies: category number
    slot_id: int | None = None    # Sea: id of the slot quality this item is equipped in
    known: bool = True

    def label(self) -> str:
        return f"{self.name}  [#{self.id}]"


def unknown(qid: int) -> QualityDef:
    return QualityDef(qid, f"Unknown #{qid}", "Unknown", "Other", known=False)


class Catalog:
    def __init__(self, defs: dict[int, QualityDef], source: str):
        self.defs = defs
        self.source = source

    def get(self, qid: int) -> QualityDef:
        return self.defs.get(qid) or unknown(qid)

    def __len__(self) -> int:
        return len(self.defs)

    def where(self, pred) -> list[QualityDef]:
        return sorted((d for d in self.defs.values() if pred(d)), key=lambda d: d.name.lower())

    def categories(self) -> list[str]:
        return sorted({d.category for d in self.defs.values()})


# ---------------------------------------------------------------- Sunless Sea

def load_sea_catalog(path: Path | None = None) -> Catalog:
    path = path or paths.sea_qualities_file()
    if not path:
        return Catalog({}, "Sunless Sea qualities.json not found — names unavailable")
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    defs: dict[int, QualityDef] = {}
    for d in raw:
        try:
            qid = int(d["Id"])
        except (KeyError, TypeError, ValueError):
            continue
        slot = d.get("AssignToSlot")
        defs[qid] = QualityDef(
            id=qid,
            name=(d.get("Name") or f"#{qid}").strip(),
            category=d.get("Category") or "Unspecified",
            nature=d.get("Nature") or "Other",
            raw_category=d.get("Category"),
            slot_id=int(slot["Id"]) if isinstance(slot, dict) and slot.get("Id") is not None else None,
        )
    return Catalog(defs, str(path))


# ---------------------------------------------------------------- Sunless Skies

SKIES_NATURES = {1: "Status", 2: "Thing"}

# Labels for Skies' numeric categories, worked out from the names in each category.
# Entries marked "?" are educated guesses.
SKIES_CATEGORIES = {
    0: "Unspecified",
    1: "Core",
    106: "Officer",
    150: "Hold item / passenger",
    200: "Goods",
    1000: "Ship stat",
    2000: "Luck",
    5000: "Circumstance?",
    5050: "Story?",
    5200: "Progress?",
    5500: "Patience?",
    6661: "Hidden",
    10000: "Locomotive",
    13999: "Timer?",
    18000: "Contraband",
    33000: "Attribute",
    34000: "Status/Reputation",
    35000: "Story",
    36000: "Accomplishment?",
    37000: "Derived",
    40000: "Venture?",
    60000: "Companion?",
    70004: "Equipment: Auxiliary?",
    70005: "Equipment: Plating/Fittings?",
    70006: "Equipment: Cabin?",
    70007: "Equipment: Weapon",
    70008: "Equipment: Weapon (heavy)?",
    70009: "Equipment: Scout",
    70010: "Equipment: Engine",
}


def load_skies_catalog(files: list[Path] | None = None) -> Catalog:
    files = paths.skies_qualities_files() if files is None else files
    if not files:
        return Catalog({}, "Sunless Skies qualities.bytes not found — names unavailable")
    defs: dict[int, QualityDef] = {}
    # Later files only fill gaps, so the first (game install) copy wins.
    for f in files:
        for rec in read_qualities(f).values():
            if rec.id in defs:
                continue
            defs[rec.id] = QualityDef(
                id=rec.id,
                name=rec.name.strip() or f"#{rec.id}",
                category=SKIES_CATEGORIES.get(rec.category, f"Category {rec.category}"),
                nature=SKIES_NATURES.get(rec.nature, "Other"),
                raw_category=rec.category,
            )
    return Catalog(defs, " + ".join(str(f) for f in files))
