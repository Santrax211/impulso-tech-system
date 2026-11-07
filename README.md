# Impulso Tech · Cotizador

Flask + SQLite. Login con contraseña, historial, PDF cifrado (AES-256) sin permiso de edición/copia.

## Ejecutar en tu PC
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
python crear_usuario.py         # crea usuario y contraseña (mín. 10 caracteres)
python app.py                   # abre http://127.0.0.1:5000
```
Luego entra a **Ajustes** y completa teléfono, correo, RUC y datos de pago.

## Variables de entorno
| Variable | Uso |
|---|---|
| `IMPULSO_DATA_DIR` | Carpeta de la base de datos y la clave secreta (por defecto `./data`). Debe ser **persistente**. |
| `IMPULSO_SECRET` | Clave secreta de sesión (opcional; si falta se genera en `data/secret.key`). |
| `IMPULSO_HTTPS=1` | Obligatorio en producción con HTTPS (cookie `Secure` + HSTS). |
| `IMPULSO_PROXY=1` | Actívalo si hay proxy inverso (Render, Nginx) para leer la IP real en el límite de intentos. |
| `IMPULSO_USER` / `IMPULSO_PASSWORD` | Crean el usuario al arrancar **solo si no existe ninguno** (útil si el hosting no da terminal). |

## Despliegue
- **VPS (Nginx + gunicorn)**: `gunicorn app:app --workers 1 --threads 4`. HTTPS con Let's Encrypt.
- **PythonAnywhere**: sube la carpeta, crea el virtualenv, apunta el WSGI a `app:app`, define las variables arriba.
- **Render/Railway**: usa el `Procfile`. Necesita **disco persistente** montado en `IMPULSO_DATA_DIR`; sin él, la base se borra en cada redeploy.
- Mantén `--workers 1` (SQLite + límite de intentos en un solo proceso).

## Seguridad incluida
- Hash de contraseña (scrypt/werkzeug), sesión HttpOnly + SameSite, expira a las 12 h.
- Bloqueo de 15 min tras 5 intentos fallidos por IP.
- Token CSRF en toda operación de escritura.
- Cabeceras CSP, X-Frame-Options, nosniff.
- Consultas parametrizadas; la interfaz nunca inserta datos del usuario como HTML.
- PDF: AES-256, sin contraseña de apertura, bloquea editar, copiar texto y anotar; permite imprimir.
  Límite conocido: son permisos que respetan los lectores estándar; una herramienta dedicada puede saltárselos.

## Respaldos
Ajustes → **Descargar respaldo** (copia completa de la base). Hazlo cada semana.
