"""
Production configuration shared by the scanner API and the admin console.

Every value can be overridden with an environment variable, so the same code
runs locally (defaults) and on a hosted instance (env vars set by the host).

    ADMIN_PASSWORD   password for the admin console (default: admin123)
    ADMIN_USER       admin username (default: admin)
    SECRET_KEY       session signing key - MUST be set in production
    CORS_ORIGINS     comma separated list of allowed browser origins
    DB_PATH          absolute path to the SQLite file
    TRUST_PROXY      "1" when running behind nginx / Render / Railway
    PUBLIC_API_URL   public URL of the scanner API (used in admin messages)
"""
import os


def _bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _csv(name, default=''):
    raw = os.environ.get(name, default)
    return [p.strip() for p in raw.split(',') if p.strip()]


# --- admin auth -----------------------------------------------------------
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# A random key per process is fine locally but invalidates every session on
# restart, so production must supply a stable one.
_secret = os.environ.get('SECRET_KEY')
IS_PRODUCTION = _bool('FLASK_ENV_PRODUCTION') or bool(os.environ.get('RENDER')) or bool(os.environ.get('RAILWAY_ENVIRONMENT')) or bool(os.environ.get('DYNO'))
if not _secret:
    if IS_PRODUCTION:
        raise RuntimeError('SECRET_KEY must be set in production')
    _secret = os.urandom(32)
SECRET_KEY = _secret

# --- network --------------------------------------------------------------
# '*' keeps the current open behaviour (the portfolio is served from another
# origin); a comma separated list locks the API down to known front-ends.
CORS_ORIGINS = _csv('CORS_ORIGINS', '*')
TRUST_PROXY = _bool('TRUST_PROXY', IS_PRODUCTION)
PUBLIC_API_URL = os.environ.get('PUBLIC_API_URL', '').rstrip('/')
PUBLIC_ADMIN_URL = os.environ.get('PUBLIC_ADMIN_URL', '').rstrip('/')
PORTFOLIO_URL = os.environ.get('PORTFOLIO_URL', '').rstrip('/')


def cors_config():
    if '*' in CORS_ORIGINS:
        return {'origins': '*'}
    return {'origins': CORS_ORIGINS}
