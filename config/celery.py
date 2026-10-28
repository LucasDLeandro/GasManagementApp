import os
import logging

logger = logging.getLogger(__name__)

# Define o módulo padrão de configurações do Django para o Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

try:
    from celery import Celery
    from celery.schedules import crontab

    app = Celery('gasmanagementapp')

    # Lê as configurações do Django com o prefixo CELERY_
    app.config_from_object('django.conf:settings', namespace='CELERY')

    # Descobre automaticamente tasks em todos os apps instalados
    app.autodiscover_tasks()

    # Agendamento periódico de rotinas de inteligência (Celery Beat)
    app.conf.beat_schedule = {
        'analisar-risco-churn-todas-madrugadas': {
            'task': 'vendas.tasks.analisar_risco_churn_task',
            'schedule': crontab(hour=3, minute=0),
        },
    }

    @app.task(bind=True, ignore_result=True)
    def debug_task(self):
        print(f'Request: {self.request!r}')

except ImportError:
    logger.warning("Celery não está instalado no ambiente. Filas assíncronas rodarão desativadas localmente.")
    app = None

