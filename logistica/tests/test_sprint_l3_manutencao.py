import io
import uuid
from decimal import Decimal
from datetime import timedelta, date

from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from logistica.models import (
    Veiculo,
    VeiculoValorFipe,
    ManutencaoFrota,
    Fornecedor,
    PlanoManutencao,
    OrdemServico,
    OSItem,
    ChecklistModelo,
    ChecklistExecucao,
    Abastecimento
)
from logistica.services.manutencao import (
    processar_alertas_manutencao,
    calcular_indicadores_manutencao
)
from logistica.services import veiculo_apto_para_operar

User = get_user_model()


class SprintL3ManutencaoTestCase(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(
            razao_social="Empresa Logistica A Ltda",
            nome_fantasia="Log A",
            cnpj="11111111000111"
        )
        self.tenant_b = Tenant.objects.create(
            razao_social="Empresa Logistica B Ltda",
            nome_fantasia="Log B",
            cnpj="22222222000122"
        )

        self.token = set_current_tenant(self.tenant_a)

        # Usuários
        self.user_gestor = User.objects.create_user(
            username="gestor_a",
            email="gestor@empresa-a.com.br",
            password="password123"
        )
        Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_gestor,
            papel="GERENTE",
            ativo=True
        )

        self.user_motorista = User.objects.create_user(
            username="motorista_a",
            email="motorista@empresa-a.com.br",
            password="password123"
        )
        Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_motorista,
            papel="MOTORISTA",
            ativo=True
        )

        self.user_b = User.objects.create_user(
            username="gestor_b",
            email="gestor@empresa-b.com.br",
            password="password123"
        )
        Membership.objects.create(
            tenant=self.tenant_b,
            user=self.user_b,
            papel="GERENTE",
            ativo=True
        )

        # Veículo Tenant A
        self.veiculo_a = Veiculo.objects.create(
            tenant=self.tenant_a,
            placa="ABC1D23",
            modelo="Delivery 11.180",
            marca="VW",
            ano=2023,
            capacidade_carga=Decimal("5000.00"),
            odometro_atual_km=Decimal("50000.0")
        )

        # Fornecedor Tenant A
        self.fornecedor_a = Fornecedor.objects.create(
            tenant=self.tenant_a,
            nome="Oficina Central Ltda",
            documento="12.345.678/0001-90",
            telefone="(62) 3333-4444",
            email="contato@oficinacentral.com.br",
            cidade="Goiânia",
            uf="GO",
            especialidades="Mecânica Pesada Diesel, Freios"
        )

        self.client = APIClient()

    def tearDown(self):
        reset_current_tenant(self.token)

    # --------------------------------------------------------------------------
    # 1. CÁLCULO DE VENCIMENTO POR KM E DIAS (VENCE O QUE OCORRER PRIMEIRO)
    # --------------------------------------------------------------------------
    def test_calculo_vencimento_km_ou_dias_o_que_ocorrer_primeiro(self):
        """Verifica a regra de negócio: vence o que ocorrer primeiro (km ou tempo)."""
        hoje = timezone.localdate()
        base_data = hoje - timedelta(days=90)
        base_km = Decimal("40000.0")

        plano = PlanoManutencao.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            descricao="Troca de Óleo Lubrificante",
            gatilho_km=10000,
            gatilho_dias=180,
            antecedencia_alerta_km=1000,
            antecedencia_alerta_dias=15,
            ultima_execucao_data=base_data,
            ultima_execucao_km=base_km
        )

        # Caso 1: Odômetro atingiu o limite de km (50.500 km >= 40.000 + 10.000)
        # embora tempo (90 dias) esteja longe de 180 dias
        self.veiculo_a.odometro_atual_km = Decimal("50500.0")
        self.veiculo_a.save()

        st = plano.calcular_status_vencimento(data_referencia=hoje)
        self.assertTrue(st['vencido'])
        self.assertEqual(st['status'], 'Vencido')
        self.assertIn("km", st['motivo'].lower())

        # Caso 2: Km está em alerta (49.200 km >= 50.000 - 1.000)
        self.veiculo_a.odometro_atual_km = Decimal("49200.0")
        self.veiculo_a.save()
        st = plano.calcular_status_vencimento(data_referencia=hoje)
        self.assertFalse(st['vencido'])
        self.assertTrue(st['alerta'])
        self.assertEqual(st['status'], 'Alerta')

        # Caso 3: Km está baixo (42.000 km), mas tempo expirou (190 dias)
        plano.ultima_execucao_data = hoje - timedelta(days=190)
        plano.save()
        self.veiculo_a.odometro_atual_km = Decimal("42000.0")
        self.veiculo_a.save()

        st = plano.calcular_status_vencimento(data_referencia=hoje)
        self.assertTrue(st['vencido'])
        self.assertEqual(st['status'], 'Vencido')
        self.assertTrue("prazo" in st['motivo'].lower() or "dias" in st['motivo'].lower())

        # Caso 4: Em dia
        plano.ultima_execucao_data = hoje - timedelta(days=30)
        plano.save()
        self.veiculo_a.odometro_atual_km = Decimal("42000.0")
        self.veiculo_a.save()
        st = plano.calcular_status_vencimento(data_referencia=hoje)
        self.assertFalse(st['vencido'])
        self.assertFalse(st['alerta'])
        self.assertEqual(st['status'], 'Em dia')

    # --------------------------------------------------------------------------
    # 2. IDEMPOTÊNCIA DO GERADOR DE ALERTAS E COMANDO MANAGE.PY
    # --------------------------------------------------------------------------
    def test_gerador_alertas_idempotente_e_comando(self):
        """O comando gera OS preventivas e não duplica para o mesmo plano já aberto."""
        self.veiculo_a.odometro_atual_km = Decimal("51000.0")
        self.veiculo_a.save()

        plano = PlanoManutencao.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            descricao="Revisão Periódica 50.000 km",
            gatilho_km=10000,
            antecedencia_alerta_km=1000,
            ultima_execucao_km=Decimal("40000.0")
        )

        # 1ª Execução
        res1 = processar_alertas_manutencao(self.tenant_a)
        self.assertEqual(res1['os_geradas'], 1)
        self.assertEqual(OrdemServico.objects.filter(plano=plano).count(), 1)

        os_criada = OrdemServico.objects.get(plano=plano)
        self.assertEqual(os_criada.status, 'Aberta')
        self.assertEqual(os_criada.origem, 'Plano')
        self.assertEqual(os_criada.tipo, 'Preventiva')

        # 2ª Execução (Idempotência: não duplica OS aberta)
        res2 = processar_alertas_manutencao(self.tenant_a)
        self.assertEqual(res2['os_geradas'], 0)
        self.assertEqual(OrdemServico.objects.filter(plano=plano).count(), 1)

        # Execução via comando manage.py
        call_command('gerar_alertas_manutencao')
        self.assertEqual(OrdemServico.objects.filter(plano=plano).count(), 1)

    # --------------------------------------------------------------------------
    # 3. TRANSIÇÕES DE STATUS DA OS E VALIDAÇÃO ESTREITA
    # --------------------------------------------------------------------------
    def test_transicoes_status_os_e_exigencias(self):
        """Valida que transições inválidas são bloqueadas e concluir exige odômetro e custos."""
        os_obj = OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            descricao_problema="Manutenção Preventiva de Rotina",
            odometro_entrada=Decimal("50000.0")
        )

        # Aberta -> Concluída direto deve falhar
        with self.assertRaises(ValidationError):
            os_obj.status = 'Concluída'
            os_obj.odometro_saida = Decimal("50020.0")
            os_obj.save()

        os_obj.refresh_from_db()

        # Fluxo válido: Aberta -> Aprovada
        os_obj.status = 'Aprovada'
        os_obj.aprovado_por = self.user_gestor
        os_obj.save()

        # Aprovada -> Em Execução
        os_obj.status = 'Em Execução'
        os_obj.save()

        # Em Execução -> Concluída sem odômetro de saída deve falhar
        with self.assertRaises(ValidationError):
            os_obj.status = 'Concluída'
            os_obj.odometro_saida = None
            os_obj.save()

        os_obj.refresh_from_db()

        # Em Execução -> Concluída com odômetro de saída menor que entrada deve falhar
        with self.assertRaises(ValidationError):
            os_obj.status = 'Concluída'
            os_obj.odometro_saida = Decimal("49000.0")
            os_obj.save()

        os_obj.refresh_from_db()

        # Conclusão com sucesso
        os_obj.status = 'Concluída'
        os_obj.odometro_saida = Decimal("50050.0")
        os_obj.save()

        self.veiculo_a.refresh_from_db()
        self.assertEqual(self.veiculo_a.odometro_atual_km, Decimal("50050.0"))

        # Concluída não pode mais sofrer transição
        with self.assertRaises(ValidationError):
            os_obj.status = 'Cancelada'
            os_obj.save()

    # --------------------------------------------------------------------------
    # 4. ITENS DA OS E CÁLCULO CONSISTENTE DE CUSTO TOTAL
    # --------------------------------------------------------------------------
    def test_os_itens_e_soma_custo_total(self):
        """Custo total soma itens de peças, serviços e terceiros."""
        os_obj = OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            descricao_problema="Troca de amortecedores e pastilhas",
            custo_terceiros=Decimal("150.00")
        )

        # Adiciona Peça
        OSItem.objects.create(
            tenant=self.tenant_a,
            os=os_obj,
            tipo="Peça",
            descricao="Par de Amortecedores Dianteiros",
            quantidade=Decimal("2.0"),
            valor_unitario=Decimal("350.00")
        )

        # Adiciona Serviço
        OSItem.objects.create(
            tenant=self.tenant_a,
            os=os_obj,
            tipo="Serviço",
            descricao="Mão de Obra Troca Suspensão",
            quantidade=Decimal("1.0"),
            valor_unitario=Decimal("200.00")
        )

        os_obj.refresh_from_db()
        self.assertEqual(os_obj.custo_pecas, Decimal("700.00"))
        self.assertEqual(os_obj.custo_mao_de_obra, Decimal("200.00"))
        self.assertEqual(os_obj.custo_terceiros, Decimal("150.00"))
        self.assertEqual(os_obj.custo_total, Decimal("1050.00"))

    # --------------------------------------------------------------------------
    # 5. IMOBILIZAÇÃO DO VEÍCULO E REFLEXO EM VEICULO_APTO_PARA_OPERAR
    # --------------------------------------------------------------------------
    def test_imobilizacao_veiculo_e_liberacao(self):
        """OS com imobiliza_veiculo=True torna veículo inapto; concluir ou cancelar libera."""
        apto, motivos = veiculo_apto_para_operar(self.veiculo_a)
        self.assertTrue(apto)

        # Cria OS imobilizante
        os_imob = OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            tipo="Corretiva",
            descricao_problema="Quebra de Eixo Traseiro",
            imobiliza_veiculo=True,
            status="Em Execução",
            odometro_entrada=Decimal("50000.0")
        )

        self.veiculo_a.refresh_from_db()
        self.assertTrue(self.veiculo_a.tem_os_imobilizante_aberta)

        apto, motivos = veiculo_apto_para_operar(self.veiculo_a)
        self.assertFalse(apto)
        self.assertTrue(any("imobilizante" in m for m in motivos))

        # Concluir a OS libera o veículo
        os_imob.status = "Concluída"
        os_imob.odometro_saida = Decimal("50010.0")
        os_imob.save()

        self.veiculo_a.refresh_from_db()
        self.assertFalse(self.veiculo_a.tem_os_imobilizante_aberta)

        apto, motivos = veiculo_apto_para_operar(self.veiculo_a)
        self.assertTrue(apto)

    # --------------------------------------------------------------------------
    # 6. CHECKLIST REPROVADO GERA OS CORRETIVA AUTOMÁTICA
    # --------------------------------------------------------------------------
    def test_checklist_reprovado_gera_os_e_bloqueia_veiculo(self):
        """Item impeditivo Não OK gera OS corretiva de origem Checklist e imobiliza veículo."""
        respostas = [
            {"nome": "Pneus", "status": "OK", "impeditivo": True},
            {"nome": "Freios", "status": "Não OK", "impeditivo": True, "obs": "Vazamento de ar na cuíca"},
            {"nome": "Luzes", "status": "OK", "impeditivo": True}
        ]

        chk = ChecklistExecucao.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            motorista=self.user_motorista,
            odometro=Decimal("50200.0"),
            respostas=respostas,
            observacoes="Barulho forte no freio"
        )

        self.assertFalse(chk.aprovado)
        self.assertIsNotNone(chk.os_gerada)

        os_auto = chk.os_gerada
        self.assertEqual(os_auto.origem, "Checklist")
        self.assertEqual(os_auto.tipo, "Corretiva")
        self.assertTrue(os_auto.imobiliza_veiculo)
        self.assertEqual(os_auto.status, "Aberta")
        self.assertIn("Freios", os_auto.descricao_problema)

        # Veículo ficou inapto
        self.veiculo_a.refresh_from_db()
        self.assertTrue(self.veiculo_a.tem_os_imobilizante_aberta)
        apto, motivos = veiculo_apto_para_operar(self.veiculo_a)
        self.assertFalse(apto)

    # --------------------------------------------------------------------------
    # 7. INDICADORES DE MANUTENÇÃO (MTBF, MTTR, TCO, CUSTO/KM, FIPE >30%)
    # --------------------------------------------------------------------------
    def test_indicadores_manutencao_tco_e_fipe(self):
        """Calcula TCO, proporção preventiva/corretiva e alerta >30% da FIPE."""
        hoje = timezone.localdate()

        # FIPE do veículo = R$ 100.000,00
        self.veiculo_a.fipe_valor = Decimal("100000.00")
        self.veiculo_a.save()

        VeiculoValorFipe.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            valor=Decimal("100000.00"),
            mes_referencia="10/2026"
        )

        # Cria abastecimentos (L2) somando R$ 4.000,00
        Abastecimento.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            data_hora=timezone.now() - timedelta(days=60),
            odometro_km=Decimal("51000.0"),
            tipo_combustivel="Diesel S10",
            litros=Decimal("400.000"),
            valor_litro=Decimal("5.0000"),
            valor_total=Decimal("2000.00")
        )
        Abastecimento.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            data_hora=timezone.now() - timedelta(days=20),
            odometro_km=Decimal("52000.0"),
            tipo_combustivel="Diesel S10",
            litros=Decimal("400.000"),
            valor_litro=Decimal("5.0000"),
            valor_total=Decimal("2000.00")
        )

        # Cria OS Concluídas: Manutenção total = R$ 35.000,00 (> 30% da FIPE de 100k)
        os1 = OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            tipo="Corretiva",
            descricao_problema="Retífica de Motor",
            odometro_entrada=Decimal("50000.0"),
            custo_pecas=Decimal("20000.00"),
            custo_mao_de_obra=Decimal("15000.00")
        )
        os1.status = 'Aprovada'
        os1.save()
        os1.status = 'Em Execução'
        os1.save()
        os1.status = 'Concluída'
        os1.odometro_saida = Decimal("52000.0")
        os1.save()

        # Calcula indicadores
        indicadores = calcular_indicadores_manutencao(
            tenant=self.tenant_a,
            data_inicio=hoje - timedelta(days=365),
            data_fim=hoje,
            percentual_substituicao_fipe=Decimal("30.00")
        )

        # Total manutenção: 35.000
        self.assertEqual(indicadores['custo_total_manutencao'], 35000.0)

        # Alerta FIPE deve existir (35k > 30k)
        alertas = indicadores['alertas_substituicao_fipe']
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0]['placa'], "ABC1D23")
        self.assertEqual(alertas[0]['percentual_atingido'], 35.0)

        # Ranking TCO: Manutenção (35k) + Combustível (4k) = 39k
        tco_list = indicadores['ranking_tco']
        self.assertEqual(len(tco_list), 1)
        self.assertEqual(tco_list[0]['custo_manutencao'], 35000.0)
        self.assertEqual(tco_list[0]['custo_combustivel'], 4000.0)
        self.assertEqual(tco_list[0]['tco_total'], 39000.0)

    # --------------------------------------------------------------------------
    # 8. PERMISSÕES POR PERFIL (MOTORISTA VS GESTOR)
    # --------------------------------------------------------------------------
    def test_permissoes_motorista_vs_gestor(self):
        """Motorista pode reportar defeito e checklist, mas não pode aprovar/concluir OS nem mexer em planos."""
        # Motorista autenticado
        self.client.force_authenticate(user=self.user_motorista)

        # 1. Motorista abre OS de relato de defeito (Permitido)
        res_os = self.client.post('/logistica/api/ordens-servico/', {
            'veiculo': self.veiculo_a.id,
            'tipo': 'Corretiva',
            'origem': 'Motorista',
            'descricao_problema': 'Farol esquerdo queimado',
            'status': 'Aberta'
        }, format='json')
        self.assertEqual(res_os.status_code, status.HTTP_201_CREATED)
        os_id = res_os.data['id']

        # 2. Motorista tenta aprovar a OS (Bloqueado 403)
        res_aprov = self.client.post(f'/logistica/api/ordens-servico/{os_id}/aprovar/')
        self.assertEqual(res_aprov.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Motorista tenta criar plano preventivo (Bloqueado 403)
        res_plano = self.client.post('/logistica/api/planos-manutencao/', {
            'veiculo': self.veiculo_a.id,
            'descricao': 'Plano ilegal',
            'gatilho_km': 5000
        }, format='json')
        self.assertEqual(res_plano.status_code, status.HTTP_403_FORBIDDEN)

        # 4. Gestor aprova e gerencia OS (Permitido)
        self.client.force_authenticate(user=self.user_gestor)
        res_aprov_gestor = self.client.post(f'/logistica/api/ordens-servico/{os_id}/aprovar/')
        self.assertEqual(res_aprov_gestor.status_code, status.HTTP_200_OK)

    # --------------------------------------------------------------------------
    # 9. ISOLAMENTO MULTI-TENANT
    # --------------------------------------------------------------------------
    def test_isolamento_multi_tenant(self):
        """Usuário do Tenant B não visualiza nem altera OS ou planos do Tenant A."""
        os_a = OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            descricao_problema="Segredo industrial Tenant A"
        )

        self.client.force_authenticate(user=self.user_b)
        res = self.client.get(f'/logistica/api/ordens-servico/{os_a.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        res_list = self.client.get('/logistica/api/ordens-servico/')
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in res_list.data.get('results', res_list.data)]
        self.assertNotIn(os_a.id, ids)

    # --------------------------------------------------------------------------
    # 10. MIGRAÇÃO REVERSÍVEL DE MANUTENCAOFROTA
    # --------------------------------------------------------------------------
    def test_migracao_legada_manutencao_e_reversao(self):
        import importlib
        from django.apps import apps
        mig_mod = importlib.import_module('logistica.migrations.0013_migrar_manutencaofrota_para_ordemservico')
        migrar_manutencao_para_os = mig_mod.migrar_manutencao_para_os
        reverter_migracao_os = mig_mod.reverter_migracao_os

        m_legada = ManutencaoFrota.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            descricao="Troca de correia dentada histórica",
            custo=Decimal("450.00"),
            data_manutencao=date(2025, 5, 10),
            status="Concluída"
        )

        # Executa migração
        migrar_manutencao_para_os(apps, None)

        os_migrada = OrdemServico.objects.filter(numero=f"OS-LEGADO-{m_legada.id}").first()
        self.assertIsNotNone(os_migrada)
        self.assertEqual(os_migrada.status, "Concluída")
        self.assertEqual(os_migrada.custo_total, Decimal("450.00"))
        self.assertIn("Troca de correia", os_migrada.descricao_problema)
        self.assertEqual(os_migrada.veiculo, self.veiculo_a)

        # Executa reversão
        reverter_migracao_os(apps, None)
        self.assertFalse(OrdemServico.objects.filter(numero=f"OS-LEGADO-{m_legada.id}").exists())

        # Tabela antiga ManutencaoFrota NÃO foi apagada
        self.assertTrue(ManutencaoFrota.objects.filter(id=m_legada.id).exists())
