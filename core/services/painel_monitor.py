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
    from produtos.models import Cilindro, GasQuimico
    # Nota arquitetural: Cilindro não possui filial_id. O pátio consolida a frota do tenant.
    cil_qs = Cilindro.unscoped.filter(tenant=tenant)

    # Cheios aptos para expedição: status CHEIO_DISPONIVEL, sem bloqueio sanitário
    # e, se houver envase_atual apontando para lote de produção, o lote deve estar APROVADO
    filtro_cheios_aptos = Q(
        status='CHEIO_DISPONIVEL',
        bloqueio_sanitario=False
    ) & (
        Q(envase_atual__isnull=True) | Q(envase_atual__lote__status_qualidade='APROVADO')
    )

    # Agregação única consolidada de contadores de pátio, reteste e bloqueios sanitários
    aggr_patio = cil_qs.aggregate(
        cheios=Count('id', filter=filtro_cheios_aptos),
        vazios=Count('id', filter=Q(status='VAZIO_TRIAGEM')),
        reteste_vencido=Count('id', filter=Q(
            status__in=['CHEIO_DISPONIVEL', 'VAZIO_TRIAGEM'],
            data_proximo_reteste__lt=hoje
        )),
        bloqueios_sanitarios=Count('id', filter=Q(
            bloqueio_sanitario=True
        ) & ~Q(status='BAIXADO'))
    )

    if secoes_cfg.get('patio_demanda', True):
        # Mapeamento e normalização de gases para consolidação Pátio x Demanda (com cache do catálogo)
        todos_gases_quimicos = cache.get_or_set(
            'catalogo_gases_quimicos',
            lambda: list(GasQuimico.objects.all()),
            timeout=300
        )
        mapa_gas_lookup = {}
        for g in todos_gases_quimicos:
            nome_display = g.sigla or g.nome
            if g.sigla:
                mapa_gas_lookup[g.sigla.strip().lower()] = nome_display
            if g.nome:
                mapa_gas_lookup[g.nome.strip().lower()] = nome_display

        # Pares ordenados por tamanho decrescente para priorizar termos mais específicos
        pares_lookup = sorted(mapa_gas_lookup.items(), key=lambda x: len(x[0]), reverse=True)

        def resolver_chave_gas(nome_ou_sigla: str) -> str:
            s = (nome_ou_sigla or '').strip()
            if not s:
                return 'Outros'
            s_lower = s.lower()
            if s_lower in mapa_gas_lookup:
                return mapa_gas_lookup[s_lower]
            for k, display in pares_lookup:
                if len(k) >= 2 and (k in s_lower or k in s_lower.split()):
                    return display
            return s

        # 1. Cheios disponíveis por gás no pátio (agregação agrupada no banco)
        cheios_por_gas = {}
        if aggr_patio['cheios'] > 0:
            cil_cheios_qs = Cilindro.unscoped.filter(
                tenant=tenant
            ).filter(filtro_cheios_aptos).values('gas_dedicado__sigla', 'gas_dedicado__nome').annotate(total=Count('id'))

            for c in cil_cheios_qs:
                raw_gas = c['gas_dedicado__sigla'] or c['gas_dedicado__nome'] or 'Outros'
                chave_g = resolver_chave_gas(raw_gas)
                cheios_por_gas[chave_g] = cheios_por_gas.get(chave_g, 0) + c['total']

        # 2. Demanda por gás nos pedidos em aberto (Pendente, Em Separação)
        # com prazo de entrega hoje ou vencido (ou sem prazo definido)
        from vendas.models import ItemVenda
        itens_abertos_qs = ItemVenda.unscoped.filter(
            venda__tenant=tenant,
            venda__status__in=['Pendente', 'Em Separação']
        ).filter(
            Q(venda__prazo_entrega__lte=hoje) | Q(venda__prazo_entrega__isnull=True)
        )
        if painel.filial_id:
            itens_abertos_qs = itens_abertos_qs.filter(venda__filial_id=painel.filial_id)

        itens_abertos_qs = itens_abertos_qs.select_related('sku__gas', 'produto')

        pedidos_por_gas = {}
        for item in itens_abertos_qs:
            if item.sku and item.sku.gas:
                raw_gas = item.sku.gas.sigla or item.sku.gas.nome
            elif item.produto:
                raw_gas = item.produto.nome
            else:
                raw_gas = 'Outros'
            chave_g = resolver_chave_gas(raw_gas)
            pedidos_por_gas[chave_g] = pedidos_por_gas.get(chave_g, 0) + int(item.quantidade)

        # 3. Consolidação individual por gás
        todos_nomes_gases = sorted(set(list(cheios_por_gas.keys()) + list(pedidos_por_gas.keys())))
        lista_gases = []
        tot_cheios = 0
        tot_pedidos = 0

        for g_nome in todos_nomes_gases:
            c_qtd = cheios_por_gas.get(g_nome, 0)
            p_qtd = pedidos_por_gas.get(g_nome, 0)
            s_qtd = c_qtd - p_qtd
            falta = (s_qtd < 0)
            tot_cheios += c_qtd
            tot_pedidos += p_qtd
            lista_gases.append({
                'gas': g_nome,
                'cheios_disponiveis': c_qtd,
                'quantidade_pedida': p_qtd,
                'saldo': s_qtd,
                'em_falta': falta
            })

        tot_saldo = tot_cheios - tot_pedidos
        tem_falta_geral = any(g['em_falta'] for g in lista_gases) if lista_gases else (tot_saldo < 0)

        dados['patio_demanda'] = {
            'cheios_disponiveis': tot_cheios,
            'quantidade_pedida': tot_pedidos,
            'saldo': tot_saldo,
            'em_falta': tem_falta_geral,
            'gases': lista_gases,
        }

    if secoes_cfg.get('retornos', True):
        # Nota: O sistema registra recolhas em trânsito no ato da bipagem em campo (full-for-empty),
        # sem modelo de previsão prévia agendada de recolhas de vasilhames.
        dados['retornos'] = {
            'vazios_triagem': aggr_patio['vazios'] or 0,
        }

    if secoes_cfg.get('alertas', True):
        from produtos.models import RecallCampanha

        # Campanhas de recall abertas / em andamento
        recalls_count = RecallCampanha.unscoped.filter(
            tenant=tenant,
            status__in=['ABERTO', 'HOMOLOGADO_RT', 'EM_NOTIFICACAO']
        ).count()

        dados['alertas'] = {
            'reteste_vencido_patio': aggr_patio['reteste_vencido'] or 0,
            'bloqueios_sanitarios': aggr_patio['bloqueios_sanitarios'] or 0,
            'recalls_abertos': recalls_count
        }

    # --------------------------------------------------------------------------
    # 5. FÁBRICA / ENVASE (Somente com Módulo Envase Ativo)
    # --------------------------------------------------------------------------
    if tem_envase and secoes_cfg.get('fabrica', True):
        from produtos.models import LoteEnvase, TanqueCriogenico

        # Inspeções pendentes na rampa: cilindros em VAZIO_TRIAGEM sem inspeção aprovada recente nos últimos 7 dias
        inspecoes_pendentes = Cilindro.unscoped.filter(
            tenant=tenant,
            status='VAZIO_TRIAGEM'
        ).exclude(
            inspecoes_pre_envase__aprovado=True,
            inspecoes_pre_envase__realizado_em__gte=agora - timezone.timedelta(days=7)
        ).count()

        # Lotes de produção em quarentena aguardando liberação do CQ/RT
        lotes_quarentena = LoteEnvase.unscoped.filter(
            tenant=tenant,
            status_qualidade='QUARENTENA'
        ).count()

        # Níveis operacionais dos tanques criogênicos
        tanques_qs = TanqueCriogenico.unscoped.filter(
            tenant=tenant
        ).select_related('gas')
        if painel.filial_id:
            tanques_qs = tanques_qs.filter(filial_id=painel.filial_id)

        tanques_info = []
        for t in tanques_qs:
            cap = float(t.capacidade_kg or 0)
            saldo = float(t.saldo_atual_kg or 0)
            pct = round((saldo / cap * 100), 1) if cap > 0 else 0.0
            gas_sigla = t.gas.sigla if t.gas else "Gás"
            nome_tanque = f"{t.codigo} - {t.descricao}" if t.descricao else t.codigo
            tanques_info.append({
                'nome': nome_tanque,
                'gas': gas_sigla,
                'percentual_nivel': pct,
                'alerta_nivel_baixo': pct < 20.0
            })

        dados['fabrica'] = {
            'inspecoes_pendentes': inspecoes_pendentes,
            'lotes_quarentena': lotes_quarentena,
            'tanques': tanques_info
        }

    # Guarda no cache por 15 segundos
    cache.set(cache_key, dados, timeout=15)
    return dados

