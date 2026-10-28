from django.db import migrations


def migrar_retestes_legados(apps, schema_editor):
    Cilindro = apps.get_model('produtos', 'Cilindro')
    HistoricoRetesteHidrostatico = apps.get_model('produtos', 'HistoricoRetesteHidrostatico')

    cilindros_com_reteste = Cilindro.objects.filter(data_ultimo_reteste__isnull=False)
    for cil in cilindros_com_reteste:
        if HistoricoRetesteHidrostatico.objects.filter(
            cilindro=cil,
            origem_registro='LEGADO',
            data_execucao=cil.data_ultimo_reteste
        ).exists():
            continue

        HistoricoRetesteHidrostatico.objects.create(
            tenant=cil.tenant,
            cilindro=cil,
            origem_registro='LEGADO',
            data_execucao=cil.data_ultimo_reteste,
            data_proximo_reteste=cil.data_proximo_reteste,
            resultado='APROVADO',
            numero_certificado='LEGADO-PRE-V2',
            oficina_nome='Oficina Histórica / Carga Legada',
            oficina_cnpj='00.000.000/0000-00',
            registro_inmetro='LEGADO-INMETRO',
            observacoes='Carga inicial de histórico de reteste a partir dos dados legados do cilindro.',
        )


def reverter_migracao_retestes_legados(apps, schema_editor):
    HistoricoRetesteHidrostatico = apps.get_model('produtos', 'HistoricoRetesteHidrostatico')
    ReclassificacaoCilindro = apps.get_model('produtos', 'ReclassificacaoCilindro')
    ItemEnvioReteste = apps.get_model('produtos', 'ItemEnvioReteste')

    # Desconecta eventuais vínculos protegidos antes da exclusão
    ReclassificacaoCilindro.objects.filter(reteste_vinculado__origem_registro='LEGADO').update(reteste_vinculado=None, force=True)
    ItemEnvioReteste.objects.filter(reteste_vinculado__origem_registro='LEGADO').update(reteste_vinculado=None)

    HistoricoRetesteHidrostatico.objects.filter(origem_registro='LEGADO').delete(force=True)


class Migration(migrations.Migration):

    dependencies = [
        ('produtos', '0015_reclassificacaocilindro_exigiu_novo_reteste_and_more'),
    ]

    operations = [
        migrations.RunPython(migrar_retestes_legados, reverter_migracao_retestes_legados),
    ]
