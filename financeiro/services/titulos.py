"""
Serviços de gestão de títulos a pagar e a receber, parcelas, rateios e alçadas (Sprint 9B - Tarefas 1, 2, 3, 4, 5, 7, 8).
"""

from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import allocate, quantize
from financeiro.models import (
    AlcadaAprovacao,
    AprovacaoTitulo,
    BaixaParcela,
    CentroCusto,
    CondicaoPagamento,
    ParametroFinanceiroTenant,
    ParcelaFinanceira,
    PlanoContas,
    RateioCentroCusto,
    Renegociacao,
    RenegociacaoParcelaOrigem,
    RetencaoTitulo,
    TituloFinanceiro,
)
from financeiro.services.periodo import checar_periodo_aberto


# ==============================================================================
# PARÂMETROS FINANCEIROS
# ==============================================================================

def obter_parametros_financeiros(tenant) -> ParametroFinanceiroTenant:
    """Retorna os parâmetros financeiros do Tenant, criando os defaults se inexistente."""
    param, _ = ParametroFinanceiroTenant.objects.get_or_create(
        tenant=tenant,
        defaults={
            'aliquota_efetiva_deducoes': Decimal('0.0565'),
            'percentual_multa_padrao': Decimal('0.0200'),
            'percentual_juros_diario_padrao': Decimal('0.000333'),
            'valor_primeira_alcada': Decimal('1000.00'),
        }
    )
    return param


# ==============================================================================
# 1. CRIAÇÃO DE TÍTULO FINANCEIRO (Tarefas 1, 3 e 4)
# ==============================================================================

@transaction.atomic
def criar_titulo(
    *,
    tenant,
    tipo: str,
    conta_gerencial,
    valor_bruto,
    data_emissao=None,
    data_competencia=None,
    filial=None,
    cliente=None,
    fornecedor=None,
    beneficiario_texto: str = '',
    condicao_pagamento=None,
    origem_tipo: str = 'MANUAL',
    origem_id: str = '',
    historico: str = '',
    retencoes: list[dict] | None = None,
    rateios: list[dict] | None = None,
    criado_por=None
) -> TituloFinanceiro:
    """
    Cria um Título Financeiro a Receber ou a Pagar validando todas as regras contábeis e fiscais.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    tipo = tipo.upper().strip()
    if tipo not in ('RECEBER', 'PAGAR'):
        raise ValidationError(f"Tipo de título inválido: '{tipo}'. Esperado 'RECEBER' ou 'PAGAR'.")

    # 1. Validação de partes
    if tipo == 'RECEBER' and not cliente:
        raise ValidationError("Título a RECEBER exige obrigatoriamente a indicação de um Cliente cadastrado.")

    if tipo == 'PAGAR' and not fornecedor and not (beneficiario_texto and beneficiario_texto.strip()):
        raise ValidationError("Título a PAGAR exige um Fornecedor cadastrado ou a identificação do Beneficiário.")

    # 2. Resolução da conta gerencial
    if isinstance(conta_gerencial, int | str):
        try:
            conta_gerencial = PlanoContas.objects.get(tenant=tenant, id=conta_gerencial)
        except (PlanoContas.DoesNotExist, ValueError):
            conta_gerencial = PlanoContas.objects.get(tenant=tenant, codigo_estrutural=str(conta_gerencial))

    if conta_gerencial.tipo != 'ANALITICA' or not conta_gerencial.aceita_lancamento:
        raise ValidationError(
            f"A conta gerencial {conta_gerencial.codigo_estrutural} deve ser analítica e aceitar lançamentos diretos."
        )

    # 3. Datas e validação de período aberto
    dt_emissao = data_emissao or timezone.localdate()
    dt_competencia = data_competencia or dt_emissao
    checar_periodo_aberto(tenant, dt_competencia)

    # 4. Valores monetários estritos
    v_bruto = quantize(valor_bruto, 2)
    if v_bruto <= Decimal('0.00'):
        raise ValidationError(f"O valor bruto do título deve ser estritamente maior que zero (recebido: R$ {v_bruto}).")

    # 5. Cálculo e validação de retenções (Tarefa 3 / F-13)
    total_retencoes = Decimal('0.00')
    retencoes_processadas = []

    if retencoes:
        for ret in retencoes:
            tipo_ret = ret['tipo'].upper().strip()
            aliquota_ret = quantize(ret.get('aliquota', Decimal('0.00')), 4)
            base_ret = quantize(ret.get('base', v_bruto), 2)
            if 'valor' in ret and ret['valor'] is not None:
                valor_ret = quantize(Decimal(str(ret['valor'])), 2)
            else:
                fator = aliquota_ret if aliquota_ret <= Decimal('1.0000') else (aliquota_ret / Decimal('100.00'))
                valor_ret = quantize(base_ret * fator, 2)

            if valor_ret <= Decimal('0.00'):
                continue

            c_passivo = ret.get('conta_passivo')
            if isinstance(c_passivo, int | str):
                c_passivo = PlanoContas.objects.get(tenant=tenant, id=c_passivo)

            total_retencoes += valor_ret
            retencoes_processadas.append({
                'tipo': tipo_ret,
                'base': base_ret,
                'aliquota': aliquota_ret,
                'valor': valor_ret,
                'conta_passivo': c_passivo,
                'data_recolhimento': ret.get('data_recolhimento')
            })

    total_retencoes = quantize(total_retencoes, 2)
    v_liquido = quantize(v_bruto - total_retencoes, 2)

    if v_liquido <= Decimal('0.00'):
        raise ValidationError(
            f"O valor líquido esperado (R$ {v_liquido}) não pode ser menor ou igual a zero "
            f"(Bruto: R$ {v_bruto}, Retenções: R$ {total_retencoes})."
        )

    # 6. Status inicial e alçadas de aprovação (Tarefa 8 / F-03)
    status_inicial = 'ABERTO'
    if tipo == 'PAGAR':
        parametros = obter_parametros_financeiros(tenant)
        # Se ultrapassar o piso da 1ª alçada, entra obrigatoriamente em aprovação
        if v_bruto > parametros.valor_primeira_alcada:
            status_inicial = 'EM_APROVACAO'

    # 7. Persistência do título
    titulo = TituloFinanceiro.objects.create(
        tenant=tenant,
        filial=filial,
        tipo=tipo,
        status=status_inicial,
        cliente=cliente,
        fornecedor=fornecedor,
        beneficiario_texto=beneficiario_texto.strip() if beneficiario_texto else '',
        conta_gerencial=conta_gerencial,
        condicao_pagamento=condicao_pagamento,
        data_emissao=dt_emissao,
        data_competencia=dt_competencia,
        valor_bruto=v_bruto,
        valor_retencoes=total_retencoes,
        valor_liquido_esperado=v_liquido,
        origem_tipo=origem_tipo,
        origem_id=str(origem_id).strip(),
        historico=historico.strip() if historico else '',
        criado_por=criado_por
    )

    # 8. Persistência das retenções
    for r_data in retencoes_processadas:
        RetencaoTitulo.objects.create(
            tenant=tenant,
            titulo=titulo,
            tipo=r_data['tipo'],
            base=r_data['base'],
            aliquota=r_data['aliquota'],
            valor=r_data['valor'],
            conta_passivo=r_data['conta_passivo'],
            data_recolhimento=r_data['data_recolhimento']
        )

    # 9. Cálculo e persistência de rateios por centro de custo (Tarefa 4)
    calcular_rateio(titulo, rateios)

    # 10. Geração das parcelas com allocate (Tarefa 5 / F-06)
    gerar_parcelas(titulo, condicao_pagamento)

    return titulo


# ==============================================================================
# 2. RATEIO POR CENTRO DE CUSTO (Tarefa 4)
# ==============================================================================

def calcular_rateio(titulo: TituloFinanceiro, rateios_data: list[dict] | None = None) -> list[RateioCentroCusto]:
    """
    Calcula e persiste o rateio por centro de custo via allocate (garantia de soma exata).
    Sem rateio informado, aloca 100% para o centro padrão da conta gerencial (ou primeiro CC do tenant).
    """
    tenant = titulo.tenant

    # Se já existirem rateios gravados, remove para recalcular
    RateioCentroCusto.objects.filter(titulo=titulo).delete()

    if not rateios_data:
        # Rateio padrão 100%
        cc_padrao = CentroCusto.objects.filter(tenant=tenant, ativo=True).first()
        if not cc_padrao:
            raise ValidationError("Nenhum Centro de Custo ativo cadastrado para rateio padrão.")
        r = RateioCentroCusto.objects.create(
            tenant=tenant,
            titulo=titulo,
            centro_custo=cc_padrao,
            percentual=Decimal('100.0000'),
            valor_rateado=titulo.valor_bruto
        )
        return [r]

    # Validação dos percentuais informados
    pesos = [quantize(item['percentual'], 4) for item in rateios_data]
    soma_pesos = sum(pesos)
    if soma_pesos != Decimal('100.0000'):
        raise ValidationError(
            f"A soma dos percentuais de rateio deve ser exatamente 100.0000% (soma informada: {soma_pesos}%)."
        )

    # Distribuição exata com allocate (resíduo de centavos na última linha)
    valores_alocados = allocate(titulo.valor_bruto, pesos, casas=2)

    instancias = []
    for item, val_alocado, pct in zip(rateios_data, valores_alocados, pesos, strict=True):
        cc = item['centro_custo']
        if isinstance(cc, int | str):
            cc = CentroCusto.objects.get(tenant=tenant, id=cc)

        veic = item.get('veiculo')
        if veic and isinstance(veic, int | str):
            from logistica.models import Veiculo
            veic = Veiculo.objects.filter(tenant=tenant, id=veic).first()

        instancias.append(
            RateioCentroCusto(
                tenant=tenant,
                titulo=titulo,
                centro_custo=cc,
                veiculo=veic,
                percentual=pct,
                valor_rateado=val_alocado
            )
        )

    return RateioCentroCusto.objects.bulk_create(instancias)


# ==============================================================================
# 3. GERAÇÃO DE PARCELAS (Tarefa 5 / Correção F-06)
# ==============================================================================

def gerar_parcelas(titulo: TituloFinanceiro, condicao: CondicaoPagamento | None = None) -> list[ParcelaFinanceira]:
    """
    Gera o cronograma de parcelas financeiras para o título usando allocate sobre valor_liquido_esperado.
    """
    tenant = titulo.tenant

    # Se já existirem parcelas (e sem baixas), remove para regerar
    if titulo.parcelas.filter(baixas__isnull=False).exists():
        raise ValidationError("Não é possível regerar parcelas de um título que já possui baixas registradas.")

    titulo.parcelas.all().delete()

    if not condicao or not condicao.parcelas_json:
        # Parcela única à vista na data de emissão
        p = ParcelaFinanceira.objects.create(
            tenant=tenant,
            titulo=titulo,
            numero_parcela=1,
            total_parcelas=1,
            data_vencimento=titulo.data_emissao,
            valor_nominal=titulo.valor_liquido_esperado,
            saldo_em_aberto=titulo.valor_liquido_esperado,
            status='PENDENTE'
        )
        return [p]

    # Distribuição via parcelas_json: [{'dias': 30, 'percentual': '50.0000'}, ...]
    itens = condicao.parcelas_json
    pesos = [Decimal(str(item['percentual'])) for item in itens]
    valores_alocados = allocate(titulo.valor_liquido_esperado, pesos, casas=2)

    total_parc = len(itens)
    parcelas = []

    for idx, (item, val_parc) in enumerate(zip(itens, valores_alocados, strict=True), start=1):
        dias = int(item.get('dias', 0))
        dt_venc = titulo.data_emissao + timedelta(days=dias)

        parcelas.append(
            ParcelaFinanceira(
                tenant=tenant,
                titulo=titulo,
                numero_parcela=idx,
                total_parcelas=total_parc,
                data_vencimento=dt_venc,
                valor_nominal=val_parc,
                saldo_em_aberto=val_parc,
                status='PENDENTE'
            )
        )

    return ParcelaFinanceira.objects.bulk_create(parcelas)


# ==============================================================================
# 4. MÁQUINA DE ESTADOS DO TÍTULO (Tarefa 2)
# ==============================================================================

TRANSIÇÕES_PERMITIDAS_TITULO = {
    'RASCUNHO': {'EM_APROVACAO', 'ABERTO'},
    'EM_APROVACAO': {'ABERTO', 'RASCUNHO', 'CANCELADO'},
    'ABERTO': {'PARCIAL', 'LIQUIDADO', 'CANCELADO'},
    'PARCIAL': {'LIQUIDADO'},
    'LIQUIDADO': set(),
    'CANCELADO': set(),
}

@transaction.atomic
def transicionar(titulo: TituloFinanceiro, novo_status: str, motivo: str = '', usuario=None) -> TituloFinanceiro:
    """
    Executa a transição formal de estado do Título Financeiro validando as transições permitidas.
    Cancelar título com baixa exige estornar as baixas antes.
    """
    tenant = titulo.tenant
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    status_atual = titulo.status
    novo_status = novo_status.upper().strip()

    # Regra estrita: Cancelar título com baixa exige estornar as baixas antes
    if novo_status == 'CANCELADO':
        baixas_ativas = BaixaParcela.objects.filter(
            parcela__titulo=titulo,
            estornado=False
        ).exists()
        if baixas_ativas:
            raise ValidationError(
                "Não é permitido cancelar um título financeiro com baixas ativas. "
                "Estorne todas as baixas registradas antes de cancelar o título."
            )

    if novo_status not in TRANSIÇÕES_PERMITIDAS_TITULO.get(status_atual, set()):
        raise ValidationError(
            f"Transição de status inválida: não é permitido transicionar de '{status_atual}' para '{novo_status}'."
        )

    if novo_status == 'CANCELADO':
        # Cancela também as parcelas em aberto
        titulo.parcelas.filter(status__in=['PENDENTE', 'PARCIAL']).update(
            status='CANCELADA',
            saldo_em_aberto=Decimal('0.00')
        )

    titulo.status = novo_status
    titulo.save(update_fields=['status', 'atualizado_em'])
    return titulo


# ==============================================================================
# 5. CÁLCULO DE ENCARGOS MORATÓRIOS (Tarefa 6)
# ==============================================================================

def calcular_encargos(parcela: ParcelaFinanceira, data_calculo=None) -> dict[str, Decimal]:
    """
    Calcula multa e juros moratórios com base nos parâmetros do tenant e atraso pro rata die.
    """
    dt_ref = data_calculo or timezone.localdate()

    if dt_ref <= parcela.data_vencimento or parcela.saldo_em_aberto <= Decimal('0.00'):
        return {
            'dias_atraso': 0,
            'valor_multa': Decimal('0.00'),
            'valor_juros': Decimal('0.00'),
            'total_encargos': Decimal('0.00'),
            'total_devido': parcela.saldo_em_aberto
        }

    dias_atraso = (dt_ref - parcela.data_vencimento).days
    parametros = obter_parametros_financeiros(parcela.tenant)

    # Multa percentual única incidente sobre o saldo em aberto
    multa = quantize(parcela.saldo_em_aberto * parametros.percentual_multa_padrao, 2)

    # Juros pro rata die
    juros = quantize(parcela.saldo_em_aberto * (parametros.percentual_juros_diario_padrao * Decimal(dias_atraso)), 2)

    total_encargos = multa + juros
    total_devido = parcela.saldo_em_aberto + total_encargos

    return {
        'dias_atraso': dias_atraso,
        'valor_multa': multa,
        'valor_juros': juros,
        'total_encargos': total_encargos,
        'total_devido': total_devido
    }


# ==============================================================================
# 6. SEGREGAÇÃO E APROVAÇÃO DE CONTAS A PAGAR (Tarefa 8 / Correção F-03)
# ==============================================================================

def pode_aprovar(titulo: TituloFinanceiro, usuario) -> bool:
    """
    Verifica se o usuário pode aprovar o título financeiro (Segregação de funções).
    Regra estrita: Quem lançou/criou o título NÃO pode aprová-lo nem baixá-lo.
    """
    if not usuario:
        return False

    # Superusuário ou Admin não anulam a regra de segregação se ele for o próprio criador
    if titulo.criado_por_id and titulo.criado_por_id == usuario.id:
        return False

    return True


@transaction.atomic
def aprovar_titulo(
    *,
    titulo_id,
    usuario,
    decisao: str,
    motivo: str = ''
) -> AprovacaoTitulo:
    """
    Aprova ou rejeita formalmente um título de Contas a Pagar em status EM_APROVACAO.
    """
    titulo = TituloFinanceiro.objects.select_for_update().get(id=titulo_id)
    tenant = titulo.tenant

    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if titulo.tipo != 'PAGAR':
        raise ValidationError("Apenas títulos do tipo PAGAR passam por alçadas de aprovação formal.")

    if titulo.status != 'EM_APROVACAO':
        raise ValidationError(f"O título #{titulo.id} está com status '{titulo.status}', não está aguardando aprovação.")

    if not pode_aprovar(titulo, usuario):
        raise ValidationError(
            f"Violação de Segregação de Funções: O usuário '{usuario.username}' criou este título "
            f"e está estritamente proibido de aprová-lo."
        )

    decisao = decisao.upper().strip()
    if decisao not in ('APROVADO', 'REJEITADO'):
        raise ValidationError(f"Decisão inválida: '{decisao}'. Esperado APROVADO ou REJEITADO.")

    aprovacao = AprovacaoTitulo.objects.create(
        tenant=tenant,
        titulo=titulo,
        aprovador=usuario,
        decisao=decisao,
        motivo=motivo.strip()
    )

    if decisao == 'APROVADO':
        transicionar(titulo, 'ABERTO', motivo=f"Aprovado por {usuario.username}: {motivo}", usuario=usuario)
    else:
        transicionar(titulo, 'CANCELADO', motivo=f"Rejeitado na aprovação por {usuario.username}: {motivo}", usuario=usuario)

    return aprovacao


# ==============================================================================
# 7. RENEGOCIAÇÃO DE PARCELAS (Tarefa 7)
# ==============================================================================

@transaction.atomic
def renegociar_parcelas(
    *,
    tenant,
    parcelas_origem_ids: list[int],
    titulo_id=None,
    novas_parcelas_data: list[dict] | None = None,
    novas_parcelas: list[dict] | None = None,
    motivo: str,
    desconto_concedido: Decimal = Decimal('0.00'),
    usuario=None
) -> Renegociacao:
    """
    Renegocia uma ou mais parcelas em aberto consolidando saldo e emitindo novo cronograma.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if not motivo or not motivo.strip():
        raise ValidationError("O motivo formal da renegociação é obrigatório.")

    novas_itens = novas_parcelas_data if novas_parcelas_data is not None else (novas_parcelas or [])
    if not novas_itens:
        raise ValidationError("Nenhuma nova parcela informada para a renegociação.")

    # Lock nas parcelas de origem
    parcelas_origem = list(
        ParcelaFinanceira.objects.select_for_update().filter(
            tenant=tenant,
            id__in=parcelas_origem_ids,
            status__in=['PENDENTE', 'PARCIAL']
        )
    )

    if len(parcelas_origem) != len(parcelas_origem_ids):
        raise ValidationError("Uma ou mais parcelas informadas para renegociação não existem ou não estão pendentes.")

    titulo = TituloFinanceiro.objects.select_for_update().get(tenant=tenant, id=titulo_id) if titulo_id else parcelas_origem[0].titulo

    # Soma dos saldos devedores incorporados
    saldo_total_incorporado = sum(p.saldo_em_aberto for p in parcelas_origem)
    desconto = quantize(Decimal(str(desconto_concedido)), 2)

    valor_novo_total = quantize(saldo_total_incorporado - desconto, 2)
    if valor_novo_total <= Decimal('0.00'):
        raise ValidationError(
            f"O valor total da repactuação (R$ {valor_novo_total}) deve ser maior que zero "
            f"(Saldo Incorporado: R$ {saldo_total_incorporado}, Desconto: R$ {desconto})."
        )

    # 1. Cria a Renegociação
    reneg = Renegociacao.objects.create(
        tenant=tenant,
        titulo=titulo,
        motivo=motivo.strip(),
        desconto_concedido=desconto,
        aprovado_por=usuario,
        aprovado_em=timezone.now()
    )

    # 2. Marca as parcelas antigas como RENEGOCIADA
    for p in parcelas_origem:
        RenegociacaoParcelaOrigem.objects.create(
            tenant=tenant,
            renegociacao=reneg,
            parcela=p,
            saldo_incorporado=p.saldo_em_aberto
        )
        p.status = 'RENEGOCIADA'
        p.saldo_em_aberto = Decimal('0.00')
        p.save(update_fields=['status', 'saldo_em_aberto', 'atualizado_em'])

    # 3. Cria as novas parcelas
    has_percentual = any('percentual' in item for item in novas_itens)
    if not has_percentual and any('valor' in item for item in novas_itens):
        soma_vals = sum(quantize(Decimal(str(item['valor'])), 2) for item in novas_itens)
        if soma_vals != valor_novo_total:
            raise ValidationError(
                f"A soma dos valores das novas parcelas (R$ {soma_vals}) diverge do novo saldo total (R$ {valor_novo_total})."
            )
        pesos = [quantize((Decimal(str(item['valor'])) / valor_novo_total) * Decimal('100.0000'), 4) for item in novas_itens]
        dif_pesos = Decimal('100.0000') - sum(pesos)
        pesos[-1] += dif_pesos
    else:
        pesos = [quantize(Decimal(str(item.get('percentual', 0))), 4) for item in novas_itens]
        if sum(pesos) != Decimal('100.0000'):
            raise ValidationError(f"A soma dos percentuais das novas parcelas deve ser 100.0000% (recebido: {sum(pesos)}%).")

    valores_novas_parc = allocate(valor_novo_total, pesos, casas=2)
    ultimo_num = titulo.parcelas.order_by('-numero_parcela').values_list('numero_parcela', flat=True).first() or 0

    novas_instancias = []
    total_novas = len(novas_itens)

    for idx, (item, val) in enumerate(zip(novas_itens, valores_novas_parc, strict=True), start=1):
        if 'data_vencimento' in item:
            dt_venc = item['data_vencimento']
        else:
            dias = int(item.get('dias', 30))
            dt_venc = timezone.localdate() + timedelta(days=dias)

        novas_instancias.append(
            ParcelaFinanceira(
                tenant=tenant,
                titulo=titulo,
                numero_parcela=ultimo_num + idx,
                total_parcelas=ultimo_num + total_novas,
                data_vencimento=dt_venc,
                valor_nominal=val,
                saldo_em_aberto=val,
                status='PENDENTE'
            )
        )

    ParcelaFinanceira.objects.bulk_create(novas_instancias)

    # Se o título estava PARCIAL ou ABERTO, mantém coerente
    if titulo.status == 'PARCIAL':
        titulo.status = 'ABERTO'
        titulo.save(update_fields=['status', 'atualizado_em'])

    return reneg
