from decimal import Decimal
from datetime import date
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.guards import assert_tenant_writable
from core.money import quantize
from fiscal.models import (
    ApuracaoImposto,
    DocumentoFiscal,
    DocumentoFiscalItem,
    ItemDocumentoTributo,
    DocumentoFiscalEntrada,
)


@transaction.atomic
def calcular_apuracao_imposto(
    tenant,
    filial,
    periodo: str,
    tributo: str
) -> ApuracaoImposto:
    """
    Calcula a apuração gerencial de tributos do período/competência (Sprint 11B - Tarefa 10).
    - Débitos: soma de impostos de itens de documentos de saída AUTORIZADOS.
    - Créditos: soma de créditos tributários de NF-e de entrada importadas.
    - Saldo Credor Anterior: transportado da apuração da competência anterior.
    - Saldo Apurado = Débitos - Créditos - Saldo Credor Anterior.
      (Positivo = Saldo a Recolher / Gerar Guia; Negativo = Saldo Credor a Transportar).
    """
    assert_tenant_writable(tenant)

    if not periodo or len(periodo) != 7 or '-' not in periodo:
        raise ValidationError(f"Período de apuração inválido '{periodo}'. Utilize o formato 'AAAA-MM' (Ex: '2026-10').")

    ano, mes = map(int, periodo.split('-'))

    # 1. Cálculo de Débitos (Saídas)
    # Busca itens de documentos fiscais autorizados do período
    docs_saida = DocumentoFiscal.objects.filter(
        tenant=tenant,
        filial=filial,
        status='AUTORIZADO',
        criado_em__year=ano,
        criado_em__month=mes
    ).exclude(
        tipo_operacao__in=['RETORNO_COMODATO', 'RETORNO_VASILHAME', 'RETORNO_CONSERTO', 'COMPRA']
    )

    debitos = Decimal('0.00')
    itens_docs = DocumentoFiscalItem.objects.filter(documento__in=docs_saida)
    tributos_itens = ItemDocumentoTributo.objects.filter(item__in=itens_docs, tributo=tributo)
    for tib in tributos_itens:
        debitos += tib.valor

    debitos = quantize(debitos)

    # 2. Cálculo de Créditos (Entradas)
    creditos = Decimal('0.00')
    docs_entrada = DocumentoFiscalEntrada.objects.filter(
        tenant=tenant,
        filial=filial,
        data_emissao__year=ano,
        data_emissao__month=mes
    ).exclude(status='CANCELADO')

    for doc_ent in docs_entrada:
        if tributo == 'ICMS':
            creditos += doc_ent.credito_icms
        elif tributo == 'PIS':
            creditos += doc_ent.credito_pis
        elif tributo == 'COFINS':
            creditos += doc_ent.credito_cofins
        elif tributo == 'IPI':
            creditos += doc_ent.credito_ipi

    creditos = quantize(creditos)

    # 3. Saldo Credor Anterior
    # Tenta identificar competência imediatamente anterior (Ex: '2026-09' para '2026-10')
    ano, mes = map(int, periodo.split('-'))
    if mes == 1:
        periodo_ant = f"{ano - 1:04d}-12"
    else:
        periodo_ant = f"{ano:04d}-{mes - 1:02d}"

    apuracao_ant = ApuracaoImposto.objects.filter(
        tenant=tenant,
        filial=filial,
        tributo=tributo,
        periodo=periodo_ant
    ).first()

    saldo_anterior = Decimal('0.00')
    if apuracao_ant and apuracao_ant.saldo_apurado < Decimal('0.00'):
        saldo_anterior = abs(apuracao_ant.saldo_apurado)

    saldo_apurado = quantize(debitos - creditos - saldo_anterior)

    apuracao, _ = ApuracaoImposto.objects.update_or_create(
        tenant=tenant,
        filial=filial,
        periodo=periodo,
        tributo=tributo,
        defaults={
            'debitos': debitos,
            'creditos': creditos,
            'saldo_credor_anterior': saldo_anterior,
            'saldo_apurado': saldo_apurado,
            'status': 'ABERTO'
        }
    )

    return apuracao


@transaction.atomic
def fechar_apuracao_e_gerar_guia(
    apuracao: ApuracaoImposto,
    data_vencimento: date,
    usuario=None
) -> ApuracaoImposto:
    """
    Consolida o fechamento da apuração do período (Task 10).
    Se o saldo for devedor (saldo_apurado > 0), gera a respectiva Guia/Título PAGAR
    no módulo financeiro na categoria de tributos/obrigações fiscais.
    """
    assert_tenant_writable(apuracao.tenant)

    if apuracao.status == 'FECHADO' or apuracao.status == 'GUIA_GERADA':
        return apuracao

    # Se há saldo de imposto a recolher
    if apuracao.saldo_apurado > Decimal('0.00'):
        if getattr(apuracao.tenant, 'modulo_financeiro_ativo', False):
            try:
                from financeiro.models import TituloFinanceiro, ParcelaFinanceira, PlanoContas
                conta_tributos = PlanoContas.objects.filter(
                    tenant=apuracao.tenant,
                    codigo_estrutural__startswith='2.1.2',
                    tipo='ANALITICA',
                    aceita_lancamento=True
                ).first()
                if not conta_tributos:
                    conta_tributos = PlanoContas.objects.filter(tenant=apuracao.tenant, tipo='ANALITICA', aceita_lancamento=True).first()

                v_saldo = quantize(apuracao.saldo_apurado)
                titulo = TituloFinanceiro.objects.create(
                    tenant=apuracao.tenant,
                    filial=apuracao.filial,
                    tipo='PAGAR',
                    beneficiario_texto=f"Secretaria da Fazenda - Guia {apuracao.tributo} ({apuracao.periodo})",
                    conta_gerencial=conta_tributos,
                    origem_tipo='MANUAL',
                    origem_id=str(apuracao.id),
                    valor_bruto=v_saldo,
                    valor_liquido_esperado=v_saldo,
                    data_emissao=timezone.localdate(),
                    data_competencia=timezone.localdate(),
                    status='ABERTO',
                    historico=f"Guia de Recolhimento Apuração {apuracao.tributo} ({apuracao.periodo})"
                )
                ParcelaFinanceira.objects.create(
                    tenant=apuracao.tenant,
                    titulo=titulo,
                    numero_parcela=1,
                    total_parcelas=1,
                    data_vencimento=data_vencimento or timezone.localdate() + timezone.timedelta(days=20),
                    valor_nominal=v_saldo,
                    saldo_em_aberto=v_saldo,
                    status='PENDENTE'
                )
                apuracao.titulo_pagar = titulo
                apuracao.status = 'GUIA_GERADA'
            except Exception:
                apuracao.status = 'FECHADO'
        else:
            apuracao.status = 'FECHADO'
    else:
        apuracao.status = 'FECHADO'

    apuracao.fechado_em = timezone.now()
    apuracao.fechado_por = usuario
    apuracao.save(update_fields=['status', 'titulo_pagar', 'fechado_em', 'fechado_por', 'atualizado_em'])

    return apuracao
