"""Locate Sunless Sea / Sunless Skies save files and game data on disk."""
from __future__ import annotations

import json
import os
import string
import sys
from dataclasses import dataclass
from pathlib import Path

SEA = "sea"
SKIES = "skies"
GAME_TITLES = {SEA: "Sunless Sea", SKIES: "Sunless Skies"}


def user_data_root() -> Path | None:
    """Folder Unity uses for Failbetter's per-user data."""
    if sys.platform == "win32":
        base = os.environ.get("USERPROFILE")
        return Path(base, "AppData", "LocalLow", "Failbetter Games") if base else None
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"  # folders are "unity.Failbetter Games.<Game>"
    return Path.home() / ".config" / "unity3d" / "Failbetter Games"


def game_user_dir(game: str) -> Path | None:
    root = user_data_root()
    if root is None:
        return None
    if sys.platform == "darwin":
        return root / f"unity.Failbetter Games.{GAME_TITLES[game]}"
    return root / GAME_TITLES[game]


def backup_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "SunlessSaveEditor" / "backups"


@dataclass
class SaveEntry:
    game: str
    path: Path
    label: str


def find_saves() -> list[SaveEntry]:
    """All save files we can find for both games, newest first."""
    found: list[SaveEntry] = []

    sea = game_user_dir(SEA)
    if sea and (sea / "saves").is_dir():
        for f in (sea / "saves").glob("*.json"):
            found.append(SaveEntry(SEA, f, f"Sea — {f.stem}"))

    skies = game_user_dir(SKIES)
    repo = skies / "storage" / "characterrepository" if skies else None
    if repo and repo.is_dir():
        for lineage in repo.iterdir():
            snippet = _read_snippet(lineage / "saveSnippet.json")
            for f in lineage.glob("*.json"):
                if f.name == "saveSnippet.json":
                    continue
                label = f"Skies — {lineage.name}/{f.stem}"
                if snippet:
                    label += f" ({snippet})"
                found.append(SaveEntry(SKIES, f, label))

    found.sort(key=lambda e: e.path.stat().st_mtime, reverse=True)
    return found


def _read_snippet(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return ", ".join(str(data[k]) for k in ("Name", "Location") if data.get(k))


def sea_qualities_file() -> Path | None:
    d = game_user_dir(SEA)
    f = d / "entities" / "qualities.json" if d else None
    return f if f and f.is_file() else None


def skies_qualities_files() -> list[Path]:
    """Candidate qualities.bytes files, most authoritative first (game install, then cache)."""
    files = [install / "Sunless Skies_Data" / "StreamingAssets" / "BuildInStorage" / "data" / "qualities.bytes"
             for install in _skies_install_dirs()]
    d = game_user_dir(SKIES)
    if d:
        files.append(d / "storage" / "data" / "qualities.bytes")
    seen, result = set(), []
    for f in files:
        if f.is_file() and f.resolve() not in seen:
            seen.add(f.resolve())
            result.append(f)
    return result


def _skies_install_dirs() -> list[Path]:
    candidates: list[Path] = []
    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:/")
            if not drive.exists():
                continue
            for sub in ("GOG Games", "Program Files (x86)/GOG Galaxy/Games", "Program Files (x86)/Steam/steamapps/common",
                        "Program Files/Steam/steamapps/common", "SteamLibrary/steamapps/common", "Steam/steamapps/common"):
                candidates.append(drive / sub / "Sunless Skies")
    else:
        home = Path.home()
        candidates += [home / ".steam/steam/steamapps/common/Sunless Skies",
                       home / ".local/share/Steam/steamapps/common/Sunless Skies",
                       home / "Library/Application Support/Steam/steamapps/common/Sunless Skies"]
    # The game's Player.log records its data path, which catches unusual install locations.
    d = game_user_dir(SKIES)
    if d:
        for log in ("Player.log", "Player-prev.log"):
            try:
                with open(d / log, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if "Sunless Skies_Data" in line and ":/" in line:
                            start = line.find(":/") - 1
                            candidates.append(Path(line[start:line.find("Sunless Skies_Data")]))
                            break
            except OSError:
                pass
    return [c for c in candidates if c.is_dir()]
