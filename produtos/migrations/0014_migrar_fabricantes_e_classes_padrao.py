import csv
from decimal import Decimal
import os
from django.db import migrations


def migrar_fabricantes_e_classes(apps, schema_editor):
    Tenant = apps.get_model('core', 'Tenant')
    FabricanteCilindro = apps.get_model('produtos', 'FabricanteCilindro')
    ClasseAtivo = apps.get_model('produtos', 'ClasseAtivo')
    Cilindro = apps.get_model('produtos', 'Cilindro')

    linhas_relatorio = []

    for tenant in Tenant.objects.all():
        # 1. Garante classe de ativo padrão para o tenant
        classe_padrao, _ = ClasseAtivo.objects.get_or_create(
            tenant=tenant,
            codigo='CILINDRO_PADRAO',
            defaults={
                'nome': 'Cilindros de Aço / Alumínio (Padrão)',
                'tipo': 'CILINDRO',
                'vida_util_meses_padrao': 120,
                'percentual_residual_padrao': Decimal('0.1000'),
                'metodo_depreciacao': 'LINEAR',
                'ativo': True,
            }
        )

        # 2. Normaliza fabricantes distintos de cilindros
        valores_fabricante = Cilindro.objects.filter(tenant=tenant).values_list('fabricante', flat=True).distinct()

        for fab_raw in valores_fabricante:
            fab_str = (fab_raw or '').strip()
            # Se for nulo, vazio ou genérico não identificável
            if not fab_str or fab_str.upper() in ['N/I', 'DESCONHECIDO', '?', 'SEM FABRICANTE']:
                # Coleta cilindros para o relatório de pendências
                cilindros_pendentes = Cilindro.objects.filter(tenant=tenant, fabricante=fab_raw)
                for c in cilindros_pendentes:
                    linhas_relatorio.append({
                        'tenant_id': str(tenant.id),
                        'cilindro_id': str(c.id),
                        'codigo_qr': c.codigo_qr,
                        'numero_serie': c.numero_serie_ogiva,
                        'fabricante_legado': str(fab_raw),
                        'motivo_pendencia': 'Fabricante nulo, vazio ou não identificado',
                    })
                continue

            # Nome canônico com capitalização adequada se for tudo minúsculo
            nome_canonico = fab_str.upper() if len(fab_str) <= 4 else fab_str.title()

            fabricante_obj, _ = FabricanteCilindro.objects.get_or_create(
                tenant=tenant,
                nome=nome_canonico,
                defaults={
                    'pais_origem': 'BR',
                    'norma_fabricacao_padrao': '',
                    'ativo': True,
                }
            )

            # Atualiza cilindros vinculados
            Cilindro.objects.filter(tenant=tenant, fabricante=fab_raw).update(
                fabricante_catalogo=fabricante_obj,
                fabricante=nome_canonico
            )

        # 3. Garante que todo cilindro PROPRIO ativo tenha classe de ativo vinculada
        cilindros_proprios_sem_classe = Cilindro.objects.filter(
            tenant=tenant,
            propriedade__in=['PROPRIO', 'DISTRIBUIDORA'],
            classe_ativo__isnull=True
        )
        for c in cilindros_proprios_sem_classe:
            c.classe_ativo = classe_padrao
            if not c.vida_util_meses:
                c.vida_util_meses = classe_padrao.vida_util_meses_padrao
            if c.valor_aquisicao and c.valor_residual is None:
                c.valor_residual = (c.valor_aquisicao * classe_padrao.percentual_residual_padrao).quantize(Decimal('0.01'))
            c.save(update_fields=['classe_ativo', 'vida_util_meses', 'valor_residual'])

    # 4. Grava relatório de inconsistências em docs/migracao_fabricantes.csv
    try:
        from django.conf import settings
        docs_dir = os.path.join(settings.BASE_DIR, 'docs')
        os.makedirs(docs_dir, exist_ok=True)
        relatorio_path = os.path.join(docs_dir, 'migracao_fabricantes.csv')

        with open(relatorio_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['tenant_id', 'cilindro_id', 'codigo_qr', 'numero_serie', 'fabricante_legado', 'motivo_pendencia']
            )
            writer.writeheader()
            for linha in linhas_relatorio:
                writer.writerow(linha)
    except Exception:
        pass


def reverter_migracao_fabricantes(apps, schema_editor):
    Cilindro = apps.get_model('produtos', 'Cilindro')
    FabricanteCilindro = apps.get_model('produtos', 'FabricanteCilindro')
    ClasseAtivo = apps.get_model('produtos', 'ClasseAtivo')

    # Desvincula catálogos e classes preenchidos nos cilindros para evitar ProtectedError
    Cilindro.objects.all().update(fabricante_catalogo=None, classe_ativo=None)
    FabricanteCilindro.objects.all().delete()
    ClasseAtivo.objects.filter(codigo='CILINDRO_PADRAO').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('produtos', '0013_tabelaindenizacaocilindro_and_more'),
        ('core', '0010_seed_planos_saas'),
    ]

    operations = [
        migrations.RunPython(migrar_fabricantes_e_classes, reverter_migracao_fabricantes),
    ]
