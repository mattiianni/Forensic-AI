"""Compressione PDF tramite Ghostscript."""
import os
import shutil
import subprocess


def find_ghostscript() -> str:
    for cmd in ['gs', 'gswin64c', 'gswin32c']:
        if shutil.which(cmd):
            return cmd
    return None


def compress_pdf(input_path: str, output_path: str, quality: str = 'ebook') -> dict:
    """
    Comprimi un PDF con Ghostscript.
    quality: 'screen' (72 dpi) | 'ebook' (150 dpi) | 'printer' (300 dpi)
    Ritorna dict con chiavi: ok, orig_mb, size_mb, reduction_pct, error
    """
    gs = find_ghostscript()
    if not gs:
        return {'ok': False, 'error': 'Ghostscript non trovato (brew install ghostscript)'}

    if quality not in ('screen', 'ebook', 'printer'):
        quality = 'ebook'

    orig_bytes = os.path.getsize(input_path)

    cmd = [
        gs, '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.4',
        f'-dPDFSETTINGS=/{quality}', '-dNOPAUSE', '-dQUIET', '-dBATCH',
        f'-sOutputFile={output_path}', input_path,
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            err = r.stderr.strip() or 'Errore Ghostscript sconosciuto'
            return {'ok': False, 'error': err}
        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            return {'ok': False, 'error': 'File di output vuoto'}

        out_bytes = os.path.getsize(output_path)
        reduction = round((1 - out_bytes / orig_bytes) * 100, 1) if orig_bytes else 0
        return {
            'ok': True,
            'orig_mb': round(orig_bytes / (1024 * 1024), 2),
            'size_mb': round(out_bytes / (1024 * 1024), 2),
            'reduction_pct': reduction,
        }
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'Ghostscript timeout (>10 min)'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
