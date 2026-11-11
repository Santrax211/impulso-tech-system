"""Impulso Tech · Sistema de cotizaciones (Flask + SQLite)."""
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

from flask import Flask, g, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

import pdfgen

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("IMPULSO_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "cotizaciones.db")
LOGO_PATH = os.path.join(BASE_DIR, "static", "logo.png")
os.makedirs(DATA_DIR, exist_ok=True)

IGV_RATE = Decimal("0.18")
MIN_PASSWORD = 10
MAX_FAILS = 5
LOCK_SECONDS = 15 * 60

DEFAULT_SETTINGS = {
    "business_name": "Impulso Tech",
    "tagline": "Tecnología & Innovación Digital",
    "ruc": "",
    "phone": "",
    "email": "",
    "web": "",
    "address": "",
    "payment_info": "",
    "default_conditions": (
        "- 50% de adelanto para iniciar el trabajo y 50% restante contra entrega.\n"
        "- Los plazos de entrega se cuentan desde la confirmación del adelanto."
    ),
    "default_valid_days": "7",
    "next_number": "1",
}
SETTING_LIMITS = {
    "business_name": 80, "tagline": 120, "ruc": 20, "phone": 40, "email": 120,
    "web": 120, "address": 200, "payment_info": 600, "default_conditions": 3000,
}


def _load_secret():
    env = os.environ.get("IMPULSO_SECRET")
    if env:
        return env
    path = os.path.join(DATA_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    with open(path) as fh:
        return fh.read().strip()


SECRET = _load_secret()
PDF_OWNER_PASSWORD = hmac.new(SECRET.encode(), b"pdf-owner", hashlib.sha256).hexdigest()

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(
    SECRET_KEY=SECRET,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("IMPULSO_HTTPS") == "1",
    PERMANENT_SESSION_LIFETIME=12 * 3600,
    MAX_CONTENT_LENGTH=1024 * 1024,
    JSON_AS_ASCII=False,
)
if os.environ.get("IMPULSO_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ---------------------------------------------------------------- base de datos
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE NOT NULL COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotes(
  id INTEGER PRIMARY KEY,
  number TEXT UNIQUE NOT NULL,
  issue_date TEXT NOT NULL,
  valid_days INTEGER NOT NULL,
  client_name TEXT NOT NULL,
  client_doc TEXT NOT NULL DEFAULT '',
  client_phone TEXT NOT NULL DEFAULT '',
  items TEXT NOT NULL,
  discount_type TEXT NOT NULL,
  discount_value TEXT NOT NULL,
  igv_mode TEXT NOT NULL,
  subtotal TEXT NOT NULL,
  discount_amount TEXT NOT NULL,
  base TEXT NOT NULL,
  igv TEXT NOT NULL,
  total TEXT NOT NULL,
  conditions TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enviada',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_quotes_client ON quotes(client_name);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY,
  quote_id INTEGER,
  doc_type TEXT NOT NULL,
  series TEXT NOT NULL,
  number TEXT NOT NULL,
  issue_date TEXT NOT NULL,
  client_name TEXT NOT NULL,
  client_doc TEXT NOT NULL DEFAULT '',
  client_phone TEXT NOT NULL DEFAULT '',
  items TEXT NOT NULL,
  discount_type TEXT NOT NULL,
  discount_value TEXT NOT NULL,
  igv_mode TEXT NOT NULL,
  subtotal TEXT NOT NULL,
  discount_amount TEXT NOT NULL,
  base TEXT NOT NULL,
  igv TEXT NOT NULL,
  total TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'emitido',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(doc_type, series, number));
CREATE INDEX IF NOT EXISTS idx_documents_quote ON documents(quote_id);
CREATE TABLE IF NOT EXISTS login_attempts(
  id INTEGER PRIMARY KEY, ip TEXT NOT NULL, ts REAL NOT NULL);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value))
    conn.close()


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def set_user(conn, username, password):
    conn.execute(
        "INSERT INTO users(username, password_hash, created_at) VALUES(?, ?, ?) "
        "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash",
        (username, generate_password_hash(password), now_iso()),
    )


def bootstrap_user_from_env():
    """Permite crear el usuario con variables de entorno si aún no existe ninguno."""
    user, pwd = os.environ.get("IMPULSO_USER"), os.environ.get("IMPULSO_PASSWORD")
    if not (user and pwd) or len(pwd) < MIN_PASSWORD:
        return
    conn = connect()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        set_user(conn, user.strip(), pwd)
    conn.close()


init_db()
bootstrap_user_from_env()


def db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def get_settings():
    rows = db().execute("SELECT key, value FROM settings").fetchall()
    out = dict(DEFAULT_SETTINGS)
    out.update({r["key"]: r["value"] for r in rows})
    return out


# ---------------------------------------------------------------- validación / cálculo
class ValidationError(ValueError):
    pass


CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value, label, max_len, required=False):
    text = CTRL.sub("", str(value if value is not None else "")).strip()
    if required and not text:
        raise ValidationError(f"{label}: campo obligatorio.")
    if len(text) > max_len:
        raise ValidationError(f"{label}: máximo {max_len} caracteres.")
    return text


def dec(value, label, minimum, maximum):
    raw = str(value if value is not None else "").strip().replace(",", ".")
    if raw == "":
        raise ValidationError(f"{label}: ingresa un valor.")
    try:
        d = Decimal(raw)
    except InvalidOperation:
        raise ValidationError(f"{label}: número no válido.")
    if not d.is_finite() or d < minimum or d > maximum:
        raise ValidationError(f"{label}: valor fuera de rango.")
    return d


def q2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute(items, discount_type, discount_value, igv_mode):
    subtotal = q2(sum((q2(i["qty"] * i["price"]) for i in items), Decimal(0)))
    if discount_type == "percent":
        disc = q2(subtotal * discount_value / 100)
    elif discount_type == "amount":
        disc = q2(discount_value)
    else:
        disc = Decimal("0.00")
    disc = min(disc, subtotal)
    net = subtotal - disc
    if igv_mode == "add":
        base, igv = net, q2(net * IGV_RATE)
        total = base + igv
    elif igv_mode == "included":
        total = net
        base = q2(total / (1 + IGV_RATE))
        igv = total - base
    else:
        base, igv, total = net, Decimal("0.00"), net
    return {"subtotal": subtotal, "discount_amount": disc, "base": base, "igv": igv, "total": total}


def clean_quote(data):
    if not isinstance(data, dict):
        raise ValidationError("Datos no válidos.")
    name = clean_text(data.get("client_name"), "Cliente", 120, required=True)
    doc = re.sub(r"\s", "", clean_text(data.get("client_doc"), "DNI/RUC", 20))
    if doc and not (doc.isdigit() and len(doc) in (8, 11)):
        raise ValidationError("DNI/RUC: debe tener 8 dígitos (DNI) u 11 dígitos (RUC).")
    phone = clean_text(data.get("client_phone"), "Teléfono", 30)
    if phone and not re.fullmatch(r"[0-9+()\-\s]{6,30}", phone):
        raise ValidationError("Teléfono: usa solo números, espacios, + - ( ).")

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not (1 <= len(raw_items) <= 50):
        raise ValidationError("Agrega entre 1 y 50 servicios.")
    items = []
    for n, it in enumerate(raw_items, 1):
        if not isinstance(it, dict):
            raise ValidationError(f"Ítem {n}: datos no válidos.")
        items.append({
            "desc": clean_text(it.get("desc"), f"Ítem {n} · descripción", 2000, required=True),
            "qty": dec(it.get("qty"), f"Ítem {n} · cantidad", Decimal("0.001"), Decimal("1000000")).quantize(Decimal("0.001")),
            "price": q2(dec(it.get("price"), f"Ítem {n} · precio", Decimal(0), Decimal("1000000000"))),
        })

    discount_type = data.get("discount_type", "none")
    if discount_type not in ("none", "percent", "amount"):
        raise ValidationError("Tipo de descuento no válido.")
    if discount_type == "none":
        discount_value = Decimal(0)
    else:
        top = Decimal(100) if discount_type == "percent" else Decimal("1000000000")
        discount_value = dec(data.get("discount_value") or "0", "Descuento", Decimal(0), top)

    igv_mode = data.get("igv_mode", "none")
    if igv_mode not in ("none", "add", "included"):
        raise ValidationError("Modo de IGV no válido.")
    status = data.get("status", "enviada")
    if status not in ("enviada", "aceptada", "rechazada"):
        raise ValidationError("Estado no válido.")
    try:
        valid_days = int(data.get("valid_days"))
    except (TypeError, ValueError):
        raise ValidationError("Validez: ingresa un número de días.")
    if not 1 <= valid_days <= 365:
        raise ValidationError("Validez: entre 1 y 365 días.")
    issue_date = str(data.get("issue_date") or date.today().isoformat())
    try:
        date.fromisoformat(issue_date)
    except ValueError:
        raise ValidationError("Fecha no válida.")

    totals = compute(items, discount_type, discount_value, igv_mode)
    return {
        "client_name": name, "client_doc": doc, "client_phone": phone, "items": items,
        "discount_type": discount_type, "discount_value": discount_value, "igv_mode": igv_mode,
        "status": status, "valid_days": valid_days, "issue_date": issue_date,
        "conditions": clean_text(data.get("conditions"), "Condiciones", 3000),
        **totals,
    }


def items_to_json(items):
    return json.dumps([{"desc": i["desc"], "qty": str(i["qty"]), "price": str(i["price"])} for i in items], ensure_ascii=False)


def quote_out(row):
    d = {k: row[k] for k in row.keys()}
    d["items"] = json.loads(row["items"])
    for it in d["items"]:
        it["amount"] = str(q2(Decimal(it["qty"]) * Decimal(it["price"])))
    return d


# ---------------------------------------------------------------- seguridad
@app.after_request
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if app.config["SESSION_COOKIE_SECURE"]:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def api_error(message, status):
    return jsonify({"error": message}), status


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
        sent = request.headers.get("X-CSRF-Token", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            return api_error("Sesión inválida. Recarga la página.", 403)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            return api_error("Inicia sesión.", 401)
        return fn(*args, **kwargs)
    return wrapper


@app.errorhandler(404)
def not_found(_e):
    return api_error("No encontrado.", 404)


@app.errorhandler(405)
def bad_method(_e):
    return api_error("Método no permitido.", 405)


@app.errorhandler(413)
def too_large(_e):
    return api_error("Solicitud demasiado grande.", 413)


@app.errorhandler(ValidationError)
def on_validation(e):
    return api_error(str(e), 400)


@app.errorhandler(500)
def on_error(_e):
    return api_error("Error interno del servidor.", 500)


# ---------------------------------------------------------------- páginas y sesión
@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "index.html")


@app.get("/api/session")
def session_info():
    return jsonify({"authenticated": bool(session.get("uid")), "user": session.get("user"), "csrf": csrf_token()})


@app.post("/api/login")
def login():
    ip = request.remote_addr or "?"
    conn = db()
    conn.execute("DELETE FROM login_attempts WHERE ts < ?", (time.time() - LOCK_SECONDS,))
    fails = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE ip=?", (ip,)).fetchone()[0]
    if fails >= MAX_FAILS:
        return api_error("Demasiados intentos. Espera 15 minutos.", 429)
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    # Se verifica siempre un hash para igualar tiempos de respuesta.
    stored = row["password_hash"] if row else generate_password_hash("x")
    ok = check_password_hash(stored, password) and row is not None
    if not ok:
        conn.execute("INSERT INTO login_attempts(ip, ts) VALUES(?, ?)", (ip, time.time()))
        return api_error("Usuario o contraseña incorrectos.", 401)
    conn.execute("DELETE FROM login_attempts WHERE ip=?", (ip,))
    session.clear()
    session.permanent = True
    session["uid"] = row["id"]
    session["user"] = row["username"]
    return jsonify({"user": row["username"], "csrf": csrf_token()})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"csrf": csrf_token()})


@app.post("/api/password")
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    current, new = str(data.get("current", "")), str(data.get("new", ""))
    row = db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    if not row or not check_password_hash(row["password_hash"], current):
        return api_error("La contraseña actual no es correcta.", 400)
    if len(new) < MIN_PASSWORD:
        return api_error(f"La nueva contraseña debe tener al menos {MIN_PASSWORD} caracteres.", 400)
    db().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), row["id"]))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- ajustes
@app.get("/api/settings")
@login_required
def settings_get():
    return jsonify(get_settings())


@app.put("/api/settings")
@login_required
def settings_put():
    data = request.get_json(silent=True) or {}
    updates = {}
    for key, limit in SETTING_LIMITS.items():
        if key in data:
            updates[key] = clean_text(data[key], key, limit, required=(key == "business_name"))
    if "default_valid_days" in data:
        try:
            days = int(data["default_valid_days"])
        except (TypeError, ValueError):
            raise ValidationError("Validez por defecto: ingresa un número.")
        if not 1 <= days <= 365:
            raise ValidationError("Validez por defecto: entre 1 y 365 días.")
        updates["default_valid_days"] = str(days)
    if "next_number" in data:
        try:
            nxt = int(data["next_number"])
        except (TypeError, ValueError):
            raise ValidationError("Próximo número: ingresa un número entero.")
        if not 1 <= nxt <= 9999999:
            raise ValidationError("Próximo número fuera de rango.")
        updates["next_number"] = str(nxt)
    for key, value in updates.items():
        db().execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))
    return jsonify(get_settings())


# ---------------------------------------------------------------- cotizaciones
def like_escape(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.get("/api/quotes")
@login_required
def quotes_list():
    where, params = [], []
    term = request.args.get("q", "").strip()[:80]
    if term:
        pat = f"%{like_escape(term)}%"
        where.append("(number LIKE ? ESCAPE '\\' OR client_name LIKE ? ESCAPE '\\' OR client_doc LIKE ? ESCAPE '\\')")
        params += [pat, pat, pat]
    status = request.args.get("status", "")
    if status in ("enviada", "aceptada", "rechazada"):
        where.append("status=?")
        params.append(status)
    sql = ("SELECT id, number, issue_date, client_name, client_doc, total, status, igv_mode, "
           "(SELECT d.id FROM documents d WHERE d.quote_id=quotes.id AND d.status='emitido' LIMIT 1) AS doc_id, "
           "(SELECT d.series||'-'||d.number FROM documents d WHERE d.quote_id=quotes.id AND d.status='emitido' LIMIT 1) AS doc_label "
           "FROM quotes"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT 500")
    rows = [dict(r) for r in db().execute(sql, params).fetchall()]

    month = date.today().strftime("%Y-%m")
    month_total = accepted_total = Decimal(0)
    pending = 0
    for r in db().execute("SELECT issue_date, status, total FROM quotes").fetchall():
        if r["status"] == "enviada":
            pending += 1
        if r["issue_date"].startswith(month):
            if r["status"] != "rechazada":
                month_total += Decimal(r["total"])
            if r["status"] == "aceptada":
                accepted_total += Decimal(r["total"])
    return jsonify({
        "quotes": rows,
        "stats": {"month_total": str(q2(month_total)), "accepted_total": str(q2(accepted_total)), "pending": pending},
    })


def fetch_quote(qid):
    return db().execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone()


def insert_quote(clean):
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='next_number'").fetchone()
        n = int(row["value"]) if row else 1
        while conn.execute("SELECT 1 FROM quotes WHERE number=?", (f"COT-{n:04d}",)).fetchone():
            n += 1
        number = f"COT-{n:04d}"
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('next_number', ?)", (str(n + 1),))
        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO quotes(number, issue_date, valid_days, client_name, client_doc, client_phone, items, "
            "discount_type, discount_value, igv_mode, subtotal, discount_amount, base, igv, total, conditions, "
            "status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, clean["issue_date"], clean["valid_days"], clean["client_name"], clean["client_doc"],
             clean["client_phone"], items_to_json(clean["items"]), clean["discount_type"],
             str(clean["discount_value"]), clean["igv_mode"], str(clean["subtotal"]),
             str(clean["discount_amount"]), str(clean["base"]), str(clean["igv"]), str(clean["total"]),
             clean["conditions"], clean["status"], ts, ts),
        )
        conn.execute("COMMIT")
        return cur.lastrowid
    except Exception:
        conn.execute("ROLLBACK")
        raise


@app.post("/api/quotes")
@login_required
def quotes_create():
    clean = clean_quote(request.get_json(silent=True))
    return jsonify(quote_out(fetch_quote(insert_quote(clean)))), 201


@app.get("/api/quotes/<int:qid>")
@login_required
def quotes_get(qid):
    row = fetch_quote(qid)
    if not row:
        return api_error("Cotización no encontrada.", 404)
    return jsonify(quote_out(row))


@app.put("/api/quotes/<int:qid>")
@login_required
def quotes_update(qid):
    if not fetch_quote(qid):
        return api_error("Cotización no encontrada.", 404)
    c = clean_quote(request.get_json(silent=True))
    db().execute(
        "UPDATE quotes SET issue_date=?, valid_days=?, client_name=?, client_doc=?, client_phone=?, items=?, "
        "discount_type=?, discount_value=?, igv_mode=?, subtotal=?, discount_amount=?, base=?, igv=?, total=?, "
        "conditions=?, status=?, updated_at=? WHERE id=?",
        (c["issue_date"], c["valid_days"], c["client_name"], c["client_doc"], c["client_phone"],
         items_to_json(c["items"]), c["discount_type"], str(c["discount_value"]), c["igv_mode"],
         str(c["subtotal"]), str(c["discount_amount"]), str(c["base"]), str(c["igv"]), str(c["total"]),
         c["conditions"], c["status"], now_iso(), qid),
    )
    return jsonify(quote_out(fetch_quote(qid)))


@app.patch("/api/quotes/<int:qid>/status")
@login_required
def quotes_status(qid):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("enviada", "aceptada", "rechazada"):
        return api_error("Estado no válido.", 400)
    if not fetch_quote(qid):
        return api_error("Cotización no encontrada.", 404)
    db().execute("UPDATE quotes SET status=?, updated_at=? WHERE id=?", (status, now_iso(), qid))
    return jsonify({"ok": True})


@app.delete("/api/quotes/<int:qid>")
@login_required
def quotes_delete(qid):
    if not fetch_quote(qid):
        return api_error("Cotización no encontrada.", 404)
    db().execute("DELETE FROM quotes WHERE id=?", (qid,))
    return jsonify({"ok": True})


@app.post("/api/quotes/<int:qid>/duplicate")
@login_required
def quotes_duplicate(qid):
    row = fetch_quote(qid)
    if not row:
        return api_error("Cotización no encontrada.", 404)
    src = quote_out(row)
    clean = clean_quote({**src, "issue_date": date.today().isoformat(), "status": "enviada"})
    return jsonify(quote_out(fetch_quote(insert_quote(clean)))), 201


@app.get("/api/quotes/<int:qid>/pdf")
@login_required
def quotes_pdf(qid):
    row = fetch_quote(qid)
    if not row:
        return api_error("Cotización no encontrada.", 404)
    pdf_bytes = pdfgen.build_pdf(quote_out(row), get_settings(), LOGO_PATH, PDF_OWNER_PASSWORD)
    safe = re.sub(r"[^A-Za-z0-9 _.-]", "", row["client_name"]).strip()[:40] or "cliente"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     download_name=f"{row['number']} - {safe}.pdf", as_attachment=False)



# ---------------------------------------------------------------- comprobantes (registro)
DOC_TYPES = {
    "boleta": {"label": "Boleta de venta", "prefix": "B", "default_series": "B001"},
    "factura": {"label": "Factura", "prefix": "F", "default_series": "F001"},
    "recibo": {"label": "Recibo por honorarios", "prefix": "", "default_series": "E001"},
}
BOLETA_DNI_THRESHOLD = Decimal("700")


def doc_out(row):
    d = quote_out(row)
    d["label"] = f"{row['series']}-{row['number']}"
    d["type_label"] = DOC_TYPES[row["doc_type"]]["label"]
    return d


def clean_doc_ref(data, doc_type):
    series = clean_text(data.get("series"), "Serie", 4, required=True).upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", series):
        raise ValidationError("Serie: 4 caracteres entre letras y números (ej. B001).")
    prefix = DOC_TYPES[doc_type]["prefix"]
    if prefix and not series.startswith(prefix):
        raise ValidationError(f"Serie: debe empezar con {prefix} (ej. {prefix}001).")
    number = str(data.get("number", "")).strip()
    if not re.fullmatch(r"[0-9]{1,8}", number) or int(number) < 1:
        raise ValidationError("Número: hasta 8 dígitos y mayor que 0.")
    return series, number.zfill(8)


@app.get("/api/documents/suggest")
@login_required
def documents_suggest():
    doc_type = request.args.get("doc_type", "")
    if doc_type not in DOC_TYPES:
        return api_error("Tipo de comprobante no válido.", 400)
    row = db().execute("SELECT series, number FROM documents WHERE doc_type=? ORDER BY id DESC LIMIT 1",
                       (doc_type,)).fetchone()
    if row:
        return jsonify({"series": row["series"], "number": str(int(row["number"]) + 1)})
    return jsonify({"series": DOC_TYPES[doc_type]["default_series"], "number": "1"})


@app.get("/api/documents")
@login_required
def documents_list():
    where, params = [], []
    term = request.args.get("q", "").strip()[:80]
    if term:
        pat = f"%{like_escape(term)}%"
        where.append("(number LIKE ? ESCAPE '\\' OR series LIKE ? ESCAPE '\\' OR client_name LIKE ? ESCAPE '\\' "
                     "OR client_doc LIKE ? ESCAPE '\\')")
        params += [pat, pat, pat, pat]
    doc_type = request.args.get("type", "")
    if doc_type in DOC_TYPES:
        where.append("doc_type=?")
        params.append(doc_type)
    status = request.args.get("status", "")
    if status in ("emitido", "anulado"):
        where.append("status=?")
        params.append(status)
    sql = ("SELECT id, quote_id, doc_type, series, number, issue_date, client_name, client_doc, total, status "
           "FROM documents" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT 500")
    rows = []
    for r in db().execute(sql, params).fetchall():
        d = dict(r)
        d["label"] = f"{r['series']}-{r['number']}"
        d["type_label"] = DOC_TYPES[r["doc_type"]]["label"]
        rows.append(d)
    month = date.today().strftime("%Y-%m")
    month_total, month_count = Decimal(0), 0
    for r in db().execute("SELECT issue_date, total FROM documents WHERE status='emitido'").fetchall():
        if r["issue_date"].startswith(month):
            month_total += Decimal(r["total"])
            month_count += 1
    return jsonify({"documents": rows, "stats": {"month_total": str(q2(month_total)), "month_count": month_count}})


@app.post("/api/documents")
@login_required
def documents_create():
    data = request.get_json(silent=True) or {}
    doc_type = data.get("doc_type")
    if doc_type not in DOC_TYPES:
        raise ValidationError("Tipo de comprobante no válido.")
    try:
        qid = int(data.get("quote_id"))
    except (TypeError, ValueError):
        raise ValidationError("Selecciona una cotización.")
    quote = fetch_quote(qid)
    if not quote:
        return api_error("Cotización no encontrada.", 404)
    series, number = clean_doc_ref(data, doc_type)
    issue_date = str(data.get("issue_date") or date.today().isoformat())
    try:
        date.fromisoformat(issue_date)
    except ValueError:
        raise ValidationError("Fecha no válida.")

    doc_no = quote["client_doc"]
    total = Decimal(quote["total"])
    if doc_type == "factura" and len(doc_no) != 11:
        raise ValidationError("La factura requiere el RUC (11 dígitos) del cliente. Edita la cotización.")
    if doc_type == "boleta" and total >= BOLETA_DNI_THRESHOLD and not doc_no:
        raise ValidationError("Las boletas desde S/ 700 requieren DNI o RUC del cliente. Edita la cotización.")
    if total <= 0:
        raise ValidationError("El total de la cotización debe ser mayor que 0.")

    conn = db()
    prev = conn.execute("SELECT series, number FROM documents WHERE quote_id=? AND status='emitido'", (qid,)).fetchone()
    if prev:
        return api_error(f"Esta cotización ya tiene el comprobante {prev['series']}-{prev['number']}. "
                         "Anúlalo primero si necesitas registrar otro.", 409)
    ts = now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "INSERT INTO documents(quote_id, doc_type, series, number, issue_date, client_name, client_doc, "
            "client_phone, items, discount_type, discount_value, igv_mode, subtotal, discount_amount, base, igv, "
            "total, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, doc_type, series, number, issue_date, quote["client_name"], quote["client_doc"],
             quote["client_phone"], quote["items"], quote["discount_type"], quote["discount_value"],
             quote["igv_mode"], quote["subtotal"], quote["discount_amount"], quote["base"], quote["igv"],
             quote["total"], "emitido", ts, ts))
        conn.execute("UPDATE quotes SET status='aceptada', updated_at=? WHERE id=?", (ts, qid))
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        return api_error(f"Ya registraste {series}-{number} como {DOC_TYPES[doc_type]['label'].lower()}.", 409)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    row = conn.execute("SELECT * FROM documents WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(doc_out(row)), 201


@app.get("/api/documents/<int:did>")
@login_required
def documents_get(did):
    row = db().execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if not row:
        return api_error("Comprobante no encontrado.", 404)
    return jsonify(doc_out(row))


@app.patch("/api/documents/<int:did>/void")
@login_required
def documents_void(did):
    row = db().execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
    if not row:
        return api_error("Comprobante no encontrado.", 404)
    db().execute("UPDATE documents SET status='anulado', updated_at=? WHERE id=?", (now_iso(), did))
    return jsonify({"ok": True})


def csv_safe(value):
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@app.get("/api/documents/export.csv")
@login_required
def documents_export():
    import csv
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Fecha", "Tipo", "Serie", "Número", "Cliente", "DNI/RUC", "Base imponible", "IGV", "Total", "Estado"])
    for r in db().execute("SELECT * FROM documents ORDER BY issue_date, id").fetchall():
        w.writerow([r["issue_date"], DOC_TYPES[r["doc_type"]]["label"], r["series"], r["number"],
                    csv_safe(r["client_name"]), r["client_doc"], r["base"], r["igv"], r["total"], r["status"]])
    payload = ("\ufeff" + out.getvalue()).encode("utf-8")
    return send_file(io.BytesIO(payload), mimetype="text/csv", as_attachment=True,
                     download_name=f"comprobantes-{date.today().isoformat()}.csv")


@app.get("/api/backup")
@login_required
def backup():
    fd, tmp = tempfile.mkstemp(suffix=".db", dir=DATA_DIR)
    os.close(fd)
    try:
        src, dst = connect(), sqlite3.connect(tmp)
        src.backup(dst)
        dst.close()
        src.close()
        with open(tmp, "rb") as fh:
            payload = fh.read()
    finally:
        os.remove(tmp)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return send_file(io.BytesIO(payload), mimetype="application/octet-stream",
                     download_name=f"impulso-respaldo-{stamp}.db", as_attachment=True)


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
