import os
import django
import uuid
from decimal import Decimal
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from core.models import Tenant, Membership, ResponsavelTecnico, PerfilRegulatorioTenant
from core.tenancy import tenant_context
from accounts.models import User, UserProfile
from clientes.models import Cliente, ContratoComodato
from clientes.services import calcular_radar_comodato_tenant
from produtos.models import (
    Produto,
    GasQuimico,
    ModeloCilindro,
    SkuRecarga,
    Cilindro,
    MovimentacaoCilindro,
    LoteEnvase,
    EnvaseCilindro
)
from produtos.services import (
    registrar_envase_cilindro,
    registrar_entrega_cilindro,
    registrar_recolha_cilindro,
    enviar_para_reteste,
    retornar_de_reteste,
    alocar_cilindro_rota,
    baixar_cilindro
)
from logistica.models import Veiculo, Rota, Entrega
from vendas.models import Venda, ItemVenda


def get_deterministic_uuid(tenant_id, key: str) -> uuid.UUID:
    """Gera um UUID determinístico para garantir a idempotência perfeita no seed."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}:{key}")


def criar_gases_globais():
    print("Garantindo Gases Químicos Globais (ABNT / ANVISA)...")
    gases_data = [
        {
            "nome": "Oxigênio Medicinal",
            "sigla": "O2-MED",
            "categoria": "MEDICINAL",
            "numero_onu": "1072",
            "classe_risco": "2.2",
            "cor_padrao_abnt": "Verde",
            "exige_lote_anvisa": True
        },
        {
            "nome": "Nitrogênio Industrial",
            "sigla": "N2-IND",
            "categoria": "INDUSTRIAL",
            "numero_onu": "1066",
            "classe_risco": "2.2",
            "cor_padrao_abnt": "Cinza",
            "exige_lote_anvisa": False
        },
        {
            "nome": "Argônio Puro Solda",
            "sigla": "AR-IND",
            "categoria": "INDUSTRIAL",
            "numero_onu": "1006",
            "classe_risco": "2.2",
            "cor_padrao_abnt": "Marrom",
            "exige_lote_anvisa": False
        },
    ]
    gases = {}
    for gd in gases_data:
        gas, _ = GasQuimico.objects.get_or_create(sigla=gd['sigla'], defaults=gd)
        gases[gas.sigla] = gas
    return gases


def popular_tenant(tenant, user_vendedor, sufixo_cidade, gases):
    print(f"\n--- Populando dados com integridade estrita: {tenant.nome_fantasia} ({sufixo_cidade}) ---")
    with tenant_context(tenant):
        print(f"[{tenant.nome_fantasia}] Criando Clientes e Contratos de Comodato...")
        is_df = "Brasília" in sufixo_cidade
        uf = "DF" if is_df else "GO"
        cidade_nome = "Brasília" if is_df else "Goiânia"
        cnpj_prefix = "11.101" if is_df else "22.202"

        clientes_data = [
            {
                "cnpj": f"{cnpj_prefix}.111/0001-11",
                "tipo_cliente": "GOV",
                "nome": f"Hospital Regional {sufixo_cidade} - SES/{uf}",
                "nome_fantasia": f"Hospital Regional {sufixo_cidade}",
                "endereco": "Setor Hospitalar Sul, Quadra 716" if is_df else "Av. Universitária, 500",
                "numero": "S/N" if is_df else "500",
                "bairro": "Asa Sul" if is_df else "Setor Universitário",
                "cidade": cidade_nome,
                "estado": uf,
                "cep": "70330-716" if is_df else "74605-010",
                "telefone": "6133450001" if is_df else "6232210001",
                "email_financeiro": f"financeiro.hr{sufixo_cidade.lower()}@saude.gov.br",
                "proprietario": "Dr. Fernando Silveira",
                "is_medicinal": True,
                "cnes_licenca_sanitaria": "2678910" if is_df else "2678920"
            },
            {
                "cnpj": f"{cnpj_prefix}.222/0001-22",
                "tipo_cliente": "PJ",
                "nome": f"Metalúrgica {sufixo_cidade} Indústria e Comércio Ltda",
                "nome_fantasia": f"Metalúrgica {sufixo_cidade}",
                "endereco": "SIA Trecho 3, Lote 12" if is_df else "Pólo Moveleiro, Quadra 4",
                "numero": "12" if is_df else "4",
                "bairro": "Zona Industrial" if is_df else "Pólo Moveleiro",
                "cidade": cidade_nome,
                "estado": uf,
                "cep": "71200-030" if is_df else "74000-000",
                "telefone": "6133450002" if is_df else "6232210002",
                "email_financeiro": f"nfe@metalurgica{sufixo_cidade.lower()}.com.br",
                "proprietario": "Sr. Carlos Eduardo",
                "is_medicinal": False
            },
            {
                "cnpj": f"{cnpj_prefix}.333/0001-33",
                "tipo_cliente": "PJ",
                "nome": f"Clínica Médica Vida {sufixo_cidade} S/S",
                "nome_fantasia": f"Clínica Vida {sufixo_cidade}",
                "endereco": "Asa Norte, CLN 116" if is_df else "Setor Bueno, T-10",
                "numero": "Bloco B" if is_df else "1024",
                "bairro": "Asa Norte" if is_df else "Setor Bueno",
                "cidade": cidade_nome,
                "estado": uf,
                "cep": "70775-520" if is_df else "74223-060",
                "telefone": "6133450003" if is_df else "6232210003",
                "email_financeiro": f"contas@clinicavida{sufixo_cidade.lower()}.med.br",
                "proprietario": "Dra. Beatriz Mendes",
                "is_medicinal": True,
                "cnes_licenca_sanitaria": "3847561" if is_df else "3847562"
            },
        ]
        clientes = []
        for cd in clientes_data:
            cliente, created = Cliente.objects.get_or_create(cnpj=cd['cnpj'], defaults=cd)
            if not created:
                for k, v in cd.items():
                    setattr(cliente, k, v)
                cliente.save()
            clientes.append(cliente)

            # Contrato de Comodato: 30 dias de carência, diária excedente R$ 3,50
            ContratoComodato.objects.get_or_create(
                cliente=cliente,
                defaults={
                    "franquia_cilindros_isentos": 0,
                    "dias_carencia_giro": 30,
                    "valor_diaria_excedente": Decimal("3.50"),
                    "custo_reposicao_casco": Decimal("1800.00")
                }
            )

        print(f"[{tenant.nome_fantasia}] Criando Modelos de Cilindro e SKUs de Recarga...")
        mod_50l, _ = ModeloCilindro.objects.get_or_create(
            descricao="Cilindro Aço 50L / 10m³",
            defaults={
                "material": "ACO",
                "volume_hidraulico_litros": Decimal("50.00"),
                "pressao_servico_bar": 200,
                "tara_nominal_kg": Decimal("60.00"),
                "padrao_valvula_abnt": "ABNT 218-1",
                "periodicidade_reteste_anos": 5
            }
        )

        mod_10l, _ = ModeloCilindro.objects.get_or_create(
            descricao="Cilindro Alumínio 10L / 2m³",
            defaults={
                "material": "ALUMINIO",
                "volume_hidraulico_litros": Decimal("10.00"),
                "pressao_servico_bar": 150,
                "tara_nominal_kg": Decimal("12.50"),
                "padrao_valvula_abnt": "ABNT 218-1",
                "periodicidade_reteste_anos": 5
            }
        )

        sku_o2, _ = SkuRecarga.objects.get_or_create(
            nome_comercial=f"Carga O2 Medicinal 10m³ ({sufixo_cidade})",
            defaults={
                "gas": gases['O2-MED'],
                "modelo_cilindro": mod_50l,
                "quantidade_carga": Decimal("10.00"),
                "unidade": "m3",
                "massa_gas_kg": Decimal("13.30"),
                "preco_base": Decimal("165.00"),
                "ativo": True
            }
        )

        sku_n2, _ = SkuRecarga.objects.get_or_create(
            nome_comercial=f"Carga N2 Industrial 50L ({sufixo_cidade})",
            defaults={
                "gas": gases['N2-IND'],
                "modelo_cilindro": mod_50l,
                "quantidade_carga": Decimal("50.00"),
                "unidade": "l",
                "massa_gas_kg": Decimal("11.60"),
                "preco_base": Decimal("320.00"),
                "ativo": True
            }
        )

        sku_ar, _ = SkuRecarga.objects.get_or_create(
            nome_comercial=f"Carga Argônio Puro 2m³ ({sufixo_cidade})",
            defaults={
                "gas": gases['AR-IND'],
                "modelo_cilindro": mod_10l,
                "quantidade_carga": Decimal("2.00"),
                "unidade": "m3",
                "massa_gas_kg": Decimal("3.50"),
                "preco_base": Decimal("220.00"),
                "ativo": True
            }
        )

        print(f"[{tenant.nome_fantasia}] Criando Produtos Legados (Strangler Pattern)...")
        prod_o2, _ = Produto.objects.get_or_create(
            nome=f"Cilindro Oxigênio Medicinal ({sufixo_cidade})",
            defaults={
                "categoria": "Medicinal",
                "capacidade": Decimal("10.00"),
                "unidade_medida": "m³",
                "preco": Decimal("165.00"),
                "estoque": 35
            }
        )

        prod_n2, _ = Produto.objects.get_or_create(
            nome=f"Cilindro Nitrogênio Industrial ({sufixo_cidade})",
            defaults={
                "categoria": "Industrial",
                "capacidade": Decimal("50.00"),
                "unidade_medida": "litros",
                "preco": Decimal("320.00"),
                "estoque": 20
            }
        )

        print(f"[{tenant.nome_fantasia}] Garantindo Veículos, Rotas e Entregas...")
        placa_fixa = "BRA1A80" if is_df else "GOI2B90"
        veiculo = Veiculo.objects.filter(placa=placa_fixa).first()
        if not veiculo:
            veiculo = Veiculo.objects.create(
                placa=placa_fixa,
                modelo="Delivery 11.180",
                marca="VW",
                ano=2022,
                capacidade_carga=Decimal("4500.00"),
                status="Ativo"
            )

        rota = Rota.objects.filter(nome=f"Rota Expressa {sufixo_cidade}").first()
        if not rota:
            rota = Rota.objects.create(
                nome=f"Rota Expressa {sufixo_cidade}",
                origem=f"Base Operacional {sufixo_cidade}",
                destino=f"Pólo Industrial {sufixo_cidade}",
                distancia_km=Decimal("35.00"),
                tempo_estimado_horas=Decimal("1.50")
            )

        entrega = Entrega.objects.filter(veiculo=veiculo, rota=rota, motorista=user_vendedor).first()
        if not entrega:
            entrega = Entrega.objects.create(
                veiculo=veiculo,
                rota=rota,
                motorista=user_vendedor,
                status="Em Rota"
            )

        venda = Venda.objects.filter(cliente=clientes[0], vendedor=user_vendedor, entrega=entrega).first()
        if not venda:
            venda = Venda.objects.create(
                cliente=clientes[0],
                vendedor=user_vendedor,
                entrega=entrega,
                status="Em Rota"
            )

        item = ItemVenda.objects.filter(venda=venda, sku=sku_o2).first()
        if not item:
            ItemVenda.objects.create(
                venda=venda,
                produto=prod_o2,
                sku=sku_o2,
                forma_faturamento="cilindro",
                quantidade=3,
                peso_unitario=sku_o2.quantidade_carga,
                valor_unitario=sku_o2.preco_base,
                preco_unitario_congelado=sku_o2.preco_base
            )
        venda.calcular_total()

        print(f"[{tenant.nome_fantasia}] Criando Lotes Farmacêuticos e Industriais...")
        hoje = timezone.now().date()
        agora = timezone.now()

        lote_o2_valido, _ = LoteEnvase.objects.get_or_create(
            codigo_lote=f"LOTE-O2-{sufixo_cidade[:3].upper()}-2026-01",
            defaults={
                "gas": gases['O2-MED'],
                "data_envase": hoje - timedelta(days=20),
                "data_validade": hoje + timedelta(days=365),
                "pureza_percentual": Decimal("99.65"),
                "responsavel_tecnico": "Dra. Camila Rocha CRF-DF 4589" if is_df else "Dr. Marcos Vinicius CRQ-GO 1234"
            }
        )

        lote_o2_recall, _ = LoteEnvase.objects.get_or_create(
            codigo_lote=f"LOTE-O2-{sufixo_cidade[:3].upper()}-2025-99",
            defaults={
                "gas": gases['O2-MED'],
                "data_envase": hoje - timedelta(days=60),
                "data_validade": hoje + timedelta(days=300),
                "pureza_percentual": Decimal("98.10"),
                "responsavel_tecnico": "Dra. Camila Rocha CRF-DF 4589" if is_df else "Dr. Marcos Vinicius CRQ-GO 1234"
            }
        )

        lote_n2, _ = LoteEnvase.objects.get_or_create(
            codigo_lote=f"LOTE-N2-{sufixo_cidade[:3].upper()}-2026-01",
            defaults={
                "gas": gases['N2-IND'],
                "data_envase": hoje - timedelta(days=50),
                "data_validade": hoje + timedelta(days=730),
                "pureza_percentual": Decimal("99.90"),
                "responsavel_tecnico": "Eng. Roberto Dias CREA-DF 1098" if is_df else "Eng. Flávio Costa CREA-GO 2234"
            }
        )

        lote_ar, _ = LoteEnvase.objects.get_or_create(
            codigo_lote=f"LOTE-AR-{sufixo_cidade[:3].upper()}-2026-01",
            defaults={
                "gas": gases['AR-IND'],
                "data_envase": hoje - timedelta(days=100),
                "data_validade": hoje + timedelta(days=730),
                "pureza_percentual": Decimal("99.99"),
                "responsavel_tecnico": "Eng. Roberto Dias CREA-DF 1098" if is_df else "Eng. Flávio Costa CREA-GO 2234"
            }
        )

        print(f"[{tenant.nome_fantasia}] Gerenciando Ciclo de Vida da Frota exclusivamente via services.py...")

        # Cilindro 1: Cheio disponível no pátio com lote válido O2
        cil_1, _ = Cilindro.objects.get_or_create(
            codigo_qr=f"QR-{sufixo_cidade[:3].upper()}-0101",
            defaults={
                "numero_serie_ogiva": f"SN-{sufixo_cidade[:3].upper()}-901",
                "fabricante": "Cilbras",
                "ano_fabricacao": 2021,
                "modelo": mod_50l,
                "gas_dedicado": gases['O2-MED'],
                "tara_real_kg": Decimal("59.70"),
                "propriedade": "PROPRIO",
                "data_ultimo_reteste": hoje - timedelta(days=365),
                "data_proximo_reteste": hoje + timedelta(days=365 * 4),
                "status": "VAZIO_TRIAGEM"
            }
        )
        if cil_1.status == 'VAZIO_TRIAGEM':
            registrar_envase_cilindro(
                cilindro_id=cil_1.id,
                lote_id=lote_o2_valido.id,
                pressao_bar=200,
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=18),
                client_uuid=get_deterministic_uuid(tenant.id, "cil1-envase"),
                observacoes="Envase hospitalar aprovado em CQ"
            )

        # Cilindro 2: Entregue há 15 dias (dentro da carência de 30d) com lote válido O2
        cil_2, _ = Cilindro.objects.get_or_create(
            codigo_qr=f"QR-{sufixo_cidade[:3].upper()}-0102",
            defaults={
                "numero_serie_ogiva": f"SN-{sufixo_cidade[:3].upper()}-902",
                "fabricante": "Mannesmann",
                "ano_fabricacao": 2020,
                "modelo": mod_50l,
                "gas_dedicado": gases['O2-MED'],
                "tara_real_kg": Decimal("60.20"),
                "propriedade": "PROPRIO",
                "data_ultimo_reteste": hoje - timedelta(days=365 * 2),
                "data_proximo_reteste": hoje + timedelta(days=365 * 3),
                "status": "VAZIO_TRIAGEM"
            }
        )
        if cil_2.status == 'VAZIO_TRIAGEM':
            registrar_envase_cilindro(
                cilindro_id=cil_2.id,
                lote_id=lote_o2_valido.id,
                pressao_bar=200,
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=16),
                client_uuid=get_deterministic_uuid(tenant.id, "cil2-envase"),
                observacoes="Envase medicinal para remessa hospitalar"
            )
        if cil_2.status == 'CHEIO_DISPONIVEL':
            registrar_entrega_cilindro(
                cilindro_id=cil_2.id,
                cliente=clientes[0],
                entrega=entrega,
                documento_fiscal_ref=f"NFE-{sufixo_cidade[:3].upper()}-002",
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=15),
                client_uuid=get_deterministic_uuid(tenant.id, "cil2-entrega")
            )

        # Cilindro 3: Entregue há 45 dias (15 dias excedentes = R$ 52,50) N2 Industrial
        cil_3, _ = Cilindro.objects.get_or_create(
            codigo_qr=f"QR-{sufixo_cidade[:3].upper()}-0103",
            defaults={
                "numero_serie_ogiva": f"SN-{sufixo_cidade[:3].upper()}-903",
                "fabricante": "Cilbras",
                "ano_fabricacao": 2019,
                "modelo": mod_50l,
                "gas_dedicado": gases['N2-IND'],
                "tara_real_kg": Decimal("60.50"),
                "propriedade": "PROPRIO",
                "data_ultimo_reteste": hoje - timedelta(days=365 * 3),
                "data_proximo_reteste": hoje + timedelta(days=365 * 2),
                "status": "VAZIO_TRIAGEM"
            }
        )
        if cil_3.status == 'VAZIO_TRIAGEM':
            registrar_envase_cilindro(
                cilindro_id=cil_3.id,
                lote_id=lote_n2.id,
                pressao_bar=200,
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=48),
                client_uuid=get_deterministic_uuid(tenant.id, "cil3-envase"),
                observacoes="Envase N2 industrial para metalúrgica"
            )
        if cil_3.status == 'CHEIO_DISPONIVEL':
            registrar_entrega_cilindro(
                cilindro_id=cil_3.id,
                cliente=clientes[1],
                documento_fiscal_ref=f"NFE-{sufixo_cidade[:3].upper()}-003",
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=45),
                client_uuid=get_deterministic_uuid(tenant.id, "cil3-entrega")
            )

        # Cilindro 4: Entregue há 95 dias (65 dias excedentes = R$ 227,50 - CRÍTICO) AR Industrial
        cil_4, _ = Cilindro.objects.get_or_create(
            codigo_qr=f"QR-{sufixo_cidade[:3].upper()}-0104",
            defaults={
                "numero_serie_ogiva": f"SN-{sufixo_cidade[:3].upper()}-904",
                "fabricante": "Matheson",
                "ano_fabricacao": 2018,
                "modelo": mod_10l,
                "gas_dedicado": gases['AR-IND'],
                "tara_real_kg": Decimal("12.40"),
                "propriedade": "PROPRIO",
                "data_ultimo_reteste": hoje - timedelta(days=365 * 4),
                "data_proximo_reteste": hoje + timedelta(days=365),
                "status": "VAZIO_TRIAGEM"
            }
        )
        if cil_4.status == 'VAZIO_TRIAGEM':
            registrar_envase_cilindro(
                cilindro_id=cil_4.id,
                lote_id=lote_ar.id,
                pressao_bar=150,
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=98),
                client_uuid=get_deterministic_uuid(tenant.id, "cil4-envase"),
                observacoes="Envase Argônio puro para solda especializada"
            )
        if cil_4.status == 'CHEIO_DISPONIVEL':
            registrar_entrega_cilindro(
                cilindro_id=cil_4.id,
                cliente=clientes[2],
                documento_fiscal_ref=f"NFE-{sufixo_cidade[:3].upper()}-004",
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=95),
                client_uuid=get_deterministic_uuid(tenant.id, "cil4-entrega")
            )

        # Cilindro 5: Vazio recolhido na entrega (Full-for-Empty bilateral)
        cil_5, _ = Cilindro.objects.get_or_create(
            codigo_qr=f"QR-{sufixo_cidade[:3].upper()}-0105",
            defaults={
                "numero_serie_ogiva": f"SN-{sufixo_cidade[:3].upper()}-905",
                "fabricante": "Cilbras",
                "ano_fabricacao": 2017,
                "modelo": mod_50l,
                "gas_dedicado": gases['O2-MED'],
                "tara_real_kg": Decimal("60.00"),
                "propriedade": "PROPRIO",
                "data_ultimo_reteste": hoje - timedelta(days=365 * 2),
                "data_proximo_reteste": hoje + timedelta(days=365 * 3),
                "status": "VAZIO_TRIAGEM"
            }
        )
        # Se estiver em VAZIO_TRIAGEM e ainda não tiver histórico de recolha: simula ciclo completo
        if cil_5.status == 'VAZIO_TRIAGEM' and not MovimentacaoCilindro.objects.filter(cilindro=cil_5, tipo='RECOLHA_CLIENTE').exists():
            registrar_envase_cilindro(
                cilindro_id=cil_5.id,
                lote_id=lote_o2_valido.id,
                pressao_bar=200,
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=40),
                client_uuid=get_deterministic_uuid(tenant.id, "cil5-envase"),
                observacoes="Envase para fornecimento anterior"
            )
            registrar_entrega_cilindro(
                cilindro_id=cil_5.id,
                cliente=clientes[0],
                documento_fiscal_ref=f"NFE-{sufixo_cidade[:3].upper()}-005-ANT",
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=35),
                client_uuid=get_deterministic_uuid(tenant.id, "cil5-entrega")
            )
            registrar_recolha_cilindro(
                cilindro_id=cil_5.id,
                cliente=clientes[0],
                entrega=entrega,
                documento_fiscal_ref=f"NFE-{sufixo_cidade[:3].upper()}-005-RET",
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(hours=2),
                client_uuid=get_deterministic_uuid(tenant.id, "cil5-recolha"),
                observacao="Recolhido casco vazio na troca bilateral Full-for-Empty"
            )

        # Cilindro 6: Enviado para Reteste Quinquenal
        cil_6, _ = Cilindro.objects.get_or_create(
            codigo_qr=f"QR-{sufixo_cidade[:3].upper()}-0106",
            defaults={
                "numero_serie_ogiva": f"SN-{sufixo_cidade[:3].upper()}-906",
                "fabricante": "Mannesmann",
                "ano_fabricacao": 2016,
                "modelo": mod_50l,
                "gas_dedicado": gases['N2-IND'],
                "tara_real_kg": Decimal("59.90"),
                "propriedade": "PROPRIO",
                "data_ultimo_reteste": hoje - timedelta(days=365 * 5),
                "data_proximo_reteste": hoje - timedelta(days=5),
                "status": "VAZIO_TRIAGEM"
            }
        )
        if cil_6.status == 'VAZIO_TRIAGEM':
            enviar_para_reteste(
                cilindro_id=cil_6.id,
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=3),
                client_uuid=get_deterministic_uuid(tenant.id, "cil6-reteste"),
                observacao="Enviado para reteste quinquenal na Retestadora Brasil"
            )

        # Cilindro 7: Cilindro com lote sob Alerta de Recall ANVISA (entregue no Hospital Santa Lúcia)
        cil_7, _ = Cilindro.objects.get_or_create(
            codigo_qr=f"QR-{sufixo_cidade[:3].upper()}-0107",
            defaults={
                "numero_serie_ogiva": f"SN-{sufixo_cidade[:3].upper()}-907",
                "fabricante": "Cilbras",
                "ano_fabricacao": 2020,
                "modelo": mod_50l,
                "gas_dedicado": gases['O2-MED'],
                "tara_real_kg": Decimal("60.10"),
                "propriedade": "PROPRIO",
                "data_ultimo_reteste": hoje - timedelta(days=365 * 2),
                "data_proximo_reteste": hoje + timedelta(days=365 * 3),
                "status": "VAZIO_TRIAGEM"
            }
        )
        if cil_7.status == 'VAZIO_TRIAGEM':
            registrar_envase_cilindro(
                cilindro_id=cil_7.id,
                lote_id=lote_o2_recall.id,
                pressao_bar=200,
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=60),
                client_uuid=get_deterministic_uuid(tenant.id, "cil7-envase"),
                observacoes="Envase do lote sob monitoramento ANVISA por subespecificação de pureza"
            )
        if cil_7.status == 'CHEIO_DISPONIVEL':
            registrar_entrega_cilindro(
                cilindro_id=cil_7.id,
                cliente=clientes[0],
                documento_fiscal_ref=f"NFE-{sufixo_cidade[:3].upper()}-007",
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=50),
                client_uuid=get_deterministic_uuid(tenant.id, "cil7-entrega")
            )

        # Cilindro 8: Cilindro Baixado/Condenado (estado terminal da FSM)
        cil_8, _ = Cilindro.objects.get_or_create(
            codigo_qr=f"QR-{sufixo_cidade[:3].upper()}-0108",
            defaults={
                "numero_serie_ogiva": f"SN-{sufixo_cidade[:3].upper()}-908",
                "fabricante": "Cilbras",
                "ano_fabricacao": 2012,
                "modelo": mod_50l,
                "gas_dedicado": gases['O2-MED'],
                "tara_real_kg": Decimal("58.20"),
                "propriedade": "PROPRIO",
                "data_ultimo_reteste": hoje - timedelta(days=365 * 6),
                "data_proximo_reteste": hoje - timedelta(days=365),
                "status": "VAZIO_TRIAGEM"
            }
        )
        if cil_8.status == 'VAZIO_TRIAGEM':
            baixar_cilindro(
                cilindro_id=cil_8.id,
                motivo="Condenado na inspeção visual: trinca mecânica na ogiva reprovada em triagem",
                usuario=user_vendedor,
                ocorrido_em=agora - timedelta(days=1),
                client_uuid=get_deterministic_uuid(tenant.id, "cil8-baixa")
            )

        # Cálculo do Radar de Comodato
        radar = calcular_radar_comodato_tenant()
        print(f"[{tenant.nome_fantasia}] Radar de Comodato Atualizado:")
        print(f"  * Cilindros Retidos: {radar['total_cilindros_em_posse']}")
        print(f"  * Sem Giro > 30d: {radar['cilindros_sem_giro_30_mais']}")
        print(f"  * Receita de Locação Acumulada: R$ {radar['receita_locacao_acumulada']:.2f}")
        print(f"  * Peso Total Real Carregado na Entrega #{entrega.id}: {entrega.peso_total_carregado} kg ({entrega.percentual_lotacao}% ocupação)")


def run():
    print("Iniciando povoamento Multi-Tenant com FSM, Ledger e Imutabilidade (Sprint 5A.2)...")

    gases = criar_gases_globais()

    tenant_a, _ = Tenant.objects.get_or_create(
        cnpj="10.100.100/0001-10",
        defaults={
            "id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
            "razao_social": "Oxigênio Brasília Distribuidora Ltda",
            "nome_fantasia": "Oxigênio Brasília",
            "plano": "PRO",
            "limite_cilindros": 800,
            "ativo": True
        }
    )

    tenant_b, _ = Tenant.objects.get_or_create(
        cnpj="20.200.200/0001-20",
        defaults={
            "id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
            "razao_social": "Gases Goiás Comércio e Distribuição S/A",
            "nome_fantasia": "Gases Goiás",
            "plano": "ENTERPRISE",
            "limite_cilindros": 1500,
            "ativo": True
        }
    )

    # Responsabilidade Técnica e Perfil Regulatório ANVISA - Tenant A (Brasília)
    with tenant_context(tenant_a):
        rt_a, _ = ResponsavelTecnico.objects.get_or_create(
            nome_completo="Dra. Camila Rocha",
            conselho_classe="CRF",
            numero_registro="4589",
            uf_conselho="DF",
            defaults={
                "vigencia_inicio": timezone.now().date() - timedelta(days=365),
                "vigencia_fim": timezone.now().date() + timedelta(days=365),
                "ativo": True,
            }
        )
    PerfilRegulatorioTenant.objects.get_or_create(
        tenant=tenant_a,
        defaults={
            "modo_operacao": "MISTO",
            "afe_numero": "AFE-1.12345.6",
            "afe_validade": timezone.now().date() + timedelta(days=365),
            "licenca_sanitaria_numero": "VISA-DF-2026/890",
            "licenca_sanitaria_validade": timezone.now().date() + timedelta(days=365),
            "cbpf_cbpda_numero": "CBPF-ANVISA-2025/112",
            "cbpf_cbpda_validade": timezone.now().date() + timedelta(days=365),
            "responsavel_tecnico_vigente": rt_a,
        }
    )

    # Responsabilidade Técnica e Perfil Regulatório ANVISA - Tenant B (Goiás)
    with tenant_context(tenant_b):
        rt_b, _ = ResponsavelTecnico.objects.get_or_create(
            nome_completo="Dr. Marcos Vinicius",
            conselho_classe="CRQ",
            numero_registro="1234",
            uf_conselho="GO",
            defaults={
                "vigencia_inicio": timezone.now().date() - timedelta(days=365),
                "vigencia_fim": timezone.now().date() + timedelta(days=365),
                "ativo": True,
            }
        )
    PerfilRegulatorioTenant.objects.get_or_create(
        tenant=tenant_b,
        defaults={
            "modo_operacao": "ENVASADORA",
            "afe_numero": "AFE-1.65432.1",
            "afe_validade": timezone.now().date() + timedelta(days=365),
            "licenca_sanitaria_numero": "VISA-GO-2026/432",
            "licenca_sanitaria_validade": timezone.now().date() + timedelta(days=365),
            "cbpf_cbpda_numero": "CBPF-ANVISA-2025/334",
            "cbpf_cbpda_validade": timezone.now().date() + timedelta(days=365),
            "responsavel_tecnico_vigente": rt_b,
        }
    )

    # Superusuário Administrativo via Variáveis de Ambiente (.env)
    superuser_username = os.getenv("DJANGO_SUPERUSER_USERNAME")
    superuser_password = os.getenv("DJANGO_SUPERUSER_PASSWORD")
    superuser_email = os.getenv("DJANGO_SUPERUSER_EMAIL", "admin@bsbgases.com.br")
    if superuser_username and superuser_password:
        admin_user, created = User.objects.get_or_create(
            username=superuser_username,
            defaults={"email": superuser_email, "is_staff": True, "is_superuser": True, "tipo_usuario": "ADMIN"}
        )
        if created or not admin_user.check_password(superuser_password):
            admin_user.set_password(superuser_password)
            admin_user.is_staff = True
            admin_user.is_superuser = True
            admin_user.tipo_usuario = "ADMIN"
            admin_user.save()
            print(f"Superusuário administrativo configurado via .env: {superuser_username}")

    default_pwd = os.getenv("DEFAULT_USER_PASSWORD", "Agy@Gas2026!Segura")

    user_bsb, _ = User.objects.get_or_create(
        username="gerente.bsb",
        defaults={"email": "gerente@bsbgases.com.br", "tipo_usuario": "GERENTE"}
    )
    if not user_bsb.check_password(default_pwd):
        user_bsb.set_password(default_pwd)
        user_bsb.save()

    user_go, _ = User.objects.get_or_create(
        username="gerente.go",
        defaults={"email": "gerente@gasesgoias.com.br", "tipo_usuario": "GERENTE"}
    )
    if not user_go.check_password(default_pwd):
        user_go.set_password(default_pwd)
        user_go.save()

    Membership.objects.get_or_create(user=user_bsb, tenant=tenant_a, defaults={"papel": "GERENTE", "ativo": True})
    Membership.objects.get_or_create(user=user_go, tenant=tenant_b, defaults={"papel": "GERENTE", "ativo": True})

    popular_tenant(tenant_a, user_bsb, "Brasília", gases)
    popular_tenant(tenant_b, user_go, "Goiânia", gases)

    print("\nPovoamento da Sprint 5A.2 concluído com 100% de sucesso e rastreabilidade íntegra!")


if __name__ == '__main__':
    run()
