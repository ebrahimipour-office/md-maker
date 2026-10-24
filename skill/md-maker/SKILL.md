---
name: md-maker
description: Convert PDF, DOCX, ODT, RTF or EPUB files (including Persian/Farsi documents) to Markdown locally with the md-maker CLI before reading them. Use whenever the user asks you to read, summarize, analyze, translate or extract from such a file, so the document is never loaded into context directly.
---

# md-maker

Never read a PDF/DOCX directly; that costs many more tokens than the Markdown version.

1. Convert to the scratchpad (or next to the file if the user wants to keep it):
   ```bash
   md-maker "<file>" -o "<scratchpad>/<name>.md"
   ```
   A folder works too: `md-maker "<dir>" -o "<scratchpad>/md/"`.
2. Read the resulting `.md`. For large files, check its size first and read
   only the sections you need (search for the `#` headings).

Options worth knowing:
- `--ocr always` if the output looks empty or garbled and the PDF is scanned.
  If md-maker reports missing OCR data, run `md-maker --install-ocr` once.
- `--ocr-dpi 150` (or 300) when OCR output of a scan is poor; results vary
  with resolution.
- `--engine layout` or `--engine rtl` to override the auto-detected PDF engine
  if the output order looks wrong.
- `--page-markers` when you need to cite page numbers.

If `md-maker` is not installed, tell the user to run the installer in the
md-maker project: `scripts/install-linux.sh` or `scripts\install-windows.ps1`.
