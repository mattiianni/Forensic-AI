"""
Estrazione del contenuto da file P7M (CMS SignedData).
Il P7M è una busta crittografica usata per la firma digitale italiana.
Supporta P7M annidati (firme multiple).
"""

import os
import io
import zipfile
import tempfile
import subprocess
import struct


def detect_content_type(data: bytes) -> tuple:
    """
    Rileva il tipo di contenuto dai magic bytes.
    Ritorna (mime_type, estensione).
    """
    if len(data) < 8:
        return ('application/octet-stream', '.bin')

    # PDF
    if data[:4] == b'%PDF':
        return ('application/pdf', '.pdf')

    # ZIP-based (DOCX, XLSX, PPTX, ODT, ODS, ODP)
    if data[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                if 'word/document.xml' in names:
                    return ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx')
                if 'xl/workbook.xml' in names:
                    return ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx')
                if 'ppt/presentation.xml' in names:
                    return ('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx')
                if 'content.xml' in names:
                    # LibreOffice format - check mimetype
                    try:
                        mt = z.read('mimetype').decode('utf-8', errors='ignore').strip()
                        if 'writer' in mt:
                            return ('application/vnd.oasis.opendocument.text', '.odt')
                        if 'calc' in mt:
                            return ('application/vnd.oasis.opendocument.spreadsheet', '.ods')
                        if 'impress' in mt:
                            return ('application/vnd.oasis.opendocument.presentation', '.odp')
                    except Exception:
                        pass
                    return ('application/vnd.oasis.opendocument.text', '.odt')
        except Exception:
            pass
        return ('application/zip', '.zip')

    # JPEG
    if data[:2] == b'\xff\xd8':
        return ('image/jpeg', '.jpg')

    # PNG
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return ('image/png', '.png')

    # GIF
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return ('image/gif', '.gif')

    # TIFF
    if data[:4] in (b'II*\x00', b'MM\x00*'):
        return ('image/tiff', '.tiff')

    # BMP
    if data[:2] == b'BM':
        return ('image/bmp', '.bmp')

    # RTF
    if data[:5] == b'{\\rtf':
        return ('application/rtf', '.rtf')

    # XML / FatturaPA
    try:
        decoded = data[:200].decode('utf-8', errors='ignore').strip()
        if decoded.startswith('<?xml') or decoded.startswith('<'):
            return ('application/xml', '.xml')
    except Exception:
        pass

    # P7M annidato
    # Cerca header DER per ContentInfo (sequenza: 0x30 + lunghezza)
    if data[0] == 0x30:
        try:
            from asn1crypto import cms
            inner_ci = cms.ContentInfo.load(data)
            if inner_ci['content_type'].native == 'signed_data':
                return ('application/pkcs7-mime', '.p7m')
        except Exception:
            pass

    # Testo semplice
    try:
        data[:512].decode('utf-8')
        return ('text/plain', '.txt')
    except UnicodeDecodeError:
        pass

    return ('application/octet-stream', '.bin')


def _extract_with_asn1crypto(data: bytes) -> tuple:
    """
    Estrae il contenuto usando asn1crypto.
    Ritorna (content_bytes, is_nested_p7m) o (None, False) in caso di errore.
    """
    try:
        from asn1crypto import cms
        content_info = cms.ContentInfo.load(data)

        if content_info['content_type'].native != 'signed_data':
            return None, False

        signed_data = content_info['content']
        encap = signed_data['encap_content_info']
        inner_content_type = encap['content_type'].native

        content_obj = encap['content']
        if content_obj.native is None:
            return None, False

        # Ottieni i byte del contenuto interno
        inner_bytes = content_obj.parsed.contents if hasattr(content_obj.parsed, 'contents') else content_obj.native

        if inner_bytes is None:
            return None, False

        if isinstance(inner_bytes, str):
            inner_bytes = inner_bytes.encode('utf-8')

        return inner_bytes, False

    except Exception:
        return None, False


def _extract_with_openssl(p7m_path: str) -> bytes:
    """
    Usa openssl come fallback per estrarre il contenuto.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix='.content', delete=False) as tmp:
            tmp_out = tmp.name

        # Prova DER
        result = subprocess.run(
            ['openssl', 'smime', '-verify', '-in', p7m_path,
             '-noverify', '-inform', 'DER', '-out', tmp_out],
            capture_output=True, timeout=30
        )

        if result.returncode != 0:
            # Prova PEM
            result = subprocess.run(
                ['openssl', 'smime', '-verify', '-in', p7m_path,
                 '-noverify', '-inform', 'PEM', '-out', tmp_out],
                capture_output=True, timeout=30
            )

        if os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
            with open(tmp_out, 'rb') as f:
                content = f.read()
            os.unlink(tmp_out)
            return content

    except Exception:
        pass
    finally:
        try:
            if os.path.exists(tmp_out):
                os.unlink(tmp_out)
        except Exception:
            pass

    return None


def extract_p7m(p7m_path: str, output_dir: str, depth: int = 0) -> str:
    """
    Estrae il contenuto da un file P7M e lo salva nella output_dir.
    Gestisce P7M annidati ricorsivamente (max depth 5).
    Ritorna il percorso del file estratto, o None in caso di errore.
    """
    if depth > 5:
        return None

    with open(p7m_path, 'rb') as f:
        data = f.read()

    # Gestisci PEM (base64 con header)
    if data[:5] == b'-----':
        try:
            import base64
            lines = data.decode('ascii', errors='ignore').split('\n')
            b64_lines = [l for l in lines if not l.startswith('-----') and l.strip()]
            data = base64.b64decode(''.join(b64_lines))
        except Exception:
            pass

    # Tentativo 1: asn1crypto
    inner_bytes, _ = _extract_with_asn1crypto(data)

    # Tentativo 2: openssl
    if inner_bytes is None:
        inner_bytes = _extract_with_openssl(p7m_path)

    if inner_bytes is None:
        return None

    # Rileva il tipo del contenuto
    mime, ext = detect_content_type(inner_bytes)

    # Salva il file estratto
    base_name = os.path.splitext(os.path.basename(p7m_path))[0]
    extracted_path = os.path.join(output_dir, f'p7m_extracted_{base_name}{ext}')

    with open(extracted_path, 'wb') as f:
        f.write(inner_bytes)

    # Se il contenuto è un altro P7M, estraiamo ricorsivamente
    if ext == '.p7m':
        nested_result = extract_p7m(extracted_path, output_dir, depth + 1)
        os.unlink(extracted_path)
        return nested_result

    return extracted_path
