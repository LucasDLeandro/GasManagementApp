"""
Serviço Canônico de Depreciação Patrimonial, Revisão de Vida Útil e Baixa Contábil (Sprint 10B - Tarefas 1, 3, 4, 5).
Controla o ledger DepreciacaoMensal, baixas patrimoniais apuradas em conta 8.2 e capitalização de reteste.
"""

import datetime
from decimal import Decimal
from typing import Optional, Union

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    DepreciacaoMensal,
    RevisaoVidaUtil,
    LancamentoContabil,
    PlanoContas,
    CentroCusto,
)
from financeiro.services.razao import lancar
from produtos.models import ClasseAtivo, AtivoImobilizado, LoteAquisicaoCilindros, Cilindro


def normalizar_periodo_data(periodo: Union[str, datetime.date, datetime.datetime]) -> datetime.date:
    """Normaliza período para o primeiro dia do mês correspondente."""
    if isinstance(periodo, (datetime.date, datetime.datetime)):
        return datetime.date(periodo.year, periodo.month, 1)
    if isinstance(periodo, str):
        partes = periodo.strip().split('-')
        if len(partes) >= 2:
            return datetime.date(int(partes[0]), int(partes[1]), 1)
    raise ValidationError(f"Período inválido: {periodo}. Use YYYY-MM ou objeto date.")


def obter_mes_anterior(periodo_mes: datetime.date) -> datetime.date:
    """Retorna o primeiro dia do mês imediatamente anterior."""
    primeiro_dia = periodo_mes.replace(day=1)
    ultimo_dia_mes_ant = primeiro_dia - datetime.timedelta(days=1)
    return ultimo_dia_mes_ant.replace(day=1)


def obter_contas_classe(tenant, classe: ClasseAtivo) -> tuple[PlanoContas, PlanoContas]:
    """
    Retorna (conta_despesa_depreciacao, conta_depreciacao_acumulada) da classe,
    utilizando as contas padrão do plano caso os vínculos estejam pendentes.
    """
    despesa = classe.conta_despesa_depreciacao
    acumulada = classe.conta_depreciacao_acumulada

    if not despesa:
        # Fallback por tipo de ativo no plano de contas padrão
        codigo_desp = '6.1' if classe.tipo == 'CILINDRO' else ('6.2' if classe.tipo == 'VEICULO' else '6.3')
        despesa = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural=codigo_desp).first()

    if not acumulada:
        codigo_acum = '1.2.1.02' if classe.tipo == 'CILINDRO' else ('1.2.1.04' if classe.tipo == 'VEICULO' else '1.2.1.06')
        acumulada = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural=codigo_acum).first()

    if not despesa or not acumulada:
        raise ValidationError(
            f"Contas contábeis de depreciação não configuradas para a classe '{classe.nome}' ({classe.codigo})."
        )
    return despesa, acumulada


@transaction.atomic
def calcular_depreciacao_mensal(tenant, periodo: Union[str, datetime.date], usuario=None) -> tuple[list[DepreciacaoMensal], Optional[LancamentoContabil]]:
    """
    Executa o cálculo de depreciação mensal do tenant para o período indicado (Sprint 10B - Tarefa 1).
    Regras estritas:
    1. Idempotência: se o período já foi calculado, retorna os registros e lançamento existentes sem duplicar;
    2. Sequência cronológica: exige o período anterior calculado (salvo se for o primeiro cálculo do tenant);
    3. Ledger individualizado por alvo em DepreciacaoMensal;
    4. Lançamento agregado no Razão por classe e filial (D despesa, C depreciação acumulada).
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'patrimonio')
    assert_modulo(tenant, 'financeiro')

    periodo_mes = normalizar_periodo_data(periodo)

    # 1. Idempotência: se já foi calculado, retorna sem recriar
    existentes = list(DepreciacaoMensal.unscoped.filter(tenant=tenant, periodo=periodo_mes).select_related('lancamento'))
    if existentes:
        lanc = existentes[0].lancamento
        return existentes, lanc

    # 2. Validação de período anterior calculado
    tem_historico = DepreciacaoMensal.unscoped.filter(tenant=tenant).exists()
    if tem_historico:
        mes_ant = obter_mes_anterior(periodo_mes)
        calculado_mes_ant = DepreciacaoMensal.unscoped.filter(tenant=tenant, periodo=mes_ant).exists()
        if not calculado_mes_ant:
            raise ValidationError(
                f"Bloqueio de sequência contábil: O período anterior ({mes_ant.strftime('%m/%Y')}) "
                f"deve ser calculado antes do período atual ({periodo_mes.strftime('%m/%Y')})."
            )

    itens_ledger = []
    # Agrupador para partidas contábeis: (despesa_id, acumulada_id, filial_id, veiculo_id, centro_custo_id) -> total_quota
    agrupador_partidas = {}

    # A) Depreciação de Ativos Imobilizados Gerais
    ativos = AtivoImobilizado.unscoped.filter(tenant=tenant, status='EM_USO').select_related('classe', 'filial')
    for at in ativos:
        dt_ini = at.data_inicio_depreciacao or at.data_aquisicao
        if not dt_ini or dt_ini > periodo_mes:
            continue

        # Verifica se há revisão de vida útil ativa
        revisao = RevisaoVidaUtil.unscoped.filter(
            tenant=tenant,
            tipo_alvo='ATIVO_IMOBILIZADO',
            alvo_id=str(at.id),
            data_revisao__lte=periodo_mes
        ).order_by('-data_revisao').first()

        val_aquisicao = at.valor_aquisicao
        val_residual = at.valor_residual or Decimal('0.00')
        vida_meses = at.vida_util_meses

        # Depreciação acumulada anterior
        ultimo_ledger = DepreciacaoMensal.unscoped.filter(
            tenant=tenant,
            tipo_alvo='ATIVO_IMOBILIZADO',
            alvo_id=str(at.id)
        ).order_by('-periodo').first()
        acum_ant = ultimo_ledger.depreciacao_acumulada_apos if ultimo_ledger else Decimal('0.00')

        if revisao:
            vida_restante = revisao.nova_vida_meses
            res = revisao.novo_valor_residual if revisao.novo_valor_residual is not None else val_residual
            vcl_atual = max(Decimal('0.00'), val_aquisicao - acum_ant)
            base_revisada = max(Decimal('0.00'), vcl_atual - res)
            quota = quantize(base_revisada / Decimal(str(vida_restante)), 2) if vida_restante > 0 else Decimal('0.00')
            base_depreciavel = val_aquisicao - res
        else:
            base_depreciavel = max(Decimal('0.00'), val_aquisicao - val_residual)
            quota = quantize(base_depreciavel / Decimal(str(vida_meses)), 2) if vida_meses > 0 else Decimal('0.00')

        saldo_restante = max(Decimal('0.00'), base_depreciavel - acum_ant)
        quota_efetiva = min(quota, saldo_restante)

        if quota_efetiva > Decimal('0.00'):
            acum_apos = quantize(acum_ant + quota_efetiva, 2)
            vcl_apos = quantize(val_aquisicao - acum_apos, 2)

            dep_reg = DepreciacaoMensal(
                tenant=tenant,
                periodo=periodo_mes,
                tipo_alvo='ATIVO_IMOBILIZADO',
                alvo_id=str(at.id),
                quota=quota_efetiva,
                depreciacao_acumulada_apos=acum_apos,
                valor_contabil_apos=vcl_apos
            )
            itens_ledger.append(dep_reg)

            # Contabilização agregada
            cta_desp, cta_acum = obter_contas_classe(tenant, at.classe)
            # Veículo associado caso classe seja veículo
            veiculo_id = None
            if at.classe.tipo == 'VEICULO':
                from logistica.models import Veiculo
                v_obj = Veiculo.unscoped.filter(tenant=tenant, placa__icontains=at.numero_patrimonio).first()
                if v_obj:
                    veiculo_id = v_obj.id

            cc = CentroCusto.unscoped.filter(tenant=tenant, codigo='CC-02' if at.classe.tipo == 'VEICULO' else 'CC-04').first()
            cc_id = cc.id if cc else None
            chave = (cta_desp.id, cta_acum.id, at.filial_id, veiculo_id, cc_id)
            agrupador_partidas[chave] = quantize(agrupador_partidas.get(chave, Decimal('0.00')) + quota_efetiva, 2)

    # B) Depreciação de Lotes de Cilindros
    lotes = LoteAquisicaoCilindros.unscoped.filter(tenant=tenant).select_related('classe')
    for lote in lotes:
        if lote.data_aquisicao > periodo_mes:
            continue

        ultimo_ledger = DepreciacaoMensal.unscoped.filter(
            tenant=tenant,
            tipo_alvo='LOTE_CILINDROS',
            alvo_id=str(lote.id)
        ).order_by('-periodo').first()
        acum_ant = ultimo_ledger.depreciacao_acumulada_apos if ultimo_ledger else Decimal('0.00')

        pct_res = lote.classe.percentual_residual_padrao or Decimal('0.1000')
        val_residual = quantize(lote.valor_total * pct_res, 2)
        vida_meses = lote.classe.vida_util_meses_padrao or 120
        base_depreciavel = max(Decimal('0.00'), lote.valor_total - val_residual)

        quota = quantize(base_depreciavel / Decimal(str(vida_meses)), 2)
        saldo_restante = max(Decimal('0.00'), base_depreciavel - acum_ant)
        quota_efetiva = min(quota, saldo_restante)

        if quota_efetiva > Decimal('0.00'):
            acum_apos = quantize(acum_ant + quota_efetiva, 2)
            vcl_apos = quantize(lote.valor_total - acum_apos, 2)

            dep_reg = DepreciacaoMensal(
                tenant=tenant,
                periodo=periodo_mes,
                tipo_alvo='LOTE_CILINDROS',
                alvo_id=str(lote.id),
                quota=quota_efetiva,
                depreciacao_acumulada_apos=acum_apos,
                valor_contabil_apos=vcl_apos
            )
            itens_ledger.append(dep_reg)

            cta_desp, cta_acum = obter_contas_classe(tenant, lote.classe)
            cc = CentroCusto.unscoped.filter(tenant=tenant, codigo='CC-01').first()
            cc_id = cc.id if cc else None
            chave = (cta_desp.id, cta_acum.id, None, None, cc_id)
            agrupador_partidas[chave] = quantize(agrupador_partidas.get(chave, Decimal('0.00')) + quota_efetiva, 2)

    # C) Depreciação de Cilindros Avulsos Próprios (não vinculados a lote)
    cilindros = Cilindro.unscoped.filter(
        tenant=tenant,
        propriedade='PROPRIO',
        lote_aquisicao__isnull=True,
        valor_aquisicao__gt=Decimal('0.00')
    ).exclude(status__in=['BAIXADO', 'EXTRAVIADO'])

    for cil in cilindros:
        dt_ini = cil.data_inicio_depreciacao or cil.data_aquisicao
        if not dt_ini or dt_ini > periodo_mes:
            continue

        ultimo_ledger = DepreciacaoMensal.unscoped.filter(
            tenant=tenant,
            tipo_alvo='CILINDRO_AVULSO',
            alvo_id=str(cil.id)
        ).order_by('-periodo').first()
        acum_ant = ultimo_ledger.depreciacao_acumulada_apos if ultimo_ledger else Decimal('0.00')

        val_aquisicao = cil.valor_aquisicao
        val_residual = cil.valor_residual or Decimal('0.00')
        vida_meses = cil.vida_util_meses or 120
        base_depreciavel = max(Decimal('0.00'), val_aquisicao - val_residual)

        quota = quantize(base_depreciavel / Decimal(str(vida_meses)), 2)
        saldo_restante = max(Decimal('0.00'), base_depreciavel - acum_ant)
        quota_efetiva = min(quota, saldo_restante)

        if quota_efetiva > Decimal('0.00'):
            acum_apos = quantize(acum_ant + quota_efetiva, 2)
            vcl_apos = quantize(val_aquisicao - acum_apos, 2)

            dep_reg = DepreciacaoMensal(
                tenant=tenant,
                periodo=periodo_mes,
                tipo_alvo='CILINDRO_AVULSO',
                alvo_id=str(cil.id),
                quota=quota_efetiva,
                depreciacao_acumulada_apos=acum_apos,
                valor_contabil_apos=vcl_apos
            )
            itens_ledger.append(dep_reg)

            # Contas padrão de cilindro
            desp = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='6.1').first()
            acum = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='1.2.1.02').first()
            if desp and acum:
                cc = CentroCusto.unscoped.filter(tenant=tenant, codigo='CC-01').first()
                cc_id = cc.id if cc else None
                chave = (desp.id, acum.id, None, None, cc_id)
                agrupador_partidas[chave] = quantize(agrupador_partidas.get(chave, Decimal('0.00')) + quota_efetiva, 2)

    if not itens_ledger:
        return [], None

    # 3. Geração do lançamento contábil agregado no Razão
    partidas_lanc = []
    filial_principal = None
    for (cta_desp_id, cta_acum_id, fil_id, veic_id, cc_id), valor_total in agrupador_partidas.items():
        if fil_id and not filial_principal:
            from core.models import Filial
            filial_principal = Filial.unscoped.filter(id=fil_id).first()

        partidas_lanc.append({
            'conta_id': cta_desp_id,
            'tipo_partida': 'DEBITO',
            'valor': valor_total,
            'centro_custo_id': cc_id,
            'veiculo_id': veic_id,
        })
        partidas_lanc.append({
            'conta_id': cta_acum_id,
            'tipo_partida': 'CREDITO',
            'valor': valor_total,
            'centro_custo_id': cc_id,
            'veiculo_id': veic_id,
        })

    # Data de competência = último dia do mês
    _, ultimo_dia = obter_mes_anterior(periodo_mes), None
    if periodo_mes.month == 12:
        dt_comp = datetime.date(periodo_mes.year, 12, 31)
    else:
        dt_comp = datetime.date(periodo_mes.year, periodo_mes.month + 1, 1) - datetime.timedelta(days=1)

    lancamento, _ = lancar(
        tenant=tenant,
        data_competencia=dt_comp,
        historico=f"Depreciação Mensal do Imobilizado - Competência {periodo_mes.strftime('%m/%Y')}",
        partidas=partidas_lanc,
        filial=filial_principal,
        origem_tipo='DepreciacaoMensal',
        origem_id=periodo_mes.strftime('%Y-%m'),
        usuario=usuario
    )

    # 4. Grava os registros no ledger vinculados ao lançamento
    for item in itens_ledger:
        item.lancamento = lancamento

    DepreciacaoMensal.unscoped.bulk_create(itens_ledger)
    return itens_ledger, lancamento


@transaction.atomic
def revisar_vida_util(
    *,
    tenant,
    tipo_alvo: str,
    alvo_id: Union[str, int],
    data_revisao: datetime.date,
    nova_vida_meses: int,
    motivo: str,
    novo_valor_residual: Optional[Decimal] = None,
    usuario=None
) -> RevisaoVidaUtil:
    """
    Registra formalmente a revisão de vida útil de um ativo sob CPC 23 (Sprint 10B - Tarefa 3).
    A revisão tem aplicação estritamente prospectiva; quotas e saldos passados não mudam.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'patrimonio')

    if not nova_vida_meses or nova_vida_meses <= 0:
        raise ValidationError("A nova vida útil restante deve ser maior que zero meses.")

    if not motivo or not motivo.strip():
        raise ValidationError("O motivo formal e a justificativa técnica/econômica são obrigatórios.")

    revisao = RevisaoVidaUtil.objects.create(
        tenant=tenant,
        tipo_alvo=tipo_alvo,
        alvo_id=str(alvo_id),
        data_revisao=data_revisao,
        nova_vida_meses=nova_vida_meses,
        novo_valor_residual=novo_valor_residual,
        motivo=motivo.strip(),
        usuario=usuario
    )
    return revisao


@transaction.atomic
def baixar_patrimonio_contabil(
    *,
    tenant,
    tipo_alvo: str,
    alvo_id: Union[str, int],
    data_baixa: datetime.date,
    valor_alienacao: Decimal = Decimal('0.00'),
    valor_recebido: Optional[Decimal] = None,
    conta_destino: Optional[PlanoContas] = None,
    conta_caixa_id: Optional[int] = None,
    motivo: str = "",
    usuario=None
) -> tuple[Optional[LancamentoContabil], Decimal]:
    """
    Realiza a baixa patrimonial contábil de um ativo imobilizado (Sprint 10B - Tarefa 4).
    1. Completa a depreciação acumulada até a data da baixa;
    2. Obtém custo de aquisição, depreciação acumulada e VCL do ledger;
    3. Apura ganho ou perda de capital (alienação - VCL);
    4. Escritura no Razão:
       - Débito em Depreciação Acumulada;
       - Débito em Caixa/Banco (valor de alienação recebido);
       - Crédito no Imobilizado (custo de aquisição);
       - Diferença debitada ou creditada na conta 8.2 (Resultado na Baixa de Imobilizado).
    5. Atualiza o status do ativo para BAIXADO.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'patrimonio')
    assert_modulo(tenant, 'financeiro')

    if valor_recebido is not None:
        valor_alienacao = valor_recebido
    if conta_caixa_id is not None and not conta_destino:
        conta_destino = PlanoContas.unscoped.filter(tenant=tenant, id=conta_caixa_id).first()

    valor_alienacao = quantize(Decimal(str(valor_alienacao or '0.00')), 2)

    if tipo_alvo == 'ATIVO_IMOBILIZADO':
        ativo = AtivoImobilizado.unscoped.select_for_update().get(tenant=tenant, id=alvo_id)
        custo_aquisicao = ativo.valor_aquisicao
        cta_desp, cta_acum = obter_contas_classe(tenant, ativo.classe)
        cta_imob = ativo.classe.conta_imobilizado
        if not cta_imob:
            codigo_imob = '1.2.1.03' if ativo.classe.tipo == 'VEICULO' else '1.2.1.05'
            cta_imob = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural=codigo_imob).first()

        # Busca depreciação acumulada no ledger
        ultimo_ledger = DepreciacaoMensal.unscoped.filter(
            tenant=tenant,
            tipo_alvo='ATIVO_IMOBILIZADO',
            alvo_id=str(ativo.id)
        ).order_by('-periodo').first()
        dep_acumulada = ultimo_ledger.depreciacao_acumulada_apos if ultimo_ledger else Decimal('0.00')

        vcl = max(Decimal('0.00'), custo_aquisicao - dep_acumulada)
        resultado_alienacao = quantize(valor_alienacao - vcl, 2)

        # Conta 8.2 para resultado na baixa de imobilizado
        cta_resultado_82 = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='8.2').first()
        if not cta_resultado_82:
            raise ValidationError("Conta 8.2 (Resultado na Baixa e Alienação de Imobilizado) não encontrada no Plano de Contas.")

        partidas = []
        # 1. Baixa da Depreciação Acumulada (D)
        if dep_acumulada > Decimal('0.00'):
            partidas.append({
                'conta_id': cta_acum.id,
                'tipo_partida': 'DEBITO',
                'valor': dep_acumulada,
            })

        # 2. Entrada do recurso alienado (D)
        if valor_alienacao > Decimal('0.00'):
            if not conta_destino:
                conta_destino = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural='1.1.1.01').first()
            partidas.append({
                'conta_id': conta_destino.id,
                'tipo_partida': 'DEBITO',
                'valor': valor_alienacao,
            })

        # 3. Baixa do Custo Histórico do Imobilizado (C)
        partidas.append({
            'conta_id': cta_imob.id,
            'tipo_partida': 'CREDITO',
            'valor': custo_aquisicao,
        })

        # 4. Reconhecimento de Ganho ou Perda de Capital em 8.2
        if resultado_alienacao < Decimal('0.00'):
            # Perda na baixa: Débito em 8.2
            partidas.append({
                'conta_id': cta_resultado_82.id,
                'tipo_partida': 'DEBITO',
                'valor': abs(resultado_alienacao),
            })
        elif resultado_alienacao > Decimal('0.00'):
            # Ganho na alienação: Crédito em 8.2
            partidas.append({
                'conta_id': cta_resultado_82.id,
                'tipo_partida': 'CREDITO',
                'valor': resultado_alienacao,
            })

        lancamento, _ = lancar(
            tenant=tenant,
            data_competencia=data_baixa,
            historico=f"Baixa Patrimonial {ativo.numero_patrimonio} - {ativo.descricao} ({motivo or 'Alienação/Descarte'})",
            partidas=partidas,
            filial=ativo.filial,
            origem_tipo='BaixaPatrimonial',
            origem_id=str(ativo.id),
            usuario=usuario
        )

        ativo.status = 'BAIXADO' if valor_alienacao == Decimal('0.00') else 'VENDIDO'
        ativo.save(update_fields=['status', 'atualizado_em'])
        return lancamento, resultado_alienacao

    raise ValidationError(f"Tipo de alvo para baixa patrimonial não suportado: {tipo_alvo}")


@transaction.atomic
def capitalizar_reteste_componente(
    *,
    tenant,
    cilindro_id: Union[str, int],
    reteste_id: Union[str, int],
    custo_servico_reteste: Decimal,
    data_reteste: datetime.date,
    periodicidade_meses: int = 60
) -> AtivoImobilizado:
    """
    Capitaliza o reteste hidrostático como componente de ativo imobilizado (Sprint 10B - Tarefa 5).
    Cria um AtivoImobilizado na classe «Componente de reteste» a ser depreciado pelo ledger
    ao longo do prazo da periodicidade normativa.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'patrimonio')

    custo = quantize(Decimal(str(custo_servico_reteste)), 2)
    if custo <= Decimal('0.00'):
        raise ValidationError("O custo do serviço de reteste deve ser maior que zero para capitalização.")

    # 1. Garante classe de ativo para componente de reteste
    classe, _ = ClasseAtivo.unscoped.get_or_create(
        tenant=tenant,
        codigo='COMPONENTE_RETESTE',
        defaults={
            'nome': 'Componente de Reteste',
            'tipo': 'CILINDRO',
            'vida_util_meses_padrao': periodicidade_meses,
            'percentual_residual_padrao': Decimal('0.0000'),
            'codigo_conta_imobilizado': '1.2.1.01',
            'codigo_conta_depreciacao_acumulada': '1.2.1.02',
            'codigo_conta_despesa_depreciacao': '6.1',
        }
    )

    cil = Cilindro.unscoped.get(tenant=tenant, id=cilindro_id)

    # 2. Criação do ativo imobilizado individual para o componente
    num_pat = f"RET-{cil.codigo_qr}-{reteste_id}"
    ativo = AtivoImobilizado.objects.create(
        tenant=tenant,
        classe=classe,
        numero_patrimonio=num_pat,
        descricao=f"Componente Reteste - Cilindro {cil.codigo_qr} (Reteste #{reteste_id})",
        data_aquisicao=data_reteste,
        data_inicio_depreciacao=data_reteste,
        valor_aquisicao=custo,
        valor_residual=Decimal('0.00'),
        vida_util_meses=periodicidade_meses,
        status='EM_USO'
    )
    return ativo
