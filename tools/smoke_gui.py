"""Drive the real GUI against temp copies of the saves on this machine.

For each detected save: load it, screenshot every tab, edit a resource, equip an item, save,
reload and check the edit stuck. Real saves are never modified; backups go to a temp folder.

    python tools/smoke_gui.py [screenshot_dir]

Screenshots use PowerShell/System.Drawing, so they only work on Windows (skipped elsewhere).
"""
import ctypes
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunless_editor import gui, paths, saves  # noqa: E402


def grab(box, path):
    if sys.platform != "win32":
        return
    x1, y1, x2, y2 = box
    ps = (f"Add-Type -AssemblyName System.Drawing; $b=New-Object System.Drawing.Bitmap({x2 - x1},{y2 - y1}); "
          f"$g=[System.Drawing.Graphics]::FromImage($b); $g.CopyFromScreen({x1},{y1},0,0,$b.Size); $b.Save('{path}')")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def main():
    shots = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    mock.patch.object(paths, "backup_dir", return_value=tmp / "backups").start()
    mock.patch.object(gui.messagebox, "askyesno", return_value=True).start()
    if sys.platform == "win32":
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # so screenshot coordinates match
    app = gui.App()
    app.geometry("1100x720+20+20")
    try:
        for e in paths.find_saves():
            if e.path.name.startswith("autosave_backup") or "fallback" in e.path.name:
                continue
            copy = tmp / e.game / e.path.parent.name / e.path.name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(e.path, copy)
            snippet = e.path.parent / "saveSnippet.json"
            if snippet.exists():
                shutil.copy2(snippet, copy.parent / snippet.name)

            app.load(copy)
            s = app.save
            tag = f"{e.game}-{e.path.parent.name}"
            if shots:
                app.attributes("-topmost", True)
                for i in range(len(app.tab_list)):
                    app.tabs.select(i)
                    app.update()
                    x, y = app.winfo_rootx(), app.winfo_rooty()
                    grab((x, y, x + app.winfo_width(), y + app.winfo_height()), shots / f"{tag}-{i}.png")

            qid = s.CORE[0][1]
            app.resources.rows[0][1].set("12345")
            app.update()
            assert s.level_of(qid) == 12345
            slot = next(sl for sl in s.equipment_slots() if sl.candidates and sl.key != s.ship_slot_qid()
                        and not str(sl.label).startswith(("Officer", "Current")))
            app.equipment._equip(slot, slot.candidates[-1].id)
            app.update()
            app.save_file()
            app.update()
            assert saves.load_save(copy).level_of(qid) == 12345
            print(f"{tag}: OK — {s.summary()}")
    finally:
        if app.save:
            app.save.dirty = False
        app.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
