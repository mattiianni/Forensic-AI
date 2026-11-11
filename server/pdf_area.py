"""
Area PDF — motore di Pdf50 (Mattia Ianniello) integrato in Forensic Tools.

La pipeline (scansione → conversione → OCR → unione → salvataggio/divisione a 50 MB)
e la post-elaborazione (comprimi, dividi per dimensione/range, estrai testo) sono
quelle originali di Pdf50. Differenze: eventi tramite server.jobs, cartelle scelte
con i dialoghi nativi della finestra, e ogni file già passato all'OCR viene
registrato anche nel fascicolo condiviso (opzione «Aggiungi al fascicolo»).
"""
import os
import shutil
import tempfile
import uuid
from collections import defaultdict

from flask import Blueprint, jsonify, request

from core import converter, file_scanner, ocr_processor, pdf_merger, pdf_splitter, pdf_extractor
from server import jobs, pipeline, store

bp = Blueprint("pdf_area", __name__)

LIMIT_BYTES = 50 * 1024 * 1024   # 50 MB


def _register_in_fascicolo(job_id: str, src: str, ocr_pdf: str):
    fid = jobs.meta(job_id, "fid")
    if not fid or not jobs.meta(job_id, "add_to_fascicolo"):
        return
    try:
        doc_id = pipeline.register_pdf(fid, src, ocr_pdf)
        registered = jobs.meta(job_id, "registered") or []
        registered.append(doc_id)
        job = jobs.get(job_id)
        if job is not None:
            job["registered"] = registered
        jobs.emit(job_id, {"type": "docs_changed"})
    except Exception as e:
        jobs.emit(job_id, {"type": "log", "level": "warning",
                           "message": f"  ⚠ Non aggiunto al fascicolo: {e}"})


def _index_registered(job_id: str):
    """Al termine della pipeline indicizza per la ricerca i file registrati nel fascicolo."""
    fid, docs = jobs.meta(job_id, "fid"), jobs.meta(job_id, "registered") or []
    if fid and docs:
        idx = jobs.create("index", label=f"Indicizzazione {len(docs)} documenti", fid=fid)
        jobs.run(idx, pipeline.index_pending_job, fid, docs)


def _convert_and_ocr(
    job_id: str,
    files: list,
    tmp_dir: str,
    lo_path: str,
    step_convert: int,
    step_ocr: int,
    label_prefix: str = '',
) -> tuple:
    """
    Converte e applica OCR a una lista di file.
    Ritorna (ocr_pdfs, errors).
    """

    def log(msg, level='info'):
        jobs.emit(job_id, {'type': 'log', 'message': msg, 'level': level})

    def progress(current, total, filename, operation, step):
        pct = int(current / total * 100) if total > 0 else 0
        jobs.emit(job_id, {
            'type': 'progress',
            'step': step,
            'current': current,
            'total': total,
            'file': (label_prefix + filename) if label_prefix else filename,
            'operation': operation,
            'percent': pct,
        })

    convert_dir = os.path.join(tmp_dir, f'conv_{uuid.uuid4().hex[:6]}')
    ocr_dir = os.path.join(tmp_dir, f'ocr_{uuid.uuid4().hex[:6]}')
    os.makedirs(convert_dir, exist_ok=True)
    os.makedirs(ocr_dir, exist_ok=True)

    converted_pdfs = []
    errors = []
    total = len(files)

    # ── Conversione ──────────────────────────────────────────────────────────
    for i, fi in enumerate(files):
        if jobs.is_cancelled(job_id):
            return [], errors

        rel = fi['rel_path'] if fi.get('rel_folder') else fi['name']
        progress(i + 1, total, rel, 'Conversione', step_convert)
        log(f'[{i+1}/{total}] Conversione: {rel}')

        try:
            pdf_path = converter.convert_to_pdf(fi['path'], convert_dir, lo_path)
            converted_pdfs.append({'path': pdf_path, 'name': fi['name'], 'index': i, 'src': fi['path']})
            log(f'  ✓ Convertito')
        except Exception as e:
            errors.append({'file': rel, 'error': str(e)})
            log(f'  ⚠ Saltato: {e}', 'warning')

    if not converted_pdfs:
        return [], errors

    # ── OCR ──────────────────────────────────────────────────────────────────
    ocr_pdfs = []
    total_conv = len(converted_pdfs)

    for i, item in enumerate(converted_pdfs):
        if jobs.is_cancelled(job_id):
            return [], errors

        progress(i + 1, total_conv, item['name'], 'OCR Italiano', step_ocr)
        log(f'[{i+1}/{total_conv}] OCR: {item["name"]}')

        ocr_out = os.path.join(ocr_dir, f'ocr_{i:05d}.pdf')
        try:
            ocr_processor.apply_ocr(item['path'], ocr_out)
            log(f'  ✓ OCR applicato')
        except Exception as e:
            shutil.copy2(item['path'], ocr_out)
            log(f'  ⚠ OCR fallito, usato PDF senza OCR: {e}', 'warning')

        ocr_pdfs.append(ocr_out)
        _register_in_fascicolo(job_id, item['src'], ocr_out)

    return ocr_pdfs, errors


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline: salva / split un PDF unito
# ─────────────────────────────────────────────────────────────────────────────

def _save_or_split(
    job_id: str,
    merged_path: str,
    output_dir: str,
    pdf_name: str,
) -> dict:
    """
    Se il PDF è ≤ 50 MB → salvalo direttamente.
    Se > 50 MB → salva l'originale + crea le parti nella sotto-cartella.
    Ritorna un dict con i risultati.
    """

    def log(msg, level='info'):
        jobs.emit(job_id, {'type': 'log', 'message': msg, 'level': level})

    merged_size = os.path.getsize(merged_path)
    merged_mb = merged_size / (1024 * 1024)
    total_pages = pdf_merger.get_page_count(merged_path)

    os.makedirs(output_dir, exist_ok=True)

    if merged_size <= LIMIT_BYTES:
        final_path = os.path.join(output_dir, f'{pdf_name}.pdf')
        shutil.copy2(merged_path, final_path)
        log(f'✓ Salvato: {pdf_name}.pdf ({merged_mb:.1f} MB, {total_pages} pag.)')
        return {
            'result_type': 'single',
            'file': final_path,
            'size_mb': round(merged_mb, 2),
            'total_pages': total_pages,
        }
    else:
        log(f'⚠ {pdf_name}.pdf supera 50 MB ({merged_mb:.1f} MB) → divisione')

        # Salva il file completo
        original_final = os.path.join(output_dir, f'{pdf_name}.pdf')
        shutil.copy2(merged_path, original_final)
        log(f'  Originale salvato: {pdf_name}.pdf ({merged_mb:.1f} MB)')

        # Crea la cartella per le parti
        split_dir = os.path.join(output_dir, pdf_name)
        os.makedirs(split_dir, exist_ok=True)
        log(f'  Cartella creata: {pdf_name}/')

        def split_cb(part_num, total_parts):
            jobs.emit(job_id, {
                'type': 'split_progress',
                'label': pdf_name,
                'current': part_num,
                'total': total_parts,
            })

        parts = pdf_splitter.split_pdf_by_size(
            merged_path, split_dir, pdf_name, progress_callback=split_cb
        )

        for part in parts:
            log(
                f'  ✓ {part["name"]} — '
                f'{part["num_pages"]} pag., {part["size_mb"]} MB '
                f'(pagine {part["pages"]})'
            )

        log(f'✓ Divisione completata: {len(parts)} parti')

        return {
            'result_type': 'split',
            'original_file': original_final,
            'split_dir': split_dir,
            'parts': parts,
            'total_parts': len(parts),
            'size_mb': round(merged_mb, 2),
            'total_pages': total_pages,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Modalità 1: PDF UNICO (tutte le sottocartelle unite)
# ─────────────────────────────────────────────────────────────────────────────

def _run_unified(job_id: str, source_path: str, output_path: str):

    def log(msg, level='info'):
        jobs.emit(job_id, {'type': 'log', 'message': msg, 'level': level})

    lo_path = converter.find_libreoffice()
    tmp_dir = None

    try:
        tmp_dir = tempfile.mkdtemp(prefix='splitpdf50_u_')

        # Step 1: Scansione
        jobs.emit(job_id, {'type': 'step', 'step': 1, 'label': 'Scansione file'})
        log(f'Scansione: {source_path}')
        files = file_scanner.scan(source_path)
        total_files = len(files)

        if total_files == 0:
            jobs.emit(job_id, {'type': 'fatal_error',
                           'message': 'Nessun file supportato trovato.'})
            return

        log(f'Trovati {total_files} file')
        jobs.emit(job_id, {'type': 'scan_done', 'total': total_files})

        # Step 2 + 3: Converti + OCR
        jobs.emit(job_id, {'type': 'step', 'step': 2, 'label': 'Conversione in PDF'})
        ocr_pdfs, errors = _convert_and_ocr(
            job_id, files, tmp_dir, lo_path,
            step_convert=2, step_ocr=3
        )

        if jobs.is_cancelled(job_id):
            return

        if not ocr_pdfs:
            jobs.emit(job_id, {'type': 'fatal_error',
                           'message': 'Nessun file convertito con successo.'})
            return

        # Step 4: Unione
        jobs.emit(job_id, {'type': 'step', 'step': 4, 'label': 'Unione PDF'})
        log(f'Unione di {len(ocr_pdfs)} PDF...')

        folder_name = jobs.meta(job_id, 'folder_name') or \
                      os.path.basename(source_path.rstrip('/\\'))
        merged_path = os.path.join(tmp_dir, f'{folder_name}_merged.pdf')

        ok = pdf_merger.merge_pdfs(ocr_pdfs, merged_path)
        if not ok:
            jobs.emit(job_id, {'type': 'fatal_error',
                           'message': "Errore durante l'unione dei PDF."})
            return

        merged_mb = os.path.getsize(merged_path) / (1024 * 1024)
        total_pages = pdf_merger.get_page_count(merged_path)
        log(f'✓ Unione completata: {total_pages} pagine, {merged_mb:.1f} MB')

        # Step 5: Salva / Split
        jobs.emit(job_id, {'type': 'step', 'step': 5, 'label': 'Salvataggio'})
        result = _save_or_split(job_id, merged_path, output_path, folder_name)

        if errors:
            log(f'')
            log(f'File non elaborati ({len(errors)}):', 'warning')
            for e in errors:
                log(f'  • {e["file"]}: {e["error"]}', 'warning')

        log('Elaborazione completata.')
        jobs.emit(job_id, {**result, 'type': 'done', 'errors': errors,
                       'output_path': output_path, 'mode': 'unified'})

    except Exception as e:
        import traceback
        jobs.emit(job_id, {'type': 'fatal_error', 'message': str(e),
                       'detail': traceback.format_exc()})
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if jobs.meta(job_id, 'source_is_temp', False):
            shutil.rmtree(source_path, ignore_errors=True)
        _index_registered(job_id)


# ─────────────────────────────────────────────────────────────────────────────
# Modalità 2: PDF PER SOTTOCARTELLA
# ─────────────────────────────────────────────────────────────────────────────

def _run_per_folder(job_id: str, source_path: str, output_path: str):
    """
    Crea un PDF separato per ogni prima-livello di sottocartella.
    I file nella radice vengono inclusi in un PDF con il nome della cartella sorgente.
    """

    def log(msg, level='info'):
        jobs.emit(job_id, {'type': 'log', 'message': msg, 'level': level})

    lo_path = converter.find_libreoffice()
    tmp_dir = None

    try:
        tmp_dir = tempfile.mkdtemp(prefix='splitpdf50_p_')

        # Step 1: Scansione
        jobs.emit(job_id, {'type': 'step', 'step': 1, 'label': 'Scansione file'})
        log(f'Scansione: {source_path}')
        files = file_scanner.scan(source_path)
        total_files = len(files)

        if total_files == 0:
            jobs.emit(job_id, {'type': 'fatal_error',
                           'message': 'Nessun file supportato trovato.'})
            return

        log(f'Trovati {total_files} file')
        jobs.emit(job_id, {'type': 'scan_done', 'total': total_files})

        # Raggruppa per prima sottocartella (livello 1)
        root_folder_name = jobs.meta(job_id, 'folder_name') or \
                           os.path.basename(source_path.rstrip('/\\'))
        groups = defaultdict(list)

        for fi in files:
            rel_folder = fi.get('rel_folder', '')
            if not rel_folder or rel_folder == '.':
                group_key = root_folder_name
            else:
                # Prima componente del percorso relativo
                parts = rel_folder.replace('\\', '/').split('/')
                group_key = parts[0]
            groups[group_key].append(fi)

        # Se tutti i file finiscono in un unico gruppo di primo livello,
        # prova a scendere al livello successivo per produrre più gruppi.
        # Se anche quello è unico (o non esiste), e il nome non è già il
        # nome della cartella radice, prefissa con "radice - gruppo"
        # (es. "RENDICONTI - DICH.SPESA IVSALBIS").
        if len(groups) == 1:
            only_key = next(iter(groups))
            drill = defaultdict(list)
            for fi in groups[only_key]:
                rf = fi.get('rel_folder', '')
                parts = rf.replace('\\', '/').split('/') if rf else []
                if len(parts) >= 2 and parts[0] == only_key:
                    full_key = f'{only_key} - {parts[1]}'
                    drill[full_key].append(fi)
                else:
                    drill[only_key].append(fi)
            if len(drill) > 1:
                log(f'  → unico gruppo "{only_key}", scendo al livello successivo')
                groups = drill
            elif only_key != root_folder_name:
                # Unico sottogruppo e non si può scendere: prefissa con il nome radice
                new_key = f'{root_folder_name} - {only_key}'
                log(f'  → unico gruppo "{only_key}", rinominato in "{new_key}"')
                groups = {new_key: groups[only_key]}

        group_keys = sorted(groups.keys(), key=lambda k: k.lower())
        total_groups = len(group_keys)
        log(f'Sottocartelle da elaborare: {total_groups}')

        all_errors = []
        all_results = []

        for g_idx, group_key in enumerate(group_keys):
            if jobs.is_cancelled(job_id):
                log('Annullato.', 'warning')
                return

            group_files = groups[group_key]
            log(f'')
            log(f'── Sottocartella {g_idx+1}/{total_groups}: "{group_key}" ({len(group_files)} file)')
            jobs.emit(job_id, {
                'type': 'folder_start',
                'folder': group_key,
                'current': g_idx + 1,
                'total': total_groups,
                'file_count': len(group_files),
            })

            sub_tmp = os.path.join(tmp_dir, f'group_{g_idx:03d}')
            os.makedirs(sub_tmp, exist_ok=True)

            # Converti + OCR per questo gruppo
            jobs.emit(job_id, {'type': 'step', 'step': 2,
                           'label': f'Conversione: {group_key}'})
            ocr_pdfs, errors = _convert_and_ocr(
                job_id, group_files, sub_tmp, lo_path,
                step_convert=2, step_ocr=3,
                label_prefix=f'{group_key}/',
            )

            if jobs.is_cancelled(job_id):
                return

            all_errors.extend(errors)

            if not ocr_pdfs:
                log(f'  ⚠ Nessun file convertito per "{group_key}", saltato.', 'warning')
                continue

            # Unione del gruppo
            log(f'  Unione di {len(ocr_pdfs)} PDF per "{group_key}"...')
            merged_path = os.path.join(sub_tmp, f'{group_key}_merged.pdf')
            ok = pdf_merger.merge_pdfs(ocr_pdfs, merged_path)

            if not ok:
                log(f'  ✗ Unione fallita per "{group_key}"', 'error')
                all_errors.append({'file': group_key, 'error': 'Unione fallita'})
                continue

            merged_mb = os.path.getsize(merged_path) / (1024 * 1024)
            log(f'  ✓ Unione: {merged_mb:.1f} MB')

            # Salva / split per questo gruppo
            jobs.emit(job_id, {'type': 'step', 'step': 5,
                           'label': f'Salvataggio: {group_key}'})
            result = _save_or_split(job_id, merged_path, output_path, group_key)
            result['folder'] = group_key
            all_results.append(result)

        if all_errors:
            log(f'')
            log(f'File non elaborati ({len(all_errors)}):', 'warning')
            for e in all_errors:
                log(f'  • {e["file"]}: {e["error"]}', 'warning')

        log('')
        log(f'Elaborazione completata. {total_groups} PDF creati.')
        jobs.emit(job_id, {
            'type': 'done',
            'mode': 'per_folder',
            'output_path': output_path,
            'results': all_results,
            'total_groups': total_groups,
            'errors': all_errors,
        })

    except Exception as e:
        import traceback
        jobs.emit(job_id, {'type': 'fatal_error', 'message': str(e),
                       'detail': traceback.format_exc()})
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if jobs.meta(job_id, 'source_is_temp', False):
            shutil.rmtree(source_path, ignore_errors=True)
        _index_registered(job_id)




# ── Post-elaborazione (identica a Pdf50) ──

@bp.route('/api/pdf/post/compress', methods=['POST'])
def post_compress():
    from core import pdf_compressor
    data = request.get_json() or {}
    pdf_path   = data.get('pdf_path',   '').strip()
    quality    = data.get('quality',    'ebook')
    output_dir = (data.get('output_dir') or '').strip()

    if not pdf_path or not os.path.isfile(pdf_path):
        return jsonify({'ok': False, 'error': 'File non trovato'}), 400

    if not output_dir:
        output_dir = os.path.dirname(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out  = os.path.join(output_dir, f'{base}_compresso.pdf')

    result = pdf_compressor.compress_pdf(pdf_path, out, quality)
    if result['ok']:
        result['output_path'] = out
        result['filename']    = os.path.basename(out)
    return jsonify(result)


@bp.route('/api/pdf/post/split-size', methods=['POST'])
def post_split_size():
    data = request.get_json() or {}
    pdf_path   = data.get('pdf_path',  '').strip()
    target_mb  = float(data.get('target_mb', 46))
    output_dir = (data.get('output_dir') or '').strip()

    if not pdf_path or not os.path.isfile(pdf_path):
        return jsonify({'ok': False, 'error': 'File non trovato'}), 400

    if not output_dir:
        output_dir = os.path.dirname(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    base    = os.path.splitext(os.path.basename(pdf_path))[0]
    sub_dir = os.path.join(output_dir, base)
    os.makedirs(sub_dir, exist_ok=True)

    part_label = (data.get('part_label') or 'Parte').strip() or 'Parte'
    show_total = bool(data.get('show_total', True))

    try:
        target_bytes = int(target_mb * 1024 * 1024)
        parts = pdf_splitter.split_pdf_by_size(
            pdf_path, sub_dir, base, target_bytes=target_bytes,
            part_label=part_label, show_total=show_total,
        )
        return jsonify({'ok': True, 'parts': parts, 'split_dir': sub_dir})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@bp.route('/api/pdf/post/split-ranges', methods=['POST'])
def post_split_ranges():
    data = request.get_json() or {}
    pdf_path   = data.get('pdf_path',  '').strip()
    ranges     = data.get('ranges',    [])   # [[start, end], ...]
    output_dir = (data.get('output_dir') or '').strip()

    if not pdf_path or not os.path.isfile(pdf_path):
        return jsonify({'ok': False, 'error': 'File non trovato'}), 400
    if not ranges:
        return jsonify({'ok': False, 'error': 'Nessun range specificato'}), 400

    if not output_dir:
        output_dir = os.path.dirname(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    part_label = (data.get('part_label') or 'Parte').strip() or 'Parte'
    show_total = bool(data.get('show_total', True))

    try:
        parts = pdf_splitter.split_by_ranges(pdf_path, ranges, output_dir,
                                             part_label=part_label, show_total=show_total)
        return jsonify({'ok': True, 'parts': parts})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@bp.route('/api/pdf/post/page-count', methods=['POST'])
def post_page_count():
    data = request.get_json() or {}
    pdf_path = data.get('pdf_path', '').strip()
    if not pdf_path or not os.path.isfile(pdf_path):
        return jsonify({'ok': False, 'error': 'File non trovato'}), 400
    try:
        pages = pdf_merger.get_page_count(pdf_path)
        return jsonify({'ok': True, 'pages': pages})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@bp.route('/api/pdf/post/extract-text', methods=['POST'])
def post_extract_text():
    data       = request.get_json() or {}
    pdf_path   = data.get('pdf_path',  '').strip()
    output_dir = (data.get('output_dir') or '').strip()

    if not pdf_path or not os.path.isfile(pdf_path):
        return jsonify({'ok': False, 'error': 'File non trovato'}), 400

    if not output_dir:
        output_dir = os.path.dirname(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    base     = os.path.splitext(os.path.basename(pdf_path))[0]
    out_path = os.path.join(output_dir, f'{base}.txt')

    result = pdf_extractor.extract_text(pdf_path, out_path)
    if result['ok']:
        result['output_path'] = out_path
    return jsonify(result)



# ── Sorgenti e avvio job ─────────────────────────────────────────────────────

@bp.route('/api/pdf/scan', methods=['POST'])
def pdf_scan():
    """Conta i file supportati in una cartella scelta col dialogo nativo o trascinata."""
    path = ((request.get_json() or {}).get('path') or '').strip()
    if not path or not os.path.isdir(path):
        return jsonify({'error': 'Cartella non valida'}), 400
    return jsonify({'path': path, 'file_count': len(file_scanner.scan(path)),
                    'folder_name': os.path.basename(path.rstrip('/'))})


@bp.route('/api/pdf/prepare-files', methods=['POST'])
def pdf_prepare_files():
    """
    File trascinati: un singolo PDF → modalità PDF diretta (comprimi/dividi/estrai);
    altrimenti i file vengono raccolti in una cartella temporanea (come l'upload di Pdf50).
    """
    paths = [p for p in (request.get_json() or {}).get('paths', []) if os.path.isfile(p)]
    if not paths:
        return jsonify({'error': 'Nessun file valido'}), 400
    if len(paths) == 1 and paths[0].lower().endswith('.pdf'):
        p = paths[0]
        pages = None
        try:
            pages = pdf_merger.get_page_count(p)
        except Exception:
            pass
        return jsonify({'is_pdf': True, 'path': p, 'filename': os.path.basename(p),
                        'size_mb': round(os.path.getsize(p) / (1024 * 1024), 2), 'pages': pages})
    tmp_dir = tempfile.mkdtemp(prefix='splitpdf50_up_')
    for p in paths:
        os.symlink(p, os.path.join(tmp_dir, os.path.basename(p)))
    name = os.path.splitext(os.path.basename(paths[0]))[0] if len(paths) == 1 else 'File selezionati'
    return jsonify({'is_pdf': False, 'tmp_dir': tmp_dir, 'folder_name': name,
                    'file_count': len(file_scanner.scan(tmp_dir))})


@bp.route('/api/pdf/cleanup-temp', methods=['POST'])
def cleanup_temp():
    path = ((request.get_json() or {}).get('path') or '').strip()
    tmp_base = tempfile.gettempdir()
    if path and os.path.isabs(path):
        try:
            if os.path.commonpath([os.path.realpath(path), os.path.realpath(tmp_base)]) == os.path.realpath(tmp_base):
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass
    return jsonify({'ok': True})


@bp.route('/api/pdf/start', methods=['POST'])
def start_job():
    data = request.get_json() or {}
    source = (data.get('source_path') or '').strip()
    output = (data.get('output_path') or '').strip()
    mode = data.get('mode', 'unified')
    folder_name = (data.get('folder_name') or '').strip() or os.path.basename(source.rstrip('/'))
    if not source or not os.path.isdir(source):
        return jsonify({'error': 'Cartella sorgente non valida'}), 400
    if not output:
        return jsonify({'error': 'Cartella di destinazione non specificata'}), 400
    if mode not in ('unified', 'per_folder'):
        return jsonify({'error': 'Modalità non valida'}), 400
    fid = data.get('fid')
    job_id = jobs.create('pdf', label=f'PDF · {folder_name}', fid=fid, mode=mode,
                         folder_name=folder_name, source_is_temp=bool(data.get('source_is_temp')),
                         add_to_fascicolo=bool(data.get('add_to_fascicolo')) and bool(fid and store.exists(fid)),
                         registered=[])
    target = _run_unified if mode == 'unified' else _run_per_folder
    jobs.run(job_id, target, source, output)
    return jsonify({'job_id': job_id, 'mode': mode})


@bp.route('/api/pdf/system-info')
def system_info():
    return jsonify({
        'ocrmypdf': ocr_processor.is_available(),
        'tesseract_italian': ocr_processor.has_italian_tessdata(),
        'ghostscript': ocr_processor.has_ghostscript(),
        'ms_office': converter.has_microsoft_office(),
    })
