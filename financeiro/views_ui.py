"""
Views baseadas em template (UI HTML) para o módulo Financeiro (Sprint 9A - Tarefa 12).
Fornece interface para consulta do Plano de Contas, Balancete, Períodos Contábeis,
Contas Financeiras (com transferências), Centros de Custo e Fornecedores.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from core.modulos import is_modulo_ativo
from financeiro.models import (
    PlanoContas,
    CentroCusto,
    Fornecedor,
    CondicaoPagamento,
    PeriodoContabil,
    ContaFinanceira,
    LancamentoContabil,
)
from financeiro.selectors.balancete import obter_balancete_verificacao
from financeiro.services.conta import saldo_em


class FinanceiroDashboardView(LoginRequiredMixin, View):
    """
    Dashboard unificado de Gestão Contábil e Financeira Base.
    """
    template_name = 'financeiro/dashboard.html'

    def get(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            raise PermissionDenied("Nenhum tenant ativo associado à sessão.")

        # Validação de Módulo Financeiro
        if not is_modulo_ativo(tenant, 'financeiro') and not request.user.is_superuser:
            raise PermissionDenied("O módulo Financeiro não está contratado ou ativo para esta empresa.")

        hoje = timezone.localdate()
        mes_atual = hoje.month
        ano_atual = hoje.year

        # Contas Financeiras com saldo atual apurado dinamicamente
        contas_fin = ContaFinanceira.objects.all().order_by('nome')
        contas_com_saldo = []
        for c in contas_fin:
            contas_com_saldo.append({
                'conta': c,
                'saldo_atual': saldo_em(c, hoje)
            })

        # Plano de contas estruturado
        plano_contas = PlanoContas.objects.all().order_by('codigo_estrutural')

        # Centros de Custo
        centros_custo = CentroCusto.objects.all().order_by('codigo')

        # Fornecedores
        fornecedores = Fornecedor.objects.all().order_by('razao_social')

        # Condições de Pagamento
        condicoes = CondicaoPagamento.objects.all().order_by('nome')

        # Períodos contábeis recentes
        periodos = PeriodoContabil.objects.all().order_by('-ano', '-mes')[:12]

        # Últimos lançamentos do Razão
        ultimos_lancamentos = LancamentoContabil.objects.select_related('criado_por').prefetch_related('partidas__conta_contabil').order_by('-numero')[:15]

        # Balancete padrão do mês corrente
        data_ini_balancete = hoje.replace(day=1).isoformat()
        data_fim_balancete = hoje.isoformat()
        balancete = obter_balancete_verificacao(
            tenant=tenant,
            data_inicio=data_ini_balancete,
            data_fim=data_fim_balancete,
            apenas_com_movimento=False
        )

        # Sprint 9B: Títulos e Obrigações
        from financeiro.models import TituloFinanceiro, PendenciaContabilizacao, ImportacaoSaldoAbertura
        titulos_receber = TituloFinanceiro.objects.filter(tipo='RECEBER').select_related('cliente', 'conta_gerencial').prefetch_related('parcelas').order_by('-data_emissao')[:30]
        titulos_pagar = TituloFinanceiro.objects.filter(tipo='PAGAR').select_related('fornecedor', 'conta_gerencial').prefetch_related('parcelas').order_by('-data_emissao')[:30]
        titulos_em_aprovacao = TituloFinanceiro.objects.filter(tipo='PAGAR', status='EM_APROVACAO').select_related('fornecedor', 'criado_por').order_by('-data_emissao')
        pendencias = PendenciaContabilizacao.objects.filter(resolvido=False).order_by('-criado_em')[:15]
        importacoes_abertura = ImportacaoSaldoAbertura.objects.all().order_by('-criado_em')[:5]

        # Sprint 9C: Despesas de Campo, Faturas Posto e Caixa de Rota
        from financeiro.models import PreLancamentoDespesaCampo, FaturaConsolidadaPosto, FechamentoCaixaRota
        despesas_campo_pendentes = PreLancamentoDespesaCampo.objects.filter(status='PENDENTE_CONFERENCIA').select_related('veiculo', 'motorista').order_by('-data_hora')[:30]
        faturas_posto_recentes = FaturaConsolidadaPosto.objects.all().order_by('-criado_em')[:10]
        fechamentos_caixa_recentes = FechamentoCaixaRota.objects.select_related('motorista', 'conta_caixa').order_by('-data', '-criado_em')[:15]

        context = {
            'hoje': hoje,
            'ano_atual': ano_atual,
            'mes_atual': mes_atual,
            'contas_financeiras': contas_com_saldo,
            'plano_contas': plano_contas,
            'centros_custo': centros_custo,
            'fornecedores': fornecedores,
            'condicoes_pagamento': condicoes,
            'periodos_contabeis': periodos,
            'ultimos_lancamentos': ultimos_lancamentos,
            'balancete': balancete,
            'titulos_receber': titulos_receber,
            'titulos_pagar': titulos_pagar,
            'titulos_em_aprovacao': titulos_em_aprovacao,
            'pendencias': pendencias,
            'importacoes_abertura': importacoes_abertura,
            'despesas_campo_pendentes': despesas_campo_pendentes,
            'faturas_posto_recentes': faturas_posto_recentes,
            'fechamentos_caixa_recentes': fechamentos_caixa_recentes,
        }
        return render(request, self.template_name, context)


class FechamentoCaixaDetalheView(LoginRequiredMixin, View):
    """
    Interface para contagem cega e conferência de caixa de rota.
    IMPORTANTE: Nunca expõe o saldo_esperado antes de informada a contagem cega.
    """
    template_name = 'financeiro/fechamento_caixa_detalhe.html'

    def get(self, request, pk, *args, **kwargs):
        from django.shortcuts import get_object_or_404
        from financeiro.models import FechamentoCaixaRota

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            raise PermissionDenied("Nenhum tenant ativo associado à sessão.")

        fechamento = get_object_or_404(FechamentoCaixaRota.objects.filter(tenant=tenant), pk=pk)

        context = {
            'fechamento': fechamento,
            'exibir_saldo_esperado': (fechamento.valor_contado_cego is not None),
        }
        return render(request, self.template_name, context)


class ConciliacaoBancariaView(LoginRequiredMixin, View):
    """
    Interface Visual de Conciliação Bancária lado a lado (Sprint 10A - Tarefa 6).
    Extrato à esquerda, Sistema à direita; Batimento de saldo e ações auditadas.
    """
    template_name = 'financeiro/conciliacao.html'

    def get(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            raise PermissionDenied("Nenhum tenant ativo associado à sessão.")

        if not is_modulo_ativo(tenant, 'financeiro') and not request.user.is_superuser:
            raise PermissionDenied("Módulo financeiro não contratado.")

        contas = ContaFinanceira.objects.filter(
            tipo__in=['CONTA_CORRENTE', 'CONTA_INVESTIMENTO'],
            ativo=True
        ).order_by('nome')

        conta_id = request.GET.get('conta_id')
        conta_selecionada = None
        if conta_id:
            conta_selecionada = contas.filter(id=int(conta_id)).first()
        if not conta_selecionada:
            conta_selecionada = contas.first()

        painel = None
        if conta_selecionada:
            from financeiro.selectors.conciliacao import obter_painel_conciliacao
            painel = obter_painel_conciliacao(tenant=tenant, conta_id=conta_selecionada.id)

        from financeiro.models import PlanoContas, CentroCusto
        contas_contabeis = PlanoContas.objects.filter(aceita_lancamento=True, tipo='ANALITICA').order_by('codigo_estrutural')
        centros_custo = CentroCusto.objects.filter(ativo=True).order_by('codigo')

        context = {
            'contas': contas,
            'conta_selecionada': conta_selecionada,
            'painel': painel,
            'contas_contabeis': contas_contabeis,
            'centros_custo': centros_custo,
        }
        return render(request, self.template_name, context)



