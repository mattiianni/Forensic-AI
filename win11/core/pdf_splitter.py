"""
Divisione di un PDF in parti da massimo 49 MB.
Usa una stima iniziale basata sulla dimensione media per pagina,
poi affina con binary search per garantire il rispetto del limite.

Nomenclatura output: NomeFile_Parte 1 di N.pdf, NomeFile_Parte 2 di N.pdf, ...
"""

import os
import tempfile
import shutil

TARGET_BYTES = 46 * 1024 * 1024   # 46 MB (margine per overhead pypdf lazy-loading)
MAX_DEPTH = 20                    # massimo iterazioni binary search per chunk


def _write_chunk(reader, start: int, end: int, output_path: str):
    """Scrive le pagine [start, end) nel file output_path."""
    import pypdf
    writer = pypdf.PdfWriter()
    for i in range(start, end):
        writer.add_page(reader.pages[i])
    with open(output_path, 'wb') as f:
        writer.write(f)


def _chunk_size(reader, start: int, num_pages: int) -> int:
    """
    Scrive un chunk temporaneo e ne misura la dimensione in byte.
    Ritorna i byte del chunk.
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _write_chunk(reader, start, start + num_pages, tmp_path)
        return os.path.getsize(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _find_max_pages(reader, start: int, remaining: int, target: int) -> int:
    """
    Binary search: trova il massimo numero di pagine [start, start+n)
    che producono un PDF <= target bytes.
    """
    lo, hi = 1, remaining
    best = 1  # minimo 1 pagina per evitare loop infiniti

    # Stima iniziale per accelerare il binary search
    total_pages = len(reader.pages)
    try:
        from pypdf import PdfReader as _R
    except ImportError:
        pass

    # Centra il binary search sull'intervallo [lo, hi]
    for _ in range(MAX_DEPTH):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        size = _chunk_size(reader, start, mid)
        if size <= target:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return max(1, best)


def split_pdf_by_size(
    input_path: str,
    output_dir: str,
    base_name: str,
    target_bytes: int = TARGET_BYTES,
    progress_callback=None,
    part_label: str = 'Parte',
    show_total: bool = True,
) -> list:
    """
    Divide il PDF in parti, ognuna <= target_bytes.
    Crea la output_dir se non esiste.

    Args:
        input_path:        percorso del PDF da dividere
        output_dir:        cartella in cui salvare le parti
        base_name:         nome base per i file (es. "Fatture 2024")
        target_bytes:      dimensione massima di ogni parte in byte (default 49 MB)
        progress_callback: callable(part_num, total_estimated) chiamato ad ogni parte

    Returns:
        Lista di dizionari con info su ogni parte:
        [{'name': ..., 'path': ..., 'pages': '1-342', 'size_mb': 48.2}, ...]
    """
    import pypdf

    os.makedirs(output_dir, exist_ok=True)

    reader = pypdf.PdfReader(input_path, strict=False)
    total_pages = len(reader.pages)

    if total_pages == 0:
        raise RuntimeError('Il PDF non contiene pagine.')

    total_size = os.path.getsize(input_path)
    avg_page_bytes = total_size / total_pages

    # Stima del numero totale di parti (usata per la nomenclatura)
    estimated_parts = max(1, int(total_size / target_bytes) + 1)

    # Prima passata: raccoglie i range di pagine per ogni parte
    page_ranges = []
    start = 0

    while start < total_pages:
        remaining = total_pages - start

        # Stima iniziale pagine per questo chunk
        estimated_pages = max(1, int(target_bytes / avg_page_bytes))
        estimated_pages = min(estimated_pages, remaining)

        # Verifica la stima
        size_estimate = _chunk_size(reader, start, estimated_pages)

        if size_estimate <= target_bytes and estimated_pages == remaining:
            # Ultima parte: entra tutta
            page_ranges.append((start, start + remaining))
            start = total_pages
        elif size_estimate <= target_bytes:
            # La stima è ok, proviamo ad aggiungere qualche pagina in più
            n = _find_max_pages(reader, start, remaining, target_bytes)
            page_ranges.append((start, start + n))
            start += n
        else:
            # La stima è troppo grande, riduciamo con binary search
            n = _find_max_pages(reader, start, estimated_pages, target_bytes)
            page_ranges.append((start, start + n))
            start += n

    total_parts = len(page_ranges)

    # Seconda passata: scrive i file con la nomenclatura corretta
    parts = []
    for idx, (p_start, p_end) in enumerate(page_ranges, 1):
        if show_total:
            part_name = f'{base_name}_{part_label} {idx} di {total_parts}.pdf'
        else:
            part_name = f'{base_name}_{part_label} {idx}.pdf'
        part_path = os.path.join(output_dir, part_name)

        _write_chunk(reader, p_start, p_end, part_path)

        size = os.path.getsize(part_path)
        page_label = f'{p_start + 1}-{p_end}' if p_end - p_start > 1 else str(p_start + 1)

        part_info = {
            'name': part_name,
            'path': part_path,
            'pages': page_label,
            'num_pages': p_end - p_start,
            'size_mb': round(size / (1024 * 1024), 2),
            'size_bytes': size,
        }
        parts.append(part_info)

        if progress_callback:
            progress_callback(idx, total_parts)

    return parts


def split_by_ranges(input_path: str, ranges: list, output_dir: str,
                    part_label: str = 'Parte', show_total: bool = True) -> list:
    """
    Divide il PDF in base a range di pagine specificati dall'utente.

    Args:
        input_path:  percorso del PDF sorgente
        ranges:      lista di [start, end] (1-based, inclusi), es. [[1,80],[81,150]]
        output_dir:  cartella di destinazione
        part_label:  parola usata nel nome file (default "Parte")
        show_total:  se True aggiunge "di N" nel nome file

    Returns:
        Lista di dict con info su ogni parte (name, path, pages, size_mb)
    """
    import pypdf

    os.makedirs(output_dir, exist_ok=True)
    reader = pypdf.PdfReader(input_path, strict=False)
    total_pages = len(reader.pages)
    base = os.path.splitext(os.path.basename(input_path))[0]

    parts = []
    for idx, (p_start, p_end) in enumerate(ranges, 1):
        p_start = max(1, int(p_start))
        p_end   = min(total_pages, int(p_end))
        if p_start > p_end:
            continue

        total_r = len(ranges)
        if show_total:
            part_name = f'{base}_{part_label} {idx} di {total_r}_pag{p_start}-{p_end}.pdf'
        else:
            part_name = f'{base}_{part_label} {idx}_pag{p_start}-{p_end}.pdf'
        part_path = os.path.join(output_dir, part_name)

        _write_chunk(reader, p_start - 1, p_end, part_path)

        size = os.path.getsize(part_path)
        parts.append({
            'name':      part_name,
            'path':      part_path,
            'pages':     f'{p_start}-{p_end}',
            'num_pages': p_end - p_start + 1,
            'size_mb':   round(size / (1024 * 1024), 2),
        })

    return parts
