"""
Unione di più PDF in un unico file, nell'ordine fornito.
"""

import os


def merge_pdfs(pdf_paths: list, output_path: str) -> bool:
    """
    Unisce i PDF nella lista (in ordine) e salva in output_path.

    Args:
        pdf_paths:   lista di percorsi PDF da unire (già nell'ordine corretto)
        output_path: percorso del PDF risultante

    Returns:
        True se l'unione è riuscita, False altrimenti.
    """
    if not pdf_paths:
        return False

    # Filtra i file che esistono effettivamente
    valid_paths = [p for p in pdf_paths if os.path.isfile(p) and os.path.getsize(p) > 0]

    if not valid_paths:
        return False

    try:
        import pypdf

        writer = pypdf.PdfWriter()

        for pdf_path in valid_paths:
            try:
                reader = pypdf.PdfReader(pdf_path, strict=False)
                for page in reader.pages:
                    writer.add_page(page)
            except Exception as e:
                # Se un singolo PDF è corrotto, lo saltiamo
                print(f'[merge] Saltato PDF corrotto: {pdf_path} - {e}')
                continue

        if len(writer.pages) == 0:
            return False

        with open(output_path, 'wb') as f:
            writer.write(f)

        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0

    except Exception as e:
        raise RuntimeError(f'Errore durante l\'unione PDF: {e}')


def get_page_count(pdf_path: str) -> int:
    """Ritorna il numero di pagine di un PDF."""
    try:
        import pypdf
        reader = pypdf.PdfReader(pdf_path, strict=False)
        return len(reader.pages)
    except Exception:
        return 0
