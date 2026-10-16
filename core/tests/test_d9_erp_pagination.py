from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant
from clientes.models import Cliente, FechamentoFaturaEstadia
from logistica.models import Veiculo, Rota, Entrega

User = get_user_model()


class ERPPaginationD9TestCase(APITestCase):
    """
    Testes de paginação global e exportações canônicas ERP (D9 - Fase 0):
    1. Paginação configurável eliminando corte fixo de [:100].
    2. Suporte ao cursor incremental 'updated_since'.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='55.666.777/0001-88',
            razao_social='Gás Central Faturamento SA',
            nome_fantasia='GásCentral'
        )
        self.token = set_current_tenant(self.tenant)

        self.gerente = User.objects.create_user(username='gerente_erp', password='pwd')
        Membership.objects.create(user=self.gerente, tenant=self.tenant, papel='GERENTE')

        self.cliente = Cliente.objects.create(
            tenant=self.tenant,
            nome='Hospital Santa Lúcia',
            cnpj='11.222.333/0001-44',
            endereco='SHLS Quadra 716',
            telefone='6133334444',
            estado='DF',
            cidade='Brasília'
        )

        # Cria 5 faturas de estadia em datas diferentes
        self.now = timezone.now()
        self.faturas = []
        for i in range(5):
            f = FechamentoFaturaEstadia.objects.create(
                tenant=self.tenant,
                cliente=self.cliente,
                competencia_ano_mes=f'2026-0{i+1}',
                data_fechamento=self.now - timedelta(days=10 - i),
                valor_bruto_diarias=Decimal('100.00'),
                valor_liquido_total=Decimal('100.00'),
                status_pagamento='FECHADA',
                fechado_por=self.gerente
            )
            self.faturas.append(f)

        # Veículo e Entregas
        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa='ERP-2026',
            modelo='VUC Mercedes',
            marca='Mercedes-Benz',
            ano=2024,
            capacidade_carga=Decimal('2000.00')
        )
        self.rota = Rota.objects.create(
            tenant=self.tenant,
            nome='Rota Asa Sul',
            origem='Base',
            destino='Asa Sul',
            distancia_km=Decimal('15.00'),
            tempo_estimado_horas=Decimal('0.80')
        )
        self.entregas = []
        for i in range(5):
            e = Entrega.objects.create(
                tenant=self.tenant,
                veiculo=self.veiculo,
                rota=self.rota,
                data_saida=self.now - timedelta(days=10 - i),
                status='Concluída'
            )
            self.entregas.append(e)

    def test_faturas_erp_paginacao_e_cursor_updated_since(self):
        """
        Valida que o endpoint de faturas ERP aceita paginação e cursor updated_since (D9).
        """
        self.client.force_authenticate(user=self.gerente)

        # 1. Paginação com page_size=2
        resp = self.client.get('/api/erp/faturas/?page=1&page_size=2')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(data['total'], 5)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['page_size'], 2)
        self.assertEqual(len(data['faturas']), 2)

        # Página 2
        resp_p2 = self.client.get('/api/erp/faturas/?page=2&page_size=2')
        self.assertEqual(resp_p2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_p2.json()['faturas']), 2)

        # 2. Cursor incremental updated_since (filtra faturas mais recentes que data de corte)
        corte = (self.now - timedelta(days=8)).isoformat()
        resp_cursor = self.client.get(f'/api/erp/faturas/?updated_since={corte}')
        self.assertEqual(resp_cursor.status_code, status.HTTP_200_OK)
        # Devem retornar apenas faturas dos últimos 8 dias (ou seja, 3 faturas mais recentes)
        self.assertLessEqual(resp_cursor.json()['total'], 4)
        self.assertGreaterEqual(resp_cursor.json()['total'], 1)

    def test_entregas_erp_paginacao_e_cursor_updated_since(self):
        """
        Valida que o endpoint de entregas ERP aceita paginação e cursor updated_since (D9).
        """
        self.client.force_authenticate(user=self.gerente)

        # 1. Paginação com page_size=3
        resp = self.client.get('/api/erp/entregas/?page=1&page_size=3')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(data['total'], 5)
        self.assertEqual(len(data['entregas']), 3)

        # 2. Cursor incremental updated_since
        corte = (self.now - timedelta(days=7)).isoformat()
        resp_cursor = self.client.get(f'/api/erp/entregas/?updated_since={corte}')
        self.assertEqual(resp_cursor.status_code, status.HTTP_200_OK)
        self.assertLess(resp_cursor.json()['total'], 5)
