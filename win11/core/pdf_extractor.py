"""Estrazione testo da PDF tramite pypdf (solo testo, niente immagini)."""
import os


def extract_text(input_path: str, output_path: str) -> dict:
    """
    Estrae il testo da ogni pagina del PDF e lo salva in un file .txt.
    Le pagine senza testo (es. immagini scansionate) vengono saltate.

    Ritorna dict: ok, chars, pages, pages_with_text, size_kb, error
    """
    try:
        import pypdf
    except ImportError:
        return {'ok': False, 'error': 'pypdf non installato'}

    try:
        reader = pypdf.PdfReader(input_path, strict=False)
        total_pages = len(reader.pages)
        chunks = []
        pages_with_text = 0

        for page_num, page in enumerate(reader.pages, 1):
            try:
                text = page.extract_text() or ''
            except Exception:
                text = ''
            text = text.strip()
            if text:
                chunks.append(text)
                pages_with_text += 1

        if not chunks:
            return {
                'ok': False,
                'error': 'Nessun testo trovato — il PDF è probabilmente composto solo da immagini scansionate',
            }

        full_text = '\n\n'.join(chunks)

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(full_text)

        size = os.path.getsize(output_path)
        return {
            'ok': True,
            'chars': len(full_text),
            'pages': total_pages,
            'pages_with_text': pages_with_text,
            'size_kb': round(size / 1024, 1),
            'filename': os.path.basename(output_path),
        }

    except Exception as e:
        return {'ok': False, 'error': str(e)}
