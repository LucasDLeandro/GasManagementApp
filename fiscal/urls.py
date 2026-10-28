from django.urls import path, include
from rest_framework.routers import DefaultRouter
from fiscal.views import (
    ConfiguracaoFiscalFilialViewSet,
    RegraTributariaViewSet,
    DocumentoFiscalViewSet,
    TarefaInutilizacaoNumeracaoViewSet,
    MovimentoComodatoFiscalViewSet,
    ConfiguracaoMDFeViewSet,
    DocumentoFiscalEntradaViewSet,
    ApuracaoImpostoViewSet,
    OrdemRecargaTerceiroViewSet,
)

from fiscal.views_ui import FiscalDashboardView

app_name = 'fiscal'

router = DefaultRouter()
router.register(r'configuracoes', ConfiguracaoFiscalFilialViewSet, basename='configuracao-fiscal')
router.register(r'regras-tributarias', RegraTributariaViewSet, basename='regra-tributaria')
router.register(r'documentos', DocumentoFiscalViewSet, basename='documento-fiscal')
router.register(r'inutilizacoes', TarefaInutilizacaoNumeracaoViewSet, basename='inutilizacao-numeracao')
router.register(r'movimentos-comodato', MovimentoComodatoFiscalViewSet, basename='movimento-comodato')
router.register(r'configuracoes-mdfe', ConfiguracaoMDFeViewSet, basename='configuracao-mdfe')
router.register(r'documentos-entrada', DocumentoFiscalEntradaViewSet, basename='documento-entrada')
router.register(r'apuracoes', ApuracaoImpostoViewSet, basename='apuracao-imposto')
router.register(r'ordens-recarga', OrdemRecargaTerceiroViewSet, basename='ordem-recarga')

urlpatterns = [
    path('painel/', FiscalDashboardView.as_view(), name='index'),
    path('api/', include(router.urls)),
    path('', include(router.urls)),
]
