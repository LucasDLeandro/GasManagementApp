from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant
from logistica.models import Veiculo, Rota, Entrega

User = get_user_model()


class RBACMatrixSprint6TestCase(APITestCase):
    """
    Teste automatizado da Matriz Papel × Endpoint (D6 - Fase 0).
    Verifica que:
    1. Romaneio (concluir-romaneio) e Sync Offline: autorizados apenas para MOTORISTA e ADMIN.
    2. Exportações ERP (faturas e entregas) e Webhooks: autorizados apenas para ADMIN e GERENTE.
    3. Todos os papéis não autorizados recebem 403 Forbidden.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            cnpj='12.345.678/0001-90',
            razao_social='Matriz RBAC Gás Ltda',
            nome_fantasia='RBAC Gás'
        )
        self.token = set_current_tenant(self.tenant)

        # Configura um usuário para cada um dos 6 papéis do Membership
        self.users = {}
        for papel, _ in Membership.PAPEL_CHOICES:
            u = User.objects.create_user(
                username=f'user_{papel.lower()}',
                password='password123',
                email=f'{papel.lower()}@rbacgas.com.br'
            )
            Membership.objects.create(
                user=u,
                tenant=self.tenant,
                papel=papel,
                ativo=True
            )
            self.users[papel] = u

        # Veículo, Rota e Entrega para testes de endpoints de romaneio
        self.veiculo = Veiculo.objects.create(
            tenant=self.tenant,
            placa='RBC-2026',
            modelo='Ford Cargo',
            marca='Ford',
            ano=2024,
            capacidade_carga=Decimal('1000.00'),
            status='Ativo'
        )
        self.rota = Rota.objects.create(
            tenant=self.tenant,
            nome='Rota Hospitalar Central',
            origem='Centro de Distribuição',
            destino='Setor Hospitalar Sul',
            distancia_km=Decimal('25.50'),
            tempo_estimado_horas=Decimal('1.50')
        )
        self.entrega = Entrega.objects.create(
            tenant=self.tenant,
            veiculo=self.veiculo,
            rota=self.rota,
            motorista=self.users['MOTORISTA'],
            data_saida=timezone.now(),
            status='Em Rota'
        )

    def test_matriz_rbac_concluir_romaneio(self):
        """
        Endpoint: POST /logistica/api/entregas/<id>/concluir-romaneio/
        Permitidos: MOTORISTA, ADMIN
        Negados (403): GERENTE, OPERADOR_PATIO, VENDEDOR, RESPONSAVEL_TECNICO
        """
        endpoint = f'/logistica/api/entregas/{self.entrega.id}/concluir-romaneio/'
        autorizados = {'MOTORISTA', 'ADMIN'}

        for papel, user in self.users.items():
            self.client.force_authenticate(user=user)
            resp = self.client.post(endpoint, {}, format='json')

            if papel in autorizados:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_200_OK,
                    f"Papel autorizado '{papel}' foi bloqueado com {resp.status_code} em concluir-romaneio."
                )
            else:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"Papel não autorizado '{papel}' conseguiu acessar concluir-romaneio (status {resp.status_code})."
                )

    def test_matriz_rbac_sync_offline(self):
        """
        Endpoint: POST /api/movimentacoes/sync-offline/
        Permitidos: MOTORISTA, ADMIN
        Negados (403): GERENTE, OPERADOR_PATIO, VENDEDOR, RESPONSAVEL_TECNICO
        """
        endpoint = '/api/movimentacoes/sync-offline/'
        autorizados = {'MOTORISTA', 'ADMIN'}
        payload = {'itens': []}

        for papel, user in self.users.items():
            self.client.force_authenticate(user=user)
            resp = self.client.post(endpoint, payload, format='json')

            if papel in autorizados:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_200_OK,
                    f"Papel autorizado '{papel}' foi bloqueado com {resp.status_code} no sync-offline."
                )
            else:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"Papel não autorizado '{papel}' conseguiu acessar sync-offline (status {resp.status_code})."
                )

    def test_matriz_rbac_webhook_endpoints(self):
        """
        Endpoint: GET /api/webhooks/
        Permitidos: ADMIN, GERENTE
        Negados (403): MOTORISTA, OPERADOR_PATIO, VENDEDOR, RESPONSAVEL_TECNICO
        """
        endpoint = '/api/webhooks/'
        autorizados = {'ADMIN', 'GERENTE'}

        for papel, user in self.users.items():
            self.client.force_authenticate(user=user)
            resp = self.client.get(endpoint)

            if papel in autorizados:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_200_OK,
                    f"Papel autorizado '{papel}' foi bloqueado com {resp.status_code} em webhooks."
                )
            else:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"Papel não autorizado '{papel}' conseguiu acessar webhooks (status {resp.status_code})."
                )

    def test_matriz_rbac_erp_export_faturas(self):
        """
        Endpoint: GET /api/erp/faturas/
        Permitidos: ADMIN, GERENTE
        Negados (403): MOTORISTA, OPERADOR_PATIO, VENDEDOR, RESPONSAVEL_TECNICO
        """
        endpoint = '/api/erp/faturas/'
        autorizados = {'ADMIN', 'GERENTE'}

        for papel, user in self.users.items():
            self.client.force_authenticate(user=user)
            resp = self.client.get(endpoint)

            if papel in autorizados:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_200_OK,
                    f"Papel autorizado '{papel}' foi bloqueado com {resp.status_code} em erp/faturas."
                )
            else:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"Papel não autorizado '{papel}' conseguiu acessar erp/faturas (status {resp.status_code})."
                )

    def test_matriz_rbac_erp_export_entregas(self):
        """
        Endpoint: GET /api/erp/entregas/
        Permitidos: ADMIN, GERENTE
        Negados (403): MOTORISTA, OPERADOR_PATIO, VENDEDOR, RESPONSAVEL_TECNICO
        """
        endpoint = '/api/erp/entregas/'
        autorizados = {'ADMIN', 'GERENTE'}

        for papel, user in self.users.items():
            self.client.force_authenticate(user=user)
            resp = self.client.get(endpoint)

            if papel in autorizados:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_200_OK,
                    f"Papel autorizado '{papel}' foi bloqueado com {resp.status_code} em erp/entregas."
                )
            else:
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"Papel não autorizado '{papel}' conseguiu acessar erp/entregas (status {resp.status_code})."
                )
