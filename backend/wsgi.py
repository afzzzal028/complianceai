"""
Single entry point that serves the scanner and the admin console from one
process and one port - the shape a hosted instance needs.

    /                 scanner UI
    /api/*            scanner API
    /admin            admin console
    /api/admin/*      admin API

Run it with:
    gunicorn --bind 0.0.0.0:5000 wsgi:application --chdir backend
"""
from app import app as scanner_app
from admin_app import app as admin_app


def _is_admin_path(path):
    return path.startswith('/api/admin') or path == '/admin' or path.startswith('/admin/')


def application(environ, start_response):
    """Route admin traffic to the admin app, everything else to the scanner."""
    path = environ.get('PATH_INFO', '')
    if _is_admin_path(path):
        return admin_app(environ, start_response)
    return scanner_app(environ, start_response)
