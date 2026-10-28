from django.db import migrations


def criar_matrizes_tenants(apps, schema_editor):
    """
    Data migration idempotente:
    Cria a Filial Matriz para cada Tenant já existente na base de dados.
    """
    Tenant = apps.get_model('core', 'Tenant')
    Filial = apps.get_model('core', 'Filial')
    manager = getattr(Filial, 'unscoped', Filial.objects)

    for tenant in Tenant.objects.all():
        ja_tem_matriz = manager.filter(tenant=tenant, matriz=True).exists()
        if not ja_tem_matriz:
            nome_filial = f"Matriz - {tenant.nome_fantasia or tenant.razao_social}"
            manager.create(
                tenant=tenant,
                nome=nome_filial[:255],
                cnpj=tenant.cnpj or "00.000.000/0001-00",
                inscricao_estadual='ISENTO',
                uf='SP',
                municipio_ibge='3550308',
                matriz=True,
                ativo=True
            )


def reverter_matrizes_tenants(apps, schema_editor):
    """
    Reversão idempotente da data migration.
    """
    Filial = apps.get_model('core', 'Filial')
    manager = getattr(Filial, 'unscoped', Filial.objects)
    # Remove apenas filiais marcadas como Matriz criadas
    manager.filter(matriz=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_jobexecucao_logauditoriadados_filial_idempotencykey'),
    ]

    operations = [
        migrations.RunPython(criar_matrizes_tenants, reverter_matrizes_tenants),
    ]
