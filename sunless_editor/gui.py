"""Tkinter user interface."""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, paths, saves
from .catalog import QualityDef

EMPTY_CHOICE = "(empty)"


class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame; put widgets in ``.inner``."""

    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        w = self.winfo_containing(event.x_root, event.y_root)
        while w is not None:
            if w is self:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            w = w.master


# ------------------------------------------------------------------ dialogs

class AddQualityDialog(tk.Toplevel):
    """Pick a quality from a searchable list (or type a numeric id) and a level."""

    def __init__(self, master, title: str, candidates: list[QualityDef], allow_raw_id: bool):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result: tuple[int, int] | None = None
        self.candidates = candidates
        self.allow_raw_id = allow_raw_id

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        hint = "Search by name" + (" or type a quality ID" if allow_raw_id else "")
        ttk.Label(frm, text=hint).pack(anchor="w")
        self.search = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=self.search, width=60)
        entry.pack(fill="x", pady=(2, 6))
        self.search.trace_add("write", lambda *_: self._filter())

        box = ttk.Frame(frm)
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(box, height=18, activestyle="dotbox", exportselection=False)
        sb = ttk.Scrollbar(box, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<Double-Button-1>", lambda e: self._ok())

        row = ttk.Frame(frm)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Level:").pack(side="left")
        self.level = tk.StringVar(value="1")
        ttk.Spinbox(row, from_=0, to=10_000_000, textvariable=self.level, width=10).pack(side="left", padx=4)
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(row, text="Add", command=self._ok).pack(side="right", padx=4)

        self.shown: list[QualityDef] = []
        self._filter()
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        entry.focus_set()
        self.grab_set()

    def _filter(self):
        text = self.search.get().strip().lower()
        self.shown = [d for d in self.candidates
                      if not text or text in d.name.lower() or text == str(d.id)][:2000]
        self.listbox.delete(0, "end")
        for d in self.shown:
            self.listbox.insert("end", f"{d.name}   —  {d.category}  #{d.id}")
        if self.shown:
            self.listbox.selection_set(0)

    def _ok(self):
        try:
            level = int(self.level.get())
        except ValueError:
            messagebox.showerror("Add", "Level must be a whole number.", parent=self)
            return
        sel = self.listbox.curselection()
        if sel:
            qid = self.shown[sel[0]].id
        elif self.allow_raw_id and self.search.get().strip().isdigit():
            qid = int(self.search.get().strip())
        else:
            return
        self.result = (qid, level)
        self.destroy()


# --------------------------------------------------------------------- tabs

class ResourcesTab(ttk.Frame):
    def __init__(self, master, app: "App"):
        super().__init__(master, padding=12)
        self.app = app
        self.rows: list[tuple[int, tk.StringVar, ttk.Label]] = []
        self._loading = False

    def build(self):
        for w in self.winfo_children():
            w.destroy()
        self.rows.clear()
        s = self.app.save
        ttk.Label(self, text="Edit a value and it is applied immediately. Save with Ctrl+S.",
                  foreground="gray").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        for i, (label, qid) in enumerate(s.CORE, start=1):
            ttk.Label(self, text=label, width=14).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            ttk.Spinbox(self, from_=0, to=10_000_000, textvariable=var, width=12).grid(row=i, column=1, sticky="w")
            note = ttk.Label(self, foreground="gray")
            note.grid(row=i, column=2, sticky="w", padx=8)
            var.trace_add("write", lambda *_, q=qid, v=var: self._changed(q, v))
            self.rows.append((qid, var, note))
        self.refresh()

    def refresh(self):
        self._loading = True
        for qid, var, note in self.rows:
            level = self.app.save.level_of(qid)
            var.set(str(level or 0))
            note.configure(text="" if level is not None else "not in save yet — setting a value adds it")
        self._loading = False

    def _changed(self, qid, var):
        if self._loading:
            return
        try:
            value = int(var.get())
        except ValueError:
            return
        s = self.app.save
        if (s.level_of(qid) or 0) != value:
            s.set_quality(qid, value)
            self.app.changed(source=self)


class QualityTableTab(ttk.Frame):
    """Filterable table of possessed qualities with level editing, add and remove."""

    COLUMNS = (("name", "Name", 360), ("category", "Category", 170), ("level", "Level", 80), ("id", "ID", 80))

    def __init__(self, master, app: "App", include, add_candidates, allow_raw_id: bool):
        super().__init__(master, padding=8)
        self.app = app
        self.include = include                # (save, QualityDef) -> bool
        self.add_candidates = add_candidates  # (save) -> list[QualityDef]
        self.allow_raw_id = allow_raw_id
        self.sort_col, self.sort_rev = "name", False

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Filter:").pack(side="left")
        self.filter = tk.StringVar()
        ttk.Entry(top, textvariable=self.filter, width=30).pack(side="left", padx=4)
        self.filter.trace_add("write", lambda *_: self.refresh())
        ttk.Label(top, text="Category:").pack(side="left", padx=(12, 0))
        self.category = ttk.Combobox(top, state="readonly", width=26)
        self.category.pack(side="left", padx=4)
        self.category.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.count = ttk.Label(top, foreground="gray")
        self.count.pack(side="right")

        box = ttk.Frame(self)
        box.pack(fill="both", expand=True, pady=6)
        self.tree = ttk.Treeview(box, columns=[c[0] for c in self.COLUMNS], show="headings", selectmode="browse")
        for key, text, width in self.COLUMNS:
            self.tree.heading(key, text=text, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=width, stretch=(key == "name"),
                             anchor="e" if key in ("level", "id") else "w")
        sb = ttk.Scrollbar(box, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._selected())
        self.tree.bind("<Double-Button-1>", lambda e: (self.level_box.focus_set(), self.level_box.selection_range(0, "end")))

        bottom = ttk.Frame(self)
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Level:").pack(side="left")
        self.level = tk.StringVar()
        self.level_box = ttk.Spinbox(bottom, from_=0, to=10_000_000, textvariable=self.level, width=12)
        self.level_box.pack(side="left", padx=4)
        self.level_box.bind("<Return>", lambda e: self._apply_level())
        ttk.Button(bottom, text="Set level", command=self._apply_level).pack(side="left")
        ttk.Button(bottom, text="Remove", command=self._remove).pack(side="right")
        ttk.Button(bottom, text="Add…", command=self._add).pack(side="right", padx=4)

    def build(self):
        self.filter.set("")
        self.refresh()

    def _rows(self):
        s = self.app.save
        rows = []
        for e in s.entries():
            d = s.define(s.entry_id(e))
            if self.include(s, d):
                rows.append((d, s.get_level(e)))
        return rows

    def refresh(self):
        s = self.app.save
        if s is None:
            return
        rows = self._rows()
        cats = sorted({d.category for d, _ in rows})
        self.category.configure(values=["All"] + cats)
        if self.category.get() not in cats:
            self.category.set("All")
        text = self.filter.get().strip().lower()
        cat = self.category.get()
        rows = [(d, lvl) for d, lvl in rows
                if (cat == "All" or d.category == cat) and (not text or text in d.name.lower() or text == str(d.id))]
        keyf = {"name": lambda r: r[0].name.lower(), "category": lambda r: r[0].category,
                "level": lambda r: r[1], "id": lambda r: r[0].id}[self.sort_col]
        rows.sort(key=keyf, reverse=self.sort_rev)
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for d, lvl in rows:
            self.tree.insert("", "end", iid=str(d.id), values=(d.name, d.category, lvl, d.id))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
            self.tree.see(selected[0])
        self.count.configure(text=f"{len(rows)} shown")

    def _sort(self, col):
        self.sort_rev = not self.sort_rev if self.sort_col == col else False
        self.sort_col = col
        self.refresh()

    def _selected_id(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _selected(self):
        qid = self._selected_id()
        if qid is not None:
            self.level.set(str(self.app.save.level_of(qid) or 0))

    def _apply_level(self):
        qid = self._selected_id()
        if qid is None:
            return
        try:
            value = int(self.level.get())
        except ValueError:
            messagebox.showerror("Set level", "Level must be a whole number.")
            return
        self.app.save.set_quality(qid, value)
        self.app.changed()

    def _add(self):
        s = self.app.save
        dlg = AddQualityDialog(self, "Add quality", self.add_candidates(s), self.allow_raw_id)
        self.wait_window(dlg)
        if dlg.result:
            qid, level = dlg.result
            s.add(qid, level)
            self.app.changed()
            if self.tree.exists(str(qid)):
                self.tree.selection_set(str(qid))
                self.tree.see(str(qid))

    def _remove(self):
        qid = self._selected_id()
        if qid is None:
            return
        name = self.app.save.define(qid).name
        if messagebox.askyesno("Remove", f"Remove “{name}” from this save?"):
            self.app.save.remove(qid)
            self.app.changed()


class EquipmentTab(ttk.Frame):
    def __init__(self, master, app: "App"):
        super().__init__(master, padding=8)
        self.app = app
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)

    def build(self):
        self.refresh()

    def refresh(self):
        s = self.app.save
        f = self.scroll.inner
        for w in f.winfo_children():
            w.destroy()

        ttk.Label(f, text="Ship name:" if s.game == paths.SEA else "Locomotive name:").grid(row=0, column=0, sticky="w", pady=4)
        name = tk.StringVar(value=s.ship_name())
        entry = ttk.Entry(f, textvariable=name, width=40)
        entry.grid(row=0, column=1, sticky="w")

        def apply_name(*_):
            if name.get() != s.ship_name():
                s.set_ship_name(name.get())
                self.app.changed(source=self)
        entry.bind("<FocusOut>", apply_name)
        entry.bind("<Return>", apply_name)

        for row, slot in enumerate(s.equipment_slots(), start=1):
            ttk.Label(f, text=slot.label).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 8))
            choices = [EMPTY_CHOICE] + [d.label() for d in slot.candidates]
            ids = [None] + [d.id for d in slot.candidates]
            if slot.current is not None and slot.current not in ids:
                choices.append(s.define(slot.current).label())
                ids.append(slot.current)
            box = ttk.Combobox(f, values=choices, state="readonly", width=60)
            box.current(ids.index(slot.current))
            box.grid(row=row, column=1, sticky="w")
            box.bind("<<ComboboxSelected>>", lambda e, b=box, i=ids, sl=slot: self._equip(sl, i[b.current()]))
            if slot.note:
                ttk.Label(f, text=slot.note, foreground="gray").grid(row=row, column=2, sticky="w", padx=8)

        help_text = ("Equipping an item also adds it to your possessions if needed. Unequipped items stay in "
                     "your hold, except ships/locomotives, which are replaced.")
        ttk.Label(f, text=help_text, foreground="gray", wraplength=700).grid(
            row=999, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def _equip(self, slot, qid):
        try:
            self.app.save.equip(slot.key, qid)
        except KeyError as exc:
            messagebox.showerror("Equip", str(exc))
        self.app.changed()


# ---------------------------------------------------------------------- app

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Sunless Save Editor {__version__}")
        self.geometry("980x680")
        self.minsize(760, 480)
        self.save: saves.GameSave | None = None
        self.detected: list[paths.SaveEntry] = []

        self._build_menu()
        top = ttk.Frame(self, padding=(8, 8, 8, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Save:").pack(side="left")
        self.picker = ttk.Combobox(top, state="readonly", width=80)
        self.picker.pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(top, text="Load", command=self._load_picked).pack(side="left")
        ttk.Button(top, text="Browse…", command=self.open_dialog).pack(side="left", padx=(4, 0))

        self.info = ttk.Label(self, padding=(8, 6), font=("Segoe UI", 10, "bold"))
        self.info.pack(fill="x")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8)
        self.resources = ResourcesTab(self.tabs, self)
        self.cargo = QualityTableTab(self.tabs, self,
                                     include=lambda s, d: s.is_cargo(d),
                                     add_candidates=lambda s: s.catalog.where(s.is_cargo),
                                     allow_raw_id=False)
        self.equipment = EquipmentTab(self.tabs, self)
        self.everything = QualityTableTab(self.tabs, self,
                                          include=lambda s, d: True,
                                          add_candidates=lambda s: s.catalog.where(lambda d: True),
                                          allow_raw_id=True)
        self.tab_list = [(self.resources, "Resources"), (self.cargo, "Cargo & items"),
                         (self.equipment, "Ship & equipment"), (self.everything, "All qualities")]

        self.status = ttk.Label(self, padding=(8, 4), foreground="gray")
        self.status.pack(fill="x")

        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.bind_all("<Control-s>", lambda e: self.save_file())
        self.bind_all("<Control-o>", lambda e: self.open_dialog())
        self.refresh_detected()
        self._set_status("Pick a save above. Close the game (or return to its main menu) before saving.")

    # --- menu / file handling ------------------------------------------------
    def _build_menu(self):
        bar = tk.Menu(self)
        m = tk.Menu(bar, tearoff=False)
        m.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_dialog)
        m.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        m.add_command(label="Save As…", command=self.save_as)
        m.add_command(label="Reload from disk", command=self.reload)
        m.add_separator()
        m.add_command(label="Rescan for saves", command=self.refresh_detected)
        m.add_command(label="Open backups folder", command=self.open_backups)
        m.add_separator()
        m.add_command(label="Exit", command=self.quit_app)
        bar.add_cascade(label="File", menu=m)
        self.configure(menu=bar)

    def refresh_detected(self):
        self.detected = paths.find_saves()
        self.picker.configure(values=[e.label for e in self.detected])
        if self.detected and not self.picker.get():
            self.picker.current(0)

    def _load_picked(self):
        i = self.picker.current()
        if i >= 0:
            self.load(self.detected[i].path)

    def open_dialog(self):
        start = None
        if self.save:
            start = self.save.path.parent
        elif self.detected:
            start = self.detected[0].path.parent
        f = filedialog.askopenfilename(title="Open save", initialdir=start,
                                       filetypes=[("Save files", "*.json"), ("All files", "*.*")])
        if f:
            self.load(Path(f))

    def _confirm_discard(self) -> bool:
        if self.save and self.save.dirty:
            return messagebox.askyesno("Unsaved changes", "Discard unsaved changes?")
        return True

    def load(self, path: Path):
        if not self._confirm_discard():
            return
        self._set_status(f"Loading {path} …")
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.save = saves.load_save(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Open", f"Couldn't open {path}:\n{exc}")
            self._set_status("")
            return
        finally:
            self.config(cursor="")
        for tab, _ in self.tab_list:
            if str(tab) not in self.tabs.tabs():
                self.tabs.add(tab, text=_)
            tab.build()
        match = [i for i, e in enumerate(self.detected) if e.path.resolve() == Path(path).resolve()]
        if match:
            self.picker.current(match[0])
        else:
            self.picker.set(str(path))
        cat = self.save.catalog
        catalog_note = f"{len(cat)} quality names loaded" if len(cat) else cat.source
        self._set_status(f"Loaded {path}  ·  {catalog_note}")
        self._update_title()

    def reload(self):
        if self.save:
            path = self.save.path
            if self._confirm_discard():
                self.save.dirty = False
                self.load(path)

    def save_file(self):
        if not self.save:
            return
        self._write(self.save.path)

    def save_as(self):
        if not self.save:
            return
        f = filedialog.asksaveasfilename(title="Save as", initialdir=self.save.path.parent,
                                         initialfile=self.save.path.name, defaultextension=".json",
                                         filetypes=[("Save files", "*.json")])
        if f:
            self._write(Path(f))

    def _write(self, path: Path):
        self.focus_set()  # commit any half-typed field (FocusOut handlers)
        self.update_idletasks()
        if saves.game_running(self.save.game) and not messagebox.askyesno(
                "Game is running",
                f"{self.save.title} appears to be running. It may overwrite this save or ignore the change.\n\n"
                "It's safest to quit the game first. Save anyway?"):
            return
        try:
            backup = self.save.write(path)
        except OSError as exc:
            messagebox.showerror("Save", f"Couldn't save:\n{exc}")
            return
        msg = f"Saved {path}"
        if backup:
            msg += f"  ·  backup: {backup}"
        self._set_status(msg)
        self._update_title()

    def open_backups(self):
        folder = paths.backup_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])

    def quit_app(self):
        if self._confirm_discard():
            self.destroy()

    # --- change propagation --------------------------------------------------
    def changed(self, source=None):
        """Something in the save changed: refresh every tab except the one being typed in."""
        for tab, _ in self.tab_list:
            if tab is not source:
                tab.refresh()
        self._update_title()

    def _update_title(self):
        if not self.save:
            return
        star = "• " if self.save.dirty else ""
        self.title(f"{star}{self.save.path.name} — {self.save.title} — Sunless Save Editor {__version__}")
        self.info.configure(text=f"{self.save.title}:  {self.save.summary()}"
                                 + ("   (unsaved changes)" if self.save.dirty else ""))

    def _set_status(self, text: str):
        self.status.configure(text=text)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    App().mainloop()
