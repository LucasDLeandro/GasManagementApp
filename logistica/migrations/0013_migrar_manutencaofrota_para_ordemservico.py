from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from django.db import migrations


def migrar_manutencao_para_os(apps, schema_editor):
    ManutencaoFrota = apps.get_model('logistica', 'ManutencaoFrota')
    OrdemServico = apps.get_model('logistica', 'OrdemServico')

    status_map = {
        'Agendada': 'Aberta',
        'Em Progresso': 'Em Execução',
        'Concluída': 'Concluída',
    }

    for m in ManutencaoFrota.objects.all():
        numero_legado = f"OS-LEGADO-{m.id}"
        if OrdemServico.objects.filter(numero=numero_legado).exists():
            continue

        novo_status = status_map.get(m.status, 'Concluída')
        data_abert = datetime(m.data_manutencao.year, m.data_manutencao.month, m.data_manutencao.day, 12, 0, tzinfo=dt_timezone.utc)
        data_concl = data_abert if novo_status == 'Concluída' else None
        odometro = getattr(m.veiculo, 'odometro_atual_km', Decimal('0.00')) or Decimal('0.00')

        OrdemServico.objects.create(
            tenant=m.tenant,
            veiculo=m.veiculo,
            numero=numero_legado,
            tipo='Corretiva',
            origem='Manual',
            status=novo_status,
            imobiliza_veiculo=False,
            descricao_problema=m.descricao or 'Manutenção registrada no sistema legado',
            data_abertura=data_abert,
            data_conclusao=data_concl,
            odometro_entrada=odometro,
            odometro_saida=odometro,
            custo_mao_de_obra=m.custo or Decimal('0.00'),
            custo_pecas=Decimal('0.00'),
            custo_terceiros=Decimal('0.00'),
            custo_total=m.custo or Decimal('0.00'),
            observacoes='Migrado automaticamente do registro legado de ManutencaoFrota'
        )


def reverter_migracao_os(apps, schema_editor):
    OrdemServico = apps.get_model('logistica', 'OrdemServico')
    OrdemServico.objects.filter(numero__startswith='OS-LEGADO-').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('logistica', '0012_checklistmodelo_fornecedor_ordemservico_osanexo_and_more'),
    ]

    operations = [
        migrations.RunPython(migrar_manutencao_para_os, reverter_migracao_os),
    ]
