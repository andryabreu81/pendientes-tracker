from django import forms
from django.core.exceptions import ValidationError

from .models import Recordatorio, Reunion, Tarea, Ticket

# Altura minima 42px: cumple el minimo de area tactil en pantallas chicas.
BASE = (
    "w-full min-h-[42px] rounded-lg border border-slate-300 px-3 py-2 text-sm "
    "transition-colors duration-150 placeholder:text-slate-400 "
    "focus:border-brand-700 disabled:bg-slate-50 disabled:text-slate-500"
)


class TicketForm(forms.ModelForm):
    """Formulario de alta y edicion. Los 8 campos que pidio el negocio."""

    # No es obligatorio: en el alta lo genera el sistema y el campo ni
    # siquiera se muestra. Solo aparece al editar.
    codigo = forms.CharField(
        label="Número de requerimiento",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": BASE + " font-mono uppercase",
                "placeholder": "PRY-001",
            }
        ),
        help_text="Formato PRY-000, REQ-000 o INC-000, según el tipo.",
    )

    class Meta:
        model = Ticket
        fields = [
            "codigo",
            "nombre",
            "categoria",
            "fecha_solicitada",
            "fecha_fin",
            "funcional_solicitante",
            "descripcion",
            "avance",
            "asignado",
            "observacion",
            "estatus",
        ]
        widgets = {
            "nombre": forms.TextInput(
                attrs={"class": BASE, "placeholder": "Título del proyecto o incidencia"}
            ),
            "categoria": forms.Select(attrs={"class": BASE}),
            "fecha_solicitada": forms.DateInput(
                attrs={"class": BASE, "type": "date"}, format="%Y-%m-%d"
            ),
            "fecha_fin": forms.DateInput(
                attrs={"class": BASE, "type": "date"}, format="%Y-%m-%d"
            ),
            "funcional_solicitante": forms.TextInput(
                attrs={"class": BASE, "placeholder": "Área o persona que solicita"}
            ),
            "descripcion": forms.Textarea(
                attrs={"class": BASE, "rows": 4, "placeholder": "Detalle técnico o funcional"}
            ),
            "avance": forms.NumberInput(
                attrs={"class": BASE + " tabular", "min": 0, "max": 100, "step": 5}
            ),
            "asignado": forms.TextInput(
                attrs={"class": BASE, "placeholder": "Quién lo atiende"}
            ),
            "observacion": forms.Textarea(
                attrs={"class": BASE, "rows": 3, "placeholder": "Comentarios o bloqueos"}
            ),
            "estatus": forms.Select(choices=Ticket.ESTATUS, attrs={"class": BASE}),
        }

    def clean_avance(self):
        avance = self.cleaned_data["avance"]
        if not 0 <= avance <= 100:
            raise forms.ValidationError("El avance debe estar entre 0 y 100.")
        return avance

    def validate_unique(self):
        """
        Deja la unicidad del código en manos de clean_codigo().

        La vista de edición construye la instancia con Ticket(pk=...) para
        no pisar el objeto real antes de comparar los cambios. Esa
        instancia nace en memoria, así que Django la considera "en alta"
        (_state.adding = True) y su validate_unique() no la excluye de la
        búsqueda: el registro se encuentra a sí mismo y reporta un
        duplicado que no existe.

        clean_codigo() sí excluye el pk correcto, y corre siempre.
        """
        excluidos = self._get_validation_exclusions()
        excluidos.add("codigo")

        try:
            self.instance.validate_unique(exclude=excluidos)
        except ValidationError as e:
            self._update_errors(e)

    def clean_codigo(self):
        """
        Valida el formato y la unicidad del código.

        El formato se exige para que Ticket.siguiente_codigo() siga
        encontrando el correlativo: si alguien guarda "PRY-A", el próximo
        alta de esa categoría no sabría desde qué número seguir.
        """
        codigo = (self.cleaned_data.get("codigo") or "").strip().upper()

        # Vacío es válido: en el alta lo genera el sistema.
        if not codigo:
            return ""

        if not Ticket.PATRON_CODIGO.match(codigo):
            raise forms.ValidationError(
                "Formato inválido. Usá PRY-000, REQ-000 o INC-000 "
                "(tres dígitos como mínimo)."
            )

        tomado = Ticket.objects.filter(codigo=codigo)
        if self.instance.pk:
            tomado = tomado.exclude(pk=self.instance.pk)

        if tomado.exists():
            raise forms.ValidationError(
                f"El código {codigo} ya lo tiene otro registro."
            )

        return codigo

    def clean(self):
        """Coherencia entre campos: prefijo vs tipo, y orden de las fechas."""
        datos = super().clean()

        codigo, categoria = datos.get("codigo"), datos.get("categoria")
        if codigo and categoria:
            esperado = Ticket.PREFIJOS.get(categoria)
            if esperado and not codigo.startswith(f"{esperado}-"):
                self.add_error(
                    "codigo",
                    f"Un {dict(Ticket.CATEGORIAS)[categoria].lower()} debe "
                    f"llevar el prefijo {esperado}-.",
                )

        solicitada, fin = datos.get("fecha_solicitada"), datos.get("fecha_fin")
        if solicitada and fin and fin < solicitada:
            self.add_error(
                "fecha_fin",
                "La fecha final no puede ser anterior a la fecha solicitada.",
            )

        return datos


class ImportForm(forms.Form):
    archivo = forms.FileField(
        label="Archivo de pendientes",
        help_text="Formato .xlsx o .docx con los bloques de Proyectos, Requerimientos e Incidencias.",
        widget=forms.ClearableFileInput(
            attrs={
                "class": (
                    "block w-full cursor-pointer rounded-lg border border-dashed border-slate-300 "
                    "bg-slate-50 p-3 text-sm text-slate-600 transition-colors duration-150 "
                    "hover:border-brand-600 hover:bg-brand-50 "
                    "file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-brand-800 "
                    "file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white "
                    "hover:file:bg-brand-900"
                ),
                "accept": ".xlsx,.xls,.docx",
            }
        ),
    )

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        if not archivo.name.lower().endswith((".xlsx", ".xls", ".docx")):
            raise forms.ValidationError("Solo se aceptan archivos .xlsx, .xls o .docx.")
        if archivo.size > 25 * 1024 * 1024:
            raise forms.ValidationError("El archivo supera los 25 MB.")
        return archivo


class TareaForm(forms.ModelForm):
    """Alta y edición de una tarea dentro de un registro existente."""

    class Meta:
        model = Tarea
        fields = [
            "descripcion",
            "responsable",
            "estado",
            "avance",
            "prioridad",
            "fecha_inicio",
            "fecha_limite",
            "observacion",
        ]
        widgets = {
            "descripcion": forms.TextInput(
                attrs={"class": BASE, "placeholder": "Qué hay que hacer"}
            ),
            "responsable": forms.TextInput(
                attrs={"class": BASE, "placeholder": "Quién la atiende"}
            ),
            "estado": forms.Select(attrs={"class": BASE}),
            "avance": forms.NumberInput(
                attrs={"class": BASE + " tabular", "min": 0, "max": 100, "step": 5}
            ),
            "prioridad": forms.Select(attrs={"class": BASE}),
            "fecha_inicio": forms.DateInput(
                attrs={"class": BASE, "type": "date"}, format="%Y-%m-%d"
            ),
            "fecha_limite": forms.DateInput(
                attrs={"class": BASE, "type": "date"}, format="%Y-%m-%d"
            ),
            "observacion": forms.Textarea(
                attrs={"class": BASE, "rows": 2, "placeholder": "Comentarios o bloqueos"}
            ),
        }

    def clean(self):
        datos = super().clean()
        inicio, limite = datos.get("fecha_inicio"), datos.get("fecha_limite")

        if inicio and limite and limite < inicio:
            self.add_error(
                "fecha_limite",
                "La fecha límite no puede ser anterior a la de inicio.",
            )

        return datos


class RecordatorioForm(forms.ModelForm):
    """Alerta de seguimiento sobre un registro o una tarea."""

    class Meta:
        model = Recordatorio
        fields = ["titulo", "fecha", "nota"]
        widgets = {
            "titulo": forms.TextInput(
                attrs={"class": BASE, "placeholder": "Qué hay que revisar"}
            ),
            "fecha": forms.DateInput(
                attrs={"class": BASE, "type": "date"}, format="%Y-%m-%d"
            ),
            "nota": forms.Textarea(
                attrs={"class": BASE, "rows": 3, "placeholder": "Detalle del seguimiento"}
            ),
        }


class ReunionForm(forms.ModelForm):
    """Reunión pautada sobre un registro o una tarea."""

    class Meta:
        model = Reunion
        fields = [
            "titulo",
            "fecha_hora",
            "duracion_minutos",
            "lugar",
            "enlace",
            "participantes",
            "notas",
        ]
        widgets = {
            "titulo": forms.TextInput(
                attrs={"class": BASE, "placeholder": "Motivo de la reunión"}
            ),
            # datetime-local es el control nativo del navegador: no hace
            # falta traer una libreria de calendario solo para esto.
            "fecha_hora": forms.DateTimeInput(
                attrs={"class": BASE, "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "duracion_minutos": forms.NumberInput(
                attrs={"class": BASE + " tabular", "min": 5, "max": 600, "step": 5}
            ),
            "lugar": forms.TextInput(
                attrs={"class": BASE, "placeholder": "Sala 3, o vacío si es virtual"}
            ),
            "enlace": forms.URLInput(
                attrs={"class": BASE, "placeholder": "https://teams.microsoft.com/..."}
            ),
            "participantes": forms.Textarea(
                attrs={
                    "class": BASE,
                    "rows": 3,
                    "placeholder": "Un nombre o correo por línea",
                }
            ),
            "notas": forms.Textarea(
                attrs={"class": BASE, "rows": 3, "placeholder": "Agenda de la reunión"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sin esto el control datetime-local llega vacio al editar: el
        # navegador solo entiende el formato ISO con "T" en el medio.
        self.fields["fecha_hora"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]

    def clean_duracion_minutos(self):
        minutos = self.cleaned_data["duracion_minutos"]
        if not 5 <= minutos <= 600:
            raise forms.ValidationError("La duración debe estar entre 5 y 600 minutos.")
        return minutos
