"""
Rotas do profissional de saúde: portal, busca de pacientes,
solicitação de acesso (dois métodos), visualização do prontuário,
upload de documento.
"""
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, session, current_app, send_file, abort, jsonify)

from models import (db, Patient, Professional, Document, AccessRequest,
                    AccessLog, Medication, DOCUMENT_CATEGORIES, ACCESS_DURATIONS)
from utils.file_utils import (allowed_extension, validate_magic_number,
                               generate_unique_filename, get_mime_type,
                               is_viewable_inline, get_extension)
from utils.notifications import push_notification

professional_bp = Blueprint('professional', __name__, url_prefix='/profissional')


# ---------------------------------------------------------------------------
# Decorador e helpers
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('user_type') != 'professional':
            flash('Faça login como profissional para continuar.', 'warning')
            return redirect(url_for('auth.login_profissional'))
        return f(*args, **kwargs)
    return decorated


def get_current_professional() -> Professional:
    return Professional.query.get_or_404(session['user_id'])


def get_client_ip():
    return (request.headers.get('X-Forwarded-For',
                                request.remote_addr) or '').split(',')[0].strip()


def log_access(patient_id, action, description, professional_id):
    log = AccessLog(
        patient_id=patient_id,
        professional_id=professional_id,
        action=action,
        description=description,
        ip_address=get_client_ip(),
        performed_by='professional',
    )
    db.session.add(log)
    db.session.commit()


def get_active_access(professional_id: int, patient_id: int) -> AccessRequest | None:
    """Retorna o AccessRequest ativo (aprovado e dentro do prazo) ou None."""
    req = (AccessRequest.query
           .filter_by(professional_id=professional_id,
                      patient_id=patient_id,
                      status='approved')
           .order_by(AccessRequest.expires_at.desc())
           .first())
    if req and req.is_active:
        return req
    return None


# ---------------------------------------------------------------------------
# Portal
# ---------------------------------------------------------------------------
@professional_bp.route('/portal')
@login_required
def portal():
    professional = get_current_professional()
    search = request.args.get('search', '').strip()
    patients = []

    if search:
        patients = Patient.query.filter(
            db.or_(
                Patient.name.ilike(f'%{search}%'),
                Patient.cpf.ilike(f'%{search}%'),
                Patient.sus_card.ilike(f'%{search}%'),
            )
        ).order_by(Patient.name).limit(20).all()

        # Para cada paciente, verifica o status de acesso
        for p in patients:
            active = get_active_access(professional.id, p.id)
            pending = AccessRequest.query.filter_by(
                professional_id=professional.id,
                patient_id=p.id,
                status='pending',
            ).first()

            if active:
                p._access_status = 'active'
                p._access_expires = active.expires_at
            elif pending:
                p._access_status = 'pending'
                p._access_expires = None
            else:
                p._access_status = 'none'
                p._access_expires = None

    return render_template('profissional/portal.html',
                           professional=professional,
                           patients=patients,
                           search=search)


# ---------------------------------------------------------------------------
# Solicitar Acesso — Método 1 (notificação ao paciente)
# ---------------------------------------------------------------------------
@professional_bp.route('/paciente/<int:patient_id>/solicitar', methods=['GET', 'POST'])
@login_required
def solicitar_acesso(patient_id):
    professional = get_current_professional()
    patient = Patient.query.get_or_404(patient_id)

    # Se já tem acesso ativo, redireciona para prontuário
    if get_active_access(professional.id, patient_id):
        return redirect(url_for('professional.prontuario', patient_id=patient_id))

    # Se já tem solicitação pendente
    pending = AccessRequest.query.filter_by(
        professional_id=professional.id,
        patient_id=patient_id,
        status='pending',
    ).first()

    if request.method == 'POST':
        method = request.form.get('method', 'notify')

        if method == 'notify':
            if not pending:
                message = request.form.get('message', '').strip()[:500]
                req = AccessRequest(
                    professional_id=professional.id,
                    patient_id=patient_id,
                    status='pending',
                    message=message or None,
                )
                db.session.add(req)
                db.session.flush()

                # Log
                log_access(patient_id, 'access_request',
                            f'Profissional {professional.name} ({professional.registration}) '
                            f'solicitou acesso ao prontuário.',
                            professional.id)

                # Notificação SSE em tempo real
                push_notification(patient_id, 'access_request', {
                    'professional_name': professional.name,
                    'professional_type': professional.prof_type_display,
                    'professional_reg': professional.registration,
                    'request_id': req.id,
                })

                flash(
                    f'Solicitação enviada para {patient.name}. '
                    'Aguarde a aprovação do paciente.', 'info'
                )
            else:
                flash('Você já tem uma solicitação pendente para este paciente.', 'warning')

            return redirect(url_for('professional.solicitar_acesso',
                                    patient_id=patient_id))

        elif method == 'password':
            # Autorização direta pela senha do paciente
            patient_password = request.form.get('patient_password', '')
            try:
                minutes = int(request.form.get('minutes', 30))
            except ValueError:
                minutes = 30
            if minutes not in ACCESS_DURATIONS:
                minutes = 30
            allow_download = request.form.get('allow_download') == '1'

            if patient.check_password(patient_password):
                # Cancela solicitação pendente, se houver
                if pending:
                    pending.status = 'approved'
                    pending.allow_download = allow_download
                    pending.access_minutes = minutes
                    pending.responded_at = datetime.utcnow()
                    pending.expires_at = datetime.utcnow() + timedelta(minutes=minutes)
                    req = pending
                else:
                    req = AccessRequest(
                        professional_id=professional.id,
                        patient_id=patient_id,
                        status='approved',
                        allow_download=allow_download,
                        access_minutes=minutes,
                        responded_at=datetime.utcnow(),
                        expires_at=datetime.utcnow() + timedelta(minutes=minutes),
                    )
                    db.session.add(req)

                db.session.flush()

                log_access(patient_id, 'access_approved',
                            f'Acesso autorizado por senha do paciente para '
                            f'{professional.name} por {minutes} min.',
                            professional.id)

                flash(f'Acesso autorizado por {minutes} minutos!', 'success')
                return redirect(url_for('professional.prontuario',
                                        patient_id=patient_id))
            else:
                flash('Senha do paciente incorreta.', 'danger')

    return render_template('profissional/solicitar_acesso.html',
                           professional=professional,
                           patient=patient,
                           pending=pending,
                           durations=ACCESS_DURATIONS)


# ---------------------------------------------------------------------------
# Prontuário do Paciente
# ---------------------------------------------------------------------------
@professional_bp.route('/paciente/<int:patient_id>/prontuario')
@login_required
def prontuario(patient_id):
    professional = get_current_professional()
    patient = Patient.query.get_or_404(patient_id)

    access = get_active_access(professional.id, patient_id)
    if not access:
        flash('Você não tem acesso ativo ao prontuário deste paciente.', 'warning')
        return redirect(url_for('professional.solicitar_acesso',
                                patient_id=patient_id))

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

    docs = query.all()
    meds_ativos = patient.medications.filter_by(is_active=True).all()

    # Estatísticas
    all_docs = patient.documents.all()
    cat_stats = {}
    for cat_key, cat_label in DOCUMENT_CATEGORIES:
        count = sum(1 for d in all_docs if d.category == cat_key)
        if count > 0:
            cat_stats[cat_label] = count

    log_access(patient_id, 'access_prontuario',
               f'Prontuário acessado por {professional.name}.', professional.id)

    return render_template('profissional/prontuario.html',
                           professional=professional,
                           patient=patient,
                           access=access,
                           docs=docs,
                           meds_ativos=meds_ativos,
                           cat_stats=cat_stats,
                           categories=DOCUMENT_CATEGORIES,
                           selected_category=category,
                           search=search,
                           order=order)


# ---------------------------------------------------------------------------
# Visualizar documento (profissional)
# ---------------------------------------------------------------------------
@professional_bp.route('/paciente/<int:patient_id>/documento/<int:doc_id>/visualizar')
@login_required
def visualizar_documento(patient_id, doc_id):
    professional = get_current_professional()
    patient = Patient.query.get_or_404(patient_id)

    access = get_active_access(professional.id, patient_id)
    if not access:
        abort(403)

    doc = Document.query.filter_by(id=doc_id, patient_id=patient_id).first_or_404()

    upload_folder = current_app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_folder, doc.filename)

    if not os.path.exists(file_path):
        flash('Arquivo não encontrado.', 'danger')
        return redirect(url_for('professional.prontuario', patient_id=patient_id))

    mime = get_mime_type(doc.original_filename)
    inline = is_viewable_inline(doc.original_filename)

    log_access(patient_id, 'view_doc',
               f'Profissional {professional.name} visualizou "{doc.name}".',
               professional.id)

    # Sem acesso a download: redireciona para viewer seguro
    if not access.allow_download:
        return redirect(url_for('professional.viewer_documento',
                                patient_id=patient_id, doc_id=doc_id))

    return send_file(file_path, mimetype=mime, as_attachment=not inline,
                     download_name=doc.original_filename if not inline else None)


# ---------------------------------------------------------------------------
# Download documento (profissional)
# ---------------------------------------------------------------------------
@professional_bp.route('/paciente/<int:patient_id>/documento/<int:doc_id>/download')
@login_required
def download_documento(patient_id, doc_id):
    professional = get_current_professional()

    access = get_active_access(professional.id, patient_id)
    if not access:
        abort(403)
    if not access.allow_download:
        flash('Download não autorizado pelo paciente.', 'warning')
        return redirect(url_for('professional.prontuario', patient_id=patient_id))

    doc = Document.query.filter_by(id=doc_id, patient_id=patient_id).first_or_404()
    upload_folder = current_app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_folder, doc.filename)

    mime = get_mime_type(doc.original_filename)

    log_access(patient_id, 'download_doc',
               f'Profissional {professional.name} fez download de "{doc.name}".',
               professional.id)

    return send_file(file_path, mimetype=mime, as_attachment=True,
                     download_name=doc.original_filename)


# ---------------------------------------------------------------------------
# Upload pelo Profissional
# ---------------------------------------------------------------------------
@professional_bp.route('/paciente/<int:patient_id>/upload', methods=['GET', 'POST'])
@login_required
def upload_documento(patient_id):
    professional = get_current_professional()
    patient = Patient.query.get_or_404(patient_id)

    access = get_active_access(professional.id, patient_id)
    if not access:
        flash('Você não tem acesso ativo ao prontuário deste paciente.', 'warning')
        return redirect(url_for('professional.solicitar_acesso',
                                patient_id=patient_id))

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
                errors.append('O conteúdo do arquivo não corresponde à extensão declarada.')

            file_size = len(file_bytes)
            if file_size > current_app.config['MAX_CONTENT_LENGTH']:
                errors.append('Arquivo excede o limite de 16 MB.')

            if not errors:
                stored_name = generate_unique_filename(file.filename)
                upload_folder = current_app.config['UPLOAD_FOLDER']
                os.makedirs(upload_folder, exist_ok=True)
                dest = os.path.join(upload_folder, stored_name)

                with open(dest, 'wb') as f:
                    f.write(file_bytes)

                doc = Document(
                    patient_id=patient_id,
                    uploaded_by_professional_id=professional.id,
                    name=name,
                    category=category,
                    filename=stored_name,
                    original_filename=file.filename,
                    file_size=file_size,
                    observation=observation or None,
                )
                db.session.add(doc)
                db.session.flush()

                log_access(patient_id, 'prof_upload',
                            f'Profissional {professional.name} adicionou '
                            f'documento "{name}" ao prontuário.',
                            professional.id)

                flash('Documento enviado ao prontuário!', 'success')
                return redirect(url_for('professional.prontuario',
                                        patient_id=patient_id))

        for e in errors:
            flash(e, 'danger')

    return render_template('profissional/upload_documento.html',
                           professional=professional,
                           patient=patient,
                           access=access,
                           categories=DOCUMENT_CATEGORIES)


# ---------------------------------------------------------------------------
# Perfil do Profissional
# ---------------------------------------------------------------------------
@professional_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    professional = get_current_professional()

    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'update_profile':
            name = request.form.get('name', '').strip()
            specialty = request.form.get('specialty', '').strip()
            email = request.form.get('email', '').strip().lower()

            if not name:
                flash('Nome é obrigatório.', 'danger')
            elif not email or '@' not in email:
                flash('E-mail inválido.', 'danger')
            else:
                professional.name = name
                professional.specialty = specialty or None
                professional.email = email
                db.session.commit()
                flash('Perfil atualizado com sucesso!', 'success')

        elif action == 'change_password':
            current_pw = request.form.get('current_password', '')
            new_pw = request.form.get('new_password', '')
            new_pw2 = request.form.get('new_password2', '')

            if not professional.check_password(current_pw):
                flash('Senha atual incorreta.', 'danger')
            elif len(new_pw) < 6:
                flash('A nova senha deve ter pelo menos 6 caracteres.', 'danger')
            elif new_pw != new_pw2:
                flash('As novas senhas não coincidem.', 'danger')
            else:
                professional.set_password(new_pw)
                db.session.commit()
                flash('Senha alterada com sucesso!', 'success')

        return redirect(url_for('professional.perfil'))

    return render_template('profissional/perfil.html', professional=professional)


# ---------------------------------------------------------------------------
# Excluir Conta do Profissional
# ---------------------------------------------------------------------------
@professional_bp.route('/conta/excluir', methods=['POST'])
@login_required
def excluir_conta():
    professional = get_current_professional()
    password = request.form.get('password', '')

    if not professional.check_password(password):
        flash('Senha incorreta. A conta não foi excluída.', 'danger')
        return redirect(url_for('professional.perfil'))

    db.session.delete(professional)
    db.session.commit()

    session.clear()
    flash('Sua conta foi excluída permanentemente.', 'info')
    return redirect(url_for('auth.index'))


# ---------------------------------------------------------------------------
# Check Access (polling para auto-redirect)
# ---------------------------------------------------------------------------
@professional_bp.route('/paciente/<int:patient_id>/check-access')
@login_required
def check_access(patient_id):
    """Retorna JSON com status do acesso. Usado pelo polling JS na página de solicitação."""
    professional = get_current_professional()

    active = get_active_access(professional.id, patient_id)
    if active:
        return jsonify({'status': 'active',
                        'redirect': url_for('professional.prontuario',
                                            patient_id=patient_id)})

    pending = AccessRequest.query.filter_by(
        professional_id=professional.id,
        patient_id=patient_id,
        status='pending',
    ).first()
    if pending:
        return jsonify({'status': 'pending'})

    denied = (AccessRequest.query
              .filter_by(professional_id=professional.id,
                         patient_id=patient_id,
                         status='denied')
              .order_by(AccessRequest.id.desc())
              .first())
    return jsonify({'status': 'denied' if denied else 'none'})


# ---------------------------------------------------------------------------
# Viewer seguro de documento (sem download)
# ---------------------------------------------------------------------------
VIEWER_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'txt'}


@professional_bp.route('/paciente/<int:patient_id>/documento/<int:doc_id>/raw')
@login_required
def raw_documento(patient_id, doc_id):
    """Serve os bytes do arquivo inline, com headers que desestimulam download.
    Usado exclusivamente pelo viewer seguro."""
    professional = get_current_professional()

    access = get_active_access(professional.id, patient_id)
    if not access:
        abort(403)

    doc = Document.query.filter_by(id=doc_id, patient_id=patient_id).first_or_404()
    upload_folder = current_app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_folder, doc.filename)

    if not os.path.exists(file_path):
        abort(404)

    mime = get_mime_type(doc.original_filename)
    response = send_file(file_path, mimetype=mime, as_attachment=False)
    response.headers['Content-Disposition'] = 'inline'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@professional_bp.route('/paciente/<int:patient_id>/documento/<int:doc_id>/pdf-info')
@login_required
def pdf_info(patient_id, doc_id):
    """Retorna JSON com número de páginas do PDF. Usado pelo viewer."""
    professional = get_current_professional()
    if not get_active_access(professional.id, patient_id):
        abort(403)

    doc = Document.query.filter_by(id=doc_id, patient_id=patient_id).first_or_404()
    if get_extension(doc.original_filename) != 'pdf':
        abort(400)

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], doc.filename)
    if not os.path.exists(file_path):
        abort(404)

    try:
        import fitz  # PyMuPDF
        pdf = fitz.open(file_path)
        count = pdf.page_count
        pdf.close()
        return jsonify({'pages': count})
    except Exception:
        abort(500)


@professional_bp.route('/paciente/<int:patient_id>/documento/<int:doc_id>/pdf-page/<int:page_num>')
@login_required
def pdf_page(patient_id, doc_id, page_num):
    """Renderiza uma página do PDF como PNG e a retorna. Usado pelo viewer."""
    professional = get_current_professional()
    if not get_active_access(professional.id, patient_id):
        abort(403)

    doc = Document.query.filter_by(id=doc_id, patient_id=patient_id).first_or_404()
    if get_extension(doc.original_filename) != 'pdf':
        abort(400)

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], doc.filename)
    if not os.path.exists(file_path):
        abort(404)

    try:
        import io
        import fitz  # PyMuPDF
        pdf  = fitz.open(file_path)
        if page_num < 1 or page_num > pdf.page_count:
            pdf.close()
            abort(404)
        page = pdf[page_num - 1]
        mat  = fitz.Matrix(2.0, 2.0)   # escala 2× para boa resolução
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        png  = pix.tobytes('png')
        pdf.close()

        from flask import Response as FlaskResponse
        return FlaskResponse(png, mimetype='image/png',
                             headers={'Cache-Control': 'no-store',
                                      'X-Content-Type-Options': 'nosniff'})
    except Exception:
        abort(500)


@professional_bp.route('/paciente/<int:patient_id>/documento/<int:doc_id>/viewer')
@login_required
def viewer_documento(patient_id, doc_id):
    """Página de visualização segura — sem botão de download, sem URL exposta."""
    professional = get_current_professional()
    patient = Patient.query.get_or_404(patient_id)

    access = get_active_access(professional.id, patient_id)
    if not access:
        flash('Você não tem acesso ativo ao prontuário deste paciente.', 'warning')
        return redirect(url_for('professional.solicitar_acesso', patient_id=patient_id))

    doc = Document.query.filter_by(id=doc_id, patient_id=patient_id).first_or_404()
    ext = get_extension(doc.original_filename)

    if ext not in VIEWER_EXTENSIONS:
        flash('Este tipo de arquivo não pode ser visualizado sem permissão de download.', 'warning')
        return redirect(url_for('professional.prontuario', patient_id=patient_id))

    raw_url      = url_for('professional.raw_documento',
                           patient_id=patient_id, doc_id=doc_id)
    pdf_info_url = url_for('professional.pdf_info',
                           patient_id=patient_id, doc_id=doc_id)
    # URL template de página — o JS substitui PAGE_NUM pelo número real
    pdf_page_url = url_for('professional.pdf_page',
                           patient_id=patient_id, doc_id=doc_id,
                           page_num=0).replace('/0', '/PAGE_NUM')

    log_access(patient_id, 'view_doc',
               f'Profissional {professional.name} visualizou "{doc.name}" (somente leitura).',
               professional.id)

    return render_template('profissional/viewer.html',
                           professional=professional,
                           patient=patient,
                           doc=doc,
                           access=access,
                           raw_url=raw_url,
                           pdf_info_url=pdf_info_url,
                           pdf_page_url=pdf_page_url,
                           ext=ext,
                           patient_id=patient_id)
