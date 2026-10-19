from django.core.management.base import BaseCommand
from core.models import Tenant
from logistica.services.manutencao import processar_alertas_manutencao


class Command(BaseCommand):
    help = "Varre os planos preventivos de manutenção e gera alertas e Ordens de Serviço (OS) preventivas de forma idempotente."

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            default=None,
            help="Filtrar por ID ou nome do Tenant."
        )

    def handle(self, *args, **options):
        tenant_arg = options.get('tenant')
        tenant_obj = None

        if tenant_arg:
            if tenant_arg.isdigit():
                tenant_obj = Tenant.objects.filter(pk=int(tenant_arg)).first()
            else:
                tenant_obj = Tenant.objects.filter(nome_fantasia__icontains=tenant_arg).first() or Tenant.objects.filter(razao_social__icontains=tenant_arg).first()

            if not tenant_obj:
                self.stdout.write(self.style.ERROR(f"Tenant '{tenant_arg}' não encontrado."))
                return

        self.stdout.write("Iniciando varredura de planos de manutenção preventiva...")
        resultado = processar_alertas_manutencao(tenant=tenant_obj)

        self.stdout.write(
            self.style.SUCCESS(
                f"Varredura concluída!\n"
                f"- Planos analisados: {resultado['planos_analisados']}\n"
                f"- Novas Ordens de Serviço (OS) geradas: {resultado['total_ordens_criadas']}\n"
                f"- Alertas em antecedência / pendências: {resultado['total_alertas']}"
            )
        )

        for os_info in resultado['ordens_criadas']:
            self.stdout.write(
                self.style.NOTICE(
                    f"  [+] OS Criada: {os_info['numero']} | Veículo: {os_info['veiculo']} | Plano: {os_info['plano']} ({os_info['motivo']})"
                )
            )

        for alerta in resultado['alertas_gerados']:
            self.stdout.write(
                f"  [*] Alerta: Veículo {alerta['veiculo']} | Plano: {alerta['plano']} -> {alerta['status']} ({alerta['motivo']})"
            )
