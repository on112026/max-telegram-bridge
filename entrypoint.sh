#!/bin/sh
# entrypoint.sh — готовит окружение и стартует supervisord.
# Главное: генерирует пароль x11vnc из env VNC_PASSWORD,
# чтобы VNC-доступ был защищён.

set -eu

mkdir -p /var/log/supervisor /data

# --- VNC-пароль ---
if [ -z "${VNC_PASSWORD:-}" ]; then
    echo "[entrypoint] WARNING: VNC_PASSWORD is not set — using insecure default 'changeme'." >&2
    VNC_PASSWORD="changeme"
fi
# x11vnc сам хранит пароль в файле, зашифрованном DES.
# В openbox-headless окружении (Xvfb) нельзя просто прочитать stdin,
# поэтому используем -storepasswd с прямым аргументом (через envsub).
x11vnc -storepasswd "$VNC_PASSWORD" /etc/x11vnc.passwd
chmod 600 /etc/x11vnc.passwd
echo "[entrypoint] VNC password file generated."

# --- Передача WATCHER_HEADFUL_DEFAULT (опционально) ---
# если переменная выставлена, watcher стартует сразу в headful (на xvfb-экране :99)

# Если в $1 пришла команда — выполняем её; иначе — supervisord.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi
exec supervisord -c /etc/supervisor/conf.d/bridge.conf