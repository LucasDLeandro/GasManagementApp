from decimal import Decimal
from django.db import migrations


def seed_alcadas_e_parametros(apps, schema_editor):
    Tenant = apps.get_model('core', 'Tenant')
    ParametroFinanceiroTenant = apps.get_model('financeiro', 'ParametroFinanceiroTenant')
    AlcadaAprovacao = apps.get_model('financeiro', 'AlcadaAprovacao')

    for tenant in Tenant.objects.all():
        # 1. Parâmetro financeiro padrão
        ParametroFinanceiroTenant.objects.get_or_create(
            tenant=tenant,
            defaults={
                'aliquota_efetiva_deducoes': Decimal('0.0565'),
                'percentual_multa_padrao': Decimal('0.0200'),
                'percentual_juros_diario_padrao': Decimal('0.000333'),
                'valor_primeira_alcada': Decimal('1000.00'),
            }
        )

        # 2. Alçadas de aprovação de Contas a Pagar
        if not AlcadaAprovacao.objects.filter(tenant=tenant).exists():
            AlcadaAprovacao.objects.create(
                tenant=tenant,
                tipo='PAGAR',
                valor_ate=Decimal('1000.00'),
                grupo_aprovador='DIRETORIA',
                ordem=1,
                ativo=True
            )


def reverter_seed(apps, schema_editor):
    # Data migration idempotente e reversível: não destrói registros em produção
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0004_sprint9b_titulos_baixas_aprovacoes'),
    ]

    operations = [
        migrations.RunPython(seed_alcadas_e_parametros, reverter_seed),
    ]
