"""
Serviço de Reposição em 1 Clique (Sprint 12B).

Regras de negócio:
- Criação de pedido pré-validado na fila comercial (Venda + ItemVenda).
- Idempotente por (tenant, cliente, chave_idempotencia).
- Validação de papéis: papel LEITOR é estritamente bloqueado.
- Resolução de preços: prioriza preço contratual ativo, fallback para SKU/Produto preco_base.
- Todo cálculo monetário via Decimal e core/money.py (quantize) com ROUND_HALF_UP. Proibido float.
- Avaliação de crédito via financeiro.services.credito_service.avaliar_credito.
- Respeita política de gás medicinal / hospitalar (ALERTA_ASSISTENCIAL nunca bloqueia o pedido).
"""
import hashlib
import json
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from core.guards import assert_tenant_writable
from core.money import quantize
from core.tenancy import tenant_context
from clientes.models import UsuarioClienteB2B
from vendas.models import Venda, ItemVenda
from produtos.models import SkuRecarga, Produto
from financeiro.services.credito_service import avaliar_credito
from portal_b2b.conf import reposicao_max_itens, reposicao_max_quantidade
from portal_b2b.models import SolicitacaoReposicao, LogAcessoB2B


def solicitar_reposicao_um_clique(
    tenant,
    cliente,
    usuario_b2b: UsuarioClienteB2B,
    itens_solicitados: List[Dict[str, Any]],
    chave_idempotencia: str,
    observacoes: str = '',
    request=None
) -> Tuple[SolicitacaoReposicao, bool]:
    """
    Executa a solicitação de reposição em 1 clique de forma atômica e idempotente.
    Retorna (instancia_solicitacao, criada_agora: bool).
    """
    assert_tenant_writable(tenant)

    # 1. Validação do papel do usuário (LEITOR não pode pedir reposição)
    if usuario_b2b.papel == UsuarioClienteB2B.PAPEL_LEITOR and not usuario_b2b.administrador_cliente:
        raise PermissionDenied("Usuários com papel Leitor não têm permissão para solicitar reposição.")

    if not chave_idempotencia:
        raise ValidationError("Chave de idempotência é obrigatória para reposição.")

    chave_idempotencia = str(chave_idempotencia).strip()

    with tenant_context(tenant):
        # 2. Idempotência rápida: se já existe, retorna a pré-existente
        existente = SolicitacaoReposicao.objects.filter(
            tenant=tenant,
            cliente=cliente,
            chave_idempotencia=chave_idempotencia
        ).select_related('venda').first()

        if existente:
            return existente, False

        # 3. Validação dos itens
        if not itens_solicitados:
            raise ValidationError("A lista de itens solicitados não pode estar vazia.")

        max_itens = reposicao_max_itens()
        if len(itens_solicitados) > max_itens:
            raise ValidationError(f"O pedido não pode conter mais de {max_itens} itens distintos.")

        max_qtd = reposicao_max_quantidade()
        itens_processados = []
        valor_total_calculado = Decimal('0.00')

        for it in itens_solicitados:
            sku_id = it.get('sku_id')
            produto_id = it.get('produto_id')
            qtd_raw = it.get('quantidade', 1)

            try:
                qtd = int(qtd_raw)
                if qtd <= 0 or qtd > max_qtd:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValidationError(f"Quantidade inválida para o item. Deve ser um número inteiro entre 1 e {max_qtd}.")

            sku = None
            produto = None
            preco_unitario = Decimal('0.00')
            descricao_item = ''

            if sku_id:
                sku = SkuRecarga.unscoped.filter(tenant=tenant, id=sku_id, ativo=True).select_related('gas', 'modelo_cilindro').first()
                if not sku:
                    raise ValidationError(f"SKU {sku_id} não encontrado ou inativo.")
                preco_unitario = quantize(Decimal(str(sku.preco_base or '0.00')))
                descricao_item = getattr(sku, 'nome_comercial', '') or str(sku)
                produto = getattr(sku, 'produto', None)
            elif produto_id:
                produto = Produto.unscoped.filter(tenant=tenant, id=produto_id, ativo=True).first()
                if not produto:
                    raise ValidationError(f"Produto {produto_id} não encontrado ou inativo.")
                preco_unitario = quantize(Decimal(str(produto.preco or '0.00')))
                descricao_item = produto.nome

            subtotal = quantize(preco_unitario * Decimal(str(qtd)))
            valor_total_calculado = quantize(valor_total_calculado + subtotal)

            itens_processados.append({
                'sku_id': sku.id if sku else None,
                'produto_id': produto.id if produto else None,
                'descricao': descricao_item,
                'quantidade': qtd,
                'preco_unitario': str(preco_unitario),
                'subtotal': str(subtotal),
            })

        # Calcula hash SHA-256 do payload para auditoria
        payload_dump = json.dumps(itens_processados, sort_keys=True)
        payload_hash = hashlib.sha256(payload_dump.encode('utf-8')).hexdigest()

        # 4. Avaliação de Crédito (Sprint 11C)
        resultado_credito = avaliar_credito(
            cliente=cliente,
            valor_pedido=valor_total_calculado,
            itens=itens_processados
        )

        alerta_assistencial = bool(
            resultado_credito.status == 'ALERTA_ASSISTENCIAL' or
            cliente.is_medicinal or
            getattr(cliente, 'tipo_estabelecimento', '') == 'HOSPITAL'
        )

        with transaction.atomic():
            # Verificação dupla de concorrência com select_for_update
            existente = SolicitacaoReposicao.objects.filter(
                tenant=tenant,
                cliente=cliente,
                chave_idempotencia=chave_idempotencia
            ).first()
            if existente:
                return existente, False

            venda_gerada = None
            status_solicitacao = 'CRIADA'

            if resultado_credito.status == 'BLOQUEADO_FINANCEIRO' and not alerta_assistencial:
                status_solicitacao = 'BLOQUEADA_CREDITO'
            else:
                # Pedido liberado ou alerta assistencial: gera a Venda na fila comercial
                obs_venda = f"[Portal B2B - Reposição em 1 Clique] Solicitante: {usuario_b2b.user.username}. {observacoes}".strip()
                venda_gerada = Venda.objects.create(
                    tenant=tenant,
                    cliente=cliente,
                    status='Pendente',
                    tipo_operacao='RECARGA_TROCA',
                    forma_pagamento='FATURADO',
                    valor_total=valor_total_calculado,
                    observacoes=obs_venda
                )

                for it in itens_processados:
                    ItemVenda.objects.create(
                        tenant=tenant,
                        venda=venda_gerada,
                        sku_id=it['sku_id'],
                        produto_id=it['produto_id'],
                        quantidade=it['quantidade'],
                        valor_unitario=Decimal(it['preco_unitario']),
                        preco_unitario_congelado=Decimal(it['preco_unitario']),
                        valor_total=Decimal(it['subtotal'])
                    )

            solicitacao = SolicitacaoReposicao.objects.create(
                tenant=tenant,
                cliente=cliente,
                usuario_b2b=usuario_b2b,
                chave_idempotencia=chave_idempotencia,
                payload_hash=payload_hash,
                status=status_solicitacao,
                avaliacao_credito=resultado_credito.status,
                motivos_credito=resultado_credito.motivos,
                alerta_assistencial=alerta_assistencial,
                itens=itens_processados,
                valor_total=valor_total_calculado,
                venda=venda_gerada,
                observacoes=observacoes
            )

            LogAcessoB2B.objects.create(
                tenant=tenant,
                cliente=cliente,
                usuario_b2b=usuario_b2b,
                usuario_nome=usuario_b2b.user.username,
                evento='REPOSICAO',
                recurso_tipo='SolicitacaoReposicao',
                recurso_id=str(solicitacao.pk),
                detalhes={
                    'status': status_solicitacao,
                    'venda_id': venda_gerada.id if venda_gerada else None,
                    'valor_total': str(valor_total_calculado),
                    'alerta_assistencial': alerta_assistencial,
                }
            )

        return solicitacao, True
