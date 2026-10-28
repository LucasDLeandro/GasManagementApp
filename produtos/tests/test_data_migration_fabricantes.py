import os
import csv
import datetime
from decimal import Decimal
from django.test import TestCase
from django.apps import apps
from django.conf import settings

from core.models import Tenant
from produtos.models import Cilindro, FabricanteCilindro, ClasseAtivo, GasQuimico, ModeloCilindro
from core.tenancy import set_current_tenant, reset_current_tenant
import importlib

migration_mod = importlib.import_module('produtos.migrations.0014_migrar_fabricantes_e_classes_padrao')
migrar_fabricantes_e_classes = migration_mod.migrar_fabricantes_e_classes
reverter_migracao_fabricantes = migration_mod.reverter_migracao_fabricantes


class DataMigrationFabricantesTests(TestCase):
    """
    Testes unitários específicos para validar idempotência, geração de relatório de pendências
    e rollback da data migration de fabricantes e classes de ativos (Sprint 8A - Tarefa 1).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='88.999.000/0001-11',
            razao_social='Usina Migração Ltda',
            nome_fantasia='Migração Gás'
        )
        set_current_tenant(self.tenant)
        self.gas = GasQuimico.objects.create(nome='Hélio Puro', sigla='He', categoria='INDUSTRIAL')
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao='HE-50L',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('45.00')
        )

        # 1. Cilindro com fabricante válido
        self.cil_valido = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-MIG-01',
            numero_serie_ogiva='SERIE-MIG-01',
            fabricante='  cilbras s/a  ',
            ano_fabricacao=2022,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            propriedade='PROPRIO',
            valor_aquisicao=Decimal('1000.00'),
            data_ultimo_reteste=datetime.date(2023, 1, 1),
            data_proximo_reteste=datetime.date(2028, 1, 1),
        )

        # 2. Cilindro com fabricante não identificado/vazio (candidato ao relatório)
        self.cil_invalido = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-MIG-02',
            numero_serie_ogiva='SERIE-MIG-02',
            fabricante='',
            ano_fabricacao=2020,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            propriedade='CLIENTE',
            data_ultimo_reteste=datetime.date(2023, 1, 1),
            data_proximo_reteste=datetime.date(2028, 1, 1),
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_migracao_fabricantes_idempotente_e_relatorio(self):
        """Executa a migração, verifica normalização, classe de ativo e relatório CSV."""
        # Execução 1
        migrar_fabricantes_e_classes(apps, None)

        self.cil_valido.refresh_from_db()
        self.assertIsNotNone(self.cil_valido.fabricante_catalogo)
        self.assertEqual(self.cil_valido.fabricante_catalogo.nome, 'Cilbras S/A')
        self.assertEqual(self.cil_valido.fabricante, 'Cilbras S/A')
        self.assertIsNotNone(self.cil_valido.classe_ativo)
        self.assertEqual(self.cil_valido.classe_ativo.codigo, 'CILINDRO_PADRAO')

        # Cilindro inválido não vinculou catálogo
        self.cil_invalido.refresh_from_db()
        self.assertIsNone(self.cil_invalido.fabricante_catalogo)

        # Verifica relatório CSV gerado
        csv_path = os.path.join(settings.BASE_DIR, 'docs', 'migracao_fabricantes.csv')
        self.assertTrue(os.path.exists(csv_path))

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            linhas = list(reader)
            # Confirma que o cilindro com fabricante vazio foi para o relatório de pendências
            self.assertTrue(any(l['codigo_qr'] == 'QR-MIG-02' for l in linhas))

        # Execução 2 (Idempotência: não duplica fabricantes nem classes)
        migrar_fabricantes_e_classes(apps, None)
        total_fab = FabricanteCilindro.objects.filter(tenant=self.tenant, nome='Cilbras S/A').count()
        self.assertEqual(total_fab, 1)

    def test_reversao_migracao_fabricantes(self):
        """Testa o rollback da migração de dados."""
        migrar_fabricantes_e_classes(apps, None)
        self.cil_valido.refresh_from_db()
        self.assertIsNotNone(self.cil_valido.fabricante_catalogo)

        # Executa rollback
        reverter_migracao_fabricantes(apps, None)

        self.cil_valido.refresh_from_db()
        self.assertIsNone(self.cil_valido.fabricante_catalogo)
        self.assertEqual(FabricanteCilindro.objects.filter(tenant=self.tenant).count(), 0)
