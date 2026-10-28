"""
Views e ViewSets do Portal B2B do Cliente Final (Sprint 12B).

Implementa:
- Isolamento estrito de cliente e tenant em todas as consultas (B2BQuerysetMixin).
- Prevenção ativa de IDOR em todas as rotas (404 para dados de outro cliente/tenant).
- Controle de papéis (COMPRADOR, FINANCEIRO, LEITOR, administrador_cliente).
- MFA TOTP obrigatória para consultas e downloads financeiros.
- Degradação graciosa por módulos ('b2b', 'financeiro', 'fiscal') respondendo MODULO_INATIVO.
- Tenant SUSPENSO em somente leitura (escritas bloqueadas com ASSINATURA_INATIVA).
- Reposição em 1 clique idempotente com avaliação de crédito.
- Downloads assinados efêmeros de uso único (5 minutos).
- Gestão de equipe pelo administrador do cliente.
"""
import logging
from decimal import Decimal
from django.db import models, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views import View
from django.contrib.auth import login, logout, get_user_model
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.guards import (
    assert_modulo,
    assert_tenant_writable,
    ModuloInativoError,
    AssinaturaInativaError,
)
from clientes.models import Cliente, UsuarioClienteB2B, FechamentoFaturaEstadia
from vendas.models import Venda
from faturamento.models import FaturaCobranca
from produtos.models import Cilindro, MovimentacaoCilindro, LoteEnvase
from fiscal.models import DocumentoFiscal
from financeiro.models import ParcelaFinanceira

from portal_b2b.mixins import B2BQuerysetMixin, B2BSecurityHeadersMixin
from portal_b2b.permissions import (
    IsB2BAuthenticated,
    IsCompradorRole,
    IsFinanceiroRole,
    IsAdminCliente,
    RequiresMFAIfFinanceiro,
    RequiresModuloFinanceiro,
    RequiresModuloFiscal,
)
from portal_b2b.serializers import (
    B2BVendaSerializer,
    B2BFaturaSerializer,
    B2BCilindroSerializer,
    B2BPerfilClienteSerializer,
    B2BSolicitacaoReposicaoSerializer,
    B2BSolicitacaoReposicaoInputSerializer,
    B2BNotificacaoSerializer,
    B2BUsuarioClienteB2BSerializer,
    B2BConviteInputSerializer,
    B2BAceiteConviteSerializer,
)
from portal_b2b.selectors.cilindros import get_cilindros_em_posse, get_historico_comodato_fiscal
from portal_b2b.selectors.financeiro import get_parcelas_cliente, get_faturas_estadia_cliente
from portal_b2b.selectors.fiscal import get_documentos_fiscais_cliente
from portal_b2b.selectors.entregas import get_historico_pedidos, get_status_entregas
from portal_b2b.download_service import gerar_link_download, processar_download_documento
from portal_b2b.reposicao_service import solicitar_reposicao_um_clique
from portal_b2b.notificacao_service import gerar_notificacoes_reteste, gerar_notificacoes_boletos
from portal_b2b.auth import (
    PortalB2BBackend,
    gerar_convite_b2b,
    aceitar_convite_b2b,
    tem_mfa_configurada,
    configurar_totp,
    confirmar_dispositivo_totp,
    verificar_totp,
    revogar_acesso_b2b,
    aceitar_termo_b2b,
    registrar_log_acesso,
)
from portal_b2b.models import SolicitacaoReposicao, NotificacaoB2B, LogAcessoB2B
from portal_b2b.conf import termo_versao

logger = logging.getLogger(__name__)
User = get_user_model()


# ==============================================================================
# ViewSets da API REST
# ==============================================================================

class B2BVendaViewSet(B2BQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Consulta de pedidos e vendas do cliente autenticado."""
    queryset = Venda.unscoped.all()
    permission_classes = [permissions.IsAuthenticated, IsB2BAuthenticated]
    serializer_class = B2BVendaSerializer


class B2BFaturaViewSet(B2BQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Consulta de faturas com validação de módulo financeiro e MFA para papel financeiro."""
    queryset = FaturaCobranca.unscoped.all()
    permission_classes = [
        permissions.IsAuthenticated,
        IsB2BAuthenticated,
        RequiresModuloFinanceiro,
        RequiresMFAIfFinanceiro,
    ]
    serializer_class = B2BFaturaSerializer


class B2BCilindroViewSet(B2BQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Consulta de cilindros em posse física do cliente.
    Ação 'laudo-quimico' gera link de download assinado e efêmero com auditoria.
    """
    queryset = Cilindro.unscoped.all()
    permission_classes = [permissions.IsAuthenticated, IsB2BAuthenticated]
    serializer_class = B2BCilindroSerializer

    @action(detail=True, methods=['get', 'post'], url_path='laudo-quimico')
    def laudo_quimico(self, request, pk=None):
        cilindro = self.get_object()
        cliente = request.cliente_b2b
        tenant = request.tenant

        # Valida se o cilindro esteve ou está com o cliente
        teve_entrega = MovimentacaoCilindro.unscoped.filter(
            tenant=tenant, cilindro=cilindro, cliente=cliente
        ).exists()

        if not teve_entrega and cilindro.cliente_posse_atual != cliente:
            raise Http404("Cilindro não pertence ao histórico do cliente.")

        mov = MovimentacaoCilindro.unscoped.filter(
            cilindro=cilindro,
            cliente=cliente,
            tenant=tenant
        ).order_by('-registrado_em', '-id').first()

        lote = None
        arquivo_laudo = None
        nome_arquivo = f"laudo_cilindro_{cilindro.numero_serie_ogiva}.pdf"

        if mov:
            if mov.envase_cilindro and mov.envase_cilindro.lote:
                lote = mov.envase_cilindro.lote
            elif mov.recebimento_externo and mov.recebimento_externo.laudo_pdf:
                arquivo_laudo = mov.recebimento_externo.laudo_pdf
                nome_arquivo = f"laudo_recebimento_{mov.recebimento_externo.lote_fornecedor}.pdf"
            elif mov.lote_envase:
                lote = LoteEnvase.unscoped.filter(
                    tenant=tenant,
                    codigo_lote=mov.lote_envase
                ).first()

        if not lote and not arquivo_laudo:
            if cilindro.envase_atual and cilindro.envase_atual.lote:
                lote = cilindro.envase_atual.lote
            elif cilindro.recebimento_externo_atual and cilindro.recebimento_externo_atual.laudo_pdf:
                arquivo_laudo = cilindro.recebimento_externo_atual.laudo_pdf

        if lote:
            nome_arquivo = f"laudo_lote_{lote.codigo_lote}.pdf"
            if lote.laudo_pdf:
                arquivo_laudo = lote.laudo_pdf

        if not arquivo_laudo and not lote:
            return Response(
                {"detail": "Nenhum lote químico ou laudo homologado encontrado para a carga deste cilindro."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Se solicitado explicitamente via JSON ou POST (Sprint 12B - URL assinada)
        if request.method == 'POST' or 'application/json' in request.headers.get('accept', '') or request.query_params.get('format') == 'json':
            download_url = gerar_link_download(
                tenant=tenant,
                cliente=cliente,
                tipo_documento='LAUDO_LOTE',
                recurso_tipo='Cilindro',
                recurso_id=cilindro.id,
                usuario_b2b=request.vinculo_b2b,
                request=request
            )
            return Response({
                'cilindro_id': cilindro.id,
                'numero_serie': cilindro.numero_serie_ogiva,
                'download_url': download_url,
                'validade_segundos': 300,
            })

        # Download direto com streaming ou HttpResponse
        if arquivo_laudo:
            from django.http import FileResponse
            response = FileResponse(arquivo_laudo.open('rb'), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{nome_arquivo}"'
            return response

        if lote:
            from portal_b2b.services import gerar_laudo_quimico_pdf
            pdf_buffer = gerar_laudo_quimico_pdf(cilindro, lote, mov, cliente)
            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{nome_arquivo}"'
            return response


class B2BReposicaoViewSet(B2BQuerysetMixin, viewsets.ModelViewSet):
    """
    Solicitação de reposição em 1 clique.
    Papel LEITOR bloqueado (403). Idempotente por chave_idempotencia.
    """
    queryset = SolicitacaoReposicao.unscoped.all()
    permission_classes = [permissions.IsAuthenticated, IsB2BAuthenticated, IsCompradorRole]
    serializer_class = B2BSolicitacaoReposicaoSerializer

    def create(self, request, *args, **kwargs):
        input_serializer = B2BSolicitacaoReposicaoInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        data = input_serializer.validated_data
        solicitacao, criada_agora = solicitar_reposicao_um_clique(
            tenant=request.tenant,
            cliente=request.cliente_b2b,
            usuario_b2b=request.vinculo_b2b,
            itens_solicitados=data['itens'],
            chave_idempotencia=data['chave_idempotencia'],
            observacoes=data.get('observacoes', ''),
            request=request
        )

        serializer = self.get_serializer(solicitacao)
        status_code = status.HTTP_201_CREATED if criada_agora else status.HTTP_200_OK
        return Response(serializer.data, status=status_code)


class B2BFinanceiroAPIView(B2BSecurityHeadersMixin, APIView):
    """Consulta consolidada de dados financeiros (parcelas abertas, pagas, faturas de estadia)."""
    permission_classes = [
        permissions.IsAuthenticated,
        IsB2BAuthenticated,
        RequiresModuloFinanceiro,
        IsFinanceiroRole,
        RequiresMFAIfFinanceiro,
    ]

    def get(self, request):
        tenant = request.tenant
        cliente = request.cliente_b2b
        parcelas_data = get_parcelas_cliente(tenant, cliente)
        faturas_estadia = get_faturas_estadia_cliente(tenant, cliente)

        return Response({
            'parcelas': parcelas_data,
            'faturas_estadia': faturas_estadia,
        })


class B2BFiscalAPIView(B2BSecurityHeadersMixin, APIView):
    """Consulta de documentos fiscais autorizados (NF-e, DANFE, XML)."""
    permission_classes = [
        permissions.IsAuthenticated,
        IsB2BAuthenticated,
        RequiresModuloFiscal,
        IsFinanceiroRole,
        RequiresMFAIfFinanceiro,
    ]

    def get(self, request):
        tenant = request.tenant
        cliente = request.cliente_b2b
        documentos = get_documentos_fiscais_cliente(tenant, cliente)
        return Response({'documentos_fiscais': documentos})


class B2BEntregasAPIView(B2BSecurityHeadersMixin, APIView):
    """Consulta de entregas e paradas ativas com link de rastreamento da Sprint 12A."""
    permission_classes = [permissions.IsAuthenticated, IsB2BAuthenticated]

    def get(self, request):
        tenant = request.tenant
        cliente = request.cliente_b2b
        entregas = get_status_entregas(tenant, cliente)
        pedidos = get_historico_pedidos(tenant, cliente)
        return Response({
            'entregas': entregas,
            'pedidos_recentes': pedidos[:10],
        })


class B2BNotificacoesAPIView(B2BSecurityHeadersMixin, APIView):
    """Consulta e geração sob demanda de notificações de reteste e boletos a vencer."""
    permission_classes = [permissions.IsAuthenticated, IsB2BAuthenticated]

    def get(self, request):
        tenant = request.tenant
        cliente = request.cliente_b2b

        # Dispara varredura sob demanda de reteste e boletos
        gerar_notificacoes_reteste(tenant, cliente)
        gerar_notificacoes_boletos(tenant, cliente)

        notifs = NotificacaoB2B.objects.filter(
            tenant=tenant,
            cliente=cliente,
            canal='PORTAL'
        ).order_by('-criado_em')[:50]

        serializer = B2BNotificacaoSerializer(notifs, many=True)
        return Response(serializer.data)


class B2BEquipeViewSet(B2BQuerysetMixin, viewsets.ModelViewSet):
    """Gerenciamento da equipe pelo administrador do cliente."""
    queryset = UsuarioClienteB2B.unscoped.all()
    permission_classes = [permissions.IsAuthenticated, IsB2BAuthenticated, IsAdminCliente]
    serializer_class = B2BUsuarioClienteB2BSerializer

    def get_queryset(self):
        user = self.request.user
        vinculo = getattr(user, 'vinculo_b2b', None)
        if not vinculo or not vinculo.ativo:
            return UsuarioClienteB2B.objects.none()
        return UsuarioClienteB2B.objects.filter(
            tenant=vinculo.tenant,
            cliente=vinculo.cliente
        ).select_related('user', 'cliente')

    @action(detail=False, methods=['post'], url_path='convidar')
    def convidar(self, request):
        input_serializer = B2BConviteInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        tenant = request.tenant
        cliente = request.cliente_b2b

        with transaction.atomic():
            novo_user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'email': data['email'],
                    'first_name': data.get('nome', ''),
                    'is_active': True,
                }
            )
            if not created and UsuarioClienteB2B.objects.filter(tenant=tenant, user=novo_user).exists():
                raise ValidationError("Este usuário já possui acesso configurado nesta empresa.")

            novo_vinculo = UsuarioClienteB2B.objects.create(
                tenant=tenant,
                cliente=cliente,
                user=novo_user,
                cargo=data.get('cargo', ''),
                telefone_contato=data.get('telefone_contato', ''),
                papel=data['papel'],
                administrador_cliente=data.get('administrador_cliente', False),
                ativo=True,
            )

            convite, token_claro = gerar_convite_b2b(
                usuario_b2b=novo_vinculo,
                criado_por=request.user,
                request=request
            )

        link_convite = f"/portal-b2b/convite/{token_claro}/"
        return Response({
            'usuario_id': novo_vinculo.id,
            'email': data['email'],
            'link_convite': link_convite,
            'expira_em': convite.expira_em.isoformat(),
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='revogar')
    def revogar(self, request, pk=None):
        vinculo = self.get_object()
        if vinculo.user == request.user:
            raise ValidationError("Não é permitido revogar o próprio acesso.")

        revogar_acesso_b2b(vinculo, revogado_por=request.user, request=request)
        return Response({'success': True, 'detail': 'Acesso revogado com sucesso.'})


class B2BPerfilView(B2BQuerysetMixin, APIView):
    """Retorna o perfil consolidado do cliente B2B autenticado."""
    permission_classes = [permissions.IsAuthenticated, IsB2BAuthenticated]

    def get(self, request):
        cliente = request.cliente_b2b
        tenant = request.tenant
        vinculo = request.vinculo_b2b

        cilindros_em_posse = Cilindro.unscoped.filter(
            cliente_posse_atual=cliente,
            tenant=tenant
        ).count()

        faturas_abertas_qs = FaturaCobranca.unscoped.filter(
            models.Q(cliente=cliente) | models.Q(venda__cliente=cliente) | models.Q(estadia__cliente=cliente),
            status__in=['ABERTA', 'VENCIDA'],
            tenant=tenant
        ).distinct()

        faturas_abertas_count = faturas_abertas_qs.count()
        valor_total_aberto = sum((f.valor for f in faturas_abertas_qs), Decimal('0.00'))

        data = {
            'cliente_id': cliente.id,
            'cliente_nome': cliente.nome,
            'cnpj': cliente.cnpj,
            'logradouro': f"{cliente.endereco}, {cliente.numero or 'S/N'}",
            'cidade': cliente.cidade,
            'estado': cliente.estado,
            'telefone': cliente.telefone,
            'email_financeiro': cliente.email_financeiro,
            'usuario_nome': request.user.get_full_name() or request.user.username,
            'usuario_email': request.user.email,
            'cargo': vinculo.cargo,
            'papel': vinculo.papel,
            'administrador_cliente': vinculo.administrador_cliente,
            'total_cilindros_em_posse': cilindros_em_posse,
            'total_faturas_abertas': faturas_abertas_count,
            'valor_total_aberto': valor_total_aberto,
        }

        serializer = B2BPerfilClienteSerializer(data)
        return Response(serializer.data)


# ==============================================================================
# Endpoint de Download Seguro e Efêmero
# ==============================================================================

class B2BDownloadView(APIView):
    """
    Processa URLs assinadas de uso único (single-use) para download de documentos.
    Acesso aberto via token criptográfico com validação estrita no payload.
    """
    permission_classes = []
    authentication_classes = []

    def get(self, request, token):
        return processar_download_documento(token, request=request)


# ==============================================================================
# Views Web Mobile-First (HTML)
# ==============================================================================

class B2BLoginView(View):
    template_name = 'portal_b2b/login.html'

    def get(self, request):
        if request.user.is_authenticated and getattr(request.user, 'vinculo_b2b', None):
            return redirect('portal_b2b:dashboard')
        return render(request, self.template_name)

    def post(self, request):
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        backend = PortalB2BBackend()
        user = backend.authenticate(request, username=username, password=password)

        if not user:
            return render(request, self.template_name, {
                'error': 'Usuário ou senha inválidos, ou acesso bloqueado temporariamente por excesso de tentativas.'
            }, status=401)

        vinculo = user.vinculo_b2b
        login(request, user, backend='portal_b2b.auth.PortalB2BBackend')

        # Se for papel FINANCEIRO, exige verificação TOTP
        if vinculo.mfa_obrigatoria:
            request.session['b2b_mfa_verified'] = False
            return redirect('portal_b2b:mfa')

        # Se termo de uso não foi aceito
        if not vinculo.termo_aceito_em:
            return redirect('portal_b2b:termo')

        return redirect('portal_b2b:dashboard')


class B2BLogoutView(View):
    def get(self, request):
        if request.user.is_authenticated and getattr(request.user, 'vinculo_b2b', None):
            registrar_log_acesso(
                'LOGOUT',
                tenant=request.user.vinculo_b2b.tenant,
                cliente=request.user.vinculo_b2b.cliente,
                usuario_b2b=request.user.vinculo_b2b,
                request=request
            )
        logout(request)
        return redirect('portal_b2b:login')


class B2BMFAView(View):
    template_name = 'portal_b2b/mfa.html'

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('portal_b2b:login')

        tem_mfa = tem_mfa_configurada(request.user)
        otpauth_url = None
        if not tem_mfa:
            dispositivo, otpauth_url = configurar_totp(request.user)

        return render(request, self.template_name, {
            'tem_mfa': tem_mfa,
            'otpauth_url': otpauth_url,
        })

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect('portal_b2b:login')

        token = request.POST.get('token', '').strip()
        tem_mfa = tem_mfa_configurada(request.user)

        if not tem_mfa:
            sucesso = confirmar_dispositivo_totp(request.user, token, request=request)
        else:
            sucesso = verificar_totp(request.user, token, request=request)

        if sucesso:
            request.session['b2b_mfa_verified'] = True
            return redirect('portal_b2b:dashboard')

        return render(request, self.template_name, {
            'error': 'Código TOTP inválido ou expirado. Tente novamente.',
            'tem_mfa': tem_mfa,
        }, status=400)


class B2BTermoView(View):
    template_name = 'portal_b2b/termo.html'

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('portal_b2b:login')
        return render(request, self.template_name, {'termo_versao': termo_versao()})

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect('portal_b2b:login')
        vinculo = getattr(request.user, 'vinculo_b2b', None)
        if vinculo:
            aceitar_termo_b2b(vinculo, request=request)
        return redirect('portal_b2b:dashboard')


class B2BConviteAceiteView(View):
    template_name = 'portal_b2b/aceitar_convite.html'

    def get(self, request, token):
        return render(request, self.template_name, {'token': token})

    def post(self, request, token):
        senha = request.POST.get('senha', '')
        senha_confirm = request.POST.get('senha_confirmacao', '')

        if senha != senha_confirm:
            return render(request, self.template_name, {
                'token': token,
                'error': 'As senhas informadas não coincidem.'
            }, status=400)

        try:
            aceitar_convite_b2b(token, senha, request=request)
            return render(request, self.template_name, {
                'sucesso': True,
                'mensagem': 'Senha configurada com sucesso! Você já pode efetuar login no Portal B2B.'
            })
        except Exception as err:
            return render(request, self.template_name, {
                'token': token,
                'error': str(err)
            }, status=400)


class B2BDashboardView(View):
    template_name = 'portal_b2b/dashboard.html'

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('portal_b2b:login')

        vinculo = getattr(request.user, 'vinculo_b2b', None)
        if not vinculo or not vinculo.ativo:
            logout(request)
            return redirect('portal_b2b:login')

        if vinculo.mfa_obrigatoria and not request.session.get('b2b_mfa_verified'):
            return redirect('portal_b2b:mfa')

        if not vinculo.termo_aceito_em:
            return redirect('portal_b2b:termo')

        tenant = vinculo.tenant
        cliente = vinculo.cliente

        # Carrega dados consolidando cilindros, entregas e faturas
        cilindros = get_cilindros_em_posse(tenant, cliente)
        entregas = get_status_entregas(tenant, cliente)
        reteste_alertas = [c for c in cilindros if c['status_reteste'] in ('RETESTE_VENCENDO', 'RETESTE_VENCIDO')]

        financeiro_disponivel = False
        parcelas_abertas = []
        try:
            assert_modulo(tenant, 'financeiro')
            financeiro_disponivel = True
            p_data = get_parcelas_cliente(tenant, cliente)
            parcelas_abertas = p_data.get('abertas', [])[:5]
        except Exception:
            pass

        return render(request, self.template_name, {
            'vinculo': vinculo,
            'cliente': cliente,
            'cilindros': cilindros[:10],
            'total_cilindros': len(cilindros),
            'reteste_alertas': reteste_alertas,
            'entregas': entregas[:5],
            'financeiro_disponivel': financeiro_disponivel,
            'parcelas_abertas': parcelas_abertas,
        })
