"""
Serviço Canônico de Lançamentos Manuais, Provisões e Alçadas de Aprovação (Sprint 10B - Tarefa 11).
Valida partidas dobradas balanceadas, submete a alçada de aprovação acima do limite e importa provisões em lote via CSV.
"""

import csv
import io
import datetime
from decimal import Decimal
from typing import Optional, Union, Sequence, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    LancamentoManualPendente,
    LancamentoContabil,
    PlanoContas,
    CentroCusto,
)
from financeiro.services.razao import lancar

LIMITE_ALCADA_LANCAMENTO_MANUAL_PADRAO = Decimal('10000.00')


@transaction.atomic
def criar_lancamento_manual(
    *,
    tenant,
    data_competencia: datetime.date,
    historico: str,
    partidas: Optional[Sequence[dict[str, Any]]] = None,
    partidas_data: Optional[Sequence[dict[str, Any]]] = None,
    filial=None,
    usuario=None
) -> tuple[Optional[LancamentoManualPendente], Optional[LancamentoContabil]]:
    """
    Cria uma solicitação de lançamento manual com validação de partidas dobradas e alçada (Sprint 10B - Tarefa 11).
    Retorna (pendente, lancamento).
    Se o valor superar o limite de alçada, entra em estado PENDENTE para aprovação formal.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    partidas_efetivas = partidas or partidas_data
    if not partidas_efetivas or len(partidas_efetivas) < 2:
        raise ValidationError("Um lançamento manual exige no mínimo duas partidas (débito e crédito).")
    partidas = partidas_efetivas

    if not historico or not historico.strip():
        raise ValidationError("O histórico contábil é obrigatório.")

    # 1. Validação de equilíbrio de partidas (D == C)
    total_debitos = Decimal('0.00')
    total_creditos = Decimal('0.00')
    partidas_formatadas = []

    for idx, p in enumerate(partidas, start=1):
        c_id = p.get('conta_id') or p.get('conta_contabil_id')
        tipo = str(p.get('tipo_partida', '')).upper()
        if tipo not in ['DEBITO', 'CREDITO']:
            raise ValidationError(f"Partida {idx}: Tipo inválido ('{tipo}'). Deve ser DEBITO ou CREDITO.")

        val = quantize(Decimal(str(p.get('valor', '0.00'))), 2)
        if val <= Decimal('0.00'):
            raise ValidationError(f"Partida {idx}: O valor deve ser estritamente maior que zero.")

        conta = PlanoContas.unscoped.filter(tenant=tenant, id=c_id).first()
        if not conta:
            raise ValidationError(f"Partida {idx}: Conta contábil #{c_id} não encontrada.")

        if tipo == 'DEBITO':
            total_debitos += val
        else:
            total_creditos += val

        partidas_formatadas.append({
            'conta_id': conta.id,
            'codigo_estrutural': conta.codigo_estrutural,
            'nome_conta': conta.nome,
            'tipo_partida': tipo,
            'valor': str(val),
            'centro_custo_id': p.get('centro_custo_id'),
            'veiculo_id': p.get('veiculo_id'),
            'produto_gas_id': p.get('produto_gas_id'),
        })

    total_debitos = quantize(total_debitos, 2)
    total_creditos = quantize(total_creditos, 2)
    if total_debitos != total_creditos:
        raise ValidationError(
            f"Desequilíbrio de partidas: Total Débitos (R$ {total_debitos}) != Total Créditos (R$ {total_creditos})."
        )

    # 2. Verificação de Alçada
    is_admin = False
    if usuario:
        is_admin = usuario.is_superuser or getattr(usuario, 'papel', '') == 'ADMIN'
        from core.models import Membership
        m = Membership.objects.filter(user=usuario, tenant=tenant, ativo=True).first()
        if m and m.papel in ['ADMIN', 'DIRETOR']:
            is_admin = True

    # Se estiver dentro do limite de alçada, escritura imediatamente
    if total_debitos <= LIMITE_ALCADA_LANCAMENTO_MANUAL_PADRAO:
        lancamento, _ = lancar(
            tenant=tenant,
            data_competencia=data_competencia,
            historico=historico.strip(),
            partidas=[{
                'conta_id': p['conta_id'],
                'tipo_partida': p['tipo_partida'],
                'valor': Decimal(p['valor']),
                'centro_custo_id': p.get('centro_custo_id'),
                'veiculo_id': p.get('veiculo_id'),
                'produto_gas_id': p.get('produto_gas_id'),
            } for p in partidas_formatadas],
            filial=filial,
            origem_tipo='LancamentoManual',
            origem_id='',
            usuario=usuario
        )
        return None, lancamento

    # 3. Caso contrário, gera solicitação pendente de aprovação
    pendente = LancamentoManualPendente.objects.create(
        tenant=tenant,
        data_competencia=data_competencia,
        historico=historico.strip(),
        partidas_json=partidas_formatadas,
        valor_total=total_debitos,
        status='PENDENTE',
        criado_por=usuario
    )
    return pendente, None


@transaction.atomic
def aprovar_lancamento_manual(
    *,
    tenant,
    lancamento_pendente_id: Optional[int] = None,
    pendente_id: Optional[int] = None,
    aprovador=None,
    usuario=None
) -> tuple[LancamentoManualPendente, LancamentoContabil]:
    """Aprova formalmente um lançamento manual pendente e escritura no Razão."""
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    pid = lancamento_pendente_id if lancamento_pendente_id is not None else pendente_id
    usr = aprovador if aprovador is not None else usuario

    pendente = LancamentoManualPendente.unscoped.select_for_update().get(
        tenant=tenant,
        id=pid
    )
    if pendente.status == 'APROVADO':
        return pendente, pendente.lancamento
    if pendente.status == 'REJEITADO':
        raise ValidationError("Não é possível aprovar um lançamento manual previamente rejeitado.")

    # Segregação de funções
    if pendente.criado_por and usr and pendente.criado_por_id == usr.id:
        raise ValidationError("Violação de segregação de funções: o usuário que solicitou o lançamento não pode aprová-lo.")

    # Constrói partidas validadas
    partidas = []
    for p in pendente.partidas_json:
        partidas.append({
            'conta_id': p['conta_id'],
            'tipo_partida': p['tipo_partida'],
            'valor': Decimal(p['valor']),
            'centro_custo_id': p.get('centro_custo_id'),
            'veiculo_id': p.get('veiculo_id'),
            'produto_gas_id': p.get('produto_gas_id'),
        })

    lancamento, _ = lancar(
        tenant=tenant,
        data_competencia=pendente.data_competencia,
        historico=pendente.historico,
        partidas=partidas,
        origem_tipo='LancamentoManualPendente',
        origem_id=str(pendente.id),
        usuario=usr
    )

    pendente.status = 'APROVADO'
    pendente.aprovado_por = usr
    pendente.aprovado_em = timezone.now()
    pendente.lancamento = lancamento
    pendente.save(update_fields=['status', 'aprovado_por', 'aprovado_em', 'lancamento'])

    return lancamento


@transaction.atomic
def rejeitar_lancamento_manual(
    *,
    tenant,
    lancamento_pendente_id: Optional[int] = None,
    pendente_id: Optional[int] = None,
    motivo: str,
    rejeitador=None,
    usuario=None
) -> LancamentoManualPendente:
    """Rejeita uma solicitação de lançamento manual."""
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    pid = lancamento_pendente_id if lancamento_pendente_id is not None else pendente_id
    usr = rejeitador if rejeitador is not None else usuario

    if not motivo or not motivo.strip():
        raise ValidationError("O motivo formal de rejeição é obrigatório.")

    pendente = LancamentoManualPendente.unscoped.select_for_update().get(
        tenant=tenant,
        id=pid
    )
    if pendente.status == 'APROVADO':
        raise ValidationError("Não é possível rejeitar um lançamento manual já escriturado no Razão.")

    pendente.status = 'REJEITADO'
    pendente.motivo_rejeicao = motivo.strip()
    pendente.aprovado_por = usr
    pendente.aprovado_em = datetime.datetime.now()
    pendente.save(update_fields=['status', 'motivo_rejeicao', 'aprovado_por', 'aprovado_em'])
    return pendente


@transaction.atomic
def importar_provisoes_csv(
    *,
    tenant,
    conteudo_csv: str,
    usuario=None
) -> list[LancamentoContabil]:
    """
    Importa provisões contábeis em lote a partir de arquivo CSV (Sprint 10B - Tarefa 11).
    Usado para provisões de folha de pagamento, férias, 13º salário e tributos.
    Colunas esperadas: data_competencia,historico,conta_debito,conta_credito,valor[,centro_custo]
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    reader = csv.DictReader(io.StringIO(conteudo_csv.strip()))
    if not reader.fieldnames:
        raise ValidationError("Arquivo CSV de provisões vazio ou inválido.")

    obrigatorios = {'data_competencia', 'historico', 'conta_debito', 'conta_credito', 'valor'}
    if not obrigatorios.issubset(set(reader.fieldnames)):
        raise ValidationError(f"Cabeçalho do CSV deve conter as colunas: {', '.join(obrigatorios)}")

    lancamentos_criados = []
    for idx, row in enumerate(reader, start=2):
        dt_comp = datetime.date.fromisoformat(row['data_competencia'].strip())
        hist = row['historico'].strip()
        cod_deb = row['conta_debito'].strip()
        cod_cred = row['conta_credito'].strip()
        val = quantize(Decimal(row['valor'].strip().replace(',', '.')), 2)

        cta_deb = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural=cod_deb).first()
        cta_cred = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural=cod_cred).first()

        if not cta_deb or not cta_cred:
            raise ValidationError(f"Linha {idx}: Conta de débito '{cod_deb}' ou crédito '{cod_cred}' não encontrada.")

        cc = None
        cod_cc = row.get('centro_custo', '').strip()
        if cod_cc:
            cc = CentroCusto.unscoped.filter(tenant=tenant, codigo=cod_cc).first()

        partidas = [
            {'conta_id': cta_deb.id, 'tipo_partida': 'DEBITO', 'valor': val, 'centro_custo_id': cc.id if cc else None},
            {'conta_id': cta_cred.id, 'tipo_partida': 'CREDITO', 'valor': val, 'centro_custo_id': cc.id if cc else None},
        ]

        lanc, _ = lancar(
            tenant=tenant,
            data_competencia=dt_comp,
            historico=hist,
            partidas=partidas,
            origem_tipo='IMPORTACAO_PROVISOES_CSV',
            origem_id=f"CSV-LINHA-{idx}",
            usuario=usuario
        )
        lancamentos_criados.append(lanc)

    return lancamentos_criados
