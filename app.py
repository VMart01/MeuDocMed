"""
MeuDocMed — Aplicação Flask principal.
"""
import os
from datetime import datetime
from flask import Flask, render_template, send_from_directory, jsonify, session, abort
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

from config import config
from models import db

load_dotenv()

mail = Mail()
csrf = CSRFProtect()


def _migrate_columns(database):
    """Adiciona colunas novas em tabelas existentes sem destruir dados."""
    migrations = [
        ('documents', 'storage_type', "VARCHAR(20) DEFAULT 'local'"),
        ('documents', 'storage_meta', 'TEXT'),
        ('documents', 'shard3_hex',   'TEXT'),
    ]
    with database.engine.connect() as conn:
        for table, column, col_def in migrations:
            try:
                conn.execute(database.text(f'ALTER TABLE {table} ADD COLUMN {column} {col_def}'))
                conn.commit()
            except Exception:
                conn.rollback()


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    from routes.auth import auth_bp
    from routes.patient import patient_bp
    from routes.professional import professional_bp
    from routes.share import share_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(professional_bp)
    app.register_blueprint(share_bp)

    @app.context_processor
    def inject_now():
        return {'now': datetime.utcnow()}

    @app.template_filter('formatar_data')
    def formatar_data(value):
        if value is None:
            return ''
        if hasattr(value, 'strftime'):
            return value.strftime('%d/%m/%Y')
        return str(value)

    with app.app_context():
        db.create_all()
        _migrate_columns(db)

    @app.route('/sw.js')
    def service_worker():
        return send_from_directory(app.static_folder, 'sw.js',
                                   mimetype='application/javascript')

    @app.route('/admin/clouds_status')
    def clouds_status():
        if not session.get('user_type'):
            abort(403)
        from storage_shamir import clouds_status as _status
        return jsonify(_status())

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
