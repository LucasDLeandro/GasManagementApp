"""
Motor de conciliação bancária inteligente (Sprint 10A - Tarefa 5).
Executa as 5 regras ordenadas para conciliação automática e por sugestão.
"""
import re
import datetime
import itertools
from decimal import Decimal
from typing import Optional, List, Tuple

from django.db import transaction
from django.utils import timezone

from core.money import quantize
from financeiro.models import (
    ExtratoBancarioItem,
    ParcelaFinanceira,
    MovimentoConta,
    RegraConciliacao,
    ContaFinanceira,
)
from financeiro.services.baixas import baixar_parcela
from financeiro.services.conta import registrar_movimento_conta
from financeiro.services.razao import lancar


def _extrair_tokens_nome(nome: str) -> set:
    """Extrai palavras relevantes (maiores que 2 caracteres) para comparação de nomes."""
    ignorar = {'ltda', 'me', 'epp', 's/a', 'sa', 'cia', 'de', 'da', 'do', 'das', 'dos', 'e'}
    palavras = re.findall(r'\b[a-zA-Z0-9]{3,}\b', (nome or '').lower())
    return {p for p in palavras if p not in ignorar}


@transaction.atomic
def processar_item_extrato(
    *,
    tenant,
    item: ExtratoBancarioItem,
    limiar_auto: int = 90,
    usuario=None
) -> bool:
    """
    Aplica as 5 regras de conciliação sobre um item de extrato de forma ordenada e determinística.
    Retorna True se foi conciliado automaticamente, False caso contrário.
    """
    if item.status == 'CONCILIADO' or item.status == 'IGNORADO':
        return False

    # -------------------------------------------------------------------------
    # REGRA 1: NOSSO NÚMERO OU TXID DO PIX (BAIXA AUTOMÁTICA)
    # -------------------------------------------------------------------------
    if item.valor > Decimal('0.00'):
        candidatos_p = ParcelaFinanceira.objects.filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            status__in=['PENDENTE', 'PARCIAL'],
            saldo_em_aberto__gt=Decimal('0.00')
        ).select_related('titulo', 'titulo__cliente')

        for p in candidatos_p:
            match_id = False
            # Verifica se o nosso_número está presente
            if p.nosso_numero and len(p.nosso_numero) >= 4:
                if (p.nosso_numero in item.documento or
                    p.nosso_numero in item.descricao or
                    p.nosso_numero in item.fitid):
                    match_id = True

            # Verifica se o txid do PIX está presente
            if not match_id and p.txid_pix and len(p.txid_pix) >= 6:
                if (p.txid_pix in item.documento or
                    p.txid_pix in item.descricao or
                    p.txid_pix in item.fitid):
                    match_id = True

            if match_id:
                # Regra 1 identificada! Baixa automática da parcela
                v_baixa = min(item.valor, p.saldo_em_aberto)
                baixa = baixar_parcela(
                    tenant=tenant,
                    parcela_id=p.id,
                    conta_financeira_id=item.conta_id,
                    valor_principal=v_baixa,
                    data_liquidacao=item.data,
                    comprovante=item.documento or item.fitid or f"Extrato #{item.id}",
                    usuario=usuario
                )
                item.movimento = baixa.movimento_conta
                item.status = 'CONCILIADO'
                item.score = 100
                item.regra_aplicada = 'REGRA_1_IDENTIFICADOR_DIRETO'
                item.motivo_sugestao = f"Conciliação automática via identificador direto ({p.nosso_numero or p.txid_pix})."
                item.parcelas_sugeridas_ids = [p.id]
                item.save()
                return True

    # -------------------------------------------------------------------------
    # REGRA 2: VALOR EXATO + JANELA ±3 DIAS + DOCUMENTO DO PAGADOR (CPF/CNPJ)
    # -------------------------------------------------------------------------
    if item.valor > Decimal('0.00'):
        data_min = item.data - datetime.timedelta(days=3)
        data_max = item.data + datetime.timedelta(days=3)

        candidatos_r2 = ParcelaFinanceira.objects.filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            status__in=['PENDENTE', 'PARCIAL'],
            saldo_em_aberto=item.valor,
            data_vencimento__range=[data_min, data_max]
        ).select_related('titulo', 'titulo__cliente')

        doc_extrato_limpo = re.sub(r'\D', '', f"{item.documento} {item.descricao} {item.fitid}")

        for p in candidatos_r2:
            doc_cliente = re.sub(r'\D', '', (p.titulo.cliente.documento if p.titulo.cliente else '') or '')
            if doc_cliente and len(doc_cliente) >= 8 and doc_cliente in doc_extrato_limpo:
                score = 95
                if score >= limiar_auto:
                    baixa = baixar_parcela(
                        tenant=tenant,
                        parcela_id=p.id,
                        conta_financeira_id=item.conta_id,
                        valor_principal=item.valor,
                        data_liquidacao=item.data,
                        comprovante=item.documento or f"Extrato #{item.id}",
                        usuario=usuario
                    )
                    item.movimento = baixa.movimento_conta
                    item.status = 'CONCILIADO'
                    item.score = score
                    item.regra_aplicada = 'REGRA_2_VALOR_DATA_DOCUMENTO'
                    item.motivo_sugestao = f"Conciliação automática por valor exato, data (±3d) e documento do cliente ({doc_cliente})."
                    item.parcelas_sugeridas_ids = [p.id]
                    item.save()
                    return True
                else:
                    item.status = 'SUGERIDO'
                    item.score = score
                    item.regra_aplicada = 'REGRA_2_VALOR_DATA_DOCUMENTO'
                    item.motivo_sugestao = f"Sugestão de conciliação por documento ({doc_cliente}) abaixo do limiar configurado."
                    item.parcelas_sugeridas_ids = [p.id]
                    item.save()
                    return False

    # -------------------------------------------------------------------------
    # REGRA 3: VALOR EXATO + JANELA ±3 DIAS + SIMILARIDADE DE NOME (APENAS SUGERIDO)
    # -------------------------------------------------------------------------
    if item.valor > Decimal('0.00'):
        data_min = item.data - datetime.timedelta(days=3)
        data_max = item.data + datetime.timedelta(days=3)

        candidatos_r3 = ParcelaFinanceira.objects.filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            status__in=['PENDENTE', 'PARCIAL'],
            saldo_em_aberto=item.valor,
            data_vencimento__range=[data_min, data_max]
        ).select_related('titulo', 'titulo__cliente')

        tokens_extrato = _extrair_tokens_nome(item.descricao)

        for p in candidatos_r3:
            if not p.titulo.cliente:
                continue
            tokens_cliente = _extrair_tokens_nome(p.titulo.cliente.nome)
            intersecao = tokens_extrato.intersection(tokens_cliente)

            # Se houver similaridade nominal mínima de 1 token significativo ou 2 tokens
            if len(intersecao) >= 1:
                item.status = 'SUGERIDO'
                item.score = 80
                item.regra_aplicada = 'REGRA_3_VALOR_DATA_NOME'
                item.motivo_sugestao = (
                    f"Sugestão por similaridade no nome do cliente '{p.titulo.cliente.nome}' "
                    f"({', '.join(intersecao)}) e valor idêntico (R$ {item.valor}). Confirmação humana obrigatória."
                )
                item.parcelas_sugeridas_ids = [p.id]
                item.save()
                return False

    # -------------------------------------------------------------------------
    # REGRA 4: UM DEPÓSITO PARA VÁRIAS PARCELAS DO MESMO CLIENTE (ATÉ 5 PARCELAS)
    # -------------------------------------------------------------------------
    if item.valor > Decimal('0.00'):
        data_min = item.data - datetime.timedelta(days=3)
        data_max = item.data + datetime.timedelta(days=3)

        candidatos_r4 = ParcelaFinanceira.objects.filter(
            tenant=tenant,
            titulo__tipo='RECEBER',
            status__in=['PENDENTE', 'PARCIAL'],
            saldo_em_aberto__gt=Decimal('0.00'),
            saldo_em_aberto__lt=item.valor,
            data_vencimento__range=[data_min, data_max],
            titulo__cliente__isnull=False
        ).select_related('titulo', 'titulo__cliente')

        # Agrupa por cliente
        por_cliente = {}
        for p in candidatos_r4:
            cid = p.titulo.cliente_id
            if cid not in por_cliente:
                por_cliente[cid] = []
            por_cliente[cid].append(p)

        for cid, parcelas_cli in por_cliente.items():
            if len(parcelas_cli) < 2:
                continue

            # Testa combinações de 2 até 5 parcelas
            encontrado = None
            max_tam = min(len(parcelas_cli), 5)
            for r in range(2, max_tam + 1):
                for combo in itertools.combinations(parcelas_cli, r):
                    soma_combo = sum(c.saldo_em_aberto for c in combo)
                    if quantize(soma_combo, 2) == item.valor:
                        encontrado = combo
                        break
                if encontrado:
                    break

            if encontrado:
                cli_nome = encontrado[0].titulo.cliente.nome
                item.status = 'SUGERIDO'
                item.score = 75
                item.regra_aplicada = 'REGRA_4_DEPOSITO_MULTIPLAS_PARCELAS'
                item.parcelas_sugeridas_ids = [c.id for c in encontrado]
                item.motivo_sugestao = (
                    f"Sugestão: depósito de R$ {item.valor} coincide exatamente com a soma de "
                    f"{len(encontrado)} parcelas do cliente '{cli_nome}'. Confirmação humana obrigatória."
                )
                item.save()
                return False

    # -------------------------------------------------------------------------
    # REGRA 5: TARIFAS E RENDIMENTOS POR RegraConciliacao (MOVIMENTO + LANÇAMENTO)
    # -------------------------------------------------------------------------
    regras = RegraConciliacao.objects.filter(tenant=tenant, ativo=True).select_related('conta_contabil', 'centro_custo')
    desc_upper = item.descricao.upper()

    for regra in regras:
        padrao = regra.padrao_descricao.strip().upper()
        if padrao and padrao in desc_upper:
            # Regra casou! Cria MovimentoConta e Lançamento no Razão
            conta_fin = item.conta
            val_abs = abs(item.valor)

            if item.valor < Decimal('0.00'):
                # Despesa bancária (Tarifa, Imposto, IOF)
                tipo_mov = 'TARIFA' if regra.tipo_regra == 'TARIFA' else 'SAIDA'
                mov = registrar_movimento_conta(
                    tenant=tenant,
                    conta=conta_fin,
                    tipo=tipo_mov,
                    valor=val_abs,
                    historico=f"{regra.get_tipo_regra_display()}: {item.descricao}"
                )
                # Partida dobrada contábil:
                # D: Conta de Despesa da Regra
                # C: Conta de Disponibilidades Bancária
                partidas = [
                    {
                        'conta_contabil_id': regra.conta_contabil_id,
                        'tipo_partida': 'DEBITO',
                        'valor': val_abs,
                        'centro_custo_id': regra.centro_custo_id,
                    },
                    {
                        'conta_contabil_id': conta_fin.conta_contabil_id,
                        'tipo_partida': 'CREDITO',
                        'valor': val_abs,
                    }
                ]
            else:
                # Rendimento de aplicação financeira
                tipo_mov = 'RENDIMENTO'
                mov = registrar_movimento_conta(
                    tenant=tenant,
                    conta=conta_fin,
                    tipo=tipo_mov,
                    valor=val_abs,
                    historico=f"Rendimento de Aplicação: {item.descricao}"
                )
                # Partida dobrada contábil:
                # D: Conta de Disponibilidades Bancária
                # C: Conta de Receita Financeira da Regra
                partidas = [
                    {
                        'conta_contabil_id': conta_fin.conta_contabil_id,
                        'tipo_partida': 'DEBITO',
                        'valor': val_abs,
                    },
                    {
                        'conta_contabil_id': regra.conta_contabil_id,
                        'tipo_partida': 'CREDITO',
                        'valor': val_abs,
                        'centro_custo_id': regra.centro_custo_id,
                    }
                ]

            lancar(
                tenant=tenant,
                filial=conta_fin.filial,
                data_competencia=item.data,
                historico=f"Conciliação Automática [{regra.tipo_regra}] - {item.descricao}",
                partidas=partidas,
                usuario=usuario
            )

            item.movimento = mov
            item.status = 'CONCILIADO'
            item.score = 90
            item.regra_aplicada = f"REGRA_5_EXTRATO_{regra.tipo_regra}"
            item.motivo_sugestao = f"Conciliado automaticamente conforme regra contábil '{regra.padrao_descricao}'."
            item.save()
            return True

    # -------------------------------------------------------------------------
    # NADA CASOU OU ABAIXO DO LIMIAR: PERMANECE NÃO CONCILIADO
    # -------------------------------------------------------------------------
    item.status = 'NAO_CONCILIADO'
    item.score = 0
    item.save(update_fields=['status', 'score', 'conciliado'])
    return False
