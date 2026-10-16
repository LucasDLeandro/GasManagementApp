from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProdutoViewSet,
    CilindroViewSet,
    EnvaseCilindroViewSet,
    InspecaoPreEnvaseViewSet,
    RecebimentoCilindroCheioViewSet,
    RegistrarEnvaseAPIView,
    RegistrarEnvaseBateladaAPIView,
    ValidarCilindroRampaAPIView,
    EtiquetasColarinhoAPIView,
    ReceberCilindroCheioAPIView,
    DownloadLaudoLoteView,
    DownloadLaudoRecebimentoView,
    ProdutoTemplateView,
    RecallAnvisaTemplateView,
    PassaporteConformidadeView,
    PassaporteSanitarioPublicoView,
    PassaporteLaudoPublicoView,
    EtiquetaCascoView,
    EtiquetaColarinhoView,
    LotesAnvisaListAPIView,
    LoteRecallAPIView,
    LoteEnvaseViewSet,
    RecallCampanhaViewSet,
    ItemRecallClienteViewSet,
    SincronizarMovimentacoesOfflineAPIView,
)


router = DefaultRouter()
router.register(r'api/cilindros', CilindroViewSet, basename='cilindro-api')
router.register(r'api/envases', EnvaseCilindroViewSet, basename='envase-api')
router.register(r'api/inspecoes', InspecaoPreEnvaseViewSet, basename='inspecao-api')
router.register(r'api/recebimentos-fornecedor', RecebimentoCilindroCheioViewSet, basename='recebimento-fornecedor-api')
router.register(r'api/lotes', LoteEnvaseViewSet, basename='lote-api')
router.register(r'api/campanhas-recall', RecallCampanhaViewSet, basename='campanha-recall-api')
router.register(r'api/itens-recall', ItemRecallClienteViewSet, basename='item-recall-api')
router.register(r'api', ProdutoViewSet, basename='produto-api')

app_name = 'produtos'

urlpatterns = [
    # Rota para a view HTML do frontend de produtos
    path('', ProdutoTemplateView.as_view(), name='index'),

    # Passaporte Público de Conformidade Normativa & Sanitária (Fase 1 e Fase Final)
    path('passaporte/<str:codigo_qr>/', PassaporteSanitarioPublicoView.as_view(), name='passaporte_conformidade'),
    path('passaporte/<str:identificador>/laudo/', PassaporteLaudoPublicoView.as_view(), name='passaporte_laudo'),

    # Impressão de Etiquetas Térmicas (Casco 60x40mm e Colarinho IN 129/2022)
    path('cilindros/<int:pk>/etiqueta-casco/', EtiquetaCascoView.as_view(), name='etiqueta_casco'),
    path('cilindros/<int:pk>/etiqueta-colarinho/', EtiquetaColarinhoView.as_view(), name='etiqueta_colarinho_cilindro'),
    path('lotes/<int:pk>/etiqueta-colarinho/', EtiquetaColarinhoView.as_view(), name='etiqueta_colarinho_lote'),

    # Rota para a tela de Auditoria & Recall ANVISA em 1 Clique
    path('anvisa/recall/', RecallAnvisaTemplateView.as_view(), name='recall_anvisa'),

    # Endpoints operacionais de rampa e fornecedor
    path('api/envases/validar-cilindro/', ValidarCilindroRampaAPIView.as_view(), name='validar_cilindro_rampa'),
    path('api/envases/registrar/', RegistrarEnvaseAPIView.as_view(), name='registrar_envase'),
    path('api/envases/batelada/', RegistrarEnvaseBateladaAPIView.as_view(), name='registrar_envase_batelada'),
    path('api/envases/etiquetas-colarinho/', EtiquetasColarinhoAPIView.as_view(), name='etiquetas_colarinho'),
    path('api/recebimentos-fornecedor/registrar/', ReceberCilindroCheioAPIView.as_view(), name='receber_cilindro_cheio'),
    path('api/movimentacoes/sync-offline/', SincronizarMovimentacoesOfflineAPIView.as_view(), name='sync_offline_produtos'),

    # Download seguro e autenticado de laudos PDF (com validação estrita de tenant)
    path('api/lotes-anvisa/<int:pk>/laudo/', DownloadLaudoLoteView.as_view(), name='download_laudo_lote'),
    path('api/recebimentos-fornecedor/<int:pk>/laudo/', DownloadLaudoRecebimentoView.as_view(), name='download_laudo_recebimento'),

    # Endpoints da Rastreabilidade e Recall ANVISA
    path('api/lotes-anvisa/', LotesAnvisaListAPIView.as_view(), name='lotes_anvisa_list'),
    path('api/lotes-anvisa/recall/', LoteRecallAPIView.as_view(), name='lote_recall'),

    # Rotas padrão da API registradas no router
    path('', include(router.urls)),
]
