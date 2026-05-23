"""
Rota pública de acesso via link temporário de compartilhamento.
Sem autenticação necessária.
"""
import io
import os
from datetime import datetime

from flask import (Blueprint, render_template, abort, send_file,
                   current_app, redirect, url_for, request)

from models import db, ShareLink, Document, AccessLog, DOCUMENT_CATEGORIES
from utils.file_utils import get_mime_type, is_viewable_inline
from utils import storage

share_bp = Blueprint('share', __name__)


def get_client_ip():
    return (request.headers.get('X-Forwarded-For',
                                request.remote_addr) or '').split(',')[0].strip()


@share_bp.route('/prontuario/<token>')
def prontuario_publico(token):
    link = ShareLink.query.filter_by(token=token).first()

    if not link or not link.is_valid:
        return render_template('share/invalido.html'), 410

    patient = link.patient

    # Atualiza last_accessed
    link.last_accessed = datetime.utcnow()
    db.session.commit()

    # Log de acesso
    log = AccessLog(
        patient_id=patient.id,
        action='share_link_accessed',
        description=f'Link compartilhado acessado (descrição: {link.description or "sem descrição"}).',
        ip_address=get_client_ip(),
        performed_by='patient',
    )
    db.session.add(log)
    db.session.commit()

    docs = patient.documents.order_by(Document.created_at.desc()).all()
    meds_ativos = patient.medications.filter_by(is_active=True).all()

    cat_stats = {}
    for cat_key, cat_label in DOCUMENT_CATEGORIES:
        count = sum(1 for d in docs if d.category == cat_key)
        if count > 0:
            cat_stats[cat_label] = count

    category = request.args.get('category', '')
    search = request.args.get('search', '').strip()

    filtered_docs = docs
    if category:
        filtered_docs = [d for d in docs if d.category == category]
    if search:
        filtered_docs = [d for d in filtered_docs
                         if search.lower() in d.name.lower()]

    return render_template('share/prontuario.html',
                           patient=patient,
                           link=link,
                           docs=filtered_docs,
                           meds_ativos=meds_ativos,
                           cat_stats=cat_stats,
                           categories=DOCUMENT_CATEGORIES,
                           selected_category=category,
                           search=search,
                           token=token)


@share_bp.route('/prontuario/<token>/documento/<int:doc_id>/visualizar')
def visualizar_documento(token, doc_id):
    link = ShareLink.query.filter_by(token=token).first()
    if not link or not link.is_valid:
        abort(410)

    doc = Document.query.filter_by(id=doc_id, patient_id=link.patient_id).first_or_404()

    mime = get_mime_type(doc.original_filename)
    inline = is_viewable_inline(doc.original_filename)

    file_bytes = storage.get_file_bytes(doc.filename, current_app.config['UPLOAD_FOLDER'])
    if not file_bytes:
        abort(404)

    return send_file(
        io.BytesIO(file_bytes),
        mimetype=mime,
        as_attachment=not inline,
        download_name=doc.original_filename if not inline else None,
    )
