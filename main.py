"""
main.py
-------
HS Code Checker - Desktop App (standard layout)

  1. Search a single HS code, OR
  2. Import a CSV/TXT list of HS codes, OR
  3. Scan a PDF / Excel / Word / image, review the codes found, and search them.
Results appear in a table; double-click a row for full detail.
A CBM calculator is available from the Tools menu.

Run with:  python main.py        Package with build.bat
"""

import csv
import os
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from cbm import CbmCalculator
from hs_lookup import search_many, get_full_detail, HSCodeItem, FullDetail
from extractor import (
    extract_candidates, ExtractionError, ExtractionResult, FILETYPES,
)
from theme import (
    apply_theme, set_app_icon, center_on, MUTED, ERROR, OK, WARN, ROW_ALT,
)

APP_TITLE = "HS Code Checker"

RESULT_MODE_LABELS = [
    ("Auto: all matches for a 4-digit code, first match for 6+ digits", "auto"),
    ("First match only", "first"),
    ("All matches", "all"),
]

COLUMNS = [
    ("hs_code", "HS Code", 120, False),
    ("found", "Status", 80, False),
    ("description_en", "Description", 300, True),
    ("uom", "Unit", 55, False),
    ("ad_valorem_rate", "Duty Rate", 75, False),
    ("approval_agencies", "Approval / Other Government Agency", 300, True),
    ("error", "Notes", 180, False),
]


def _clean_code(text: str) -> str:
    """'8517.69.90' / '8517 69 90' -> '85176990'; anything else is left as typed."""
    stripped = re.sub(r"[\s.\-]", "", text)
    return stripped if stripped.isdigit() else text


def _row_values(r: HSCodeItem):
    return (r.hs_code or r.query, "Found" if r.found else "Not found", r.description_en,
            r.uom, r.ad_valorem_rate, r.approval_agencies, r.error or r.note or "")


# ===========================================================================
# Review dialog (after scanning a document)
# ===========================================================================
class ReviewDialog(tk.Toplevel):
    ON, OFF = "\u2611", "\u2610"

    def __init__(self, parent, result: ExtractionResult, on_confirm):
        super().__init__(parent)
        self.on_confirm = on_confirm
        self.checked = {}
        self.title(f"Review HS codes - {result.source_name}")
        self.minsize(700, 400)
        self.transient(parent)
        center_on(self, parent, 880, 540)

        head = ttk.Frame(self, padding=(12, 10, 12, 0))
        head.pack(fill="x")
        ttk.Label(head, style="Bold.TLabel", text=(
            f"Found {len(result.candidates)} possible HS code(s). Untick anything "
            "that isn't an HS code, then click Search.")).pack(anchor="w")
        ttk.Label(head, style="Muted.TLabel", wraplength=830, text=(
            "High = next to an 'HS Code' label or column.  Medium = looks like a code.  "
            "Low = could be an invoice / phone / quantity number (unticked by default).")
        ).pack(anchor="w", pady=(4, 0))
        for w in result.warnings:
            ttk.Label(head, text="\u26a0 " + w, wraplength=830, foreground=WARN).pack(
                anchor="w", pady=(4, 0))

        bottom = ttk.Frame(self, padding=12)
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="Select all", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(bottom, text="Select none", command=lambda: self._set_all(False)).pack(
            side="left", padx=(6, 0))
        ttk.Button(bottom, text="High confidence only", command=self._only_high).pack(
            side="left", padx=(6, 0))
        self.search_btn = ttk.Button(bottom, command=self._confirm)
        self.search_btn.pack(side="right")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))

        body = ttk.Frame(self, padding=(12, 10, 12, 0))
        body.pack(fill="both", expand=True)
        cols = ("use", "code", "confidence", "source", "context")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for cid, text, width, anchor in (
            ("use", "Use", 45, "center"), ("code", "HS Code", 130, "w"),
            ("confidence", "Confidence", 85, "w"), ("source", "Found in", 110, "w"),
            ("context", "Where it appeared", 430, "w"),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, anchor=anchor, stretch=(cid == "context"))
        self.tree.tag_configure("low", foreground="#888888")
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        for c in result.candidates:
            on = c.confidence in ("High", "Medium")
            item = self.tree.insert(
                "", "end", tags=(("low",) if c.confidence == "Low" else ()),
                values=(self.ON if on else self.OFF, c.code, c.confidence, c.source, c.context))
            self.checked[item] = on

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self._refresh_count()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _set_item(self, item, on):
        self.checked[item] = on
        self.tree.set(item, "use", self.ON if on else self.OFF)

    def _set_all(self, on):
        for item in self.checked:
            self._set_item(item, on)
        self._refresh_count()

    def _only_high(self):
        for item in self.checked:
            self._set_item(item, self.tree.set(item, "confidence") == "High")
        self._refresh_count()

    def _on_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        if item:
            self._set_item(item, not self.checked[item])
            self._refresh_count()

    def _on_space(self, event):
        for item in self.tree.selection():
            self._set_item(item, not self.checked[item])
        self._refresh_count()

    def _refresh_count(self):
        self.search_btn.configure(text=f"Search {sum(self.checked.values())} selected code(s)")

    def _confirm(self):
        codes = [self.tree.set(i, "code") for i, on in self.checked.items() if on]
        if not codes:
            messagebox.showinfo(APP_TITLE, "Tick at least one code to search.", parent=self)
            return
        self.destroy()
        self.on_confirm(codes)


# ===========================================================================
# Detail window
# ===========================================================================
class DetailWindow(tk.Toplevel):
    def __init__(self, parent, hs_code):
        super().__init__(parent)
        self.title(f"HS Code Detail - {hs_code}")
        self.minsize(560, 420)
        self.transient(parent)
        center_on(self, parent, 720, 620)

        bottom = ttk.Frame(self, padding=10)
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="Close", command=self.destroy).pack(side="right")
        self.copy_btn = ttk.Button(bottom, text="Copy to clipboard", command=self._copy,
                                   state="disabled")
        self.copy_btn.pack(side="right", padx=(0, 8))

        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        ttk.Label(self.body, text="Loading full detail...", padding=20).pack(anchor="nw")
        self._plain = ""

    def populate(self, d: FullDetail):
        for child in self.body.winfo_children():
            child.destroy()
        if not d.found:
            ttk.Label(self.body, text=f"Could not load detail: {d.error}", padding=20,
                      foreground=ERROR, wraplength=660).pack(anchor="nw")
            return
        try:
            self._render(d)
            self.copy_btn.configure(state="normal")
        except Exception as e:
            for child in self.body.winfo_children():
                child.destroy()
            ttk.Label(self.body, text=f"Could not display detail (internal error): {e}",
                      padding=20, foreground=ERROR, wraplength=660).pack(anchor="nw")

    def _render(self, d: FullDetail):
        text = tk.Text(self.body, wrap="word", padx=14, pady=12, relief="flat", bd=0,
                       font="TkDefaultFont", spacing3=2, background="white")
        vsb = ttk.Scrollbar(self.body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        text.tag_configure("h1", font=("TkDefaultFont", 14, "bold"))
        text.tag_configure("h2", font=("TkDefaultFont", 11, "bold"), spacing1=14, spacing3=4)
        text.tag_configure("label", font=("TkDefaultFont", 9, "bold"))
        text.tag_configure("ok", foreground=OK, font=("TkDefaultFont", 9, "bold"))
        text.tag_configure("warn", foreground=WARN, font=("TkDefaultFont", 9, "bold"))
        text.tag_configure("muted", foreground=MUTED)

        plain = []

        def line(s="", tag=None):
            text.insert("end", s + "\n", tag) if tag else text.insert("end", s + "\n")
            plain.append(s)

        def kv(label_, value):
            if not value and value != 0:
                return
            text.insert("end", f"{label_}: ", "label")
            text.insert("end", f"{value}\n")
            plain.append(f"{label_}: {value}")

        line(f"HS Code {d.hs_code}", "h1")
        if d.final_description:
            line(d.final_description)
        line("Classification", "h2")
        kv("Chapter", f"{d.chapter_code} - {d.chapter_desc}")
        kv("Heading", f"{d.heading_code} - {d.heading_desc}")
        kv("Subheading", f"{d.subheading_code} - {d.subheading_desc}")
        kv("GCC Subheading", f"{d.subheading2_code} - {d.subheading2_desc}")
        kv("Local Subheading 1", f"{d.local1_code} - {d.local1_desc}")
        kv("Local Subheading 2", f"{d.local2_code} - {d.local2_desc}")

        line("Duty and valuation", "h2")
        kv("Valuation Type", d.valuation_type)
        kv("Duty Rate", d.rate or "0 / Not set")
        kv("Protection Duty Rate", d.protection_rate or "0 / Not set")
        kv("Status", d.hs_status)

        line("Other Government Agency Approval", "h2")
        if not d.agencies:
            line("No approval required from other agency (standard clearance).", "ok")
        else:
            line("Approval required from:", "warn")
            for a in d.agencies:
                line()
                text.insert("end", f"\u2022 {a.name_en}\n", "label")
                plain.append(f"* {a.name_en}")
                if a.name_ar:
                    line(f"   {a.name_ar}", "muted")
                if a.website:
                    line(f"   Website: {a.website}")
                if a.documents:
                    line("   Required documents:")
                    for doc in a.documents:
                        line(f"     - {doc}")
                else:
                    line("   (No specific document list returned by the portal.)", "muted")

        text.configure(state="disabled")
        self._plain = "\n".join(plain)

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self._plain)
        self.copy_btn.configure(text="Copied")
        self.after(2000, lambda: self.copy_btn.winfo_exists() and
                   self.copy_btn.configure(text="Copy to clipboard"))


# ===========================================================================
# Main window
# ===========================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        apply_theme(self)
        self.title(APP_TITLE)
        set_app_icon(self)
        self.geometry("1060x640")
        self.minsize(860, 500)

        self.results: list[HSCodeItem] = []
        self._item_by_iid = {}
        self._busy = False

        self._build_menu()
        self._build_status_bar()
        self._build_search()
        self._build_table()

        self.bind("<Control-o>", lambda e: self.on_import_file())
        self.bind("<Control-e>", lambda e: self.on_export())
        self.bind("<Control-l>", lambda e: self.entry.focus_set())
        self.entry.focus_set()

    # ------------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Import list (CSV / TXT)...", accelerator="Ctrl+O",
                          command=self.on_import_file)
        filem.add_command(label="Scan document (PDF / Excel / Image)...",
                          command=self.on_import_document)
        filem.add_separator()
        filem.add_command(label="Export results to CSV...", accelerator="Ctrl+E",
                          command=self.on_export)
        filem.add_separator()
        filem.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filem)

        edit = tk.Menu(menubar, tearoff=0)
        edit.add_command(label="Clear results", command=self.clear_results)
        menubar.add_cascade(label="Edit", menu=edit)

        tools = tk.Menu(menubar, tearoff=0)
        tools.add_command(label="CBM Calculator...", command=self.on_cbm)
        menubar.add_cascade(label="Tools", menu=tools)

        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="About", command=lambda: messagebox.showinfo(
            APP_TITLE,
            "HS Code Checker\n\nLooks up HS codes, duty rates and government-agency "
            "approval requirements on Qatar's e-Customs portal."))
        menubar.add_cascade(label="Help", menu=helpm)
        self.config(menu=menubar)

    def _build_search(self):
        box = ttk.LabelFrame(self, text="Search", padding=10)
        box.pack(side="top", fill="x", padx=10, pady=(10, 0))

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="HS Code:").pack(side="left")
        self.entry = ttk.Entry(row, width=24)
        self.entry.pack(side="left", padx=(6, 8))
        self.entry.bind("<Return>", lambda e: self.on_search_single())
        self.search_btn = ttk.Button(row, text="Search", command=self.on_search_single)
        self.search_btn.pack(side="left", padx=(0, 18))
        self.import_btn = ttk.Button(row, text="Import List...", command=self.on_import_file)
        self.import_btn.pack(side="left")
        self.scan_btn = ttk.Button(row, text="Scan Document...", command=self.on_import_document)
        self.scan_btn.pack(side="left", padx=(8, 0))
        ttk.Button(row, text="CBM Calculator...", command=self.on_cbm).pack(side="right")

        row2 = ttk.Frame(box)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="Show:").pack(side="left")
        self.mode_var = tk.StringVar(value=RESULT_MODE_LABELS[0][0])
        ttk.Combobox(row2, textvariable=self.mode_var, state="readonly", width=56,
                     values=[l for l, _ in RESULT_MODE_LABELS]).pack(side="left", padx=(6, 0))

    def _build_table(self):
        box = ttk.LabelFrame(self, text="Results", padding=8)
        box.pack(side="top", fill="both", expand=True, padx=10, pady=10)

        tools = ttk.Frame(box)
        tools.pack(side="top", fill="x", pady=(0, 6))
        self.count_var = tk.StringVar(value="No results")
        ttk.Label(tools, textvariable=self.count_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(tools, text="Clear", command=self.clear_results).pack(side="right")
        ttk.Button(tools, text="Export to CSV...", command=self.on_export).pack(
            side="right", padx=(0, 6))

        frame = ttk.Frame(box)
        frame.pack(side="top", fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS], show="headings")
        for cid, heading, width, stretch in COLUMNS:
            self.tree.heading(cid, text=heading)
            self.tree.column(cid, width=width, anchor="w", stretch=stretch)
        self.tree.tag_configure("odd", background=ROW_ALT)
        self.tree.tag_configure("missing", foreground=ERROR)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        ttk.Label(box, style="Muted.TLabel",
                  text="Double-click a row for full detail (agencies + required documents). "
                       "Right-click to copy.").pack(side="top", anchor="w", pady=(6, 0))

        self.tree.bind("<Double-1>", self.on_row_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="View full detail", command=self._menu_detail)
        self.menu.add_command(label="Copy HS code", command=self._menu_copy_code)
        self.menu.add_command(label="Copy row", command=self._menu_copy_row)

    def _build_status_bar(self):
        bar = ttk.Frame(self, padding=(10, 4))
        bar.pack(side="bottom", fill="x")
        ttk.Separator(self, orient="horizontal").pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="determinate", length=200)
        self.progress.pack(side="right")

    # ------------------------------------------------------------------
    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.search_btn, self.import_btn, self.scan_btn):
            b.configure(state=state)

    def on_cbm(self):
        existing = getattr(self, "_cbm_win", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        self._cbm_win = CbmCalculator(self)

    def on_search_single(self):
        if self._busy:
            return
        code = self.entry.get().strip()
        if not code:
            messagebox.showwarning(APP_TITLE, "Please enter an HS code.")
            return
        self._run_search_in_background([_clean_code(code)])

    def on_import_file(self):
        if self._busy:
            return
        path = filedialog.askopenfilename(
            title="Select a file with HS codes",
            filetypes=[("CSV or text files", "*.csv *.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            codes = self._read_codes_from_file(path)
        except (OSError, UnicodeDecodeError) as e:
            messagebox.showerror(APP_TITLE, f"Could not read that file:\n{e}")
            return
        if not codes:
            messagebox.showwarning(APP_TITLE, "No HS codes were found in that file.")
            return
        self._run_search_in_background(codes)

    def _read_codes_from_file(self, path):
        codes = []
        if path.lower().endswith(".csv"):
            with open(path, newline="", encoding="utf-8-sig") as f:
                for row in csv.reader(f):
                    for cell in row:
                        cell = _clean_code(cell.strip())
                        if cell.isdigit():
                            codes.append(cell)
        else:
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    line = _clean_code(line.strip())
                    if line.isdigit():
                        codes.append(line)
        return codes

    def _run_search_in_background(self, codes):
        self._set_busy(True)
        self.progress.configure(mode="determinate")
        self.progress["value"] = 0
        self.progress["maximum"] = len(codes)
        self.status_var.set(f"Searching {len(codes)} code(s)...")
        mode = dict(RESULT_MODE_LABELS).get(self.mode_var.get(), "auto")

        def worker():
            def on_progress(i, total, code):
                self.after(0, lambda: self._update_progress(i, total, code))
            try:
                results = search_many(codes, on_progress=on_progress, mode=mode)
            except Exception as e:
                msg = str(e)
                self.after(0, lambda m=msg: self._search_failed(m))
                return
            self.after(0, lambda: self._display_results(results))

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, i, total, code):
        self.progress["value"] = i
        self.status_var.set(f"Searching {i}/{total}: {code}")

    def _search_failed(self, msg):
        self._set_busy(False)
        self.status_var.set("Search failed.")
        messagebox.showerror(APP_TITLE, f"The search could not be completed:\n{msg}")

    def _display_results(self, results):
        for r in results:
            n = len(self.results)
            self.results.append(r)
            tags = ["odd" if n % 2 else "even"] + ([] if r.found else ["missing"])
            iid = self.tree.insert("", "end", values=_row_values(r), tags=tags)
            self._item_by_iid[iid] = r
        self._set_busy(False)
        found = sum(1 for r in results if r.found)
        self.status_var.set(f"Done. {found}/{len(results)} code(s) found.")
        total_found = sum(1 for r in self.results if r.found)
        self.count_var.set(f"{len(self.results)} result(s), {total_found} found")
        children = self.tree.get_children()
        if children:
            self.tree.see(children[-1])

    def clear_results(self):
        self.tree.delete(*self.tree.get_children())
        self.results.clear()
        self._item_by_iid.clear()
        self.count_var.set("No results")
        self.status_var.set("Ready.")
        self.progress["value"] = 0

    # ------------------------------------------------------------------
    def on_import_document(self):
        if self._busy:
            return
        path = filedialog.askopenfilename(
            title="Select a document to scan for HS codes", filetypes=FILETYPES)
        if not path:
            return
        self._set_busy(True)
        self.status_var.set(f"Reading {os.path.basename(path)}...")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def worker():
            try:
                result = extract_candidates(path)
            except ExtractionError as e:
                msg = str(e)
                self.after(0, lambda m=msg: self._on_extraction_done(None, m))
                return
            except Exception as e:
                msg = f"Unexpected problem reading the file: {e}"
                self.after(0, lambda m=msg: self._on_extraction_done(None, m))
                return
            self.after(0, lambda: self._on_extraction_done(result, None))

        threading.Thread(target=worker, daemon=True).start()

    def _on_extraction_done(self, result, error):
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._set_busy(False)
        if error:
            self.status_var.set("Could not read the document.")
            messagebox.showerror(APP_TITLE, error)
            return
        if not result.candidates:
            self.status_var.set("No HS codes found in the document.")
            extra = ("\n\n" + "\n".join(result.warnings)) if result.warnings else ""
            messagebox.showinfo(
                APP_TITLE, f"No HS-code-like numbers were found in {result.source_name}.{extra}")
            return
        self.status_var.set(
            f"Found {len(result.candidates)} possible code(s) in {result.source_name} - review them.")
        ReviewDialog(self, result, on_confirm=self._run_search_in_background)

    def on_export(self):
        if not self.results:
            messagebox.showinfo(APP_TITLE, "There are no results to export yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Save results as CSV", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([c[1] for c in COLUMNS])
                w.writerows(_row_values(r) for r in self.results)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Could not save the file:\n{e}")
            return
        messagebox.showinfo(APP_TITLE, f"Results exported to:\n{path}")

    # ------------------------------------------------------------------
    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _selected(self):
        sel = self.tree.selection()
        return self._item_by_iid.get(sel[0]) if sel else None

    def _menu_detail(self):
        r = self._selected()
        if r:
            self._open_detail(r)

    def _menu_copy_code(self):
        r = self._selected()
        if r:
            self.clipboard_clear()
            self.clipboard_append(r.hs_code or r.query)

    def _menu_copy_row(self):
        r = self._selected()
        if r:
            self.clipboard_clear()
            self.clipboard_append("\t".join(map(str, _row_values(r))))

    def on_row_double_click(self, event):
        r = self._item_by_iid.get(self.tree.identify_row(event.y))
        if r:
            self._open_detail(r)

    def _open_detail(self, r):
        hs_code = str(r.hs_code or "").strip()
        if not r.found or not hs_code.isdigit() or len(hs_code) < 12:
            messagebox.showinfo(
                APP_TITLE, "Full detail is only available for a found, complete 12-digit HS code row.")
            return
        win = DetailWindow(self, hs_code)

        def worker():
            detail = get_full_detail(hs_code)
            self.after(0, lambda: win.winfo_exists() and win.populate(detail))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()