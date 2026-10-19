import io
import uuid
from decimal import Decimal
from datetime import timedelta, date

from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from logistica.models import (
    Veiculo,
    Abastecimento,
    PrecoCombustivelReferencia,
    ConfiguracaoCombustivelFrota
)
from logistica.services.combustivel import (
    calcular_valores_abastecimento,
    validar_odometro_abastecimento,
    validar_capacidade_tanque,
    calcular_consumo_abastecimento,
    avaliar_alertas_abastecimento,
    processar_abastecimento,
    obter_preco_referencia_aplicavel,
    obter_configuracao_combustivel
)
from logistica.services.anp import (
    importar_precos_anp_de_conteudo,
    normalizar_nome_produto_anp,
    parse_decimal_brasileiro
)

User = get_user_model()


class SprintL2CombustivelCalculosTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            razao_social="Transportadora Gas S.A.",
            nome_fantasia="Gas Log",
            cnpj="12345678000199"
        )
        self.token = set_current_tenant(self.tenant)

        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="GAS1A23",
            modelo="Delivery 11.180",
            marca="VW",
            ano=2023,
            capacidade_carga=Decimal("5000.00"),
            combustivel_padrao="Diesel S10",
            capacidade_tanque_l=Decimal("150.00"),
            consumo_referencia_km_l=Decimal("4.50"),
            odometro_atual_km=10000,
            status_ativo="Ativo"
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_calcular_valores_bidirecional(self):
        # 1. Informa Litros e Valor/Litro -> Calcula Valor Total
        l, vl, vt = calcular_valores_abastecimento(litros="50.000", valor_litro="6.2500")
        self.assertEqual(vt, Decimal("312.50"))

        # 2. Informa Valor Total e Litros -> Calcula Valor/Litro
        l, vl, vt = calcular_valores_abastecimento(valor_total="312.50", litros="50.000")
        self.assertEqual(vl, Decimal("6.2500"))

        # 3. Informa Valor Total e Valor/Litro -> Calcula Litros
        l, vl, vt = calcular_valores_abastecimento(valor_total="312.50", valor_litro="6.2500")
        self.assertEqual(l, Decimal("50.000"))

        # 4. Inconsistência nos 3 valores (excede tolerância de centavos) -> Levanta ValidationError
        with self.assertRaises(ValidationError):
            calcular_valores_abastecimento(litros="50.000", valor_litro="6.2500", valor_total="450.00")

    def test_validacao_odometro_nao_pode_retroceder(self):
        # Odômetro atual do veículo é 10.000 km
        # Tentativa de registrar abastecimento com 9.800 km deve falhar
        with self.assertRaises(ValidationError) as ctx:
            validar_odometro_abastecimento(self.veiculo, odometro_km=9800)
        self.assertIn("não pode ser inferior ao último odômetro registrado", str(ctx.exception))

        # Odômetro válido com 10.500 km
        valido = validar_odometro_abastecimento(self.veiculo, odometro_km=10500)
        self.assertTrue(valido)

    def test_odometro_atualiza_veiculo_ao_salvar(self):
        abast = Abastecimento(
            tenant=self.tenant,
            veiculo=self.veiculo,
            odometro_km=10850,
            tipo_combustivel="Diesel S10",
            litros=Decimal("80.000"),
            valor_litro=Decimal("6.1000"),
            valor_total=Decimal("488.00"),
            tanque_cheio=True
        )
        processar_abastecimento(abast)
        abast.save()

        self.veiculo.refresh_from_db()
        self.assertEqual(self.veiculo.odometro_atual_km, 10850)

    def test_validacao_capacidade_tanque(self):
        # Tanque é 150 L
        # Volume de 160 L (>100% mas <=130%) -> não bloqueia, mas gera aviso
        aviso = validar_capacidade_tanque(self.veiculo, litros=Decimal("160.000"))
        self.assertIsNotNone(aviso)
        self.assertIn("excede a capacidade nominal", aviso)

        # Volume de 210 L (>130% de 150 = 195 L) -> Bloqueio obrigatório
        with self.assertRaises(ValidationError) as ctx:
            validar_capacidade_tanque(self.veiculo, litros=Decimal("210.000"))
        self.assertIn("excede a capacidade física máxima do tanque", str(ctx.exception))

    def test_calculo_consumo_tanque_cheio_a_tanque_cheio_com_parciais(self):
        # Marco 1: Primeiro tanque cheio em 10.000 km
        a1 = Abastecimento.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            odometro_km=10000,
            tipo_combustivel="Diesel S10",
            litros=Decimal("100.000"),
            valor_litro=Decimal("6.0000"),
            valor_total=Decimal("600.00"),
            tanque_cheio=True,
            data_hora=timezone.now() - timedelta(days=5)
        )
        processar_abastecimento(a1)
        a1.save()
        self.assertIsNone(a1.consumo_km_l)  # Primeiro cheio é o baseline

        # Abastecimento parcial 1: 10.200 km (+20 L)
        a_parcial1 = Abastecimento.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            odometro_km=10200,
            tipo_combustivel="Diesel S10",
            litros=Decimal("20.000"),
            valor_litro=Decimal("6.0000"),
            valor_total=Decimal("120.00"),
            tanque_cheio=False,
            data_hora=timezone.now() - timedelta(days=3)
        )
        processar_abastecimento(a_parcial1)
        a_parcial1.save()
        self.assertEqual(a_parcial1.km_rodados_desde_anterior, 200)
        self.assertIsNone(a_parcial1.consumo_km_l)  # Parcial não fecha km/l

        # Abastecimento parcial 2: 10.400 km (+15 L)
        a_parcial2 = Abastecimento.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            odometro_km=10400,
            tipo_combustivel="Diesel S10",
            litros=Decimal("15.000"),
            valor_litro=Decimal("6.0000"),
            valor_total=Decimal("90.00"),
            tanque_cheio=False,
            data_hora=timezone.now() - timedelta(days=2)
        )
        processar_abastecimento(a_parcial2)
        a_parcial2.save()
        self.assertEqual(a_parcial2.km_rodados_desde_anterior, 200)
        self.assertIsNone(a_parcial2.consumo_km_l)

        # Marco 2: Segundo tanque cheio em 10.600 km (+25 L)
        # Total km rodados no ciclo: 10.600 - 10.000 = 600 km
        # Total litros no ciclo: 20 + 15 + 25 = 60 L
        # Consumo real esperado: 600 km / 60 L = 10.00 km/l
        # Custo por km: (120 + 90 + 150) / 600 = 360 / 600 = 0.6000 R$/km
        a2 = Abastecimento.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            odometro_km=10600,
            tipo_combustivel="Diesel S10",
            litros=Decimal("25.000"),
            valor_litro=Decimal("6.0000"),
            valor_total=Decimal("150.00"),
            tanque_cheio=True,
            data_hora=timezone.now() - timedelta(days=1)
        )
        processar_abastecimento(a2)
        a2.save()

        self.assertEqual(a2.km_rodados_desde_anterior, 600)
        self.assertEqual(a2.consumo_km_l, Decimal("10.00"))
        self.assertEqual(a2.custo_por_km, Decimal("0.6000"))

    def test_arla32_categoria_separada_nao_afeta_km_l(self):
        # Abastecimento de Arla 32 não calcula km/l
        abast_arla = Abastecimento(
            tenant=self.tenant,
            veiculo=self.veiculo,
            odometro_km=10700,
            tipo_combustivel="Arla 32",
            litros=Decimal("20.000"),
            valor_litro=Decimal("4.5000"),
            valor_total=Decimal("90.00"),
            tanque_cheio=True
        )
        km, consumo, custo = calcular_consumo_abastecimento(abast_arla)
        self.assertIsNone(consumo)


class SprintL2AlertasTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(razao_social="Log Alertas Ltda", cnpj="99887766000155")
        self.token = set_current_tenant(self.tenant)

        self.config = ConfiguracaoCombustivelFrota.objects.create(
            tenant=self.tenant,
            uf_padrao="GO",
            tolerancia_preco_pct=Decimal("15.00"),
            tolerancia_consumo_pct=Decimal("25.00")
        )

        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa="ALT1A23",
            modelo="Constellation",
            marca="VW",
            ano=2022,
            capacidade_carga=Decimal("8000.00"),
            combustivel_padrao="Diesel S10",
            capacidade_tanque_l=Decimal("200.00"),
            consumo_referencia_km_l=Decimal("4.00"),
            odometro_atual_km=50000
        )

        # Preço de referência da ANP: R$ 6,0000
        PrecoCombustivelReferencia.objects.create(
            tenant=self.tenant,
            fonte="ANP",
            produto="Diesel S10",
            uf="GO",
            municipio="",
            data_inicial=timezone.localdate() - timedelta(days=7),
            data_final=timezone.localdate(),
            preco_medio=Decimal("6.0000"),
            preco_minimo=Decimal("5.8000"),
            preco_maximo=Decimal("6.3000")
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_alerta_preco_acima_referencia_anp(self):
        # Limite tolerado: R$ 6.00 + 15% = R$ 6.90
        # Preço pago: R$ 7.50 (+25%) -> Deve gerar alerta
        abast = Abastecimento(
            tenant=self.tenant,
            veiculo=self.veiculo,
            odometro_km=50500,
            tipo_combustivel="Diesel S10",
            litros=Decimal("100.000"),
            valor_litro=Decimal("7.5000"),
            valor_total=Decimal("750.00"),
            posto_uf="GO",
            tanque_cheio=True
        )
        status_val, alertas = avaliar_alertas_abastecimento(abast, self.config)
        self.assertNotEqual(status_val, 'Normal')
        self.assertTrue(any("acima da referência ANP" in a for a in alertas))

    def test_alerta_combustivel_incompativel(self):
        # Veículo usa Diesel S10, abastece com Gasolina Comum
        abast = Abastecimento(
            tenant=self.tenant,
            veiculo=self.veiculo,
            odometro_km=50200,
            tipo_combustivel="Gasolina Comum",
            litros=Decimal("50.000"),
            valor_litro=Decimal("5.8000"),
            valor_total=Decimal("290.00"),
            tanque_cheio=False
        )
        status_val, alertas = avaliar_alertas_abastecimento(abast, self.config)
        self.assertTrue(any("difere do padrão" in a for a in alertas))


class SprintL2ANPImportacaoTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(razao_social="Empresa ANP Teste", cnpj="55443322000111")
        self.token = set_current_tenant(self.tenant)

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_parser_anp_csv_amostra_com_virgula_decimal_e_encoding(self):
        # CSV de amostra no formato oficial da ANP com ponto e vírgula e vírgula decimal
        csv_conteudo = (
            "Regiao - Sigla;Estado - Sigla;Municipio;Revenda;CNPJ da Revenda;Produto;Data da Coleta;Valor de Venda;Unidade de Medida;Bandeira\n"
            "CO;GO;GOIANIA;POSTO ALPHA;01.111.111/0001-01;DIESEL S10;10/10/2026;6,190;R$ / litro;BRANCA\n"
            "CO;GO;GOIANIA;POSTO BETA;02.222.222/0001-02;DIESEL S10;12/10/2026;5,990;R$ / litro;IPIRANGA\n"
            "CO;GO;APARECIDA DE GOIANIA;POSTO GAMA;03.333.333/0001-03;GASOLINA;11/10/2026;5,790;R$ / litro;SHELL\n"
            "CO;GO;GOIANIA;POSTO DELTA;04.444.444/0001-04;GLP;11/10/2026;95,50;R$ / 13 kg;ULTRAGAZ\n"
            "LINHA_INVALIDA_SEM_SEPARADORES\n"
        ).encode('latin-1')

        res = importar_precos_anp_de_conteudo(csv_conteudo, tenant=self.tenant)
        self.assertGreater(res['criados'], 0)

        # Verifica média de Diesel S10 em Goiânia: (6.19 + 5.99) / 2 = 6.0900
        ref_goiania = PrecoCombustivelReferencia.objects.filter(
            tenant=self.tenant,
            produto="Diesel S10",
            municipio="GOIANIA"
        ).first()
        self.assertIsNotNone(ref_goiania)
        self.assertEqual(ref_goiania.preco_medio, Decimal("6.0900"))
        self.assertEqual(ref_goiania.preco_minimo, Decimal("5.9900"))
        self.assertEqual(ref_goiania.preco_maximo, Decimal("6.1900"))
        self.assertEqual(ref_goiania.n_postos, 2)

        # Verifica média estadual de Goiás
        ref_uf = PrecoCombustivelReferencia.objects.filter(
            tenant=self.tenant,
            produto="Diesel S10",
            uf="GO",
            municipio=""
        ).first()
        self.assertIsNotNone(ref_uf)

    def test_idempotencia_da_importacao_anp(self):
        csv_conteudo = (
            "Regiao - Sigla;Estado - Sigla;Municipio;Revenda;CNPJ da Revenda;Produto;Data da Coleta;Valor de Venda;Unidade de Medida;Bandeira\n"
            "CO;GO;ANAPOLIS;POSTO TESTE;01.111.111/0001-01;ETANOL;10/10/2026;3,890;R$ / litro;BRANCA\n"
        ).encode('utf-8')

        # 1ª Importação -> Cria registro
        res1 = importar_precos_anp_de_conteudo(csv_conteudo, tenant=self.tenant)
        self.assertEqual(res1['criados'], 2)  # 1 município + 1 UF

        total_antes = PrecoCombustivelReferencia.objects.filter(tenant=self.tenant).count()

        # 2ª Importação idêntica -> Atualiza sem duplicar
        res2 = importar_precos_anp_de_conteudo(csv_conteudo, tenant=self.tenant)
        self.assertEqual(res2['criados'], 0)
        self.assertEqual(res2['atualizados'], 2)

        total_depois = PrecoCombustivelReferencia.objects.filter(tenant=self.tenant).count()
        self.assertEqual(total_antes, total_depois)

    def test_fallback_hierarquico_municipio_estado_manual(self):
        # 1. Cria preço estadual em Goiás para Diesel S10
        PrecoCombustivelReferencia.objects.create(
            tenant=self.tenant,
            fonte="ANP",
            produto="Diesel S10",
            uf="GO",
            municipio="",
            data_inicial=timezone.localdate() - timedelta(days=5),
            data_final=timezone.localdate(),
            preco_medio=Decimal("6.1500")
        )

        # 2. Busca por município 'Rio Verde' (não tem municipal, cai na UF GO)
        ref_rv = obter_preco_referencia_aplicavel(self.tenant, "Diesel S10", uf="GO", municipio="Rio Verde")
        self.assertIsNotNone(ref_rv)
        self.assertEqual(ref_rv.uf, "GO")
        self.assertEqual(ref_rv.municipio, "")
        self.assertEqual(ref_rv.preco_medio, Decimal("6.1500"))

        # 3. Agora cadastra municipal específico para 'Rio Verde'
        PrecoCombustivelReferencia.objects.create(
            tenant=self.tenant,
            fonte="ANP",
            produto="Diesel S10",
            uf="GO",
            municipio="Rio Verde",
            data_inicial=timezone.localdate() - timedelta(days=5),
            data_final=timezone.localdate(),
            preco_medio=Decimal("6.2900")
        )
        ref_especifico = obter_preco_referencia_aplicavel(self.tenant, "Diesel S10", uf="GO", municipio="Rio Verde")
        self.assertEqual(ref_especifico.preco_medio, Decimal("6.2900"))

    def test_propriedade_esta_defasado(self):
        ref_antiga = PrecoCombustivelReferencia.objects.create(
            tenant=self.tenant,
            fonte="ANP",
            produto="GNV",
            uf="GO",
            data_inicial=timezone.localdate() - timedelta(days=40),
            data_final=timezone.localdate() - timedelta(days=20),
            preco_medio=Decimal("4.8000")
        )
        self.assertTrue(ref_antiga.esta_defasado)

        ref_recente = PrecoCombustivelReferencia.objects.create(
            tenant=self.tenant,
            fonte="ANP",
            produto="GNV",
            uf="GO",
            municipio="GOIANIA",
            data_inicial=timezone.localdate() - timedelta(days=7),
            data_final=timezone.localdate(),
            preco_medio=Decimal("4.8500")
        )
        self.assertFalse(ref_recente.esta_defasado)


class SprintL2APIEIsolamentoTestCase(TestCase):
    def setUp(self):
        self.tenant1 = Tenant.objects.create(razao_social="Tenant 1 Log", cnpj="11111111000101")
        self.tenant2 = Tenant.objects.create(razao_social="Tenant 2 Log", cnpj="22222222000102")

        self.u1 = User.objects.create_user(username="u1_gestor", password="password123")
        Membership.objects.create(user=self.u1, tenant=self.tenant1, papel="ADMIN", ativo=True)

        self.u2 = User.objects.create_user(username="u2_outro", password="password123")
        Membership.objects.create(user=self.u2, tenant=self.tenant2, papel="OPERADOR", ativo=True)

        self.token = set_current_tenant(self.tenant1)
        self.veiculo1 = Veiculo.objects.create(
            tenant=self.tenant1,
            placa="AB11A11",
            modelo="Caminhão T1",
            marca="Scania",
            ano=2021,
            capacidade_carga=Decimal("6000.00"),
            combustivel_padrao="Diesel S10",
            capacidade_tanque_l=Decimal("120.00"),
            odometro_atual_km=20000
        )

        foto_bytes = b"fake_photo_bytes_comprovante"
        file_comp = SimpleUploadedFile("cupom.jpg", foto_bytes, content_type="image/jpeg")

        self.abast1 = Abastecimento.objects.create(
            tenant=self.tenant1,
            veiculo=self.veiculo1,
            odometro_km=20500,
            tipo_combustivel="Diesel S10",
            litros=Decimal("60.000"),
            valor_litro=Decimal("6.0000"),
            valor_total=Decimal("360.00"),
            comprovante=file_comp,
            tanque_cheio=True
        )

        self.client = APIClient()

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_resumo_combustivel_api(self):
        self.client.force_authenticate(user=self.u1)
        res = self.client.get("/logistica/api/combustivel/resumo/", HTTP_X_TENANT_ID=str(self.tenant1.id))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['total_gasto'], 360.0)
        self.assertEqual(res.data['total_litros'], 60.0)
        self.assertIn('ranking_veiculos', res.data)
        self.assertIn('por_combustivel', res.data)

    def test_isolamento_comprovante_entre_tenants(self):
        # Usuário do Tenant 2 tenta acessar comprovante do Tenant 1 -> 404
        self.client.force_authenticate(user=self.u2)
        res_bloqueado = self.client.get(f"/logistica/api/abastecimentos/{self.abast1.id}/comprovante/", HTTP_X_TENANT_ID=str(self.tenant2.id))
        self.assertEqual(res_bloqueado.status_code, status.HTTP_404_NOT_FOUND)

        # Usuário do Tenant 1 acessa normalmente
        self.client.force_authenticate(user=self.u1)
        res_ok = self.client.get(f"/logistica/api/abastecimentos/{self.abast1.id}/comprovante/", HTTP_X_TENANT_ID=str(self.tenant1.id))
        self.assertEqual(res_ok.status_code, status.HTTP_200_OK)

    def test_idempotencia_pwa_client_uuid(self):
        self.client.force_authenticate(user=self.u1)
        c_uuid = str(uuid.uuid4())

        payload = {
            "client_uuid": c_uuid,
            "veiculo": self.veiculo1.id,
            "odometro_km": 20800,
            "tipo_combustivel": "Diesel S10",
            "litros": "40.000",
            "valor_litro": "6.0000",
            "valor_total": "240.00",
            "tanque_cheio": True,
            "origem": "PWA"
        }

        # Primeiro envio cria registro
        res1 = self.client.post("/logistica/api/abastecimentos/", payload, format="json", HTTP_X_TENANT_ID=str(self.tenant1.id))
        self.assertIn(res1.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        abast_id = res1.data['id']

        # Reenvio idêntico do PWA não duplica
        res2 = self.client.post("/logistica/api/abastecimentos/", payload, format="json", HTTP_X_TENANT_ID=str(self.tenant1.id))
        self.assertEqual(Abastecimento.objects.filter(client_uuid=c_uuid).count(), 1)
