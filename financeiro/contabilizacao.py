"""
Núcleo de contabilização automática por eventos de domínio (Sprint 9B - Tarefas 9 e 10 / Correções F-03, F-12, F-19).
Idempotente por (evento, origem_id).
Falha de handler nunca perde o evento: grava PendenciaContabilizacao e não bloqueia a operação de origem.
"""

import logging
import traceback
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.modulos import is_modulo_ativo
from core.money import quantize
from financeiro.models import (
    LancamentoContabil,
    ParametroFinanceiroTenant,
    PendenciaContabilizacao,
    PlanoContas,
    TituloFinanceiro,
)
from financeiro.services.razao import lancar
from financeiro.services.titulos import criar_titulo, obter_parametros_financeiros

logger = logging.getLogger(__name__)


# ==============================================================================
# DISPACHER SEGURO E IDEMPOTENTE COM RESILIÊNCIA A FALHAS (Tarefa 10)
# ==============================================================================

def processar_evento_financeiro(evento: str, payload: dict) -> dict:
    """
    Roteador seguro e idempotente de contabilização por evento.
    Se o módulo financeiro estiver inativo, ignora silenciosamente.
    Se ocorrer qualquer falha durante a contabilização, registra em PendenciaContabilizacao
    e NUNCA propaga a exceção para não bloquear a operação de negócio original (venda, lote, etc.).
    """
    tenant = payload.get('tenant')
    if not tenant:
        logger.warning(f"[Contabilização] Evento '{evento}' ignorado: tenant não informado no payload.")
        return {'status': 'IGNORADO', 'motivo': 'Tenant não informado'}

    if not is_modulo_ativo(tenant, 'financeiro'):
        logger.info(f"[Contabilização] Evento '{evento}' ignorado: módulo financeiro inativo no Tenant '{tenant.nome}'.")
        return {'status': 'IGNORADO_SEM_MODULO_FINANCEIRO'}

    origem_id = str(
        payload.get('origem_id') or
        payload.get('venda_id') or
        payload.get('fatura_id') or
        payload.get('lote_id') or
        payload.get('entrada_id') or
        payload.get('baixa_id') or
        payload.get('cilindro_id') or
        payload.get('titulo_id') or
        ''
    ).strip()

    # Idempotência: verifica se o lançamento contábil já foi escriturado para este evento e origem
    if origem_id:
        lancamento_existente = LancamentoContabil.objects.filter(
            tenant=tenant,
            origem_tipo=evento,
            origem_id=origem_id
        ).first()
        if lancamento_existente:
            logger.info(f"[Contabilização] Evento '{evento}' já processado anteriormente para origem_id '{origem_id}'.")
            return {
                'status': 'JA_PROCESSADO',
                'lancamento_id': lancamento_existente.id,
                'numero': lancamento_existente.numero
            }

    # Despacho para o handler especializado
    handler = HANDLERS_CONTABILIZACAO.get(evento)
    if not handler:
        logger.warning(f"[Contabilização] Nenhum handler contábil registrado para o evento '{evento}'.")
        return {'status': 'EVENTO_SEM_HANDLER', 'evento': evento}

    try:
        resultado = handler(tenant=tenant, payload=payload, origem_id=origem_id)
        return {'status': 'SUCESSO', 'resultado': resultado}
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        logger.error(f"[Contabilização] Erro ao contabilizar evento '{evento}' (Origem: {origem_id}): {err_msg}")

        # Grava pendência para reprocessamento manual / assíncrono (Tarefa 10)
        try:
            pendencia, criada = PendenciaContabilizacao.objects.get_or_create(
                tenant=tenant,
                evento=evento,
                origem_id=origem_id,
                resolvido=False,
                defaults={
                    'payload_json': {k: str(v) for k, v in payload.items() if k != 'tenant'},
                    'erro_mensagem': err_msg,
                    'tentativas': 1
                }
            )
            if not criada:
                pendencia.tentativas += 1
                pendencia.erro_mensagem = err_msg
                pendencia.save(update_fields=['tentativas', 'erro_mensagem'])
        except Exception:
            logger.exception("[Contabilização] Erro crítico ao gravar PendenciaContabilizacao.")

        return {
            'status': 'PENDENCIA_REGISTRADA',
            'evento': evento,
            'origem_id': origem_id,
            'erro': str(exc)
        }


# ==============================================================================
# HANDLERS ESPECIALIZADOS DE EVENTOS CONTÁBEIS (Tarefa 9)
# ==============================================================================

@transaction.atomic
def contabilizar_venda_faturada(*, tenant, payload: dict, origem_id: str):
    """
    1. Venda Faturada:
       (D) Clientes (1.1.2.01)
       (C) Receita por produto (3.1.1 Medicinal / 3.1.2 Industrial / 3.1.5 Revenda)
       Criação de Título Financeiro a Receber.
    2. Venda Faturada (Deduções - F-19):
       (D) Deduções da Receita (3.2)
       (C) Obrigações Fiscais (2.1.2.01)
    3. Venda Faturada (Custo / CPV):
       (D) CPV (4.1.1 Gás / 4.1.5 Mercadorias)
       (C) Estoque de Produto Acabado (1.1.3.02)
    """
    assert_tenant_writable(tenant)

    venda_id = origem_id
    val_raw = payload.get('valor_total') or payload.get('valor_bruto') or '0.00'
    valor_total = quantize(Decimal(str(val_raw)), 2)

    custo_raw = payload.get('custo_total') or payload.get('valor_custo') or '0.00'
    custo_total = quantize(Decimal(str(custo_raw)), 2)
    dt_comp = timezone.localdate()

    c_clientes = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.2.01').first()

    # Receita padrão de acordo com o tipo de produto (3.1.1 Medicinal / 3.1.2 Industrial)
    tipo_prod = str(payload.get('tipo_produto', '')).upper()
    if 'MED' in tipo_prod:
        c_receita = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='3.1.1').first()
    else:
        c_receita = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='3.1.2').first()

    if not c_receita:
        c_receita = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__startswith='3.1', tipo='ANALITICA').first()

    # 1. Lançamento da Venda Bruta
    partidas_venda = [
        {'conta': c_clientes, 'tipo_partida': 'DEBITO', 'valor': valor_total},
        {'conta': c_receita, 'tipo_partida': 'CREDITO', 'valor': valor_total},
    ]

    lanc_venda, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Faturamento de Venda #{venda_id}",
        partidas=partidas_venda,
        origem_tipo='venda_faturada',
        origem_id=venda_id
    )

    # Cria Título a Receber (Tarefa 1)
    cliente_obj = None
    cliente_id = payload.get('cliente_id')
    if cliente_id:
        from clientes.models import Cliente
        cliente_obj = Cliente.objects.filter(tenant=tenant, id=cliente_id).first()

    titulo = criar_titulo(
        tenant=tenant,
        tipo='RECEBER',
        conta_gerencial=c_receita,
        valor_bruto=valor_total,
        cliente=cliente_obj,
        origem_tipo='VENDA',
        origem_id=venda_id,
        historico=f"Venda Faturada #{venda_id}"
    )

    # 2. Deduções da Receita (Correção F-19)
    param = obter_parametros_financeiros(tenant)
    aliquota_deducao = param.aliquota_efetiva_deducoes

    if payload.get('valor_deducoes') is not None or payload.get('deducoes') is not None:
        valor_deducoes = quantize(Decimal(str(payload.get('valor_deducoes') or payload.get('deducoes'))), 2)
        desc_deducoes = f"Deduções Fiscais sobre Venda #{venda_id}"
    else:
        valor_deducoes = quantize(valor_total * aliquota_deducao, 2)
        desc_deducoes = f"Deduções Estimadas ({aliquota_deducao * 100}%) sobre Venda #{venda_id}"

    if valor_deducoes > Decimal('0.00'):
        c_deducoes = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['3.2.1', '3.2.2', '3.2.3', '3.2.4'], tipo='ANALITICA').first() or \
                     PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__startswith='3.2', tipo='ANALITICA').first()
        c_obrig_fiscais = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['2.1.2.01', '2.1.2'], tipo='ANALITICA').first()

        if c_deducoes and c_obrig_fiscais:
            lancar(
                tenant=tenant,
                data_competencia=dt_comp,
                historico=desc_deducoes,
                partidas=[
                    {'conta': c_deducoes, 'tipo_partida': 'DEBITO', 'valor': valor_deducoes},
                    {'conta': c_obrig_fiscais, 'tipo_partida': 'CREDITO', 'valor': valor_deducoes},
                ],
                origem_tipo='venda_faturada_deducoes',
                origem_id=venda_id
            )

    # 3. Custo dos Produtos Vendidos (CPV)
    if custo_total > Decimal('0.00'):
        c_cpv = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__startswith='4.1', tipo='ANALITICA').first()
        c_estoque_acabado = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.3.02').first()

        if c_cpv and c_estoque_acabado:
            lancar(
                tenant=tenant,
                data_competencia=dt_comp,
                historico=f"CPV Apurado da Venda #{venda_id}",
                partidas=[
                    {'conta': c_cpv, 'tipo_partida': 'DEBITO', 'valor': custo_total},
                    {'conta': c_estoque_acabado, 'tipo_partida': 'CREDITO', 'valor': custo_total},
                ],
                origem_tipo='venda_faturada_custo',
                origem_id=venda_id
            )

    return {'titulo_id': titulo.id, 'lancamento_id': lanc_venda.id}


@transaction.atomic
def contabilizar_fatura_estadia_fechada(*, tenant, payload: dict, origem_id: str):
    """
    Fatura de Estadia Fechada:
    (D) Clientes (1.1.2.01)
    (C) Receita de Locação e Estadia (3.1.3)
    Gera Título Financeiro a Receber.
    """
    assert_tenant_writable(tenant)

    fatura_id = origem_id
    valor_total = quantize(Decimal(str(payload.get('valor_total', '0.00'))), 2)
    dt_comp = timezone.localdate()

    c_clientes = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.2.01').first()
    c_receita_locacao = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='3.1.3').first()

    partidas = [
        {'conta': c_clientes, 'tipo_partida': 'DEBITO', 'valor': valor_total},
        {'conta': c_receita_locacao, 'tipo_partida': 'CREDITO', 'valor': valor_total},
    ]

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Fechamento Fatura de Estadia #{fatura_id}",
        partidas=partidas,
        origem_tipo='fatura_estadia_fechada',
        origem_id=fatura_id
    )

    cliente_obj = None
    cliente_id = payload.get('cliente_id')
    if cliente_id:
        from clientes.models import Cliente
        cliente_obj = Cliente.objects.filter(tenant=tenant, id=cliente_id).first()

    titulo = criar_titulo(
        tenant=tenant,
        tipo='RECEBER',
        conta_gerencial=c_receita_locacao,
        valor_bruto=valor_total,
        cliente=cliente_obj,
        origem_tipo='FATURA_ESTADIA',
        origem_id=fatura_id,
        historico=f"Fatura de Estadia de Cilindros #{fatura_id}"
    )

    return {'titulo_id': titulo.id, 'lancamento_id': lanc.id}


@transaction.atomic
def contabilizar_entrada_gas_granel(*, tenant, payload: dict, origem_id: str):
    """
    Entrada de Gás a Granel:
    (D) Estoque de Gás a Granel (1.1.3.01)
    (C) Fornecedores (2.1.1) (e impostos a recuperar se houver)
    Gera Título a Pagar.
    """
    assert_tenant_writable(tenant)

    entrada_id = origem_id
    custo_total = quantize(Decimal(str(payload.get('custo_total') or payload.get('valor_total') or '0.00')), 2)
    valor_impostos = quantize(Decimal(str(payload.get('valor_impostos_recuperar') or '0.00')), 2)
    dt_comp = timezone.localdate()

    c_estoque_granel = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.3.01').first()
    c_fornecedores = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['2.1.1.01', '2.1.1']).first()

    fornecedor_id = payload.get('fornecedor_id')
    fornecedor_obj = None
    if fornecedor_id:
        from financeiro.models import Fornecedor
        fornecedor_obj = Fornecedor.objects.filter(tenant=tenant, id=fornecedor_id).first()

    if valor_impostos > Decimal('0.00') and custo_total > valor_impostos:
        valor_estoque = quantize(custo_total - valor_impostos, 2)
        c_impostos = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__startswith='1.1.4', tipo='ANALITICA').first()
        partidas = [
            {'conta': c_estoque_granel, 'tipo_partida': 'DEBITO', 'valor': valor_estoque},
            {'conta': c_impostos, 'tipo_partida': 'DEBITO', 'valor': valor_impostos},
            {'conta': c_fornecedores, 'tipo_partida': 'CREDITO', 'valor': custo_total},
        ]
    else:
        partidas = [
            {'conta': c_estoque_granel, 'tipo_partida': 'DEBITO', 'valor': custo_total},
            {'conta': c_fornecedores, 'tipo_partida': 'CREDITO', 'valor': custo_total},
        ]

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Entrada Gás Granel Tanque #{payload.get('tanque_id') or entrada_id}",
        partidas=partidas,
        origem_tipo='entrada_gas_granel',
        origem_id=entrada_id
    )

    titulo = criar_titulo(
        tenant=tenant,
        tipo='PAGAR',
        conta_gerencial=c_estoque_granel,
        valor_bruto=custo_total,
        fornecedor=fornecedor_obj,
        beneficiario_texto=None if fornecedor_obj else f"Fornecedor Gás Granel Ref: Entrada #{entrada_id}",
        origem_tipo='COMPRA_GRANEL',
        origem_id=entrada_id,
        historico=f"Aquisição de Gás Criogênico a Granel #{entrada_id}"
    )

    return {'titulo_id': titulo.id, 'lancamento_id': lanc.id}


@transaction.atomic
def contabilizar_lote_envase_fechado(*, tenant, payload: dict, origem_id: str):
    """
    Lote de Envase Fechado:
    (D) Estoque de Produto Acabado (1.1.3.02)
    (C) Estoque de Gás a Granel (1.1.3.01)
    (C) Energia de Rampa (4.1.3)
    (C) Mão de Obra Direta da Rampa (4.1.6)
    """
    assert_tenant_writable(tenant)

    lote_id = origem_id
    custo_gas = quantize(Decimal(str(payload.get('custo_gas', '0.00'))), 2)
    custo_energia = quantize(Decimal(str(payload.get('custo_energia', '0.00'))), 2)
    custo_mod = quantize(Decimal(str(payload.get('custo_mod', '0.00'))), 2)
    custo_total = quantize(Decimal(str(payload.get('custo_total') or (custo_gas + custo_energia + custo_mod))), 2)
    if custo_total <= Decimal('0.00'):
        custo_total = quantize(custo_gas + custo_energia + custo_mod, 2)
    dt_comp = timezone.localdate()

    c_estoque_acabado = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.3.02').first()
    c_estoque_granel = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.3.01').first()
    c_energia = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='4.1.3').first()
    c_mod = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='4.1.6').first()

    partidas = [
        {'conta': c_estoque_acabado, 'tipo_partida': 'DEBITO', 'valor': custo_total},
        {'conta': c_estoque_granel, 'tipo_partida': 'CREDITO', 'valor': custo_gas},
    ]
    if custo_energia > Decimal('0.00') and c_energia:
        partidas.append({'conta': c_energia, 'tipo_partida': 'CREDITO', 'valor': custo_energia})
    if custo_mod > Decimal('0.00') and c_mod:
        partidas.append({'conta': c_mod, 'tipo_partida': 'CREDITO', 'valor': custo_mod})

    # Resíduo para fechar balanceado
    soma_deb = sum(p['valor'] for p in partidas if p['tipo_partida'] == 'DEBITO')
    soma_cred = sum(p['valor'] for p in partidas if p['tipo_partida'] == 'CREDITO')
    if soma_deb != soma_cred:
        dif = soma_deb - soma_cred
        # Ajusta no crédito de gás
        partidas[1]['valor'] = quantize(partidas[1]['valor'] + dif, 2)

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Produção Lote de Envase #{lote_id} - {payload.get('total_cilindros')} cilindros",
        partidas=partidas,
        origem_tipo='lote_envase_fechado',
        origem_id=lote_id
    )

    return {'lancamento_id': lanc.id}


@transaction.atomic
def contabilizar_perda_gas_registrada(*, tenant, payload: dict, origem_id: str):
    """
    Perda de Gás Registrada (Boil-off / Purga):
    (D) Perdas por Evaporação e Purga (4.1.2)
    (C) Estoque de Gás a Granel (1.1.3.01)
    """
    assert_tenant_writable(tenant)

    custo_perda = quantize(Decimal(str(payload.get('valor_perda', payload.get('custo_total', '0.00')))), 2)
    if custo_perda <= Decimal('0.00'):
        return {'status': 'VALOR_ZERO'}

    dt_comp = timezone.localdate()
    c_perdas = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='4.1.2').first()
    c_estoque_granel = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.3.01').first()

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Perda por Evaporação e Purga Tanque #{payload.get('tanque_id')}",
        partidas=[
            {'conta': c_perdas, 'tipo_partida': 'DEBITO', 'valor': custo_perda},
            {'conta': c_estoque_granel, 'tipo_partida': 'CREDITO', 'valor': custo_perda},
        ],
        origem_tipo='perda_gas_registrada',
        origem_id=origem_id
    )

    return {'lancamento_id': lanc.id}


@transaction.atomic
def contabilizar_compra_imobilizado(*, tenant, payload: dict, origem_id: str):
    """
    Compra de Imobilizado:
    (D) Imobilizado (1.2.1.01)
    (C) Fornecedores (2.1.1)
    Gera Título a Pagar.
    """
    assert_tenant_writable(tenant)

    valor = quantize(Decimal(str(payload.get('valor_total') or payload.get('valor') or '0.00')), 2)
    dt_comp = timezone.localdate()

    c_imob = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.2.1.01').first()
    c_fornecedores = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['2.1.1.01', '2.1.1']).first()

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Aquisição de Ativo Imobilizado Ref: {origem_id}",
        partidas=[
            {'conta': c_imob, 'tipo_partida': 'DEBITO', 'valor': valor},
            {'conta': c_fornecedores, 'tipo_partida': 'CREDITO', 'valor': valor},
        ],
        origem_tipo='compra_imobilizado',
        origem_id=origem_id
    )

    fornecedor_id = payload.get('fornecedor_id')
    fornecedor_obj = None
    if fornecedor_id:
        from financeiro.models import Fornecedor
        fornecedor_obj = Fornecedor.objects.filter(tenant=tenant, id=fornecedor_id).first()

    titulo = criar_titulo(
        tenant=tenant,
        tipo='PAGAR',
        conta_gerencial=c_imob,
        valor_bruto=valor,
        fornecedor=fornecedor_obj,
        beneficiario_texto=None if fornecedor_obj else (payload.get('fornecedor_nome') or f"Fornecedor Imobilizado Ref: {origem_id}"),
        origem_tipo='COMPRA_IMOBILIZADO',
        origem_id=origem_id,
        historico=f"Aquisição de Imobilizado #{origem_id}"
    )

    return {'titulo_id': titulo.id, 'lancamento_id': lanc.id}


@transaction.atomic
def contabilizar_reteste_concluido(*, tenant, payload: dict, origem_id: str):
    """
    Reteste Concluído:
    (D) Retestes Despesa CPV (4.1.4) OU Componente Capitalizado (1.2.1.07), conforme política
    (C) Fornecedores (2.1.1)
    """
    assert_tenant_writable(tenant)

    custo_reteste = quantize(Decimal(str(payload.get('valor_servico') or payload.get('custo_servico_reteste') or payload.get('custo') or '0.00')), 2)
    if custo_reteste <= Decimal('0.00'):
        return {'status': 'SEM_CUSTO_RETESTE'}

    politica = 'CAPITALIZAR_COMPONENTE' if payload.get('capitalizar') else payload.get('politica_reteste', 'DESPESA_CPV')
    if politica == 'CAPITALIZAR_COMPONENTE':
        c_debito = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.2.1.07').first()
    else:
        c_debito = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='4.1.4').first()

    c_fornecedores = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['2.1.1.01', '2.1.1']).first()
    dt_comp = timezone.localdate()

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Reteste Hidrostático Cilindro #{payload.get('cilindro_id') or origem_id} [{politica}]",
        partidas=[
            {'conta': c_debito, 'tipo_partida': 'DEBITO', 'valor': custo_reteste},
            {'conta': c_fornecedores, 'tipo_partida': 'CREDITO', 'valor': custo_reteste},
        ],
        origem_tipo='reteste_concluido',
        origem_id=origem_id
    )

    return {'lancamento_id': lanc.id}


@transaction.atomic
def contabilizar_baixa_patrimonial(*, tenant, payload: dict, origem_id: str):
    """
    Baixa Patrimonial (Cilindros / Veículos):
    (D) Depreciação Acumulada (1.2.1.02)
    (D) Banco/Caixa ou Clientes (valor recebido / valor venda)
    (C) Imobilizado (1.2.1.01) (custo original)
    (D/C) Diferença apurada em 8.2 (Resultado na Baixa de Imobilizado)
    """
    assert_tenant_writable(tenant)

    custo_original = quantize(Decimal(str(payload.get('custo_original') or payload.get('valor_contabil_baixa') or '0.00')), 2)
    deprec_acumulada = quantize(Decimal(str(payload.get('depreciacao_acumulada') or '0.00')), 2)
    valor_venda = quantize(Decimal(str(payload.get('valor_venda') or payload.get('valor_recebido') or '0.00')), 2)
    dt_comp = timezone.localdate()

    c_imob = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.2.1.01').first()
    c_deprec = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.2.1.02').first()
    c_banco = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.1.01').first()
    c_resultado_baixa = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='8.2').first()

    partidas = []
    # (C) Imobilizado pelo custo original
    partidas.append({'conta': c_imob, 'tipo_partida': 'CREDITO', 'valor': custo_original})

    # (D) Depreciação acumulada
    if deprec_acumulada > Decimal('0.00') and c_deprec:
        partidas.append({'conta': c_deprec, 'tipo_partida': 'DEBITO', 'valor': deprec_acumulada})

    # (D) Caixa/Banco ou Clientes
    if valor_venda > Decimal('0.00') and c_banco:
        partidas.append({'conta': c_banco, 'tipo_partida': 'DEBITO', 'valor': valor_venda})

    # Diferença no resultado na baixa de imobilizado (8.2)
    total_deb = sum(p['valor'] for p in partidas if p['tipo_partida'] == 'DEBITO')
    total_crd = sum(p['valor'] for p in partidas if p['tipo_partida'] == 'CREDITO')

    if total_deb > total_crd:
        ganho = quantize(total_deb - total_crd, 2)
        partidas.append({'conta': c_resultado_baixa, 'tipo_partida': 'CREDITO', 'valor': ganho})
    elif total_crd > total_deb:
        perda = quantize(total_crd - total_deb, 2)
        partidas.append({'conta': c_resultado_baixa, 'tipo_partida': 'DEBITO', 'valor': perda})

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Baixa Patrimonial #{origem_id} Tipo: {payload.get('tipo', 'Alienação')}",
        partidas=partidas,
        origem_tipo='baixa_patrimonial',
        origem_id=origem_id
    )

    return {'lancamento_id': lanc.id}


@transaction.atomic
def contabilizar_extravio_cobrado(*, tenant, payload: dict, origem_id: str):
    """
    Extravio Cobrado / Indenização de Cascos:
    (D) Clientes (1.1.2.01)
    (C) Outras Receitas Operacionais - Indenizações por Extravio (8.1)
    Gera Título a Receber.
    """
    assert_tenant_writable(tenant)

    v_indenizacao = quantize(Decimal(str(payload.get('valor_indenizacao', '0.00'))), 2)
    dt_comp = timezone.localdate()

    c_clientes = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.2.01').first()
    c_outras_rec = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='8.1').first()

    partidas = [
        {'conta': c_clientes, 'tipo_partida': 'DEBITO', 'valor': v_indenizacao},
        {'conta': c_outras_rec, 'tipo_partida': 'CREDITO', 'valor': v_indenizacao},
    ]

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Indenização Extravio Cilindro #{payload.get('cilindro_id') or origem_id}",
        partidas=partidas,
        origem_tipo='extravio_cobrado',
        origem_id=origem_id
    )

    cliente_obj = None
    cliente_id = payload.get('cliente_id')
    if cliente_id:
        from clientes.models import Cliente
        cliente_obj = Cliente.objects.filter(tenant=tenant, id=cliente_id).first()

    titulo = criar_titulo(
        tenant=tenant,
        tipo='RECEBER',
        conta_gerencial=c_outras_rec,
        valor_bruto=v_indenizacao,
        cliente=cliente_obj,
        origem_tipo='EXTRAVIO',
        origem_id=origem_id,
        historico=f"Cobrança Indenização Extravio Cilindro #{payload.get('cilindro_id') or origem_id}"
    )

    return {'titulo_id': titulo.id, 'lancamento_id': lanc.id}


@transaction.atomic
def contabilizar_caucao_recebida(*, tenant, payload: dict, origem_id: str):
    """
    Caução de Cilindro Recebida (Passivo Circulante):
    (D) Banco/Caixa (1.1.1.01)
    (C) Cauções de Cilindros Recebidas (2.1.5.01)
    """
    assert_tenant_writable(tenant)

    valor = quantize(Decimal(str(payload.get('valor_caucao') or payload.get('valor') or '0.00')), 2)
    dt_comp = timezone.localdate()

    c_banco = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.1.01').first()
    c_caucao = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['2.1.5.01', '2.1.5']).first()

    partidas = [
        {'conta': c_banco, 'tipo_partida': 'DEBITO', 'valor': valor},
        {'conta': c_caucao, 'tipo_partida': 'CREDITO', 'valor': valor},
    ]

    lanc, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Recebimento de Caução de Cilindros Ref: {origem_id}",
        partidas=partidas,
        origem_tipo='caucao_recebida',
        origem_id=origem_id
    )

    return {'lancamento_id': lanc.id}


# ==============================================================================
# REPROCESSAMENTO MANUAL DE PENDÊNCIAS (Tarefa 10)
# ==============================================================================

@transaction.atomic
def reprocessar_pendencia(pendencia_id: int, usuario=None) -> PendenciaContabilizacao:
    """
    Reprocessa uma pendência de contabilização anteriormente gravada por falha transitória.
    """
    pendencia = PendenciaContabilizacao.objects.select_for_update().get(id=pendencia_id)
    if pendencia.resolvido:
        return pendencia

    pendencia.tentativas += 1
    tenant = pendencia.tenant
    payload = dict(pendencia.payload_json or {})
    payload['tenant'] = tenant

    res = processar_evento_financeiro(pendencia.evento, payload)
    if res.get('status') in ('SUCESSO', 'JA_PROCESSADO'):
        pendencia.resolvido = True
        pendencia.resolvido_em = timezone.now()
        pendencia.save(update_fields=['resolvido', 'resolvido_em', 'tentativas'])
    else:
        pendencia.erro_mensagem = str(res.get('erro', 'Falha na reexecução'))
        pendencia.save(update_fields=['tentativas', 'erro_mensagem'])

    return pendencia


# Mapa de registro de handlers
HANDLERS_CONTABILIZACAO = {
    'venda_faturada': contabilizar_venda_faturada,
    'fatura_estadia_fechada': contabilizar_fatura_estadia_fechada,
    'entrada_gas_granel': contabilizar_entrada_gas_granel,
    'lote_envase_fechado': contabilizar_lote_envase_fechado,
    'perda_gas_registrada': contabilizar_perda_gas_registrada,
    'compra_imobilizado': contabilizar_compra_imobilizado,
    'reteste_concluido': contabilizar_reteste_concluido,
    'baixa_patrimonial': contabilizar_baixa_patrimonial,
    'extravio_registrado': contabilizar_extravio_cobrado,
    'extravio_cobrado': contabilizar_extravio_cobrado,
    'caucao_recebida': contabilizar_caucao_recebida,
}
