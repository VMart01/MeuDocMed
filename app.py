"""
MeuDocMed — Aplicação Flask principal.
"""
import os
from datetime import datetime
from flask import Flask, render_template, send_from_directory
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

from config import config
from models import db

load_dotenv()

mail = Mail()
csrf = CSRFProtect()


def create_app(config_name: str = None) -> Flask:
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Render usa proxy reverso — necessário para HTTPS, IPs reais e CSRF correto
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Inicializa extensões
    db.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)

    # Garante que a pasta de uploads existe
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Registra blueprints
    from routes.auth import auth_bp
    from routes.patient import patient_bp
    from routes.professional import professional_bp
    from routes.share import share_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(professional_bp)
    app.register_blueprint(share_bp)

    # Injeta `now` em todos os templates (para usar {{ now.year }}, etc.)
    @app.context_processor
    def inject_now():
        return {'now': datetime.utcnow()}

    # Cria tabelas se não existirem
    with app.app_context():
        db.create_all()

    # Service Worker — precisa estar na raiz do domínio
    @app.route('/sw.js')
    def service_worker():
        return send_from_directory(app.static_folder, 'sw.js',
                                   mimetype='application/javascript')

    # Handlers de erro
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(413)
    def too_large(e):
        return render_template('errors/413.html'), 413

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
