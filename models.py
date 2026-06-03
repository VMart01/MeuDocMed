from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# Paciente
# ---------------------------------------------------------------------------
class Patient(db.Model):
    __tablename__ = 'patients'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    birth_date = db.Column(db.Date, nullable=False)
    cpf = db.Column(db.String(11), unique=True, nullable=False)
    sus_card = db.Column(db.String(20), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    clinical_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    govbr_verified = db.Column(db.Boolean, default=False)  # identidade verificada via Gov.br
    google_sub     = db.Column(db.String(128), unique=True, nullable=True)  # Google OAuth subject ID
    ext_token_hash = db.Column(db.String(64), nullable=True)               # Token da extensão Chrome

    documents = db.relationship('Document', backref='patient', lazy='dynamic',
                                cascade='all, delete-orphan')
    medications = db.relationship('Medication', backref='patient', lazy='dynamic',
                                  cascade='all, delete-orphan')
    access_requests = db.relationship('AccessRequest', backref='patient', lazy='dynamic',
                                      cascade='all, delete-orphan')
    share_links = db.relationship('ShareLink', backref='patient', lazy='dynamic',
                                  cascade='all, delete-orphan')
    access_logs = db.relationship('AccessLog', backref='patient', lazy='dynamic',
                                  cascade='all, delete-orphan')
    password_resets = db.relationship('PasswordReset', backref='patient', lazy='dynamic',
                                      cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def cpf_formatted(self):
        c = self.cpf
        if len(c) == 11:
            return f'{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}'
        return c

    def __repr__(self):
        return f'<Patient {self.name}>'


# ---------------------------------------------------------------------------
# Profissional de Saúde
# ---------------------------------------------------------------------------
PROF_TYPES = [
    ('medico', 'Médico'),
    ('enfermeiro', 'Enfermeiro'),
    ('dentista', 'Dentista'),
    ('farmaceutico', 'Farmacêutico'),
    ('fisioterapeuta', 'Fisioterapeuta'),
    ('acs', 'Agente Comunitário de Saúde'),
]

PROF_COUNCILS = {
    'medico': 'CRM',
    'enfermeiro': 'COREN',
    'dentista': 'CRO',
    'farmaceutico': 'CRF',
    'fisioterapeuta': 'CREFITO',
    'acs': 'CPF',
}


class Professional(db.Model):
    __tablename__ = 'professionals'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    prof_type = db.Column(db.String(50), nullable=False)
    registration = db.Column(db.String(60), unique=True, nullable=False)
    cpf = db.Column(db.String(11), nullable=False)
    specialty = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    registration_verified = db.Column(db.Boolean, default=False)  # registro verificado via API do conselho

    access_requests = db.relationship('AccessRequest', backref='professional', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def prof_type_display(self):
        return dict(PROF_TYPES).get(self.prof_type, self.prof_type)

    @property
    def council_label(self):
        return PROF_COUNCILS.get(self.prof_type, '')

    def __repr__(self):
        return f'<Professional {self.name}>'


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------
DOCUMENT_CATEGORIES = [
    ('exame_lab', 'Exame Laboratorial'),
    ('exame_img', 'Exame de Imagem'),
    ('relatorio', 'Relatório Médico'),
    ('receita', 'Receita'),
    ('laudo', 'Laudo'),
    ('vacina', 'Vacina'),
    ('internacao', 'Internação'),
    ('cirurgia', 'Cirurgia'),
    ('outro', 'Outro'),
]


class Document(db.Model):
    __tablename__ = 'documents'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    uploaded_by_professional_id = db.Column(
        db.Integer, db.ForeignKey('professionals.id'), nullable=True
    )
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    filename = db.Column(db.String(255), nullable=False)       # nome armazenado no servidor
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    observation = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    storage_type = db.Column(db.String(20), default='local')     # 'local', 'cloudinary', 'shamir'
    storage_meta = db.Column(db.Text, nullable=True)             # JSON: file_id, nonce_hex, salt_hex, ext

    uploader_professional = db.relationship('Professional', foreign_keys=[uploaded_by_professional_id])

    @property
    def category_display(self):
        return dict(DOCUMENT_CATEGORIES).get(self.category, self.category)

    @property
    def file_size_display(self):
        size = self.file_size
        if size < 1024:
            return f'{size} B'
        elif size < 1024 * 1024:
            return f'{size / 1024:.1f} KB'
        else:
            return f'{size / (1024 * 1024):.1f} MB'

    @property
    def extension(self):
        return self.original_filename.rsplit('.', 1)[-1].lower() if '.' in self.original_filename else ''

    @property
    def is_viewable_inline(self):
        return self.extension in {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

    def __repr__(self):
        return f'<Document {self.name}>'


# ---------------------------------------------------------------------------
# Medicamento
# ---------------------------------------------------------------------------
MEDICATION_ROUTES = [
    ('oral', 'Oral'),
    ('sublingual', 'Sublingual'),
    ('topica', 'Tópica'),
    ('inalatoria', 'Inalatória'),
    ('endovenosa', 'Endovenosa'),
    ('intramuscular', 'Intramuscular'),
    ('subcutanea', 'Subcutânea'),
    ('ocular', 'Ocular'),
    ('nasal', 'Nasal'),
    ('outra', 'Outra'),
]


class Medication(db.Model):
    __tablename__ = 'medications'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    dose = db.Column(db.String(100), nullable=True)
    frequency = db.Column(db.String(100), nullable=True)
    route = db.Column(db.String(30), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    prescriber = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def route_display(self):
        return dict(MEDICATION_ROUTES).get(self.route, self.route or '')

    def __repr__(self):
        return f'<Medication {self.name}>'


# ---------------------------------------------------------------------------
# Solicitação de Acesso
# ---------------------------------------------------------------------------
ACCESS_DURATIONS = [10, 30, 60, 120]  # minutos


class AccessRequest(db.Model):
    __tablename__ = 'access_requests'

    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending/approved/denied/expired/revoked
    allow_download = db.Column(db.Boolean, default=False)
    access_minutes = db.Column(db.Integer, nullable=True)
    message = db.Column(db.String(500), nullable=True)   # mensagem do profissional ao solicitar
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_active(self):
        if self.status != 'approved':
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def __repr__(self):
        return f'<AccessRequest prof={self.professional_id} pat={self.patient_id} status={self.status}>'


# ---------------------------------------------------------------------------
# Link de Compartilhamento Temporário
# ---------------------------------------------------------------------------
class ShareLink(db.Model):
    __tablename__ = 'share_links'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(200), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_accessed = db.Column(db.DateTime, nullable=True)
    is_revoked = db.Column(db.Boolean, default=False)

    @property
    def is_valid(self):
        if self.is_revoked:
            return False
        return datetime.utcnow() <= self.expires_at

    @property
    def status_display(self):
        if self.is_revoked:
            return 'Revogado'
        if datetime.utcnow() > self.expires_at:
            return 'Expirado'
        return 'Ativo'

    def __repr__(self):
        return f'<ShareLink {self.token[:8]}...>'


# ---------------------------------------------------------------------------
# Log de Acesso
# ---------------------------------------------------------------------------
LOG_ACTIONS = {
    'login': 'Login',
    'logout': 'Logout',
    'upload': 'Upload de documento',
    'delete_doc': 'Exclusão de documento',
    'view_doc': 'Visualização de documento',
    'download_doc': 'Download de documento',
    'edit_doc': 'Edição de documento',
    'edit_profile': 'Edição de perfil',
    'change_password': 'Alteração de senha',
    'access_request': 'Solicitação de acesso (profissional)',
    'access_approved': 'Acesso aprovado',
    'access_denied': 'Acesso negado',
    'access_prontuario': 'Acesso ao prontuário',
    'password_reset': 'Redefinição de senha',
    'delete_account': 'Exclusão de conta',
    'share_link_created': 'Link de compartilhamento criado',
    'share_link_accessed': 'Link de compartilhamento acessado',
    'share_link_revoked': 'Link de compartilhamento revogado',
    'add_medication': 'Medicamento adicionado',
    'edit_medication': 'Medicamento editado',
    'delete_medication': 'Medicamento excluído',
    'prof_upload': 'Upload por profissional',
}


class AccessLog(db.Model):
    __tablename__ = 'access_logs'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    performed_by = db.Column(db.String(20), default='patient')  # 'patient' ou 'professional'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    professional_ref = db.relationship('Professional', foreign_keys=[professional_id])

    @property
    def action_display(self):
        return LOG_ACTIONS.get(self.action, self.action)

    def __repr__(self):
        return f'<AccessLog {self.action} pat={self.patient_id}>'


# ---------------------------------------------------------------------------
# Redefinição de Senha
# ---------------------------------------------------------------------------
class PasswordReset(db.Model):
    __tablename__ = 'password_resets'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    @property
    def is_valid(self):
        return not self.used and datetime.utcnow() <= self.expires_at

    def __repr__(self):
        return f'<PasswordReset pat={self.patient_id}>'


# ---------------------------------------------------------------------------
# Upload pendente (retry automático de shards Shamir com falha)
# ---------------------------------------------------------------------------
class PendingUpload(db.Model):
    __tablename__ = 'pending_uploads'

    id = db.Column(db.Integer, primary_key=True)
    doc_id = db.Column(db.Integer, db.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)
    provider = db.Column(db.String(20), nullable=False)
    object_key = db.Column(db.String(255), nullable=False)
    data_hex = db.Column(db.Text, nullable=False)
    attempts = db.Column(db.Integer, default=0)
    last_attempt = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    document = db.relationship('Document', backref=db.backref(
                               'pending_uploads', cascade='all, delete-orphan',
                               passive_deletes=True))

    def __repr__(self):
        return f'<PendingUpload doc={self.doc_id} provider={self.provider}>'

