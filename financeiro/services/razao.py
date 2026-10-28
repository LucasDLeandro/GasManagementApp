"""
Serviço Canônico do Livro Razão Contábil (Sprint 9A - Tarefas 8, 9 e 10 / Correções F-02, F-18).
Regra Mandatória: Nenhum outro código no sistema escreve em LancamentoContabil ou PartidaContabil
fora das funções 'lancar' e 'estornar' deste serviço.
"""

import hashlib
from decimal import Decimal
from typing import Any, Sequence

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.models import Tenant
from core.money import quantize
from financeiro.models import (
    LancamentoContabil,
    PartidaContabil,
    PlanoContas,
    CentroCusto,
)
from financeiro.services.periodo import checar_periodo_aberto


def _calcular_payload_canonico(tenant_id, numero, data_competencia, historico, origem_tipo, origem_id, partidas_dados):
    """
    Gera a representação canônica e determinística do lançamento para cálculo do hash SHA-256 encadeado.
    """
    partidas_formatadas = []
    for p in partidas_dados:
        c_id = str(p['conta_id'])
        t = str(p['tipo_partida'])
        v = str(quantize(p['valor'], 2))
        cc = str(p.get('centro_custo_id') or '')
        veic = str(p.get('veiculo_id') or '')
        prod = str(p.get('produto_gas_id') or '')
        cli = str(p.get('cliente_id') or '')
        ent = str(p.get('entrega_id') or '')
        partidas_formatadas.append(f"{c_id}:{t}:{v}:{cc}:{veic}:{prod}:{cli}:{ent}")

    # Ordenação determinística das partidas
    partidas_formatadas.sort()
    partidas_str = ";".join(partidas_formatadas)

    payload = (
        f"TENANT:{tenant_id}|NUMERO:{numero}|DATA:{data_competencia.isoformat()}|"
        f"HIST:{historico.strip()}|ORIG_TIPO:{origem_tipo}|ORIG_ID:{origem_id}|"
        f"PARTIDAS:{partidas_str}"
    )
    return payload


def _calcular_hash_lancamento(hash_anterior: str, payload_canonico: str) -> str:
    """Calcula o hash encadeado SHA-256 = sha256(hash_anterior + payload_canonico)."""
    conteudo = f"{hash_anterior}|{payload_canonico}".encode('utf-8')
    return hashlib.sha256(conteudo).hexdigest()


@transaction.atomic
def lancar(
    *,
    tenant,
    data_competencia,
    historico: str,
    partidas: Sequence[dict[str, Any]],
    filial=None,
    origem_tipo: str = '',
    origem_id: str = '',
    lancamento_estornado=None,
    data_registro=None,
    usuario=None,
    client_uuid: str = None
):
    """
    Escritura um lançamento em partidas dobradas no Livro Razão Contábil (Sprint 9A - Tarefas 8 e 9).
    Validações estritas:
    1. Tenant ativo e módulo financeiro ativo;
    2. Competência em período contábil aberto;
    3. No mínimo 2 partidas (débito e crédito);
    4. Contas contábeis analíticas, ativas e que aceitam lançamentos;
    5. Valores estritamente positivos (CheckConstraint);
    6. Equilíbrio de partidas: Soma dos Débitos == Soma dos Créditos;
    7. Sequenciamento numérico sob select_for_update() e hash encadeado anti-adulteração.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if not data_competencia:
        raise ValidationError("A data de competência é obrigatória para o lançamento contábil.")

    if not historico or not historico.strip():
        raise ValidationError("O histórico contábil é obrigatório.")

    # 1. Validação de período contábil aberto (F-17)
    checar_periodo_aberto(tenant, data_competencia)

    if not partidas or len(partidas) < 2:
        raise ValidationError("Um lançamento contábil deve conter no mínimo duas partidas (partidas dobradas).")

    # 2. Validação e normalização das partidas
    total_debitos = Decimal('0.00')
    total_creditos = Decimal('0.00')
    partidas_validadas = []

    for idx, p in enumerate(partidas):
        conta_ref = p.get('conta') or p.get('conta_contabil') or p.get('conta_id') or p.get('conta_contabil_id')
        if not conta_ref:
            raise ValidationError(f"Partida {idx + 1}: conta contábil é obrigatória.")

        if isinstance(conta_ref, PlanoContas):
            conta = conta_ref
        elif isinstance(conta_ref, (int, str)):
            conta = PlanoContas.objects.filter(tenant=tenant, id=conta_ref).first()
        else:
            raise ValidationError(f"Partida {idx + 1}: referência de conta contábil inválida.")

        if not conta:
            raise ValidationError(f"Partida {idx + 1}: conta contábil não encontrada no Tenant.")

        if conta.tenant_id != tenant.id:
            raise ValidationError(f"Partida {idx + 1}: conta {conta.codigo_estrutural} pertence a outro Tenant.")

        if not conta.ativo:
            raise ValidationError(f"Partida {idx + 1}: a conta {conta.codigo_estrutural} está inativa.")

        if conta.tipo != 'ANALITICA' or not conta.aceita_lancamento:
            raise ValidationError(
                f"Partida {idx + 1}: a conta {conta.codigo_estrutural} - {conta.nome} é sintética ou não aceita lançamentos. "
                "Lançamentos só podem ser realizados em contas analíticas."
            )

        tipo = p.get('tipo_partida') or p.get('tipo')
        if tipo not in ('DEBITO', 'CREDITO'):
            raise ValidationError(f"Partida {idx + 1}: tipo de partida deve ser 'DEBITO' ou 'CREDITO'.")

        valor_raw = p.get('valor')
        if valor_raw is None:
            raise ValidationError(f"Partida {idx + 1}: valor é obrigatório.")

        valor = quantize(Decimal(str(valor_raw)), 2)
        if valor <= Decimal('0.00'):
            raise ValidationError(f"Partida {idx + 1}: valor deve ser estritamente maior que zero (recebido: R$ {valor}).")

        if tipo == 'DEBITO':
            total_debitos += valor
        else:
            total_creditos += valor

        # Validação das dimensões analíticas opcionais
        cc = p.get('centro_custo')
        cc_id = cc.id if isinstance(cc, CentroCusto) else cc
        if cc_id:
            cc_obj = CentroCusto.objects.filter(tenant=tenant, id=cc_id).first()
            if not cc_obj or not cc_obj.ativo:
                raise ValidationError(f"Partida {idx + 1}: Centro de custo inválido ou inativo.")

        veic = p.get('veiculo')
        veic_id = getattr(veic, 'id', veic)
        prod = p.get('produto_gas')
        prod_id = getattr(prod, 'id', prod)
        cli = p.get('cliente')
        cli_id = getattr(cli, 'id', cli)
        ent = p.get('entrega')
        ent_id = getattr(ent, 'id', ent)

        partidas_validadas.append({
            'conta_obj': conta,
            'conta_id': conta.id,
            'tipo_partida': tipo,
            'valor': valor,
            'centro_custo_id': cc_id,
            'veiculo_id': veic_id,
            'produto_gas_id': prod_id,
            'cliente_id': cli_id,
            'entrega_id': ent_id,
        })

    # 3. Equilíbrio de partidas dobradas
    if total_debitos != total_creditos:
        raise ValidationError(
            f"Lançamento contábil desbalanceado: soma dos débitos (R$ {total_debitos}) "
            f"difere da soma dos créditos (R$ {total_creditos})."
        )

    # 4. Sequenciamento numérico sob lock exclusivo do Tenant (concorrência segura)
    Tenant.objects.select_for_update().get(id=tenant.id)

    ultimo_lancamento = LancamentoContabil.objects.filter(
        tenant=tenant
    ).order_by('-numero').first()

    proximo_numero = (ultimo_lancamento.numero + 1) if ultimo_lancamento else 1
    hash_anterior = ultimo_lancamento.hash_integridade if ultimo_lancamento else ('0' * 64)

    # 5. Cálculo do Hash SHA-256 encadeado
    dt_reg = data_registro or timezone.localdate()
    payload = _calcular_payload_canonico(
        tenant_id=tenant.id,
        numero=proximo_numero,
        data_competencia=data_competencia,
        historico=historico,
        origem_tipo=origem_tipo,
        origem_id=origem_id,
        partidas_dados=partidas_validadas
    )
    hash_integridade = _calcular_hash_lancamento(hash_anterior, payload)

    # 6. Gravação do cabeçalho do lançamento
    lancamento = LancamentoContabil.objects.create(
        tenant=tenant,
        filial=filial,
        numero=proximo_numero,
        data_competencia=data_competencia,
        data_registro=dt_reg,
        historico=historico.strip(),
        origem_tipo=origem_tipo,
        origem_id=str(origem_id) if origem_id else '',
        lancamento_estornado=lancamento_estornado,
        hash_anterior=hash_anterior,
        hash_integridade=hash_integridade,
        criado_por=usuario
    )

    # 7. Gravação das partidas contábeis
    from financeiro.services.snapshot_service import atualizar_snapshot_partida

    partidas_criadas = []
    for pv in partidas_validadas:
        partida = PartidaContabil.objects.create(
            tenant=tenant,
            lancamento=lancamento,
            conta_contabil=pv['conta_obj'],
            tipo_partida=pv['tipo_partida'],
            valor=pv['valor'],
            centro_custo_id=pv['centro_custo_id'],
            veiculo_id=pv['veiculo_id'],
            produto_gas_id=pv['produto_gas_id'],
            cliente_id=pv['cliente_id'],
            entrega_id=pv['entrega_id']
        )
        partidas_criadas.append(partida)

        # Atualização determinística e síncrona do snapshot de saldo mensal (Sprint 10B - Tarefa 6)
        atualizar_snapshot_partida(tenant=tenant, partida=partida)

    return lancamento, partidas_criadas


@transaction.atomic
def estornar(lancamento_id, motivo: str, usuario=None):
    """
    Realiza o estorno integral de um lançamento contábil existente (Sprint 9A - Tarefa 9).
    Inverte todas as partidas (Débitos viram Créditos e vice-versa).
    Se a competência original estiver em um período fechado, o estorno é gravado
    obrigatoriamente na data corrente (período aberto atual) com referência ao lançamento original.
    """
    if not motivo or not motivo.strip():
        raise ValidationError("O motivo formal do estorno é obrigatório.")

    lanc_id = lancamento_id.id if hasattr(lancamento_id, 'id') else lancamento_id
    lancamento = LancamentoContabil.objects.select_related('tenant', 'filial').get(id=lanc_id)
    tenant = lancamento.tenant

    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    # Verifica se já foi estornado anteriormente
    if lancamento.estornos.exists():
        raise ValidationError(f"O lançamento contábil #{lancamento.numero} já foi estornado anteriormente.")

    # Determinação da data de competência do estorno:
    # Se o período original estiver fechado, estorno cai no período aberto corrente (Sprint 9A - Tarefa 5).
    data_estorno = lancamento.data_competencia
    try:
        checar_periodo_aberto(tenant, data_estorno)
    except ValidationError:
        data_estorno = timezone.localdate()
        checar_periodo_aberto(tenant, data_estorno)

    partidas_originais = lancamento.partidas.all()
    if not partidas_originais.exists():
        raise ValidationError(f"O lançamento #{lancamento.numero} não possui partidas contábeis para estornar.")

    # Inverte as partidas
    partidas_inversas = []
    for p in partidas_originais:
        tipo_invertido = 'CREDITO' if p.tipo_partida == 'DEBITO' else 'DEBITO'
        partidas_inversas.append({
            'conta': p.conta_contabil,
            'tipo_partida': tipo_invertido,
            'valor': p.valor,
            'centro_custo': p.centro_custo,
            'veiculo': p.veiculo,
            'produto_gas': p.produto_gas,
            'cliente': p.cliente,
            'entrega': p.entrega,
        })

    hist_estorno = f"Estorno do lançamento #{lancamento.numero}: {motivo.strip()}"

    lancamento_estorno, partidas_estorno = lancar(
        tenant=tenant,
        filial=lancamento.filial,
        data_competencia=data_estorno,
        historico=hist_estorno,
        partidas=partidas_inversas,
        origem_tipo='EstornoLancamento',
        origem_id=str(lancamento.id),
        lancamento_estornado=lancamento,
        usuario=usuario
    )

    return lancamento_estorno, partidas_estorno


def verificar_integridade_razao(tenant):
    """
    Job de auditoria contábil (Sprint 9A - Tarefa 10 / Correção F-18).
    Recalcula rigorosamente toda a cadeia criptográfica de hashes SHA-256 do Livro Razão
    do primeiro ao último lançamento do Tenant.
    Detecta qualquer alteração física ou adulteração em partidas ou cabeçalhos.
    Retorna (valido: bool, erros: list[dict]).
    """
    lancamentos = LancamentoContabil.objects.filter(
        tenant=tenant
    ).prefetch_related('partidas').order_by('numero')

    hash_esperado_anterior = '0' * 64
    erros = []

    for lanc in lancamentos:
        # 1. Verifica encadeamento com o anterior
        if lanc.hash_anterior != hash_esperado_anterior:
            erros.append({
                'lancamento_id': lanc.id,
                'numero': lanc.numero,
                'erro': 'QUEBRA_ENCADEAMENTO_HASH_ANTERIOR',
                'esperado': hash_esperado_anterior,
                'gravado': lanc.hash_anterior
            })

        # 2. Recalcula o hash do lançamento atual com suas partidas
        partidas_dados = []
        for p in lanc.partidas.all():
            partidas_dados.append({
                'conta_id': p.conta_contabil_id,
                'tipo_partida': p.tipo_partida,
                'valor': p.valor,
                'centro_custo_id': p.centro_custo_id,
                'veiculo_id': p.veiculo_id,
                'produto_gas_id': p.produto_gas_id,
                'cliente_id': p.cliente_id,
                'entrega_id': p.entrega_id,
            })

        payload = _calcular_payload_canonico(
            tenant_id=tenant.id,
            numero=lanc.numero,
            data_competencia=lanc.data_competencia,
            historico=lanc.historico,
            origem_tipo=lanc.origem_tipo,
            origem_id=lanc.origem_id,
            partidas_dados=partidas_dados
        )
        hash_recalculado = _calcular_hash_lancamento(lanc.hash_anterior, payload)

        if lanc.hash_integridade != hash_recalculado:
            erros.append({
                'lancamento_id': lanc.id,
                'numero': lanc.numero,
                'erro': 'ADULTERACAO_HASH_INTEGRIDADE',
                'recalculado': hash_recalculado,
                'gravado': lanc.hash_integridade
            })

        hash_esperado_anterior = lanc.hash_integridade

    return len(erros) == 0, erros
