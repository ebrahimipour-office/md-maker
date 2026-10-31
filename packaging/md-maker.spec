# PyInstaller spec for a standalone md-maker (no Python needed on the target):
# md-maker (console CLI) and md-maker-gui (windowed) in one shared folder.
# Build with scripts/build.py, which also bundles OCR data.
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []
# pymupdf ships its layout model (ONNX) and pymupdf4llm its OCR decision
# model as package data; pypandoc_binary ships pandoc itself;
# hazm ships its word lists.
for pkg in ("pymupdf", "pymupdf4llm", "onnxruntime", "pypandoc", "hazm"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("md_maker")


def analysis(script):
    return Analysis([script], datas=datas, binaries=binaries, hiddenimports=hiddenimports,
                    excludes=["matplotlib", "IPython"])


a, g = analysis("entry.py"), analysis("gui_entry.py")
cli = EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name="md-maker", console=True)
gui = EXE(PYZ(g.pure), g.scripts, [], exclude_binaries=True, name="md-maker-gui", console=False)
coll = COLLECT(cli, gui, a.binaries, a.datas, g.binaries, g.datas, name="md-maker")
