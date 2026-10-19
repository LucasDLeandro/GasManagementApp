import uuid
from decimal import Decimal
from datetime import timedelta, date

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework import status

from core.models import Tenant, Membership
from core.tenancy import set_current_tenant, reset_current_tenant
from produtos.models import Produto
from logistica.models import (
    Veiculo,
    VeiculoValorFipe,
    ApoliceSeguro,
    ApoliceCobertura,
    ApoliceVeiculo,
    ConfiguracaoSeguros,
    Sinistro,
    SinistroEvento,
    SinistroAnexo,
    SinistroItemCarga,
    OrdemServico,
    Entrega
)
from logistica.services.seguros_sinistros import (
    criar_sinistro,
    transicionar_status_sinistro,
    vincular_ou_criar_os_sinistro,
    processar_ajuste_estoque_sinistro_carga,
    liberar_veiculo_sinistrado,
    obter_indicadores_sinistralidade
)
from logistica.services import veiculo_apto_para_operar

User = get_user_model()


class SprintL5SegurosSinistrosTestCase(TestCase):
    def setUp(self):
        # 1. Tenants
        self.tenant_a = Tenant.objects.create(
            razao_social="Distribuidora Nacional de Gas Ltda",
            nome_fantasia="Gas Nacional",
            cnpj="11222333000199"
        )
        self.tenant_b = Tenant.objects.create(
            razao_social="Gas Express do Cerrado Ltda",
            nome_fantasia="Gas Cerrado",
            cnpj="99888777000111"
        )

        self.token = set_current_tenant(self.tenant_a)

        # 2. Usuários
        self.user_admin = User.objects.create_user(
            username="admin_a",
            email="admin@gasnacional.com.br",
            password="adminpassword123",
            first_name="Admin",
            last_name="Frota"
        )
        Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_admin,
            papel="ADMIN",
            ativo=True
        )

        self.user_motorista = User.objects.create_user(
            username="motorista_pedro",
            email="pedro@gasnacional.com.br",
            password="driverpassword123",
            first_name="Pedro",
            last_name="Alcantara"
        )
        Membership.objects.create(
            tenant=self.tenant_a,
            user=self.user_motorista,
            papel="MOTORISTA",
            ativo=True
        )

        self.user_b = User.objects.create_user(
            username="admin_b",
            email="admin@gascerrado.com.br",
            password="passb123"
        )
        Membership.objects.create(
            tenant=self.tenant_b,
            user=self.user_b,
            papel="ADMIN",
            ativo=True
        )

        # 3. Veículos
        self.veiculo_a = Veiculo.objects.create(
            tenant=self.tenant_a,
            placa="BRA2E19",
            marca="Mercedes-Benz",
            modelo="Accelo 1016",
            ano=2021,
            ano_fabricacao=2021,
            ano_modelo=2022,
            capacidade_carga=Decimal("5000.00"),
            status="Disponível",
            status_ativo="Ativo",
            odometro_atual_km=Decimal("45000.00")
        )

        self.veiculo_b = Veiculo.objects.create(
            tenant=self.tenant_b,
            placa="GOI9988",
            marca="Volkswagen",
            modelo="Delivery 9.170",
            ano=2020,
            ano_fabricacao=2020,
            ano_modelo=2021,
            capacidade_carga=Decimal("4000.00"),
            status="Disponível",
            status_ativo="Ativo",
            odometro_atual_km=Decimal("30000.00")
        )

        # 4. Produtos e Estoque (para testes de perda de carga)
        self.produto_glp = Produto.objects.create(
            tenant=self.tenant_a,
            nome="GLP P13 - Botijão de Gás Cozinha 13kg",
            categoria="Industrial",
            capacidade=Decimal("13.00"),
            unidade_medida="kg",
            preco=Decimal("110.00"),
            estoque=50
        )

        # 5. Entrega
        self.entrega = Entrega.objects.create(
            tenant=self.tenant_a,
            motorista=self.user_motorista,
            veiculo=self.veiculo_a,
            status="Em Rota",
            data_saida=timezone.now()
        )

        # 6. Clientes de API
        self.client_admin = APIClient()
        self.client_admin.force_authenticate(user=self.user_admin)

        self.client_motorista = APIClient()
        self.client_motorista.force_authenticate(user=self.user_motorista)

        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)

    def tearDown(self):
        reset_current_tenant(self.token)

    # =========================================================================
    # TESTE 1: Apólices, Coberturas, Vigência e Alertas (60/30/15 dias)
    # =========================================================================
    def test_01_apolice_e_coberturas_e_alertas_vigencia(self):
        hoje = timezone.now().date()
        apolice = ApoliceSeguro.objects.create(
            tenant=self.tenant_a,
            seguradora="Porto Seguro Cia de Seguros",
            corretor="Seguros Brasil Ltda",
            telefone_assistencia_24h="0800-727-2727",
            numero_apolice="APOL-2026-FROTA-001",
            tipo="Frota/Casco+RCF",
            vigencia_inicio=hoje - timedelta(days=30),
            vigencia_fim=hoje + timedelta(days=335),
            premio_total=Decimal("14500.00"),
            forma_pagamento="Boleto",
            parcelas=10,
            prazo_comunicacao_sinistro_horas=48,
            cobre_produto_perigoso="Sim",
            ativa=True
        )

        # Adiciona coberturas
        cob_casco = ApoliceCobertura.objects.create(
            tenant=self.tenant_a,
            apolice=apolice,
            cobertura="Casco",
            limite=Decimal("250000.00"),
            franquia_valor=Decimal("4500.00"),
            franquia_percentual=Decimal("10.00")
        )
        cob_rcf = ApoliceCobertura.objects.create(
            tenant=self.tenant_a,
            apolice=apolice,
            cobertura="RCF-Danos Materiais",
            limite=Decimal("150000.00"),
            franquia_valor=Decimal("1000.00")
        )

        # Vincula veículo
        ApoliceVeiculo.objects.create(
            tenant=self.tenant_a,
            apolice=apolice,
            veiculo=self.veiculo_a,
            valor_segurado=Decimal("180000.00"),
            tipo_valor="Percentual FIPE"
        )

        self.assertEqual(apolice.status_vigencia, "Vigente")
        self.assertEqual(apolice.semaforo_vigencia, "green")
        self.assertGreater(apolice.dias_para_vencer, 300)
        self.assertFalse(apolice.alerta_renovacao_60dias)

        # Teste de semáforo com apólice prestes a vencer (20 dias)
        apolice_expirando = ApoliceSeguro.objects.create(
            tenant=self.tenant_a,
            seguradora="Tokio Marine",
            numero_apolice="APOL-EXP-020",
            tipo="Carga RCTR-C",
            vigencia_inicio=hoje - timedelta(days=340),
            vigencia_fim=hoje + timedelta(days=20),
            premio_total=Decimal("8000.00"),
            cobre_produto_perigoso="Nao_Verificado",
            ativa=True
        )
        self.assertEqual(apolice_expirando.status_vigencia, "Vence em 30 dias")
        self.assertEqual(apolice_expirando.semaforo_vigencia, "orange")
        self.assertTrue(apolice_expirando.alerta_renovacao_60dias)
        self.assertTrue(apolice_expirando.alerta_renovacao_30dias)
        self.assertFalse(apolice_expirando.alerta_renovacao_15dias)

        # Teste de apólice vencida
        apolice_vencida = ApoliceSeguro.objects.create(
            tenant=self.tenant_a,
            seguradora="Mapfre",
            numero_apolice="APOL-VENC-001",
            tipo="Outro",
            vigencia_inicio=hoje - timedelta(days=400),
            vigencia_fim=hoje - timedelta(days=5),
            premio_total=Decimal("5000.00"),
            ativa=True
        )
        self.assertEqual(apolice_vencida.status_vigencia, "Vencida")
        self.assertEqual(apolice_vencida.semaforo_vigencia, "red")

        # Verifica API de apólices
        res = self.client_admin.get('/logistica/api/apolices-seguro/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Deve listar as 3 apólices do tenant_a
        results = res.data.get('results', res.data)
        self.assertEqual(len(results), 3)

    # =========================================================================
    # TESTE 2: Criação de Sinistro e Imutabilidade da Linha do Tempo
    # =========================================================================
    def test_02_criacao_sinistro_e_linha_do_tempo_imutavel(self):
        sinistro = criar_sinistro(
            tipo="Colisão",
            descricao="Colisão frontal leve com poste em manobra de ré.",
            veiculo=self.veiculo_a,
            motorista=self.user_motorista,
            autor=self.user_admin,
            tenant=self.tenant_a,
            status="Registrado",
            valor_prejuizo_estimado=Decimal("3500.00")
        )

        self.assertIsNotNone(sinistro.id)
        self.assertEqual(sinistro.status, "Registrado")

        # Verifica que o evento inicial foi criado na linha do tempo (Criação + Marcação de Sinistrado)
        eventos = SinistroEvento.objects.filter(sinistro=sinistro)
        self.assertEqual(eventos.count(), 2)
        evento_inicial = eventos.filter(tipo="Criação").first()
        self.assertEqual(evento_inicial.tipo, "Criação")
        self.assertEqual(evento_inicial.status_novo, "Registrado")

        # Tentar editar o evento deve levantar ValidationError (Imutabilidade estrita)
        evento_inicial.descricao = "Tentativa de adulteração da linha do tempo"
        with self.assertRaises(ValidationError):
            evento_inicial.save()

        # Tentar deletar o evento deve levantar ValidationError
        with self.assertRaises(ValidationError):
            evento_inicial.delete()

        # Confirma que continua inalterado no banco
        evento_recarregado = SinistroEvento.objects.get(pk=evento_inicial.pk)
        self.assertNotEqual(evento_recarregado.descricao, "Tentativa de adulteração da linha do tempo")
        self.assertEqual(eventos.count(), 2)

    # =========================================================================
    # TESTE 3: Transições de Status Validadas
    # =========================================================================
    def test_03_transicoes_status_validas_e_invalidas(self):
        sinistro = criar_sinistro(
            tipo="Colisão",
            descricao="Batida traseira no trânsito.",
            veiculo=self.veiculo_a,
            autor=self.user_admin,
            tenant=self.tenant_a,
            status="Rascunho"
        )

        # Transição válida 1: Rascunho -> Registrado
        sinistro = transicionar_status_sinistro(
            sinistro=sinistro,
            novo_status="Registrado",
            autor=self.user_admin,
            observacao="Validado pelo analista de frotas."
        )
        self.assertEqual(sinistro.status, "Registrado")

        # Transição válida 2: Registrado -> Comunicado à Seguradora
        sinistro = transicionar_status_sinistro(
            sinistro=sinistro,
            novo_status="Comunicado à Seguradora",
            autor=self.user_admin,
            protocolo="PROT-SEG-998811",
            observacao="Sinistro aberto na central de atendimento."
        )
        self.assertEqual(sinistro.status, "Comunicado à Seguradora")
        self.assertEqual(sinistro.protocolo_seguradora, "PROT-SEG-998811")
        self.assertIsNotNone(sinistro.data_comunicacao_seguradora)

        # Transição válida 3: Comunicado à Seguradora -> Em Análise
        sinistro = transicionar_status_sinistro(
            sinistro=sinistro,
            novo_status="Em Análise",
            autor=self.user_admin
        )
        self.assertEqual(sinistro.status, "Em Análise")

        # Transição inválida: Não pode pular direto de Em Análise para Encerrado sem aprovação/negação
        with self.assertRaises(ValidationError):
            transicionar_status_sinistro(
                sinistro=sinistro,
                novo_status="Encerrado",
                autor=self.user_admin
            )

        # Linha do tempo deve conter os eventos das transições válidas
        eventos = SinistroEvento.objects.filter(sinistro=sinistro).order_by('data_hora')
        self.assertEqual(eventos.count(), 5)  # 2 Criação (Criação + Veículo) + 3 transições
        mudancas = eventos.filter(tipo="Mudança de Status")
        self.assertEqual(mudancas.count(), 3)

    # =========================================================================
    # TESTE 4: Prazo de Comunicação à Seguradora e Alertas Destacados
    # =========================================================================
    def test_04_prazo_comunicacao_seguradora(self):
        hoje = timezone.now().date()
        apolice = ApoliceSeguro.objects.create(
            tenant=self.tenant_a,
            seguradora="Azul Seguros",
            numero_apolice="AZUL-9988",
            tipo="Frota/Casco+RCF",
            vigencia_inicio=hoje - timedelta(days=10),
            vigencia_fim=hoje + timedelta(days=350),
            prazo_comunicacao_sinistro_horas=24,
            ativa=True
        )

        agora = timezone.now()
        # Ocorrência há 22 horas: faltam 2 horas para estourar o prazo (< 4h -> urgente)
        data_sinistro = agora - timedelta(hours=22)
        sinistro = Sinistro.objects.create(
            tenant=self.tenant_a,
            tipo="Colisão",
            descricao="Batida na porta da garagem.",
            veiculo=self.veiculo_a,
            apolice=apolice,
            data_hora=data_sinistro,
            status="Registrado"
        )
        sinistro.calcular_prazo_limite()
        sinistro.save()

        limite_esperado = data_sinistro + timedelta(hours=24)
        self.assertEqual(sinistro.prazo_limite_comunicacao, limite_esperado)
        self.assertTrue(sinistro.prazo_comunicacao_urgente)
        self.assertFalse(sinistro.prazo_comunicacao_expirado)

        # Se a ocorrência foi há 26 horas, prazo já expirou
        sinistro.data_hora = agora - timedelta(hours=26)
        sinistro.calcular_prazo_limite()
        sinistro.save()
        self.assertTrue(sinistro.prazo_comunicacao_expirado)

        # Uma vez comunicado à seguradora, os alertas cessam
        sinistro.status = "Comunicado à Seguradora"
        sinistro.save()
        self.assertFalse(sinistro.prazo_comunicacao_urgente)
        self.assertFalse(sinistro.prazo_comunicacao_expirado)

    # =========================================================================
    # TESTE 5: Efeito no Veículo (Sinistrado, Inapto e Bloqueio Operacional)
    # =========================================================================
    def test_05_sinistro_veiculo_torna_inapto_e_bloqueia_operacao(self):
        self.veiculo_a.status = "Disponível"
        self.veiculo_a.status_ativo = "Ativo"
        self.veiculo_a.save()

        # Verifica que o veículo estava apto
        apto, msg = veiculo_apto_para_operar(self.veiculo_a)
        self.assertTrue(apto, f"Deveria estar apto, mas retornou: {msg}")

        # Registra sinistro de veículo (Colisão)
        sinistro = criar_sinistro(
            tipo="Colisão",
            descricao="Abalroamento na rodovia com perda do para-choque dianteiro.",
            veiculo=self.veiculo_a,
            autor=self.user_admin,
            tenant=self.tenant_a,
            status="Registrado"
        )

        # Veículo deve ter sido marcado automaticamente como Sinistrado
        self.veiculo_a.refresh_from_db()
        self.assertEqual(self.veiculo_a.status, "Sinistrado")
        self.assertEqual(self.veiculo_a.status_ativo, "Sinistrado")

        # Função de prontidão operacional deve rejeitar o veículo
        apto, motivos = veiculo_apto_para_operar(self.veiculo_a)
        self.assertFalse(apto)
        self.assertIn("sinistrado", ' '.join(motivos).lower())

        # Teste da regra configurável por empresa: exigir_apolice_ativa_para_operar
        cfg = ConfiguracaoSeguros.get_para_tenant(self.tenant_a)
        cfg.exigir_apolice_ativa_para_operar = True
        cfg.save()

        # Criamos veículo C ativo sem apólice para testar o gancho da regra
        veiculo_sem_seguro = Veiculo.objects.create(
            tenant=self.tenant_a,
            placa="SEM9999",
            marca="Ford",
            modelo="Cargo",
            ano=2020,
            capacidade_carga=Decimal("3000.00"),
            status="Disponível",
            status_ativo="Ativo"
        )
        apto_sem_seguro, motivo_seguro = veiculo_apto_para_operar(veiculo_sem_seguro)
        self.assertFalse(apto_sem_seguro)
        self.assertIn("apólice de seguro ativa", ' '.join(motivo_seguro).lower())

    # =========================================================================
    # TESTE 6: Regra Estrita de Liberação do Veículo (Apenas Ação de Gestor)
    # =========================================================================
    def test_06_regra_estrita_liberacao_veiculo_gestor(self):
        sinistro = criar_sinistro(
            tipo="Colisão",
            descricao="Dano na suspensão dianteira.",
            veiculo=self.veiculo_a,
            autor=self.user_admin,
            tenant=self.tenant_a,
            status="Registrado"
        )
        self.veiculo_a.refresh_from_db()
        self.assertEqual(self.veiculo_a.status, "Sinistrado")

        # 1. Encerrar o sinistro NÃO DEVE liberar o veículo automaticamente
        sinistro = transicionar_status_sinistro(
            sinistro=sinistro,
            novo_status="Encerrado",
            autor=self.user_admin,
            observacao="Sinistro finalizado pela seguradora."
        )
        self.assertEqual(sinistro.status, "Encerrado")
        self.veiculo_a.refresh_from_db()
        self.assertEqual(self.veiculo_a.status, "Sinistrado")

        # 2. Motorista NÃO PODE liberar veículo
        with self.assertRaises(ValidationError):
            liberar_veiculo_sinistrado(self.veiculo_a, autor=self.user_motorista, observacao="Liberando...")

        # 3. Se houver Ordem de Serviço imobilizadora aberta, liberação é bloqueada
        os_aberta = OrdemServico.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            tipo="Corretiva",
            status="Aberta",
            imobiliza_veiculo=True,
            descricao_problema="Reparo estrutural da colisão"
        )
        with self.assertRaises(ValidationError) as ctx:
            liberar_veiculo_sinistrado(self.veiculo_a, autor=self.user_admin, observacao="Tentando liberar...")
        self.assertIn("imobilizante", str(ctx.exception).lower())

        # Conclui a OS respeitando a máquina de estados
        os_aberta.status = "Aprovada"
        os_aberta.save()
        os_aberta.status = "Em Execução"
        os_aberta.save()
        os_aberta.odometro_saida = self.veiculo_a.odometro_atual_km
        os_aberta.custo_total = Decimal("500.00")
        os_aberta.status = "Concluída"
        os_aberta.save()

        # 4. Agora sim, gestor/admin libera com sucesso
        v_liberado = liberar_veiculo_sinistrado(self.veiculo_a, autor=self.user_admin, observacao="Vistoria técnica aprovada.")
        self.assertEqual(v_liberado.status, "Disponível")
        self.assertEqual(v_liberado.status_ativo, "Ativo")

    # =========================================================================
    # TESTE 7: Vínculo com OS (1 clique) e Soma de Custos no Prejuízo Líquido
    # =========================================================================
    def test_07_vinculo_os_e_soma_custos_prejuizo_liquido(self):
        sinistro = criar_sinistro(
            tipo="Colisão",
            descricao="Avaria de funilaria e radiador furado.",
            veiculo=self.veiculo_a,
            autor=self.user_admin,
            tenant=self.tenant_a,
            valor_prejuizo_estimado=Decimal("2000.00"),
            valor_franquia=Decimal("1500.00")
        )

        # 1-clique: Criação e vínculo de OS
        sinistro, os_obj = vincular_ou_criar_os_sinistro(
            sinistro=sinistro,
            autor=self.user_admin,
            descricao="Reparação de radiador e funilaria do sinistro.",
            prioridade="Crítica",
            imobiliza_veiculo=True
        )

        self.assertIsNotNone(sinistro.os_vinculada)
        self.assertEqual(sinistro.os_vinculada.id, os_obj.id)
        self.assertEqual(os_obj.sinistro_origem.id, sinistro.id)

        # Lança custos na OS
        os_obj.custo_pecas = Decimal("1800.00")
        os_obj.custo_mao_de_obra = Decimal("1200.00")
        os_obj.custo_total = Decimal("3000.00")
        os_obj.save()

        # Recalcula prejuízo líquido
        sinistro.refresh_from_db()
        prejuizo = sinistro.calcular_prejuizo_liquido()
        sinistro.save()

        # Prejuízo líquido = prejuizo_estimado (2000) + franquia (1500) + custos_os (3000) = 6500
        self.assertEqual(prejuizo, Decimal("6500.00"))
        self.assertEqual(sinistro.prejuizo_liquido, Decimal("6500.00"))

        # Seguradora indeniza 4000
        sinistro.valor_indenizacao = Decimal("4000.00")
        prejuizo_com_indenizacao = sinistro.calcular_prejuizo_liquido()
        self.assertEqual(prejuizo_com_indenizacao, Decimal("2500.00"))

    # =========================================================================
    # TESTE 8: Sinistro com Carga, Ajuste Atômico de Estoque e Contingência
    # =========================================================================
    def test_08_sinistro_carga_ajuste_estoque_atomico_e_contingencia(self):
        # Estoque inicial de botijões P13 = 50
        self.produto_glp.refresh_from_db()
        qtd_inicial = self.produto_glp.estoque
        self.assertEqual(qtd_inicial, 50)

        sinistro = criar_sinistro(
            tipo="Avaria de Carga",
            descricao="Cilindros de GLP caíram durante frenagem brusca.",
            veiculo=self.veiculo_a,
            entrega=self.entrega,
            autor=self.user_admin,
            tenant=self.tenant_a,
            itens_carga=[
                {
                    'produto': self.produto_glp.id,
                    'quantidade': 6,
                    'categoria': 'Cheio',
                    'valor_unitario': Decimal("110.00")
                },
                {
                    'produto': self.produto_glp.id,
                    'quantidade': 4,
                    'categoria': 'Vazio',
                    'valor_unitario': Decimal("80.00")
                }
            ]
        )

        self.assertEqual(sinistro.itens_carga.count(), 2)

        # Executa ajuste atômico de estoque com decisão de contingência 'reentregar'
        sinistro_processado = processar_ajuste_estoque_sinistro_carga(
            sinistro=sinistro,
            autor=self.user_admin,
            decisao_entrega="reentregar",
            justificativa="Avaria em trânsito com reprogramação de rota."
        )

        self.assertTrue(sinistro_processado.ajuste_estoque_realizado)

        # Verifica decremento no estoque físico (6 cheios + 4 vazios = 10)
        self.produto_glp.refresh_from_db()
        self.assertEqual(self.produto_glp.estoque, qtd_inicial - 10)

        # Verifica status da entrega
        self.entrega.refresh_from_db()
        self.assertEqual(self.entrega.status, "Agendada")

        # Linha do tempo deve registrar o ajuste de estoque
        eventos_estoque = SinistroEvento.objects.filter(sinistro=sinistro, tipo="Ajuste de Estoque")
        self.assertEqual(eventos_estoque.count(), 1)

    # =========================================================================
    # TESTE 9: Perda Total e Comparação com Valor FIPE
    # =========================================================================
    def test_09_comparacao_indenizacao_com_fipe(self):
        VeiculoValorFipe.objects.create(
            tenant=self.tenant_a,
            veiculo=self.veiculo_a,
            mes_referencia=timezone.now().date(),
            valor=Decimal("150000.00")
        )

        sinistro = Sinistro.objects.create(
            tenant=self.tenant_a,
            tipo="Incêndio",
            descricao="Perda total por incêndio no compartimento do motor.",
            veiculo=self.veiculo_a,
            valor_indenizacao=Decimal("100000.00"),  # Divergência de 33.3% em relação aos 150k da FIPE
            status="Indenizado"
        )

        comp = sinistro.comparacao_fipe
        self.assertIsNotNone(comp)
        self.assertEqual(comp['valor_fipe'], Decimal("150000.00"))
        self.assertTrue(comp['divergente'], "Divergência > 15% deveria estar sinalizada.")
        self.assertIn("atenção", comp['alerta'].lower())

    # =========================================================================
    # TESTE 10: Indicadores de Sinistralidade (Loss Ratio, Km e Prejuízo)
    # =========================================================================
    def test_10_indicadores_sinistralidade_loss_ratio_e_km(self):
        hoje = timezone.now().date()
        # Apólice com prêmio de 20.000
        apolice = ApoliceSeguro.objects.create(
            tenant=self.tenant_a,
            seguradora="Porto Seguro",
            numero_apolice="APOL-BI-001",
            tipo="Frota/Casco+RCF",
            vigencia_inicio=hoje - timedelta(days=60),
            vigencia_fim=hoje + timedelta(days=300),
            premio_total=Decimal("20000.00"),
            ativa=True
        )

        # Sinistro 1 indenizado em 10.000
        s1 = Sinistro.objects.create(
            tenant=self.tenant_a,
            tipo="Colisão",
            veiculo=self.veiculo_a,
            apolice=apolice,
            valor_prejuizo_estimado=Decimal("8000.00"),
            valor_indenizacao=Decimal("10000.00"),
            status="Indenizado",
            data_hora=timezone.now() - timedelta(days=20)
        )
        s1.calcular_prejuizo_liquido()
        s1.save()

        # Veículo tem 45.000 km rodados
        dados_bi = obter_indicadores_sinistralidade(self.tenant_a)

        self.assertEqual(dados_bi['total_sinistros'], 1)
        self.assertEqual(dados_bi['total_indenizacoes_recebidas'], Decimal("10000.00"))
        self.assertEqual(dados_bi['total_premios_apolices'], Decimal("20000.00"))
        # Loss ratio = (10.000 / 20.000) * 100 = 50.0%
        self.assertEqual(dados_bi['loss_ratio_global'], 50.0)

        # Endpoint de API de indicadores
        res = self.client_admin.get('/logistica/api/sinistros/indicadores/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['loss_ratio_global'], 50.0)

    # =========================================================================
    # TESTE 11: PWA Offline Idempotência (client_uuid)
    # =========================================================================
    def test_11_pwa_idempotencia_offline(self):
        uuid_teste = str(uuid.uuid4())
        payload = {
            'client_uuid': uuid_teste,
            'tipo': 'Colisão',
            'descricao': 'Queda de retrovisor contra galho de árvore.',
            'veiculo': self.veiculo_a.id,
            'status': 'Rascunho',
            'latitude': -16.686891,
            'longitude': -49.264789,
            'houve_vitimas': False
        }

        # Primeiro envio pelo PWA
        res1 = self.client_motorista.post('/logistica/api/sinistros/', data=payload, format='json')
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED, f"Falha na criação do sinistro: {res1.data}")
        sinistro_id_1 = res1.data['id']

        # Reenvio idêntico pelo PWA (idempotência offline pós-reconexão)
        res2 = self.client_motorista.post('/logistica/api/sinistros/', data=payload, format='json')
        self.assertIn(res2.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED))
        sinistro_id_2 = res2.data['id']

        self.assertEqual(sinistro_id_1, sinistro_id_2)
        # Deve existir estritamente 1 registro com o client_uuid
        self.assertEqual(Sinistro.objects.filter(client_uuid=uuid_teste).count(), 1)

    # =========================================================================
    # TESTE 12: Isolamento Multi-tenant e Proteção LGPD de Terceiros
    # =========================================================================
    def test_12_isolamento_multitenant_e_lgpd(self):
        # Cria sinistro no Tenant A com dados sensíveis de terceiros
        sinistro_a = Sinistro.objects.create(
            tenant=self.tenant_a,
            tipo="Colisão",
            descricao="Colisão com veículo de terceiro.",
            veiculo=self.veiculo_a,
            terceiros={
                'nome': 'João da Silva Sauro',
                'cpf': '123.456.789-00',
                'telefone': '(62) 98765-4321',
                'placa': 'ABC-1234'
            },
            status="Registrado"
        )

        # 1. Tenant B NÃO DEVE conseguir acessar o sinistro do Tenant A
        res_b = self.client_b.get(f'/logistica/api/sinistros/{sinistro_a.id}/')
        self.assertEqual(res_b.status_code, status.HTTP_404_NOT_FOUND)

        # 2. Gestor/Admin do Tenant A visualiza dados de terceiros desmascarados
        res_admin = self.client_admin.get(f'/logistica/api/sinistros/{sinistro_a.id}/')
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)
        terceiros_admin = res_admin.data.get('terceiros', {})
        self.assertEqual(terceiros_admin.get('nome'), 'João da Silva Sauro')
        self.assertEqual(terceiros_admin.get('cpf'), '123.456.789-00')

        # 3. Motorista / usuário sem papel de gestão tem dados de terceiros mascarados (LGPD)
        res_mot = self.client_motorista.get(f'/logistica/api/sinistros/{sinistro_a.id}/')
        self.assertEqual(res_mot.status_code, status.HTTP_200_OK)
        terceiros_mot = res_mot.data.get('terceiros', {})
        self.assertTrue(terceiros_mot.get('acesso_restrito_lgpd'))
        self.assertIn('lgpd', terceiros_mot.get('mensagem', '').lower())
        self.assertNotIn('cpf', terceiros_mot)
