from django.urls import path, include
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter
from .views import (
    LogisticaTemplateView,
    AppCampoView,
    VeiculoViewSet,
    RotaViewSet,
    ManutencaoFrotaViewSet,
    TabelaFreteViewSet,
    ValidacaoCargaViewSet,
    EntregaViewSet,
    ComprovanteEntregaViewSet,
    ComprovanteAssinaturaDownloadView,
    VeiculoFotoDownloadView,
    VeiculoDocumentoDownloadView,
    DocumentoObrigatorioVeiculoViewSet,
    FipeMarcasAPIView,
    FipeModelosAPIView,
    FipeAnosAPIView,
    FipeValorAPIView,
    AbastecimentoViewSet,
    PrecoCombustivelReferenciaViewSet,
    CombustivelResumoAPIView,
    ImportarPrecosANPAPIView,
    AbastecimentoComprovanteDownloadView,
    FornecedorViewSet,
    PlanoManutencaoViewSet,
    OrdemServicoViewSet,
    OSItemViewSet,
    ChecklistModeloViewSet,
    ChecklistExecucaoViewSet,
    ManutencaoIndicadoresAPIView,
    OSAnexoDownloadView,
    ChecklistFotoDownloadView,
    ValidacaoEvidenciaDownloadView,
    ApoliceSeguroViewSet,
    ApolicePdfDownloadView,
    SinistroViewSet,
    SinistroAnexoDownloadView,
    ConfiguracaoSegurosView,
    CustoViagemViewSet,
    CustoViagemItemViewSet,
    ConfiguracaoRentabilidadeView,
    RentabilidadeIndicadoresView,
    TCOFrotaView,
    CustoViagemItemComprovanteDownloadView
)

router = DefaultRouter()
router.register(r'veiculos', VeiculoViewSet, basename='veiculo')
router.register(r'rotas', RotaViewSet, basename='rota')
router.register(r'manutencoes', ManutencaoFrotaViewSet, basename='manutencao')
router.register(r'fretes', TabelaFreteViewSet, basename='frete')
router.register(r'validacoes', ValidacaoCargaViewSet, basename='validacao')
router.register(r'entregas', EntregaViewSet, basename='entrega')
router.register(r'comprovantes', ComprovanteEntregaViewSet, basename='comprovante')
router.register(r'documentos-obrigatorios', DocumentoObrigatorioVeiculoViewSet, basename='documento-obrigatorio')
router.register(r'abastecimentos', AbastecimentoViewSet, basename='abastecimento')
router.register(r'combustivel/precos-referencia', PrecoCombustivelReferenciaViewSet, basename='preco-referencia')
router.register(r'fornecedores', FornecedorViewSet, basename='fornecedor')
router.register(r'planos-manutencao', PlanoManutencaoViewSet, basename='plano-manutencao')
router.register(r'ordens-servico', OrdemServicoViewSet, basename='ordem-servico')
router.register(r'os-itens', OSItemViewSet, basename='os-item')
router.register(r'checklists-modelos', ChecklistModeloViewSet, basename='checklist-modelo')
router.register(r'checklists', ChecklistExecucaoViewSet, basename='checklist')
router.register(r'apolices', ApoliceSeguroViewSet, basename='apolice')
router.register(r'apolices-seguro', ApoliceSeguroViewSet, basename='apolice-seguro')
router.register(r'sinistros', SinistroViewSet, basename='sinistro')
router.register(r'custos-viagem', CustoViagemViewSet, basename='custo-viagem')
router.register(r'custos-viagem-itens', CustoViagemItemViewSet, basename='custo-viagem-item')

app_name = 'logistica'

urlpatterns = [
    path('', LogisticaTemplateView.as_view(), name='index'),
    path('campo/', RedirectView.as_view(url='/campo/', permanent=False), name='campo'),
    path('app/', RedirectView.as_view(url='/campo/', permanent=False), name='app_campo'),
    path('api/comprovantes/<int:pk>/assinatura/', ComprovanteAssinaturaDownloadView.as_view(), name='download_assinatura_comprovante'),
    path('api/veiculos/fotos/<int:pk>/arquivo/', VeiculoFotoDownloadView.as_view(), {'tipo': 'arquivo'}, name='veiculo_foto_arquivo'),
    path('api/veiculos/fotos/<int:pk>/miniatura/', VeiculoFotoDownloadView.as_view(), {'tipo': 'miniatura'}, name='veiculo_foto_miniatura'),
    path('api/veiculos/documentos/<int:pk>/arquivo/', VeiculoDocumentoDownloadView.as_view(), name='veiculo_documento_arquivo'),
    path('api/abastecimentos/<int:pk>/comprovante/', AbastecimentoComprovanteDownloadView.as_view(), name='download_comprovante_abastecimento'),
    path('api/combustivel/resumo/', CombustivelResumoAPIView.as_view(), name='combustivel_resumo'),
    path('api/combustivel/importar-anp/', ImportarPrecosANPAPIView.as_view(), name='combustivel_importar_anp'),
    path('api/fipe/marcas/', FipeMarcasAPIView.as_view(), name='fipe_marcas'),
    path('api/fipe/modelos/', FipeModelosAPIView.as_view(), name='fipe_modelos'),
    path('api/fipe/anos/', FipeAnosAPIView.as_view(), name='fipe_anos'),
    path('api/fipe/valor/', FipeValorAPIView.as_view(), name='fipe_valor'),
    path('api/manutencao/indicadores/', ManutencaoIndicadoresAPIView.as_view(), name='manutencao_indicadores'),
    path('api/ordens-servico/anexos/<int:pk>/download/', OSAnexoDownloadView.as_view(), name='download_anexo_os'),
    path('api/checklists/<int:pk>/foto/', ChecklistFotoDownloadView.as_view(), name='download_foto_checklist'),
    path('api/validacoes/evidencias/<int:pk>/download/', ValidacaoEvidenciaDownloadView.as_view(), name='download_evidencia_validacao'),
    path('api/apolices/<int:pk>/pdf/', ApolicePdfDownloadView.as_view(), name='download_pdf_apolice'),
    path('api/sinistros/anexos/<int:pk>/arquivo/', SinistroAnexoDownloadView.as_view(), name='download_anexo_sinistro'),
    path('api/seguros/configuracao/', ConfiguracaoSegurosView.as_view(), name='seguros_configuracao'),
    path('api/rentabilidade/', RentabilidadeIndicadoresView.as_view(), name='rentabilidade_indicadores'),
    path('api/rentabilidade/tco/', TCOFrotaView.as_view(), name='rentabilidade_tco'),
    path('api/rentabilidade/configuracao/', ConfiguracaoRentabilidadeView.as_view(), name='rentabilidade_configuracao'),
    path('api/custos-viagem-itens/<int:pk>/comprovante/', CustoViagemItemComprovanteDownloadView.as_view(), name='download_comprovante_custo_item'),
    path('api/', include(router.urls)),
]

