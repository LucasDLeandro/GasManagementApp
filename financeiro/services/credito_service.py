from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date, timedelta
from typing import List, Dict, Any, Optional

from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    ParametroCredito,
    LimiteCreditoCliente,
    PromessaPagamento,
    ParcelaFinanceira,
)


@dataclass
class ResultadoAvaliacaoCredito:
    status: str  # 'LIBERADO', 'BLOQUEADO_FINANCEIRO', 'ALERTA_ASSISTENCIAL'
    motivos: List[str] = field(default_factory=list)
    limite: Decimal = Decimal('0.00')
    exposicao_total: Decimal = Decimal('0.00')
    saldo_vencido: Decimal = Decimal('0.00')
    detalhes: Dict[str, Any] = field(default_factory=dict)

    @property
    def liberado(self) -> bool:
        return self.status in ('LIBERADO', 'ALERTA_ASSISTENCIAL')


def obter_parametro_credito(tenant) -> ParametroCredito:
    """Retorna os parâmetros de crédito do tenant ou cria com defaults recomendados."""
    param, _ = ParametroCredito.objects.get_or_create(
        tenant=tenant,
        defaults={
            'dias_tolerancia': 5,
            'valor_minimo_considerado': Decimal('50.00'),
            'limite_credito_padrao': Decimal('5000.00'),
            'max_dias_promessa': 30,
            'max_promessas_ativas': 2,
            'politica_gas_medicinal': 'ALERTAR_E_ESCALAR',
        }
    )
    return param


def obter_limite_credito_cliente(cliente) -> Decimal:
    """
    Retorna o limite de crédito vigente do cliente.
    Se houver LimiteCreditoCliente ativo e vigente, utiliza o limite individual.
    Caso contrário, adota o limite_credito_padrao do ParametroCredito do tenant.
    """
    hoje = timezone.localdate()
    limite_indiv = LimiteCreditoCliente.objects.filter(
        tenant=cliente.tenant,
        cliente=cliente,
        ativo=True,
        vigencia_inicio__lte=hoje
    ).filter(
        models.Q(vigencia_fim__isnull=True) | models.Q(vigencia_fim__gte=hoje)
    ).order_by('-vigencia_inicio').first()

    if limite_indiv:
        return quantize(limite_indiv.limite)

    # Fallback para o limite padrão do tenant
    param = obter_parametro_credito(cliente.tenant)
    return quantize(param.limite_credito_padrao)


def avaliar_credito(
    cliente,
    valor_pedido: Decimal = Decimal('0.00'),
    itens: Optional[list] = None
) -> ResultadoAvaliacaoCredito:
    """
    Avalia a situação financeira e de crédito do cliente para liberação comercial (Sprint 11C - Tarefa 3).
    - Bloqueia se houver parcela a receber vencida além de dias_tolerancia sem promessa ativa.
    - Bloqueia se a exposição (saldo aberto + pedido) exceder o limite de crédito.
    - Regra assistencial: Para hospitais e gás medicinal, alerta e escala à gerência por padrão (não bloqueia).
    - Degradação graciosa: Com modulo_financeiro_ativo = False, retorna LIBERADO sem bloquear.
    - Isenção controlada: Respeita bloqueio_isento do cliente durante o prazo de validade.
    """
    tenant = cliente.tenant
    hoje = timezone.localdate()

    # 1. Degradação Graciosa: Se o módulo financeiro estiver inativo no tenant
    if not getattr(tenant, 'modulo_financeiro_ativo', False):
        return ResultadoAvaliacaoCredito(
            status='LIBERADO',
            motivos=[],
            limite=Decimal('0.00'),
            exposicao_total=Decimal('0.00'),
            saldo_vencido=Decimal('0.00'),
            detalhes={'motivo': 'MODULO_FINANCEIRO_INATIVO', 'mensagem': 'Módulo financeiro inativo no tenant. Liberação automática.'}
        )

    # 2. Isenção Controlada do Cliente (Tarefa 6)
    if cliente.bloqueio_isento:
        if not cliente.isencao_validade or cliente.isencao_validade >= hoje:
            return ResultadoAvaliacaoCredito(
                status='LIBERADO',
                motivos=[],
                limite=obter_limite_credito_cliente(cliente),
                exposicao_total=quantize(valor_pedido),
                saldo_vencido=Decimal('0.00'),
                detalhes={
                    'motivo': 'CLIENTE_ISENTO',
                    'justificativa': cliente.isencao_justificativa,
                    'validade': cliente.isencao_validade.isoformat() if cliente.isencao_validade else None
                }
            )

    param = obter_parametro_credito(tenant)
    limite = obter_limite_credito_cliente(cliente)

    # 3. Busca parcelas em aberto a receber do cliente
    parcelas_abertas = ParcelaFinanceira.objects.filter(
        tenant=tenant,
        titulo__cliente=cliente,
        titulo__tipo='RECEBER',
        saldo_em_aberto__gt=Decimal('0.00')
    ).exclude(
        titulo__status__in=['CANCELADO', 'LIQUIDADO']
    ).select_related('titulo')

    # Identifica IDs de parcelas protegidas por promessas de pagamento ATIVAS vigentes
    promessas_ativas = PromessaPagamento.objects.filter(
        tenant=tenant,
        cliente=cliente,
        status='ATIVA',
        data_promessa__gte=hoje
    ).prefetch_related('parcelas')

    parcelas_protegidas_ids = set()
    for prom in promessas_ativas:
        for p in prom.parcelas.all():
            parcelas_protegidas_ids.add(p.id)

    # 4. Checagem de Parcelas Vencidas com Tolerância (o X da v2.0)
    data_tolerancia_limite = hoje - timedelta(days=param.dias_tolerancia)
    parcelas_vencidas_bloqueantes = []
    saldo_vencido_total = Decimal('0.00')

    for parc in parcelas_abertas:
        if parc.data_vencimento < data_tolerancia_limite:
            # Tolerância de valor mínimo considerado
            if parc.saldo_em_aberto >= param.valor_minimo_considerado:
                if parc.id not in parcelas_protegidas_ids:
                    parcelas_vencidas_bloqueantes.append(parc)
                    saldo_vencido_total += parc.saldo_em_aberto

    saldo_vencido_total = quantize(saldo_vencido_total)

    # 5. Checagem de Exposição Financeira (Saldo em aberto + Pedido Atual)
    saldo_aberto_geral = sum((p.saldo_em_aberto for p in parcelas_abertas), Decimal('0.00'))
    exposicao_total = quantize(saldo_aberto_geral + quantize(Decimal(str(valor_pedido or '0.00'))))

    motivos = []
    if parcelas_vencidas_bloqueantes:
        motivos.append('PARCELA_VENCIDA')

    if exposicao_total > limite:
        motivos.append('LIMITE_EXCEDIDO')

    detalhes = {
        'dias_tolerancia': param.dias_tolerancia,
        'valor_minimo_considerado': param.valor_minimo_considerado,
        'quantidade_parcelas_vencidas': len(parcelas_vencidas_bloqueantes),
        'parcelas_vencidas_ids': [p.id for p in parcelas_vencidas_bloqueantes],
        'promessas_ativas_count': promessas_ativas.count(),
        'exposicao_total': exposicao_total,
        'limite_credito': limite,
    }

    # Se não houver motivos de bloqueio, está plenamente liberado
    if not motivos:
        return ResultadoAvaliacaoCredito(
            status='LIBERADO',
            motivos=[],
            limite=limite,
            exposicao_total=exposicao_total,
            saldo_vencido=saldo_vencido_total,
            detalhes=detalhes
        )

    # 6. Regra de Segurança Assistencial: Hospitalar ou Gás Medicinal (Tarefa 5)
    eh_hospitalar = (
        getattr(cliente, 'tipo_estabelecimento', '') == 'HOSPITAL'
        or getattr(cliente, 'is_medicinal', False)
    )

    tem_item_medicinal = False
    if itens:
        for it in itens:
            sku = getattr(it, 'sku', None) or (it.get('sku') if isinstance(it, dict) else None)
            prod = getattr(it, 'produto', None) or (it.get('produto') if isinstance(it, dict) else None)
            if (sku and getattr(sku, 'medicinal', False)) or (prod and getattr(prod, 'medicinal', False)):
                tem_item_medicinal = True
                break

    if eh_hospitalar or tem_item_medicinal:
        detalhes['seguranca_assistencial'] = True
        detalhes['eh_hospitalar'] = eh_hospitalar
        detalhes['tem_item_medicinal'] = tem_item_medicinal
        detalhes['politica_adotada'] = param.politica_gas_medicinal

        if param.politica_gas_medicinal == 'ALERTAR_E_ESCALAR':
            # Padrão: Nunca bloqueia automaticamente fornecimento hospitalar/medicinal
            return ResultadoAvaliacaoCredito(
                status='ALERTA_ASSISTENCIAL',
                motivos=motivos,
                limite=limite,
                exposicao_total=exposicao_total,
                saldo_vencido=saldo_vencido_total,
                detalhes=detalhes
            )
        else:
            # Endurecimento formal auditado do tenant
            return ResultadoAvaliacaoCredito(
                status='BLOQUEADO_FINANCEIRO',
                motivos=motivos,
                limite=limite,
                exposicao_total=exposicao_total,
                saldo_vencido=saldo_vencido_total,
                detalhes=detalhes
            )

    # Cliente comum com pendências: Bloqueio financeiro comercial
    return ResultadoAvaliacaoCredito(
        status='BLOQUEADO_FINANCEIRO',
        motivos=motivos,
        limite=limite,
        exposicao_total=exposicao_total,
        saldo_vencido=saldo_vencido_total,
        detalhes=detalhes
    )


@transaction.atomic
def criar_promessa_pagamento(
    cliente,
    parcelas: list,
    data_promessa: date,
    valor: Optional[Decimal] = None,
    usuario=None,
    observacao: str = ''
) -> PromessaPagamento:
    """
    Registra uma nova promessa de pagamento para parcelas em aberto (Sprint 11C - Tarefa 2).
    - Valida limite de promessas ativas e prazo máximo permitido.
    - Suspende o bloqueio comercial e a régua de cobrança automática das parcelas vinculadas.
    """
    tenant = cliente.tenant
    assert_tenant_writable(tenant)

    hoje = timezone.localdate()
    param = obter_parametro_credito(tenant)

    if data_promessa < hoje:
        raise ValidationError(f"A data da promessa ({data_promessa}) não pode ser retroativa.")

    limite_futuro = hoje + timedelta(days=param.max_dias_promessa)
    if data_promessa > limite_futuro:
        raise ValidationError(
            f"A data da promessa ({data_promessa}) excede o prazo máximo permitido de {param.max_dias_promessa} dias "
            f"(limite: {limite_futuro})."
        )

    # Limite de promessas ativas simultâneas
    ativas_count = PromessaPagamento.objects.filter(
        tenant=tenant,
        cliente=cliente,
        status='ATIVA'
    ).count()

    if ativas_count >= param.max_promessas_ativas:
        raise ValidationError(
            f"O cliente '{cliente.nome}' já possui {ativas_count} promessa(s) ativa(s). "
            f"Máximo permitido por política: {param.max_promessas_ativas}."
        )

    if not parcelas:
        raise ValidationError("A promessa de pagamento deve vincular ao menos uma parcela.")

    # Validação e cálculo do valor total das parcelas vinculadas
    soma_parcelas = Decimal('0.00')
    parcelas_validas = []
    for parc in parcelas:
        if parc.tenant_id != tenant.id or parc.titulo.cliente_id != cliente.id:
            raise ValidationError(f"A parcela #{parc.id} não pertence ao cliente informado.")
        if parc.status == 'PAGA' or parc.saldo_em_aberto <= Decimal('0.00'):
            raise ValidationError(f"A parcela #{parc.id} já está quitada e não aceita promessa.")
        soma_parcelas += parc.saldo_em_aberto
        parcelas_validas.append(parc)

    valor_final = quantize(valor if valor is not None else soma_parcelas)
    if valor_final <= Decimal('0.00'):
        raise ValidationError("O valor da promessa de pagamento deve ser estritamente maior que zero.")

    promessa = PromessaPagamento.objects.create(
        tenant=tenant,
        cliente=cliente,
        data_promessa=data_promessa,
        valor=valor_final,
        status='ATIVA',
        criado_por=usuario,
        observacao=observacao.strip()
    )
    promessa.parcelas.set(parcelas_validas)
    return promessa


@transaction.atomic
def atualizar_status_promessas_diario(tenant=None) -> Dict[str, int]:
    """
    Job diário de monitoramento de promessas de pagamento (Sprint 11C - Tarefa 2):
    - Marca CUMPRIDA se todas as parcelas vinculadas foram baixadas/quitadas.
    - Marca QUEBRADA se a data_promessa venceu e as parcelas ainda têm saldo devedor.
    """
    hoje = timezone.localdate()
    qs = PromessaPagamento.objects.filter(status='ATIVA').prefetch_related('parcelas')
    if tenant:
        qs = qs.filter(tenant=tenant)

    cumpridas = 0
    quebradas = 0

    for prom in qs:
        parcelas = list(prom.parcelas.all())
        todas_quitadas = len(parcelas) > 0 and all(p.saldo_em_aberto <= Decimal('0.00') or p.status == 'PAGA' for p in parcelas)

        if todas_quitadas:
            prom.status = 'CUMPRIDA'
            prom.save(update_fields=['status', 'atualizado_em'])
            cumpridas += 1
        elif prom.data_promessa < hoje:
            prom.status = 'QUEBRADA'
            prom.save(update_fields=['status', 'atualizado_em'])
            quebradas += 1

    return {'cumpridas': cumpridas, 'quebradas': quebradas}
