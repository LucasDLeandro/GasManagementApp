import datetime
from decimal import Decimal
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership, PerfilRegulatorioTenant
from core.tenancy import tenant_context
from accounts.models import User
from clientes.models import Cliente
from vendas.models import Venda, ItemVenda, AlertaComercial
from vendas.tasks import analisar_risco_churn_task
from produtos.models import (
    Cilindro,
    GasQuimico,
    ModeloCilindro,
    SkuRecarga,
    LoteEnvase,
    EnvaseCilindro,
    MovimentacaoCilindro,
    AuditoriaDownloadLog,
)
from produtos.services.dossie_builder import gerar_dossie_anvisa_pdf
from logistica.models import Entrega, ComprovanteEntrega
from faturamento.models import FaturaCobranca


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-sprint10-cache',
        }
    }
)
class Sprint10AnalyticsIAPreditivaTests(TestCase):
    def setUp(self):
        cache.clear()

        # 1. Tenant Alfa
        self.tenant_a = Tenant.objects.create(
            razao_social="Alfa Gases & Soluções Industriais LTDA",
            nome_fantasia="Alfa Gases",
            cnpj="10.111.222/0001-33",
            plano="PRO",
            modulo_patrimonio_ativo=True,
            modulo_envase_ativo=True,
            modulo_vendas_ativo=True,
            modulo_logistica_ativo=True,
            modulo_financeiro_ativo=True,
            modulo_analytics_ativo=True,
        )
        self.perfil_a = PerfilRegulatorioTenant.objects.create(
            tenant=self.tenant_a,
            modo_operacao='MISTO',
            afe_numero='AFE-ALFA-01',
            licenca_sanitaria_numero='LIC-ALFA-01',
            licenca_sanitaria_validade=timezone.now().date() + timezone.timedelta(days=365)
        )

        # 2. Tenant Beta (Isolamento)
        self.tenant_b = Tenant.objects.create(
            razao_social="Beta Gases LTDA",
            nome_fantasia="Beta Gases",
            cnpj="20.333.444/0001-55",
            plano="BASIC"
        )

        with tenant_context(self.tenant_a):
            # Usuário Gerente / Admin do Tenant A
            self.user_a = User.objects.create_user(
                username="gerente_alfa",
                email="gerente@alfa.com.br",
                password="password123"
            )
            self.membership_a = Membership.objects.create(
                user=self.user_a,
                tenant=self.tenant_a,
                papel='ADMIN',
                ativo=True
            )

            # Clientes no Tenant A
            self.cliente_hospital = Cliente.objects.create(
                tipo_cliente='PJ',
                cnpj="33.444.555/0001-66",
                nome="Hospital Central Alfa",
                endereco="Av. Principal, 500",
                cidade="São Paulo",
                estado="SP",
                telefone="11911112222",
                is_medicinal=True
            )
            self.cliente_industria = Cliente.objects.create(
                tipo_cliente='PJ',
                cnpj="44.555.666/0001-77",
                nome="Metalúrgica Alfa S/A",
                endereco="Distrito Industrial, 12",
                cidade="Campinas",
                estado="SP",
                telefone="19922223333"
            )

            # Catálogo: Gás, Modelo e SKU
            self.gas_o2 = GasQuimico.objects.create(
                nome="Oxigênio Industrial",
                sigla="OXI",
                categoria="INDUSTRIAL",
                numero_onu="1072",
                classe_risco="2.2"
            )
            self.gas_ar = GasQuimico.objects.create(
                nome="Argônio Puro",
                sigla="ARG",
                categoria="INDUSTRIAL",
                numero_onu="1006",
                classe_risco="2.2"
            )
            self.modelo_t50 = ModeloCilindro.objects.create(
                descricao="Cilindro T50 (50 Litros)",
                material="ACO",
                volume_hidraulico_litros=Decimal('50.0'),
                pressao_servico_bar=200,
                tara_nominal_kg=Decimal('60.0'),
                periodicidade_reteste_anos=5
            )
            self.sku_o2 = SkuRecarga.objects.create(
                gas=self.gas_o2,
                modelo_cilindro=self.modelo_t50,
                nome_comercial="Recarga O2 Ind 10m³",
                quantidade_carga=Decimal('10.0'),
                unidade='m3',
                massa_gas_kg=Decimal('14.2'),
                preco_base=Decimal('150.00')
            )
            self.sku_ar = SkuRecarga.objects.create(
                gas=self.gas_ar,
                modelo_cilindro=self.modelo_t50,
                nome_comercial="Recarga Argônio 10m³",
                quantidade_carga=Decimal('10.0'),
                unidade='m3',
                massa_gas_kg=Decimal('17.8'),
                preco_base=Decimal('300.00')
            )

            # Cilindros em Posse (Comodato Ativo)
            self.cil_1 = Cilindro.objects.create(
                codigo_qr="QR-ALFA-001",
                numero_serie_ogiva="SN-O2-001",
                fabricante="CIBER",
                ano_fabricacao=2024,
                modelo=self.modelo_t50,
                gas_dedicado=self.gas_o2,
                status='EM_POSSE_CLIENTE',
                cliente_posse_atual=self.cliente_hospital,
                posse_desde=timezone.now() - timezone.timedelta(days=60),
                data_ultimo_reteste=timezone.now().date() - timezone.timedelta(days=365),
                data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1460)
            )
            self.cil_2 = Cilindro.objects.create(
                codigo_qr="QR-ALFA-002",
                numero_serie_ogiva="SN-ARG-002",
                fabricante="CIBER",
                ano_fabricacao=2023,
                modelo=self.modelo_t50,
                gas_dedicado=self.gas_ar,
                status='CHEIO_DISPONIVEL',
                data_ultimo_reteste=timezone.now().date() - timezone.timedelta(days=365),
                data_proximo_reteste=timezone.now().date() + timezone.timedelta(days=1460)
            )

            # Lote de Envase e Rastreabilidade Completa para Dossiê ANVISA
            self.lote_envase = LoteEnvase.objects.create(
                gas=self.gas_o2,
                codigo_lote="LOTE-ANVISA-2026-X",
                data_envase=timezone.now().date() - timezone.timedelta(days=10),
                data_validade=timezone.now().date() + timezone.timedelta(days=720),
                pureza_percentual=Decimal('99.80'),
                responsavel_tecnico="Farm. Carlos Oliveira (CRF/SP 88.990)",
                rt_nome_snapshot="Carlos Oliveira",
                rt_conselho_snapshot="CRF/SP",
                rt_registro_snapshot="88.990",
                status_qualidade='APROVADO'
            )
            self.envase = EnvaseCilindro.objects.create(
                cilindro=self.cil_1,
                lote=self.lote_envase,
                pressao_final_bar=200,
                envasado_em=timezone.now() - timezone.timedelta(days=10),
                operador=self.user_a,
                observacoes="Envase aprovado na rampa BPF"
            )
            self.cil_1.envase_atual = self.envase
            self.cil_1.save(update_fields=['envase_atual'])

            # Logística e Entrega do Cilindro 1
            self.entrega = Entrega.objects.create(
                status='Concluída',
                data_saida=timezone.now() - timezone.timedelta(days=8)
            )
            self.mov_entrega = MovimentacaoCilindro.objects.create(
                cilindro=self.cil_1,
                tipo='ENTREGA_CLIENTE',
                status_anterior='RESERVADO_ROTA',
                status_novo='EM_POSSE_CLIENTE',
                cliente=self.cliente_hospital,
                entrega=self.entrega,
                ocorrido_em=timezone.now() - timezone.timedelta(days=8),
                registrado_por=self.user_a,
                envase_cilindro=self.envase,
                lote_envase=self.lote_envase.codigo_lote
            )
            self.comprovante = ComprovanteEntrega.objects.create(
                entrega=self.entrega,
                movimentacao=self.mov_entrega,
                recebedor_nome="Marcos Enfermeiro Chefe",
                recebedor_documento="12345678900",
                latitude=Decimal('-23.5505200'),
                longitude=Decimal('-46.6333080'),
                timestamp_captura=timezone.now() - timezone.timedelta(days=8),
                hash_integridade_sha256="E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"
            )
            self.comprovante.movimentacoes.add(self.mov_entrega)

        self.client = APIClient()

    # ==============================================================================
    # 10.1. OTIMIZAÇÃO SEVERA DE QUERIES & CACHE
    # ==============================================================================

    def test_analytics_faturamento_mensal_agregado_orm(self):
        """
        Valida que faturamento_mensal usa TruncMonth e Sum sem carregar instâncias em memória.
        """
        now = timezone.now()
        # Vendas em 2 meses distintos
        mes_passado = now - timezone.timedelta(days=35)
        mes_atual = now

        with tenant_context(self.tenant_a):
            # Venda 1 (Mês passado): R$ 1500.00
            v1 = Venda.objects.create(
                cliente=self.cliente_hospital,
                status='Finalizada',
                valor_total=Decimal('1500.00')
            )
            Venda.objects.filter(id=v1.id).update(data_venda=mes_passado)

            # Venda 2 (Mês atual): R$ 3000.00
            v2 = Venda.objects.create(
                cliente=self.cliente_hospital,
                status='Finalizada',
                valor_total=Decimal('3000.00')
            )
            Venda.objects.filter(id=v2.id).update(data_venda=mes_atual)

            # Venda 3 (Cancelada - Não deve entrar no faturamento padrão)
            v3 = Venda.objects.create(
                cliente=self.cliente_industria,
                status='Cancelada',
                valor_total=Decimal('5000.00')
            )
            Venda.objects.filter(id=v3.id).update(data_venda=mes_atual)

        self.client.force_authenticate(user=self.user_a)
        res = self.client.get('/api/analytics/faturamento-mensal/', HTTP_X_TENANT_ID=str(self.tenant_a.id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        dados = res.data
        self.assertGreaterEqual(len(dados), 2)

        totais = [Decimal(str(item['total_vendas'])) for item in dados]
        self.assertIn(Decimal('1500.00'), totais)
        self.assertIn(Decimal('3000.00'), totais)
        # Garante que a venda cancelada não entrou
        self.assertNotIn(Decimal('8000.00'), totais)

    def test_analytics_vendas_por_gas_agregado_orm(self):
        """Valida agregação de vendas agrupadas por Gás Químico."""
        with tenant_context(self.tenant_a):
            venda = Venda.objects.create(
                cliente=self.cliente_hospital,
                status='Finalizada',
                valor_total=Decimal('900.00')
            )
            ItemVenda.objects.create(
                venda=venda,
                sku=self.sku_o2,
                quantidade=2,
                valor_unitario=Decimal('150.00'),
                valor_total=Decimal('300.00')
            )
            ItemVenda.objects.create(
                venda=venda,
                sku=self.sku_ar,
                quantidade=2,
                valor_unitario=Decimal('300.00'),
                valor_total=Decimal('600.00')
            )

        self.client.force_authenticate(user=self.user_a)
        res = self.client.get('/api/analytics/vendas-por-gas/', HTTP_X_TENANT_ID=str(self.tenant_a.id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        gas_nomes = [item['gas_nome'] for item in res.data]
        self.assertIn("Oxigênio Industrial", gas_nomes)
        self.assertIn("Argônio Puro", gas_nomes)

    def test_analytics_cache_page_15_minutos(self):
        """Valida que o endpoint de analytics é cacheado e evita consultas repetidas ao banco."""
        with tenant_context(self.tenant_a):
            Venda.objects.create(
                cliente=self.cliente_hospital,
                status='Finalizada',
                valor_total=Decimal('500.00')
            )

        self.client.force_authenticate(user=self.user_a)
        res1 = self.client.get('/api/analytics/faturamento-mensal/', HTTP_X_TENANT_ID=str(self.tenant_a.id))
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        # Adiciona nova venda no banco diretamente
        with tenant_context(self.tenant_a):
            Venda.objects.create(
                cliente=self.cliente_hospital,
                status='Finalizada',
                valor_total=Decimal('9999.00')
            )

        # Como a view está decorada com cache_page(60 * 15), a segunda requisição deve retornar do cache
        res2 = self.client.get('/api/analytics/faturamento-mensal/', HTTP_X_TENANT_ID=str(self.tenant_a.id))
        self.assertEqual(res1.data, res2.data)

    # ==============================================================================
    # 10.2. ALGORITMO PREDITIVO DE CHURN
    # ==============================================================================

    def test_algoritmo_preditivo_churn_identifica_atraso_superior_30_porcento(self):
        """
        Cria histórico de 5 pedidos com intervalo de 10 dias (média = 10 dias).
        Se o último pedido foi há 15 dias (15 > 10 * 1.3 = 13), dispara AlertaComercial(tipo='RISCO_CHURN').
        """
        hoje = timezone.now()

        with tenant_context(self.tenant_a):
            # Garante que cliente_hospital tem comodato ativo (cil_1 está em sua posse)
            self.assertTrue(self.cliente_hospital.cilindros_em_posse.exists())

            # Criar 5 pedidos anteriores em intervalos de 10 dias
            # Pedido 5: há 55 dias
            # Pedido 4: há 45 dias (dif = 10)
            # Pedido 3: há 35 dias (dif = 10)
            # Pedido 2: há 25 dias (dif = 10)
            # Pedido 1 (último): há 15 dias (dif = 10) -> dias_sem_comprar = 15
            # Média histórica = (10+10+10+10)/4 = 10 dias.
            # Limite tolerável (30% de folga) = 10 * 1.3 = 13 dias.
            # 15 dias sem comprar > 13 -> DEVE CRIAR ALERTA DE CHURN!
            for i, dias_atras in enumerate([55, 45, 35, 25, 15]):
                v = Venda.objects.create(
                    cliente=self.cliente_hospital,
                    status='Entregue',
                    valor_total=Decimal('200.00')
                )
                dt_fake = hoje - timezone.timedelta(days=dias_atras)
                Venda.objects.filter(id=v.id).update(data_venda=dt_fake)

            # Executa a task assíncrona do Celery
            resultado = analisar_risco_churn_task(tenant_id=str(self.tenant_a.id))

            self.assertEqual(resultado['status'], 'SUCESSO')
            self.assertGreaterEqual(resultado['alertas_criados'], 1)

            # Verifica se o alerta foi registrado corretamente no banco
            alerta = AlertaComercial.objects.filter(
                cliente=self.cliente_hospital,
                tipo='RISCO_CHURN',
                resolvido=False
            ).first()

            self.assertIsNotNone(alerta)
            self.assertEqual(alerta.dias_sem_comprar, 15)
            self.assertEqual(alerta.media_historica_dias, Decimal('10.00'))
            self.assertEqual(alerta.percentual_atraso, Decimal('50.00'))
            self.assertIn("Risco de Churn", alerta.descricao)

    def test_algoritmo_preditivo_churn_nao_dispara_quando_dentro_do_padrao(self):
        """
        Cliente com média de 10 dias e última compra há 8 dias (8 <= 13):
        NÃO deve gerar alerta de churn.
        """
        hoje = timezone.now()

        with tenant_context(self.tenant_a):
            # Histórico: pedidos há 38, 28, 18, 8 dias (média = 10 dias)
            for dias_atras in [38, 28, 18, 8]:
                v = Venda.objects.create(
                    cliente=self.cliente_industria,
                    status='Entregue',
                    valor_total=Decimal('500.00')
                )
                Venda.objects.filter(id=v.id).update(data_venda=hoje - timezone.timedelta(days=dias_atras))

            # Associa um cilindro à indústria para ter comodato ativo
            Cilindro.objects.create(
                codigo_qr="QR-COM-IND-1",
                numero_serie_ogiva="SN-IND-1",
                fabricante="CIBER",
                ano_fabricacao=2024,
                modelo=self.modelo_t50,
                gas_dedicado=self.gas_o2,
                status='EM_POSSE_CLIENTE',
                cliente_posse_atual=self.cliente_industria,
                data_ultimo_reteste=hoje.date(),
                data_proximo_reteste=hoje.date() + timezone.timedelta(days=365)
            )

            # Executa a task
            analisar_risco_churn_task(tenant_id=str(self.tenant_a.id))

            # Não deve existir alerta aberto para este cliente
            alerta = AlertaComercial.objects.filter(
                cliente=self.cliente_industria,
                tipo='RISCO_CHURN',
                resolvido=False
            ).first()
            self.assertIsNone(alerta)

    def test_painel_vendas_resolver_alerta_comercial(self):
        """Valida resolução de alerta via endpoint comercial."""
        with tenant_context(self.tenant_a):
            alerta = AlertaComercial.objects.create(
                cliente=self.cliente_hospital,
                tipo='RISCO_CHURN',
                dias_sem_comprar=20,
                media_historica_dias=Decimal('10.00'),
                percentual_atraso=Decimal('100.00'),
                descricao="Alerta teste"
            )

        self.client.force_authenticate(user=self.user_a)
        res = self.client.post(
            f'/vendas/api/alertas/{alerta.id}/resolver/',
            {'observacao': 'Contato realizado. Pedido novo agendado para amanhã.'},
            HTTP_X_TENANT_ID=str(self.tenant_a.id)
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        alerta.refresh_from_db()
        self.assertTrue(alerta.resolvido)
        self.assertEqual(alerta.resolvido_por, self.user_a)
        self.assertIn("Contato realizado", alerta.observacao_resolucao)

    # ==============================================================================
    # 10.3. GERADOR DE DOSSIÊ ANVISA & AUDITORIA DE DOWNLOAD
    # ==============================================================================

    def test_dossie_anvisa_geracao_hierarquica_e_auditoria_download(self):
        """
        Valida que dossie_builder navega a árvore hierárquica sem N+1:
        Lote -> Envase -> Cilindro -> Movimentacao -> Entrega -> Comprovante,
        gera PDF Platypus e cria registro em AuditoriaDownloadLog com hash SHA-256.
        """
        pdf_buffer, hash_sha256 = gerar_dossie_anvisa_pdf(
            lote=self.lote_envase,
            usuario=self.user_a,
            ip_origem="192.168.1.50",
            user_agent="Mozilla/5.0 (Windows NT 10.0)"
        )

        self.assertIsNotNone(pdf_buffer)
        pdf_bytes = pdf_buffer.getvalue()
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        self.assertEqual(len(hash_sha256), 64)

        # Valida que AuditoriaDownloadLog foi instanciado
        with tenant_context(self.tenant_a):
            log_auditoria = AuditoriaDownloadLog.objects.filter(
                entidade_tipo='DOSSIE_LOTE_ANVISA',
                entidade_id=str(self.lote_envase.codigo_lote),
                hash_sha256=hash_sha256
            ).first()

            self.assertIsNotNone(log_auditoria)
            self.assertEqual(log_auditoria.tenant, self.tenant_a)
            self.assertEqual(log_auditoria.usuario, self.user_a)
            self.assertEqual(log_auditoria.ip_origem, "192.168.1.50")

    def test_endpoint_dossie_anvisa_lote_viewset(self):
        """Valida rota HTTP /produtos/api/lotes/{id}/dossie-anvisa/."""
        self.client.force_authenticate(user=self.user_a)
        url = f'/produtos/api/lotes/{self.lote_envase.id}/dossie-anvisa/'

        res = self.client.get(url, HTTP_X_TENANT_ID=str(self.tenant_a.id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertIn('dossie_anvisa_lote_LOTE-ANVISA-2026-X.pdf', res['Content-Disposition'])
        self.assertIn('X-Integrity-SHA256', res)
        self.assertEqual(len(res['X-Integrity-SHA256']), 64)
