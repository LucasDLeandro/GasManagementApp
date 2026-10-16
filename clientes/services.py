import csv
import io
import json
import calendar
import zoneinfo
from datetime import datetime, time, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from core.models import Membership
from core.tenancy import get_current_tenant
from produtos.models import Cilindro, MovimentacaoCilindro, ModeloCilindro
from clientes.models import (
    Cliente, ContratoComodato, FranquiaModeloContrato, DiaCilindro,
    FechamentoFaturaEstadia, ItemFaturaEstadia, AjusteCompetenciaEstadia, ExtravioCilindroRegistro
)

FUSO_HORARIO_PADRAO = zoneinfo.ZoneInfo('America/Sao_Paulo')



def obter_contrato_vigente_cliente(cliente, data_ref):
    """
    Retorna o ContratoComodato vigente para o cliente na data_ref informada.
    Se houver múltiplos, prioriza o que contém data_ref em [vigencia_inicio, vigencia_fim].
    Fallback para o mais recente caso nenhum cubra exatamente a data_ref.
    """
    contrato = (
        ContratoComodato.unscoped
        .filter(
            cliente=cliente,
            vigencia_inicio__lte=data_ref,
        )
        .filter(
            models.Q(vigencia_fim__isnull=True) | models.Q(vigencia_fim__gte=data_ref)
        )
        .order_by('-vigencia_inicio')
        .first()
    )
    if not contrato:
        contrato = ContratoComodato.unscoped.filter(cliente=cliente).order_by('-vigencia_inicio').first()
    return contrato


def obter_parametros_modelo_contrato(contrato, modelo):
    """
    Obtém a parametrização de franquia, carência, taxa diária e custo de reposição
    para o modelo específico dentro do contrato versionado.
    Caso não exista FranquiaModeloContrato cadastrada para o modelo, utiliza os defaults do ContratoComodato.
    """
    if not contrato:
        return {
            'franquia_isentos': 0,
            'carencia_dias': 30,
            'taxa_diaria': Decimal('3.50'),
            'valor_reposicao': Decimal('1800.00'),
            'criterio_franquia': 'FIFO',
            'dias_limite_extravio': 180,
            'contrato_versao': 'SEM_CONTRATO'
        }

    criterio = getattr(contrato, 'criterio_franquia', 'FIFO') or 'FIFO'
    limite_extravio = getattr(contrato, 'dias_limite_extravio', 180) or 180
    versao = f"CONTRATO_{contrato.id}_VIG_{contrato.vigencia_inicio.strftime('%Y%m%d')}"

    franquia_mod = FranquiaModeloContrato.unscoped.filter(contrato=contrato, modelo=modelo).first()
    if franquia_mod:
        return {
            'franquia_isentos': franquia_mod.franquia_cilindros_isentos,
            'carencia_dias': franquia_mod.dias_carencia_giro,
            'taxa_diaria': franquia_mod.taxa_diaria,
            'valor_reposicao': franquia_mod.valor_reposicao_extravio,
            'criterio_franquia': criterio,
            'dias_limite_extravio': limite_extravio,
            'contrato_versao': versao
        }

    return {
        'franquia_isentos': contrato.franquia_cilindros_isentos,
        'carencia_dias': contrato.dias_carencia_giro,
        'taxa_diaria': contrato.valor_diaria_excedente,
        'valor_reposicao': contrato.custo_reposicao_casco,
        'criterio_franquia': criterio,
        'dias_limite_extravio': limite_extravio,
        'contrato_versao': versao
    }


def reconstruir_posse_cliente_no_dia(cliente, data_ref, tenant_id=None):
    """
    Reconstrói a lista de cilindros em posse do cliente no fechamento do dia data_ref (23:59:59)
    estritamente a partir do histórico imutável de MovimentacaoCilindro no fuso America/Sao_Paulo.
    
    Regras determinísticas:
    1. A última movimentação válida até 23:59:59 de data_ref deve ser entrega ao cliente
       (ENTREGA_CLIENTE ou SAIDA_ENTREGA) e o cilindro não pode ter sido declarado EXTRAVIADO.
    2. Entrega e recolha no mesmo dia resulta em posse encerrada antes das 23:59:59 (0 dias de posse).
    3. Identifica a data da entrega que iniciou o ciclo de posse contínuo atual para cálculo de idade.
    """
    if tenant_id is None:
        tenant_id = cliente.tenant_id

    fim_dia_sp = datetime.combine(data_ref, time.max, tzinfo=FUSO_HORARIO_PADRAO)

    # Identifica cilindros que possuem movimentações com o cliente até fim_dia_sp
    cilindros_candidatos_ids = list(
        MovimentacaoCilindro.unscoped
        .filter(tenant_id=tenant_id, cliente=cliente, ocorrido_em__lte=fim_dia_sp)
        .values_list('cilindro_id', flat=True)
        .distinct()
    )

    cilindros_em_posse = []
    cilindros_processados = set()

    if cilindros_candidatos_ids:
        # Busca todas as movimentações dos candidatos até o final do dia D
        movs = (
            MovimentacaoCilindro.unscoped
            .filter(tenant_id=tenant_id, cilindro_id__in=cilindros_candidatos_ids, ocorrido_em__lte=fim_dia_sp)
            .order_by('cilindro_id', 'ocorrido_em', 'id')
            .select_related('cilindro', 'cilindro__modelo', 'cilindro__gas_dedicado')
        )

        movs_por_cilindro = {}
        for m in movs:
            movs_por_cilindro.setdefault(m.cilindro_id, []).append(m)

        for cil_id, historico in movs_por_cilindro.items():
            if not historico:
                continue
            ultima_mov = historico[-1]
            cilindros_processados.add(cil_id)

            # Posse no dia D: última movimentação é entrega ao cliente
            if ultima_mov.tipo in ['ENTREGA_CLIENTE', 'SAIDA_ENTREGA'] and ultima_mov.cliente_id == cliente.id:
                # Localiza o evento ENTREGA_CLIENTE que iniciou o intervalo contínuo de posse com este cliente
                mov_entrega_inicio = ultima_mov
                for m in reversed(historico):
                    if m.cliente_id == cliente.id and m.tipo in ['ENTREGA_CLIENTE', 'SAIDA_ENTREGA']:
                        mov_entrega_inicio = m
                    elif m.cliente_id != cliente.id or m.tipo in ['RECOLHA_CLIENTE', 'ENVIO_RETESTE', 'BAIXA', 'ENTRADA_ESTOQUE', 'EXTRAVIADO']:
                        break

                dt_entrega_sp = mov_entrega_inicio.ocorrido_em.astimezone(FUSO_HORARIO_PADRAO).date()
                idade_dias = max(0, (data_ref - dt_entrega_sp).days)

                cilindros_em_posse.append({
                    'cilindro': ultima_mov.cilindro,
                    'data_entrega': dt_entrega_sp,
                    'idade_posse_dias': idade_dias,
                    'data_referencia': data_ref,
                })

    # Compatibilidade retroativa exclusiva para testes sintéticos que criem Cilindro sem passar pelo Ledger
    cilindros_sem_ledger = (
        Cilindro.unscoped
        .filter(tenant_id=tenant_id, cliente_posse_atual=cliente, status='EM_POSSE_CLIENTE')
        .exclude(id__in=cilindros_processados)
        .select_related('modelo', 'gas_dedicado')
    )
    for cil in cilindros_sem_ledger:
        if cil.posse_desde:
            dt_entrega = cil.posse_desde.astimezone(FUSO_HORARIO_PADRAO).date()
        else:
            dt_entrega = data_ref
        idade_dias = max(0, (data_ref - dt_entrega).days)
        cilindros_em_posse.append({
            'cilindro': cil,
            'data_entrega': dt_entrega,
            'idade_posse_dias': idade_dias,
            'data_referencia': data_ref,
        })

    return cilindros_em_posse


def calcular_diarias_cliente_data(cliente, data_ref, tenant_id=None, persistir=True):
    """
    Executa o algoritmo determinístico de cobrança diária de estadia para o cliente em data_ref (Seção 3.1):
    
    1. Reconstrução da posse no dia D exclusivamente pelo Ledger no fuso America/Sao_Paulo.
    2. Elegibilidade:
       - Propriedade != DISTRIBUIDORA -> NAO_COBRAVEL_PROPRIEDADE (R$ 0,00)
       - Reserva Técnica -> ISENTO_RESERVA (R$ 0,00)
    3. Carência Individual:
       - idade = D - data_entrega_do_intervalo (dia da entrega = 0).
       - Enquanto idade < dias_carencia_giro: classificado como ISENTO_CARENCIA (R$ 0,00).
       - Regra de Ouro: Cilindros em carência NÃO consomem a franquia do modelo!
    4. Franquia por Modelo:
       - Cilindros com idade >= dias_carencia_giro são agrupados por Modelo de Cilindro.
       - Ordenação por criterio_franquia (FIFO: menor data_entrega, desempate cilindro.id ASC; LIFO: maior data_entrega).
       - Os primeiros F cilindros recebem ISENTO_FRANQUIA (R$ 0,00).
    5. Excedente:
       - Do cilindro F + 1 em diante na fila ordenada, recebe COBRAVEL com a taxa_diaria vigente em D.
    """
    if tenant_id is None:
        tenant_id = cliente.tenant_id

    contrato = obter_contrato_vigente_cliente(cliente, data_ref)
    itens_posse = reconstruir_posse_cliente_no_dia(cliente, data_ref, tenant_id=tenant_id)

    resultados_dia = []
    cilindros_para_franquia = {}

    for item in itens_posse:
        cil = item['cilindro']
        idade = item['idade_posse_dias']
        data_entrega = item['data_entrega']
        params = obter_parametros_modelo_contrato(contrato, cil.modelo)

        # 2. Elegibilidade
        if not cil.is_propriedade_distribuidora:
            resultados_dia.append({
                'tenant_id': tenant_id,
                'cliente': cliente,
                'cilindro': cil,
                'data_referencia': data_ref,
                'data_entrega': data_entrega,
                'idade_posse_dias': idade,
                'classe_cobranca': 'NAO_COBRAVEL_PROPRIEDADE',
                'valor_diaria': Decimal('0.00'),
                'contrato_versao': params['contrato_versao'],
                'algoritmo_versao': '5B.1',
            })
            continue

        if cil.is_reserva_tecnica:
            resultados_dia.append({
                'tenant_id': tenant_id,
                'cliente': cliente,
                'cilindro': cil,
                'data_referencia': data_ref,
                'data_entrega': data_entrega,
                'idade_posse_dias': idade,
                'classe_cobranca': 'ISENTO_RESERVA',
                'valor_diaria': Decimal('0.00'),
                'contrato_versao': params['contrato_versao'],
                'algoritmo_versao': '5B.1',
            })
            continue

        # 3. Carência Individual (dia da entrega = 0. Enquanto idade < carencia -> ISENTO_CARENCIA)
        carencia = params['carencia_dias']
        if idade < carencia:
            resultados_dia.append({
                'tenant_id': tenant_id,
                'cliente': cliente,
                'cilindro': cil,
                'data_referencia': data_ref,
                'data_entrega': data_entrega,
                'idade_posse_dias': idade,
                'classe_cobranca': 'ISENTO_CARENCIA',
                'valor_diaria': Decimal('0.00'),
                'contrato_versao': params['contrato_versao'],
                'algoritmo_versao': '5B.1',
            })
            continue

        # Candidato à franquia do modelo
        item['params'] = params
        cilindros_para_franquia.setdefault(cil.modelo_id, []).append(item)

    # 4 e 5. Franquia e Excedente por Modelo
    for modelo_id, candidatos in cilindros_para_franquia.items():
        if not candidatos:
            continue
        params = candidatos[0]['params']
        criterio = params['criterio_franquia']
        franquia = params['franquia_isentos']
        taxa = params['taxa_diaria']
        versao = params['contrato_versao']

        # Ordenação determinística estrita
        if criterio == 'LIFO':
            candidatos.sort(key=lambda x: (-x['data_entrega'].toordinal(), x['cilindro'].id))
        else:  # FIFO default
            candidatos.sort(key=lambda x: (x['data_entrega'].toordinal(), x['cilindro'].id))

        for idx, item in enumerate(candidatos):
            cil = item['cilindro']
            idade = item['idade_posse_dias']
            data_entrega = item['data_entrega']

            if idx < franquia:
                classe = 'ISENTO_FRANQUIA'
                valor = Decimal('0.00')
            else:
                classe = 'COBRAVEL'
                valor = Decimal(str(taxa)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            resultados_dia.append({
                'tenant_id': tenant_id,
                'cliente': cliente,
                'cilindro': cil,
                'data_referencia': data_ref,
                'data_entrega': data_entrega,
                'idade_posse_dias': idade,
                'classe_cobranca': classe,
                'valor_diaria': valor,
                'contrato_versao': versao,
                'algoritmo_versao': '5B.1',
            })

    if persistir:
        with transaction.atomic():
            cilindros_ativos_ids = [r['cilindro'].id for r in resultados_dia]
            DiaCilindro.unscoped.filter(
                tenant_id=tenant_id,
                cliente=cliente,
                data_referencia=data_ref
            ).exclude(cilindro_id__in=cilindros_ativos_ids).delete()

            for r in resultados_dia:
                DiaCilindro.unscoped.update_or_create(
                    tenant_id=tenant_id,
                    cliente=cliente,
                    cilindro=r['cilindro'],
                    data_referencia=data_ref,
                    defaults={
                        'data_entrega': r['data_entrega'],
                        'idade_posse_dias': r['idade_posse_dias'],
                        'classe_cobranca': r['classe_cobranca'],
                        'valor_diaria': r['valor_diaria'],
                        'contrato_versao': r['contrato_versao'],
                        'algoritmo_versao': r['algoritmo_versao'],
                    }
                )

    return resultados_dia


def recalcular_estadia_periodo(tenant_id, data_inicio, data_fim=None, cliente_id=None):
    """
    Recalcula as diárias de posse para todos os clientes (ou cliente específico)
    no intervalo [data_inicio, data_fim].
    Garante idempotência e suporta cálculo incremental a partir da data de qualquer nova movimentação.
    """
    if data_fim is None:
        data_fim = timezone.now().astimezone(FUSO_HORARIO_PADRAO).date()

    if data_inicio > data_fim:
        data_inicio = data_fim

    clientes_qs = Cliente.unscoped.filter(tenant_id=tenant_id)
    if cliente_id:
        clientes_qs = clientes_qs.filter(id=cliente_id)

    clientes = list(clientes_qs)
    total_dias = (data_fim - data_inicio).days + 1

    dias_gerados = 0
    with transaction.atomic():
        for d in range(total_dias):
            data_atual = data_inicio + timedelta(days=d)
            for cli in clientes:
                res = calcular_diarias_cliente_data(cli, data_atual, tenant_id=tenant_id, persistir=True)
                dias_gerados += len(res)

        # Sprint 5B.2: Detecção automática de impacto retroativo em competências já fechadas
        for cli in clientes:
            verificar_e_gerar_ajustes_competencias_fechadas(tenant_id, cli, data_inicio, data_fim)

    return {
        'tenant_id': tenant_id,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'clientes_processados': len(clientes),
        'total_registros_dia_cilindro': dias_gerados
    }



def recalcular_diarias_posse(tenant_id, data_inicio, data_fim=None, cliente_id=None):
    """Alias para recalcular_estadia_periodo conforme especificação da Sprint 5B.1."""
    return recalcular_estadia_periodo(tenant_id, data_inicio, data_fim=data_fim, cliente_id=cliente_id)


def calcular_radar_comodato_tenant(tenant=None):
    """
    Motor analítico unificado do Radar de Comodato / Estadia.
    Alimenta o Dashboard Operacional com os 4 KPIs e detalhamento de frota em cliente,
    consumindo o novo motor diário determinístico e reconciliando com DiaCilindro.
    """
    if tenant is None:
        tenant = get_current_tenant()
    tenant_id = tenant.id if hasattr(tenant, 'id') else tenant

    hoje = timezone.now().astimezone(FUSO_HORARIO_PADRAO).date()

    clientes = list(Cliente.unscoped.filter(tenant_id=tenant_id)) if tenant_id else list(Cliente.objects.all())

    faixas = {
        'dias_0_a_29': 0,
        'dias_30_a_59': 0,
        'dias_60_a_89': 0,
        'dias_90_mais': 0,
    }

    total_receita_acumulada = Decimal('0.00')
    total_risco_patrimonial = Decimal('0.00')
    itens_detalhados = []

    for cli in clientes:
        resultados_dia = calcular_diarias_cliente_data(cli, hoje, tenant_id=tenant_id, persistir=True)
        contrato = obter_contrato_vigente_cliente(cli, hoje)

        for res in resultados_dia:
            cil = res['cilindro']
            idade = res['idade_posse_dias']
            classe = res['classe_cobranca']
            valor_diaria = res['valor_diaria']
            dt_entrega = res['data_entrega']

            params = obter_parametros_modelo_contrato(contrato, cil.modelo)
            custo_casco = params['valor_reposicao']
            carencia_dias = params['carencia_dias']

            # Classificação por faixa de permanência
            if idade < 30:
                faixa = '0-29'
                faixas['dias_0_a_29'] += 1
            elif 30 <= idade <= 59:
                faixa = '30-59'
                faixas['dias_30_a_59'] += 1
            elif 60 <= idade <= 89:
                faixa = '60-89'
                faixas['dias_60_a_89'] += 1
            else:
                faixa = '90+'
                faixas['dias_90_mais'] += 1

            total_risco_patrimonial += custo_casco

            # Valor acumulado da locação/estadia
            dias_excedentes = max(0, idade - carencia_dias) if classe == 'COBRAVEL' else 0
            if classe == 'COBRAVEL':
                valor_locacao = Decimal(dias_excedentes) * Decimal(str(params['taxa_diaria']))
            else:
                valor_locacao = Decimal('0.00')

            total_receita_acumulada += valor_locacao

            gas_nome = cil.gas_dedicado.nome if cil.gas_dedicado else "N/A"
            gas_sigla = cil.gas_dedicado.sigla if cil.gas_dedicado else "N/A"

            itens_detalhados.append({
                'cilindro_id': cil.id,
                'codigo_qr': cil.codigo_qr,
                'numero_serie': cil.numero_serie_ogiva,
                'gas': gas_nome,
                'gas_sigla': gas_sigla,
                'cliente_id': cli.id,
                'cliente_nome': cli.nome,
                'cliente_cnpj': cli.cnpj,
                'data_entrega': dt_entrega.strftime('%d/%m/%Y'),
                'dias_parado': idade,
                'carencia_dias': carencia_dias,
                'dias_excedentes': dias_excedentes,
                'valor_diaria': float(params['taxa_diaria']),
                'valor_acumulado': float(valor_locacao),
                'custo_casco': float(custo_casco),
                'faixa': faixa,
                'status_risco': 'Crítico' if idade >= 90 else ('Alerta' if idade >= 30 else 'Normal'),
                'classe_cobranca': classe,
            })

    # Ordena pelo maior tempo parado (maior urgência primeiro)
    itens_detalhados.sort(key=lambda x: x['dias_parado'], reverse=True)

    sem_giro_30_mais = faixas['dias_30_a_59'] + faixas['dias_60_a_89'] + faixas['dias_90_mais']

    return {
        'total_cilindros_em_posse': len(itens_detalhados),
        'cilindros_sem_giro_30_mais': sem_giro_30_mais,
        'receita_locacao_acumulada': float(total_receita_acumulada),
        'risco_patrimonial_total': float(total_risco_patrimonial),
        'faixas': faixas,
        'itens': itens_detalhados
    }


# ==============================================================================
# SPRINT 5B.2: Fechamento de Fatura, Ajustes de Competência e Extravio
# ==============================================================================

def verificar_e_gerar_ajustes_competencias_fechadas(tenant_id, cliente, data_inicio, data_fim):
    """
    Caso uma movimentação ou recálculo atinja uma competência de fatura JÁ FECHADA
    (status FECHADA ou PAGA), a fatura fechada JAMAIS é alterada (imutabilidade estrita - Caso de Ouro #7).
    Em vez disso, calcula a diferença entre o novo total apurado de COBRAVEL e o valor
    já reconhecido (fatura fechada + ajustes anteriores) e gera um registro em AjusteCompetenciaEstadia.
    """
    if data_fim is None:
        data_fim = timezone.now().astimezone(FUSO_HORARIO_PADRAO).date()

    meses_afetados = set()
    dt = date(data_inicio.year, data_inicio.month, 1)
    dt_fim_mes = date(data_fim.year, data_fim.month, 1)
    while dt <= dt_fim_mes:
        meses_afetados.add(dt.strftime('%Y-%m'))
        if dt.month == 12:
            dt = date(dt.year + 1, 1, 1)
        else:
            dt = date(dt.year, dt.month + 1, 1)

    for comp in sorted(meses_afetados):
        fatura_fechada = FechamentoFaturaEstadia.unscoped.filter(
            tenant_id=tenant_id,
            cliente=cliente,
            competencia_ano_mes=comp,
            status_pagamento__in=['FECHADA', 'PAGA']
        ).first()

        if not fatura_fechada:
            continue

        ano, mes = map(int, comp.split('-'))
        novo_total_bruto = DiaCilindro.unscoped.filter(
            tenant_id=tenant_id,
            cliente=cliente,
            data_referencia__year=ano,
            data_referencia__month=mes,
            classe_cobranca='COBRAVEL'
        ).aggregate(tot=models.Sum('valor_diaria'))['tot'] or Decimal('0.00')

        ajustes_existentes = list(AjusteCompetenciaEstadia.unscoped.filter(
            tenant_id=tenant_id,
            fatura_origem=fatura_fechada
        ))
        soma_debitos_existentes = sum((a.valor_ajuste for a in ajustes_existentes if a.tipo_ajuste == 'DEBITO'), Decimal('0.00'))
        soma_creditos_existentes = sum((a.valor_ajuste for a in ajustes_existentes if a.tipo_ajuste == 'CREDITO'), Decimal('0.00'))
        valor_ja_reconhecido = fatura_fechada.valor_bruto_diarias + soma_debitos_existentes - soma_creditos_existentes

        delta = novo_total_bruto - valor_ja_reconhecido

        if delta != Decimal('0.00'):
            if delta < Decimal('0.00'):
                tipo = 'CREDITO'
                valor = abs(delta)
                motivo = (
                    f"Ajuste retroativo a crédito na competência {comp}: "
                    f"novo montante cobrável apurado (R$ {novo_total_bruto:.2f}) é inferior "
                    f"ao faturado/reconhecido (R$ {valor_ja_reconhecido:.2f}) decorrente de movimentação tardia."
                )
            else:
                tipo = 'DEBITO'
                valor = delta
                motivo = (
                    f"Ajuste retroativo a débito na competência {comp}: "
                    f"novo montante cobrável apurado (R$ {novo_total_bruto:.2f}) é superior "
                    f"ao faturado/reconhecido (R$ {valor_ja_reconhecido:.2f}) decorrente de movimentação tardia."
                )

            AjusteCompetenciaEstadia.objects.create(
                tenant_id=tenant_id,
                cliente=cliente,
                fatura_origem=fatura_fechada,
                competencia_afetada=comp,
                tipo_ajuste=tipo,
                valor_ajuste=valor,
                motivo=motivo,
                compensado=False
            )


def fechar_fatura_estadia_competencia(cliente, competencia_ano_mes, usuario=None, tenant_id=None, persistir=True):
    """
    Executa o fechamento formal e imutável da fatura de estadia para o cliente na competência informada (AAAA-MM).
    Conforme ADR-001 e Sprint 5B.2 / Fase 0:
    - Se persistir=False (modo prévia / dry_run): calcula e retorna a simulação sem gravar no banco de dados e sem disparar webhooks.
    - Se persistir=True: congela o snapshot imutável em FechamentoFaturaEstadia, salva itens e compensa pendências.
    """
    if tenant_id is None:
        tenant_id = cliente.tenant_id

    try:
        ano, mes = map(int, competencia_ano_mes.split('-'))
        if mes < 1 or mes > 12:
            raise ValueError
    except Exception:
        raise ValidationError(f"Formato de competência inválido: '{competencia_ano_mes}'. Use o formato AAAA-MM.")

    fatura_existente = FechamentoFaturaEstadia.unscoped.filter(
        tenant_id=tenant_id,
        cliente=cliente,
        competencia_ano_mes=competencia_ano_mes
    ).first()

    if persistir and fatura_existente and fatura_existente.status_pagamento in ['FECHADA', 'PAGA']:
        raise ValidationError(
            f"A fatura de {competencia_ano_mes} para o cliente {cliente.nome} "
            f"já foi fechada em {fatura_existente.data_fechamento.strftime('%d/%m/%Y %H:%M')} e é imutável."
        )

    ultimo_dia = calendar.monthrange(ano, mes)[1]
    data_inicio = date(ano, mes, 1)
    data_fim = date(ano, mes, ultimo_dia)

    with transaction.atomic():
        if persistir:
            # Garante que todos os dias da competência foram calculados e persistidos
            for d in range((data_fim - data_inicio).days + 1):
                dia_calc = data_inicio + timedelta(days=d)
                calcular_diarias_cliente_data(cliente, dia_calc, tenant_id=tenant_id, persistir=True)

            dias_mes = list(
                DiaCilindro.unscoped.filter(
                    tenant_id=tenant_id,
                    cliente=cliente,
                    data_referencia__gte=data_inicio,
                    data_referencia__lte=data_fim
                ).select_related('cilindro', 'cilindro__modelo').order_by('cilindro', 'data_referencia')
            )
        else:
            # Em modo prévia / dry_run (persistir=False):
            dias_existentes = list(
                DiaCilindro.unscoped.filter(
                    tenant_id=tenant_id,
                    cliente=cliente,
                    data_referencia__gte=data_inicio,
                    data_referencia__lte=data_fim
                ).select_related('cilindro', 'cilindro__modelo').order_by('cilindro', 'data_referencia')
            )
            if dias_existentes:
                dias_mes = dias_existentes
            else:
                dias_mes = []
                for d in range((data_fim - data_inicio).days + 1):
                    dia_calc = data_inicio + timedelta(days=d)
                    res_dia = calcular_diarias_cliente_data(cliente, dia_calc, tenant_id=tenant_id, persistir=False)
                    for r in res_dia:
                        dias_mes.append(DiaCilindro(
                            tenant_id=tenant_id,
                            cliente=cliente,
                            cilindro=r['cilindro'],
                            data_referencia=r['data_referencia'],
                            data_entrega=r['data_entrega'],
                            idade_posse_dias=r['idade_posse_dias'],
                            classe_cobranca=r['classe_cobranca'],
                            valor_diaria=r['valor_diaria'],
                            contrato_versao=r['contrato_versao'],
                            algoritmo_versao=r['algoritmo_versao'],
                        ))

        contrato_vigente = obter_contrato_vigente_cliente(cliente, data_fim)

        dias_por_cilindro = {}
        for d in dias_mes:
            dias_por_cilindro.setdefault(d.cilindro, []).append(d)

        itens_para_criar = []
        valor_bruto_diarias = Decimal('0.00')
        valor_desconto_carencia = Decimal('0.00')
        valor_desconto_franquia = Decimal('0.00')

        for cil, lista_dias in dias_por_cilindro.items():
            params = obter_parametros_modelo_contrato(contrato_vigente, cil.modelo)
            taxa_padrao = params['taxa_diaria']

            p_ini = min(d.data_referencia for d in lista_dias)
            p_fim = max(d.data_referencia for d in lista_dias)
            dias_posse = len(lista_dias)

            dias_carencia = sum(1 for d in lista_dias if d.classe_cobranca == 'ISENTO_CARENCIA')
            dias_franquia = sum(1 for d in lista_dias if d.classe_cobranca == 'ISENTO_FRANQUIA')
            dias_reserva = sum(1 for d in lista_dias if d.classe_cobranca == 'ISENTO_RESERVA')
            dias_cobraveis = sum(1 for d in lista_dias if d.classe_cobranca == 'COBRAVEL')

            diaria_aplicada = taxa_padrao
            subtotal_cil = Decimal('0.00')
            for d in lista_dias:
                if d.classe_cobranca == 'COBRAVEL':
                    subtotal_cil += d.valor_diaria
                    diaria_aplicada = d.valor_diaria

            valor_bruto_diarias += subtotal_cil
            valor_desconto_carencia += (Decimal(dias_carencia) * taxa_padrao)
            valor_desconto_franquia += (Decimal(dias_franquia) * taxa_padrao)

            modelo_desc = cil.modelo.descricao if cil.modelo else "Padrão"

            itens_para_criar.append({
                'cilindro': cil,
                'modelo_cilindro': modelo_desc,
                'periodo_inicio': p_ini,
                'periodo_fim': p_fim,
                'dias_posse_mes': dias_posse,
                'dias_carencia': dias_carencia,
                'dias_franquia': dias_franquia,
                'dias_reserva_tecnica': dias_reserva,
                'dias_cobraveis': dias_cobraveis,
                'diaria_aplicada': diaria_aplicada,
                'subtotal': subtotal_cil,
            })

        # Ajustes retroativos pendentes
        ajustes_pendentes = list(
            AjusteCompetenciaEstadia.unscoped.filter(
                tenant_id=tenant_id,
                cliente=cliente,
                compensado=False
            ).order_by('criado_em')
        )
        total_debitos = sum((a.valor_ajuste for a in ajustes_pendentes if a.tipo_ajuste == 'DEBITO'), Decimal('0.00'))
        total_creditos = sum((a.valor_ajuste for a in ajustes_pendentes if a.tipo_ajuste == 'CREDITO'), Decimal('0.00'))
        valor_ajustes_retroativos = total_debitos - total_creditos

        # Reposições por extravio pendentes
        extravios_pendentes = list(
            ExtravioCilindroRegistro.unscoped.filter(
                tenant_id=tenant_id,
                cliente=cliente,
                cobrado=False
            ).order_by('criado_em')
        )
        valor_reposicao_extravios = sum((e.valor_reposicao for e in extravios_pendentes), Decimal('0.00'))

        valor_liquido_total = valor_bruto_diarias + valor_reposicao_extravios + valor_ajustes_retroativos

        if not persistir:
            fatura_previa = FechamentoFaturaEstadia(
                tenant_id=tenant_id,
                cliente=cliente,
                competencia_ano_mes=competencia_ano_mes,
                data_fechamento=timezone.now(),
                valor_bruto_diarias=valor_bruto_diarias,
                valor_desconto_carencia=valor_desconto_carencia,
                valor_desconto_franquia=valor_desconto_franquia,
                valor_ajustes_retroativos=valor_ajustes_retroativos,
                valor_reposicao_extravios=valor_reposicao_extravios,
                valor_liquido_total=valor_liquido_total,
                status_pagamento='PREVIA',
                fechado_por=usuario
            )
            itens_previa = [
                ItemFaturaEstadia(
                    tenant_id=tenant_id,
                    fatura=fatura_previa,
                    cilindro=item_data['cilindro'],
                    modelo_cilindro=item_data['modelo_cilindro'],
                    periodo_inicio=item_data['periodo_inicio'],
                    periodo_fim=item_data['periodo_fim'],
                    dias_posse_mes=item_data['dias_posse_mes'],
                    dias_carencia=item_data['dias_carencia'],
                    dias_franquia=item_data['dias_franquia'],
                    dias_reserva_tecnica=item_data['dias_reserva_tecnica'],
                    dias_cobraveis=item_data['dias_cobraveis'],
                    diaria_aplicada=item_data['diaria_aplicada'],
                    subtotal=item_data['subtotal']
                )
                for item_data in itens_para_criar
            ]
            fatura_previa.itens_previa = itens_previa
            return fatura_previa

        fatura = FechamentoFaturaEstadia.objects.create(
            tenant_id=tenant_id,
            cliente=cliente,
            competencia_ano_mes=competencia_ano_mes,
            data_fechamento=timezone.now(),
            valor_bruto_diarias=valor_bruto_diarias,
            valor_desconto_carencia=valor_desconto_carencia,
            valor_desconto_franquia=valor_desconto_franquia,
            valor_ajustes_retroativos=valor_ajustes_retroativos,
            valor_reposicao_extravios=valor_reposicao_extravios,
            valor_liquido_total=valor_liquido_total,
            status_pagamento='FECHADA',
            fechado_por=usuario
        )

        for item_data in itens_para_criar:
            ItemFaturaEstadia.objects.create(
                tenant_id=tenant_id,
                fatura=fatura,
                cilindro=item_data['cilindro'],
                modelo_cilindro=item_data['modelo_cilindro'],
                periodo_inicio=item_data['periodo_inicio'],
                periodo_fim=item_data['periodo_fim'],
                dias_posse_mes=item_data['dias_posse_mes'],
                dias_carencia=item_data['dias_carencia'],
                dias_franquia=item_data['dias_franquia'],
                dias_reserva_tecnica=item_data['dias_reserva_tecnica'],
                dias_cobraveis=item_data['dias_cobraveis'],
                diaria_aplicada=item_data['diaria_aplicada'],
                subtotal=item_data['subtotal']
            )

        for a in ajustes_pendentes:
            a.compensado = True
            a.fatura_compensacao = fatura
            a.save(update_fields=['compensado', 'fatura_compensacao'])

        for e in extravios_pendentes:
            e.cobrado = True
            e.fatura_cobranca = fatura
            e.save(update_fields=['cobrado', 'fatura_cobranca'])

    # Disparo de Webhook para ERPs externos (Sprint 6)
    try:
        from core.webhooks import disparar_webhooks_tenant
        payload_webhook = {
            'evento': 'fatura.fechada',
            'fatura_id': fatura.id,
            'competencia': fatura.competencia_ano_mes,
            'cliente': {
                'id': cliente.id,
                'nome': cliente.nome,
                'cnpj': cliente.cnpj,
            },
            'valor_bruto': float(fatura.valor_bruto_diarias),
            'valor_desconto_carencia': float(fatura.valor_desconto_carencia),
            'valor_desconto_franquia': float(fatura.valor_desconto_franquia),
            'valor_ajustes_retroativos': float(fatura.valor_ajustes_retroativos),
            'valor_reposicao_extravios': float(fatura.valor_reposicao_extravios),
            'valor_liquido_total': float(fatura.valor_liquido_total),
            'status_pagamento': fatura.status_pagamento,
            'data_fechamento': fatura.data_fechamento.isoformat(),
            'total_itens': fatura.itens.count()
        }
        disparar_webhooks_tenant(tenant=cliente.tenant, evento='fatura.fechada', payload=payload_webhook)
    except Exception:
        pass

    return fatura



def declarar_cilindro_extraviado(cilindro, usuario, data_extravio=None, justificativa=""):
    """
    Ação e serviço restrito a GERENTE ou ADMIN para declarar extravio de cilindro (Caso de Ouro #9).
    Ao declarar EXTRAVIADO:
    1. O cilindro encerra imediatamente a contagem de diárias a partir de data_extravio.
    2. O status do cilindro é alterado para EXTRAVIADO no cadastro e registrado no Ledger (MovimentacaoCilindro).
    3. Gera um registro em ExtravioCilindroRegistro com base no valor_reposicao_extravio do contrato vigente.
    4. Esse valor é cobrado no próximo fechamento de fatura do cliente responsável.
    """
    tenant_id = cilindro.tenant_id

    # 1. Restrição RBAC: GERENTE ou ADMIN
    if usuario and not getattr(usuario, 'is_superuser', False):
        papel = None
        membership = Membership.objects.filter(user=usuario, tenant_id=tenant_id).first()
        if membership:
            papel = membership.papel
        if papel not in ['GERENTE', 'ADMIN']:
            raise PermissionDenied("Apenas usuários com papel GERENTE ou ADMIN podem declarar cilindros extraviados.")

    if data_extravio is None:
        data_extravio = timezone.now().astimezone(FUSO_HORARIO_PADRAO).date()

    # 2. Identifica o cliente responsável
    try:
        cilindro.refresh_from_db()
    except Exception:
        pass

    cliente = cilindro.cliente_posse_atual
    last_delivery = (
        MovimentacaoCilindro.unscoped
        .filter(cilindro=cilindro, tipo__in=['ENTREGA_CLIENTE', 'SAIDA_ENTREGA'])
        .order_by('-ocorrido_em', '-id')
        .first()
    )
    if not cliente and last_delivery and last_delivery.cliente:
        cliente = last_delivery.cliente

    if not cliente:
        raise ValidationError(
            f"Não é possível declarar extravio: o cilindro {cilindro.numero_serie_ogiva} "
            f"não possui cliente responsável associado à sua posse."
        )

    # 3. Calcula idade de posse sem giro
    if cilindro.posse_desde:
        dt_inicio_posse = cilindro.posse_desde.astimezone(FUSO_HORARIO_PADRAO).date()
    elif last_delivery:
        dt_inicio_posse = last_delivery.ocorrido_em.astimezone(FUSO_HORARIO_PADRAO).date()
    else:
        dt_inicio_posse = data_extravio
    dias_sem_giro = max(0, (data_extravio - dt_inicio_posse).days)

    # 4. Obtém valor de reposição do contrato
    contrato = obter_contrato_vigente_cliente(cliente, data_extravio)
    params = obter_parametros_modelo_contrato(contrato, cilindro.modelo)
    valor_reposicao = params['valor_reposicao']

    with transaction.atomic():
        # 5. Atualiza status no Cilindro e no Ledger
        status_anterior = cilindro.status
        cilindro.status = 'EXTRAVIADO'
        cilindro.cliente_posse_atual = None
        cilindro.posse_desde = None
        cilindro.save(update_fields=['status', 'cliente_posse_atual', 'posse_desde'])

        MovimentacaoCilindro.objects.create(
            tenant_id=tenant_id,
            cilindro=cilindro,
            tipo='EXTRAVIADO',
            status_anterior=status_anterior,
            status_novo='EXTRAVIADO',
            cliente=cliente,
            ocorrido_em=datetime.combine(data_extravio, time.min, tzinfo=FUSO_HORARIO_PADRAO),
            registrado_por=usuario,
            observacao=justificativa or f"Extravio declarado por {usuario.username if usuario else 'Sistema'}."
        )

        registro = ExtravioCilindroRegistro.objects.create(
            tenant_id=tenant_id,
            cilindro=cilindro,
            cliente=cliente,
            data_extravio=data_extravio,
            dias_em_posse_sem_giro=dias_sem_giro,
            valor_reposicao=valor_reposicao,
            justificativa=justificativa or "Extravio declarado formalmente.",
            declarado_por=usuario,
            cobrado=False
        )

        # 6. Remove imediatamente diárias geradas em ou após data_extravio
        DiaCilindro.unscoped.filter(
            tenant_id=tenant_id,
            cilindro=cilindro,
            data_referencia__gte=data_extravio
        ).delete()

    return registro


def identificar_cilindros_limite_extravio(tenant_id=None, cliente=None, data_referencia=None):
    """
    Identifica cilindros em posse do cliente sem movimentação há mais de dias_limite_extravio
    (default 180 dias), gerando alertas para o painel operacional (Caso de Ouro #9).
    """
    if tenant_id is None and cliente:
        tenant_id = cliente.tenant_id

    hoje = data_referencia or timezone.now().astimezone(FUSO_HORARIO_PADRAO).date()

    clientes_qs = Cliente.unscoped.filter(tenant_id=tenant_id) if tenant_id else Cliente.objects.all()
    if cliente:
        clientes_qs = clientes_qs.filter(id=cliente.id)

    alertas = []
    for cli in clientes_qs:
        contrato = obter_contrato_vigente_cliente(cli, hoje)

        cilindros = list(
            Cilindro.unscoped.filter(
                cliente_posse_atual=cli,
                status='EM_POSSE_CLIENTE'
            ).select_related('modelo', 'gas_dedicado')
        )

        for cil in cilindros:
            params = obter_parametros_modelo_contrato(contrato, cil.modelo)
            limite = params['dias_limite_extravio']

            if cil.posse_desde:
                dt_entrega = cil.posse_desde.astimezone(FUSO_HORARIO_PADRAO).date()
            else:
                dt_entrega = hoje
            dias_em_posse = max(0, (hoje - dt_entrega).days)

            if dias_em_posse >= limite:
                dias_excedentes = dias_em_posse - limite
                alertas.append({
                    'cilindro_id': cil.id,
                    'numero_serie': cil.numero_serie_ogiva,
                    'codigo_qr': cil.codigo_qr,
                    'cliente_id': cli.id,
                    'cliente_nome': cli.nome,
                    'cliente_cnpj': cli.cnpj,
                    'data_entrega': dt_entrega.strftime('%d/%m/%Y'),
                    'dias_em_posse': dias_em_posse,
                    'dias_limite_extravio': limite,
                    'dias_excedentes_extravio': dias_excedentes,
                    'valor_reposicao': float(params['valor_reposicao']),
                    'modelo_descricao': cil.modelo.descricao if cil.modelo else "N/A",
                    'gas': cil.gas_dedicado.nome if cil.gas_dedicado else "N/A",
                })

    alertas.sort(key=lambda x: x['dias_em_posse'], reverse=True)
    return alertas


def gerar_espelho_medicao_csv(fatura):
    """
    Gera o espelho de medição em formato CSV para conferência e exportação.
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    writer.writerow(['ESPELHO DE MEDIÇÃO DE ESTADIA / LOCAÇÃO DE CILINDROS EXCEDENTES'])
    writer.writerow(['Tenant', str(fatura.tenant)])
    writer.writerow(['Cliente', fatura.cliente.nome])
    writer.writerow(['CNPJ', fatura.cliente.cnpj])
    writer.writerow(['Competência', fatura.competencia_ano_mes])
    writer.writerow(['Data de Fechamento', fatura.data_fechamento.strftime('%d/%m/%Y %H:%M:%S')])
    writer.writerow(['Status Pagamento', fatura.status_pagamento])
    writer.writerow([])

    writer.writerow(['ITENS DA MEDIÇÃO (DIÁRIAS DE CILINDROS)'])
    writer.writerow([
        'Cilindro (Série)', 'Código QR', 'Modelo', 'Início Período', 'Fim Período',
        'Dias Posse Mês', 'Dias Carência', 'Dias Franquia', 'Dias Reserva',
        'Dias Cobráveis', 'Diária Aplicada (R$)', 'Subtotal (R$)'
    ])

    itens = list(fatura.itens.select_related('cilindro', 'cilindro__modelo').order_by('cilindro__numero_serie_ogiva'))
    for it in itens:
        writer.writerow([
            it.cilindro.numero_serie_ogiva,
            it.cilindro.codigo_qr,
            it.modelo_cilindro,
            it.periodo_inicio.strftime('%d/%m/%Y'),
            it.periodo_fim.strftime('%d/%m/%Y'),
            it.dias_posse_mes,
            it.dias_carencia,
            it.dias_franquia,
            it.dias_reserva_tecnica,
            it.dias_cobraveis,
            f"{it.diaria_aplicada:.2f}",
            f"{it.subtotal:.2f}"
        ])
    writer.writerow([])

    ajustes = list(fatura.ajustes_compensados.all().order_by('criado_em'))
    if ajustes:
        writer.writerow(['AJUSTES RETROATIVOS COMPENSADOS'])
        writer.writerow(['ID', 'Tipo', 'Competência Afetada', 'Valor (R$)', 'Motivo'])
        for a in ajustes:
            writer.writerow([
                a.id,
                a.tipo_ajuste,
                a.competencia_afetada,
                f"{a.valor_ajuste:.2f}",
                a.motivo
            ])
        writer.writerow([])

    extravios = list(fatura.registros_extravio.select_related('cilindro').order_by('criado_em'))
    if extravios:
        writer.writerow(['REPOSIÇÕES PATRIMONIAIS POR EXTRAVIO'])
        writer.writerow(['Cilindro', 'Data Extravio', 'Dias Sem Giro', 'Valor Reposição (R$)', 'Justificativa'])
        for e in extravios:
            writer.writerow([
                e.cilindro.numero_serie_ogiva,
                e.data_extravio.strftime('%d/%m/%Y'),
                e.dias_em_posse_sem_giro,
                f"{e.valor_reposicao:.2f}",
                e.justificativa
            ])
        writer.writerow([])

    writer.writerow(['RESUMO FINANCEIRO'])
    writer.writerow(['Valor Bruto das Diárias', f"R$ {fatura.valor_bruto_diarias:.2f}"])
    writer.writerow(['Desconto por Carência', f"R$ {fatura.valor_desconto_carencia:.2f}"])
    writer.writerow(['Desconto por Franquia', f"R$ {fatura.valor_desconto_franquia:.2f}"])
    writer.writerow(['Ajustes Retroativos (Líquido)', f"R$ {fatura.valor_ajustes_retroativos:.2f}"])
    writer.writerow(['Reposições por Extravio', f"R$ {fatura.valor_reposicao_extravios:.2f}"])
    writer.writerow(['VALOR LÍQUIDO TOTAL', f"R$ {fatura.valor_liquido_total:.2f}"])

    return output.getvalue()


def gerar_espelho_medicao_pdf(fatura):
    """
    Gera o espelho de medição formal em formato PDF utilizando ReportLab.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError as e:
        raise RuntimeError("A biblioteca 'reportlab' é necessária para gerar relatórios em PDF. Instale com pip install reportlab.") from e

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=15,
        leading=19,
        textColor=colors.HexColor('#1E293B'),
        alignment=1,
        spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569'),
        alignment=1,
        spaceAfter=12
    )
    section_title = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#0F172A'),
        spaceBefore=10,
        spaceAfter=5
    )
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#334155')
    )
    header_cell_style = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontSize=8,
        leading=11,
        textColor=colors.white,
        fontName='Helvetica-Bold'
    )
    footer_style = ParagraphStyle(
        'FooterNotice',
        parent=styles['Normal'],
        fontSize=7,
        leading=10,
        textColor=colors.HexColor('#64748B'),
        alignment=1,
        spaceBefore=15
    )

    story = []

    tenant_nome = fatura.tenant.nome_fantasia or fatura.tenant.razao_social if fatura.tenant else "Distribuidora de Gases"
    story.append(Paragraph(f"<b>{tenant_nome}</b>", title_style))
    story.append(Paragraph("Espelho de Medição de Estadia / Locação de Cilindros Excedentes", subtitle_style))

    meta_data = [
        [
            Paragraph("<b>Cliente:</b> " + fatura.cliente.nome, body_style),
            Paragraph("<b>Competência:</b> " + fatura.competencia_ano_mes, body_style)
        ],
        [
            Paragraph("<b>CNPJ:</b> " + fatura.cliente.cnpj, body_style),
            Paragraph("<b>Data Fechamento:</b> " + fatura.data_fechamento.strftime('%d/%m/%Y %H:%M'), body_style)
        ],
        [
            Paragraph("<b>Status:</b> " + fatura.status_pagamento, body_style),
            Paragraph("<b>Fechado por:</b> " + (fatura.fechado_por.username if fatura.fechado_por else "Sistema"), body_style)
        ]
    ]
    t_meta = Table(meta_data, colWidths=[9.0 * cm, 9.0 * cm])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Detalhamento por Cilindro (Medição Mensal)", section_title))
    itens_headers = [
        Paragraph("Cilindro", header_cell_style),
        Paragraph("Modelo", header_cell_style),
        Paragraph("Período", header_cell_style),
        Paragraph("Dias Posse", header_cell_style),
        Paragraph("Isentos", header_cell_style),
        Paragraph("Cobráveis", header_cell_style),
        Paragraph("Diária", header_cell_style),
        Paragraph("Subtotal", header_cell_style),
    ]
    itens_table_data = [itens_headers]

    itens = list(fatura.itens.select_related('cilindro').order_by('cilindro__numero_serie_ogiva'))
    for it in itens:
        dias_isentos = it.dias_carencia + it.dias_franquia + it.dias_reserva_tecnica
        periodo_str = f"{it.periodo_inicio.strftime('%d/%m')} - {it.periodo_fim.strftime('%d/%m')}"
        itens_table_data.append([
            Paragraph(it.cilindro.numero_serie_ogiva, body_style),
            Paragraph(it.modelo_cilindro[:15], body_style),
            Paragraph(periodo_str, body_style),
            Paragraph(str(it.dias_posse_mes), body_style),
            Paragraph(str(dias_isentos), body_style),
            Paragraph(str(it.dias_cobraveis), body_style),
            Paragraph(f"R$ {it.diaria_aplicada:.2f}", body_style),
            Paragraph(f"R$ {it.subtotal:.2f}", body_style),
        ])

    t_itens = Table(itens_table_data, colWidths=[2.8 * cm, 2.6 * cm, 2.4 * cm, 1.8 * cm, 1.8 * cm, 2.0 * cm, 2.2 * cm, 2.4 * cm])
    t_itens.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_itens)
    story.append(Spacer(1, 8))

    ajustes = list(fatura.ajustes_compensados.all())
    if ajustes:
        story.append(Paragraph("Ajustes Retroativos Compensados", section_title))
        ajustes_table_data = [[
            Paragraph("Tipo", header_cell_style),
            Paragraph("Competência", header_cell_style),
            Paragraph("Valor", header_cell_style),
            Paragraph("Motivo", header_cell_style)
        ]]
        for a in ajustes:
            ajustes_table_data.append([
                Paragraph(a.tipo_ajuste, body_style),
                Paragraph(a.competencia_afetada, body_style),
                Paragraph(f"R$ {a.valor_ajuste:.2f}", body_style),
                Paragraph(a.motivo[:60], body_style),
            ])
        t_ajustes = Table(ajustes_table_data, colWidths=[3.0 * cm, 3.0 * cm, 3.0 * cm, 9.0 * cm])
        t_ajustes.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(t_ajustes)
        story.append(Spacer(1, 8))

    extravios = list(fatura.registros_extravio.select_related('cilindro').all())
    if extravios:
        story.append(Paragraph("Reposição Patrimonial por Extravio", section_title))
        extravios_table_data = [[
            Paragraph("Cilindro", header_cell_style),
            Paragraph("Data Extravio", header_cell_style),
            Paragraph("Dias Retido", header_cell_style),
            Paragraph("Valor Reposição", header_cell_style)
        ]]
        for e in extravios:
            extravios_table_data.append([
                Paragraph(e.cilindro.numero_serie_ogiva, body_style),
                Paragraph(e.data_extravio.strftime('%d/%m/%Y'), body_style),
                Paragraph(str(e.dias_em_posse_sem_giro), body_style),
                Paragraph(f"R$ {e.valor_reposicao:.2f}", body_style),
            ])
        t_extravios = Table(extravios_table_data, colWidths=[4.5 * cm, 4.5 * cm, 4.5 * cm, 4.5 * cm])
        t_extravios.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(t_extravios)
        story.append(Spacer(1, 8))

    story.append(Paragraph("Resumo Financeiro da Fatura", section_title))
    totais_data = [
        [Paragraph("Valor Bruto das Diárias:", body_style), Paragraph(f"R$ {fatura.valor_bruto_diarias:.2f}", body_style)],
        [Paragraph("Descontos por Carência Individual:", body_style), Paragraph(f"- R$ {fatura.valor_desconto_carencia:.2f}", body_style)],
        [Paragraph("Descontos por Franquia Contratual:", body_style), Paragraph(f"- R$ {fatura.valor_desconto_franquia:.2f}", body_style)],
        [Paragraph("Ajustes Retroativos (Líquido):", body_style), Paragraph(f"R$ {fatura.valor_ajustes_retroativos:.2f}", body_style)],
        [Paragraph("Reposições por Extravio:", body_style), Paragraph(f"+ R$ {fatura.valor_reposicao_extravios:.2f}", body_style)],
        [
            Paragraph("<b>VALOR LÍQUIDO TOTAL:</b>", ParagraphStyle('BoldL', parent=body_style, fontName='Helvetica-Bold', fontSize=9)),
            Paragraph(f"<b>R$ {fatura.valor_liquido_total:.2f}</b>", ParagraphStyle('BoldR', parent=body_style, fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0F172A')))
        ]
    ]
    t_totais = Table(totais_data, colWidths=[12.0 * cm, 6.0 * cm])
    t_totais.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -2), colors.HexColor('#F8FAFC')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E2E8F0')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#94A3B8')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_totais)

    story.append(Spacer(1, 15))
    story.append(Paragraph(
        "Documento emitido para fins de conferência operacional e conciliação financeira de estadia de cilindros excedentes. "
        "Em conformidade com RDC nº 658/2022, IN nº 129/2022, RDC nº 870/2024 e RDC nº 887/2024 (ANVISA) e Resolução CFF nº 731/2022.",
        footer_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def gerar_exportacao_canonica_erp(tenant_id, competencia_ano_mes, formato='json'):
    """
    Exportação Canônica estável para integração com ERPs e operação em modo sombra (Sprint 5B.2).
    Suporta formato JSON e CSV.
    """
    faturas = list(
        FechamentoFaturaEstadia.unscoped.filter(
            tenant_id=tenant_id,
            competencia_ano_mes=competencia_ano_mes
        ).select_related('cliente').prefetch_related('itens', 'itens__cilindro', 'ajustes_compensados', 'registros_extravio')
    )

    if formato == 'json':
        total_faturado = sum((f.valor_liquido_total for f in faturas), Decimal('0.00'))
        dados_faturas = []

        for f in faturas:
            itens_lista = []
            for it in f.itens.all():
                itens_lista.append({
                    'cilindro_id': it.cilindro_id,
                    'cilindro_codigo_qr': it.cilindro.codigo_qr,
                    'cilindro_numero_serie': it.cilindro.numero_serie_ogiva,
                    'modelo': it.modelo_cilindro,
                    'periodo_inicio': it.periodo_inicio.isoformat(),
                    'periodo_fim': it.periodo_fim.isoformat(),
                    'dias_posse_mes': it.dias_posse_mes,
                    'dias_carencia': it.dias_carencia,
                    'dias_franquia': it.dias_franquia,
                    'dias_reserva_tecnica': it.dias_reserva_tecnica,
                    'dias_cobraveis': it.dias_cobraveis,
                    'diaria_aplicada': float(it.diaria_aplicada),
                    'subtotal': float(it.subtotal)
                })

            ajustes_lista = []
            for a in f.ajustes_compensados.all():
                ajustes_lista.append({
                    'ajuste_id': a.id,
                    'competencia_afetada': a.competencia_afetada,
                    'tipo_ajuste': a.tipo_ajuste,
                    'valor_ajuste': float(a.valor_ajuste),
                    'motivo': a.motivo
                })

            extravios_lista = []
            for e in f.registros_extravio.all():
                extravios_lista.append({
                    'extravio_id': e.id,
                    'cilindro_numero_serie': e.cilindro.numero_serie_ogiva,
                    'data_extravio': e.data_extravio.isoformat(),
                    'dias_sem_giro': e.dias_em_posse_sem_giro,
                    'valor_reposicao': float(e.valor_reposicao),
                    'justificativa': e.justificativa
                })

            dados_faturas.append({
                'fatura_id': f.id,
                'cliente_id': f.cliente.id,
                'cliente_cnpj': f.cliente.cnpj,
                'cliente_nome': f.cliente.nome,
                'competencia': f.competencia_ano_mes,
                'data_fechamento': f.data_fechamento.isoformat(),
                'status_pagamento': f.status_pagamento,
                'valor_bruto_diarias': float(f.valor_bruto_diarias),
                'valor_desconto_carencia': float(f.valor_desconto_carencia),
                'valor_desconto_franquia': float(f.valor_desconto_franquia),
                'valor_ajustes_retroativos': float(f.valor_ajustes_retroativos),
                'valor_reposicao_extravios': float(f.valor_reposicao_extravios),
                'valor_liquido_total': float(f.valor_liquido_total),
                'itens': itens_lista,
                'ajustes_compensados': ajustes_lista,
                'extravios_cobrados': extravios_lista
            })

        return {
            'versao_schema': '1.0',
            'gerado_em': timezone.now().isoformat(),
            'tenant_id': tenant_id,
            'competencia': competencia_ano_mes,
            'total_faturas': len(faturas),
            'valor_total_faturado': float(total_faturado),
            'faturas': dados_faturas
        }

    elif formato == 'csv':
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow([
            'FATURA_ID', 'CLIENTE_CNPJ', 'CLIENTE_NOME', 'COMPETENCIA', 'STATUS',
            'VALOR_BRUTO', 'DESCONTO_CARENCIA', 'DESCONTO_FRANQUIA', 'AJUSTES_RETROATIVOS',
            'REPOSICAO_EXTRAVIOS', 'VALOR_LIQUIDO', 'CILINDRO_SERIE', 'MODELO',
            'DIAS_POSSE', 'DIAS_COBRAVEIS', 'DIARIA', 'SUBTOTAL'
        ])
        for f in faturas:
            for it in f.itens.all():
                writer.writerow([
                    f.id,
                    f.cliente.cnpj,
                    f.cliente.nome,
                    f.competencia_ano_mes,
                    f.status_pagamento,
                    f"{f.valor_bruto_diarias:.2f}",
                    f"{f.valor_desconto_carencia:.2f}",
                    f"{f.valor_desconto_franquia:.2f}",
                    f"{f.valor_ajustes_retroativos:.2f}",
                    f"{f.valor_reposicao_extravios:.2f}",
                    f"{f.valor_liquido_total:.2f}",
                    it.cilindro.numero_serie_ogiva,
                    it.modelo_cilindro,
                    it.dias_posse_mes,
                    it.dias_cobraveis,
                    f"{it.diaria_aplicada:.2f}",
                    f"{it.subtotal:.2f}"
                ])
        return output.getvalue()
    else:
        raise ValueError(f"Formato de exportação não suportado: {formato}")

