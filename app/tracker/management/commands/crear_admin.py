import os
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea el usuario administrador inicial si todavia no existe."

    def handle(self, *args, **options):
        User = get_user_model()
        usuario = os.getenv("ADMIN_USER", "admin")

        if User.objects.filter(username=usuario).exists():
            self.stdout.write(f"El usuario '{usuario}' ya existe, no se toca.")
            return

        clave = os.getenv("ADMIN_PASSWORD", "")

        # Sin valor por defecto: un sistema que arranca con una clave
        # conocida queda abierto sin que nadie se entere.
        if not clave:
            self.stderr.write(
                self.style.ERROR(
                    "Falta ADMIN_PASSWORD en el archivo .env.\n"
                    "El usuario administrador no se creo."
                )
            )
            sys.exit(1)

        if clave.startswith("CAMBIAR"):
            self.stderr.write(
                self.style.ERROR(
                    "ADMIN_PASSWORD todavia tiene el valor de ejemplo.\n"
                    "Editalo en .env antes de continuar."
                )
            )
            sys.exit(1)

        User.objects.create_superuser(
            username=usuario,
            email=os.getenv("ADMIN_EMAIL", "admin@local"),
            password=clave,
        )
        self.stdout.write(self.style.SUCCESS(f"Usuario '{usuario}' creado."))
