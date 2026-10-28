from django.db import migrations


def seed_rbac(apps, schema_editor):
    from core.rbac import seed_rbac_financeiro
    seed_rbac_financeiro()


def reverter_rbac(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=[
        'FIN_LANCADOR',
        'FIN_APROVADOR',
        'FIN_TESOUREIRO',
        'FIN_AUDITOR',
        'FIN_ADMIN'
    ]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_criar_matriz_tenants_existentes'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(seed_rbac, reverter_rbac),
    ]
