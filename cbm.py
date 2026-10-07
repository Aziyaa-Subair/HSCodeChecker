"""
cbm.py
------
CBM (cubic metre) calculator for the HS Code Lookup app.

    CBM per line = Length x Width x Height (in metres) x Quantity

Also gives the numbers freight people usually need next:
  - Volumetric weight for AIR freight  = L x W x H (cm) / 6000  per package
                                       (i.e. about 167 kg per CBM)
  - Chargeable weight for AIR          = the greater of gross and volumetric
  - Chargeable for SEA LCL (W/M)       = the greater of CBM and gross tonnes
                                         (1 CBM is charged the same as 1 tonne)

The calculation functions at the top are plain Python (no GUI), so they can be
tested on their own. The CbmCalculator window at the bottom is the Tkinter UI.
"""

import re
import tkinter as tk
from tkinter import ttk, messagebox

from theme import center_on, OK, ERROR, MUTED
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Calculation logic (no GUI)
# ---------------------------------------------------------------------------

UNIT_TO_METRE = {"cm": 0.01, "m": 1.0, "mm": 0.001, "in": 0.0254}
AIR_VOLUMETRIC_CM3_PER_KG = 6000.0      # IATA standard divisor


def to_number(text: str) -> Optional[float]:
    """'' -> None. '12.5' -> 12.5. '1,5' -> 1.5 (decimal comma) but '1,200' ->
    1200 (thousands). Raises ValueError for anything that is not a number."""
    s = (text or "").strip().replace(" ", "")
    if not s:
        return None
    if "," in s:
        if "." in s:
            s = s.replace(",", "")                       # 1,200.5
        elif s.count(",") == 1 and len(s.split(",")[1]) != 3:
            s = s.replace(",", ".")                      # 1,5  -> 1.5
        else:
            s = s.replace(",", "")                       # 1,200 -> 1200
    return float(s)


def cbm_of(length: float, width: float, height: float, unit: str, qty: float = 1) -> float:
    f = UNIT_TO_METRE[unit]
    return (length * f) * (width * f) * (height * f) * qty


def summarize(lines: List[Dict], unit: str, gross_kg: Optional[float] = None) -> Dict:
    """
    lines: [{"length": float|None, "width": ..., "height": ..., "qty": float|None}, ...]
    A line counts only when length, width and height are all filled in and > 0.
    A blank quantity means 1. Returns per-line CBM plus the shipment totals.
    """
    per_line: List[Optional[float]] = []
    total_cbm = 0.0
    total_pkgs = 0.0
    volumetric_kg = 0.0

    for ln in lines:
        l, w, h = ln.get("length"), ln.get("width"), ln.get("height")
        qty = ln.get("qty")
        qty = 1.0 if qty is None else qty
        if not (l and w and h) or l <= 0 or w <= 0 or h <= 0 or qty <= 0:
            per_line.append(None)
            continue
        c = cbm_of(l, w, h, unit, qty)
        per_line.append(c)
        total_cbm += c
        total_pkgs += qty
        volumetric_kg += c * 1_000_000 / AIR_VOLUMETRIC_CM3_PER_KG

    out = {
        "per_line": per_line,
        "packages": total_pkgs,
        "cbm": total_cbm,
        "volumetric_kg": volumetric_kg,
        "gross_kg": gross_kg,
        "air_chargeable_kg": None,
        "sea_chargeable": None,
    }
    if total_cbm > 0:
        out["air_chargeable_kg"] = max(volumetric_kg, gross_kg or 0.0)
        out["sea_chargeable"] = max(total_cbm, (gross_kg or 0.0) / 1000.0)
    return out


_NUM = r"\d+(?:[.,]\d+)?"
_SEP = r"\s*[x\u00d7*]\s*"
# optional "qty x" prefix, then L x W x H, then an optional unit
_DIM_RE = re.compile(
    rf"(?:(\d+){_SEP})?({_NUM}){_SEP}({_NUM}){_SEP}({_NUM})\s*(mm|cm|inch|in|m)?(?![a-z])",
    re.IGNORECASE,
)
# "(01Plt)", "(2 ctns)", "(3)"  -> quantity in brackets after the size
_QTY_RE = re.compile(r"\(\s*(\d+)\s*[a-z]*\s*\)", re.IGNORECASE)


def parse_dimensions(text: str) -> List[Dict]:
    """
    Pulls package sizes out of pasted text, e.g. a packing list:
        116x78x145cm(01Plt)
        116 x 78 x 144 cm (01Plt)
        2 x 60x40x50 cm
    Returns [{"length","width","height","qty","unit"(may be None)}, ...].
    """
    found = []
    for line in text.splitlines():
        m = _DIM_RE.search(line)
        if not m:
            continue
        pre_qty, l, w, h, unit = m.groups()
        qty = int(pre_qty) if pre_qty else None
        if qty is None:
            q = _QTY_RE.search(line[m.end():])
            if q:
                qty = int(q.group(1))
        found.append({
            "length": to_number(l), "width": to_number(w), "height": to_number(h),
            "qty": qty or 1,
            "unit": (unit or "").lower().replace("inch", "in") or None,
        })
    return found


def _fmt(x: Optional[float], places: int = 3) -> str:
    return "" if x is None else f"{x:,.{places}f}"


# ---------------------------------------------------------------------------
# The calculator window
# ---------------------------------------------------------------------------

class CbmCalculator(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("CBM Calculator")
        self.minsize(780, 520)
        self.transient(parent)
        center_on(self, parent, 860, 640)

        self.unit_var = tk.StringVar(value="cm")
        self.gross_var = tk.StringVar()
        self.rows: List[Dict] = []

        self._build_toolbar()
        self._build_results()          # bottom before the expanding grid
        self._build_grid()

        self.unit_var.trace_add("write", lambda *a: self._recalc())
        self.gross_var.trace_add("write", lambda *a: self._recalc())
        self._add_row()
        self.after(50, lambda: self.rows[0]["entries"][1].focus_set())

    # -- layout -------------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(12, 10, 12, 4))
        bar.pack(side="top", fill="x")
        ttk.Label(bar, text="Dimensions in:").pack(side="left")
        ttk.Combobox(bar, textvariable=self.unit_var, values=list(UNIT_TO_METRE),
                     width=5, state="readonly").pack(side="left", padx=(6, 16))
        ttk.Button(bar, text="Add row", command=self._add_row).pack(side="left")
        ttk.Button(bar, text="Paste dimensions...", command=self._open_paste).pack(
            side="left", padx=(8, 0))
        ttk.Button(bar, text="Clear all", command=self._clear_all).pack(side="left", padx=(8, 0))

    def _build_grid(self):
        outer = ttk.Frame(self, padding=(12, 0, 12, 0))
        outer.pack(side="top", fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(side="top", fill="x")
        self._config_cols(head)
        for col, text in enumerate(["#", "Description (optional)", "Length", "Width",
                                    "Height", "Qty", "CBM", ""]):
            ttk.Label(head, text=text, style="Bold.TLabel").grid(row=0, column=col, padx=2, sticky="w")
        ttk.Separator(outer, orient="horizontal").pack(side="top", fill="x", pady=(2, 0))

        holder = ttk.Frame(outer)
        holder.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(holder, highlightthickness=0, height=200,
                                background=ttk.Style().lookup("TFrame", "background") or "#f0f0f0")
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = ttk.Frame(self.canvas)
        win = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self._config_cols(self.grid_frame)
        self.grid_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.grid_frame.bind("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

    @staticmethod
    def _config_cols(frame):
        for col, (minsize, weight) in enumerate(
                [(30, 0), (200, 1), (80, 0), (80, 0), (80, 0), (60, 0), (100, 0), (36, 0)]):
            frame.columnconfigure(col, minsize=minsize, weight=weight)

    def _build_results(self):
        box = ttk.LabelFrame(self, text="Shipment total", padding=12)
        box.pack(side="bottom", fill="x", padx=12, pady=12)

        gross = ttk.Frame(box)
        gross.pack(side="top", fill="x", pady=(0, 8))
        ttk.Label(gross, text="Total gross weight (kg, optional):").pack(side="left")
        ttk.Entry(gross, textvariable=self.gross_var, width=12).pack(side="left", padx=(6, 0))
        ttk.Label(gross, text="  used for the chargeable-weight figures below",
                  style="Muted.TLabel").pack(side="left")

        self.result_vars = {k: tk.StringVar(value="-") for k in ("pkgs", "cbm", "vol", "air", "sea")}
        grid = ttk.Frame(box)
        grid.pack(side="top", fill="x")
        for r, (label, key, big) in enumerate([
            ("Total packages:", "pkgs", False), ("Total CBM:", "cbm", True),
            ("Volumetric weight (air, /6000):", "vol", False),
            ("Air chargeable weight:", "air", False),
            ("Sea LCL chargeable (W/M):", "sea", False),
        ]):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w", pady=1)
            ttk.Label(grid, textvariable=self.result_vars[key],
                      style="Big.TLabel" if big else "Bold.TLabel").grid(
                row=r, column=1, sticky="w", padx=(12, 0))

        self.warn_var = tk.StringVar()
        self.warn_lbl = ttk.Label(box, textvariable=self.warn_var, foreground=ERROR)
        self.warn_lbl.pack(side="top", anchor="w", pady=(6, 0))
        btns = ttk.Frame(box)
        btns.pack(side="top", fill="x", pady=(8, 0))
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Copy summary", command=self._copy_summary).pack(
            side="right", padx=(0, 8))

    # -- rows ---------------------------------------------------------------
    def _add_row(self, desc="", length="", width="", height="", qty=""):
        i = len(self.rows)
        vars_ = [tk.StringVar(value=v) for v in (desc, length, width, height, qty)]
        num = ttk.Label(self.grid_frame, text=str(i + 1))
        num.grid(row=i, column=0, padx=2, pady=2, sticky="w")
        entries = []
        for c, v in enumerate(vars_, start=1):
            e = ttk.Entry(self.grid_frame, textvariable=v, width=6)
            e.grid(row=i, column=c, padx=2, pady=2, sticky="ew")
            entries.append(e)
            v.trace_add("write", lambda *a: self._recalc())
        cbm_lbl = ttk.Label(self.grid_frame, text="")
        cbm_lbl.grid(row=i, column=6, padx=4, pady=2, sticky="w")
        row = {"vars": vars_, "entries": entries, "num": num, "cbm": cbm_lbl, "widgets": None}
        rm = ttk.Button(self.grid_frame, text="\u2715", width=3,
                        command=lambda r=row: self._remove_row(r))
        rm.grid(row=i, column=7, padx=2, pady=2)
        row["widgets"] = [num, *entries, cbm_lbl, rm]
        entries[4].bind("<Return>", lambda e, r=row: self._next_row(r))
        self.rows.append(row)
        self._recalc()
        return row

    def _next_row(self, row):
        idx = self.rows.index(row)
        nxt = self.rows[idx + 1] if idx + 1 < len(self.rows) else self._add_row()
        nxt["entries"][1].focus_set()

    def _remove_row(self, row):
        for w in row["widgets"]:
            w.destroy()
        self.rows.remove(row)
        if not self.rows:
            self._add_row()
            return
        for i, r in enumerate(self.rows):
            for w in r["widgets"]:
                w.grid_configure(row=i)
            r["num"].configure(text=str(i + 1))
        self._recalc()

    def _clear_all(self):
        for r in list(self.rows):
            for w in r["widgets"]:
                w.destroy()
        self.rows.clear()
        self.gross_var.set("")
        self._add_row()

    # -- paste --------------------------------------------------------------
    def _open_paste(self):
        win = tk.Toplevel(self)
        win.title("Paste dimensions")
        win.transient(self)
        center_on(win, self, 480, 340)
        ttk.Label(
            win, padding=10, justify="left",
            text=("Paste package sizes, one per line, e.g. from a packing list:\n"
                  "  116x78x145cm(01Plt)\n  2 x 60x40x50 cm\n"
                  "Text that isn't a size is ignored."),
        ).pack(side="top", anchor="w")
        bar = ttk.Frame(win, padding=10)
        bar.pack(side="bottom", fill="x")
        txt = tk.Text(win, height=10, wrap="word")
        txt.pack(side="top", fill="both", expand=True, padx=10)
        txt.focus_set()

        def add():
            items = parse_dimensions(txt.get("1.0", "end"))
            if not items:
                messagebox.showinfo("Paste dimensions", "No sizes like 116x78x145 were found.",
                                    parent=win)
                return
            self.add_parsed(items)
            win.destroy()

        ttk.Button(bar, text="Add to calculator", command=add).pack(side="right")
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right", padx=(0, 8))

    def add_parsed(self, items: List[Dict]):
        blank = len(self.rows) == 1 and not any(v.get().strip() for v in self.rows[0]["vars"])
        cur = self.unit_var.get()
        for n, it in enumerate(items):
            factor = UNIT_TO_METRE[it["unit"]] / UNIT_TO_METRE[cur] if it["unit"] else 1.0
            values = ("", *(f"{it[k] * factor:.4g}" for k in ("length", "width", "height")),
                      str(it["qty"]))
            if blank and n == 0:
                for v, val in zip(self.rows[0]["vars"], values):
                    v.set(val)
            else:
                self._add_row(*values)

    # -- calculation --------------------------------------------------------
    def _collect(self):
        lines, bad = [], False
        for r in self.rows:
            d = {}
            for key, v in zip(("length", "width", "height", "qty"), r["vars"][1:]):
                try:
                    d[key] = to_number(v.get())
                except ValueError:
                    d[key] = None
                    bad = True
            lines.append(d)
        try:
            gross = to_number(self.gross_var.get())
        except ValueError:
            gross, bad = None, True
        return lines, gross, bad

    def _recalc(self):
        if not hasattr(self, "result_vars"):
            return
        lines, gross, bad = self._collect()
        s = summarize(lines, self.unit_var.get(), gross)
        for r, c in zip(self.rows, s["per_line"]):
            r["cbm"].configure(text=_fmt(c, 4))
        rv = self.result_vars
        has = s["cbm"] > 0
        rv["pkgs"].set(f"{s['packages']:g}" if has else "-")
        rv["cbm"].set(f"{s['cbm']:,.3f} m\u00b3" if has else "-")
        rv["vol"].set(f"{s['volumetric_kg']:,.1f} kg" if has else "-")
        if has:
            label = "kg" if gross else "kg (volumetric only - enter gross weight to compare)"
            rv["air"].set(f"{s['air_chargeable_kg']:,.1f} {label}")
            rv["sea"].set(f"{s['sea_chargeable']:,.3f} W/M" +
                          ("" if gross else "  (CBM only - enter gross weight to compare)"))
        else:
            rv["air"].set("-")
            rv["sea"].set("-")
        self.warn_lbl.configure(foreground=ERROR)
        self.warn_var.set("Some values aren't valid numbers and were ignored." if bad else "")

    def _copy_summary(self):
        lines, gross, _ = self._collect()
        unit = self.unit_var.get()
        s = summarize(lines, unit, gross)
        out = ["CBM summary", f"Dimensions in: {unit}", ""]
        for i, (r, c) in enumerate(zip(self.rows, s["per_line"]), 1):
            if c is None:
                continue
            l, w, h = (v.get().strip() for v in r["vars"][1:4])
            q = r["vars"][4].get().strip() or "1"
            desc = r["vars"][0].get().strip()
            out.append(f"{i}. {desc + ' ' if desc else ''}{l} x {w} x {h} {unit}  x {q}  = {c:.4f} CBM")
        out += ["", f"Total packages: {s['packages']:g}", f"Total CBM: {s['cbm']:.3f}",
                f"Volumetric weight (air): {s['volumetric_kg']:.1f} kg"]
        if gross:
            out += [f"Gross weight: {gross:,.1f} kg",
                    f"Air chargeable weight: {s['air_chargeable_kg']:.1f} kg",
                    f"Sea LCL chargeable (W/M): {s['sea_chargeable']:.3f}"]
        self.clipboard_clear()
        self.clipboard_append("\n".join(out))
        self.warn_lbl.configure(foreground=OK)
        self.warn_var.set("Summary copied to the clipboard.")
        self.after(2500, lambda: self.winfo_exists() and self._recalc())