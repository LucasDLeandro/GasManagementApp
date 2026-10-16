import uuid
import zoneinfo
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from clientes.models import (
    Cliente, ContratoComodato, FranquiaModeloContrato,
    FechamentoFaturaEstadia, ItemFaturaEstadia
)
from produtos.models import (
    GasQuimico, ModeloCilindro, Cilindro, LoteEnvase, EnvaseCilindro
)
from produtos.services import registrar_entrega_cilindro

User = get_user_model()
FUSO_SP = zoneinfo.ZoneInfo('America/Sao_Paulo')


class FaturamentoEstadiaAPITests(APITestCase):
    """
    Testes de integração REST API da Sprint 5B.2:
    - Fechamento formal de fatura de estadia (/clientes/api/faturas-estadia/fechar/)
    - Download de Espelho de Medição em PDF e CSV (/clientes/api/faturas-estadia/<id>/espelho-pdf/ e espelho-csv/)
    - Exportação Canônica ERP (/clientes/api/faturas-estadia/exportacao-canonica/)
    - Painel e declaração de extravio com RBAC (/clientes/api/extravios/alertas/ e /declarar/)
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='11.222.333/0001-44',
            razao_social='Oxigênio Central Ltda',
            nome_fantasia='OxiCentral'
        )
        self.token = set_current_tenant(self.tenant)

        # Usuários
        self.user_gerente = User.objects.create_user(username='gerente.faturamento', password='pwd')
        Membership.objects.create(user=self.user_gerente, tenant=self.tenant, papel='GERENTE')

        self.user_operador = User.objects.create_user(username='operador.patio.faturamento', password='pwd')
        Membership.objects.create(user=self.user_operador, tenant=self.tenant, papel='OPERADOR_PATIO')

        # Catálogo
        self.gas_o2 = GasQuimico.objects.create(
            sigla='O2-MED-API',
            nome='Oxigênio Medicinal API',
            categoria='MEDICINAL',
            exige_lote_anvisa=True
        )
        self.modelo_t50 = ModeloCilindro.objects.create(
            descricao='Cilindro T-50 API',
            volume_hidraulico_litros=Decimal('50.00'),
            pressao_servico_bar=200,
            tara_nominal_kg=Decimal('60.00'),
            periodicidade_reteste_anos=5
        )

        self.cliente = Cliente.objects.create(
            cnpj='99.888.777/0001-66',
            nome='Hospital Metropolitano',
            endereco='Av Central, 500',
            telefone='6133445566',
            estado='DF',
            cidade='Brasília',
            proprietario='Diretoria Médica'
        )

        self.lote_o2 = LoteEnvase.objects.create(
            gas=self.gas_o2,
            codigo_lote='LOT-API-2026-01',
            status_qualidade='APROVADO',
            data_envase=date(2026, 1, 1),
            data_validade=date(2028, 1, 1),
            pureza_percentual=Decimal('99.60'),
            responsavel_tecnico='Dr. Lucas Farmacêutico (CRF-DF 9999)'
        )

        self.contrato = ContratoComodato.objects.create(
            cliente=self.cliente,
            vigencia_inicio=date(2026, 1, 1),
            franquia_cilindros_isentos=0,
            dias_carencia_giro=0,
            valor_diaria_excedente=Decimal('15.00'),
            dias_limite_extravio=180,
            custo_reposicao_casco=Decimal('2000.00')
        )

    def tearDown(self):
        reset_current_tenant(self.token)

    def _criar_e_entregar_cilindro(self, serial, dt_entrega):
        cil = Cilindro.objects.create(
            codigo_qr=f"QR-API-{serial}",
            numero_serie_ogiva=serial,
            fabricante='Cilbras',
            ano_fabricacao=2022,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas_o2,
            tara_real_kg=Decimal('60.00'),
            propriedade='DISTRIBUIDORA',
            data_ultimo_reteste=date(2024, 1, 1),
            data_proximo_reteste=date(2029, 1, 1),
            status='CHEIO_DISPONIVEL'
        )
        env = EnvaseCilindro.objects.create(
            cilindro=cil,
            lote=self.lote_o2,
            pressao_final_bar=200,
            envasado_em=timezone.now(),
            operador=self.user_gerente
        )
        cil.envase_atual = env
        cil.save(update_fields=['envase_atual'])

        dt_sp = datetime.combine(dt_entrega, datetime.min.time(), tzinfo=FUSO_SP).replace(hour=10)
        registrar_entrega_cilindro(
            cilindro=cil,
            cliente=self.cliente,
            usuario=self.user_gerente,
            ocorrido_em=dt_sp,
            client_uuid=uuid.uuid4()
        )
        return cil

    def test_api_fechar_fatura_estadia_e_consultar(self):
        """Valida endpoint POST /clientes/api/faturas-estadia/fechar/ e GET /clientes/api/faturas-estadia/"""
        client = APIClient()
        client.force_authenticate(user=self.user_gerente)
        client.defaults['HTTP_X_TENANT_ID'] = str(self.tenant.id)

        cil = self._criar_e_entregar_cilindro('FAT-API-01', date(2026, 10, 1))

        # Fecha a competência 2026-10 (31 dias * R$ 15,00 = R$ 465,00)
        payload = {
            'cliente_id': self.cliente.id,
            'competencia_ano_mes': '2026-10'
        }
        res_post = client.post('/clientes/api/faturas-estadia/fechar/', data=payload, format='json')
        self.assertEqual(res_post.status_code, status.HTTP_201_CREATED)
        data = res_post.data

        self.assertEqual(data['competencia_ano_mes'], '2026-10')
        self.assertEqual(data['status_pagamento'], 'FECHADA')
        self.assertEqual(Decimal(str(data['valor_bruto_diarias'])), Decimal('465.00'))
        self.assertEqual(Decimal(str(data['valor_liquido_total'])), Decimal('465.00'))
        self.assertEqual(len(data['itens']), 1)
        fatura_id = data['id']

        # Consulta lista de faturas
        res_get = client.get(f'/clientes/api/faturas-estadia/?cliente_id={self.cliente.id}&competencia=2026-10')
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        results = res_get.data.get('results', res_get.data) if isinstance(res_get.data, dict) else res_get.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], fatura_id)

    def test_api_download_espelho_pdf_e_csv(self):
        """Valida endpoints de download do Espelho de Medição em PDF e CSV"""
        client = APIClient()
        client.force_authenticate(user=self.user_gerente)
        client.defaults['HTTP_X_TENANT_ID'] = str(self.tenant.id)

        self._criar_e_entregar_cilindro('DOC-API-01', date(2026, 10, 1))

        res_close = client.post('/clientes/api/faturas-estadia/fechar/', {
            'cliente_id': self.cliente.id,
            'competencia_ano_mes': '2026-10'
        }, format='json')
        self.assertEqual(res_close.status_code, status.HTTP_201_CREATED)
        fatura_id = res_close.data['id']

        # Download PDF
        res_pdf = client.get(f'/clientes/api/faturas-estadia/{fatura_id}/espelho-pdf/')
        self.assertEqual(res_pdf.status_code, status.HTTP_200_OK)
        self.assertEqual(res_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(res_pdf.content.startswith(b'%PDF'))
        self.assertIn('attachment;', res_pdf['Content-Disposition'])

        # Download CSV
        res_csv = client.get(f'/clientes/api/faturas-estadia/{fatura_id}/espelho-csv/')
        self.assertEqual(res_csv.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', res_csv['Content-Type'])
        self.assertIn('ESPELHO DE MEDIÇÃO', res_csv.content.decode('utf-8'))
        self.assertIn('DOC-API-01', res_csv.content.decode('utf-8'))

    def test_api_exportacao_canonica_erp(self):
        """Valida endpoint GET /clientes/api/faturas-estadia/exportacao-canonica/ (JSON e CSV)"""
        client = APIClient()
        client.force_authenticate(user=self.user_gerente)
        client.defaults['HTTP_X_TENANT_ID'] = str(self.tenant.id)

        self._criar_e_entregar_cilindro('CANON-01', date(2026, 10, 1))
        client.post('/clientes/api/faturas-estadia/fechar/', {
            'cliente_id': self.cliente.id,
            'competencia_ano_mes': '2026-10'
        }, format='json')

        # Exportação JSON
        res_json = client.get('/clientes/api/faturas-estadia/exportacao-canonica/?competencia=2026-10&formato=json')
        self.assertEqual(res_json.status_code, status.HTTP_200_OK)
        self.assertEqual(res_json.data['versao_schema'], '1.0')
        self.assertEqual(res_json.data['competencia'], '2026-10')
        self.assertEqual(res_json.data['total_faturas'], 1)
        self.assertEqual(len(res_json.data['faturas']), 1)

        # Exportação CSV
        res_csv = client.get('/clientes/api/faturas-estadia/exportacao-canonica/?competencia=2026-10&formato=csv')
        self.assertEqual(res_csv.status_code, status.HTTP_200_OK)
        self.assertIn('FATURA_ID;CLIENTE_CNPJ', res_csv.content.decode('utf-8'))
        self.assertIn(self.cliente.cnpj, res_csv.content.decode('utf-8'))

    def test_api_extravios_alertas_e_declarar_com_rbac(self):
        """Valida alertas de extravio e restrição RBAC ao declarar extravio"""
        # Cilindro retido há 190 dias (> 180 limite)
        dia_ref = date(2026, 10, 15)
        dt_antiga = dia_ref - timedelta(days=190)
        cil = self._criar_e_entregar_cilindro('EXTRAV-API-01', dt_antiga)

        # 1. Alertas
        client_gerente = APIClient()
        client_gerente.force_authenticate(user=self.user_gerente)
        client_gerente.defaults['HTTP_X_TENANT_ID'] = str(self.tenant.id)

        res_alertas = client_gerente.get('/clientes/api/extravios/alertas/')
        self.assertEqual(res_alertas.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(res_alertas.data), 1)
        alerta_cil = next(a for a in res_alertas.data if a['cilindro_id'] == cil.id)
        self.assertEqual(alerta_cil['dias_limite_extravio'], 180)
        self.assertEqual(alerta_cil['valor_reposicao'], 2000.0)

        # 2. RBAC: Operador não pode declarar extravio (403 Forbidden)
        client_op = APIClient()
        client_op.force_authenticate(user=self.user_operador)
        client_op.defaults['HTTP_X_TENANT_ID'] = str(self.tenant.id)

        payload_extravio = {
            'cilindro_id': cil.id,
            'data_extravio': dia_ref.isoformat(),
            'justificativa': 'Tentativa de operador declarar extravio'
        }
        res_op = client_op.post('/clientes/api/extravios/declarar/', payload_extravio, format='json')
        self.assertEqual(res_op.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Gerente declara extravio com sucesso
        res_gerente = client_gerente.post('/clientes/api/extravios/declarar/', {
            'cilindro_id': cil.id,
            'data_extravio': dia_ref.isoformat(),
            'justificativa': 'Extravio homologado pela gerência'
        }, format='json')
        self.assertEqual(res_gerente.status_gerente if hasattr(res_gerente, 'status_gerente') else res_gerente.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(res_gerente.data['valor_reposicao'])), Decimal('2000.00'))
        self.assertFalse(res_gerente.data['cobrado'])
