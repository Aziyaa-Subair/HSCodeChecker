"""
theme.py - small shared helpers: icon, resource paths and a restrained ttk style.
Uses the native Windows look ("vista" theme) when available.
"""
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

MUTED = "#666666"
ERROR = "#B00020"
OK = "#1B7F3B"
WARN = "#B35C00"
ROW_ALT = "#F5F7FA"


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def set_app_icon(window) -> None:
    try:
        window.iconbitmap(default=resource_path(os.path.join("assets", "app_icon.ico")))
        return
    except tk.TclError:
        pass
    try:
        png = tk.PhotoImage(file=resource_path(os.path.join("assets", "app_icon.png")))
        window.iconphoto(True, png)
        window._icon_ref = png
    except tk.TclError:
        pass


def center_on(win, parent, w, h):
    try:
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        x = max(0, min(x, win.winfo_screenwidth() - w))
        y = max(0, min(y, win.winfo_screenheight() - h - 40))
        win.geometry(f"{w}x{h}+{x}+{y}")
    except tk.TclError:
        win.geometry(f"{w}x{h}")


def apply_theme(root) -> None:
    families = set(tkfont.families(root))
    family = "Segoe UI" if "Segoe UI" in families else None
    if family:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=family, size=9)
            except tk.TclError:
                pass

    style = ttk.Style(root)
    for theme in ("vista", "winnative", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break

    # Tag colours in Treeview are ignored by some Tk versions without this.
    def fixed_map(option):
        return [e for e in style.map("Treeview", query_opt=option)
                if e[:2] != ("!disabled", "!selected")]
    style.map("Treeview", foreground=fixed_map("foreground"), background=fixed_map("background"))

    style.configure("Treeview", rowheight=24)
    style.configure("Treeview.Heading", font=(family or "TkDefaultFont", 9, "bold"))
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Error.TLabel", foreground=ERROR)
    style.configure("Title.TLabel", font=(family or "TkDefaultFont", 14, "bold"))
    style.configure("Big.TLabel", font=(family or "TkDefaultFont", 13, "bold"))
    style.configure("Bold.TLabel", font=(family or "TkDefaultFont", 9, "bold"))