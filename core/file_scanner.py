"""
Scansione ricorsiva della cartella sorgente e ordinamento dei file.
Ordinamento: per cartella (A→Z), poi data nel nome file, poi data di modifica.
"""

import os
import re
from datetime import datetime

# Formati di date italiane comuni nei nomi file
DATE_PATTERNS = [
    # YYYYMMDD
    (re.compile(r'(\d{4})(\d{2})(\d{2})'), lambda m: _date(m[1], m[2], m[3])),
    # YYYY-MM-DD o YYYY_MM_DD
    (re.compile(r'(\d{4})[-_](\d{2})[-_](\d{2})'), lambda m: _date(m[1], m[2], m[3])),
    # DD-MM-YYYY o DD/MM/YYYY o DD_MM_YYYY
    (re.compile(r'(\d{2})[-/_](\d{2})[-/_](\d{4})'), lambda m: _date(m[3], m[2], m[1])),
    # DDMMYYYY (meno comune)
    (re.compile(r'(\d{2})(\d{2})(\d{4})'), lambda m: _date(m[3], m[2], m[1])),
]

ITALIAN_MONTHS = {
    'gen': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'mag': 5, 'giu': 6,
    'lug': 7, 'ago': 8, 'set': 9, 'ott': 10, 'nov': 11, 'dic': 12,
    'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4, 'maggio': 5,
    'giugno': 6, 'luglio': 7, 'agosto': 8, 'settembre': 9, 'ottobre': 10,
    'novembre': 11, 'dicembre': 12,
}

# Estensioni file supportate
SUPPORTED_EXTENSIONS = {
    # Immagini
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp',
    # Documenti Office
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.odt', '.ods', '.odp', '.odg',
    # PDF
    '.pdf',
    # Testo
    '.txt', '.rtf', '.csv',
    # Firmati digitalmente
    '.p7m',
    # HTML
    '.html', '.htm',
    # Altro comune
    '.xml',
}


def _date(year_str, month_str, day_str):
    """Costruisce un datetime da stringhe anno/mese/giorno."""
    try:
        y, m, d = int(year_str), int(month_str), int(day_str)
        if 1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
            return datetime(y, m, d)
    except (ValueError, TypeError):
        pass
    return None


def extract_date_from_name(filename: str):
    """
    Estrae una data dal nome del file.
    Ritorna un datetime o None se non trovata.
    """
    name = os.path.splitext(filename)[0]

    # Cerca mese italiano + anno (es. "gennaio2024" o "gen_2024")
    for month_name, month_num in ITALIAN_MONTHS.items():
        pattern = re.compile(
            rf'\b{re.escape(month_name)}[-_\s]?(\d{{4}})\b', re.IGNORECASE
        )
        m = pattern.search(name)
        if m:
            d = _date(m.group(1), month_num, 1)
            if d:
                return d

    # Cerca pattern numerici di data
    for pattern, builder in DATE_PATTERNS:
        m = pattern.search(name)
        if m:
            d = builder(m)
            if d:
                return d

    return None


def get_file_sort_date(filepath: str, filename: str):
    """
    Ritorna la data da usare per l'ordinamento:
    1. Data nel nome file (se presente)
    2. Data di modifica del file
    """
    date_from_name = extract_date_from_name(filename)
    if date_from_name:
        return date_from_name

    try:
        mtime = os.path.getmtime(filepath)
        return datetime.fromtimestamp(mtime)
    except OSError:
        return datetime.min


def scan(source_path: str) -> list:
    """
    Scansiona ricorsivamente la cartella sorgente.
    Ritorna una lista di dizionari con informazioni su ogni file,
    ordinata per: cartella (A→Z) poi data (crescente).

    Ogni elemento: {
        'path': percorso assoluto,
        'name': nome file,
        'rel_path': percorso relativo dalla sorgente,
        'rel_folder': cartella relativa,
        'ext': estensione minuscola,
        'sort_date': datetime per ordinamento,
        'size': dimensione in byte,
    }
    """
    files = []

    for root, dirs, filenames in os.walk(source_path):
        # Ordina le sottocartelle per percorso alfabetico
        dirs.sort(key=lambda d: d.lower())

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, source_path)
            rel_folder = os.path.relpath(root, source_path)
            if rel_folder == '.':
                rel_folder = ''

            try:
                size = os.path.getsize(abs_path)
            except OSError:
                size = 0

            files.append({
                'path': abs_path,
                'name': filename,
                'rel_path': rel_path,
                'rel_folder': rel_folder,
                'ext': ext,
                'sort_date': get_file_sort_date(abs_path, filename),
                'size': size,
            })

    # Ordinamento principale: cartella (A→Z), poi data (crescente), poi nome
    files.sort(key=lambda f: (
        f['rel_folder'].lower(),
        f['sort_date'],
        f['name'].lower(),
    ))

    return files
