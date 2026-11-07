"""Crea o actualiza el usuario de acceso.  Uso:  python crear_usuario.py"""
import getpass
import sys

import app as cotizador


def main():
    username = input("Usuario: ").strip()
    if not username:
        sys.exit("El usuario no puede estar vacío.")
    pwd = getpass.getpass(f"Contraseña (mínimo {cotizador.MIN_PASSWORD} caracteres): ")
    if len(pwd) < cotizador.MIN_PASSWORD:
        sys.exit("Contraseña demasiado corta.")
    if pwd != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden.")
    conn = cotizador.connect()
    cotizador.set_user(conn, username, pwd)
    conn.close()
    print("Usuario guardado.")


if __name__ == "__main__":
    main()
