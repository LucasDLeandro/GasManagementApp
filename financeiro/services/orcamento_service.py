"""
Serviço Canônico de Gestão Orçamentária e Importação CSV (Sprint 10B - Tarefa 9).
Permite modelar o plano orçamentário anual, aprovar orçamentos e comparar orçado vs realizado no DRE.
"""

import csv
import io
from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    Orcamento,
    OrcamentoMensalConta,
    PlanoContas,
    CentroCusto,
)


@transaction.atomic
def criar_orcamento(
    *,
    tenant,
    ano: int,
    nome: str,
    usuario=None
) -> Orcamento:
    """Cria um novo plano orçamentário anual no estado RASCUNHO."""
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    if not nome or not nome.strip():
        raise ValidationError("O nome do orçamento é obrigatório.")

    if ano < 2000 or ano > 2100:
        raise ValidationError("Ano de exercício orçamentário inválido.")

    orcamento = Orcamento.objects.create(
        tenant=tenant,
        ano=ano,
        nome=nome.strip(),
        status='RASCUNHO',
        criado_por=usuario
    )
    return orcamento


@transaction.atomic
def aprovar_orcamento(
    *,
    tenant,
    orcamento_id: int,
    aprovador=None,
    usuario=None
) -> Orcamento:
    """Aprova formalmente o orçamento anual."""
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    aprovador_efetivo = aprovador or usuario
    if not aprovador_efetivo:
        raise ValidationError("Usuário aprovador é obrigatório.")

    orcamento = Orcamento.unscoped.select_for_update().get(tenant=tenant, id=orcamento_id)
    if orcamento.status == 'APROVADO':
        return orcamento

    orcamento.status = 'APROVADO'
    orcamento.aprovado_por = aprovador_efetivo
    orcamento.save(update_fields=['status', 'aprovado_por', 'atualizado_em'])
    return orcamento


@transaction.atomic
def importar_orcamento_csv(
    *,
    tenant,
    orcamento_id: int,
    conteudo_csv: Optional[str] = None,
    csv_file=None
) -> int:
    """
    Importa linhas orçamentárias mensais por conta contábil a partir de conteúdo CSV (Sprint 10B - Tarefa 9).
    Colunas esperadas: mes,codigo_conta/conta,valor[,codigo_centro_custo/centro_custo,filial/filial_id]
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    orcamento = Orcamento.unscoped.select_for_update().get(tenant=tenant, id=orcamento_id)
    if orcamento.status == 'APROVADO':
        raise ValidationError("Não é permitido importar ou alterar dados de um orçamento já APROVADO.")

    if csv_file is not None:
        if hasattr(csv_file, 'read'):
            raw = csv_file.read()
            conteudo_csv = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        else:
            conteudo_csv = str(csv_file)

    if not conteudo_csv or not conteudo_csv.strip():
        raise ValidationError("Arquivo CSV de orçamento vazio ou inválido.")

    reader = csv.DictReader(io.StringIO(conteudo_csv.strip()))
    if not reader.fieldnames:
        raise ValidationError("Arquivo CSV de orçamento vazio ou inválido.")

    f_set = set(reader.fieldnames)
    tem_conta = ('codigo_conta' in f_set) or ('conta' in f_set)
    if 'mes' not in f_set or 'valor' not in f_set or not tem_conta:
        raise ValidationError("Cabeçalho do CSV deve conter no mínimo as colunas: mes, conta/codigo_conta, valor")

    itens_criados = 0
    for idx, row in enumerate(reader, start=2):
        try:
            mes = int(row['mes'].strip())
            if not 1 <= mes <= 12:
                raise ValueError()
        except Exception:
            raise ValidationError(f"Linha {idx}: Mês inválido ('{row.get('mes')}'). Deve ser um inteiro de 1 a 12.")

        cod_conta = (row.get('codigo_conta') or row.get('conta') or '').strip()
        conta = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural=cod_conta).first()
        if not conta:
            raise ValidationError(f"Linha {idx}: Conta contábil '{cod_conta}' não encontrada.")

        try:
            valor = quantize(Decimal(row['valor'].strip().replace(',', '.')), 2)
        except Exception:
            raise ValidationError(f"Linha {idx}: Valor inválido ('{row.get('valor')}').")

        # Centro de custo opcional
        cc = None
        cod_cc = (row.get('codigo_centro_custo') or row.get('centro_custo') or '').strip()
        if cod_cc:
            cc = CentroCusto.unscoped.filter(tenant=tenant, codigo=cod_cc).first()

        filial_id = (row.get('filial_id') or row.get('filial') or '').strip() or None

        OrcamentoMensalConta.unscoped.update_or_create(
            tenant=tenant,
            orcamento=orcamento,
            mes=mes,
            conta=conta,
            centro_custo=cc,
            filial_id=filial_id,
            defaults={'valor': valor}
        )
        itens_criados += 1

    return itens_criados
