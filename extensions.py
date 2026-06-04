"""Instâncias de extensões Flask compartilhadas (evita importação circular)."""
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail

csrf = CSRFProtect()
mail = Mail()
