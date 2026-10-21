"""
ComplianceAI — Admin Control Panel
===================================
Standalone lightweight Flask server for managing the compliance.db database.

Runs independently of the ML scanning pipeline so the dashboard never waits on
OCR model loading. Only needs: flask, flask-cors.

    python backend/admin_app.py            # http://127.0.0.1:5001
    ADMIN_PASSWORD=secret python backend/admin_app.py

Every change written here lands in the same SQLite database the scanner reads,
so rule and catalog edits are picked up by the next scan straight away.
"""

import os
import csv
import io
import json
import hmac
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime

from flask import Flask, jsonify, render_template, request, send_file, session, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import database
import rule_registry

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = database.DB_PATH
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

ADMIN_PASSWORD = config.ADMIN_PASSWORD
ADMIN_USER = config.ADMIN_USER

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=TEMPLATE_DIR)
app.secret_key = config.SECRET_KEY
CORS(app, resources={r'/api/*': config.cors_config()})

if config.TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

PAGE_SIZE = 25

SCAN_COLUMNS = [
    'id', 'scan_id', 'timestamp', 'product_name', 'category', 'score', 'grade',
    'is_compliant', 'violation_count', 'total_penalty', 'penalty_min',
    'penalty_max', 'image_name',
]
SCAN_JSON_COLUMNS = [
    'summary_json', 'rule_checks_json', 'violations_json', 'extracted_data_json',
    'insights_json', 'recommendations_json', 'fraud_analysis_json', 'barcode_data_json',
]
RULE_COLUMNS = [
    'rule_key', 'rule_name', 'act_section', 'description', 'severity',
    'default_weight', 'weight_non_food', 'penalty_first_offence',
    'penalty_subsequent_offence', 'enabled',
]
PRODUCT_COLUMNS = [
    'id', 'barcode', 'brand', 'product_name', 'category', 'standard_mrp',
    'standard_quantity', 'unit_sale_price', 'fssai_no', 'manufacturer_name',
    'manufacturer_address', 'country_of_origin', 'shelf_life_months', 'is_veg',
]


# ==================== DB HELPER ====================
def get_db():
    """Same connection helper the scanner uses, so both share one schema."""
    conn = database.get_db()
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def parse_json_field(value):
    if value in (None, '', b''):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {'_raw': str(value)}


# ==================== AUTH ====================
LOGIN_ATTEMPTS = {}


def require_login(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        return fn(*args, **kwargs)

    return wrapper


@app.route('/api/admin/login', methods=['POST'])
def login():
    payload = request.get_json(silent=True) or {}
    username = payload.get('username', '')
    password = payload.get('password', '')

    ip = request.remote_addr or 'unknown'
    now = time.time()
    attempts = [t for t in LOGIN_ATTEMPTS.get(ip, []) if now - t < 300]
    if len(attempts) >= 8:
        return jsonify({'error': 'Too many login attempts. Try again in a few minutes.'}), 429
    LOGIN_ATTEMPTS[ip] = attempts

    ok_user = hmac.compare_digest(str(username), str(ADMIN_USER))
    ok_pass = hmac.compare_digest(str(password), str(ADMIN_PASSWORD))
    if ok_user and ok_pass:
        LOGIN_ATTEMPTS.pop(ip, None)
        session['admin_authenticated'] = True
        session['login_time'] = datetime.now().isoformat()
        return jsonify({'success': True, 'user': ADMIN_USER})

    LOGIN_ATTEMPTS.setdefault(ip, []).append(now)
    return jsonify({'error': 'Invalid credentials'}), 401


@app.route('/api/admin/logout', methods=['POST'])
@require_login
def logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/admin/session', methods=['GET'])
def session_status():
    return jsonify({
        'authenticated': bool(session.get('admin_authenticated')),
        'user': ADMIN_USER if session.get('admin_authenticated') else None,
    })


# ==================== PAGE ====================
@app.route('/')
@app.route('/admin')
def admin_page():
    return render_template(
        'admin.html',
        scanner_url=config.PUBLIC_API_URL or 'http://localhost:5000/',
        portfolio_url=config.PORTFOLIO_URL or 'http://localhost:5500/index.html',
        default_password_hint=(not config.IS_PRODUCTION and ADMIN_PASSWORD == 'admin123'),
    )


# ==================== OVERVIEW ====================
@app.route('/api/admin/overview', methods=['GET'])
@require_login
def overview():
    conn = get_db()
    cur = conn.cursor()

    totals = cur.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN is_compliant = 1 THEN 1 ELSE 0 END) AS compliant,
               SUM(CASE WHEN is_compliant = 0 THEN 1 ELSE 0 END) AS failed,
               AVG(score) AS avg_score,
               SUM(violation_count) AS total_violations,
               SUM(penalty_min) AS penalty_min,
               SUM(penalty_max) AS penalty_max
        FROM scans
    """).fetchone()

    total = totals['total'] or 0
    compliant = totals['compliant'] or 0

    # Live registry state — the same numbers the scanner scores against
    engine = rule_registry.registry_summary()
    engine = {k: v for k, v in engine.items() if k != 'rules'}

    result = {
        'scans': {
            'total': total,
            'compliant': compliant,
            'failed': totals['failed'] or 0,
            'compliance_rate': round((compliant / total) * 100, 1) if total else 0.0,
            'avg_score': round(totals['avg_score'] or 0, 1),
            'total_violations': totals['total_violations'] or 0,
            'penalty_min': totals['penalty_min'] or 0,
            'penalty_max': totals['penalty_max'] or 0,
        },
        'catalog': {
            'products': cur.execute('SELECT COUNT(*) FROM product_catalog').fetchone()[0],
            'brands': cur.execute('SELECT COUNT(DISTINCT brand) FROM product_catalog').fetchone()[0],
            'categories': cur.execute('SELECT COUNT(DISTINCT category) FROM product_catalog').fetchone()[0],
        },
        'rules': {
            'total': cur.execute('SELECT COUNT(*) FROM legal_rules').fetchone()[0],
            'by_severity': rows_to_dicts(cur.execute(
                'SELECT severity, COUNT(*) AS count FROM legal_rules GROUP BY severity'
            )),
        },
        'engine': engine,
        'recent': rows_to_dicts(cur.execute(
            'SELECT id, scan_id, timestamp, product_name, category, score, grade, '
            'is_compliant, violation_count FROM scans ORDER BY id DESC LIMIT 8'
        )),
        'db': {
            'path': DB_PATH,
            'size_bytes': os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
            'integrity': cur.execute('PRAGMA integrity_check').fetchone()[0],
        },
        'server_time': datetime.now().isoformat(),
    }

    conn.close()
    return jsonify(result)


# ==================== SCANS ====================
@app.route('/api/admin/scans', methods=['GET'])
@require_login
def list_scans():
    conn = get_db()
    cur = conn.cursor()

    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    grade = request.args.get('grade', '').strip()
    category = request.args.get('category', '').strip()
    page = max(int(request.args.get('page', 1)), 1)
    per_page = min(int(request.args.get('per_page', PAGE_SIZE)), 200)
    offset = (page - 1) * per_page

    where, params = [], []
    if search:
        where.append('(product_name LIKE ? OR scan_id LIKE ? OR category LIKE ?)')
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    if status == 'compliant':
        where.append('is_compliant = 1')
    elif status == 'violation':
        where.append('is_compliant = 0')
    if grade:
        where.append('grade = ?')
        params.append(grade)
    if category:
        where.append('category = ?')
        params.append(category)

    clause = f'WHERE {" AND ".join(where)}' if where else ''

    total = cur.execute(f'SELECT COUNT(*) FROM scans {clause}', params).fetchone()[0]
    rows = cur.execute(
        f'SELECT {", ".join(SCAN_COLUMNS)} FROM scans {clause} ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [per_page, offset]
    ).fetchall()

    conn.close()
    return jsonify({
        'scans': rows_to_dicts(rows),
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': max((total + per_page - 1) // per_page, 1),
    })


@app.route('/api/admin/scans/<int:scan_row_id>', methods=['GET'])
@require_login
def get_scan(scan_row_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM scans WHERE id = ?', (scan_row_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({'error': 'Scan not found'}), 404

    scan = dict(row)
    for col in SCAN_JSON_COLUMNS:
        scan[col[:-5]] = parse_json_field(scan.pop(col))
    return jsonify(scan)


@app.route('/api/admin/scans/<int:scan_row_id>', methods=['DELETE'])
@require_login
def delete_scan(scan_row_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM scans WHERE id = ?', (scan_row_id,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return jsonify({'success': bool(deleted), 'deleted': deleted})


@app.route('/api/admin/scans', methods=['DELETE'])
@require_login
def clear_scans():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM scans')
    conn.commit()
    deleted = cur.rowcount
    conn.execute('VACUUM')
    conn.close()
    return jsonify({'success': True, 'deleted': deleted})


# ==================== LEGAL RULES ====================
@app.route('/api/admin/rules', methods=['GET'])
@require_login
def list_rules():
    conn = get_db()
    rows = conn.execute('SELECT * FROM legal_rules ORDER BY rule_key').fetchall()
    conn.close()
    return jsonify({'rules': rows_to_dicts(rows), 'count': len(rows)})


@app.route('/api/admin/rules/registry', methods=['GET'])
@require_login
def rules_registry():
    """The registry exactly as the scoring engine sees it right now."""
    summary = rule_registry.registry_summary()
    return jsonify({
        'summary': {k: v for k, v in summary.items() if k != 'rules'},
        'rules': summary['rules'],
    })


@app.route('/api/admin/rules/<path:rule_key>', methods=['GET'])
@require_login
def get_rule(rule_key):
    conn = get_db()
    row = conn.execute('SELECT * FROM legal_rules WHERE rule_key = ?', (rule_key,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Rule not found'}), 404
    return jsonify({'rule': dict(row)})


@app.route('/api/admin/rules/<path:rule_key>', methods=['PUT'])
@require_login
def update_rule(rule_key):
    payload = request.get_json(silent=True) or {}
    conn = get_db()
    cur = conn.cursor()

    existing = cur.execute('SELECT * FROM legal_rules WHERE rule_key = ?', (rule_key,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'error': 'Rule not found'}), 404

    fields, params = [], []
    for col in RULE_COLUMNS:
        if col == 'rule_key':
            continue
        if col in payload:
            value = payload[col]
            if col == 'enabled':
                value = 1 if value in (1, True, '1', 'true', 'on') else 0
            fields.append(f'{col} = ?')
            params.append(value)

    if fields:
        params.append(rule_key)
        cur.execute(f'UPDATE legal_rules SET {", ".join(fields)} WHERE rule_key = ?', params)
        conn.commit()

    row = cur.execute('SELECT * FROM legal_rules WHERE rule_key = ?', (rule_key,)).fetchone()
    conn.close()
    return jsonify({'success': True, 'rule': dict(row)})


@app.route('/api/admin/rules', methods=['POST'])
@require_login
def create_rule():
    payload = request.get_json(silent=True) or {}
    if not payload.get('rule_key'):
        return jsonify({'error': 'rule_key is required'}), 400

    conn = get_db()
    cur = conn.cursor()
    cols = [c for c in RULE_COLUMNS if c != 'rule_key']
    values = []
    for c in cols:
        if c == 'enabled':
            values.append(1 if payload.get('enabled', 1) in (1, True, '1', 'true', 'on') else 0)
        else:
            values.append(payload.get(c))
    try:
        cur.execute(
            f'INSERT INTO legal_rules ({", ".join(cols)}) '
            f'VALUES ({", ".join("?" for _ in cols)})',
            values
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': f"Rule '{payload['rule_key']}' already exists"}), 409
    row = cur.execute('SELECT * FROM legal_rules WHERE rule_key = ?', (payload['rule_key'],)).fetchone()
    conn.close()
    return jsonify({'success': True, 'rule': dict(row)}), 201



@app.route('/api/admin/rules/<path:rule_key>', methods=['DELETE'])
@require_login
def delete_rule(rule_key):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM legal_rules WHERE rule_key = ?', (rule_key,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return jsonify({'success': bool(deleted), 'deleted': deleted})


# ==================== PRODUCT CATALOG ====================
@app.route('/api/admin/products', methods=['GET'])
@require_login
def list_products():
    conn = get_db()
    cur = conn.cursor()
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()

    where, params = [], []
    if search:
        where.append('(product_name LIKE ? OR brand LIKE ? OR barcode LIKE ? OR fssai_no LIKE ?)')
        params += [f'%{search}%'] * 4
    if category:
        where.append('category = ?')
        params.append(category)

    clause = f'WHERE {" AND ".join(where)}' if where else ''
    rows = cur.execute(
        f'SELECT * FROM product_catalog {clause} ORDER BY brand, product_name', params
    ).fetchall()
    categories = rows_to_dicts(cur.execute(
        'SELECT DISTINCT category FROM product_catalog ORDER BY category'
    ))
    conn.close()
    return jsonify({'products': rows_to_dicts(rows), 'count': len(rows), 'categories': categories})


@app.route('/api/admin/products/<int:product_id>', methods=['PUT'])
@require_login
def update_product(product_id):
    payload = request.get_json(silent=True) or {}
    conn = get_db()
    cur = conn.cursor()

    if not cur.execute('SELECT 1 FROM product_catalog WHERE id = ?', (product_id,)).fetchone():
        conn.close()
        return jsonify({'error': 'Product not found'}), 404

    fields, params = [], []
    for col in PRODUCT_COLUMNS:
        if col == 'id':
            continue
        if col in payload:
            fields.append(f'{col} = ?')
            params.append(payload[col])

    if fields:
        params.append(product_id)
        cur.execute(f'UPDATE product_catalog SET {", ".join(fields)} WHERE id = ?', params)
        conn.commit()

    row = cur.execute('SELECT * FROM product_catalog WHERE id = ?', (product_id,)).fetchone()
    conn.close()
    return jsonify({'success': True, 'product': dict(row)})


@app.route('/api/admin/products', methods=['POST'])
@require_login
def create_product():
    payload = request.get_json(silent=True) or {}
    if not payload.get('product_name'):
        return jsonify({'error': 'product_name is required'}), 400

    conn = get_db()
    cur = conn.cursor()
    cols = [c for c in PRODUCT_COLUMNS if c != 'id']
    try:
        cur.execute(
            f'INSERT INTO product_catalog ({", ".join(cols)}) '
            f'VALUES ({", ".join("?" for _ in cols)})',
            [payload.get(c) for c in cols]
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': f"Barcode '{payload.get('barcode')}' already exists"}), 409
    row = cur.execute('SELECT * FROM product_catalog WHERE id = ?', (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify({'success': True, 'product': dict(row)}), 201


@app.route('/api/admin/products/<int:product_id>', methods=['DELETE'])
@require_login
def delete_product(product_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM product_catalog WHERE id = ?', (product_id,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return jsonify({'success': bool(deleted), 'deleted': deleted})


# ==================== EXPORT / BACKUP ====================
@app.route('/api/admin/export/<table>.csv')
@require_login
def export_csv(table):
    allowed = {'scans': SCAN_COLUMNS, 'legal_rules': RULE_COLUMNS, 'product_catalog': PRODUCT_COLUMNS}
    if table not in allowed:
        return jsonify({'error': 'Unknown table'}), 404

    conn = get_db()
    rows = conn.execute(f'SELECT * FROM {table}').fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(allowed[table])
    for r in rows:
        writer.writerow([r[c] for c in allowed[table]])

    filename = f'{table}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return send_file(
        io.BytesIO(buf.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )


@app.route('/api/admin/backup')
@require_login
def backup():
    if not os.path.exists(DB_PATH):
        return jsonify({'error': 'Database file missing'}), 404

    tmpdir = tempfile.mkdtemp()
    archive = os.path.join(tmpdir, 'compliance_backup.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(DB_PATH, 'compliance.db')
    return send_file(
        archive,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'compliance_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip',
    )


@app.route('/api/admin/backup', methods=['POST'])
@require_login
def restore_backup():
    upload = request.files.get('file')
    if not upload:
        return jsonify({'error': 'No file uploaded'}), 400

    tmpdir = tempfile.mkdtemp()
    saved = os.path.join(tmpdir, upload.filename)
    upload.save(saved)

    try:
        if zipfile.is_zipfile(saved):
            with zipfile.ZipFile(saved) as zf:
                member = [m for m in zf.namelist() if m.endswith('.db')]
                if not member:
                    return jsonify({'error': 'Archive contains no .db file'}), 400
                with zf.open(member[0]) as src, open(DB_PATH, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
        else:
            shutil.copy(saved, DB_PATH)

        conn = get_db()
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        conn.close()
        if integrity != 'ok':
            return jsonify({'error': f'Restored database failed integrity check: {integrity}'}), 400

        return jsonify({'success': True, 'message': 'Database restored', 'integrity': integrity})
    except Exception as exc:
        return jsonify({'error': f'Restore failed: {exc}'}), 500


@app.route('/api/admin/vacuum', methods=['POST'])
@require_login
def vacuum():
    conn = get_db()
    conn.execute('VACUUM')
    conn.close()
    return jsonify({'success': True, 'size_bytes': os.path.getsize(DB_PATH)})


if __name__ == '__main__':
    import socket

    port = int(os.environ.get('ADMIN_PORT', 5001))
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except OSError:
        local_ip = '127.0.0.1'

    print('\n' + '=' * 62)
    print('  COMPLIANCE AI — ADMIN CONTROL PANEL')
    print('=' * 62)
    print(f'  Local:        http://127.0.0.1:{port}/admin')
    print(f'  Network:      http://{local_ip}:{port}/admin')
    print(f'  Database:     {DB_PATH}')
    print(f'  Default user: {ADMIN_USER} / (ADMIN_PASSWORD env var)')
    print('=' * 62 + '\n')
    app.run(debug=False, host='0.0.0.0', port=port)
