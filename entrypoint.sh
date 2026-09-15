#!/bin/sh
set -e

echo "[entrypoint] esperando postgres en ${DB_HOST}:${DB_PORT} ..."
until pg_isready -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" >/dev/null 2>&1; do
  sleep 2
done
echo "[entrypoint] postgres listo."

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Crea el usuario administrador la primera vez.
# Si ya existe, no hace nada (idempotente).
python manage.py crear_admin

exec "$@"
