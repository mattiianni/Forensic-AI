#!/usr/bin/env python3
"""
Copia in <dest> (runtime/arm64/tools) il minimo indispensabile dall'ambiente
conda-forge: tesseract, ghostscript e le librerie pango/harfbuzz/fontconfig
usate da weasyprint, con la chiusura completa delle dipendenze dinamiche.

I binari conda-forge usano @rpath + LC_RPATH @loader_path/../lib, quindi basta
mantenere il layout bin/ lib/ share/: non serve riscrivere install name.

Uso: python3 bundle_tools.py <conda_env> <dest>
"""
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

BINARIES = ["tesseract", "gs"]
WEASY_LIBS = ["libgobject-2.0.0.dylib", "libpango-1.0.0.dylib", "libharfbuzz.0.dylib",
              "libharfbuzz-subset.0.dylib", "libfontconfig.1.dylib", "libpangoft2-1.0.0.dylib"]
TESSDATA_BEST = "https://github.com/tesseract-ocr/tessdata_best/raw/main/{}.traineddata"


def deps_of(path: Path) -> list[str]:
    out = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True).stdout
    return [line.strip().split(" (")[0] for line in out.splitlines()[1:]]


def resolve(dep: str, env_lib: Path) -> Path | None:
    if dep.startswith(("/usr/lib/", "/System/")):
        return None
    name = os.path.basename(dep)
    cand = env_lib / name
    return cand if cand.exists() else None


def main(env: Path, dest: Path):
    env_lib = env / "lib"
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "bin").mkdir(parents=True)
    (dest / "lib").mkdir(parents=True)

    queue = [env / "bin" / b for b in BINARIES] + [env_lib / l for l in WEASY_LIBS if (env_lib / l).exists()]
    seen: set[str] = set()
    while queue:
        item = queue.pop()
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        for d in deps_of(item.resolve()):
            r = resolve(d, env_lib)
            if r and str(r) not in seen:
                queue.append(r)

    libs = 0
    for p in sorted(seen):
        src = Path(p)
        sub = "bin" if src.parent == env / "bin" else "lib"
        target = dest / sub / src.name
        shutil.copy2(src.resolve(), target)       # copia il file reale con il nome referenziato
        libs += sub == "lib"
    print(f"Binari: {BINARIES} · librerie copiate: {libs}")

    # Alias senza versione cercati da weasyprint (es. libpango-1.0.dylib)
    for real, alias in [("libpango-1.0.0.dylib", "libpango-1.0.dylib"),
                        ("libpangoft2-1.0.0.dylib", "libpangoft2-1.0.dylib")]:
        if (dest / "lib" / real).exists() and not (dest / "lib" / alias).exists():
            os.symlink(real, dest / "lib" / alias)

    # Tessdata: modelli "best" per italiano e inglese, OSD, config per ocrmypdf
    td_src, td = env / "share" / "tessdata", dest / "share" / "tessdata"
    td.mkdir(parents=True)
    for extra in ("configs", "tessconfigs"):
        if (td_src / extra).is_dir():
            shutil.copytree(td_src / extra, td / extra)
    if (td_src / "pdf.ttf").exists():
        shutil.copy2(td_src / "pdf.ttf", td / "pdf.ttf")
    shutil.copy2(td_src / "osd.traineddata", td / "osd.traineddata")
    for lang in ("ita", "eng"):
        out = td / f"{lang}.traineddata"
        try:
            urllib.request.urlretrieve(TESSDATA_BEST.format(lang), out)
            print(f"tessdata_best {lang}: {out.stat().st_size // 1024} KB")
        except Exception as e:  # ripiego sul modello fast di conda
            print(f"tessdata_best {lang} non scaricato ({e}), uso il modello incluso")
            shutil.copy2(td_src / f"{lang}.traineddata", out)

    # Risorse Ghostscript
    gs_src = env / "share" / "ghostscript"
    if gs_src.is_dir():
        shutil.copytree(gs_src, dest / "share" / "ghostscript",
                        ignore=shutil.ignore_patterns("doc", "examples", "man"))

    # Firma ad-hoc (le librerie sono già firmate da conda, ma la copia la ripristina)
    for f in list((dest / "bin").iterdir()) + list((dest / "lib").iterdir()):
        subprocess.run(["codesign", "-f", "-s", "-", str(f)], capture_output=True)

    size = subprocess.run(["du", "-sh", str(dest)], capture_output=True, text=True).stdout.split()[0]
    print(f"Strumenti pronti in {dest} ({size})")


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser())
