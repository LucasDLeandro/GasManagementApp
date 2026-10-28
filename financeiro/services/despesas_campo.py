import uuid
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from core.guards import assert_tenant_writable, assert_modulo
from core.money import quantize
from financeiro.models import (
    PreLancamentoDespesaCampo,
    PlanoContas,
    ContaFinanceira,
    MovimentoConta,
)
from financeiro.antifraude import analisar_despesa_campo
from financeiro.services.razao import lancar
from logistica.models import Veiculo, LeituraOdometro, Entrega


from django.contrib.auth import get_user_model

@transaction.atomic
def criar_pre_lancamento_despesa(
    *,
    tenant,
    tipo: str,
    veiculo=None,
    veiculo_id=None,
    motorista=None,
    motorista_id=None,
    valor_informado,
    forma_pagamento: str = 'CARTAO_FROTA',
    data_hora=None,
    odometro_informado=None,
    litros=None,
    posto_nome: str = '',
    posto_cnpj: str = '',
    foto_cupom=None,
    latitude=None,
    longitude=None,
    entrega=None,
    entrega_id=None,
    client_uuid=None
) -> PreLancamentoDespesaCampo:
    """
    Registra um pré-lançamento de despesa de campo submetido pelo motorista (Sprint 9C - Tarefa 2 / F-05).
    Garante idempotência por client_uuid e executa imediatamente a auditoria antifraude.
    Nunca cria TituloFinanceiro diretamente.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    # 1. Idempotência por client_uuid
    c_uuid = client_uuid or uuid.uuid4()
    if isinstance(c_uuid, str):
        try:
            c_uuid = uuid.UUID(c_uuid)
        except ValueError:
            c_uuid = uuid.uuid4()

    existente = PreLancamentoDespesaCampo.objects.filter(
        tenant=tenant,
        client_uuid=c_uuid
    ).first()
    if existente:
        return existente

    # 2. Resolução das entidades
    v_target = veiculo or veiculo_id
    if isinstance(v_target, Veiculo):
        veiculo_obj = v_target
    else:
        veiculo_obj = Veiculo.objects.get(tenant=tenant, id=v_target)

    m_target = motorista or motorista_id
    User = get_user_model()
    if isinstance(m_target, User):
        motorista_obj = m_target
    else:
        motorista_obj = User.objects.get(id=m_target)

    ent_target = entrega or entrega_id
    entrega_obj = None
    if ent_target:
        if isinstance(ent_target, Entrega):
            entrega_obj = ent_target
        else:
            entrega_obj = Entrega.objects.filter(tenant=tenant, id=ent_target).first()

    # 3. Tratamento de valores com core/money (Regra 2)
    val_inf = quantize(Decimal(str(valor_informado)), 2)
    if val_inf <= Decimal('0.00'):
        raise ValidationError("O valor informado da despesa deve ser estritamente maior que zero.")

    litros_dec = None
    preco_litro = None
    if litros is not None:
        litros_dec = quantize(Decimal(str(litros)), 3)
        if litros_dec > Decimal('0.000'):
            preco_litro = quantize(val_inf / litros_dec, 3)

    odo_dec = None
    if odometro_informado is not None:
        odo_dec = quantize(Decimal(str(odometro_informado)), 3)

    lat_dec = Decimal(str(latitude)) if latitude is not None else None
    lon_dec = Decimal(str(longitude)) if longitude is not None else None
    dt_hora = data_hora or timezone.now()

    # 4. Criação do pré-lançamento
    despesa = PreLancamentoDespesaCampo.objects.create(
        tenant=tenant,
        tipo=tipo.upper().strip(),
        veiculo=veiculo_obj,
        motorista=motorista_obj,
        entrega=entrega_obj,
        data_hora=dt_hora,
        odometro_informado=odo_dec,
        litros=litros_dec,
        valor_informado=val_inf,
        preco_litro_calculado=preco_litro,
        forma_pagamento=forma_pagamento.upper().strip(),
        posto_nome=posto_nome.strip() if posto_nome else '',
        posto_cnpj=posto_cnpj.strip() if posto_cnpj else '',
        foto_cupom=foto_cupom,
        latitude=lat_dec,
        longitude=lon_dec,
        status='PENDENTE_CONFERENCIA',
        client_uuid=c_uuid
    )

    # 5. Análise antifraude imediata
    analisar_despesa_campo(despesa, salvar=True)
    return despesa


@transaction.atomic
def aprovar_despesa_campo(tenant, despesa_id: int, usuario) -> PreLancamentoDespesaCampo:
    """
    Aprova formalmente uma despesa de campo na conferência do backoffice (Sprint 9C - Tarefas 5 e 7).
    Regra de segregação estrita: quem aprova não pode ser o autor / motorista da despesa.
    Se for paga com DINHEIRO_ROTA, realiza lançamento contábil direto contra a conta caixa de rota.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    despesa = PreLancamentoDespesaCampo.objects.select_for_update().get(id=despesa_id)
    if despesa.tenant_id != tenant.id:
        raise ValidationError("A despesa informada pertence a outro Tenant.")

    if despesa.status != 'PENDENTE_CONFERENCIA':
        raise ValidationError(f"A despesa #{despesa.id} está com status '{despesa.status}' e não pode ser aprovada.")

    # Segregação de funções estrita (Tarefa 5)
    if usuario and usuario.id == despesa.motorista_id:
        raise ValidationError("Segregação de funções violada: o usuário conferente não pode aprovar a própria despesa lançada.")

    # 1. Se for abastecimento com odômetro, valida e registra a leitura oficial
    if despesa.tipo == 'ABASTECIMENTO' and despesa.odometro_informado is not None:
        LeituraOdometro.objects.create(
            tenant=tenant,
            veiculo=despesa.veiculo,
            km=despesa.odometro_informado,
            data_hora=despesa.data_hora,
            origem='ABASTECIMENTO',
            validada=True
        )

    # 2. Pagamento em Dinheiro da Rota (Tarefa 7)
    # "após aprovação, lançamento direto (débito despesa, crédito caixa de rota), sem título."
    if despesa.forma_pagamento == 'DINHEIRO_ROTA':
        c_despesa = PlanoContas.objects.filter(
            tenant=tenant,
            codigo_estrutural__startswith='5.1',
            tipo='ANALITICA'
        ).first() or PlanoContas.objects.filter(
            tenant=tenant,
            codigo_estrutural__startswith='4.1',
            tipo='ANALITICA'
        ).first()

        c_caixa_rota = PlanoContas.objects.filter(
            tenant=tenant,
            codigo_estrutural='1.1.1.03'
        ).first() or PlanoContas.objects.filter(
            tenant=tenant,
            codigo_estrutural='1.1.1.01'
        ).first()

        partidas = [
            {'conta': c_despesa, 'tipo_partida': 'DEBITO', 'valor': despesa.valor_informado, 'veiculo': despesa.veiculo},
            {'conta': c_caixa_rota, 'tipo_partida': 'CREDITO', 'valor': despesa.valor_informado},
        ]

        dt_comp = despesa.data_hora.date() if hasattr(despesa.data_hora, 'date') else despesa.data_hora

        lanc, _ = lancar(
            tenant=tenant,
            data_competencia=dt_comp,
            historico=f"Despesa de Campo Aprovada #{despesa.id} ({despesa.tipo}) - Veículo {despesa.veiculo.placa}",
            partidas=partidas,
            origem_tipo='despesa_campo_dinheiro',
            origem_id=str(despesa.id),
            usuario=usuario
        )
        despesa.lancamento_contabil = lanc

        # Movimento de Conta Financeira de saída do caixa de rota
        conta_fin = ContaFinanceira.objects.filter(
            tenant=tenant,
            tipo__in=['CAIXA', 'OUTRO']
        ).first()
        if conta_fin:
            MovimentoConta.objects.create(
                tenant=tenant,
                conta=conta_fin,
                tipo='SAIDA',
                valor=despesa.valor_informado,
                data_movimento=dt_comp,
                historico=f"Pagamento em Rota: {despesa.tipo} - Placa {despesa.veiculo.placa}",
                lancamento=lanc
            )

    despesa.status = 'APROVADO'
    despesa.aprovado_por = usuario
    despesa.save(update_fields=['status', 'aprovado_por', 'lancamento_contabil', 'atualizado_em'])

    return despesa


@transaction.atomic
def rejeitar_despesa_campo(tenant, despesa_id: int, usuario, motivo: str) -> PreLancamentoDespesaCampo:
    """
    Rejeita um pré-lançamento de despesa de campo com justificativa obrigatória (Sprint 9C - Tarefa 5).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if not motivo or not motivo.strip():
        raise ValidationError("O motivo formal da rejeição da despesa de campo é obrigatório.")

    despesa = PreLancamentoDespesaCampo.objects.select_for_update().get(id=despesa_id)
    if despesa.tenant_id != tenant.id:
        raise ValidationError("A despesa informada pertence a outro Tenant.")

    if despesa.status != 'PENDENTE_CONFERENCIA':
        raise ValidationError(f"A despesa #{despesa.id} está com status '{despesa.status}' e não pode ser rejeitada.")

    if usuario and usuario.id == despesa.motorista_id:
        raise ValidationError("Segregação de funções violada: o usuário conferente não pode rejeitar a própria despesa.")

    despesa.status = 'REJEITADO'
    despesa.motivo_rejeicao = motivo.strip()
    despesa.aprovado_por = usuario
    despesa.save(update_fields=['status', 'motivo_rejeicao', 'aprovado_por', 'atualizado_em'])

    return despesa


@transaction.atomic
def aprovar_despesas_campo_em_lote(tenant, despesas_ids: list[int], usuario) -> list[PreLancamentoDespesaCampo]:
    """
    Aprova múltiplas despesas de campo pendentes em lote (Sprint 9C - Tarefa 5).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    aprovadas = []
    for d_id in despesas_ids:
        d = aprovar_despesa_campo(tenant, d_id, usuario)
        aprovadas.append(d)

    return aprovadas
