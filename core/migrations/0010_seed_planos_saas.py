import datetime
from decimal import Decimal
from django.db import migrations


def seed_planos_e_tenants_ativos(apps, schema_editor):
    PlanoSaaS = apps.get_model('core', 'PlanoSaaS')
    Tenant = apps.get_model('core', 'Tenant')

    planos_data = [
        {
            'nome': 'Starter',
            'preco_base': Decimal('499.00'),
            'limite_usuarios': 5,
            'limite_cilindros': 500,
            'modulo_patrimonio_ativo': True,
            'modulo_comercial_ativo': True,
            'modulo_vendas_ativo': True,
            'modulo_envase_ativo': False,
            'modulo_logistica_ativo': True,
            'modulo_fiscal_ativo': False,
            'modulo_b2b_ativo': False,
            'modulo_financeiro_ativo': True,
            'modulo_analytics_ativo': False,
        },
        {
            'nome': 'Profissional',
            'preco_base': Decimal('999.00'),
            'limite_usuarios': 15,
            'limite_cilindros': 2000,
            'modulo_patrimonio_ativo': True,
            'modulo_comercial_ativo': True,
            'modulo_vendas_ativo': True,
            'modulo_envase_ativo': True,
            'modulo_logistica_ativo': True,
            'modulo_fiscal_ativo': True,
            'modulo_b2b_ativo': True,
            'modulo_financeiro_ativo': True,
            'modulo_analytics_ativo': False,
        },
        {
            'nome': 'Enterprise',
            'preco_base': Decimal('2499.00'),
            'limite_usuarios': 50,
            'limite_cilindros': 10000,
            'modulo_patrimonio_ativo': True,
            'modulo_comercial_ativo': True,
            'modulo_vendas_ativo': True,
            'modulo_envase_ativo': True,
            'modulo_logistica_ativo': True,
            'modulo_fiscal_ativo': True,
            'modulo_b2b_ativo': True,
            'modulo_financeiro_ativo': True,
            'modulo_analytics_ativo': True,
        },
    ]

    for p in planos_data:
        nome = p.pop('nome')
        PlanoSaaS.objects.update_or_create(nome=nome, defaults=p)

    # Garante que os tenants existentes possuam status ATIVO e data de licença válida
    vencimento_padrao = datetime.date(2030, 12, 31)
    for t in Tenant.objects.all():
        if t.status_assinatura == 'TRIAL':
            t.status_assinatura = 'ATIVO'
        if not t.data_vencimento_licenca:
            t.data_vencimento_licenca = vencimento_padrao
        if t.valor_mensalidade_saas == Decimal('0.00'):
            t.valor_mensalidade_saas = Decimal('499.00')
        t.save(update_fields=['status_assinatura', 'data_vencimento_licenca', 'valor_mensalidade_saas'])


def reverter_seed_planos(apps, schema_editor):
    PlanoSaaS = apps.get_model('core', 'PlanoSaaS')
    PlanoSaaS.objects.filter(nome__in=['Starter', 'Profissional', 'Enterprise']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_saas_governanca_modulos_cotas'),
    ]

    operations = [
        migrations.RunPython(seed_planos_e_tenants_ativos, reverter_seed_planos),
    ]
