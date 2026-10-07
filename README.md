<p align="center"><img src="assets/logo_full.png" width="240" alt="HS Code Checker"></p>

# HS Code Checker

A lightweight Windows desktop tool that looks up Harmonized System (HS) codes
on Qatar's official e-Customs / Al-Nadeeb portal and displays the results —
description, unit of measure, duty rate, and any Other Government Agency
(OGA) approval requirements — without needing to use the website by hand.

Supports single lookups, bulk lookups from a CSV/TXT list, CSV export, and a
double-click drill-down for the full classification breakdown plus the exact
document checklist per required agency.

## Features

- 🔍 Search by a full 12-digit HS code or a shorter chapter/heading prefix
- 📋 Bulk search by importing a CSV or TXT list of codes
- 📄 **Scan documents for HS codes** — PDF, Excel, Word, CSV/TXT, and images/scanned
  PDFs (via OCR). Found codes are shown on a review screen with a confidence level
  so you confirm them before anything is searched
- 🏛️ Clearly flags whether another government agency's approval is required
  (and which agency), or shows "standard clearance" when none is needed
- 🔎 Double-click any result for full detail: classification breadcrumb,
  duty/protection rate, and the required-documents checklist per agency
- 📦 **CBM calculator** — length × width × height × quantity per line, with total CBM,
  air volumetric weight, and air / sea (LCL) chargeable weight. Can read package sizes
  pasted straight from a packing list (e.g. `116x78x145cm(01Plt)`)
- 📤 Export results to CSV
- 🖥️ Packaged as a single standalone Windows `.exe` — no Python required to
  run it

## How it works

The portal is an Angular single-page app. Rather than driving a browser, this
tool calls the same background REST API the site's own JavaScript calls
(reverse-engineered via the browser's DevTools Network tab), so lookups are
fast and don't require a headless browser. See `hs_lookup.py` for the
confirmed endpoints and response shapes.

## Scanning documents for HS codes

Click **Scan Document (PDF / Excel / Image)...**, pick a file, and the app pulls
out anything that looks like an HS code, then shows a review list:

| Confidence | Meaning |
|---|---|
| **High** | Next to an "HS Code" / "HSN" / "Tariff" label, or in a column with that header |
| **Medium** | An 8/10/12-digit number that looks like a code |
| **Low** | Could be an invoice, phone or quantity number — unticked by default |

Tick/untick rows, then **Search selected**. Supported: `.pdf`, `.xlsx`/`.xlsm`,
`.docx`, `.csv`, `.txt`, and images (`.png .jpg .tif .bmp`). Old `.xls`/`.doc`
files must be re-saved as `.xlsx`/`.docx` first.

**OCR (images and scanned PDFs) is optional.** It needs the Tesseract program
installed on the computer (Windows installer:
<https://github.com/UB-Mannheim/tesseract/wiki>). Without it, digital PDFs, Excel,
Word, CSV and TXT still work, and the app explains what to install if OCR is needed.
The OCR pipeline auto-corrects EXIF-rotated phone photos, straightens tilted
scans, and improves low-contrast images before reading them — but OCR is never
perfect, so that's what the review screen is for.

## Getting started (running from source)

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python main.py
```

## Building a standalone .exe

On Windows, with the dependencies installed:

```bat
build.bat
```

This runs PyInstaller and produces `dist/HSCodeChecker.exe` — a single
file that runs on any Windows machine without Python installed. See
`build.bat` for details; it will clearly print `FAILED` and stop if the build
does not succeed.

> **Note:** if you're on an Anaconda environment, remove any obsolete
> third-party `pathlib` package first (`pip uninstall pathlib` or
> `conda remove pathlib`) — PyInstaller refuses to build while it's present.

## Project structure

```
.
├── main.py              # Tkinter GUI (search box, results table, detail + review windows)
├── hs_lookup.py          # Core lookup logic — calls the real portal API
├── extractor.py          # Finds HS codes inside PDF / Excel / Word / image files
├── cbm.py                # CBM calculator (calculation logic + window)
├── requirements.txt      # Python dependencies
├── build.bat             # Packages the app into a standalone .exe
├── assets/               # app_icon.ico / app_icon.png (window + .exe icon), logo_full.png
└── README.md
```

## Known limitations

- Relies on the Qatar e-Customs portal's own internal API, which is not
  officially published or guaranteed stable. If the portal is redesigned,
  the endpoints in `hs_lookup.py` may need to be updated.
- Requires an active internet connection — nothing is cached or stored
  locally; every search hits the live portal.
- This tool only automates the portal's **public inquiry search**. No login
  credentials are stored, bypassed, or required.

## License

Specify your license here (e.g. MIT) or mark as proprietary/client-owned if
this was built as commissioned freelance work.
