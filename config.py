import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-TROQUE-EM-PRODUCAO'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = 3600

    # Upload
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    ALLOWED_EXTENSIONS = {
        'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
        'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip'
    }

    # Cloudinary (armazenamento persistente de uploads em produção)
    CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME')
    CLOUDINARY_API_KEY    = os.environ.get('CLOUDINARY_API_KEY')
    CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')

    # Mail
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or 'smtp.gmail.com'
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'noreply@meudocmed.com'

    # Sessão permanente
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Gov.br OAuth 2.0 / OpenID Connect
    # Obtenha as credenciais em: https://www.gov.br/governodigital/pt-br/apis/acesso-gov.br
    GOVBR_CLIENT_ID     = os.environ.get('GOVBR_CLIENT_ID', '')
    GOVBR_CLIENT_SECRET = os.environ.get('GOVBR_CLIENT_SECRET', '')
    GOVBR_REDIRECT_URI  = os.environ.get('GOVBR_REDIRECT_URI', 'http://localhost:5000/auth/govbr/callback')
    GOVBR_AUTH_URL      = 'https://sso.acesso.gov.br/authorize'
    GOVBR_TOKEN_URL     = 'https://sso.acesso.gov.br/token'
    GOVBR_USERINFO_URL  = 'https://sso.acesso.gov.br/userinfo'

    # Google OAuth 2.0
    # Obtenha em: https://console.cloud.google.com → APIs e Serviços → Credenciais
    GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    GOOGLE_REDIRECT_URI  = os.environ.get('GOOGLE_REDIRECT_URI',
                                           'http://localhost:5000/auth/google/callback')


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL') or
        'sqlite:///' + os.path.join(basedir, 'meudocmed.db')
    )


class ProductionConfig(Config):
    DEBUG = False
    db_url = os.environ.get('DATABASE_URL', '')
    # Render fornece URLs postgres://, SQLAlchemy precisa de postgresql://
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = db_url or (
        'sqlite:///' + os.path.join(basedir, 'meudocmed.db')
    )


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
