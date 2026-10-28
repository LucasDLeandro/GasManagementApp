"""
Roteamento de URLs e API RESTful do módulo Financeiro (Sprint 9A).
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from financeiro.views import (
    PlanoContasViewSet,
    CentroCustoViewSet,
    FornecedorViewSet,
    CondicaoPagamentoViewSet,
    PeriodoContabilViewSet,
    ContaFinanceiraViewSet,
    MovimentoContaViewSet,
    RazaoViewSet,
    BalanceteAPIView,
    TituloFinanceiroViewSet,
    ParcelaFinanceiraViewSet,
    BaixaParcelaViewSet,
    AlcadaAprovacaoViewSet,
    PendenciaContabilizacaoViewSet,
    SaldoAberturaViewSet,
    PreLancamentoDespesaCampoViewSet,
    FaturaConsolidadaPostoViewSet,
    FechamentoCaixaRotaViewSet,
    PrecoReferenciaCombustivelViewSet,
    RelatorioConsumoVeiculosAPIView,
    RankingMotoristasAnomaliasAPIView,
    RelatorioQuebrasCaixaAPIView,
    ImportacaoExtratoViewSet,
    ExtratoBancarioItemViewSet,
    PainelConciliacaoAPIView,
    RegraConciliacaoViewSet,
    ConfiguracaoCobrancaViewSet,
    ReguaCobrancaViewSet,
    EnvioCobrancaViewSet,
    ConsentimentoContatoViewSet,
    EmitirCobrancaParcelaAPIView,
    WebhookCobrancaAPIView,
    MarcarProtestoManualAPIView,
    DepreciacaoViewSet,
    RevisaoVidaUtilViewSet,
    SaldoMensalContaViewSet,
    DREAPIView,
    ParametroTributarioLucroViewSet,
    OrcamentoViewSet,
    ParametroPDDViewSet,
    LancamentoManualViewSet,
    ExportacaoContabilAPIView,
    PerfilPagamentoClienteViewSet,
    RecorrenciaFinanceiraViewSet,
    AlertaCaixaViewSet,
    ParametroGestaoTenantViewSet,
    FluxoCaixaRealizadoAPIView,
    ProjecaoCaixaCenariosAPIView,
    ParametroCreditoViewSet,
    LimiteCreditoClienteViewSet,
    PromessaPagamentoViewSet,
    PainelBloqueiosAPIView,
)

from financeiro.views_ui import (
    FinanceiroDashboardView,
    FechamentoCaixaDetalheView,
    ConciliacaoBancariaView,
)

app_name = 'financeiro'

router = DefaultRouter()
router.register(r'plano-contas', PlanoContasViewSet, basename='plano-contas')
router.register(r'centros-custo', CentroCustoViewSet, basename='centro-custo')
router.register(r'fornecedores', FornecedorViewSet, basename='fornecedor')
router.register(r'condicoes-pagamento', CondicaoPagamentoViewSet, basename='condicao-pagamento')
router.register(r'periodos', PeriodoContabilViewSet, basename='periodo-contabil')
router.register(r'contas-financeiras', ContaFinanceiraViewSet, basename='conta-financeira')
router.register(r'movimentos-conta', MovimentoContaViewSet, basename='movimento-conta')
router.register(r'razao', RazaoViewSet, basename='razao')
router.register(r'titulos', TituloFinanceiroViewSet, basename='titulo-financeiro')
router.register(r'parcelas', ParcelaFinanceiraViewSet, basename='parcela-financeira')
router.register(r'baixas', BaixaParcelaViewSet, basename='baixa-parcela')
router.register(r'alcadas', AlcadaAprovacaoViewSet, basename='alcada-aprovacao')
router.register(r'pendencias', PendenciaContabilizacaoViewSet, basename='pendencia-contabilizacao')
router.register(r'saldo-abertura', SaldoAberturaViewSet, basename='saldo-abertura')
router.register(r'despesas-campo', PreLancamentoDespesaCampoViewSet, basename='despesa-campo')
router.register(r'faturas-posto', FaturaConsolidadaPostoViewSet, basename='fatura-posto')
router.register(r'fechamentos-caixa', FechamentoCaixaRotaViewSet, basename='fechamento-caixa')
router.register(r'precos-referencia', PrecoReferenciaCombustivelViewSet, basename='preco-referencia')

# Sprint 10A
router.register(r'importacoes-extrato', ImportacaoExtratoViewSet, basename='importacao-extrato')
router.register(r'extrato-itens', ExtratoBancarioItemViewSet, basename='extrato-item')
router.register(r'regras-conciliacao', RegraConciliacaoViewSet, basename='regra-conciliacao')
router.register(r'configuracoes-cobranca', ConfiguracaoCobrancaViewSet, basename='configuracao-cobranca')
router.register(r'reguas-cobranca', ReguaCobrancaViewSet, basename='regua-cobranca')
router.register(r'envios-cobranca', EnvioCobrancaViewSet, basename='envio-cobranca')
router.register(r'consentimentos-contato', ConsentimentoContatoViewSet, basename='consentimento-contato')

# Sprint 10B
router.register(r'depreciacao', DepreciacaoViewSet, basename='depreciacao')
router.register(r'revisoes-vida-util', RevisaoVidaUtilViewSet, basename='revisao-vida-util')
router.register(r'saldos-mensais', SaldoMensalContaViewSet, basename='saldo-mensal-conta')
router.register(r'parametros-tributarios', ParametroTributarioLucroViewSet, basename='parametro-tributario')
router.register(r'orcamentos', OrcamentoViewSet, basename='orcamento')
router.register(r'parametros-pdd', ParametroPDDViewSet, basename='parametro-pdd')
router.register(r'lancamentos-manuais', LancamentoManualViewSet, basename='lancamento-manual')

# Sprint 10C
router.register(r'perfis-pagamento', PerfilPagamentoClienteViewSet, basename='perfil-pagamento')
router.register(r'recorrencias', RecorrenciaFinanceiraViewSet, basename='recorrencia')
router.register(r'alertas-caixa', AlertaCaixaViewSet, basename='alerta-caixa')
router.register(r'parametros-gestao', ParametroGestaoTenantViewSet, basename='parametro-gestao')

# Sprint 11C
router.register(r'parametros-credito', ParametroCreditoViewSet, basename='parametro-credito')
router.register(r'limites-credito-cliente', LimiteCreditoClienteViewSet, basename='limite-credito-cliente')
router.register(r'promessas-pagamento', PromessaPagamentoViewSet, basename='promessa-pagamento')

urlpatterns = [
    path('', FinanceiroDashboardView.as_view(), name='index'),
    path('conciliacao/', ConciliacaoBancariaView.as_view(), name='conciliacao_view'),
    path('fechamento-caixa/<int:pk>/', FechamentoCaixaDetalheView.as_view(), name='fechamento_caixa_detalhe'),
    path('api/balancete/', BalanceteAPIView.as_view(), name='balancete_api'),
    path('api/relatorios/consumo-veiculos/', RelatorioConsumoVeiculosAPIView.as_view(), name='relatorio_consumo_veiculos'),
    path('api/relatorios/ranking-anomalias/', RankingMotoristasAnomaliasAPIView.as_view(), name='ranking_motoristas_anomalias'),
    path('api/relatorios/quebras-caixa/', RelatorioQuebrasCaixaAPIView.as_view(), name='relatorio_quebras_caixa'),
    # Sprint 10A APIs
    path('api/conciliacao/painel/', PainelConciliacaoAPIView.as_view(), name='painel_conciliacao'),
    path('api/cobranca/emitir-parcela/', EmitirCobrancaParcelaAPIView.as_view(), name='emitir_cobranca_parcela'),
    path('api/cobranca/webhook/', WebhookCobrancaAPIView.as_view(), name='webhook_cobranca'),
    path('api/parcelas/<int:pk>/protestar/', MarcarProtestoManualAPIView.as_view(), name='parcela_protestar'),
    # Sprint 10B APIs
    path('api/dre/', DREAPIView.as_view(), name='dre_api'),
    path('api/exportacao-contabil/', ExportacaoContabilAPIView.as_view(), name='exportacao_contabil_api'),
    # Sprint 10C APIs
    path('api/fluxo-caixa-realizado/', FluxoCaixaRealizadoAPIView.as_view(), name='fluxo_caixa_realizado_api'),
    path('api/projecao-caixa/', ProjecaoCaixaCenariosAPIView.as_view(), name='projecao_caixa_api'),
    # Sprint 11C APIs
    path('api/painel-bloqueios/', PainelBloqueiosAPIView.as_view(), name='painel_bloqueios_api'),
    path('api/', include(router.urls)),
]


