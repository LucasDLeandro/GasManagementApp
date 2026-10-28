from django.db import migrations


def migrar_contas_classe_ativo(apps, schema_editor):
    ClasseAtivo = apps.get_model('produtos', 'ClasseAtivo')
    PlanoContas = apps.get_model('financeiro', 'PlanoContas')

    for classe in ClasseAtivo.objects.all():
        alterado = False
        if classe.codigo_conta_imobilizado and not classe.conta_imobilizado_id:
            conta = PlanoContas.objects.filter(
                tenant_id=classe.tenant_id,
                codigo_estrutural=classe.codigo_conta_imobilizado
            ).first()
            if conta:
                classe.conta_imobilizado = conta
                alterado = True

        if classe.codigo_conta_depreciacao_acumulada and not classe.conta_depreciacao_acumulada_id:
            conta = PlanoContas.objects.filter(
                tenant_id=classe.tenant_id,
                codigo_estrutural=classe.codigo_conta_depreciacao_acumulada
            ).first()
            if conta:
                classe.conta_depreciacao_acumulada = conta
                alterado = True

        if classe.codigo_conta_despesa_depreciacao and not classe.conta_despesa_depreciacao_id:
            conta = PlanoContas.objects.filter(
                tenant_id=classe.tenant_id,
                codigo_estrutural=classe.codigo_conta_despesa_depreciacao
            ).first()
            if conta:
                classe.conta_despesa_depreciacao = conta
                alterado = True

        if alterado:
            classe.save(update_fields=[
                'conta_imobilizado',
                'conta_depreciacao_acumulada',
                'conta_despesa_depreciacao'
            ])


def reverter_migracao_contas_classe_ativo(apps, schema_editor):
    ClasseAtivo = apps.get_model('produtos', 'ClasseAtivo')
    for classe in ClasseAtivo.objects.all():
        classe.conta_imobilizado = None
        classe.conta_depreciacao_acumulada = None
        classe.conta_despesa_depreciacao = None
        classe.save(update_fields=[
            'conta_imobilizado',
            'conta_depreciacao_acumulada',
            'conta_despesa_depreciacao'
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('produtos', '0018_classeativo_conta_depreciacao_acumulada_and_more'),
        ('financeiro', '0009_lancamentomanualpendente_orcamento_and_more'),
    ]

    operations = [
        migrations.RunPython(
            migrar_contas_classe_ativo,
            reverter_migracao_contas_classe_ativo
        ),
    ]
