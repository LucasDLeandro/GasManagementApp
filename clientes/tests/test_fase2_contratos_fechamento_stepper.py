import uuid
import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from core.webhooks import WebhookDeliveryLog
from clientes.models import (
    Cliente, ContratoComodato, FranquiaModeloContrato,
    FechamentoFaturaEstadia, ItemFaturaEstadia, AjusteCompetenciaEstadia, ExtravioCilindroRegistro
)
from produtos.models import GasQuimico, ModeloCilindro, Cilindro, MovimentacaoCilindro, LoteEnvase, EnvaseCilindro
from produtos.services import registrar_entrega_cilindro

User = get_user_model()


class Fase2ContratosFechamentoStepperTests(TestCase):
    """
    Suíte de Testes Automatizados da FASE 2:
    1. Editor de Contratos Versionados com Franquias Dinâmicas por Modelo.
    2. Console de Fechamento de Faturas (Stepper de 3 Passos):
       - Passo 1 & 2: Simulação Prévia (dry-run) com Comparativo e Drill-Down em Árvore.
       - Passo 3: Fechamento Formal Imutável com Outbox e Espelhos PDF/CSV.
    3. Fila de Extravios e Radar Preventivo de Carência (5 dias).
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='22.222.222/0001-22',
            razao_social='Oxigênio Brasil Ltda',
            nome_fantasia='OxiBrasil'
        )
        self.token = set_current_tenant(self.tenant)

        # Usuário Gerente
        self.user_gerente = User.objects.create_user(
            username='gerente_fase2',
            password='Password123!',
            first_name='Mariana',
            last_name='Gerente'
        )
        self.membership_gerente = Membership.objects.create(
            user=self.user_gerente,
            tenant=self.tenant,
            papel='GERENTE',
            ativo=True
        )

        # Usuário Vendedor
        self.user_vendedor = User.objects.create_user(
            username='vendedor_fase2',
            password='Password123!',
            first_name='Lucas',
            last_name='Vendedor'
        )
        self.membership_vendedor = Membership.objects.create(
            user=self.user_vendedor,
            tenant=self.tenant,
            papel='VENDEDOR',
            ativo=True
        )

        # Cliente
        self.cliente = Cliente.objects.create(
            nome='Hospital Santa Clara',
            cnpj='33.444.555/0001-66',
            endereco='Rua da Saúde, 500',
            cidade='São Paulo',
            estado='SP'
        )

        # Modelos e Gás
        self.gas = GasQuimico.objects.create(
            nome='Oxigênio Medicinal',
            sigla='O2-MED-F2',
            categoria='MEDICINAL',
            exige_lote_anvisa=True,
            cor_padrao_abnt='BRANCO'
        )
        self.modelo_t50 = ModeloCilindro.objects.create(
            descricao='Cilindro T-50 200bar',
            volume_hidraulico_litros=50.0,
            pressao_servico_bar=200,
            tara_nominal_kg=52.0,
            periodicidade_reteste_anos=5
        )
        self.modelo_pp = ModeloCilindro.objects.create(
            descricao='Cilindro PP Portátil 10L',
            volume_hidraulico_litros=10.0,
            pressao_servico_bar=150,
            tara_nominal_kg=12.0,
            periodicidade_reteste_anos=5
        )

        # Cilindros
        self.cilindro_1 = Cilindro.objects.create(
            codigo_qr='CIL-F2-001',
            numero_serie_ogiva='SERIE-F2-001',
            fabricante='Cilindros Brasil',
            ano_fabricacao=2021,
            modelo=self.modelo_t50,
            gas_dedicado=self.gas,
            tara_real_kg=52.2,
            propriedade='DISTRIBUIDORA',
            data_ultimo_reteste=timezone.now().date(),
            data_proximo_reteste=timezone.now().date() + datetime.timedelta(days=365 * 5),
            status='CHEIO_DISPONIVEL'
        )
        self.cilindro_2 = Cilindro.objects.create(
            codigo_qr='CIL-F2-002',
            numero_serie_ogiva='SERIE-F2-002',
            fabricante='Cilindros Brasil',
            ano_fabricacao=2021,
            modelo=self.modelo_pp,
            gas_dedicado=self.gas,
            tara_real_kg=12.1,
            propriedade='DISTRIBUIDORA',
            data_ultimo_reteste=timezone.now().date(),
            data_proximo_reteste=timezone.now().date() + datetime.timedelta(days=365 * 5),
            status='CHEIO_DISPONIVEL'
        )

        self.lote_o2 = LoteEnvase.objects.create(
            gas=self.gas,
            codigo_lote='LT-F2-2026',
            status_qualidade='APROVADO',
            data_envase=timezone.now().date(),
            data_validade=timezone.now().date() + datetime.timedelta(days=365),
            pureza_percentual=99.8,
            responsavel_tecnico='Dra. Camila RT'
        )
        for cil in [self.cilindro_1, self.cilindro_2]:
            env = EnvaseCilindro.objects.create(
                cilindro=cil,
                lote=self.lote_o2,
                pressao_final_bar=200,
                envasado_em=timezone.now(),
                operador=self.user_gerente
            )
            cil.envase_atual = env
            cil.save(update_fields=['envase_atual'])

        self.client_api = APIClient()

    def tearDown(self):
        reset_current_tenant(self.token)

    def test_criar_contrato_versionado_com_franquias_por_modelo(self):
        """
        Editor de Contratos: POST /clientes/api/contratos/ com parametrização de franquias aninhadas.
        """
        self.client_api.force_authenticate(user=self.user_gerente)
        payload = {
            'cliente': self.cliente.id,
            'vigencia_inicio': '2026-01-01',
            'vigencia_fim': None,
            'criterio_franquia': 'FIFO',
            'agrupar_franquia_filiais': True,
            'dias_limite_extravio': 150,
            'franquia_cilindros_isentos': 2,
            'dias_carencia_giro': 25,
            'valor_diaria_excedente': '4.00',
            'custo_reposicao_casco': '2000.00',
            'franquias_modelo': [
                {
                    'modelo': self.modelo_t50.id,
                    'franquia_cilindros_isentos': 5,
                    'dias_carencia_giro': 30,
                    'taxa_diaria': '5.50',
                    'valor_reposicao_extravio': '2500.00'
                },
                {
                    'modelo': self.modelo_pp.id,
                    'franquia_cilindros_isentos': 10,
                    'dias_carencia_giro': 20,
                    'taxa_diaria': '2.50',
                    'valor_reposicao_extravio': '1200.00'
                }
            ]
        }

        res = self.client_api.post('/clientes/api/contratos/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.data
        self.assertTrue(data['ativo_hoje'])
        self.assertEqual(data['criterio_franquia'], 'FIFO')
        self.assertEqual(len(data['franquias_modelo']), 2)

        contrato = ContratoComodato.objects.get(id=data['id'])
        self.assertEqual(contrato.franquias_modelo.count(), 2)

    def test_stepper_passo1_e_passo2_simulacao_drill_down_previa(self):
        """
        Passo 1 & 2 do Stepper: POST /clientes/api/faturas-estadia/simular-drill-down/
        Gera simulação dry-run com comparativo e árvore completa de drill-down diário.
        """
        # Cria contrato vigente
        contrato = ContratoComodato.objects.create(
            cliente=self.cliente,
            vigencia_inicio=datetime.date(2026, 1, 1),
            criterio_franquia='FIFO',
            franquia_cilindros_isentos=0,
            dias_carencia_giro=10,
            valor_diaria_excedente=Decimal('5.00'),
            custo_reposicao_casco=Decimal('2000.00')
        )
        FranquiaModeloContrato.objects.create(
            contrato=contrato,
            modelo=self.modelo_t50,
            franquia_cilindros_isentos=0,
            dias_carencia_giro=10,
            taxa_diaria=Decimal('5.00'),
            valor_reposicao_extravio=Decimal('2000.00')
        )

        # Entrega cilindro 1 em 01/10/2026
        dt_entrega = timezone.make_aware(datetime.datetime(2026, 10, 1, 10, 0, 0))
        registrar_entrega_cilindro(cilindro=self.cilindro_1, cliente=self.cliente, ocorrido_em=dt_entrega, usuario=self.user_gerente)

        self.client_api.force_authenticate(user=self.user_gerente)
        payload = {
            'cliente_id': self.cliente.id,
            'competencia_ano_mes': '2026-10'
        }

        res = self.client_api.post('/clientes/api/faturas-estadia/simular-drill-down/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        self.assertEqual(data['status_pagamento'], 'PREVIA')
        self.assertIn('resumo_financeiro', data)
        self.assertIn('comparativo_mes_anterior', data)
        self.assertIn('arvore_modelos', data)

        # Verifica árvore desdobrável
        arvore = data['arvore_modelos']
        self.assertGreater(len(arvore), 0)
        grupo_t50 = arvore[0]
        self.assertEqual(grupo_t50['total_cilindros'], 1)

        cil_detalhes = grupo_t50['cilindros'][0]
        self.assertEqual(cil_detalhes['numero_serie'], self.cilindro_1.numero_serie_ogiva)
        self.assertIn('calendario_dias', cil_detalhes)
        # Dias decorridos até a data de hoje no mês corrente
        self.assertGreaterEqual(len(cil_detalhes['calendario_dias']), 16)

        # Garante que nenhum snapshot foi gravado no banco durante a prévia
        self.assertEqual(FechamentoFaturaEstadia.objects.filter(competencia_ano_mes='2026-10').count(), 0)

    def test_stepper_passo3_fechamento_formal_imutabilidade_e_outbox(self):
        """
        Passo 3 do Stepper: POST /clientes/api/faturas-estadia/fechar/ com persistir=True.
        Gera snapshot imutável e despacha evento para a Outbox.
        """
        from core.models import WebhookEndpoint
        WebhookEndpoint.objects.create(
            tenant=self.tenant,
            url='https://erp.hospital.com/webhook',
            eventos=['fatura.fechada', '*'],
            ativo=True
        )

        ContratoComodato.objects.create(
            cliente=self.cliente,
            vigencia_inicio=datetime.date(2026, 1, 1),
            criterio_franquia='FIFO',
            franquia_cilindros_isentos=0,
            dias_carencia_giro=5,
            valor_diaria_excedente=Decimal('4.00'),
            custo_reposicao_casco=Decimal('1800.00')
        )

        dt_entrega = timezone.make_aware(datetime.datetime(2026, 9, 1, 10, 0, 0))
        registrar_entrega_cilindro(cilindro=self.cilindro_1, cliente=self.cliente, ocorrido_em=dt_entrega, usuario=self.user_gerente)

        self.client_api.force_authenticate(user=self.user_gerente)
        payload = {
            'cliente_id': self.cliente.id,
            'competencia_ano_mes': '2026-09',
            'persistir': True
        }

        res = self.client_api.post('/clientes/api/faturas-estadia/fechar/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        fatura_id = res.data['id']

        fatura = FechamentoFaturaEstadia.objects.get(id=fatura_id)
        self.assertEqual(fatura.status_pagamento, 'FECHADA')
        self.assertGreater(fatura.itens.count(), 0)

        # Verifica outbox webhook
        log_outbox = WebhookDeliveryLog.objects.filter(
            tenant=self.tenant,
            evento__icontains='fatura'
        ).first()
        self.assertIsNotNone(log_outbox)

        # Testa imutabilidade: exclusão deve ser bloqueada
        with self.assertRaises(Exception):
            fatura.delete()

    def test_download_espelho_medicao_pdf_e_csv(self):
        """
        Downloads de Espelho de Medição em PDF e CSV.
        """
        ContratoComodato.objects.create(
            cliente=self.cliente,
            vigencia_inicio=datetime.date(2026, 1, 1),
            criterio_franquia='FIFO'
        )
        fatura = FechamentoFaturaEstadia.objects.create(
            tenant=self.tenant,
            cliente=self.cliente,
            competencia_ano_mes='2026-08',
            valor_bruto_diarias=Decimal('120.00'),
            valor_desconto_carencia=Decimal('20.00'),
            valor_desconto_franquia=Decimal('10.00'),
            valor_liquido_total=Decimal('90.00'),
            status_pagamento='FECHADA',
            fechado_por=self.user_gerente
        )
        ItemFaturaEstadia.objects.create(
            tenant=self.tenant,
            fatura=fatura,
            cilindro=self.cilindro_1,
            modelo_cilindro=self.modelo_t50.descricao,
            periodo_inicio=datetime.date(2026, 8, 1),
            periodo_fim=datetime.date(2026, 8, 31),
            dias_posse_mes=31,
            dias_carencia=5,
            dias_franquia=0,
            dias_cobraveis=26,
            diaria_aplicada=Decimal('3.50'),
            subtotal=Decimal('91.00')
        )

        self.client_api.force_authenticate(user=self.user_gerente)

        # PDF
        res_pdf = self.client_api.get(f'/clientes/api/faturas-estadia/{fatura.id}/espelho-pdf/')
        self.assertEqual(res_pdf.status_code, status.HTTP_200_OK)
        self.assertEqual(res_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(res_pdf.content.startswith(b'%PDF'))

        # CSV
        res_csv = self.client_api.get(f'/clientes/api/faturas-estadia/{fatura.id}/espelho-csv/')
        self.assertEqual(res_csv.status_code, status.HTTP_200_OK)
        self.assertEqual(res_csv['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('ESTADIA', res_csv.content.decode('utf-8'))

    def test_declarar_extravio_acao_gerencial_e_permissao(self):
        """
        Fila de Extravios: Identificação e Ação de Declarar Cilindro Extraviado.
        """
        # Entrega cilindro 2 com data retroativa de 200 dias
        hoje = timezone.now()
        dt_antiga = hoje - datetime.timedelta(days=200)
        registrar_entrega_cilindro(cilindro=self.cilindro_2, cliente=self.cliente, ocorrido_em=dt_antiga, usuario=self.user_gerente)

        ContratoComodato.objects.create(
            cliente=self.cliente,
            vigencia_inicio=datetime.date(2025, 1, 1),
            dias_limite_extravio=180
        )

        self.client_api.force_authenticate(user=self.user_gerente)

        # 1. Alertas de Extravio
        res_alertas = self.client_api.get('/clientes/api/extravios/alertas/')
        self.assertEqual(res_alertas.status_code, status.HTTP_200_OK)
        self.assertTrue(any(a['cilindro_id'] == self.cilindro_2.id for a in res_alertas.data))

        # 2. Vendedor sem permissão deve falhar ao declarar extravio
        self.client_api.force_authenticate(user=self.user_vendedor)
        res_negado = self.client_api.post('/clientes/api/extravios/declarar/', {
            'cilindro_id': self.cilindro_2.id,
            'justificativa': 'Tentativa de declaração'
        })
        self.assertEqual(res_negado.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Gerente declara extravio com sucesso
        self.client_api.force_authenticate(user=self.user_gerente)
        res_ok = self.client_api.post('/clientes/api/extravios/declarar/', {
            'cilindro_id': self.cilindro_2.id,
            'justificativa': 'Cilindro extraviado confirmado pelo cliente em auditoria física'
        })
        self.assertEqual(res_ok.status_code, status.HTTP_201_CREATED)

        self.cilindro_2.refresh_from_db()
        self.assertEqual(self.cilindro_2.status, 'EXTRAVIADO')
        self.assertEqual(ExtravioCilindroRegistro.objects.filter(cilindro=self.cilindro_2).count(), 1)

    def test_radar_preventivo_carencia_5_dias(self):
        """
        Radar Preventivo de Carência: Identifica cilindros nos últimos 5 dias de carência.
        """
        contrato = ContratoComodato.objects.create(
            cliente=self.cliente,
            vigencia_inicio=datetime.date(2026, 1, 1),
            dias_carencia_giro=30
        )

        hoje = timezone.now()
        # Entregue há 27 dias -> faltam 3 dias de carência
        dt_entrega = hoje - datetime.timedelta(days=27)
        registrar_entrega_cilindro(cilindro=self.cilindro_1, cliente=self.cliente, ocorrido_em=dt_entrega, usuario=self.user_gerente)

        self.client_api.force_authenticate(user=self.user_gerente)
        res = self.client_api.get('/clientes/api/extravios/radar-carencia/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        item = next((it for it in data if it['cilindro_id'] == self.cilindro_1.id), None)
        self.assertIsNotNone(item)
        self.assertLessEqual(item['dias_restantes_carencia'], 5)
        self.assertGreaterEqual(item['dias_restantes_carencia'], 0)
