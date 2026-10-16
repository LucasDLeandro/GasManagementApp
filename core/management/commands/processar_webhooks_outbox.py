import logging
from django.core.management.base import BaseCommand
from core.models import WebhookDeliveryLog
from core.webhooks import processar_envio_webhook_log

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Processa pendências e retentativas do Transactional Outbox de Webhooks (D7)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-tentativas',
            type=int,
            default=5,
            help='Número máximo de tentativas antes de considerar o webhook falho definitivamente (default: 5).'
        )

    def handle(self, *args, **options):
        max_tentativas = options['max_tentativas']
        pendentes = WebhookDeliveryLog.unscoped.filter(
            status__in=['PENDENTE', 'FALHA'],
            tentativas__lt=max_tentativas
        ).order_by('enviado_em')

        total = pendentes.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("[Webhook Outbox] Nenhuma pendência encontrada."))
            return

        self.stdout.write(f"[Webhook Outbox] Iniciando processamento de {total} webhook(s)...")

        sucessos = 0
        falhas = 0

        for log in pendentes:
            res = processar_envio_webhook_log(log.id)
            if res and res.sucesso:
                sucessos += 1
            else:
                falhas += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"[Webhook Outbox] Concluído: {sucessos} entregue(s) com sucesso, {falhas} com erro/aguardando retentativa."
            )
        )
