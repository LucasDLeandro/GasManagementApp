import datetime
import importlib
from decimal import Decimal
from django.test import TestCase
from django.apps import apps

from core.models import Tenant
from core.tenancy import set_current_tenant, reset_current_tenant
from produtos.models import Cilindro, GasQuimico, ModeloCilindro, HistoricoRetesteHidrostatico

migration_mod = importlib.import_module('produtos.migrations.0016_migrar_retestes_legados')
migrar_retestes_legados = migration_mod.migrar_retestes_legados
reverter_migracao_retestes_legados = migration_mod.reverter_migracao_retestes_legados


class DataMigrationRetestesLegadosTests(TestCase):
    """
    Testes de idempotência e reversibilidade da carga de retestes legados (Sprint 8B - Tarefa 9).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='77.888.999/0001-22',
            razao_social='Carga Reteste Teste Ltda',
            nome_fantasia='Reteste Gás'
        )
        set_current_tenant(self.tenant)
        self.gas, _ = GasQuimico.objects.get_or_create(
            sigla='Ar',
            defaults={'nome': 'Argônio', 'categoria': 'INDUSTRIAL'}
        )
        self.modelo = ModeloCilindro.objects.create(
            tenant=self.tenant,
            descricao='AR-50L',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('50.00')
        )

        self.cil1 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-LEG-01',
            numero_serie_ogiva='SERIE-LEG-01',
            fabricante='Cilindros Brasil',
            ano_fabricacao=2018,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            data_ultimo_reteste=datetime.date(2021, 5, 10),
            data_proximo_reteste=datetime.date(2026, 5, 10),
            status='VAZIO_TRIAGEM'
        )

        self.cil2 = Cilindro.objects.create(
            tenant=self.tenant,
            codigo_qr='QR-LEG-02',
            numero_serie_ogiva='SERIE-LEG-02',
            fabricante='Cilindros Brasil',
            ano_fabricacao=2019,
            modelo=self.modelo,
            gas_dedicado=self.gas,
            data_ultimo_reteste=datetime.date(2022, 8, 15),
            data_proximo_reteste=datetime.date(2027, 8, 15),
            status='VAZIO_TRIAGEM'
        )

    def tearDown(self):
        reset_current_tenant()
        super().tearDown()

    def test_migracao_cria_historico_legado_e_idempotente(self):
        # Limpa eventuais legados criados pelo migrate inicial do setup
        HistoricoRetesteHidrostatico.objects.filter(origem_registro='LEGADO').delete(force=True)

        # Executa migração
        migrar_retestes_legados(apps, None)

        hist1 = HistoricoRetesteHidrostatico.objects.filter(cilindro=self.cil1, origem_registro='LEGADO').first()
        self.assertIsNotNone(hist1)
        self.assertEqual(hist1.data_execucao, datetime.date(2021, 5, 10))
        self.assertEqual(hist1.data_proximo_reteste, datetime.date(2026, 5, 10))
        self.assertEqual(hist1.resultado, 'APROVADO')

        hist2 = HistoricoRetesteHidrostatico.objects.filter(cilindro=self.cil2, origem_registro='LEGADO').first()
        self.assertIsNotNone(hist2)
        self.assertEqual(hist2.data_execucao, datetime.date(2022, 8, 15))

        total_antes = HistoricoRetesteHidrostatico.objects.filter(origem_registro='LEGADO').count()

        # Idempotência: rodar novamente não duplica
        migrar_retestes_legados(apps, None)
        total_depois = HistoricoRetesteHidrostatico.objects.filter(origem_registro='LEGADO').count()
        self.assertEqual(total_antes, total_depois)

    def test_reversao_migracao_remove_apenas_legados(self):
        migrar_retestes_legados(apps, None)
        self.assertGreater(HistoricoRetesteHidrostatico.objects.filter(origem_registro='LEGADO').count(), 0)

        # Cria um reteste REGISTRO formal
        HistoricoRetesteHidrostatico.objects.create(
            tenant=self.tenant,
            cilindro=self.cil1,
            origem_registro='REGISTRO',
            data_execucao=datetime.date(2026, 1, 1),
            numero_certificado='CERT-NOVO',
            oficina_nome='Oficina Formal',
            oficina_cnpj='11.222.333/0001-00',
            registro_inmetro='INM-FORMAL',
            resultado='APROVADO'
        )

        reverter_migracao_retestes_legados(apps, None)

        self.assertEqual(HistoricoRetesteHidrostatico.objects.filter(origem_registro='LEGADO').count(), 0)
        self.assertEqual(HistoricoRetesteHidrostatico.objects.filter(origem_registro='REGISTRO').count(), 1)
