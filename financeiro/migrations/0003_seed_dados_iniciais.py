from django.db import migrations


def executar_seed_inicial(apps, schema_editor):
    Tenant = apps.get_model('core', 'Tenant')
    from financeiro.seeds import seed_financeiro_tenant_completo
    for tenant in Tenant.objects.all():
        seed_financeiro_tenant_completo(tenant)


def reverter_seed_inicial(apps, schema_editor):
    # Reversão segura e idempotente (preserva integridade referencial caso contas já tenham sido movimentadas)
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_seed_planos_saas'),
        ('financeiro', '0002_triggers_imutabilidade'),
    ]

    operations = [
        migrations.RunPython(executar_seed_inicial, reverter_seed_inicial),
    ]
