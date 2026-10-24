# PyInstaller spec for a standalone md-maker (no Python needed on the target).
# Build with scripts/build.py, which also bundles OCR data.
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []
# pymupdf ships its layout model (ONNX) and pymupdf4llm its OCR decision
# model as package data; pypandoc_binary ships pandoc itself.
for pkg in ("pymupdf", "pymupdf4llm", "onnxruntime", "pypandoc"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("md_maker")

a = Analysis(
    ["entry.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="md-maker", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="md-maker")
