#!/bin/sh
#
# Instalador de Seguimiento de Pendientes.
#
# Verifica requisitos, prepara el .env con claves generadas y levanta
# el sistema. Es idempotente: se puede volver a ejecutar sin romper nada.
#
#   ./instalar.sh
#
set -e

verde='\033[0;32m'; rojo='\033[0;31m'; ambar='\033[0;33m'; sin='\033[0m'
ok()    { printf "${verde}  OK${sin}  %s\n" "$1"; }
falla() { printf "${rojo}  ERROR${sin}  %s\n" "$1"; }
aviso() { printf "${ambar}  AVISO${sin}  %s\n" "$1"; }

echo
echo "  Seguimiento de Pendientes — instalación"
echo "  ---------------------------------------"
echo

# ---------------------------------------------------------------
# 1. Requisitos
# ---------------------------------------------------------------
echo "  Verificando requisitos"

if ! command -v docker >/dev/null 2>&1; then
    falla "Docker no está instalado."
    echo "         Instalación: https://docs.docker.com/engine/install/"
    exit 1
fi
ok "Docker $(docker --version | sed 's/Docker version //;s/,.*//')"

if ! docker compose version >/dev/null 2>&1; then
    falla "Docker Compose v2 no está disponible."
    echo "         Se necesita el plugin 'docker compose', no 'docker-compose'."
    exit 1
fi
ok "Compose $(docker compose version --short 2>/dev/null || echo v2)"

if ! docker info >/dev/null 2>&1; then
    falla "El servicio de Docker no está corriendo."
    echo "         Linux:  sudo systemctl start docker"
    echo "         macOS:  abrir Docker Desktop"
    exit 1
fi
ok "Servicio de Docker activo"

# ---------------------------------------------------------------
# 2. Configuración
# ---------------------------------------------------------------
echo
echo "  Configurando el entorno"

if [ -f .env ]; then
    ok ".env ya existe, se conserva"
else
    cp .env.example .env

    # Claves aleatorias distintas en cada instalación. Sin esto, todas
    # las instalaciones comparten la misma clave de sesión.
    SECRETO=$(docker run --rm python:3.12-slim \
        python -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null)
    CLAVE_BD=$(docker run --rm python:3.12-slim \
        python -c "import secrets; print(secrets.token_urlsafe(18))" 2>/dev/null)

    CLAVE_ADMIN=$(docker run --rm python:3.12-slim \
        python -c "import secrets; print(secrets.token_urlsafe(12))" 2>/dev/null)

    if [ -n "$SECRETO" ]; then
        # sed -i.bak funciona igual en BSD (macOS) y GNU (Linux).
        sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${SECRETO}|" .env
        sed -i.bak "s|^DB_PASSWORD=.*|DB_PASSWORD=${CLAVE_BD}|" .env
        sed -i.bak "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${CLAVE_ADMIN}|" .env
        rm -f .env.bak
        ok ".env creado con claves generadas"
    else
        aviso ".env creado, pero SECRET_KEY quedó sin generar"
        echo "         Editalo a mano antes de usarlo en producción."
    fi

    chmod 600 .env
fi

# La IP del servidor debe estar en ALLOWED_HOSTS y CSRF_TRUSTED_ORIGINS,
# o el sistema abre pero ningún formulario funciona desde la red.
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$IP" ] && IP=$(ipconfig getifaddr en0 2>/dev/null)

if [ -n "$IP" ] && ! grep -q "$IP" .env; then
    PUERTO=$(grep '^APP_PORT=' .env | cut -d= -f2)
    PUERTO=${PUERTO:-8000}

    sed -i.bak "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=localhost,127.0.0.1,${IP}|" .env
    sed -i.bak "s|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=http://localhost:${PUERTO},http://${IP}:${PUERTO}|" .env
    rm -f .env.bak
    ok "Configurado para la red: ${IP}"
fi

# ---------------------------------------------------------------
# 3. Puertos
# ---------------------------------------------------------------
echo
echo "  Verificando puertos"

APP_PORT=$(grep '^APP_PORT=' .env | cut -d= -f2); APP_PORT=${APP_PORT:-8000}
DB_PORT=$(grep '^DB_PORT_HOST=' .env | cut -d= -f2); DB_PORT=${DB_PORT:-55432}

for p in "$APP_PORT" "$DB_PORT"; do
    if lsof -i ":$p" >/dev/null 2>&1; then
        aviso "El puerto $p está ocupado"
        echo "         Cambialo en .env (APP_PORT / DB_PORT_HOST) y volvé a ejecutar."
    else
        ok "Puerto $p libre"
    fi
done

# ---------------------------------------------------------------
# 4. Arranque
# ---------------------------------------------------------------
echo
echo "  Construyendo y levantando (puede tardar unos minutos)"
echo

docker compose up -d --build

echo
echo "  Esperando a que el sistema responda"

# Hasta 60 intentos de 2 segundos = 2 minutos.
n=0
while [ $n -lt 60 ]; do
    if curl -sf -o /dev/null "http://localhost:${APP_PORT}/login/" 2>/dev/null; then
        break
    fi
    n=$((n + 1))
    sleep 2
done

echo
if [ $n -ge 60 ]; then
    falla "El sistema no respondió en 2 minutos."
    echo "         Revisá el detalle con:  docker compose logs web"
    exit 1
fi

ADMIN=$(grep '^ADMIN_USER=' .env | cut -d= -f2)
CLAVE=$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2)

ok "Sistema en funcionamiento"
echo
echo "  ---------------------------------------------------------"
echo "    Acceso:   http://localhost:${APP_PORT}"
[ -n "$IP" ] && echo "    En red:   http://${IP}:${APP_PORT}"
echo "    Admin:    http://localhost:${APP_PORT}/admin/"
echo
echo "    Usuario:  ${ADMIN}"
echo "    Clave:    ${CLAVE}"
echo "  ---------------------------------------------------------"
echo
aviso "Cambiá la contraseña antes de entregar el sistema:"
echo "         docker compose exec web python manage.py changepassword ${ADMIN}"
echo
echo "  Siguiente paso: crear una cuenta por cada persona del equipo"
echo "  desde http://localhost:${APP_PORT}/admin/ (ver DESPLIEGUE.md, sección 6)"
echo
