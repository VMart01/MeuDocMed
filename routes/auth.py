"""
Rotas de autenticação: cadastro e login de paciente/profissional,
logout, recuperação e redefinição de senha.
"""
import os
import secrets
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, session, current_app)
from flask_mail import Message

from models import db, Patient, Professional, PasswordReset, PROF_TYPES
from utils.validators import (validate_cpf, clean_cpf,
                               validate_professional_registration,
                               normalize_registration)

auth_bp = Blueprint('auth', __name__)


# ---------------------------------------------------------------------------
# Helpers de sessão
# ---------------------------------------------------------------------------
def login_patient(patient: Patient):
    session.clear()
    session['user_type'] = 'patient'
    session['user_id'] = patient.id
    session.permanent = True


def login_professional(professional: Professional):
    session.clear()
    session['user_type'] = 'professional'
    session['user_id'] = professional.id
    session.permanent = True


def get_client_ip():
    return (request.headers.get('X-Forwarded-For', request.remote_addr) or '').split(',')[0].strip()


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------
@auth_bp.route('/')
def index():
    if session.get('user_type') == 'patient':
        return redirect(url_for('patient.dashboard'))
    if session.get('user_type') == 'professional':
        return redirect(url_for('professional.portal'))
    return render_template('index.html')


# ---------------------------------------------------------------------------
# Cadastro — Paciente
# ---------------------------------------------------------------------------
@auth_bp.route('/cadastro/paciente', methods=['GET', 'POST'])
def cadastro_paciente():
    if session.get('user_type') == 'patient':
        return redirect(url_for('patient.dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        birth_date_str = request.form.get('birth_date', '')
        cpf_raw = request.form.get('cpf', '')
        sus_card = request.form.get('sus_card', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip().lower()
        clinical_notes = request.form.get('clinical_notes', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        errors = []

        if not name:
            errors.append('Nome completo é obrigatório.')
        if not birth_date_str:
            errors.append('Data de nascimento é obrigatória.')
        if not validate_cpf(cpf_raw):
            errors.append('CPF inválido. Verifique os dígitos.')
        if not email or '@' not in email:
            errors.append('E-mail inválido.')
        if len(password) < 6:
            errors.append('A senha deve ter pelo menos 6 caracteres.')
        if password != password2:
            errors.append('As senhas não coincidem.')

        cpf = clean_cpf(cpf_raw)
        if not errors and Patient.query.filter_by(cpf=cpf).first():
            errors.append('Já existe um cadastro com este CPF.')

        birth_date = None
        if birth_date_str and not errors:
            try:
                birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d').date()
            except ValueError:
                errors.append('Data de nascimento inválida.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('auth/cadastro_paciente.html',
                                   form_data=request.form)

        patient = Patient(
            name=name,
            birth_date=birth_date,
            cpf=cpf,
            sus_card=sus_card or None,
            phone=phone or None,
            email=email,
            clinical_notes=clinical_notes or None,
        )
        patient.set_password(password)
        db.session.add(patient)
        db.session.commit()

        flash('Cadastro realizado com sucesso! Faça login para continuar.', 'success')
        return redirect(url_for('auth.login_paciente'))

    return render_template('auth/cadastro_paciente.html', form_data={})


# ---------------------------------------------------------------------------
# Login — Paciente
# ---------------------------------------------------------------------------
@auth_bp.route('/login/paciente', methods=['GET', 'POST'])
def login_paciente():
    if session.get('user_type') == 'patient':
        return redirect(url_for('patient.dashboard'))

    if request.method == 'POST':
        cpf_raw = request.form.get('cpf', '')
        password = request.form.get('password', '')
        cpf = clean_cpf(cpf_raw)

        patient = Patient.query.filter_by(cpf=cpf).first()
        if patient and patient.check_password(password):
            login_patient(patient)
            # Log de login
            from models import AccessLog
            log = AccessLog(
                patient_id=patient.id,
                action='login',
                description='Login realizado com sucesso.',
                ip_address=get_client_ip(),
                performed_by='patient',
            )
            db.session.add(log)
            db.session.commit()
            return redirect(url_for('patient.dashboard'))

        flash('CPF ou senha incorretos.', 'danger')
        return render_template('auth/login_paciente.html')

    return render_template('auth/login_paciente.html')


# ---------------------------------------------------------------------------
# Cadastro — Profissional
# ---------------------------------------------------------------------------
@auth_bp.route('/cadastro/profissional', methods=['GET', 'POST'])
def cadastro_profissional():
    if session.get('user_type') == 'professional':
        return redirect(url_for('professional.portal'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        prof_type = request.form.get('prof_type', '')
        registration_raw = request.form.get('registration', '').strip()
        cpf_raw = request.form.get('cpf', '')
        specialty = request.form.get('specialty', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        errors = []

        if not name:
            errors.append('Nome completo é obrigatório.')
        if prof_type not in dict(PROF_TYPES):
            errors.append('Tipo de profissional inválido.')
        if not validate_cpf(cpf_raw):
            errors.append('CPF inválido.')
        if not email or '@' not in email:
            errors.append('E-mail inválido.')
        if len(password) < 6:
            errors.append('A senha deve ter pelo menos 6 caracteres.')
        if password != password2:
            errors.append('As senhas não coincidem.')

        # Validação do registro profissional
        reg_valid, reg_error = validate_professional_registration(prof_type, registration_raw)
        if not reg_valid:
            errors.append(reg_error)

        registration = normalize_registration(prof_type, registration_raw)

        if not errors and Professional.query.filter_by(registration=registration).first():
            errors.append('Já existe um profissional cadastrado com este número de registro.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('auth/cadastro_profissional.html',
                                   prof_types=PROF_TYPES, form_data=request.form)

        professional = Professional(
            name=name,
            prof_type=prof_type,
            registration=registration,
            cpf=clean_cpf(cpf_raw),
            specialty=specialty or None,
            email=email,
        )
        professional.set_password(password)
        db.session.add(professional)
        db.session.commit()

        flash('Cadastro realizado com sucesso! Faça login para continuar.', 'success')
        return redirect(url_for('auth.login_profissional'))

    return render_template('auth/cadastro_profissional.html',
                           prof_types=PROF_TYPES, form_data={})


# ---------------------------------------------------------------------------
# Login — Profissional
# ---------------------------------------------------------------------------
@auth_bp.route('/login/profissional', methods=['GET', 'POST'])
def login_profissional():
    if session.get('user_type') == 'professional':
        return redirect(url_for('professional.portal'))

    if request.method == 'POST':
        registration = request.form.get('registration', '').strip().upper()
        password = request.form.get('password', '')

        professional = Professional.query.filter_by(registration=registration).first()
        if professional and professional.check_password(password):
            login_professional(professional)
            return redirect(url_for('professional.portal'))

        flash('Registro ou senha incorretos.', 'danger')
        return render_template('auth/login_profissional.html')

    return render_template('auth/login_profissional.html')


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
@auth_bp.route('/logout', methods=['POST'])
def logout():
    user_type = session.get('user_type')
    user_id = session.get('user_id')

    if user_type == 'patient' and user_id:
        from models import AccessLog
        log = AccessLog(
            patient_id=user_id,
            action='logout',
            description='Logout realizado.',
            ip_address=get_client_ip(),
            performed_by='patient',
        )
        db.session.add(log)
        db.session.commit()

    session.clear()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('auth.index'))


# ---------------------------------------------------------------------------
# Recuperar Senha (paciente)
# ---------------------------------------------------------------------------
@auth_bp.route('/recuperar-senha', methods=['GET', 'POST'])
def recuperar_senha():
    if request.method == 'POST':
        cpf_raw = request.form.get('cpf', '')
        cpf = clean_cpf(cpf_raw)

        patient = Patient.query.filter_by(cpf=cpf).first()

        # Por segurança, exibimos sempre a mesma mensagem
        flash(
            'Se este CPF estiver cadastrado, um e-mail com instruções '
            'de recuperação foi enviado.', 'info'
        )

        if patient:
            # Invalida resets anteriores
            PasswordReset.query.filter_by(
                patient_id=patient.id, used=False
            ).update({'used': True})
            db.session.commit()

            token = secrets.token_urlsafe(48)
            reset = PasswordReset(
                patient_id=patient.id,
                token=token,
                expires_at=datetime.utcnow() + timedelta(minutes=30),
            )
            db.session.add(reset)
            db.session.commit()

            # Envia e-mail
            try:
                from app import mail
                reset_url = url_for('auth.redefinir_senha',
                                    token=token, _external=True)
                msg = Message(
                    subject='MeuDocMed — Recuperação de Senha',
                    recipients=[patient.email],
                    body=(
                        f'Olá, {patient.name}!\n\n'
                        f'Clique no link abaixo para redefinir sua senha. '
                        f'O link expira em 30 minutos.\n\n'
                        f'{reset_url}\n\n'
                        f'Se não foi você que solicitou, ignore este e-mail.'
                    ),
                )
                mail.send(msg)
            except Exception:
                pass  # Não revela erro ao usuário

        return redirect(url_for('auth.login_paciente'))

    return render_template('auth/recuperar_senha.html')


# ---------------------------------------------------------------------------
# Redefinir Senha (paciente)
# ---------------------------------------------------------------------------
@auth_bp.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    reset = PasswordReset.query.filter_by(token=token).first()

    if not reset or not reset.is_valid:
        flash('Link inválido ou expirado. Solicite um novo.', 'danger')
        return redirect(url_for('auth.recuperar_senha'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        if len(password) < 6:
            flash('A senha deve ter pelo menos 6 caracteres.', 'danger')
            return render_template('auth/redefinir_senha.html', token=token)
        if password != password2:
            flash('As senhas não coincidem.', 'danger')
            return render_template('auth/redefinir_senha.html', token=token)

        patient = reset.patient
        patient.set_password(password)
        reset.used = True
        db.session.commit()

        # Log
        from models import AccessLog
        log = AccessLog(
            patient_id=patient.id,
            action='password_reset',
            description='Senha redefinida via link de recuperação.',
            ip_address=get_client_ip(),
            performed_by='patient',
        )
        db.session.add(log)
        db.session.commit()

        flash('Senha redefinida com sucesso! Faça login.', 'success')
        return redirect(url_for('auth.login_paciente'))

    return render_template('auth/redefinir_senha.html', token=token)
