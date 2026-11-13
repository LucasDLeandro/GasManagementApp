"""
Comando para aplicar o plano de contas padrão do Financeiro nas empresas com módulo ativo e plano vazio.
"""
from django.core.management.base import BaseCommand

from core.models import Tenant
from financeiro.models import PlanoContas
from financeiro.seeds import aplicar_seed_tenants_plano_vazio


class Command(BaseCommand):
    help = "Aplica o seed padrão do Financeiro apenas nas empresas com módulo ativo e plano de contas vazio."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Lista as empresas elegíveis sem gravar alterações no banco.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        elegiveis = [
            t
            for t in Tenant.objects.filter(modulo_financeiro_ativo=True).order_by("id")
            if not PlanoContas.unscoped.filter(tenant=t).exists()
        ]

        if not elegiveis:
            self.stdout.write("Nenhuma empresa com módulo financeiro ativo e plano de contas vazio.")
            return

        if dry_run:
            self.stdout.write(f"[DRY-RUN] {len(elegiveis)} empresa(s) elegível(is):")
            for tenant in elegiveis:
                self.stdout.write(f" - {tenant.id}: {tenant.nome}")
            return

        aplicados = aplicar_seed_tenants_plano_vazio()
        self.stdout.write(f"Seed financeiro aplicado em {len(aplicados)} empresa(s): {aplicados}")

