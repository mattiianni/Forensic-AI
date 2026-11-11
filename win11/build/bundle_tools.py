#!/usr/bin/env python3
"""
Copia in <dest> (runtime/tools) il minimo indispensabile dall'ambiente
conda-forge win-64: tesseract.exe, gswin64c.exe, gsdll64.dll e le librerie
Pango/Cairo/HarfBuzz/Fontconfig/GObject usate da WeasyPrint, con la chiusura
transitiva delle dipendenze DLL ricavata direttamente dalla Import Table PE.

Uso: python bundle_tools.py <conda_env> <dest>
"""
from __future__ import annotations

import glob
import os
import shutil
import struct
import sys
import urllib.request
from pathlib import Path

BIN_PATTERNS = [
    "tesseract.exe",
    "gswin64c.exe",
    "gswin32c.exe",
    "gsdll64.dll",
    "gsdll32.dll",
    "*pango*.dll",
    "*gobject-2.0*.dll",
    "*glib-2.0*.dll",
    "*gio-2.0*.dll",
    "*gmodule-2.0*.dll",
    "*harfbuzz*.dll",
    "*fontconfig*.dll",
    "*cairo*.dll",
    "*freetype*.dll",
    "*pixman*.dll",
    "*gdk_pixbuf*.dll",
]

TESSDATA_BEST = "https://github.com/tesseract-ocr/tessdata_best/raw/main/{}.traineddata"


def _rva_to_offset(rva: int, sections: list[tuple[int, int, int]]) -> int | None:
    for vaddr, vsize, raw_ptr in sections:
        if vaddr <= rva < vaddr + max(vsize, 1):
            return raw_ptr + (rva - vaddr)
    return None


def _read_cstr(data: bytes, offset: int) -> str:
    end = data.find(b"\x00", offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode("ascii", errors="ignore")


def pe_imports(path: Path) -> list[str]:
    """Legge i nomi delle DLL importate da un file PE (EXE/DLL) in Python puro."""
    try:
        data = path.read_bytes()
        if len(data) < 64 or data[:2] != b"MZ":
            return []
        pe_off = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe_off:pe_off + 4] != b"PE\x00\x00":
            return []
        num_sections = struct.unpack_from("<H", data, pe_off + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe_off + 20)[0]
        opt_off = pe_off + 24
        magic = struct.unpack_from("<H", data, opt_off)[0]
        if magic == 0x20B:      # PE32+ (64-bit)
            dd_off = opt_off + 112
        elif magic == 0x10B:    # PE32 (32-bit)
            dd_off = opt_off + 96
        else:
            return []
        import_rva, import_size = struct.unpack_from("<II", data, dd_off + 8)
        if not import_rva or not import_size:
            return []

        sec_off = opt_off + opt_size
        sections: list[tuple[int, int, int]] = []
        for i in range(num_sections):
            s = sec_off + i * 40
            vsize, vaddr, raw_size, raw_ptr = struct.unpack_from("<IIII", data, s + 8)
            sections.append((vaddr, max(vsize, raw_size), raw_ptr))

        off = _rva_to_offset(import_rva, sections)
        if off is None:
            return []

        dlls: list[str] = []
        while off + 20 <= len(data):
            ilt_rva, _ts, _fwd, name_rva, iat_rva = struct.unpack_from("<IIIII", data, off)
            if name_rva == 0 and ilt_rva == 0 and iat_rva == 0:
                break
            name_off = _rva_to_offset(name_rva, sections)
            if name_off is not None:
                name = _read_cstr(data, name_off)
                if name:
                    dlls.append(name)
            off += 20
        return dlls
    except Exception:
        return []


def main(env: Path, dest: Path):
    env_lib_bin = env / "Library" / "bin"
    env_bin = env / "bin"
    search_dirs = [d for d in (env_lib_bin, env_bin, env) if d.is_dir()]
    if not search_dirs:
        raise FileNotFoundError(f"Cartella bin/Library\\bin non trovata in {env}")

    if dest.exists():
        shutil.rmtree(dest)
    dest_bin = dest / "bin"
    dest_bin.mkdir(parents=True)

    # Indice case-insensitive dei file disponibili nell'ambiente conda
    catalog: dict[str, Path] = {}
    for d in search_dirs:
        for p in d.iterdir():
            if p.is_file():
                catalog.setdefault(p.name.lower(), p)

    queue: list[Path] = []
    for d in search_dirs:
        for pat in BIN_PATTERNS:
            for m in glob.glob(str(d / pat)):
                queue.append(Path(m))

    seen: dict[str, Path] = {}
    while queue:
        item = queue.pop()
        key = item.name.lower()
        if key in seen:
            continue
        seen[key] = item
        for dep in pe_imports(item):
            dep_l = dep.lower()
            if dep_l not in seen and dep_l in catalog:
                queue.append(catalog[dep_l])

    copied_exes, copied_dlls = 0, 0
    for key in sorted(seen):
        src = seen[key]
        shutil.copy2(src, dest_bin / src.name)
        if src.suffix.lower() == ".exe":
            copied_exes += 1
        else:
            copied_dlls += 1
    print(f"Copiati {copied_exes} eseguibili e {copied_dlls} DLL in {dest_bin}")

    # Tessdata (ita + eng best da tessdata_best, piu osd/configs/tessconfigs/pdf.ttf)
    td_candidates = [env / "Library" / "share" / "tessdata", env / "share" / "tessdata"]
    td_src = next((c for c in td_candidates if c.is_dir()), None)
    td = dest / "share" / "tessdata"
    td.mkdir(parents=True, exist_ok=True)
    if td_src:
        for extra in ("configs", "tessconfigs"):
            if (td_src / extra).is_dir():
                shutil.copytree(td_src / extra, td / extra)
        if (td_src / "pdf.ttf").exists():
            shutil.copy2(td_src / "pdf.ttf", td / "pdf.ttf")
        if (td_src / "osd.traineddata").exists():
            shutil.copy2(td_src / "osd.traineddata", td / "osd.traineddata")
    for lang in ("ita", "eng"):
        out = td / f"{lang}.traineddata"
        try:
            urllib.request.urlretrieve(TESSDATA_BEST.format(lang), out)
            print(f"tessdata_best {lang}: {out.stat().st_size // 1024} KB")
        except Exception as e:
            if td_src and (td_src / f"{lang}.traineddata").exists():
                print(f"tessdata_best {lang} non scaricato ({e}), uso il modello incluso")
                shutil.copy2(td_src / f"{lang}.traineddata", out)
            else:
                print(f"AVVISO: tessdata {lang} mancante ({e})")

    # Risorse Ghostscript
    gs_candidates = [env / "Library" / "share" / "ghostscript", env / "share" / "ghostscript"]
    gs_src = next((c for c in gs_candidates if c.is_dir()), None)
    if gs_src:
        shutil.copytree(
            gs_src,
            dest / "share" / "ghostscript",
            ignore=shutil.ignore_patterns("doc", "examples", "man"),
        )

    # Eventuali file fontconfig di supporto
    fc_candidates = [env / "Library" / "etc" / "fonts", env / "etc" / "fonts"]
    fc_src = next((c for c in fc_candidates if c.is_dir()), None)
    if fc_src:
        shutil.copytree(fc_src, dest / "etc" / "fonts")

    total_bytes = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    print(f"Strumenti Windows pronti in {dest} ({total_bytes // (1024 * 1024)} MB)")


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser())
