"""
Serviços de conciliação bancária (Sprint 10A - Tarefas 2, 3, 4, 6).
Gerencia importação de OFX/CNAB, batimento de saldo, conciliação manual, divisão, estorno e regras de fechamento.
"""
import hashlib
import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    ContaFinanceira,
    ImportacaoExtrato,
    ExtratoBancarioItem,
    MovimentoConta,
    ParcelaFinanceira,
    PlanoContas,
    CentroCusto,
    BaixaParcela,
)
from financeiro.services.conta import saldo_em, registrar_movimento_conta
from financeiro.services.razao import lancar, estornar
from financeiro.services.baixas import baixar_parcela, estornar_baixa
from financeiro.banco.ofx_parser import OFXParser
from financeiro.banco.cnab_adapter import ArquivoCNABAdapter
from financeiro.conciliacao import processar_item_extrato


@transaction.atomic
def importar_extrato(
    *,
    tenant,
    conta_id: int,
    tipo: str,  # 'OFX' ou 'CNAB_RETORNO'
    arquivo_bytes: bytes,
    nome_arquivo: str = "extrato.ofx",
    usuario=None,
    limiar_auto: int = 90
) -> ImportacaoExtrato:
    """
    Importa arquivo de extrato bancário (OFX ou CNAB Retorno) com verificação de hash SHA-256 (Sprint 10A - Tarefa 2 e 4).
    Calcula e compara o saldo final do extrato contra o saldo apurado pelo Razão / MovimentoConta.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    conta = ContaFinanceira.objects.select_for_update().get(id=conta_id)
    if conta.tenant_id != tenant.id:
        raise ValidationError("Conta financeira pertence a outro Tenant.")

    # 1. Deduplicação do arquivo pelo Hash SHA-256
    hash_arq = hashlib.sha256(arquivo_bytes).hexdigest()
    if ImportacaoExtrato.objects.filter(tenant=tenant, hash_arquivo=hash_arq).exists():
        raise ValidationError(
            f"O arquivo '{nome_arquivo}' (Hash {hash_arq[:12]}...) já foi importado anteriormente neste Tenant. "
            f"Reimportação rejeitada por segurança e integridade contábil."
        )

    # 2. Parsing do arquivo conforme o tipo
    transacoes = []
    periodo_ini = None
    periodo_fim = None
    saldo_final_arquivo = None

    if tipo == 'OFX':
        ofx_res = OFXParser.parse(arquivo_bytes, conta.id)
        periodo_ini = ofx_res.data_inicio
        periodo_fim = ofx_res.data_fim
        saldo_final_arquivo = ofx_res.saldo_final
        transacoes = ofx_res.transacoes
    elif tipo == 'CNAB_RETORNO':
        texto = arquivo_bytes.decode('latin1', errors='replace')
        cnab_res = ArquivoCNABAdapter().processar_retorno_cnab400(texto)
        if cnab_res:
            periodo_ini = min(item.data_ocorrencia for item in cnab_res)
            periodo_fim = max(item.data_ocorrencia for item in cnab_res)
        for item in cnab_res:
            raw_dedup = f"{conta.id}|{item.data_ocorrencia.isoformat()}|{item.valor_pago}|{item.nosso_numero}|{item.descricao_ocorrencia}"
            h_dedup = hashlib.sha256(raw_dedup.encode('utf-8')).hexdigest()
            transacoes.append(type('CNABItemMock', (), {
                'tipo': 'CREDIT',
                'data': item.data_ocorrencia,
                'valor': item.valor_pago,
                'fitid': item.nosso_numero,
                'documento': item.numero_documento,
                'descricao': f"RETORNO CNAB - {item.descricao_ocorrencia} (Nosso Nº: {item.nosso_numero})",
                'hash_dedup': h_dedup,
            }))
    else:
        raise ValidationError(f"Tipo de importação '{tipo}' inválido. Utilize OFX ou CNAB_RETORNO.")

    # 3. Comparação com o saldo apurado pelo MovimentoConta na data final
    dt_referencia = periodo_fim or timezone.localdate()
    saldo_sistema = saldo_em(conta, dt_referencia)
    diferenca = None
    if saldo_final_arquivo is not None:
        diferenca = quantize(saldo_final_arquivo - saldo_sistema, 2)

    # 4. Cria registro de importação
    importacao = ImportacaoExtrato(
        tenant=tenant,
        conta=conta,
        tipo=tipo,
        hash_arquivo=hash_arq,
        periodo_ini=periodo_ini,
        periodo_fim=periodo_fim,
        saldo_final_arquivo=saldo_final_arquivo,
        saldo_sistema_apurado=saldo_sistema,
        diferenca_saldo=diferenca,
        usuario=usuario
    )
    importacao.arquivo.save(nome_arquivo, ContentFile(arquivo_bytes), save=False)
    importacao.save()

    # 5. Criação e conciliação dos itens de extrato
    for trn in transacoes:
        # Se já existe item idêntico deduplicado para esta conta, ignora a duplicação
        if ExtratoBancarioItem.objects.filter(tenant=tenant, conta=conta, hash_dedup=trn.hash_dedup).exists():
            continue

        item = ExtratoBancarioItem.objects.create(
            tenant=tenant,
            importacao=importacao,
            conta=conta,
            data=trn.data,
            valor=trn.valor,
            descricao=trn.descricao,
            documento=trn.documento,
            fitid=trn.fitid,
            hash_dedup=trn.hash_dedup,
            status='NAO_CONCILIADO'
        )

        # Executa motor inteligente de matching
        processar_item_extrato(
            tenant=tenant,
            item=item,
            limiar_auto=limiar_auto,
            usuario=usuario
        )

    return importacao


@transaction.atomic
def conciliar_manualmente(
    *,
    tenant,
    item_id: int,
    parcelas_ids: List[int],
    usuario=None
) -> ExtratoBancarioItem:
    """
    Efetua a conciliação manual selecionando uma ou mais parcelas em aberto (Sprint 10A - Tarefa 6).
    Valida bloqueio de data por conciliacao_fechada_ate.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    item = ExtratoBancarioItem.objects.select_for_update().get(id=item_id)
    if item.tenant_id != tenant.id:
        raise ValidationError("Item de extrato pertence a outro Tenant.")

    if item.status == 'CONCILIADO':
        raise ValidationError(f"O item de extrato #{item.id} já se encontra conciliado.")

    conta = item.conta
    if conta.conciliacao_fechada_ate and item.data <= conta.conciliacao_fechada_ate:
        raise ValidationError(
            f"Operação Bloqueada: A conta {conta.nome} possui conciliação bancária fechada até "
            f"{conta.conciliacao_fechada_ate.strftime('%d/%m/%Y')}. Lançamentos em datas anteriores não podem ser conciliados."
        )

    if not parcelas_ids:
        raise ValidationError("Selecione ao menos uma parcela para realizar a conciliação.")

    parcelas = list(ParcelaFinanceira.objects.select_for_update().filter(
        tenant=tenant,
        id__in=parcelas_ids
    ))
    if len(parcelas) != len(parcelas_ids):
        raise ValidationError("Uma ou mais parcelas selecionadas não pertencem ao Tenant ou não existem.")

    soma_parcelas = sum(p.saldo_em_aberto for p in parcelas)
    if quantize(soma_parcelas, 2) != item.valor:
        raise ValidationError(
            f"Divergência de valores: A soma das parcelas (R$ {soma_parcelas}) difere do valor "
            f"do item de extrato (R$ {item.valor})."
        )

    # Executa a baixa das parcelas
    ultima_baixa = None
    for p in parcelas:
        baixa = baixar_parcela(
            tenant=tenant,
            parcela_id=p.id,
            conta_financeira_id=conta.id,
            valor_principal=p.saldo_em_aberto,
            data_liquidacao=item.data,
            comprovante=item.documento or item.fitid or f"Extrato #{item.id}",
            usuario=usuario
        )
        ultima_baixa = baixa

    item.status = 'CONCILIADO'
    item.movimento = ultima_baixa.movimento_conta if ultima_baixa else None
    item.score = 100
    item.regra_aplicada = 'MANUAL'
    item.motivo_sugestao = f"Conciliado manualmente pelo usuário {usuario.username if usuario else 'Sistema'}."
    item.parcelas_sugeridas_ids = parcelas_ids
    item.save()

    return item


@transaction.atomic
def criar_lancamento_direto(
    *,
    tenant,
    item_id: int,
    conta_contabil_id: int,
    centro_custo_id: Optional[int] = None,
    historico: str = '',
    usuario=None
) -> ExtratoBancarioItem:
    """
    Cria movimento bancário e lançamento contábil direto a partir do extrato (ex: tarifas avulsas, rendimentos)
    (Sprint 10A - Tarefa 6).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    item = ExtratoBancarioItem.objects.select_for_update().get(id=item_id)
    if item.tenant_id != tenant.id:
        raise ValidationError("Item de extrato pertence a outro Tenant.")

    if item.status == 'CONCILIADO':
        raise ValidationError(f"O item de extrato #{item.id} já está conciliado.")

    conta = item.conta
    if conta.conciliacao_fechada_ate and item.data <= conta.conciliacao_fechada_ate:
        raise ValidationError(
            f"Operação Bloqueada: Conciliação fechada até {conta.conciliacao_fechada_ate.strftime('%d/%m/%Y')}."
        )

    conta_contrapartida = PlanoContas.objects.get(id=conta_contabil_id)
    if conta_contrapartida.tenant_id != tenant.id:
        raise ValidationError("Conta contábil pertence a outro Tenant.")
    if not conta_contrapartida.aceita_lancamento or conta_contrapartida.tipo != 'ANALITICA':
        raise ValidationError("A conta contábil de contrapartida deve ser analítica e aceitar lançamentos.")

    val_abs = abs(item.valor)
    hist_op = historico or item.descricao

    if item.valor < Decimal('0.00'):
        # Débito no extrato (saída/despesa)
        mov = registrar_movimento_conta(
            tenant=tenant,
            conta=conta,
            tipo='SAIDA',
            valor=val_abs,
            historico=hist_op
        )
        partidas = [
            {'conta_contabil_id': conta_contrapartida.id, 'tipo_partida': 'DEBITO', 'valor': val_abs, 'centro_custo_id': centro_custo_id},
            {'conta_contabil_id': conta.conta_contabil_id, 'tipo_partida': 'CREDITO', 'valor': val_abs},
        ]
    else:
        # Crédito no extrato (entrada/receita)
        mov = registrar_movimento_conta(
            tenant=tenant,
            conta=conta,
            tipo='ENTRADA',
            valor=val_abs,
            historico=hist_op
        )
        partidas = [
            {'conta_contabil_id': conta.conta_contabil_id, 'tipo_partida': 'DEBITO', 'valor': val_abs},
            {'conta_contabil_id': conta_contrapartida.id, 'tipo_partida': 'CREDITO', 'valor': val_abs, 'centro_custo_id': centro_custo_id},
        ]

    lancar(
        tenant=tenant,
        filial=conta.filial,
        data_competencia=item.data,
        historico=hist_op,
        partidas=partidas,
        usuario=usuario
    )

    item.movimento = mov
    item.status = 'CONCILIADO'
    item.score = 100
    item.regra_aplicada = 'LANCAMENTO_DIRETO'
    item.motivo_sugestao = f"Lançamento direto para {conta_contrapartida.nome}."
    item.save()

    return item


@transaction.atomic
def dividir_item_extrato(
    *,
    tenant,
    item_id: int,
    partes: List[Dict[str, Any]],
    usuario=None
) -> List[ExtratoBancarioItem]:
    """
    Divide um item de extrato em múltiplas parcelas menores para permitir conciliação fracionada
    (Sprint 10A - Tarefa 6). A soma das partes deve ser exatamente igual ao valor original.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    item = ExtratoBancarioItem.objects.select_for_update().get(id=item_id)
    if item.tenant_id != tenant.id:
        raise ValidationError("Item de extrato pertence a outro Tenant.")

    if item.status == 'CONCILIADO':
        raise ValidationError("Não é possível dividir um item de extrato já conciliado.")

    if len(partes) < 2:
        raise ValidationError("A divisão exige no mínimo duas partes.")

    soma_partes = sum(quantize(Decimal(str(p['valor'])), 2) for p in partes)
    if soma_partes != item.valor:
        raise ValidationError(
            f"A soma das partes (R$ {soma_partes}) difere do valor total do item (R$ {item.valor})."
        )

    novos_itens = []
    for idx, p in enumerate(partes, start=1):
        v = quantize(Decimal(str(p['valor'])), 2)
        desc = p.get('descricao') or f"{item.descricao} (Parte {idx}/{len(partes)})"
        h_sub = hashlib.sha256(f"{item.hash_dedup}_sub_{idx}".encode('utf-8')).hexdigest()
        
        sub_item = ExtratoBancarioItem.objects.create(
            tenant=tenant,
            importacao=item.importacao,
            conta=item.conta,
            data=item.data,
            valor=v,
            descricao=desc,
            documento=item.documento,
            fitid=f"{item.fitid}_p{idx}",
            hash_dedup=h_sub,
            status='NAO_CONCILIADO',
            motivo_sugestao=f"Originado da divisão do item #{item.id}."
        )
        novos_itens.append(sub_item)

    # Marca o item original como IGNORADO com referência à divisão
    item.status = 'IGNORADO'
    item.motivo_sugestao = f"Item dividido em {len(partes)} sub-itens (#{', #'.join(str(n.id) for n in novos_itens)})."
    item.save()

    return novos_itens


@transaction.atomic
def ignorar_item_extrato(
    *,
    tenant,
    item_id: int,
    motivo: str = 'Ignorado pelo usuário',
    usuario=None
) -> ExtratoBancarioItem:
    """
    Marca explicitamente um item de extrato como IGNORADO (Sprint 10A - Tarefa 6).
    Nenhum item bancário fica sem estado definido.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    item = ExtratoBancarioItem.objects.select_for_update().get(id=item_id)
    if item.tenant_id != tenant.id:
        raise ValidationError("Item de extrato pertence a outro Tenant.")

    if item.status == 'CONCILIADO':
        raise ValidationError("Não é possível ignorar um item já conciliado. Desfaça a conciliação primeiro.")

    item.status = 'IGNORADO'
    item.motivo_sugestao = motivo.strip()
    item.save()
    return item


@transaction.atomic
def desfazer_conciliacao(
    *,
    tenant,
    item_id: int,
    motivo: str = 'Desfazimento de conciliação solicitado',
    usuario=None
) -> ExtratoBancarioItem:
    """
    Desfaz a conciliação bancária de forma auditada (Sprint 10A - Tarefa 6).
    Bloqueado estritamente caso a data seja igual ou anterior a conta.conciliacao_fechada_ate.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    item = ExtratoBancarioItem.objects.select_for_update().get(id=item_id)
    if item.tenant_id != tenant.id:
        raise ValidationError("Item de extrato pertence a outro Tenant.")

    if item.status != 'CONCILIADO':
        raise ValidationError(f"O item #{item.id} não está conciliado (status atual: {item.status}).")

    conta = item.conta
    if conta.conciliacao_fechada_ate and item.data <= conta.conciliacao_fechada_ate:
        raise ValidationError(
            f"Impossível desfazer conciliação: A conta '{conta.nome}' possui conciliação "
            f"fechada até {conta.conciliacao_fechada_ate.strftime('%d/%m/%Y')}. "
            f"Desfazimento bloqueado para integridade contábil e auditoria."
        )

    # 1. Se houver baixas associadas a este item ou ao movimento
    if item.movimento:
        baixas = BaixaParcela.objects.filter(movimento_conta=item.movimento, estornado=False)
        for b in baixas:
            estornar_baixa(
                tenant=tenant,
                baixa_id=b.id,
                motivo=f"Estorno por desfazimento de conciliação: {motivo}",
                usuario=usuario
            )
        # Se for movimento direto (sem baixa)
        if not baixas.exists():
            tipo_rev = 'SAIDA' if item.movimento.tipo in ('ENTRADA', 'RENDIMENTO') else 'ENTRADA'
            registrar_movimento_conta(
                tenant=tenant,
                conta=conta,
                tipo=tipo_rev,
                valor=item.movimento.valor,
                historico=f"Estorno de conciliação direta - Item #{item.id}: {motivo}"
            )

    item.status = 'NAO_CONCILIADO'
    item.movimento = None
    item.score = 0
    item.regra_aplicada = ''
    item.motivo_sugestao = f"Conciliação desfeita em {timezone.now().strftime('%d/%m/%Y %H:%M')} por {usuario.username if usuario else 'Sistema'}. Motivo: {motivo}."
    item.parcelas_sugeridas_ids = []
    item.save()

    return item
