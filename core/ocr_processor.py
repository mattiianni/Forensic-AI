"""
Applicazione OCR italiano ai PDF tramite ocrmypdf.
ocrmypdf usa Tesseract (motore OCR) + Ghostscript (ottimizzazione PDF).
"""

import os
import sys
import shutil
import subprocess


def _run(cmd: list, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def is_available() -> bool:
    """Verifica che il pacchetto ocrmypdf sia installato."""
    try:
        import ocrmypdf  # noqa
        return True
    except ImportError:
        return False


def has_italian_tessdata() -> bool:
    """
    Verifica che Tesseract sia installato e che il pack italiano sia presente.
    Cerca l'eseguibile sia nel PATH che nei percorsi standard di installazione.
    """
    tesseract_cmd = _find_tesseract()
    if not tesseract_cmd:
        return False

    try:
        result = _run([tesseract_cmd, '--list-langs'])
        output = result.stdout + result.stderr
        return 'ita' in output.split()
    except Exception:
        return False


def has_ghostscript() -> bool:
    """
    Verifica che Ghostscript sia installato nel sistema.
    Cerca gs (macOS/Linux) o gswin64c / gswin32c (Windows).
    """
    gs_cmd = _find_ghostscript()
    if not gs_cmd:
        return False

    try:
        result = _run([gs_cmd, '--version'])
        return result.returncode == 0
    except Exception:
        return False


def _find_tesseract() -> str:
    """Trova l'eseguibile Tesseract nel PATH o nei percorsi standard."""
    # PATH
    found = shutil.which('tesseract')
    if found:
        return found

    if sys.platform == 'win32':
        candidates = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            os.path.join(os.environ.get('LOCALAPPDATA', ''),
                         r'Programs\Tesseract-OCR\tesseract.exe'),
            os.path.join(os.environ.get('USERPROFILE', ''),
                         r'AppData\Local\Programs\Tesseract-OCR\tesseract.exe'),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

    elif sys.platform == 'darwin':
        for c in ['/usr/local/bin/tesseract', '/opt/homebrew/bin/tesseract']:
            if os.path.isfile(c):
                return c

    return None


def _find_ghostscript() -> str:
    """Trova l'eseguibile Ghostscript nel PATH o nei percorsi standard."""
    # Nomi possibili
    names = ['gs', 'gswin64c', 'gswin32c', 'gsc']
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    if sys.platform == 'win32':
        import glob as _glob
        patterns = [
            r'C:\Program Files\gs\gs*\bin\gswin64c.exe',
            r'C:\Program Files\gs\gs*\bin\gswin32c.exe',
            r'C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe',
        ]
        for pattern in patterns:
            matches = _glob.glob(pattern)
            if matches:
                return matches[-1]   # versione più recente

    elif sys.platform == 'darwin':
        for c in ['/usr/local/bin/gs', '/opt/homebrew/bin/gs']:
            if os.path.isfile(c):
                return c

    return None


def apply_ocr(input_pdf: str, output_pdf: str, language: str = 'ita') -> bool:
    """
    Applica OCR al PDF specificato e salva il risultato.
    - Se Tesseract non è installato: copia il file senza OCR e solleva RuntimeError.
    - Se Ghostscript manca: usa optimize=0 (nessuna ottimizzazione PDF, ma OCR funziona).
    - Se ocrmypdf fallisce per altri motivi: copia il file e solleva RuntimeError.

    Returns:
        True se l'OCR è andato a buon fine.
    Raises:
        RuntimeError con messaggio leggibile in caso di fallimento.
    """
    # Controlla Tesseract prima di tutto
    tesseract_cmd = _find_tesseract()
    if not tesseract_cmd:
        shutil.copy2(input_pdf, output_pdf)
        raise RuntimeError(
            'Tesseract non trovato — installa Tesseract con il pacchetto lingua italiana. '
            'Il PDF è stato incluso senza testo ricercabile.'
        )

    # Controlla la lingua italiana
    try:
        result = subprocess.run(
            [tesseract_cmd, '--list-langs'],
            capture_output=True, text=True, timeout=10
        )
        langs = (result.stdout + result.stderr).split()
        if 'ita' not in langs:
            shutil.copy2(input_pdf, output_pdf)
            raise RuntimeError(
                'Pacchetto lingua italiana (ita) non installato in Tesseract. '
                'Installa tesseract-lang o il data pack italiano.'
            )
    except RuntimeError:
        raise
    except Exception as e:
        shutil.copy2(input_pdf, output_pdf)
        raise RuntimeError(f'Impossibile verificare le lingue Tesseract: {e}')

    # Ghostscript opzionale: se manca usa optimize=0
    has_gs = _find_ghostscript() is not None
    optimize = 1 if has_gs else 0

    # Aggiungi Tesseract al PATH del processo se non è già trovabile da ocrmypdf
    env_patch = {}
    if sys.platform == 'win32':
        tess_dir = os.path.dirname(tesseract_cmd)
        current_path = os.environ.get('PATH', '')
        if tess_dir.lower() not in current_path.lower():
            env_patch['PATH'] = tess_dir + os.pathsep + current_path

    if env_patch:
        os.environ.update(env_patch)

    try:
        import ocrmypdf

        ocrmypdf.ocr(
            input_pdf,
            output_pdf,
            language=language,
            skip_text=True,          # salta pagine che hanno già testo (molto più veloce)
            optimize=optimize,
            progress_bar=False,
            invalidate_digital_signatures=True,
            jobs=os.cpu_count() or 2,  # parallelizza su tutti i core disponibili
            tesseract_timeout=60,    # max 60s per pagina, poi la salta
        )

        if os.path.isfile(output_pdf) and os.path.getsize(output_pdf) > 0:
            return True

        shutil.copy2(input_pdf, output_pdf)
        return False

    except Exception as e:
        shutil.copy2(input_pdf, output_pdf)
        raise RuntimeError(f'ocrmypdf: {e}')
