import secrets
from decimal import Decimal
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Count, Q, Sum

from core.modulos import is_modulo_ativo


def gerar_token_painel() -> str:
    """Gera um token seguro de 32 bytes url-safe para acesso anônimo ao monitor."""
    return secrets.token_urlsafe(32)


def regenerar_token_painel(painel) -> str:
    """Gera um novo token para o painel, invalidando o cache e o token anterior."""
    cache.delete(f"cache_monitor_dados_{painel.token}")
    novo_token = gerar_token_painel()
    painel.token = novo_token
    painel.save(update_fields=['token'])
    return novo_token


def revogar_painel(painel) -> bool:
    """Desativa o painel, impedindo qualquer acesso futuro."""
    cache.delete(f"cache_monitor_dados_{painel.token}")
    painel.ativo = False
    painel.save(update_fields=['ativo'])
    return True


def montar_dados_painel(painel) -> dict:
    """
    Monta a estrutura de dados em tempo real para o monitor de TV.
    Garante:
    - Desempenho otimizado (sem N+1, <= 15 queries)
    - Cache de 15 segundos por token
    - Isolamento estrito de tenant (consultas unscoped filtradas por painel.tenant)
    - Respeito aos módulos ativos (envase, distribuicao)
    - Ausência total de dados financeiros e de contato (LGPD)
    - Mascaramento de cliente caso mostrar_nomes_clientes=False
    """
    cache_key = f"cache_monitor_dados_{painel.token}"
    cached_data = cache.get(cache_key)
    if cached_data is not None:
        return cached_data

    tenant = painel.tenant
    agora = timezone.now()
    hoje = agora.date()

    # Módulos ativos
    tem_distribuicao = is_modulo_ativo(tenant, 'distribuicao')
    tem_envase = is_modulo_ativo(tenant, 'envase')

    secoes_cfg = painel.secoes or {}

    dados = {
        'nome': painel.nome,
        'empresa': tenant.nome_fantasia or tenant.razao_social,
        'gerado_em': agora.isoformat(),
        'tempo_alerta_min': painel.tempo_alerta_min,
        'tempo_critico_min': painel.tempo_critico_min,
    }

    # --------------------------------------------------------------------------
    # 1. ESTEIRA DE PEDIDOS (Módulo Distribuição)
    # --------------------------------------------------------------------------
    if tem_distribuicao and secoes_cfg.get('esteira', True):
        from vendas.models import Venda, HistoricoStatusVenda

        # Query 1: Pedidos em aberto na esteira
        vendas_qs = Venda.unscoped.filter(
            tenant=tenant,
            status__in=['Pendente', 'BLOQUEADO_FINANCEIRO', 'Em Separação', 'Faturada', 'Em Rota']
        ).select_related('cliente')
        if painel.filial_id:
            vendas_qs = vendas_qs.filter(filial_id=painel.filial_id)

        vendas = list(vendas_qs)
        venda_ids = [v.id for v in vendas]

        # Query 2: Mapa de histórico de status em lote (evita N+1 de desde_quando_no_status)
        mapa_historico = {}
        if venda_ids:
            hist_qs = HistoricoStatusVenda.unscoped.filter(
                venda_id__in=venda_ids
            ).order_by('alterado_em')
            for h in hist_qs:
                mapa_historico[(h.venda_id, h.status_novo)] = h.alterado_em

        # Query 3: Itens dos pedidos em aberto
        from vendas.models import ItemVenda
        itens_map = {}
        if venda_ids:
            itens_qs = ItemVenda.unscoped.filter(
                venda_id__in=venda_ids
            ).select_related('sku__gas', 'produto')
            for item in itens_qs:
                gas_nome = ''
                if item.sku and item.sku.gas:
                    gas_nome = item.sku.gas.sigla or item.sku.gas.nome
                elif item.produto:
                    gas_nome = item.produto.nome
                else:
                    gas_nome = "Cilindro"

                itens_map.setdefault(item.venda_id, []).append({
                    'gas': gas_nome,
                    'quantidade': float(item.quantidade)
                })

        a_separar = []
        em_separacao = []
        faturada = []
        em_rota = []

        for v in vendas:
            # Identificação do cliente com mascaramento se configurado
            if painel.mostrar_nomes_clientes and v.cliente:
                cliente_label = v.cliente.nome_fantasia or v.cliente.nome
            elif v.cliente:
                bairro = v.cliente.bairro or ''
                cidade = v.cliente.cidade or ''
                partes = [p for p in [bairro, cidade] if p]
                cliente_label = " - ".join(partes) if partes else "Cliente"
            else:
                cliente_label = "Cliente"

            # Tempo na etapa
            dt_entrada = mapa_historico.get((v.id, v.status)) or v.data_atualizacao or v.data_venda
            minutos = int((agora - dt_entrada).total_seconds() // 60) if dt_entrada else 0
            if minutos < 0:
                minutos = 0

            # Nível de alerta
            if minutos >= painel.tempo_critico_min:
                nivel = 'critico'
            elif minutos >= painel.tempo_alerta_min:
                nivel = 'alerta'
            else:
                nivel = 'normal'

            card = {
                'id': v.id,
                'numero': v.documento_fiscal_ref or f"#{v.id}",
                'cliente': cliente_label,
                'bloqueado': (v.status == 'BLOQUEADO_FINANCEIRO'),
                'minutos_na_etapa': minutos,
                'nivel_alerta': nivel,
                'itens': itens_map.get(v.id, [])
            }

            if v.status in ('Pendente', 'BLOQUEADO_FINANCEIRO'):
                a_separar.append(card)
            elif v.status == 'Em Separação':
                em_separacao.append(card)
            elif v.status == 'Faturada':
                faturada.append(card)
            elif v.status == 'Em Rota':
                em_rota.append(card)

        # Query 4: Total de entregas concluídas hoje
        concluidos_hoje_qs = Venda.unscoped.filter(
            tenant=tenant,
            status='Entregue',
            data_atualizacao__date=hoje
        )
        if painel.filial_id:
            concluidos_hoje_qs = concluidos_hoje_qs.filter(filial_id=painel.filial_id)
        concluidos_hoje = concluidos_hoje_qs.count()

        dados['esteira'] = {
            'a_separar': a_separar,
            'em_separacao': em_separacao,
            'faturada': faturada,
            'em_rota': em_rota,
            'concluidos_hoje': concluidos_hoje,
        }

    # --------------------------------------------------------------------------
    # 2. PÁTIO × DEMANDA & 3. RETORNOS & 4. ALERTAS
    # --------------------------------------------------------------------------
    from produtos.models import Cilindro
    cil_qs = Cilindro.unscoped.filter(tenant=tenant)
    if painel.filial_id:
        cil_qs = cil_qs.filter(filial_id=painel.filial_id)

    # Query 5: Agregação rápida de contadores de pátio e reteste
    aggr_patio = cil_qs.aggregate(
        cheios=Count('id', filter=Q(status='CHEIO_DISPONIVEL')),
        vazios=Count('id', filter=Q(status='VAZIO_TRIAGEM')),
        reteste_vencido=Count('id', filter=Q(
            status__in=['CHEIO_DISPONIVEL', 'VAZIO_TRIAGEM'],
            data_proximo_reteste__lt=hoje
        ))
    )

    if secoes_cfg.get('patio_demanda', True):
        # Quantidade total pedida em aberto
        from vendas.models import ItemVenda
        itens_abertos = ItemVenda.unscoped.filter(
            venda__tenant=tenant,
            venda__status__in=['Pendente', 'Em Separação']
        )
        if painel.filial_id:
            itens_abertos = itens_abertos.filter(venda__filial_id=painel.filial_id)
        total_pedido = itens_abertos.aggregate(total=Sum('quantidade'))['total'] or 0

        cheios = aggr_patio['cheios'] or 0
        saldo = cheios - int(total_pedido)

        dados['patio_demanda'] = {
            'cheios_disponiveis': cheios,
            'quantidade_pedida': int(total_pedido),
            'saldo': saldo,
            'em_falta': saldo < 0
        }

    if secoes_cfg.get('retornos', True):
        recolhas_hoje = 0
        try:
            from logistica.models import Entrega
            recolhas_qs = Entrega.unscoped.filter(
                tenant=tenant,
                status__in=['Agendada', 'Em Rota'],
                data_criacao__date=hoje
            )
            if painel.filial_id:
                recolhas_qs = recolhas_qs.filter(filial_id=painel.filial_id)
            recolhas_hoje = recolhas_qs.count()
        except Exception:
            pass

        dados['retornos'] = {
            'vazios_triagem': aggr_patio['vazios'] or 0,
            'recolhas_previstas_hoje': recolhas_hoje
        }

    if secoes_cfg.get('alertas', True):
        bloqueios_count = 0
        recalls_count = 0
        try:
            from produtos.models import AuditoriaBloqueioSanitario, RecallCampanha
            bloqueios_count = AuditoriaBloqueioSanitario.unscoped.filter(
                tenant=tenant, ativo=True
            ).count()
            recalls_count = RecallCampanha.unscoped.filter(
                tenant=tenant, status__in=['INICIADA', 'EM_ANDAMENTO']
            ).count()
        except Exception:
            pass

        dados['alertas'] = {
            'reteste_vencido_patio': aggr_patio['reteste_vencido'] or 0,
            'bloqueios_sanitarios': bloqueios_count,
            'recalls_abertos': recalls_count
        }

    # --------------------------------------------------------------------------
    # 5. FÁBRICA / ENVASE (Somente com Módulo Envase Ativo)
    # --------------------------------------------------------------------------
    if tem_envase and secoes_cfg.get('fabrica', True):
        inspecoes_pendentes = 0
        lotes_quarentena = 0
        tanques_info = []

        try:
            from produtos.models import LoteEnvase, InspecaoPreEnvase, TanqueCriogenico
            inspecoes_pendentes = InspecaoPreEnvase.unscoped.filter(
                tenant=tenant, conforme=False
            ).count()
            lotes_quarentena = LoteEnvase.unscoped.filter(
                tenant=tenant, status='QUARENTENA'
            ).count()

            tanques_qs = TanqueCriogenico.unscoped.filter(
                tenant=tenant
            ).select_related('gas')
            if painel.filial_id:
                tanques_qs = tanques_qs.filter(filial_id=painel.filial_id)

            for t in tanques_qs:
                cap = float(t.capacidade_kg or 0)
                saldo = float(t.saldo_atual_kg or 0)
                pct = round((saldo / cap * 100), 1) if cap > 0 else 0.0
                gas_sigla = t.gas.sigla if t.gas else "Gás"
                tanques_info.append({
                    'nome': t.descricao,
                    'gas': gas_sigla,
                    'percentual_nivel': pct,
                    'alerta_nivel_baixo': pct < 20.0
                })
        except Exception:
            pass

        dados['fabrica'] = {
            'inspecoes_pendentes': inspecoes_pendentes,
            'lotes_quarentena': lotes_quarentena,
            'tanques': tanques_info
        }

    # Guarda no cache por 15 segundos
    cache.set(cache_key, dados, timeout=15)
    return dados
