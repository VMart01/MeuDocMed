"""
Rotas do paciente: painel, documentos, medicamentos, acessos,
links de compartilhamento, histórico, perfil, SSE de notificações.
"""
import io
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, session, current_app, send_file,
                   Response, jsonify, abort)

from models import (db, Patient, Document, Medication, AccessRequest,
                    ShareLink, AccessLog, DOCUMENT_CATEGORIES,
                    MEDICATION_ROUTES, ACCESS_DURATIONS)
from utils.file_utils import (allowed_extension, validate_magic_number,
                               generate_unique_filename, get_mime_type,
                               is_viewable_inline, get_extension)
from utils import storage
import storage_shamir
from utils.notifications import sse_stream
from utils.pdf_utils import generate_history_pdf

patient_bp = Blueprint('patient', __name__, url_prefix='/paciente')


# ---------------------------------------------------------------------------
# Decorador de autenticação
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('user_type') != 'patient':
            flash('Faça login para continuar.', 'warning')
            return redirect(url_for('auth.login_paciente'))
        return f(*args, **kwargs)
    return decorated


def get_current_patient() -> Patient:
    return Patient.query.get_or_404(session['user_id'])


def get_client_ip():
    return (request.headers.get('X-Forwarded-For',
                                request.remote_addr) or '').split(',')[0].strip()


def log_action(patient_id, action, description='', professional_id=None,
               performed_by='patient'):
    log = AccessLog(
        patient_id=patient_id,
        professional_id=professional_id,
        action=action,
        description=description,
        ip_address=get_client_ip(),
        performed_by=performed_by,
    )
    db.session.add(log)
    db.session.commit()


def _get_doc_bytes(doc, upload_folder):
    """Recupera bytes do documento respeitando storage_type."""
    if doc.storage_type == 'shamir' and doc.storage_meta:
        try:
            import json as _json
            meta = _json.loads(doc.storage_meta)
            return storage_shamir.download_shamir(
                meta['file_id'], meta['ext'], meta['nonce_hex'], meta['salt_hex'])
        except Exception:
            return None
    return storage.get_file_bytes(doc.filename, upload_folder)



# ---------------------------------------------------------------------------
# Painel
# ---------------------------------------------------------------------------
@patient_bp.route('/painel')
@login_required
def dashboard():
    patient = get_current_patient()

    # Estatísticas por categoria
    docs = patient.documents.all()
    cat_stats = {}
    for cat_key, cat_label in DOCUMENT_CATEGORIES:
        count = sum(1 for d in docs if d.category == cat_key)
        if count > 0:
            cat_stats[cat_label] = count

    # Últimas entradas do log
    recent_logs = (patient.access_logs
                   .order_by(AccessLog.created_at.desc())
                   .limit(10).all())

    # Medicamentos ativos
    active_meds_count = patient.medications.filter_by(is_active=True).count()

    # Solicitações pendentes
    pending_requests = (
        AccessRequest.query
        .filter_by(patient_id=patient.id, status='pending')
        .all()
    )

    # Últimos documentos
    recent_docs = (patient.documents
                   .order_by(Document.created_at.desc())
                   .limit(5).all())

    return render_template('paciente/painel.html',
                           patient=patient,
                           cat_stats=cat_stats,
                           recent_logs=recent_logs,
                           active_meds_count=active_meds_count,
                           pending_requests=pending_requests,
                           recent_docs=recent_docs,
                           total_docs=len(docs))


# ---------------------------------------------------------------------------
# SSE — Notificações em tempo real
# ---------------------------------------------------------------------------
@patient_bp.route('/notificacoes/stream')
@login_required
def notifications_stream():
    patient_id = session['user_id']

    def generate():
        for chunk in sse_stream(patient_id):
            yield chunk

    return Response(generate(), mimetype='text/event-stream',
                    headers={
                        'Cache-Control': 'no-cache',
                        'X-Accel-Buffering': 'no',
                    })


# ---------------------------------------------------------------------------
# Documentos — Listagem
# ---------------------------------------------------------------------------
@patient_bp.route('/documentos')
@login_required
def documentos():
    patient = get_current_patient()
    category = request.args.get('category', '')
    search = request.args.get('search', '').strip()
    order = request.args.get('order', 'recent')

    query = patient.documents

    if category:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(Document.name.ilike(f'%{search}%'))

    if order == 'oldest':
        query = query.order_by(Document.created_at.asc())
    elif order == 'alpha':
        query = query.order_by(Document.name.asc())
    else:
        query = query.order_by(Document.created_at.desc())

    page = request.args.get('page', 1, type=int)
    per_page = 10
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('paciente/documentos.html',
                           patient=patient,
                           docs=pagination.items,
                           pagination=pagination,
                           categories=DOCUMENT_CATEGORIES,
                           selected_category=category,
                           search=search,
                           order=order)


# ---------------------------------------------------------------------------
# Documentos — Upload
# ---------------------------------------------------------------------------
@patient_bp.route('/documentos/upload', methods=['GET', 'POST'])
@login_required
def upload_documento():
    patient = get_current_patient()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '')
        observation = request.form.get('observation', '').strip()
        file = request.files.get('file')

        errors = []

        if not name:
            errors.append('Nome do documento é obrigatório.')
        if category not in dict(DOCUMENT_CATEGORIES):
            errors.append('Categoria inválida.')
        if not file or not file.filename:
            errors.append('Selecione um arquivo.')
        elif not allowed_extension(file.filename):
            errors.append('Formato de arquivo não permitido.')

        if not errors and file:
            file_bytes = file.read()
            ext = get_extension(file.filename)

            if not validate_magic_number(file_bytes, ext):
                errors.append(
                    'O conteúdo do arquivo não corresponde à extensão declarada. '
                    'Por segurança, o envio foi bloqueado.'
                )

            file_size = len(file_bytes)
            if file_size > current_app.config['MAX_CONTENT_LENGTH']:
                errors.append('Arquivo excede o limite de 16 MB.')

            if not errors:
                # Shamir se todas as clouds estiverem configuradas; senão Cloudinary/local
                if storage_shamir.shamir_configured():
                    result = storage_shamir.upload_shamir(file_bytes, file.filename)
                    if result is None:
                        errors.append('Falha ao armazenar o arquivo nas clouds. Tente novamente.')
                    else:
                        meta = json.dumps({
                            'file_id':   result['file_id'],
                            'ext':       result['ext'],
                            'nonce_hex': result['nonce_hex'],
                            'salt_hex':  result['salt_hex'],
                        })
                        doc = Document(
                            patient_id=patient.id,
                            name=name,
                            category=category,
                            filename=result['file_id'],
                            original_filename=file.filename,
                            file_size=file_size,
                            observation=observation or None,
                            storage_type='shamir',
                            storage_meta=meta,
                        )
                else:
                    stored_id = storage.upload_file(file_bytes, file.filename)
                    if not storage._cloudinary_configured():
                        upload_folder = current_app.config['UPLOAD_FOLDER']
                        os.makedirs(upload_folder, exist_ok=True)
                        with open(os.path.join(upload_folder, stored_id), 'wb') as f_out:
                            f_out.write(file_bytes)
                    doc = Document(
                        patient_id=patient.id,
                        name=name,
                        category=category,
                        filename=stored_id,
                        original_filename=file.filename,
                        file_size=file_size,
                        observation=observation or None,
                        storage_type='cloudinary' if storage._cloudinary_configured() else 'local',
                    )

                if errors:
                    for e in errors:
                        flash(e, 'danger')
                    return render_template('paciente/upload.html', patient=patient,
                                           categories=DOCUMENT_CATEGORIES)
                db.session.add(doc)
                db.session.flush()

                log_action(patient.id, 'upload',
                           f'Documento "{name}" enviado ({file.filename}).')
                flash('Documento enviado com sucesso!', 'success')
                return redirect(url_for('patient.documentos'))

        for e in errors:
            flash(e, 'danger')

    return render_template('paciente/upload.html',
                           patient=patient,
                           categories=DOCUMENT_CATEGORIES)


# ---------------------------------------------------------------------------
# Documentos — Visualizar / Download
# ---------------------------------------------------------------------------
@patient_bp.route('/documentos/<int:doc_id>/visualizar')
@login_required
def visualizar_documento(doc_id):
    patient = get_current_patient()
    doc = Document.query.filter_by(id=doc_id, patient_id=patient.id).first_or_404()

    file_bytes = _get_doc_bytes(doc, current_app.config['UPLOAD_FOLDER'])

    if file_bytes is None:
        flash('Arquivo não encontrado no servidor.', 'danger')
        return redirect(url_for('patient.documentos'))

    mime = get_mime_type(doc.original_filename)
    inline = is_viewable_inline(doc.original_filename)

    log_action(patient.id, 'view_doc',
               f'Visualizou documento "{doc.name}".')

    return send_file(
        io.BytesIO(file_bytes),
        mimetype=mime,
        as_attachment=not inline,
        download_name=doc.original_filename if not inline else None,
    )


# ---------------------------------------------------------------------------
# Documentos — Download explícito
# ---------------------------------------------------------------------------
@patient_bp.route('/documentos/<int:doc_id>/download')
@login_required
def download_documento(doc_id):
    patient = get_current_patient()
    doc = Document.query.filter_by(id=doc_id, patient_id=patient.id).first_or_404()

    file_bytes = _get_doc_bytes(doc, current_app.config['UPLOAD_FOLDER'])

    if file_bytes is None:
        flash('Arquivo não encontrado no servidor.', 'danger')
        return redirect(url_for('patient.documentos'))

    mime = get_mime_type(doc.original_filename)
    log_action(patient.id, 'view_doc',
               f'Download do documento "{doc.name}".')

    return send_file(io.BytesIO(file_bytes), mimetype=mime, as_attachment=True,
                     download_name=doc.original_filename)


# ---------------------------------------------------------------------------
# Documentos — Editar
# ---------------------------------------------------------------------------
@patient_bp.route('/documentos/<int:doc_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_documento(doc_id):
    patient = get_current_patient()
    doc = Document.query.filter_by(id=doc_id, patient_id=patient.id).first_or_404()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '')
        observation = request.form.get('observation', '').strip()

        if not name:
            flash('Nome é obrigatório.', 'danger')
        elif category not in dict(DOCUMENT_CATEGORIES):
            flash('Categoria inválida.', 'danger')
        else:
            doc.name = name
            doc.category = category
            doc.observation = observation or None
            doc.updated_at = datetime.utcnow()
            db.session.commit()

            log_action(patient.id, 'edit_doc',
                       f'Documento "{name}" editado.')
            flash('Documento atualizado.', 'success')
            return redirect(url_for('patient.documentos'))

    return render_template('paciente/editar_documento.html',
                           patient=patient, doc=doc,
                           categories=DOCUMENT_CATEGORIES)


# ---------------------------------------------------------------------------
# Documentos — Excluir
# ---------------------------------------------------------------------------
@patient_bp.route('/documentos/<int:doc_id>/excluir', methods=['POST'])
@login_required
def excluir_documento(doc_id):
    patient = get_current_patient()
    doc = Document.query.filter_by(id=doc_id, patient_id=patient.id).first_or_404()

    name = doc.name
    if doc.storage_type == 'shamir' and doc.storage_meta:
        import json as _json
        try:
            meta = _json.loads(doc.storage_meta)
            storage_shamir.delete_shamir(meta['file_id'], meta['ext'])
        except Exception:
            pass
    else:
        storage.delete_stored_file(doc.filename, current_app.config['UPLOAD_FOLDER'])
    db.session.delete(doc)
    db.session.flush()

    log_action(patient.id, 'delete_doc',
               f'Documento "{name}" excluído.')
    flash('Documento excluído.', 'success')
    return redirect(url_for('patient.documentos'))


# ---------------------------------------------------------------------------
# Medicamentos
# ---------------------------------------------------------------------------
@patient_bp.route('/medicamentos')
@login_required
def medicamentos():
    patient = get_current_patient()
    ativos = patient.medications.filter_by(is_active=True).order_by(
        Medication.created_at.desc()).all()
    inativos = patient.medications.filter_by(is_active=False).order_by(
        Medication.created_at.desc()).all()

    return render_template('paciente/medicamentos.html',
                           patient=patient,
                           ativos=ativos,
                           inativos=inativos,
                           routes=MEDICATION_ROUTES)


@patient_bp.route('/medicamentos/adicionar', methods=['POST'])
@login_required
def adicionar_medicamento():
    patient = get_current_patient()

    name = request.form.get('name', '').strip()
    dose = request.form.get('dose', '').strip()
    frequency = request.form.get('frequency', '').strip()
    route = request.form.get('route', '')
    start_date_str = request.form.get('start_date', '')
    end_date_str = request.form.get('end_date', '')
    prescriber = request.form.get('prescriber', '').strip()
    notes = request.form.get('notes', '').strip()

    if not name:
        flash('Nome do medicamento é obrigatório.', 'danger')
        return redirect(url_for('patient.medicamentos'))

    start_date = None
    end_date = None

    try:
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Data inválida.', 'danger')
        return redirect(url_for('patient.medicamentos'))

    med = Medication(
        patient_id=patient.id,
        name=name,
        dose=dose or None,
        frequency=frequency or None,
        route=route or None,
        start_date=start_date,
        end_date=end_date,
        prescriber=prescriber or None,
        notes=notes or None,
        is_active=True,
    )
    db.session.add(med)
    db.session.flush()

    log_action(patient.id, 'add_medication', f'Medicamento "{name}" adicionado.')
    flash('Medicamento adicionado.', 'success')
    return redirect(url_for('patient.medicamentos'))


@patient_bp.route('/medicamentos/<int:med_id>/editar', methods=['POST'])
@login_required
def editar_medicamento(med_id):
    patient = get_current_patient()
    med = Medication.query.filter_by(id=med_id, patient_id=patient.id).first_or_404()

    name = request.form.get('name', '').strip()
    if not name:
        flash('Nome é obrigatório.', 'danger')
        return redirect(url_for('patient.medicamentos'))

    start_date_str = request.form.get('start_date', '')
    end_date_str = request.form.get('end_date', '')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        flash('Data inválida.', 'danger')
        return redirect(url_for('patient.medicamentos'))

    med.name = name
    med.dose = request.form.get('dose', '').strip() or None
    med.frequency = request.form.get('frequency', '').strip() or None
    med.route = request.form.get('route', '') or None
    med.start_date = start_date
    med.end_date = end_date
    med.prescriber = request.form.get('prescriber', '').strip() or None
    med.notes = request.form.get('notes', '').strip() or None
    db.session.commit()

    log_action(patient.id, 'edit_medication', f'Medicamento "{name}" editado.')
    flash('Medicamento atualizado.', 'success')
    return redirect(url_for('patient.medicamentos'))


@patient_bp.route('/medicamentos/<int:med_id>/excluir', methods=['POST'])
@login_required
def excluir_medicamento(med_id):
    patient = get_current_patient()
    med = Medication.query.filter_by(id=med_id, patient_id=patient.id).first_or_404()

    name = med.name
    db.session.delete(med)
    db.session.flush()

    log_action(patient.id, 'delete_medication', f'Medicamento "{name}" excluído.')
    flash('Medicamento excluído.', 'success')
    return redirect(url_for('patient.medicamentos'))


@patient_bp.route('/medicamentos/<int:med_id>/toggle', methods=['POST'])
@login_required
def toggle_medicamento(med_id):
    patient = get_current_patient()
    med = Medication.query.filter_by(id=med_id, patient_id=patient.id).first_or_404()
    med.is_active = not med.is_active
    db.session.commit()

    status = 'ativado' if med.is_active else 'marcado como inativo'
    flash(f'Medicamento {status}.', 'success')
    return redirect(url_for('patient.medicamentos'))


# ---------------------------------------------------------------------------
# Gerenciamento de Acessos
# ---------------------------------------------------------------------------
@patient_bp.route('/acessos')
@login_required
def acessos():
    patient = get_current_patient()

    pending = (AccessRequest.query
               .filter_by(patient_id=patient.id, status='pending')
               .order_by(AccessRequest.requested_at.desc()).all())

    history = (AccessRequest.query
               .filter(AccessRequest.patient_id == patient.id,
                       AccessRequest.status != 'pending')
               .order_by(AccessRequest.requested_at.desc())
               .limit(50).all())

    return render_template('paciente/acessos.html',
                           patient=patient,
                           pending=pending,
                           history=history,
                           durations=ACCESS_DURATIONS)


@patient_bp.route('/acessos/<int:req_id>/aprovar', methods=['POST'])
@login_required
def aprovar_acesso(req_id):
    patient = get_current_patient()
    req = AccessRequest.query.filter_by(
        id=req_id, patient_id=patient.id, status='pending'
    ).first_or_404()

    try:
        minutes = int(request.form.get('minutes', 30))
    except ValueError:
        minutes = 30

    if minutes not in ACCESS_DURATIONS:
        minutes = 30

    allow_download = request.form.get('allow_download') == '1'

    req.status = 'approved'
    req.allow_download = allow_download
    req.access_minutes = minutes
    req.responded_at = datetime.utcnow()
    req.expires_at = datetime.utcnow() + timedelta(minutes=minutes)
    db.session.commit()

    log_action(patient.id, 'access_approved',
               f'Acesso aprovado para {req.professional.name} '
               f'por {minutes} min (download: {"sim" if allow_download else "não"}).')

    flash(f'Acesso aprovado para {req.professional.name} por {minutes} minutos.', 'success')
    return redirect(url_for('patient.acessos'))


@patient_bp.route('/acessos/<int:req_id>/recusar', methods=['POST'])
@login_required
def recusar_acesso(req_id):
    patient = get_current_patient()
    req = AccessRequest.query.filter_by(
        id=req_id, patient_id=patient.id, status='pending'
    ).first_or_404()

    req.status = 'denied'
    req.responded_at = datetime.utcnow()
    db.session.commit()

    log_action(patient.id, 'access_denied',
               f'Acesso negado para {req.professional.name}.')

    flash(f'Acesso de {req.professional.name} recusado.', 'info')
    return redirect(url_for('patient.acessos'))


# ---------------------------------------------------------------------------
# Links de Compartilhamento
# ---------------------------------------------------------------------------
@patient_bp.route('/links')
@login_required
def links():
    patient = get_current_patient()
    all_links = (patient.share_links
                 .order_by(ShareLink.created_at.desc()).all())

    return render_template('paciente/links.html',
                           patient=patient,
                           links=all_links)


@patient_bp.route('/links/criar', methods=['POST'])
@login_required
def criar_link():
    patient = get_current_patient()

    description = request.form.get('description', '').strip()
    try:
        hours = int(request.form.get('hours', 24))
    except ValueError:
        hours = 24

    hours = max(1, min(168, hours))

    token = secrets.token_urlsafe(32)
    link = ShareLink(
        patient_id=patient.id,
        token=token,
        description=description or None,
        expires_at=datetime.utcnow() + timedelta(hours=hours),
    )
    db.session.add(link)
    db.session.flush()

    log_action(patient.id, 'share_link_created',
               f'Link de compartilhamento criado (válido por {hours}h).')
    flash('Link criado com sucesso!', 'success')
    return redirect(url_for('patient.links'))


@patient_bp.route('/links/<int:link_id>/revogar', methods=['POST'])
@login_required
def revogar_link(link_id):
    patient = get_current_patient()
    link = ShareLink.query.filter_by(
        id=link_id, patient_id=patient.id
    ).first_or_404()

    link.is_revoked = True
    db.session.commit()

    log_action(patient.id, 'share_link_revoked', 'Link de compartilhamento revogado.')
    flash('Link revogado.', 'info')
    return redirect(url_for('patient.links'))


# ---------------------------------------------------------------------------
# Histórico de Acessos
# ---------------------------------------------------------------------------
@patient_bp.route('/historico')
@login_required
def historico():
    patient = get_current_patient()
    logs = (patient.access_logs
            .order_by(AccessLog.created_at.desc())
            .all())

    return render_template('paciente/historico.html',
                           patient=patient, logs=logs)


@patient_bp.route('/historico/exportar')
@login_required
def exportar_historico():
    patient = get_current_patient()
    logs = (patient.access_logs
            .order_by(AccessLog.created_at.desc())
            .all())

    pdf_bytes = generate_history_pdf(patient, logs)

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'historico_{patient.cpf}.pdf',
    )


# ---------------------------------------------------------------------------
# API — Extensão Chrome
# ---------------------------------------------------------------------------
@patient_bp.route('/api/ext/token', methods=['POST'])
@login_required
def ext_generate_token():
    """Gera token de API para a extensão Chrome. Retorna JSON."""
    import secrets as _sec
    import hashlib as _hl
    patient = get_current_patient()
    raw = _sec.token_urlsafe(32)
    patient.ext_token_hash = _hl.sha256(raw.encode()).hexdigest()
    db.session.commit()
    return jsonify({'token': raw})


@patient_bp.route('/api/ext/upload', methods=['POST'])
def ext_upload():
    """
    Endpoint para a extensão Chrome enviar documentos.
    Autenticação via Bearer token no header Authorization.
    """
    import hashlib as _hl
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Token ausente'}), 401

    raw_token = auth_header[7:]
    token_hash = _hl.sha256(raw_token.encode()).hexdigest()
    patient = Patient.query.filter_by(ext_token_hash=token_hash).first()
    if not patient:
        return jsonify({'error': 'Token inválido'}), 401

    file = request.files.get('file')
    name = request.form.get('name', '').strip()
    category = request.form.get('category', 'outro')
    observation = request.form.get('observation', '').strip()
    source_url = request.form.get('source_url', '').strip()

    if not file or not file.filename:
        return jsonify({'error': 'Arquivo ausente'}), 400
    if not allowed_extension(file.filename):
        return jsonify({'error': 'Formato não permitido'}), 400
    if category not in dict(DOCUMENT_CATEGORIES):
        category = 'outro'

    file_bytes = file.read()
    ext = get_extension(file.filename)
    if not validate_magic_number(file_bytes, ext):
        return jsonify({'error': 'Conteúdo do arquivo inválido'}), 400

    file_size = len(file_bytes)
    obs_text = observation or None
    if source_url:
        obs_text = (obs_text + '\n' if obs_text else '') + f'Capturado de: {source_url}'

    if storage_shamir.shamir_configured():
        result = storage_shamir.upload_shamir(file_bytes, file.filename)
        if not result:
            return jsonify({'error': 'Falha no armazenamento'}), 500
        meta = json.dumps({k: result[k] for k in ('file_id', 'ext', 'nonce_hex', 'salt_hex')})
        doc = Document(
            patient_id=patient.id,
            name=name or file.filename,
            category=category,
            filename=result['file_id'],
            original_filename=file.filename,
            file_size=file_size,
            observation=obs_text,
            storage_type='shamir',
            storage_meta=meta,
        )
    else:
        stored_id = storage.upload_file(file_bytes, file.filename)
        if not storage._cloudinary_configured():
            upload_folder = current_app.config['UPLOAD_FOLDER']
            os.makedirs(upload_folder, exist_ok=True)
            with open(os.path.join(upload_folder, stored_id), 'wb') as f_out:
                f_out.write(file_bytes)
        doc = Document(
            patient_id=patient.id,
            name=name or file.filename,
            category=category,
            filename=stored_id,
            original_filename=file.filename,
            file_size=file_size,
            observation=obs_text,
            storage_type='cloudinary' if storage._cloudinary_configured() else 'local',
        )

    db.session.add(doc)
    db.session.flush()
    log_action(patient.id, 'upload',
               f'Documento "{doc.name}" enviado via extensão Chrome ({file.filename}).')
    db.session.commit()
    return jsonify({'ok': True, 'doc_id': doc.id, 'name': doc.name})


@patient_bp.route('/api/ext/categories')
def ext_categories():
    """Retorna categorias disponíveis para a extensão."""
    return jsonify([{'key': k, 'label': v} for k, v in DOCUMENT_CATEGORIES])


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@patient_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    patient = get_current_patient()

    if request.method == 'POST':
        action = request.form.get('action', 'update_profile')

        if action == 'update_profile':
            name = request.form.get('name', '').strip()
            birth_date_str = request.form.get('birth_date', '')
            sus_card = request.form.get('sus_card', '').strip()
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip().lower()
            clinical_notes = request.form.get('clinical_notes', '').strip()

            from utils.validators import validate_cpf, clean_cpf
            cpf_raw = request.form.get('cpf', '')
            cpf = clean_cpf(cpf_raw)

            errors = []
            if not name:
                errors.append('Nome é obrigatório.')
            if not validate_cpf(cpf_raw):
                errors.append('CPF inválido.')
            if not email or '@' not in email:
                errors.append('E-mail inválido.')
            if not birth_date_str:
                errors.append('Data de nascimento é obrigatória.')

            # Verifica CPF duplicado (outro paciente)
            existing = Patient.query.filter_by(cpf=cpf).first()
            if existing and existing.id != patient.id:
                errors.append('Este CPF já pertence a outro cadastro.')

            birth_date = None
            if birth_date_str:
                try:
                    birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d').date()
                except ValueError:
                    errors.append('Data de nascimento inválida.')

            if errors:
                for e in errors:
                    flash(e, 'danger')
                return render_template('paciente/perfil.html', patient=patient)

            patient.name = name
            patient.birth_date = birth_date
            patient.cpf = cpf
            patient.sus_card = sus_card or None
            patient.phone = phone or None
            patient.email = email
            patient.clinical_notes = clinical_notes or None
            db.session.commit()

            log_action(patient.id, 'edit_profile', 'Perfil atualizado.')
            flash('Perfil atualizado com sucesso!', 'success')

        elif action == 'change_password':
            current_pw = request.form.get('current_password', '')
            new_pw = request.form.get('new_password', '')
            new_pw2 = request.form.get('new_password2', '')

            if not patient.check_password(current_pw):
                flash('Senha atual incorreta.', 'danger')
            elif len(new_pw) < 6:
                flash('A nova senha deve ter pelo menos 6 caracteres.', 'danger')
            elif new_pw != new_pw2:
                flash('As novas senhas não coincidem.', 'danger')
            else:
                patient.set_password(new_pw)
                db.session.commit()
                log_action(patient.id, 'change_password', 'Senha alterada.')
                flash('Senha alterada com sucesso!', 'success')

        return redirect(url_for('patient.perfil'))

    return render_template('paciente/perfil.html', patient=patient)


# ---------------------------------------------------------------------------
# Excluir Conta
# ---------------------------------------------------------------------------
@patient_bp.route('/conta/excluir', methods=['POST'])
@login_required
def excluir_conta():
    patient = get_current_patient()
    password = request.form.get('password', '')

    if not patient.check_password(password):
        flash('Senha incorreta. A conta não foi excluída.', 'danger')
        return redirect(url_for('patient.perfil'))

    # Remove arquivos físicos / Cloudinary
    upload_folder = current_app.config['UPLOAD_FOLDER']
    for doc in patient.documents.all():
        if doc.storage_type == 'shamir' and doc.storage_meta:
            import json as _j2
            try:
                m2 = _j2.loads(doc.storage_meta)
                storage_shamir.delete_shamir(m2['file_id'], m2['ext'])
            except Exception:
                pass
        else:
            storage.delete_stored_file(doc.filename, upload_folder)

    db.session.delete(patient)
    db.session.commit()

    session.clear()
    flash('Sua conta foi excluída permanentemente.', 'info')
    return redirect(url_for('auth.index'))
