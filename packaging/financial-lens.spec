# PyInstaller spec for the Financial Lens desktop app (Linux, Windows, macOS).
# Bundles Python, Qt, embedded PostgreSQL (pgserver), pdfium, zxing-cpp and Tesseract with
# German, French, Italian and English language data.
import os
import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent
datas, binaries, hidden = [], [], ["financial_lens.api.app", "financial_lens.api.mobile", "uvicorn.logging",
                                   "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"]
for pkg in ("pgserver", "pypdfium2", "pypdfium2_raw", "zxingcpp", "pillow_heif", "qrcode", "openpyxl"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
# PostgreSQL must keep its directory layout ($libdir/postgresql/*.so, share/...), so ship pginstall as a tree.
import pgserver as _pg

_pginstall = Path(_pg.__file__).parent / "pginstall"
datas = [x for x in datas if "pginstall" not in x[0]]
binaries = [x for x in binaries if "pginstall" not in x[0]]
for f in _pginstall.rglob("*"):
    if f.is_file() and f.suffix != ".a" and "include" not in f.relative_to(_pginstall).parts:
        datas.append((str(f), str(Path("pgserver/pginstall") / f.relative_to(_pginstall).parent)))
datas += collect_data_files("financial_lens", includes=["**/*.sql", "assets/*"])
hidden += ["financial_lens.selftest"]

# Tesseract: FL_TESSERACT_DIR points at a folder with the executable (and its DLLs on Windows) and tessdata/.
tess_dir = Path(os.environ.get("FL_TESSERACT_DIR", ""))
if sys.platform == "win32":
    exe = tess_dir / "tesseract.exe"
    for dll in tess_dir.glob("*.dll"):
        binaries.append((str(dll), "tesseract"))
else:
    exe = Path(shutil.which("tesseract") or tess_dir / "tesseract")
binaries.append((str(exe), "tesseract"))
tessdata = Path(os.environ.get("FL_TESSDATA", tess_dir / "tessdata"))
for lang in ("deu", "fra", "ita", "eng", "osd"):
    f = tessdata / f"{lang}.traineddata"
    if f.exists():
        datas.append((str(f), "tesseract/tessdata"))
for f in (tessdata / "configs").glob("*"):  # "tsv" output config is needed for per-line confidences
    datas.append((str(f), "tesseract/tessdata/configs"))

a = Analysis([str(ROOT / "packaging" / "launcher.py")], pathex=[str(ROOT / "src")], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=["tkinter", "paddleocr", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
icon = str(ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns" if sys.platform == "darwin" else "icon.png"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FinancialLens", console=False,
          icon=icon if Path(icon).exists() else None)
coll = COLLECT(exe, a.binaries, a.datas, name="FinancialLens")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Financial Lens.app", icon=icon if Path(icon).exists() else None,
                 bundle_identifier="ch.helveticlens.finance",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": os.environ.get("FL_VERSION", "0.5.0")})
