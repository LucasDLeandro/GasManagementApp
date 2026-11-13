from django.apps import apps
from django.core.management.base import BaseCommand


MODELOS_SISTEMA = {
    "admin.logentry",
    "auth.permission",
    "contenttypes.contenttype",
    "sessions.session",
}


class Command(BaseCommand):
    help = "Conta registros de todos os modelos concretos do banco (usando manager sem escopo de tenant)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--incluir-sistema",
            action="store_true",
            help="Inclui tabelas internas do Django (contenttypes, auth.permission, admin.logentry, sessions).",
        )

    def handle(self, *args, **options):
        incluir_sistema = options["incluir_sistema"]
        modelos = sorted(apps.get_models(), key=lambda m: m._meta.label_lower)
        total = 0
        for model in modelos:
            if model._meta.proxy or not model._meta.managed:
                continue
            label = model._meta.label_lower
            if not incluir_sistema and label in MODELOS_SISTEMA:
                continue
            manager = getattr(model, "unscoped", model._base_manager)
            qtd = manager.count()
            total += qtd
            self.stdout.write(f"{model._meta.label}: {qtd}")
        self.stdout.write(f"TOTAL: {total}")

