import uuid
import logging
from decimal import Decimal
from rest_framework import viewsets, status, permissions

logger = logging.getLogger(__name__)
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError as DRFValidationError
from PIL import Image

from django.views import View
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.http import HttpResponse, FileResponse, Http404, JsonResponse
from django.core.files.base import ContentFile
from django.db import models
import base64

from django.core.exceptions import PermissionDenied
from core.mixins import TenantViewSetMixin
from core.tenancy import get_current_tenant
from core.permissions import (
    resolve_request_membership,
    IsTenantMember,
    IsTenantAdminOrGerente,
    RequiresModuleLogistica
)

def validar_upload_imagem(file, max_mb=5):
    if file.size > max_mb * 1024 * 1024:
        raise DRFValidationError({'imagem': [f"Tamanho do arquivo excede o limite de {max_mb} MB."]})
    
    ext = file.name.split('.')[-1].lower() if '.' in file.name else ''
    if ext not in ['jpg', 'jpeg', 'png', 'webp']:
        raise DRFValidationError({'imagem': [f"Extensão .{ext} não permitida. Use JPEG, PNG ou WEBP."]})
    
    try:
        file.seek(0)
        img = Image.open(file)
        img.verify()
        file.seek(0)
        format_name = (img.format or '').upper()
        if format_name not in ['JPEG', 'PNG', 'WEBP']:
            raise DRFValidationError({'imagem': [f"Conteúdo MIME inválido: formato real é {format_name}."]})
    except Exception:
        raise DRFValidationError({'imagem': ["Arquivo corrompido ou formato de imagem inválido."]})

def validar_upload_documento(file, max_mb=10):
    if file.size > max_mb * 1024 * 1024:
        raise DRFValidationError({'arquivo': [f"Tamanho do arquivo excede o limite de {max_mb} MB."]})
    
    ext = file.name.split('.')[-1].lower() if '.' in file.name else ''
    allowed_exts = ['pdf', 'jpg', 'jpeg', 'png', 'webp']
    if ext not in allowed_exts:
        raise DRFValidationError({'arquivo': [f"Extensão .{ext} não permitida. Use PDF ou imagem (JPG/PNG/WEBP)."]})
    
    file.seek(0)
    header = file.read(8)
    file.seek(0)
    if ext == 'pdf' and not header.startswith(b'%PDF'):
        raise DRFValidationError({'arquivo': ["Arquivo não é um PDF válido (cabeçalho incompatível)."]})

def _obter_ip_cliente(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')

from .models import (
    Veiculo,
    VeiculoFoto,
    VeiculoDocumento,
    DocumentoObrigatorioVeiculo,
    VeiculoValorFipe,
    LogExcecaoOperacionalVeiculo,
    Rota,
    ManutencaoFrota,
    TabelaFrete,
    ValidacaoCarga,
    ValidacaoCargaEvidencia,
    ConfiguracaoValidacaoCarga,
    Entrega,
    ComprovanteEntrega,
    Abastecimento,
    PrecoCombustivelReferencia,
    ConfiguracaoCombustivelFrota,
    Fornecedor,
    PlanoManutencao,
    OrdemServico,
    OSItem,
    OSAnexo,
    ChecklistModelo,
    ChecklistExecucao,
    ApoliceSeguro,
    ApoliceCobertura,
    ApoliceVeiculo,
    ConfiguracaoSeguros,
    Sinistro,
    SinistroEvento,
    SinistroAnexo,
    SinistroItemCarga,
    ConfiguracaoRentabilidade,
    CustoViagem,
    CustoViagemItem,
    TabelaFreteInterno,
    AlocacaoMotoristaVeiculo,
    CapacidadeVeiculoTipoCilindro,
    Motorista,
    RegraIncompatibilidadeCarga,
    LiberacaoCarga,
    ParadaEntrega,
    TokenRastreio,
    TrajetoEntrega,
    CoordenadaRastreamento,
)
from .serializers import (
    VeiculoSerializer,
    VeiculoFotoSerializer,
    VeiculoDocumentoSerializer,
    DocumentoObrigatorioVeiculoSerializer,
    VeiculoValorFipeSerializer,
    LogExcecaoOperacionalVeiculoSerializer,
    RotaSerializer,
    ManutencaoFrotaSerializer,
    TabelaFreteSerializer,
    ValidacaoCargaSerializer,
    ValidacaoCargaEvidenciaSerializer,
    ConfiguracaoValidacaoCargaSerializer,
    EntregaSerializer,
    ComprovanteEntregaSerializer,
    AbastecimentoSerializer,
    PrecoCombustivelReferenciaSerializer,
    ConfiguracaoCombustivelFrotaSerializer,
    FornecedorSerializer,
    PlanoManutencaoSerializer,
    OrdemServicoSerializer,
    OSItemSerializer,
    OSAnexoSerializer,
    ChecklistModeloSerializer,
    ChecklistExecucaoSerializer,
    ApoliceSeguroSerializer,
    ApoliceCoberturaSerializer,
    ApoliceVeiculoSerializer,
    ConfiguracaoSegurosSerializer,
    SinistroSerializer,
    SinistroEventoSerializer,
    SinistroAnexoSerializer,
    SinistroItemCargaSerializer,
    ConfiguracaoRentabilidadeSerializer,
    CustoViagemSerializer,
    CustoViagemItemSerializer,
    TabelaFreteInternoSerializer,
    AlocacaoMotoristaVeiculoSerializer,
    MargemVeiculoInputSerializer,
    TCOVeiculoInputSerializer,
    CapacidadeVeiculoTipoCilindroSerializer,
    MotoristaSerializer,
    RegraIncompatibilidadeCargaSerializer,
    LiberacaoCargaSerializer,
    ParadaEntregaSerializer,
    TokenRastreioSerializer,
    TrajetoEntregaSerializer,
)
from vendas.models import ItemVenda
from produtos.models import Cilindro
from clientes.models import Cliente
from produtos.services import registrar_entrega_cilindro, registrar_recolha_cilindro
from .services import (
    validar_capacidade_veiculo_entrega,
    gerar_romaneio_carga_antt_pdf,
    gerar_ficha_emergencia_antt_pdf,
    gerar_envelope_transporte_antt_pdf,
    veiculo_apto_para_operar,
    criar_validacao_carga,
    aprovar_validacao_carga,
    rejeitar_validacao_carga,
    aplicar_efeitos_validacao,
    obter_relatorio_divergencias,
    criar_sinistro,
    transicionar_status_sinistro,
    vincular_ou_criar_os_sinistro,
    processar_ajuste_estoque_sinistro_carga,
    liberar_veiculo_sinistrado,
    obter_indicadores_sinistralidade,
    estimar_custo_combustivel_pre_saida,
    calcular_rateios_viagem,
    apurar_receita_frete_entrega,
    verificar_alerta_averbacao,
    verificar_alerta_baixa_ocupacao,
    consolidar_custo_viagem,
    obter_indicadores_rentabilidade,
    obter_tco_frota,
    gerar_csv_rentabilidade
)
from .services.fipe import (
    obter_marcas_fipe,
    obter_modelos_fipe,
    obter_anos_fipe,
    obter_valor_fipe,
    obter_valor_por_codigo_fipe
)
from .services.manutencao import (
    calcular_indicadores_manutencao,
    processar_alertas_manutencao
)

class LogisticaTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'logistica/index.html'

    def dispatch(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None) or get_current_tenant()
        if not (request.user.is_superuser or (tenant and tenant.tem_modulo_distribuicao)):
            raise PermissionDenied("Acesso negado: Seu plano não contempla os Módulos de Distribuição e Logística.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        tenant = get_current_tenant()
        if tenant:
            motoristas_qs = User.objects.filter(
                memberships__tenant=tenant,
                memberships__ativo=True,
                is_active=True
            ).distinct().order_by('first_name', 'username')
            context['motoristas'] = motoristas_qs
        else:
            context['motoristas'] = User.objects.filter(is_active=True).order_by('first_name', 'username')
        return context

class AppCampoView(LoginRequiredMixin, TemplateView):
    """
    Superfície Mobile / PWA dedicada ao Motorista de Campo (Fase 4).
    Acesso direto via /campo/ com suporte offline-first, pre-flight sync e auditoria ANTT/LGPD.
    """
    template_name = 'logistica/app_campo.html'

    def dispatch(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None) or get_current_tenant()
        if not (request.user.is_superuser or (tenant and tenant.tem_modulo_distribuicao)):
            raise PermissionDenied("Acesso negado: Seu plano não contempla os Módulos de Distribuição e Logística.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        tenant = get_current_tenant()
        context['tenant'] = tenant
        context['user'] = user
        membership = getattr(self.request, 'membership', None)
        context['papel'] = membership.papel if membership else ('ADMIN' if user.is_superuser else '')
        if user.is_authenticated:
            try:
                from rest_framework_simplejwt.tokens import RefreshToken
                refresh = RefreshToken.for_user(user)
                context['jwt_access_token'] = str(refresh.access_token)
            except Exception:
                pass
        return context

class VeiculoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Veiculo.unscoped.all()
    serializer_class = VeiculoSerializer
    permission_classes = [IsAuthenticated, RequiresModuleLogistica]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

    @action(detail=True, methods=['get', 'post'], url_path='fotos')
    def fotos(self, request, pk=None):
        veiculo = self.get_object()
        if request.method == 'GET':
            fotos = veiculo.fotos.all().order_by('-principal', '-criado_em')
            return Response(VeiculoFotoSerializer(fotos, many=True, context={'request': request}).data)
        
        # POST: Upload de foto
        imagem = request.FILES.get('imagem')
        if not imagem:
            return Response({'imagem': ['Arquivo de imagem obrigatório.']}, status=status.HTTP_400_BAD_REQUEST)
        
        validar_upload_imagem(imagem, max_mb=5)
        tipo = request.data.get('tipo', 'Outra')
        principal = str(request.data.get('principal', '')).lower() in ('true', '1')
        
        foto = VeiculoFoto(
            veiculo=veiculo,
            imagem=imagem,
            tipo=tipo,
            principal=principal,
            enviada_por=request.user,
            tenant=veiculo.tenant
        )
        foto.save()
        return Response(VeiculoFotoSerializer(foto, context={'request': request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete', 'patch'], url_path=r'fotos/(?P<foto_id>\d+)')
    def gerenciar_foto(self, request, pk=None, foto_id=None):
        veiculo = self.get_object()
        foto = veiculo.fotos.filter(id=foto_id).first()
        if not foto:
            return Response({'error': 'Foto não encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        
        if request.method == 'DELETE':
            foto.delete()
            return Response({'status': 'Foto excluída com sucesso.'})
        
        # PATCH
        if 'principal' in request.data:
            foto.principal = str(request.data.get('principal')).lower() in ('true', '1')
        if 'tipo' in request.data:
            foto.tipo = request.data.get('tipo')
        foto.save()
        return Response(VeiculoFotoSerializer(foto, context={'request': request}).data)

    @action(detail=True, methods=['get', 'post'], url_path='documentos')
    def documentos(self, request, pk=None):
        veiculo = self.get_object()
        if request.method == 'GET':
            docs = veiculo.documentos.all().order_by('vencimento')
            return Response(VeiculoDocumentoSerializer(docs, many=True, context={'request': request}).data)
        
        tipo = request.data.get('tipo')
        if not tipo:
            return Response({'tipo': ['Tipo de documento é obrigatório.']}, status=status.HTTP_400_BAD_REQUEST)
        
        arquivo = request.FILES.get('arquivo')
        if arquivo:
            validar_upload_documento(arquivo, max_mb=10)
        
        doc = VeiculoDocumento(
            veiculo=veiculo,
            tipo=tipo,
            numero=request.data.get('numero', ''),
            emissao=request.data.get('emissao') or None,
            vencimento=request.data.get('vencimento') or None,
            arquivo=arquivo,
            observacoes=request.data.get('observacoes', ''),
            ativo=str(request.data.get('ativo', 'true')).lower() in ('true', '1'),
            enviado_por=request.user,
            tenant=veiculo.tenant
        )
        doc.save()
        return Response(VeiculoDocumentoSerializer(doc, context={'request': request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete', 'patch'], url_path=r'documentos/(?P<doc_id>\d+)')
    def gerenciar_documento(self, request, pk=None, doc_id=None):
        veiculo = self.get_object()
        doc = veiculo.documentos.filter(id=doc_id).first()
        if not doc:
            return Response({'error': 'Documento não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        
        if request.method == 'DELETE':
            doc.delete()
            return Response({'status': 'Documento excluído com sucesso.'})
        
        # PATCH
        for field in ['tipo', 'numero', 'observacoes']:
            if field in request.data:
                setattr(doc, field, request.data[field])
        if 'emissao' in request.data:
            doc.emissao = request.data['emissao'] or None
        if 'vencimento' in request.data:
            doc.vencimento = request.data['vencimento'] or None
        if 'ativo' in request.data:
            doc.ativo = str(request.data['ativo']).lower() in ('true', '1')
        if 'arquivo' in request.FILES:
            validar_upload_documento(request.FILES['arquivo'], max_mb=10)
            doc.arquivo = request.FILES['arquivo']
        doc.save()
        return Response(VeiculoDocumentoSerializer(doc, context={'request': request}).data)

    @action(detail=False, methods=['get'], url_path='pendencias-documentos')
    def pendencias_documentos(self, request):
        tenant = get_current_tenant()
        qs = self.get_queryset()
        
        docs_obrigatorios_qs = DocumentoObrigatorioVeiculo.objects.filter(tenant=tenant, ativo=True)
        if docs_obrigatorios_qs.exists():
            obrigatorios_tipos = list(docs_obrigatorios_qs.values_list('tipo_documento', flat=True))
        else:
            obrigatorios_tipos = ['CRLV', 'RNTRC', 'CIPP/CIV (produtos perigosos)']
        
        pendencias = []
        for v in qs:
            docs = v.documentos.filter(ativo=True)
            tipos_existentes = set(docs.values_list('tipo', flat=True))
            
            docs_vencidos = [d for d in docs if d.situacao == 'Vencido']
            docs_vencendo = [d for d in docs if d.situacao == 'Vence em até 30 dias']
            faltantes = [tipo for tipo in obrigatorios_tipos if tipo not in tipos_existentes]
            
            if docs_vencidos or docs_vencendo or faltantes or v.status_ativo != 'Ativo':
                pendencias.append({
                    'veiculo_id': v.id,
                    'placa': v.placa,
                    'modelo': v.modelo,
                    'status_ativo': v.status_ativo,
                    'vencidos': [{'tipo': d.tipo, 'vencimento': d.vencimento} for d in docs_vencidos],
                    'vencendo': [{'tipo': d.tipo, 'vencimento': d.vencimento, 'dias': d.dias_para_vencer} for d in docs_vencendo],
                    'faltantes': faltantes,
                })
        
        return Response({
            'total_veiculos': qs.count(),
            'veiculos_com_pendencia': len(pendencias),
            'pendencias': pendencias
        })

    @action(detail=True, methods=['post'], url_path='atualizar-fipe')
    def atualizar_fipe(self, request, pk=None):
        veiculo = self.get_object()
        codigo = veiculo.fipe_codigo or request.data.get('fipe_codigo')
        ano = veiculo.fipe_ano_codigo or request.data.get('fipe_ano_codigo')
        tipo = veiculo.fipe_tipo or request.data.get('fipe_tipo', 'carros')
        marca = veiculo.fipe_marca_codigo or request.data.get('fipe_marca_codigo')
        modelo = veiculo.fipe_modelo_codigo or request.data.get('fipe_modelo_codigo')
        
        dados = None
        if codigo:
            dados = obter_valor_por_codigo_fipe(codigo, ano)
        elif marca and modelo and ano:
            dados = obter_valor_fipe(tipo, marca, modelo, ano)
        
        if not dados or 'erro' in dados:
            return Response({
                'sucesso': False,
                'mensagem': dados.get('erro', 'Não foi possível consultar os dados da Tabela FIPE no momento.') if dados else 'Dados insuficientes para consulta FIPE (informe código/ano ou tipo/marca/modelo/ano).'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        from .services.fipe import parse_fipe_valor
        novo_valor = parse_fipe_valor(dados.get('valorFipe') or dados.get('Valor') or dados.get('priceHistory', [{}])[0].get('price'))
        mes_ref = dados.get('mesReferencia') or dados.get('MesReferencia') or dados.get('referenceTable') or timezone.now().strftime('%m/%Y')
        
        if novo_valor is not None:
            veiculo.fipe_valor = novo_valor
            veiculo.fipe_mes_referencia = mes_ref
            veiculo.fipe_atualizado_em = timezone.now()
            if dados.get('codeFipe'):
                veiculo.fipe_codigo = dados.get('codeFipe')
            veiculo.save()
            
            VeiculoValorFipe.objects.create(
                veiculo=veiculo,
                mes_referencia=mes_ref,
                valor=novo_valor,
                tenant=veiculo.tenant
            )
        
        return Response({
            'sucesso': True,
            'mensagem': 'Valor FIPE atualizado com sucesso!',
            'fipe_valor': float(veiculo.fipe_valor) if veiculo.fipe_valor else None,
            'fipe_mes_referencia': veiculo.fipe_mes_referencia,
            'valor_mercado_estimado': float(veiculo.valor_mercado_estimado) if veiculo.valor_mercado_estimado else None,
            'veiculo': VeiculoSerializer(veiculo, context={'request': request}).data
        })

    @action(detail=True, methods=['get'], url_path='historico-fipe')
    def historico_fipe(self, request, pk=None):
        veiculo = self.get_object()
        historico = veiculo.historico_fipe.all().order_by('-criado_em')
        return Response(VeiculoValorFipeSerializer(historico, many=True).data)

    @action(detail=True, methods=['get'], url_path='aptidao')
    def aptidao(self, request, pk=None):
        veiculo = self.get_object()
        tenant = get_current_tenant()
        apto, motivos = veiculo_apto_para_operar(veiculo, tenant=tenant)
        return Response({
            'veiculo_id': veiculo.id,
            'placa': veiculo.placa,
            'apto': apto,
            'motivos': motivos
        })

class RotaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Rota.unscoped.all()
    serializer_class = RotaSerializer
    permission_classes = [IsAuthenticated, RequiresModuleLogistica]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

class ManutencaoFrotaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = ManutencaoFrota.unscoped.all()
    serializer_class = ManutencaoFrotaSerializer
    permission_classes = [IsAuthenticated]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

class TabelaFreteViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = TabelaFrete.unscoped.all()
    serializer_class = TabelaFreteSerializer
    permission_classes = [IsAuthenticated]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

class ValidacaoCargaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = ValidacaoCarga.unscoped.all()
    serializer_class = ValidacaoCargaSerializer
    permission_classes = [IsAuthenticated]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

    def get_queryset(self):
        qs = super().get_queryset()
        entrega_id = self.request.query_params.get('entrega', None)
        if entrega_id:
            qs = qs.filter(entrega_id=entrega_id)
        venda_id = self.request.query_params.get('venda', None)
        if venda_id:
            qs = qs.filter(venda_id=venda_id)
        status_param = self.request.query_params.get('status', None)
        if status_param:
            qs = qs.filter(status=status_param)
        if self.request.query_params.get('pendente') in ('1', 'true', 'True'):
            qs = qs.filter(status='Pendente de Aprovação')
        return qs.order_by('-data_hora')

    def create(self, request, *args, **kwargs):
        venda_id = request.data.get('venda')
        produto_id = request.data.get('produto')
        entrega_id = request.data.get('entrega')
        motivo = request.data.get('motivo', 'Outro')
        categoria_item = request.data.get('categoria_item', 'Cheio')
        justificativa = request.data.get('justificativa', '')
        etapa_logistica = request.data.get('etapa_logistica', 'Separação / Envase')
        valida_anterior_id = request.data.get('valida_anterior')
        autorizar_sobrecarga = str(request.data.get('autorizar_sobrecarga', '')).lower() in ('true', '1')
        justificativa_sobrecarga = request.data.get('justificativa_sobrecarga', '')

        if not venda_id or not produto_id:
            return Response(
                {'error': 'Campos obrigatórios ausentes: venda e produto devem ser informados.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        tenant = get_current_tenant()
        from vendas.models import Venda
        from produtos.models import Produto

        venda = Venda.objects.filter(pk=venda_id).first()
        if not venda:
            return Response({'error': f"Pedido/Venda #{venda_id} não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        produto = Produto.objects.filter(pk=produto_id).first()
        if not produto:
            return Response({'error': f"Produto #{produto_id} não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        entrega = None
        if entrega_id:
            entrega = Entrega.objects.filter(pk=entrega_id).first()
        elif hasattr(venda, 'entrega') and venda.entrega:
            entrega = venda.entrega

        valida_anterior = None
        if valida_anterior_id:
            valida_anterior = ValidacaoCarga.objects.filter(pk=valida_anterior_id).first()

        qtd_conferida = request.data.get('quantidade_conferida')
        qtd_esperada = request.data.get('quantidade_esperada')

        # Fallback legado: se vier quantidade_alterada (+/-) sem conferida
        if qtd_conferida is None and request.data.get('quantidade_alterada') is not None:
            try:
                ajuste = Decimal(str(request.data.get('quantidade_alterada')))
                item = ItemVenda.objects.filter(venda=venda, produto=produto).first()
                qtd_esperada = Decimal(str(item.quantidade)) if item else Decimal('0.00')
                qtd_conferida = qtd_esperada + ajuste
            except Exception:
                return Response({'error': 'Valor de quantidade_alterada inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        if qtd_conferida is None:
            return Response(
                {'error': 'A quantidade conferida deve ser informada.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        evidencias = request.FILES.getlist('evidencias')
        if not evidencias:
            evidencias = request.FILES.getlist('foto')
            if not evidencias and 'arquivo' in request.FILES:
                evidencias = [request.FILES['arquivo']]

        try:
            validacao = criar_validacao_carga(
                venda=venda,
                produto=produto,
                quantidade_conferida=qtd_conferida,
                motivo=motivo,
                categoria_item=categoria_item,
                quantidade_esperada=qtd_esperada,
                justificativa=justificativa,
                etapa_logistica=etapa_logistica,
                entrega=entrega,
                criado_por=request.user,
                dispositivo_ip=_obter_ip_cliente(request),
                valida_anterior=valida_anterior,
                evidencias=evidencias,
                autorizar_sobrecarga=autorizar_sobrecarga,
                justificativa_sobrecarga=justificativa_sobrecarga,
                tenant=tenant
            )
            serializer = self.get_serializer(validacao)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e), 'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        return Response(
            {'error': 'Validações de carga são imutáveis e não podem ser editadas diretamente. Para correções, crie uma nova validação informando valida_anterior.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def partial_update(self, request, *args, **kwargs):
        return Response(
            {'error': 'Validações de carga são imutáveis e não podem ser editadas diretamente.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def destroy(self, request, *args, **kwargs):
        return Response(
            {'error': 'Validações de carga são registros auditáveis e não podem ser excluídas.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=True, methods=['post'], url_path='aprovar')
    def aprovar(self, request, pk=None):
        validacao = self.get_object()
        observacao = request.data.get('observacao', '')
        autorizar_sobrecarga = str(request.data.get('autorizar_sobrecarga', '')).lower() in ('true', '1')
        justificativa_sobrecarga = request.data.get('justificativa_sobrecarga', '')

        try:
            val_aprovada = aprovar_validacao_carga(
                validacao,
                aprovador=request.user,
                observacao=observacao,
                autorizar_sobrecarga=autorizar_sobrecarga,
                justificativa_sobrecarga=justificativa_sobrecarga
            )
            serializer = self.get_serializer(val_aprovada)
            return Response({
                'mensagem': 'Validação aprovada com sucesso.',
                'validacao': serializer.data
            })
        except Exception as e:
            return Response({'error': str(e), 'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='rejeitar')
    def rejeitar(self, request, pk=None):
        validacao = self.get_object()
        observacao = request.data.get('observacao', '')

        try:
            val_rejeitada = rejeitar_validacao_carga(
                validacao,
                rejeitador=request.user,
                observacao=observacao
            )
            serializer = self.get_serializer(val_rejeitada)
            return Response({
                'mensagem': 'Validação rejeitada.',
                'validacao': serializer.data
            })
        except Exception as e:
            return Response({'error': str(e), 'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='adicionar-evidencia')
    def adicionar_evidencia(self, request, pk=None):
        validacao = self.get_object()
        arquivo = request.FILES.get('arquivo') or request.FILES.get('foto')
        if not arquivo:
            return Response({'error': 'Nenhum arquivo enviado.'}, status=status.HTTP_400_BAD_REQUEST)

        descricao = request.data.get('descricao', '')
        try:
            evidencia = ValidacaoCargaEvidencia.objects.create(
                tenant=validacao.tenant,
                validacao=validacao,
                arquivo=arquivo,
                descricao=descricao
            )
            serializer = ValidacaoCargaEvidenciaSerializer(evidencia)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='pendentes-aprovacao')
    def pendentes_aprovacao(self, request):
        qs = self.get_queryset().filter(status='Pendente de Aprovação')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='relatorio-divergencias')
    def relatorio_divergencias(self, request):
        tenant = get_current_tenant()
        data_inicio = request.query_params.get('inicio')
        data_fim = request.query_params.get('fim')
        dados = obter_relatorio_divergencias(tenant, data_inicio=data_inicio, data_fim=data_fim)
        return Response(dados)

    @action(detail=False, methods=['get', 'put', 'patch'], url_path='configuracao')
    def configuracao(self, request):
        tenant = get_current_tenant()
        config = ConfiguracaoValidacaoCarga.get_para_tenant(tenant)
        if request.method in ['PUT', 'PATCH']:
            serializer = ConfiguracaoValidacaoCargaSerializer(config, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer = ConfiguracaoValidacaoCargaSerializer(config)
        return Response(serializer.data)

class ComprovanteEntregaViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ComprovanteEntrega.unscoped.all()
    serializer_class = ComprovanteEntregaSerializer
    permission_classes = [IsAuthenticated]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

    def get_queryset(self):
        qs = super().get_queryset()
        entrega_id = self.request.query_params.get('entrega', None)
        if entrega_id:
            qs = qs.filter(entrega_id=entrega_id)
        return qs

from core.permissions import IsMotoristaOrAdmin

class EntregaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Entrega.unscoped.all()
    serializer_class = EntregaSerializer
    permission_classes = [IsAuthenticated, RequiresModuleLogistica]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)

    def get_permissions(self):
        if self.action in ['concluir_romaneio', 'comprovante_assinatura', 'pacote_rota', 'minha_rota_ativa']:
            return [IsMotoristaOrAdmin(), RequiresModuleLogistica()]
        return [permission() for permission in self.permission_classes]

    def _validar_aptidao_veiculo(self, veiculo, request_data, entrega=None):
        if not veiculo:
            return
        tenant = get_current_tenant()
        apto, motivos = veiculo_apto_para_operar(veiculo, tenant=tenant)
        if not apto:
            justificativa = request_data.get('justificativa_excecao')
            user = self.request.user
            is_gestor = user.is_superuser or user.memberships.filter(
                tenant=tenant, papel__in=['ADMIN', 'GERENTE'], ativo=True
            ).exists()
            
            if is_gestor and justificativa and str(justificativa).strip():
                LogExcecaoOperacionalVeiculo.objects.create(
                    tenant=tenant,
                    veiculo=veiculo,
                    entrega=entrega,
                    usuario=user,
                    motivos_bloqueio=motivos,
                    justificativa=str(justificativa).strip()
                )
            else:
                msg = f"Veículo {veiculo.placa} inapto para operar: {'; '.join(motivos)}."
                if is_gestor:
                    msg += " Como gestor, você pode prosseguir fornecendo 'justificativa_excecao'."
                raise DRFValidationError({'veiculo': [msg]})

    def perform_create(self, serializer):
        veiculo = serializer.validated_data.get('veiculo')
        if veiculo:
            self._validar_aptidao_veiculo(veiculo, self.request.data)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        instance = serializer.instance
        novo_status = serializer.validated_data.get('status', instance.status)
        novo_veiculo = serializer.validated_data.get('veiculo', instance.veiculo)
        
        veiculo_final = novo_veiculo or instance.veiculo

        if novo_status == 'Em Rota':
            if veiculo_final and veiculo_final.capacidade_carga and float(veiculo_final.capacidade_carga) > 0:
                peso = instance.peso_total_carregado
                cap = float(veiculo_final.capacidade_carga)
                if peso > cap:
                    raise DRFValidationError({
                        'non_field_errors': [
                            f"Trava de Segurança ANTT: Não é permitido iniciar rota com veículo em sobrecarga! "
                            f"Peso atual de {peso:.2f} kg excede a capacidade máxima de {cap:.2f} kg do veículo {veiculo_final.placa}."
                        ]
                    })

        if veiculo_final and (novo_veiculo != instance.veiculo or novo_status == 'Em Rota'):
            self._validar_aptidao_veiculo(veiculo_final, self.request.data, entrega=instance)

        updated_entrega = serializer.save()
        if novo_status == 'Em Rota':
            updated_entrega.vendas.filter(status__in=['Pendente', 'Em Separação']).update(status='Em Rota')
        elif novo_status == 'Concluída':
            updated_entrega.vendas.filter(status='Em Rota').update(status='Entregue')

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get('status', None)
        if status_param:
            statuses = status_param.split(',')
            qs = qs.filter(status__in=statuses)
        return qs

    @action(detail=True, methods=['get', 'post'], url_path='validar-carga')
    def validar_carga_action(self, request, pk=None):
        """Validação técnica de peso, tipo de cilindro, incompatibilidade química e documentos (Sprint 12A - Tarefa 2)."""
        entrega = self.get_object()
        from logistica.services.carga import validar_carga
        res = validar_carga(entrega)
        return Response({
            'valido': res.valido,
            'bloqueado': res.bloqueado,
            'erros_bloqueantes': res.erros_bloqueantes,
            'avisos': res.avisos,
            'peso_total_kg': float(res.peso_total_kg),
            'capacidade_veiculo_kg': float(res.capacidade_veiculo_kg),
            'percentual_peso': float(res.percentual_peso),
            'contagem_por_tipo': res.contagem_por_tipo,
            'classes_risco_presentes': res.classes_risco_presentes,
            'detalhes': res.detalhes,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='liberar-carga')
    def liberar_carga_action(self, request, pk=None):
        """Liberação formal e auditada de saída com pendências de validação (Sprint 12A - Tarefa 2)."""
        entrega = self.get_object()
        motivo = request.data.get('motivo', '')
        from logistica.services.carga import liberar_carga_bloqueada
        from django.core.exceptions import ValidationError as DjangoValidationError, PermissionDenied as DjangoPermissionDenied
        try:
            lib = liberar_carga_bloqueada(entrega=entrega, responsavel=request.user, motivo=motivo)
            return Response({
                'mensagem': 'Carga liberada com sucesso e saída para rota autorizada.',
                'liberacao_id': lib.id,
                'status_entrega': entrega.status,
            }, status=status.HTTP_200_OK)
        except DjangoPermissionDenied as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='despachar-rota')
    def despachar_rota_action(self, request, pk=None):
        """Transiciona a entrega para 'Em Rota' após verificar validação ou liberação prévia (Sprint 12A - Tarefa 2)."""
        entrega = self.get_object()
        from logistica.services.carga import despachar_entrega_para_rota
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            despachar_entrega_para_rota(entrega=entrega, usuario=request.user)
            return Response({
                'mensagem': 'Entrega despachada para rota com sucesso.',
                'entrega_id': entrega.id,
                'status': entrega.status,
            }, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='notificar-saida')
    def notificar_saida_action(self, request, pk=None):
        """Dispara link de rastreio aos clientes por canais com consentimento (Sprint 12A - Tarefa 8)."""
        entrega = self.get_object()
        from logistica.services.rastreio_publico_service import notificar_saida_entrega_com_consentimento
        notifs = notificar_saida_entrega_com_consentimento(entrega)
        return Response({
            'total_notificacoes': len(notifs),
            'notificacoes': notifs
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='trajeto')
    def trajeto_action(self, request, pk=None):
        """Retorna o trajeto simplificado em menos de 300 ms (Sprint 12A - Tarefa 6)."""
        entrega = self.get_object()
        from logistica.services.rastreamento_service import consolidar_trajeto_simplificado
        trajeto = consolidar_trajeto_simplificado(entrega.id)
        from .serializers import TrajetoEntregaSerializer
        return Response(TrajetoEntregaSerializer(trajeto).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'post'], url_path='romaneio-bilateral')
    def romaneio_bilateral(self, request, pk=None):
        """
        Endpoint do Romaneio Bilateral (Full-for-Empty):
        GET: Consulta cilindros cheios entregues, vazios recolhidos, peso real e saldos de comodato.
        POST: Bipagem de QR code para entrega de cheios ou recolha de vazios.
        """
        entrega = self.get_object()

        if request.method == 'POST':
            acao = request.data.get('acao') # 'entregar' ou 'recolher'
            codigo_qr = request.data.get('codigo_qr')
            cliente_id = request.data.get('cliente_id')
            observacao = request.data.get('observacao', '')
            client_uuid_val = request.data.get('client_uuid')
            
            try:
                client_uuid = uuid.UUID(str(client_uuid_val)) if client_uuid_val else uuid.uuid4()
            except Exception:
                client_uuid = uuid.uuid4()

            if not codigo_qr:
                return Response({'error': 'Código QR do cilindro é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

            cilindro = Cilindro.objects.filter(codigo_qr=codigo_qr).first()
            if not cilindro:
                return Response({'error': f'Cilindro com código QR "{codigo_qr}" não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

            cliente = None
            if cliente_id:
                cliente = Cliente.objects.filter(id=cliente_id).first()
            elif entrega.vendas.exists():
                cliente = entrega.vendas.first().cliente

            try:
                if acao == 'entregar':
                    if not cliente:
                        return Response({'error': 'Cliente de destino não identificado para a entrega.'}, status=status.HTTP_400_BAD_REQUEST)
                    cil, mov = registrar_entrega_cilindro(
                        cilindro_id=cilindro.id,
                        cliente=cliente,
                        entrega=entrega,
                        usuario=request.user,
                        ocorrido_em=timezone.now(),
                        client_uuid=client_uuid
                    )
                    msg = f"Cilindro {cil.numero_serie_ogiva} ({cil.gas_dedicado.sigla}) entregue em {cliente.nome}."
                elif acao == 'recolher':
                    cil, mov = registrar_recolha_cilindro(
                        cilindro_id=cilindro.id,
                        cliente=cliente or cilindro.cliente_posse_atual,
                        entrega=entrega,
                        usuario=request.user,
                        ocorrido_em=timezone.now(),
                        client_uuid=client_uuid,
                        observacao=observacao
                    )
                    msg = f"Cilindro {cil.numero_serie_ogiva} recolhido vazio com sucesso."
                else:
                    return Response({'error': 'Ação inválida. Use "entregar" ou "recolher".'}, status=status.HTTP_400_BAD_REQUEST)

                return Response({
                    'status': 'sucesso',
                    'mensagem': msg,
                    'movimentacao_id': mov.id,
                    'peso_carregado_kg': entrega.peso_total_carregado,
                    'capacidade_disponivel_kg': entrega.capacidade_disponivel,
                    'percentual_lotacao': entrega.percentual_lotacao
                })
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # GET: Retorna estrutura completa do Romaneio Bilateral
        movs = entrega.movimentacoes_cilindros.select_related('cilindro__gas_dedicado', 'cliente').all()
        entregues = []
        recolhidos = []
        for m in movs:
            item_info = {
                'id': m.id,
                'codigo_qr': m.cilindro.codigo_qr,
                'numero_serie': m.cilindro.numero_serie_ogiva,
                'gas': m.cilindro.gas_dedicado.sigla,
                'gas_nome': m.cilindro.gas_dedicado.nome,
                'tara': float(m.cilindro.tara_real_kg),
                'cliente': m.cliente.nome if m.cliente else 'N/A',
                'ocorrido_em': m.ocorrido_em.strftime('%d/%m/%Y %H:%M')
            }
            if m.tipo in ['ENTREGA_CLIENTE', 'SAIDA_ROTA']:
                entregues.append(item_info)
            elif m.tipo == 'RECOLHA_CLIENTE':
                recolhidos.append(item_info)

        clientes_map = {}
        for v in entrega.vendas.select_related('cliente').all():
            c = v.cliente
            if c.id not in clientes_map:
                saldo = Cilindro.objects.filter(cliente_posse_atual=c).count()
                clientes_map[c.id] = {
                    'id': c.id,
                    'nome': c.nome,
                    'cnpj': c.cnpj,
                    'saldo_comodato': saldo
                }

        return Response({
            'entrega_id': entrega.id,
            'status': entrega.status,
            'veiculo': str(entrega.veiculo) if entrega.veiculo else 'Sem Veículo',
            'capacidade_carga_kg': float(entrega.veiculo.capacidade_carga) if (entrega.veiculo and entrega.veiculo.capacidade_carga) else 0,
            'peso_total_carregado': entrega.peso_total_carregado,
            'capacidade_disponivel': entrega.capacidade_disponivel,
            'percentual_lotacao': entrega.percentual_lotacao,
            'cilindros_entregues': entregues,
            'cilindros_recolhidos': recolhidos,
            'clientes_comodato': list(clientes_map.values())
        })

    @action(detail=True, methods=['get', 'post'], url_path='validar-capacidade')
    def validar_capacidade(self, request, pk=None):
        """
        Valida se a carga atual ou planejada da entrega respeita a capacidade do veículo.
        """
        entrega = self.get_object()
        try:
            peso_total = validar_capacidade_veiculo_entrega(entrega)
            cap = float(entrega.veiculo.capacidade_carga) if entrega.veiculo and entrega.veiculo.capacidade_carga else 0.0
            return Response({
                'valido': True,
                'peso_total_kg': peso_total,
                'capacidade_veiculo_kg': cap,
                'percentual_lotacao': entrega.percentual_lotacao,
                'possui_peso_estimado': entrega.possui_peso_estimado,
                'mensagem': 'Carga dentro da capacidade regulamentar do veículo.'
            })
        except Exception as exc:
            return Response({
                'valido': False,
                'erro': str(exc),
                'peso_total_kg': entrega.peso_total_carregado,
                'percentual_lotacao': entrega.percentual_lotacao,
                'possui_peso_estimado': entrega.possui_peso_estimado
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='romaneio-antt-pdf')
    def romaneio_antt_pdf(self, request, pk=None):
        """
        Gera o Romaneio de Carga ANTT (Resolução nº 5.998/2022) em PDF.
        """
        entrega = self.get_object()
        pdf_bytes = gerar_romaneio_carga_antt_pdf(entrega)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="romaneio_antt_entrega_{entrega.id}.pdf"'
        return response

    @action(detail=True, methods=['get'], url_path='ficha-emergencia-pdf')
    def ficha_emergencia_pdf(self, request, pk=None):
        """
        Gera a Ficha de Emergência ANTT/ABNT NBR 7503 em PDF.
        """
        entrega = self.get_object()
        pdf_bytes = gerar_ficha_emergencia_antt_pdf(entrega)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="ficha_emergencia_entrega_{entrega.id}.pdf"'
        return response

    @action(detail=True, methods=['get'], url_path='envelope-transporte-pdf')
    def envelope_transporte_pdf(self, request, pk=None):
        """
        Gera o Envelope para Transporte ANTT (Resolução nº 5.998/2022) em PDF.
        """
        entrega = self.get_object()
        pdf_bytes = gerar_envelope_transporte_antt_pdf(entrega)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="envelope_transporte_entrega_{entrega.id}.pdf"'
        return response

    @action(detail=True, methods=['post'], url_path='concluir-romaneio')
    def concluir_romaneio(self, request, pk=None):
        """
        Finaliza a rota/romaneio de entrega e dispara webhook 'romaneio.concluido'.
        """
        entrega = self.get_object()
        entrega.status = 'Concluída'
        entrega.save(update_fields=['status'])

        # Dispara webhook para sistemas externos / ERP
        try:
            from core.webhooks import disparar_webhooks_tenant
            payload = {
                'evento': 'romaneio.concluido',
                'entrega_id': entrega.id,
                'status': 'Concluída',
                'veiculo': {
                    'placa': entrega.veiculo.placa if entrega.veiculo else None,
                    'modelo': entrega.veiculo.modelo if entrega.veiculo else None,
                    'capacidade_carga_kg': float(entrega.veiculo.capacidade_carga) if entrega.veiculo and entrega.veiculo.capacidade_carga else 0.0
                },
                'motorista': entrega.motorista.get_full_name() or entrega.motorista.username if entrega.motorista else None,
                'rota': entrega.rota.nome if entrega.rota else None,
                'peso_total_carregado_kg': float(entrega.peso_total_carregado),
                'total_entregues': entrega.movimentacoes_cilindros.filter(tipo__in=['ENTREGA_CLIENTE', 'SAIDA_ROTA']).count(),
                'total_recolhidos': entrega.movimentacoes_cilindros.filter(tipo='RECOLHA_CLIENTE').count(),
                'total_comprovantes': entrega.comprovantes.count(),
                'concluido_em': timezone.now().isoformat()
            }
            disparar_webhooks_tenant(tenant=entrega.tenant, evento='romaneio.concluido', payload=payload)
        except Exception:
            pass

        # Consolida e congela snapshot financeiro da viagem
        custo = consolidar_custo_viagem(entrega, congelar=True)
        resumo_custo = {
            'combustivel_real': float(custo.combustivel_real),
            'pedagios': float(custo.pedagios),
            'rateio_manutencao': float(custo.rateio_manutencao),
            'rateio_depreciacao': float(custo.rateio_depreciacao),
            'rateio_seguro': float(custo.rateio_seguro),
            'custo_total_real': float(custo.custo_total_real),
            'receita_frete': float(custo.receita_frete),
            'margem_bruta': float(custo.margem_bruta),
            'margem_percentual': float(custo.margem_percentual) if custo.margem_percentual is not None else None,
            'snapshot_congelado': custo.snapshot_congelado,
            'dados_incompletos': custo.dados_incompletos
        }

        return Response({
            'status': 'sucesso',
            'mensagem': f'Romaneio #{entrega.id} concluído com sucesso e notificação enviada.',
            'entrega_id': entrega.id,
            'status_entrega': entrega.status,
            'custo_viagem': resumo_custo
        })

    @action(detail=True, methods=['get', 'post'], url_path='custo-viagem')
    def custo_viagem_action(self, request, pk=None):
        """
        Consulta ou força recálculo/atualização de despesas e margem da viagem (Sprint L6).
        GET: Retorna CustoViagem consolidado ou estimativa prévia.
        POST: Atualiza campos manuais ou força recálculo se não congelado.
        """
        entrega = self.get_object()
        forcar = bool(request.data.get('forcar_recalculo', False)) if request.method == 'POST' else False
        custo = consolidar_custo_viagem(entrega, forcar_recalculo=forcar)

        if request.method == 'POST' and not custo.snapshot_congelado:
            km_real = request.data.get('km_real')
            if km_real is not None and str(km_real).strip() != '':
                custo.km_real = Decimal(str(km_real))
            rec_frete = request.data.get('receita_frete')
            if rec_frete is not None and str(rec_frete).strip() != '':
                custo.receita_frete = Decimal(str(rec_frete))
            comb_real = request.data.get('combustivel_real')
            if comb_real is not None and str(comb_real).strip() != '':
                custo.combustivel_real = Decimal(str(comb_real))
            custo.save()
            custo = consolidar_custo_viagem(entrega, forcar_recalculo=True)

        return Response(CustoViagemSerializer(custo, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='comprovante-assinatura')
    def comprovante_assinatura(self, request, pk=None):
        """
        Registra comprovante de entrega com assinatura eletrônica e hash de integridade SHA-256.
        """
        import uuid
        entrega = self.get_object()
        recebedor_nome = request.data.get('recebedor_nome')
        recebedor_documento = request.data.get('recebedor_documento')
        assinatura_base64 = request.data.get('assinatura_base64')
        movimentacao_id = request.data.get('movimentacao_id')
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')

        if not recebedor_nome or not recebedor_documento:
            return Response({'error': 'Nome e documento do recebedor são obrigatórios.'}, status=status.HTTP_400_BAD_REQUEST)

        doc_file = None
        if assinatura_base64:
            if ',' in assinatura_base64:
                assinatura_base64 = assinatura_base64.split(',', 1)[1]
            img_data = base64.b64decode(assinatura_base64)
            file_name = f"assinatura_{uuid.uuid4()}.png"
            doc_file = ContentFile(img_data, name=file_name)
        elif 'assinatura_imagem' in request.FILES:
            doc_file = request.FILES['assinatura_imagem']
        else:
            return Response({'error': 'Imagem da assinatura é obrigatória.'}, status=status.HTTP_400_BAD_REQUEST)

        mov = None
        if movimentacao_id:
            mov = entrega.movimentacoes_cilindros.filter(id=movimentacao_id).first()

        movimentacoes_ids = request.data.get('movimentacoes_ids', [])

        comprovante = ComprovanteEntrega.objects.create(
            tenant=entrega.tenant,
            entrega=entrega,
            movimentacao=mov,
            recebedor_nome=recebedor_nome,
            recebedor_documento=recebedor_documento,
            assinatura_imagem=doc_file,
            latitude=lat,
            longitude=lng,
            timestamp_captura=timezone.now()
        )

        if mov:
            comprovante.movimentacoes.add(mov)
        if movimentacoes_ids and isinstance(movimentacoes_ids, list):
            for m in entrega.movimentacoes_cilindros.filter(id__in=movimentacoes_ids):
                comprovante.movimentacoes.add(m)

        serializer = ComprovanteEntregaSerializer(comprovante)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='conferencia-saida')
    def conferencia_saida(self, request, pk=None):
        """
        Conferência de carga na saída da rota (painel e PWA):
        - GET: lista de itens esperados do romaneio, status de conferência e trava de liberação.
        - POST: registra conferência de itens com validação de divergências e liberação de saída.
        """
        entrega = self.get_object()

        if request.method == 'POST':
            itens_data = request.data.get('itens')
            if not itens_data:
                itens_data = [request.data]

            resumos = []
            for item_info in itens_data:
                venda_id = item_info.get('venda_id') or item_info.get('venda')
                produto_id = item_info.get('produto_id') or item_info.get('produto')
                qtd_conferida = item_info.get('quantidade_conferida')
                qtd_esperada = item_info.get('quantidade_esperada')
                motivo = item_info.get('motivo', 'Outro')
                justificativa = item_info.get('justificativa', '')
                categoria = item_info.get('categoria_item', 'Cheio')

                if not venda_id or not produto_id or qtd_conferida is None:
                    continue

                from vendas.models import Venda
                from produtos.models import Produto

                venda = Venda.objects.filter(pk=venda_id, tenant=entrega.tenant).first()
                produto = Produto.objects.filter(pk=produto_id, tenant=entrega.tenant).first()
                if not venda or not produto:
                    continue

                diferenca = Decimal(str(qtd_conferida)) - Decimal(str(qtd_esperada or 0))
                if diferenca != 0:
                    val = criar_validacao_carga(
                        venda=venda,
                        produto=produto,
                        quantidade_conferida=qtd_conferida,
                        quantidade_esperada=qtd_esperada,
                        motivo=motivo,
                        categoria_item=categoria,
                        justificativa=justificativa or f"Divergência de conferência na saída: esperada {qtd_esperada}, conferida {qtd_conferida}.",
                        etapa_logistica='Conferência na Saída (PWA/Painel)',
                        entrega=entrega,
                        criado_por=request.user,
                        dispositivo_ip=_obter_ip_cliente(request),
                        tenant=entrega.tenant
                    )
                    resumos.append({'produto': produto.nome, 'diferenca': float(val.diferenca), 'status': val.status})
                else:
                    resumos.append({'produto': produto.nome, 'diferenca': 0, 'status': 'Conferido OK'})

            pendentes = ValidacaoCarga.objects.filter(entrega=entrega, status='Pendente de Aprovação').count()
            saida_liberada = (pendentes == 0)

            # Se a saída estiver liberada e o operador solicitar iniciar rota
            iniciar_rota = str(request.data.get('iniciar_rota', '')).lower() in ('true', '1')
            if iniciar_rota and saida_liberada and entrega.status == 'Agendada':
                entrega.status = 'Em Rota'
                entrega.data_saida = timezone.now()
                entrega.save(update_fields=['status', 'data_saida'])

            return Response({
                'mensagem': 'Conferência de saída processada.',
                'saida_liberada': saida_liberada,
                'pendencias_aprovacao': pendentes,
                'status_entrega': entrega.status,
                'resumo_itens': resumos,
                'peso_total_kg': entrega.peso_total_carregado,
                'percentual_lotacao': entrega.percentual_lotacao
            })

        # GET: Retorna lista de itens esperados
        itens_esperados = []
        for v in entrega.vendas.exclude(status='Cancelada').prefetch_related('itens__produto', 'itens__sku'):
            for it in v.itens.all():
                p = it.produto
                ultima_val = ValidacaoCarga.objects.filter(entrega=entrega, venda=v, produto=p).order_by('-data_hora').first()
                itens_esperados.append({
                    'venda_id': v.id,
                    'cliente_nome': v.cliente.nome,
                    'produto_id': p.id if p else None,
                    'produto_nome': it.sku.nome_comercial if it.sku else (p.nome if p else 'Item'),
                    'quantidade_esperada': it.quantidade,
                    'quantidade_conferida_atual': it.quantidade if not ultima_val else float(ultima_val.quantidade_conferida),
                    'possui_divergencia': bool(ultima_val and ultima_val.diferenca != 0),
                    'ultima_validacao_status': ultima_val.status if ultima_val else None,
                    'peso_unitario_kg': float(it.peso_unitario or 0)
                })

        pendentes = ValidacaoCarga.objects.filter(entrega=entrega, status='Pendente de Aprovação').count()
        return Response({
            'entrega_id': entrega.id,
            'status_entrega': entrega.status,
            'veiculo': entrega.veiculo.placa if entrega.veiculo else None,
            'capacidade_carga_kg': float(entrega.veiculo.capacidade_carga) if entrega.veiculo and entrega.veiculo.capacidade_carga else 0.0,
            'peso_total_kg': entrega.peso_total_carregado,
            'percentual_lotacao': entrega.percentual_lotacao,
            'itens_esperados': itens_esperados,
            'saida_liberada': (pendentes == 0),
            'pendencias_aprovacao': pendentes
        })

    @action(detail=True, methods=['get', 'post'], url_path='conferencia-retorno')
    def conferencia_retorno(self, request, pk=None):
        """
        Conferência de retorno de viagem (PWA / Painel):
        - Apresenta o balanço da viagem: saiu, entregou, retornou e diferenças.
        - Diferenças não justificadas geram pendência no romaneio.
        """
        entrega = self.get_object()

        total_despachado = 0
        for v in entrega.vendas.exclude(status='Cancelada'):
            for it in v.itens.all():
                total_despachado += it.quantidade

        movs = entrega.movimentacoes_cilindros.all()
        total_entregue = movs.filter(tipo__in=['ENTREGA_CLIENTE', 'SAIDA_ENTREGA']).count()
        total_recolhido_vazio = movs.filter(tipo__in=['RECOLHA_CLIENTE', 'RETORNO_VAZIO']).count()

        vals_retorno = ValidacaoCarga.objects.filter(
            entrega=entrega,
            motivo__in=['Produto devolvido', 'Cliente recusou', 'Cilindro vazio/errado', 'Avaria no manuseio', 'Vazamento', 'Roubo/Extravio']
        )
        total_justificado_retorno = sum(abs(v.diferenca) for v in vals_retorno)

        cheios_nao_entregues = max(0, total_despachado - total_entregue)
        diferenca_nao_justificada = max(0, cheios_nao_entregues - int(total_justificado_retorno))

        if request.method == 'POST':
            return Response({
                'mensagem': 'Conferência de retorno registrada.',
                'total_despachado': total_despachado,
                'total_entregue': total_entregue,
                'total_recolhido_vazio': total_recolhido_vazio,
                'cheios_nao_entregues': cheios_nao_entregues,
                'total_justificado': float(total_justificado_retorno),
                'diferenca_pendente': diferenca_nao_justificada,
                'status': 'Em Conformidade' if diferenca_nao_justificada == 0 else 'Pendência de Ajuste'
            })

        return Response({
            'entrega_id': entrega.id,
            'status': entrega.status,
            'veiculo': entrega.veiculo.placa if entrega.veiculo else None,
            'total_despachado': total_despachado,
            'total_entregue': total_entregue,
            'total_recolhido_vazio': total_recolhido_vazio,
            'cheios_nao_entregues': cheios_nao_entregues,
            'total_justificado': float(total_justificado_retorno),
            'diferenca_pendente': diferenca_nao_justificada,
            'possui_pendencia': diferenca_nao_justificada > 0
        })

    def _gerar_pacote_rota_response(self, entrega):
        """
        Gera a estrutura do Pacote da Rota para Pre-flight Sync no IndexedDB do App de Campo:
        - Dados da entrega e veículo
        - Lista de paradas (clientes, endereços, pedidos, itens)
        - Cilindros carregados no caminhão (QR, série, status, reteste_vencido, bloqueio_sanitario, lote)
        - Saldos de comodato atuais de cada cliente da rota
        """
        # 1. Paradas da rota
        paradas = []
        clientes_ids = set()
        for idx, venda in enumerate(entrega.vendas.select_related('cliente').prefetch_related('itens__produto').all()):
            c = venda.cliente
            if c:
                clientes_ids.add(c.id)
            itens = []
            for item in venda.itens.all():
                itens.append({
                    'produto': item.produto.nome if item.produto else 'Item',
                    'quantidade': item.quantidade
                })
            comprovante_parada = entrega.comprovantes.filter(
                movimentacoes__cliente=c
            ).exists() if c else False

            paradas.append({
                'ordem': idx + 1,
                'venda_id': venda.id,
                'cliente_id': c.id if c else None,
                'cliente_nome': c.nome if c else 'Cliente Não Informado',
                'cliente_cnpj': c.cnpj if c else '',
                'cliente_endereco': f"{c.endereco or ''} - {c.cidade or ''}/{c.estado or ''}".strip(' ,-') if c else '',
                'cliente_telefone': c.telefone if c else '',
                'itens': itens,
                'status': 'Concluída' if comprovante_parada else ('Em Rota' if entrega.status == 'Em Rota' else 'Pendente')
            })

        # 2. Saldos de comodato dos clientes da rota
        saldos_comodato = {}
        for c_id in clientes_ids:
            saldos_comodato[c_id] = Cilindro.objects.filter(cliente_posse_atual_id=c_id).count()

        # 3. Cilindros carregados no caminhão
        movs = entrega.movimentacoes_cilindros.select_related(
            'cilindro__modelo', 'cilindro__gas_dedicado',
            'cilindro__envase_atual__lote', 'cilindro__recebimento_externo_atual'
        ).all()
        cilindros_caminhao = []
        cilindros_ids_vistos = set()
        for m in movs:
            cil = m.cilindro
            if cil.id in cilindros_ids_vistos:
                continue
            cilindros_ids_vistos.add(cil.id)

            num_lote = 'N/A'
            lote_valido = True
            if cil.envase_atual and cil.envase_atual.lote:
                lote = cil.envase_atual.lote
                num_lote = getattr(lote, 'codigo_lote', getattr(lote, 'numero_lote', 'N/A'))
                if lote.expirado or lote.status_qualidade not in ['APROVADO', 'LIBERADO']:
                    lote_valido = False
            elif cil.recebimento_externo_atual:
                num_lote = cil.recebimento_externo_atual.lote_fornecedor or 'N/A'

            cilindros_caminhao.append({
                'id': cil.id,
                'codigo_qr': cil.codigo_qr,
                'serie_ogiva': cil.numero_serie_ogiva,
                'gas': cil.gas_dedicado.sigla if cil.gas_dedicado else 'N/A',
                'gas_nome': cil.gas_dedicado.nome if cil.gas_dedicado else 'N/A',
                'modelo': cil.modelo.descricao if cil.modelo else 'N/A',
                'tara_kg': float(cil.tara_real_kg) if cil.tara_real_kg is not None else float(cil.modelo.tara_nominal_kg or 0),
                'status': cil.status,
                'reteste_vencido': cil.reteste_vencido,
                'data_proximo_reteste': cil.data_proximo_reteste.strftime('%d/%m/%Y') if cil.data_proximo_reteste else None,
                'bloqueio_sanitario': cil.bloqueio_sanitario,
                'motivo_bloqueio_sanitario': cil.motivo_bloqueio_sanitario or '',
                'lote': num_lote,
                'lote_valido': lote_valido,
                'movimentacao_tipo': m.tipo
            })

        # Fallback para cilindros reservados em rota no tenant se nenhum ainda vinculado
        if not cilindros_caminhao:
            for cil in Cilindro.objects.filter(status='RESERVADO_ROTA').select_related(
                'modelo', 'gas_dedicado', 'envase_atual__lote', 'recebimento_externo_atual'
            )[:50]:
                num_lote = 'N/A'
                lote_valido = True
                if cil.envase_atual and cil.envase_atual.lote:
                    lote = cil.envase_atual.lote
                    num_lote = getattr(lote, 'codigo_lote', getattr(lote, 'numero_lote', 'N/A'))
                    if lote.expirado or lote.status_qualidade not in ['APROVADO', 'LIBERADO']:
                        lote_valido = False
                elif cil.recebimento_externo_atual:
                    num_lote = cil.recebimento_externo_atual.lote_fornecedor or 'N/A'
                cilindros_caminhao.append({
                    'id': cil.id,
                    'codigo_qr': cil.codigo_qr,
                    'serie_ogiva': cil.numero_serie_ogiva,
                    'gas': cil.gas_dedicado.sigla if cil.gas_dedicado else 'N/A',
                    'gas_nome': cil.gas_dedicado.nome if cil.gas_dedicado else 'N/A',
                    'modelo': cil.modelo.descricao if cil.modelo else 'N/A',
                    'tara_kg': float(cil.tara_real_kg) if cil.tara_real_kg is not None else float(cil.modelo.tara_nominal_kg or 0),
                    'status': cil.status,
                    'reteste_vencido': cil.reteste_vencido,
                    'data_proximo_reteste': cil.data_proximo_reteste.strftime('%d/%m/%Y') if cil.data_proximo_reteste else None,
                    'bloqueio_sanitario': cil.bloqueio_sanitario,
                    'motivo_bloqueio_sanitario': cil.motivo_bloqueio_sanitario or '',
                    'lote': num_lote,
                    'lote_valido': lote_valido,
                    'movimentacao_tipo': 'SAIDA_ROTA'
                })

        return Response({
            'entrega_id': entrega.id,
            'status': entrega.status,
            'veiculo': {
                'id': entrega.veiculo.id if entrega.veiculo else None,
                'placa': entrega.veiculo.placa if entrega.veiculo else 'Sem Placa',
                'modelo': entrega.veiculo.modelo if entrega.veiculo else 'Sem Modelo',
                'capacidade_carga_kg': float(entrega.veiculo.capacidade_carga) if entrega.veiculo and entrega.veiculo.capacidade_carga else 0.0
            },
            'motorista': entrega.motorista.get_full_name() or entrega.motorista.username if entrega.motorista else 'Não atribuído',
            'rota_nome': entrega.rota.nome if entrega.rota else 'Sem Rota Definida',
            'peso_total_carregado': float(entrega.peso_total_carregado),
            'percentual_lotacao': float(entrega.percentual_lotacao),
            'possui_peso_estimado': entrega.possui_peso_estimado,
            'paradas': paradas,
            'saldos_comodato': saldos_comodato,
            'cilindros_caminhao': cilindros_caminhao,
            'gerado_em': timezone.now().isoformat()
        })

    @action(detail=True, methods=['get'], url_path='pacote-rota')
    def pacote_rota(self, request, pk=None):
        """
        Retorna o Pacote da Rota para Pre-flight Sync no IndexedDB do App de Campo:
        """
        if pk:
            entrega = self.get_queryset().filter(pk=pk).first()
            if not entrega:
                return Response({'error': 'Entrega não encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            entrega = self.get_object()
        return self._gerar_pacote_rota_response(entrega)

    @action(detail=False, methods=['get'], url_path='minha-rota-ativa')
    def minha_rota_ativa(self, request):
        """
        Retorna a rota em andamento ou mais recente para o motorista autenticado.
        """
        user = request.user
        qs = self.get_queryset()

        if user.memberships.filter(papel='MOTORISTA').exists() and not user.is_superuser:
            entrega = qs.filter(motorista=user).exclude(status__in=['Concluída', 'Cancelada']).order_by('-id').first()
            if not entrega:
                entrega = qs.filter(motorista=user).order_by('-id').first()
        else:
            entrega = qs.exclude(status__in=['Concluída', 'Cancelada']).order_by('-id').first()
            if not entrega:
                entrega = qs.order_by('-id').first()

        if not entrega:
            return Response({'mensagem': 'Nenhuma entrega encontrada para o operador.'}, status=status.HTTP_404_NOT_FOUND)

        return self._gerar_pacote_rota_response(entrega)


class ComprovanteAssinaturaDownloadView(APIView):
    """
    Endpoint seguro e autenticado para download/visualização da assinatura digital do comprovante.
    Impede acesso público desautorizado (DoD da Sprint 6).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        comprovante = ComprovanteEntrega.unscoped.filter(id=pk).select_related('tenant').first()
        if not comprovante or not comprovante.assinatura_imagem:
            raise Http404("Comprovante ou imagem de assinatura não encontrados.")

        # Validação estrita de Tenant
        current_tenant = get_current_tenant()
        if current_tenant and comprovante.tenant_id != current_tenant.id:
            raise Http404("Comprovante não encontrado para a empresa ativa.")

        response = FileResponse(comprovante.assinatura_imagem.open('rb'), content_type='image/png')
        response['Content-Disposition'] = f'inline; filename="assinatura_{comprovante.id}.png"'
        return response


class VeiculoFotoDownloadView(APIView):
    """
    Endpoint seguro e autenticado para download/visualização de fotos e miniaturas dos veículos.
    Garante isolamento de tenant.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None, tipo='arquivo'):
        foto = VeiculoFoto.objects.select_related('veiculo__tenant').filter(pk=pk).first()
        if not foto:
            raise Http404("Foto não encontrada.")

        current_tenant = get_current_tenant()
        if current_tenant and foto.veiculo.tenant_id != current_tenant.id:
            raise Http404("Foto não encontrada para a empresa ativa.")

        usar_thumb = (tipo == 'miniatura') or (request.query_params.get('thumb') in ('1', 'true', 'True'))
        arquivo = foto.miniatura if (usar_thumb and foto.miniatura) else foto.imagem
        if not arquivo:
            raise Http404("Arquivo de imagem não encontrado.")

        ext = arquivo.name.split('.')[-1].lower()
        content_type = 'image/jpeg'
        if ext == 'png':
            content_type = 'image/png'
        elif ext == 'webp':
            content_type = 'image/webp'

        try:
            response = FileResponse(arquivo.open('rb'), content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="{arquivo.name.split("/")[-1]}"'
            return response
        except Exception:
            raise Http404("Erro ao abrir arquivo de imagem.")


class VeiculoDocumentoDownloadView(APIView):
    """
    Endpoint seguro e autenticado para download/visualização de documentos confidenciais de veículos.
    Garante isolamento de tenant.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        doc = VeiculoDocumento.objects.select_related('veiculo__tenant').filter(pk=pk).first()
        if not doc or not doc.arquivo:
            raise Http404("Documento não encontrado.")

        current_tenant = get_current_tenant()
        if current_tenant and doc.veiculo.tenant_id != current_tenant.id:
            raise Http404("Documento não encontrado para a empresa ativa.")

        ext = doc.arquivo.name.split('.')[-1].lower()
        content_type = 'application/pdf' if ext == 'pdf' else (f'image/{ext}' if ext in ['png', 'jpg', 'jpeg', 'webp'] else 'application/octet-stream')

        try:
            response = FileResponse(doc.arquivo.open('rb'), content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="{doc.arquivo.name.split("/")[-1]}"'
            return response
        except Exception:
            raise Http404("Erro ao abrir arquivo do documento.")


class DocumentoObrigatorioVeiculoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = DocumentoObrigatorioVeiculo.unscoped.all()
    serializer_class = DocumentoObrigatorioVeiculoSerializer
    permission_classes = [IsAuthenticated]

    def paginate_queryset(self, queryset):
        if self.request.query_params.get('sem_paginacao') in ('1', 'true', 'True'):
            return None
        return super().paginate_queryset(queryset)


class FipeMarcasAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tipo = request.query_params.get('tipo', 'carros')
        dados = obter_marcas_fipe(tipo)
        return Response(dados)


class FipeModelosAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tipo = request.query_params.get('tipo', 'carros')
        marca = request.query_params.get('marca')
        if not marca:
            return Response({'error': 'Parâmetro marca é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)
        dados = obter_modelos_fipe(tipo, marca)
        return Response(dados)


class FipeAnosAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tipo = request.query_params.get('tipo', 'carros')
        marca = request.query_params.get('marca')
        modelo = request.query_params.get('modelo')
        if not marca or not modelo:
            return Response({'error': 'Parâmetros marca e modelo são obrigatórios.'}, status=status.HTTP_400_BAD_REQUEST)
        dados = obter_anos_fipe(tipo, marca, modelo)
        return Response(dados)


class FipeValorAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tipo = request.query_params.get('tipo', 'carros')
        marca = request.query_params.get('marca')
        modelo = request.query_params.get('modelo')
        ano = request.query_params.get('ano')
        codigo = request.query_params.get('codigo')

        if codigo:
            dados = obter_valor_por_codigo_fipe(codigo, ano)
        elif marca and modelo and ano:
            dados = obter_valor_fipe(tipo, marca, modelo, ano)
        else:
            return Response({'error': 'Parâmetros insuficientes para consulta FIPE (informe codigo ou marca, modelo e ano).'}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(dados)


# ==============================================================================
# SPRINT L2: GESTÃO DE COMBUSTÍVEL, ABASTECIMENTOS E INTEGRAÇÃO ANP
# ==============================================================================

class AbastecimentoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Abastecimento.unscoped.all()
    serializer_class = AbastecimentoSerializer
    permission_classes = [IsAuthenticated]

    def paginate_queryset(self, queryset):
        # Regra 7: listagens de histórico e abastecimento mantêm paginação padrão
        return super().paginate_queryset(queryset)

    def get_queryset(self):
        qs = super().get_queryset().select_related('veiculo', 'motorista', 'entrega')
        veiculo = self.request.query_params.get('veiculo')
        if veiculo:
            if str(veiculo).isdigit():
                qs = qs.filter(veiculo_id=int(veiculo))
            else:
                qs = qs.filter(veiculo__placa__iexact=veiculo)

        motorista = self.request.query_params.get('motorista')
        if motorista:
            qs = qs.filter(motorista_id=motorista)

        status_val = self.request.query_params.get('status_validacao')
        if status_val:
            qs = qs.filter(status_validacao=status_val)

        combustivel = self.request.query_params.get('tipo_combustivel') or self.request.query_params.get('combustivel')
        if combustivel:
            qs = qs.filter(tipo_combustivel=combustivel)

        inicio = self.request.query_params.get('data_inicio') or self.request.query_params.get('inicio')
        if inicio:
            qs = qs.filter(data_hora__date__gte=inicio)

        fim = self.request.query_params.get('data_fim') or self.request.query_params.get('fim')
        if fim:
            qs = qs.filter(data_hora__date__lte=fim)

        busca = self.request.query_params.get('busca') or self.request.query_params.get('search')
        if busca:
            qs = qs.filter(
                models.Q(posto_nome__icontains=busca) |
                models.Q(posto_cidade__icontains=busca) |
                models.Q(numero_cupom__icontains=busca) |
                models.Q(veiculo__placa__icontains=busca)
            )

        return qs.order_by('-data_hora', '-odometro_km')

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        client_uuid = serializer.validated_data.get('client_uuid')
        if client_uuid:
            existente = Abastecimento.objects.filter(tenant=tenant, client_uuid=client_uuid).first()
            if existente:
                return existente

        comprovante_file = self.request.FILES.get('comprovante')
        if comprovante_file:
            validar_upload_documento(comprovante_file, max_mb=10)

        instancia = serializer.save(tenant=tenant)
        from .services.combustivel import processar_abastecimento
        processar_abastecimento(instancia)
        instancia.save()

    def perform_update(self, serializer):
        comprovante_file = self.request.FILES.get('comprovante')
        if comprovante_file:
            validar_upload_documento(comprovante_file, max_mb=10)

        instancia = serializer.save()
        from .services.combustivel import processar_abastecimento
        processar_abastecimento(instancia)
        instancia.save()


class PrecoCombustivelReferenciaViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = PrecoCombustivelReferencia.unscoped.all()
    serializer_class = PrecoCombustivelReferenciaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        produto = self.request.query_params.get('produto')
        if produto:
            qs = qs.filter(produto=produto)
        uf = self.request.query_params.get('uf')
        if uf:
            qs = qs.filter(uf=uf.upper())
        municipio = self.request.query_params.get('municipio')
        if municipio:
            qs = qs.filter(municipio__iexact=municipio)
        return qs.order_by('-data_final', 'produto')

    @action(detail=False, methods=['get'], url_path='vigente')
    def vigente(self, request):
        tenant = get_current_tenant()
        from .services.combustivel import obter_configuracao_combustivel, obter_preco_referencia_aplicavel
        config = obter_configuracao_combustivel(tenant)

        uf = request.query_params.get('uf') or (config.uf_padrao if config else 'GO')
        municipio = request.query_params.get('municipio') or (config.municipio_padrao if config else '')

        produtos = ['Diesel S10', 'Diesel S500', 'Gasolina Comum', 'Etanol', 'GNV', 'GLP']
        resultado = {}
        for prod in produtos:
            ref = obter_preco_referencia_aplicavel(tenant, prod, uf=uf, municipio=municipio)
            if ref:
                resultado[prod] = PrecoCombustivelReferenciaSerializer(ref).data
            else:
                resultado[prod] = None

        return Response({
            'uf': uf,
            'municipio': municipio,
            'precos': resultado
        })

    @action(detail=False, methods=['get'], url_path='historico')
    def historico(self, request):
        tenant = get_current_tenant()
        produto = request.query_params.get('produto', 'Diesel S10')
        uf = request.query_params.get('uf', 'GO')
        municipio = request.query_params.get('municipio', '')

        qs = PrecoCombustivelReferencia.objects.filter(
            tenant=tenant,
            produto=produto,
            uf=uf.upper()
        )
        if municipio:
            qs = qs.filter(municipio__iexact=municipio)
        else:
            qs = qs.filter(municipio='')

        dados = list(qs.order_by('data_inicial').values(
            'data_inicial', 'data_final', 'preco_medio', 'preco_minimo', 'preco_maximo', 'fonte'
        ))
        return Response(dados)


class CombustivelResumoAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = get_current_tenant()
        inicio = request.query_params.get('inicio') or request.query_params.get('data_inicio')
        fim = request.query_params.get('fim') or request.query_params.get('data_fim')
        veiculo_id = request.query_params.get('veiculo')
        motorista_id = request.query_params.get('motorista')

        qs = Abastecimento.objects.filter(tenant=tenant)
        if inicio:
            qs = qs.filter(data_hora__date__gte=inicio)
        if fim:
            qs = qs.filter(data_hora__date__lte=fim)
        if veiculo_id:
            qs = qs.filter(veiculo_id=veiculo_id)
        if motorista_id:
            qs = qs.filter(motorista_id=motorista_id)

        total_gasto = qs.aggregate(models.Sum('valor_total'))['valor_total__sum'] or Decimal('0.00')
        total_litros = qs.exclude(tipo_combustivel='Arla 32').aggregate(models.Sum('litros'))['litros__sum'] or Decimal('0.000')
        total_arla_litros = qs.filter(tipo_combustivel='Arla 32').aggregate(models.Sum('litros'))['litros__sum'] or Decimal('0.000')
        total_arla_gasto = qs.filter(tipo_combustivel='Arla 32').aggregate(models.Sum('valor_total'))['valor_total__sum'] or Decimal('0.00')

        preco_medio_litro = (total_gasto / total_litros).quantize(Decimal('0.0001')) if total_litros > Decimal('0') else Decimal('0.0000')

        km_total = qs.exclude(tipo_combustivel='Arla 32').aggregate(models.Sum('km_rodados_desde_anterior'))['km_rodados_desde_anterior__sum'] or 0
        km_l_medio = round(Decimal(km_total) / total_litros, 2) if km_total > 0 and total_litros > Decimal('0') else None
        custo_por_km = (total_gasto / Decimal(km_total)).quantize(Decimal('0.0001')) if km_total > 0 else None

        from .services.combustivel import obter_configuracao_combustivel
        config = obter_configuracao_combustivel(tenant)
        tol_cons = config.tolerancia_consumo_pct if config else Decimal('25.00')

        veiculos_ranking = []
        veiculos_ids = qs.values_list('veiculo_id', flat=True).distinct()
        for vid in veiculos_ids:
            v_qs = qs.filter(veiculo_id=vid).exclude(tipo_combustivel='Arla 32')
            v_obj = Veiculo.objects.filter(id=vid).first()
            if not v_obj:
                continue
            v_gasto = v_qs.aggregate(models.Sum('valor_total'))['valor_total__sum'] or Decimal('0.00')
            v_litros = v_qs.aggregate(models.Sum('litros'))['litros__sum'] or Decimal('0.000')
            v_km = v_qs.aggregate(models.Sum('km_rodados_desde_anterior'))['km_rodados_desde_anterior__sum'] or 0
            v_km_l = round(Decimal(v_km) / v_litros, 2) if v_km > 0 and v_litros > Decimal('0') else None

            semaforo = 'cinza'
            if v_km_l and v_obj.consumo_referencia_km_l and v_obj.consumo_referencia_km_l > Decimal('0'):
                desvio = (v_km_l - v_obj.consumo_referencia_km_l) / v_obj.consumo_referencia_km_l * 100
                if desvio >= -tol_cons:
                    semaforo = 'verde'
                elif desvio >= -(tol_cons * Decimal('1.5')):
                    semaforo = 'ambar'
                else:
                    semaforo = 'vermelho'

            veiculos_ranking.append({
                'veiculo_id': v_obj.id,
                'placa': v_obj.placa,
                'modelo': v_obj.modelo,
                'consumo_referencia': float(v_obj.consumo_referencia_km_l) if v_obj.consumo_referencia_km_l else None,
                'gasto_total': float(v_gasto),
                'litros_totais': float(v_litros),
                'km_rodados': v_km,
                'consumo_km_l': float(v_km_l) if v_km_l else None,
                'semaforo': semaforo
            })

        veiculos_ranking.sort(key=lambda x: (x['consumo_km_l'] is not None, x['consumo_km_l'] or 0), reverse=True)

        por_combustivel = []
        for comb_choice, _ in Abastecimento.TIPO_COMBUSTIVEL_CHOICES:
            c_qs = qs.filter(tipo_combustivel=comb_choice)
            if not c_qs.exists():
                continue
            c_gasto = c_qs.aggregate(models.Sum('valor_total'))['valor_total__sum'] or Decimal('0.00')
            c_litros = c_qs.aggregate(models.Sum('litros'))['litros__sum'] or Decimal('0.000')
            c_pm = (c_gasto / c_litros).quantize(Decimal('0.0001')) if c_litros > Decimal('0') else Decimal('0.0000')

            ref_obj = PrecoCombustivelReferencia.objects.filter(
                tenant=tenant, produto=comb_choice
            ).order_by('-data_final').first()

            preco_ref_val = float(ref_obj.preco_medio) if ref_obj else None
            dif_pct = None
            if ref_obj and ref_obj.preco_medio > Decimal('0'):
                dif_pct = round(float((c_pm - ref_obj.preco_medio) / ref_obj.preco_medio * 100), 1)

            por_combustivel.append({
                'tipo': comb_choice,
                'gasto_total': float(c_gasto),
                'litros': float(c_litros),
                'preco_medio_pago': float(c_pm),
                'preco_ref_anp': preco_ref_val,
                'diferenca_pct': dif_pct,
                'anp_defasado': ref_obj.esta_defasado if ref_obj else False
            })

        anomalias_qs = qs.exclude(status_validacao='Normal').order_by('-data_hora')[:5]
        anomalias = AbastecimentoSerializer(anomalias_qs, many=True).data

        return Response({
            'total_gasto': float(total_gasto),
            'total_litros': float(total_litros),
            'total_arla_gasto': float(total_arla_gasto),
            'total_arla_litros': float(total_arla_litros),
            'preco_medio_litro': float(preco_medio_litro),
            'km_total_rodados': km_total,
            'km_l_medio_frota': float(km_l_medio) if km_l_medio else None,
            'custo_por_km_medio': float(custo_por_km) if custo_por_km else None,
            'total_abastecimentos': qs.count(),
            'total_alertas': qs.exclude(status_validacao='Normal').count(),
            'ranking_veiculos': veiculos_ranking,
            'por_combustivel': por_combustivel,
            'anomalias_recentes': anomalias,
            'atribuicao_fonte': 'Dados de Preços de Combustíveis sob Licença Creative Commons CC-BY - ANP'
        })


class ImportarPrecosANPAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant = get_current_tenant()
        user = request.user
        is_gestor = user.is_superuser or user.memberships.filter(
            tenant=tenant, papel__in=['ADMIN', 'GERENTE'], ativo=True
        ).exists()
        if not is_gestor:
            return Response(
                {'error': 'Apenas gestores da empresa podem disparar a importação de dados da ANP.'},
                status=status.HTTP_403_FORBIDDEN
            )

        uf = request.data.get('uf')
        municipio = request.data.get('municipio')
        grupo = request.data.get('grupo', 'TODOS')
        arquivo = request.FILES.get('arquivo')

        from .services.anp import (
            baixar_csv_anp,
            importar_precos_anp_de_conteudo,
            DEFAULT_ANP_URLS
        )

        total_criados = 0
        total_atualizados = 0
        total_ignorados = 0
        erros = []

        try:
            if arquivo:
                conteudo = arquivo.read()
                res = importar_precos_anp_de_conteudo(conteudo, uf_filtro=uf, municipio_filtro=municipio, tenant=tenant)
                total_criados += res['criados']
                total_atualizados += res['atualizados']
                total_ignorados += res['ignorados']
                erros.extend(res['erros'])
            else:
                urls = list(DEFAULT_ANP_URLS.items()) if grupo == 'TODOS' else [(grupo, DEFAULT_ANP_URLS.get(grupo))]
                for g_nome, u in urls:
                    if not u:
                        continue
                    try:
                        raw_bytes = baixar_csv_anp(u)
                        res = importar_precos_anp_de_conteudo(raw_bytes, uf_filtro=uf, municipio_filtro=municipio, tenant=tenant)
                        total_criados += res['criados']
                        total_atualizados += res['atualizados']
                        total_ignorados += res['ignorados']
                        erros.extend(res['erros'])
                    except Exception as e:
                        erros.append(f"Falha em {g_nome}: {str(e)}")

            return Response({
                'sucesso': True,
                'mensagem': f"Importação ANP concluída: {total_criados} criados, {total_atualizados} atualizados, {total_ignorados} ignorados.",
                'criados': total_criados,
                'atualizados': total_atualizados,
                'ignorados': total_ignorados,
                'erros': erros[:10]
            })
        except Exception as e:
            return Response({'sucesso': False, 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class AbastecimentoComprovanteDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        tenant = get_current_tenant()
        abastecimento = Abastecimento.unscoped.filter(id=pk, tenant=tenant).first()
        if not abastecimento or not abastecimento.comprovante:
            raise Http404("Comprovante não encontrado ou acesso não autorizado.")

        arquivo = abastecimento.comprovante
        try:
            arquivo.open('rb')
            content_type = 'application/pdf' if arquivo.name.lower().endswith('.pdf') else 'image/jpeg'
            response = FileResponse(arquivo, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="comprovante_{abastecimento.id}_{arquivo.name.split("/")[-1]}"'
            return response
        except Exception:
            raise Http404("Arquivo físico do comprovante não encontrado no servidor de armazenamento.")


# ==============================================================================
# SPRINT L3: MANUTENÇÃO PREVENTIVA E CORRETIVA VIEWS
# ==============================================================================

class IsGestorOuMotoristaAbertura(BasePermission):
    """
    Motorista pode listar e abrir OS (como relato de defeito / ordem inicial),
    mas apenas Gestor (Admin ou Gerente) pode alterar status, aprovar, executar,
    concluir, cancelar ou excluir ordens de serviço.
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        membership = resolve_request_membership(request)
        if not (membership and membership.ativo):
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS', 'POST'):
            return True
        return membership.papel in ('ADMIN', 'GERENTE')


class FornecedorViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Fornecedor.unscoped.all()
    serializer_class = FornecedorSerializer
    permission_classes = [IsTenantMember]

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsTenantAdminOrGerente()]
        return [IsTenantMember()]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('sem_paginacao') == '1':
            self.pagination_class = None

        ativo = self.request.query_params.get('ativo')
        if ativo is not None:
            qs = qs.filter(ativo=(ativo.lower() in ('1', 'true', 't')))

        busca = self.request.query_params.get('busca') or self.request.query_params.get('search')
        if busca:
            qs = qs.filter(
                models.Q(nome__icontains=busca) |
                models.Q(documento__icontains=busca) |
                models.Q(cidade__icontains=busca) |
                models.Q(especialidades__icontains=busca)
            )
        return qs.order_by('nome')

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        serializer.save(tenant=tenant)


class PlanoManutencaoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = PlanoManutencao.unscoped.all()
    serializer_class = PlanoManutencaoSerializer
    permission_classes = [IsTenantMember]

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsTenantAdminOrGerente()]
        return [IsTenantMember()]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('sem_paginacao') == '1':
            self.pagination_class = None

        veiculo_id = self.request.query_params.get('veiculo')
        if veiculo_id:
            qs = qs.filter(veiculo_id=veiculo_id)

        ativo = self.request.query_params.get('ativo')
        if ativo is not None:
            qs = qs.filter(ativo=(ativo.lower() in ('1', 'true', 't')))

        return qs.select_related('veiculo', 'fornecedor_preferido').order_by('veiculo__placa', 'descricao')

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        serializer.save(tenant=tenant)

    @action(detail=False, methods=['get'], url_path='vencimentos')
    def vencimentos(self, request):
        """Retorna todos os planos preventivos com status de vencimento calculado (km/dias)."""
        tenant = get_current_tenant()
        qs = PlanoManutencao.objects.filter(tenant=tenant, ativo=True).select_related('veiculo')
        hoje = timezone.localdate()
        resultado = []
        for p in qs:
            st = p.calcular_status_vencimento(data_referencia=hoje)
            resultado.append({
                'id': p.id,
                'veiculo_id': p.veiculo_id,
                'veiculo_placa': p.veiculo.placa,
                'veiculo_modelo': f"{p.veiculo.marca} {p.veiculo.modelo}",
                'descricao': p.descricao,
                'gatilho_km': p.gatilho_km,
                'gatilho_dias': p.gatilho_dias,
                'custo_estimado': float(p.custo_estimado or 0),
                'status': st['status'],
                'motivo': st['motivo'],
                'vencido': st['vencido'],
                'alerta': st['alerta'],
                'km_restantes': st['km_restantes'],
                'dias_restantes': st['dias_restantes'],
                'proximo_km': st['proximo_km'],
                'proxima_data': st['proxima_data']
            })
        return Response(resultado)

    @action(detail=False, methods=['post'], url_path='gerar-alertas')
    def gerar_alertas(self, request):
        """Dispara a rotina de varredura preventiva idempotente e geração de OS."""
        tenant = get_current_tenant()
        res = processar_alertas_manutencao(tenant)
        return Response({
            'status': 'sucesso',
            'alertas_gerados': res['alertas_gerados'],
            'os_geradas': res['os_geradas'],
            'planos_verificados': res['planos_verificados']
        })


class OrdemServicoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = OrdemServico.unscoped.all()
    serializer_class = OrdemServicoSerializer
    permission_classes = [IsGestorOuMotoristaAbertura]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('sem_paginacao') == '1':
            self.pagination_class = None

        veiculo_id = self.request.query_params.get('veiculo')
        if veiculo_id:
            qs = qs.filter(veiculo_id=veiculo_id)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        tipo_param = self.request.query_params.get('tipo')
        if tipo_param:
            qs = qs.filter(tipo=tipo_param)

        origem_param = self.request.query_params.get('origem')
        if origem_param:
            qs = qs.filter(origem=origem_param)

        prioridade_param = self.request.query_params.get('prioridade')
        if prioridade_param:
            qs = qs.filter(prioridade=prioridade_param)

        imobiliza = self.request.query_params.get('imobiliza_veiculo')
        if imobiliza is not None:
            qs = qs.filter(imobiliza_veiculo=(imobiliza.lower() in ('1', 'true', 't')))

        inicio = self.request.query_params.get('data_inicio') or self.request.query_params.get('inicio')
        if inicio:
            qs = qs.filter(data_abertura__date__gte=inicio)

        fim = self.request.query_params.get('data_fim') or self.request.query_params.get('fim')
        if fim:
            qs = qs.filter(data_abertura__date__lte=fim)

        busca = self.request.query_params.get('busca') or self.request.query_params.get('search')
        if busca:
            qs = qs.filter(
                models.Q(numero__icontains=busca) |
                models.Q(descricao_problema__icontains=busca) |
                models.Q(diagnostico__icontains=busca) |
                models.Q(veiculo__placa__icontains=busca)
            )

        return qs.select_related('veiculo', 'fornecedor', 'aprovado_por', 'plano').prefetch_related('itens', 'anexos').order_by('-data_abertura')

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        membership = resolve_request_membership(self.request)
        is_motorista = bool(membership and membership.papel == 'MOTORISTA')

        # Se for motorista reportando defeito
        if is_motorista:
            serializer.save(
                tenant=tenant,
                origem='Motorista',
                status='Aberta',
                custo_pecas=Decimal('0.00'),
                custo_mao_de_obra=Decimal('0.00'),
                custo_terceiros=Decimal('0.00'),
                custo_total=Decimal('0.00'),
                aprovado_por=None,
                aprovado_em=None
            )
        else:
            serializer.save(tenant=tenant)

    @action(detail=True, methods=['post'], url_path='aprovar')
    def aprovar(self, request, pk=None):
        membership = resolve_request_membership(request)
        if not (request.user.is_superuser or (membership and membership.papel in ('ADMIN', 'GERENTE'))):
            return Response({'error': "Apenas gestores (Admin ou Gerente) podem aprovar Ordens de Serviço."}, status=status.HTTP_403_FORBIDDEN)

        os_obj = self.get_object()
        if os_obj.status not in ('Aberta', 'Orçada'):
            return Response({'error': f"Não é possível aprovar uma OS com status '{os_obj.status}'."}, status=status.HTTP_400_BAD_REQUEST)

        os_obj.status = 'Aprovada'
        os_obj.aprovado_por = request.user
        os_obj.aprovado_em = timezone.now()
        os_obj.save()
        return Response(OrdemServicoSerializer(os_obj).data)

    @action(detail=True, methods=['post'], url_path='iniciar-execucao')
    def iniciar_execucao(self, request, pk=None):
        membership = resolve_request_membership(request)
        if not (request.user.is_superuser or (membership and membership.papel in ('ADMIN', 'GERENTE'))):
            return Response({'error': "Apenas gestores podem iniciar a execução de uma OS."}, status=status.HTTP_403_FORBIDDEN)

        os_obj = self.get_object()
        if os_obj.status != 'Aprovada':
            return Response({'error': f"A OS precisa estar 'Aprovada' para iniciar execução (status atual: {os_obj.status})."}, status=status.HTTP_400_BAD_REQUEST)

        os_obj.status = 'Em Execução'
        if not os_obj.data_entrada:
            os_obj.data_entrada = timezone.now()
        os_obj.save()
        return Response(OrdemServicoSerializer(os_obj).data)

    @action(detail=True, methods=['post'], url_path='concluir')
    def concluir(self, request, pk=None):
        membership = resolve_request_membership(request)
        if not (request.user.is_superuser or (membership and membership.papel in ('ADMIN', 'GERENTE'))):
            return Response({'error': "Apenas gestores podem concluir uma OS e homologar custos."}, status=status.HTTP_403_FORBIDDEN)

        os_obj = self.get_object()
        if os_obj.status != 'Em Execução':
            return Response({'error': f"A OS precisa estar 'Em Execução' para ser concluída (status atual: {os_obj.status})."}, status=status.HTTP_400_BAD_REQUEST)

        odometro_saida = request.data.get('odometro_saida')
        if odometro_saida is not None:
            os_obj.odometro_saida = Decimal(str(odometro_saida))
        elif not os_obj.odometro_saida:
            os_obj.odometro_saida = os_obj.veiculo.odometro_atual_km

        if 'diagnostico' in request.data:
            os_obj.diagnostico = request.data.get('diagnostico')
        if 'garantia_ate' in request.data:
            os_obj.garantia_ate = request.data.get('garantia_ate')
        if 'custo_terceiros' in request.data:
            os_obj.custo_terceiros = Decimal(str(request.data.get('custo_terceiros') or '0.00'))

        try:
            os_obj.status = 'Concluída'
            os_obj.data_conclusao = timezone.now()
            os_obj.save()
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(OrdemServicoSerializer(os_obj).data)

    @action(detail=True, methods=['post'], url_path='cancelar')
    def cancelar(self, request, pk=None):
        membership = resolve_request_membership(request)
        if not (request.user.is_superuser or (membership and membership.papel in ('ADMIN', 'GERENTE'))):
            return Response({'error': "Apenas gestores podem cancelar uma Ordem de Serviço."}, status=status.HTTP_403_FORBIDDEN)

        os_obj = self.get_object()
        if os_obj.status in ('Concluída', 'Cancelada'):
            return Response({'error': f"Não é possível cancelar uma OS com status '{os_obj.status}'."}, status=status.HTTP_400_BAD_REQUEST)

        motivo = request.data.get('motivo') or 'Cancelada pela gestão'
        os_obj.status = 'Cancelada'
        os_obj.observacoes = (os_obj.observacoes + f"\n[Cancelamento em {timezone.now().strftime('%d/%m/%Y %H:%M')}]: {motivo}").strip()
        os_obj.save()
        return Response(OrdemServicoSerializer(os_obj).data)

    @action(detail=True, methods=['post'], url_path='adicionar-item')
    def adicionar_item(self, request, pk=None):
        membership = resolve_request_membership(request)
        if not (request.user.is_superuser or (membership and membership.papel in ('ADMIN', 'GERENTE'))):
            return Response({'error': "Apenas gestores podem lançar itens e custos na OS."}, status=status.HTTP_403_FORBIDDEN)

        os_obj = self.get_object()
        tenant = get_current_tenant()
        data = request.data.copy()
        data['os'] = os_obj.id

        serializer = OSItemSerializer(data=data)
        if serializer.is_valid():
            serializer.save(tenant=tenant)
            os_obj.refresh_from_db()
            return Response(OrdemServicoSerializer(os_obj).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='adicionar-anexo')
    def adicionar_anexo(self, request, pk=None):
        os_obj = self.get_object()
        tenant = get_current_tenant()
        arquivo_file = request.FILES.get('arquivo')
        if not arquivo_file:
            return Response({'error': "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)

        validar_upload_documento(arquivo_file, max_mb=10)
        tipo = request.data.get('tipo', 'Orçamento')
        descricao = request.data.get('descricao', '')

        anexo = OSAnexo.objects.create(
            tenant=tenant,
            os=os_obj,
            tipo=tipo,
            arquivo=arquivo_file,
            descricao=descricao,
            enviado_por=request.user
        )
        return Response(OSAnexoSerializer(anexo).data, status=status.HTTP_201_CREATED)


class OSItemViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = OSItem.unscoped.all()
    serializer_class = OSItemSerializer
    permission_classes = [IsTenantAdminOrGerente]

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        serializer.save(tenant=tenant)


class ChecklistModeloViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = ChecklistModelo.unscoped.all()
    serializer_class = ChecklistModeloSerializer
    permission_classes = [IsTenantMember]

    @action(detail=False, methods=['get'], url_path='padrao')
    def padrao(self, request):
        tenant = get_current_tenant()
        modelo = ChecklistModelo.objects.filter(tenant=tenant, ativo=True).first()
        if not modelo:
            modelo = ChecklistModelo.objects.create(
                tenant=tenant,
                nome="Checklist Padrão Pré-Saída",
                ativo=True,
                obrigatorio_antes_saida=True
            )
        return Response(ChecklistModeloSerializer(modelo).data)


class ChecklistExecucaoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = ChecklistExecucao.unscoped.all()
    serializer_class = ChecklistExecucaoSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('sem_paginacao') == '1':
            self.pagination_class = None

        veiculo_id = self.request.query_params.get('veiculo')
        if veiculo_id:
            qs = qs.filter(veiculo_id=veiculo_id)

        motorista_id = self.request.query_params.get('motorista')
        if motorista_id:
            qs = qs.filter(motorista_id=motorista_id)

        aprovado = self.request.query_params.get('aprovado')
        if aprovado is not None:
            qs = qs.filter(aprovado=(aprovado.lower() in ('1', 'true', 't')))

        return qs.select_related('veiculo', 'motorista', 'os_gerada').order_by('-data_hora')

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        client_uuid = serializer.validated_data.get('client_uuid')
        if client_uuid:
            existente = ChecklistExecucao.objects.filter(tenant=tenant, client_uuid=client_uuid).first()
            if existente:
                return existente

        foto_file = self.request.FILES.get('foto')
        if foto_file:
            validar_upload_imagem(foto_file, max_mb=5)

        motorista = serializer.validated_data.get('motorista') or (self.request.user if self.request.user.is_authenticated else None)
        serializer.save(tenant=tenant, motorista=motorista)


class ManutencaoIndicadoresAPIView(APIView):
    """
    Endpoint de inteligência analítica e indicadores de frota (/logistica/api/manutencao/indicadores/).
    Calcula: Custo por km, TCO por veículo, MTBF, MTTR, disponibilidade frota %,
    proporção preventiva vs corretiva, ranking e alerta avaliar substituição (>30% FIPE).
    """
    permission_classes = [IsTenantMember]

    def get(self, request):
        tenant = get_current_tenant()
        inicio_str = request.query_params.get('inicio') or request.query_params.get('data_inicio')
        fim_str = request.query_params.get('fim') or request.query_params.get('data_fim')
        fipe_pct_str = request.query_params.get('percentual_fipe', '30.00')

        data_inicio = None
        data_fim = None
        if inicio_str:
            try:
                data_inicio = timezone.datetime.strptime(inicio_str, '%Y-%m-%d').date()
            except Exception:
                pass
        if fim_str:
            try:
                data_fim = timezone.datetime.strptime(fim_str, '%Y-%m-%d').date()
            except Exception:
                pass

        try:
            fipe_pct = Decimal(str(fipe_pct_str))
        except Exception:
            fipe_pct = Decimal('30.00')

        dados = calcular_indicadores_manutencao(
            tenant=tenant,
            data_inicio=data_inicio,
            data_fim=data_fim,
            percentual_substituicao_fipe=fipe_pct
        )
        return Response(dados)


class OSAnexoDownloadView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request, pk=None):
        tenant = get_current_tenant()
        anexo = OSAnexo.unscoped.filter(id=pk, tenant=tenant).first()
        if not anexo or not anexo.arquivo:
            raise Http404("Anexo não encontrado ou acesso não autorizado.")

        arquivo = anexo.arquivo
        try:
            arquivo.open('rb')
            ext = arquivo.name.split('.')[-1].lower() if '.' in arquivo.name else ''
            content_type = 'application/pdf' if ext == 'pdf' else f'image/{ext}'
            response = FileResponse(arquivo, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="os_anexo_{anexo.id}_{arquivo.name.split("/")[-1]}"'
            return response
        except Exception:
            raise Http404("Arquivo físico do anexo não encontrado no servidor de armazenamento.")


class ChecklistFotoDownloadView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request, pk=None):
        tenant = get_current_tenant()
        chk = ChecklistExecucao.unscoped.filter(id=pk, tenant=tenant).first()
        if not chk or not chk.foto:
            raise Http404("Foto do checklist não encontrada ou acesso não autorizado.")

        arquivo = chk.foto
        try:
            arquivo.open('rb')
            ext = arquivo.name.split('.')[-1].lower() if '.' in arquivo.name else 'jpg'
            response = FileResponse(arquivo, content_type=f'image/{ext}')
            response['Content-Disposition'] = f'inline; filename="checklist_{chk.id}_{arquivo.name.split("/")[-1]}"'
            return response
        except Exception:
            raise Http404("Arquivo físico da foto não encontrado no servidor de armazenamento.")


class ValidacaoEvidenciaDownloadView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request, pk=None):
        tenant = get_current_tenant()
        evidencia = ValidacaoCargaEvidencia.unscoped.filter(id=pk, tenant=tenant).first()
        if not evidencia or not evidencia.arquivo:
            raise Http404("Evidência fotográfica não encontrada ou acesso não autorizado.")

        arquivo = evidencia.arquivo
        try:
            arquivo.open('rb')
            ext = arquivo.name.split('.')[-1].lower() if '.' in arquivo.name else 'jpg'
            content_type = 'application/pdf' if ext == 'pdf' else f'image/{ext}'
            response = FileResponse(arquivo, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="evidencia_validacao_{evidencia.id}_{arquivo.name.split("/")[-1]}"'
            return response
        except Exception:
            raise Http404("Arquivo físico da evidência não encontrado no servidor de armazenamento.")


class ApoliceSeguroViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = ApoliceSeguro.unscoped.all()
    serializer_class = ApoliceSeguroSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('sem_paginacao') == '1':
            self.pagination_class = None

        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo)

        ativa = self.request.query_params.get('ativa')
        if ativa is not None:
            qs = qs.filter(ativa=(ativa.lower() in ('1', 'true', 't')))

        veiculo_id = self.request.query_params.get('veiculo')
        if veiculo_id:
            qs = qs.filter(veiculos_segurados__veiculo_id=veiculo_id)

        return qs.prefetch_related('coberturas', 'veiculos_segurados__veiculo').order_by('vigencia_fim')

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        serializer.save(tenant=tenant)

    @action(detail=False, methods=['get'], url_path='alertas-renovacao')
    def alertas_renovacao(self, request):
        tenant = get_current_tenant()
        limite_dias = int(request.query_params.get('dias', 60))

        apolices = ApoliceSeguro.objects.filter(
            tenant=tenant,
            ativa=True
        ).order_by('vigencia_fim')

        alertas = []
        for ap in apolices:
            dias = ap.dias_para_vencimento
            if dias <= limite_dias:
                alertas.append({
                    'id': ap.id,
                    'seguradora': ap.seguradora,
                    'numero_apolice': ap.numero_apolice,
                    'tipo': ap.tipo,
                    'vigencia_fim': ap.vigencia_fim.strftime('%d/%m/%Y'),
                    'dias_para_vencimento': dias,
                    'status_vigencia': ap.status_vigencia,
                    'semaforo': ap.semaforo_vigencia,
                    'urgente': dias <= 30
                })
        return Response({'alertas': alertas, 'total': len(alertas)})

    @action(detail=True, methods=['get', 'post'], url_path='coberturas')
    def coberturas(self, request, pk=None):
        apolice = self.get_object()
        tenant = get_current_tenant()

        if request.method == 'GET':
            coberturas = apolice.coberturas.all()
            return Response(ApoliceCoberturaSerializer(coberturas, many=True).data)

        # POST: Adicionar cobertura
        cobertura_tipo = request.data.get('cobertura')
        if not cobertura_tipo:
            raise DRFValidationError({'cobertura': ['O tipo de cobertura é obrigatório.']})

        limite = request.data.get('limite')
        franquia_valor = request.data.get('franquia_valor', '0.00')
        franquia_percentual = request.data.get('franquia_percentual')

        cob = ApoliceCobertura.objects.create(
            tenant=tenant,
            apolice=apolice,
            cobertura=cobertura_tipo,
            limite=Decimal(str(limite)) if limite else None,
            franquia_valor=Decimal(str(franquia_valor)) if franquia_valor else Decimal('0.00'),
            franquia_percentual=Decimal(str(franquia_percentual)) if franquia_percentual else None
        )
        return Response(ApoliceCoberturaSerializer(cob).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='coberturas/(?P<cobertura_id>[^/.]+)')
    def remover_cobertura(self, request, pk=None, cobertura_id=None):
        apolice = self.get_object()
        cob = apolice.coberturas.filter(pk=cobertura_id).first()
        if not cob:
            raise Http404("Cobertura não encontrada.")
        cob.delete()
        return Response({'detail': 'Cobertura removida com sucesso.'}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get', 'post'], url_path='veiculos')
    def veiculos(self, request, pk=None):
        apolice = self.get_object()
        tenant = get_current_tenant()

        if request.method == 'GET':
            veics = apolice.veiculos_segurados.select_related('veiculo').all()
            return Response(ApoliceVeiculoSerializer(veics, many=True).data)

        # POST: Vincular veículo
        veiculo_id = request.data.get('veiculo') or request.data.get('veiculo_id')
        if not veiculo_id:
            raise DRFValidationError({'veiculo': ['O ID do veículo é obrigatório.']})

        veiculo = Veiculo.objects.filter(pk=veiculo_id, tenant=tenant).first()
        if not veiculo:
            raise DRFValidationError({'veiculo': ['Veículo não encontrado ou não pertence a esta empresa.']})

        tipo_valor = request.data.get('tipo_valor', 'Percentual FIPE')
        valor_segurado = request.data.get('valor_segurado')

        vinc, created = ApoliceVeiculo.objects.get_or_create(
            tenant=tenant,
            apolice=apolice,
            veiculo=veiculo,
            defaults={
                'tipo_valor': tipo_valor,
                'valor_segurado': Decimal(str(valor_segurado)) if valor_segurado else None
            }
        )
        if not created:
            vinc.tipo_valor = tipo_valor
            if valor_segurado:
                vinc.valor_segurado = Decimal(str(valor_segurado))
            vinc.save()

        return Response(ApoliceVeiculoSerializer(vinc).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], url_path='veiculos/(?P<veiculo_id>[^/.]+)')
    def remover_veiculo(self, request, pk=None, veiculo_id=None):
        apolice = self.get_object()
        vinc = apolice.veiculos_segurados.filter(veiculo_id=veiculo_id).first()
        if not vinc:
            raise Http404("Vínculo de veículo não encontrado.")
        vinc.delete()
        return Response({'detail': 'Veículo desvinculado com sucesso.'}, status=status.HTTP_204_NO_CONTENT)


class ApolicePdfDownloadView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request, pk=None):
        tenant = get_current_tenant()
        ap = ApoliceSeguro.unscoped.filter(id=pk, tenant=tenant).first()
        if not ap or not ap.arquivo_pdf:
            raise Http404("Documento PDF da apólice não encontrado ou acesso não autorizado.")

        arquivo = ap.arquivo_pdf
        try:
            arquivo.open('rb')
            response = FileResponse(arquivo, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="apolice_{ap.numero_apolice}.pdf"'
            return response
        except Exception:
            raise Http404("Arquivo físico do PDF não encontrado no servidor de armazenamento.")


class SinistroViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Sinistro.unscoped.all()
    serializer_class = SinistroSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('sem_paginacao') == '1':
            self.pagination_class = None

        status_filtro = self.request.query_params.get('status')
        if status_filtro:
            qs = qs.filter(status=status_filtro)

        tipo_filtro = self.request.query_params.get('tipo')
        if tipo_filtro:
            qs = qs.filter(tipo=tipo_filtro)

        veiculo_id = self.request.query_params.get('veiculo')
        if veiculo_id:
            qs = qs.filter(veiculo_id=veiculo_id)

        motorista_id = self.request.query_params.get('motorista')
        if motorista_id:
            qs = qs.filter(motorista_id=motorista_id)

        return qs.select_related(
            'veiculo', 'motorista', 'entrega', 'apolice', 'os_vinculada', 'criado_por'
        ).prefetch_related('eventos', 'anexos', 'itens_carga__produto').order_by('-data_hora')

    def create(self, request, *args, **kwargs):
        tenant = get_current_tenant()
        data = request.data

        client_uuid = data.get('client_uuid')
        if client_uuid:
            existente = Sinistro.objects.filter(tenant=tenant, client_uuid=client_uuid).first()
            if existente:
                serializer = self.get_serializer(existente)
                return Response(serializer.data, status=status.HTTP_200_OK)

        tipo = data.get('tipo', 'Colisão')
        descricao = data.get('descricao', '')
        data_hora_str = data.get('data_hora')
        try:
            data_hora = timezone.datetime.fromisoformat(data_hora_str.replace('Z', '+00:00')) if data_hora_str else timezone.now()
        except Exception:
            data_hora = timezone.now()

        veiculo_id = data.get('veiculo') or data.get('veiculo_id')
        veiculo = Veiculo.objects.filter(pk=veiculo_id, tenant=tenant).first() if veiculo_id else None

        motorista_id = data.get('motorista') or data.get('motorista_id')
        from django.contrib.auth import get_user_model
        User = get_user_model()
        motorista = User.objects.filter(pk=motorista_id).first() if motorista_id else (request.user if request.user.is_authenticated else None)

        entrega_id = data.get('entrega') or data.get('entrega_id')
        entrega = Entrega.objects.filter(pk=entrega_id, tenant=tenant).first() if entrega_id else None

        apolice_id = data.get('apolice') or data.get('apolice_id')
        apolice = ApoliceSeguro.objects.filter(pk=apolice_id, tenant=tenant).first() if apolice_id else None

        latitude = data.get('latitude')
        longitude = data.get('longitude')
        endereco = data.get('endereco', '')
        terceiros = data.get('terceiros') or {}
        houve_vitimas = bool(data.get('houve_vitimas', False))
        boletim_ocorrencia_numero = data.get('boletim_ocorrencia_numero', '')
        valor_prejuizo_estimado = Decimal(str(data.get('valor_prejuizo_estimado') or '0.00'))
        valor_franquia = Decimal(str(data.get('valor_franquia') or '0.00'))
        status_inicial = data.get('status', 'Registrado')

        itens_carga = data.get('itens_carga')

        try:
            sinistro = criar_sinistro(
                tipo=tipo,
                descricao=descricao,
                data_hora=data_hora,
                veiculo=veiculo,
                motorista=motorista,
                entrega=entrega,
                apolice=apolice,
                latitude=latitude,
                longitude=longitude,
                endereco=endereco,
                terceiros=terceiros,
                houve_vitimas=houve_vitimas,
                boletim_ocorrencia_numero=boletim_ocorrencia_numero,
                valor_prejuizo_estimado=valor_prejuizo_estimado,
                valor_franquia=valor_franquia,
                status=status_inicial,
                client_uuid=client_uuid,
                autor=request.user,
                tenant=tenant,
                itens_carga=itens_carga
            )

            # Suporte a foto enviada diretamente na criação do sinistro (ex: PWA de Campo)
            foto_upload = request.FILES.get('foto') or request.FILES.get('arquivo')
            if foto_upload:
                try:
                    validar_upload_documento(foto_upload, max_mb=15)
                    SinistroAnexo.objects.create(
                        tenant=tenant,
                        sinistro=sinistro,
                        tipo='Foto Local',
                        arquivo=foto_upload,
                        descricao='Foto da ocorrência capturada em campo',
                        enviado_por=request.user if request.user.is_authenticated else None
                    )
                except Exception as ex_foto:
                    logger.warning("Falha ao salvar anexo de foto inicial do sinistro %s: %s", sinistro.id, ex_foto)

            serializer = self.get_serializer(sinistro)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            raise DRFValidationError({'erro': [str(e)]})

    @action(detail=True, methods=['post'], url_path='transicionar-status')
    def transicionar_status(self, request, pk=None):
        sinistro = self.get_object()
        novo_status = request.data.get('status') or request.data.get('novo_status')
        if not novo_status:
            raise DRFValidationError({'status': ['O novo status é obrigatório.']})

        valid_choices = [c[0] for c in Sinistro.STATUS_CHOICES]
        if novo_status not in valid_choices:
            raise DRFValidationError({'status': [f"Status inválido. Escolha entre: {', '.join(valid_choices)}."]})

        observacao = request.data.get('observacao', '')
        protocolo = request.data.get('protocolo_seguradora')
        data_comunicacao_str = request.data.get('data_comunicacao_seguradora')
        data_comunicacao = None
        if data_comunicacao_str:
            try:
                data_comunicacao = timezone.datetime.fromisoformat(data_comunicacao_str.replace('Z', '+00:00'))
            except Exception:
                data_comunicacao = timezone.now()
        valor_indenizacao = request.data.get('valor_indenizacao')

        sinistro = transicionar_status_sinistro(
            sinistro=sinistro,
            novo_status=novo_status,
            autor=request.user,
            observacao=observacao,
            protocolo=protocolo,
            data_comunicacao=data_comunicacao,
            valor_indenizacao=valor_indenizacao
        )
        return Response(self.get_serializer(sinistro).data)

    @action(detail=True, methods=['post'], url_path='vincular-os')
    def vincular_os(self, request, pk=None):
        sinistro = self.get_object()
        descricao = request.data.get('descricao', '')
        prioridade = request.data.get('prioridade', 'Alta')
        imobiliza_veiculo = bool(request.data.get('imobiliza_veiculo', True))
        fornecedor_id = request.data.get('fornecedor_id')
        fornecedor = Fornecedor.objects.filter(pk=fornecedor_id, tenant=sinistro.tenant).first() if fornecedor_id else None

        try:
            sinistro, os_obj = vincular_ou_criar_os_sinistro(
                sinistro=sinistro,
                autor=request.user,
                descricao=descricao,
                prioridade=prioridade,
                imobiliza_veiculo=imobiliza_veiculo,
                fornecedor=fornecedor
            )
            return Response({
                'sinistro': self.get_serializer(sinistro).data,
                'os_numero': os_obj.numero,
                'os_id': os_obj.id,
                'mensagem': f"Ordem de Serviço #{os_obj.numero} criada e vinculada com sucesso ao sinistro."
            })
        except Exception as e:
            raise DRFValidationError({'erro': [str(e)]})

    @action(detail=True, methods=['post'], url_path='ajustar-estoque-carga')
    def ajustar_estoque(self, request, pk=None):
        sinistro = self.get_object()
        decisao = request.data.get('decisao_entrega', 'reentregar')
        justificativa = request.data.get('justificativa', '')

        try:
            sinistro = processar_ajuste_estoque_sinistro_carga(
                sinistro=sinistro,
                autor=request.user,
                decisao_entrega=decisao,
                justificativa=justificativa
            )
            return Response({
                'sinistro': self.get_serializer(sinistro).data,
                'mensagem': "Ajuste de estoque concluído com sucesso e contingência aplicada à entrega."
            })
        except Exception as e:
            raise DRFValidationError({'erro': [str(e)]})

    @action(detail=True, methods=['post'], url_path='adicionar-item-carga')
    def adicionar_item_carga(self, request, pk=None):
        sinistro = self.get_object()
        tenant = get_current_tenant()

        produto_id = request.data.get('produto') or request.data.get('produto_id')
        from produtos.models import Produto
        produto = Produto.objects.filter(pk=produto_id, tenant=tenant).first()
        if not produto:
            raise DRFValidationError({'produto': ['Produto não encontrado.']})

        quantidade = int(request.data.get('quantidade', 1))
        categoria = request.data.get('categoria', 'Cheio')
        valor_unitario = Decimal(str(request.data.get('valor_unitario') or produto.preco or '0.00'))

        item = SinistroItemCarga.objects.create(
            tenant=tenant,
            sinistro=sinistro,
            produto=produto,
            quantidade=quantidade,
            categoria=categoria,
            valor_unitario=valor_unitario,
            valor_total=quantidade * valor_unitario
        )
        sinistro.calcular_prejuizo_liquido()
        sinistro.save(update_fields=['prejuizo_liquido'])

        return Response(SinistroItemCargaSerializer(item).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='adicionar-anexo')
    def adicionar_anexo(self, request, pk=None):
        sinistro = self.get_object()
        tenant = get_current_tenant()

        arquivo = request.FILES.get('arquivo') or request.FILES.get('foto')
        arquivo_base64 = request.data.get('arquivo_base64')
        if not arquivo and arquivo_base64:
            import base64
            from django.core.files.base import ContentFile
            import uuid
            if ';base64,' in arquivo_base64:
                _, b64data = arquivo_base64.split(';base64,', 1)
            else:
                b64data = arquivo_base64
            decoded = base64.b64decode(b64data)
            fname = request.data.get('titulo') or request.data.get('descricao') or f"sinistro_{sinistro.id}_{uuid.uuid4().hex[:6]}.jpg"
            if not '.' in fname:
                fname += '.jpg'
            arquivo = ContentFile(decoded, name=fname)

        if not arquivo:
            raise DRFValidationError({'arquivo': ['Arquivo não fornecido.']})

        validar_upload_documento(arquivo, max_mb=15)

        tipo = request.data.get('tipo', 'Foto Local')
        descricao = request.data.get('descricao', '')

        anexo = SinistroAnexo.objects.create(
            tenant=tenant,
            sinistro=sinistro,
            tipo=tipo,
            arquivo=arquivo,
            descricao=descricao,
            enviado_por=request.user if request.user.is_authenticated else None
        )
        return Response(SinistroAnexoSerializer(anexo).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='liberar-veiculo')
    def liberar_veiculo(self, request):
        tenant = get_current_tenant()
        veiculo_id = request.data.get('veiculo') or request.data.get('veiculo_id')
        if not veiculo_id:
            raise DRFValidationError({'veiculo': ['ID do veículo é obrigatório.']})

        veiculo = Veiculo.objects.filter(pk=veiculo_id, tenant=tenant).first()
        if not veiculo:
            raise DRFValidationError({'veiculo': ['Veículo não encontrado.']})

        observacao = request.data.get('observacao', '')

        try:
            veiculo = liberar_veiculo_sinistrado(veiculo, request.user, observacao)
            return Response({
                'mensagem': f"Veículo {veiculo.placa} liberado com sucesso para operação.",
                'veiculo_id': veiculo.id,
                'status': veiculo.status
            })
        except Exception as e:
            raise DRFValidationError({'erro': [str(e)]})

    @action(detail=False, methods=['get'], url_path='indicadores')
    def indicadores(self, request):
        tenant = get_current_tenant()
        inicio_str = request.query_params.get('data_inicio') or request.query_params.get('inicio')
        fim_str = request.query_params.get('data_fim') or request.query_params.get('fim')

        data_inicio = timezone.datetime.strptime(inicio_str, '%Y-%m-%d').date() if inicio_str else None
        data_fim = timezone.datetime.strptime(fim_str, '%Y-%m-%d').date() if fim_str else None

        dados = obter_indicadores_sinistralidade(tenant, data_inicio, data_fim)
        return Response(dados)


class SinistroAnexoDownloadView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request, pk=None):
        tenant = get_current_tenant()
        anexo = SinistroAnexo.unscoped.filter(id=pk, tenant=tenant).first()
        if not anexo or not anexo.arquivo:
            raise Http404("Anexo do sinistro não encontrado ou acesso não autorizado.")

        arquivo = anexo.arquivo
        try:
            arquivo.open('rb')
            ext = arquivo.name.split('.')[-1].lower() if '.' in arquivo.name else 'jpg'
            content_type = 'application/pdf' if ext == 'pdf' else f'image/{ext}'
            response = FileResponse(arquivo, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="sinistro_anexo_{anexo.id}_{arquivo.name.split("/")[-1]}"'
            return response
        except Exception:
            raise Http404("Arquivo físico do anexo não encontrado no servidor de armazenamento.")


class ConfiguracaoSegurosView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request):
        tenant = get_current_tenant()
        cfg = ConfiguracaoSeguros.get_para_tenant(tenant)
        return Response(ConfiguracaoSegurosSerializer(cfg).data)

    def patch(self, request):
        tenant = get_current_tenant()
        user = request.user
        if not user.is_superuser:
            membership = Membership.objects.filter(tenant=tenant, user=user, ativo=True).first()
            if not membership or membership.papel not in ('ADMIN', 'GERENTE'):
                return Response({'detail': 'Apenas administradores e gerentes podem alterar configurações.'}, status=status.HTTP_403_FORBIDDEN)

        cfg = ConfiguracaoSeguros.get_para_tenant(tenant)
        serializer = ConfiguracaoSegurosSerializer(cfg, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ==============================================================================
# SPRINT L6: FRETE, RENTABILIDADE E CUSTO TOTAL (TCO)
# ==============================================================================

class CustoViagemViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = CustoViagem.unscoped.all()
    serializer_class = CustoViagemSerializer
    permission_classes = [IsTenantMember]

    @action(detail=True, methods=['post'], url_path='recalcular')
    def recalcular(self, request, pk=None):
        custo = self.get_object()
        custo = consolidar_custo_viagem(custo.entrega, forcar_recalculo=True)
        return Response(CustoViagemSerializer(custo, context={'request': request}).data)


class CustoViagemItemViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = CustoViagemItem.unscoped.all()
    serializer_class = CustoViagemItemSerializer
    permission_classes = [IsTenantMember]


class ConfiguracaoRentabilidadeView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request):
        tenant = get_current_tenant()
        cfg = ConfiguracaoRentabilidade.get_para_tenant(tenant)
        return Response(ConfiguracaoRentabilidadeSerializer(cfg).data)

    def patch(self, request):
        tenant = get_current_tenant()
        user = request.user
        if not user.is_superuser:
            membership = Membership.objects.filter(tenant=tenant, user=user, ativo=True).first()
            if not membership or membership.papel not in ('ADMIN', 'GERENTE'):
                return Response(
                    {'detail': 'Apenas administradores e gerentes podem alterar configurações.'},
                    status=status.HTTP_403_FORBIDDEN
                )

        cfg = ConfiguracaoRentabilidade.get_para_tenant(tenant)
        serializer = ConfiguracaoRentabilidadeSerializer(cfg, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class RentabilidadeIndicadoresView(APIView):
    """
    Endpoint consolidado de rentabilidade operacional:
    /logistica/api/rentabilidade/?inicio=&fim=&agrupar=rota|veiculo|cliente|motorista&formato=json|csv
    """
    permission_classes = [IsTenantMember]

    def get(self, request):
        tenant = get_current_tenant()
        inicio_str = request.query_params.get('inicio')
        fim_str = request.query_params.get('fim')
        agrupar = request.query_params.get('agrupar', 'rota')
        formato = request.query_params.get('formato', 'json').lower()

        data_inicio = None
        data_fim = None

        if inicio_str:
            try:
                from datetime import datetime
                data_inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        if fim_str:
            try:
                from datetime import datetime
                data_fim = datetime.strptime(fim_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        if agrupar not in ('rota', 'veiculo', 'cliente', 'motorista'):
            agrupar = 'rota'

        dados = obter_indicadores_rentabilidade(
            tenant=tenant,
            data_inicio=data_inicio,
            data_fim=data_fim,
            agrupar_por=agrupar
        )

        if formato == 'csv':
            csv_str = gerar_csv_rentabilidade(dados)
            timestamp = timezone.now().strftime('%Y%m%d_%H%M')
            response = HttpResponse(csv_str, content_type='text/csv; charset=utf-8-sig')
            response['Content-Disposition'] = f'attachment; filename="rentabilidade_{agrupar}_{timestamp}.csv"'
            return response

        return Response(dados)


class TCOFrotaView(APIView):
    """
    Endpoint de Custo Total de Propriedade (TCO) por veículo da frota:
    /logistica/api/rentabilidade/tco/?inicio=&fim=
    """
    permission_classes = [IsTenantMember]

    def get(self, request):
        tenant = get_current_tenant()
        inicio_str = request.query_params.get('inicio')
        fim_str = request.query_params.get('fim')

        data_inicio = None
        data_fim = None

        if inicio_str:
            try:
                from datetime import datetime
                data_inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        if fim_str:
            try:
                from datetime import datetime
                data_fim = datetime.strptime(fim_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        dados = obter_tco_frota(tenant=tenant, data_inicio=data_inicio, data_fim=data_fim)
        return Response(dados)


class CustoViagemItemComprovanteDownloadView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request, pk=None):
        tenant = get_current_tenant()
        item = get_object_or_404(CustoViagemItem.objects.filter(tenant=tenant), pk=pk)
        if not item.comprovante:
            raise Http404("Comprovante não cadastrado para esta despesa.")

        try:
            arquivo = item.comprovante
            arquivo.open('rb')
            ext = arquivo.name.split('.')[-1].lower() if '.' in arquivo.name else 'pdf'
            content_type = 'application/pdf' if ext == 'pdf' else f'image/{ext}'
            response = FileResponse(arquivo, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="comprovante_custo_{item.id}_{arquivo.name.split("/")[-1]}"'
            return response
        except Exception:
            raise Http404("Arquivo físico do comprovante não encontrado.")


class TrackingPublicoView(View):
    """
    View Pública de Rastreio em Tempo Real para clientes finais (Sem Autenticação DRF).
    Fail-Closed: Acessível exclusivamente via UUID (token de rastreio).
    Exibe dados estritamente mínimos (placa mascarada, status da entrega e posição sob janela de privacidade).
    LGPD / Segurança: NUNCA serializa o nome do motorista, valores fiscais ou dados de outros clientes.
    Segurança de Busca: Adiciona cabeçalho X-Robots-Tag: noindex, nofollow e rate limit por IP.
    """
    def get(self, request, token, *args, **kwargs):
        from django.http import JsonResponse, Http404
        from django.shortcuts import render
        from django.core.cache import cache
        from .services.rastreio_publico_service import consultar_rastreio_publico

        # 1. Rate limiting por IP (Sprint 12A - Tarefa 7)
        ip = _obter_ip_cliente(request)
        cache_key = f"rl_rastreio_{ip}"
        try:
            req_count = cache.get(cache_key, 0)
            if req_count is not None and int(req_count) >= 60:
                resp = JsonResponse({"erro": "Limite de requisições excedido. Tente novamente em instantes."}, status=429)
                resp['X-Robots-Tag'] = 'noindex, nofollow'
                return resp
            cache.set(cache_key, int(req_count or 0) + 1, timeout=60)
        except Exception:
            pass

        # 2. Consulta segura com validação de token e janela de privacidade (Correção F-34)
        try:
            dados = consultar_rastreio_publico(token)
        except Exception as e:
            if request.headers.get('Accept') == 'application/json' or request.GET.get('format') == 'json':
                resp = JsonResponse({"erro": "Entrega não encontrada ou link expirado/revogado."}, status=404)
                resp['X-Robots-Tag'] = 'noindex, nofollow'
                return resp
            raise Http404("Entrega não encontrada ou link expirado/revogado.")

        if request.headers.get('Accept') == 'application/json' or request.GET.get('format') == 'json':
            resp = JsonResponse(dados)
            resp['X-Robots-Tag'] = 'noindex, nofollow'
            return resp

        context = {
            **dados,
            "token": str(token),
            "emissor": "Baros Logística",
        }
        resp = render(request, 'logistica/rastreio_publico.html', context)
        resp['X-Robots-Tag'] = 'noindex, nofollow'
        return resp


class SincronizarTrackingGPSAPIView(APIView):
    """
    Recepção em lote de telemetria GPS transmitida pelo PWA de Campo (offline-first).
    Sincronização em lotes de até 200 pontos, descartando precisão > 100m e idempotente por chave composta (Sprint 12A - Tarefa 5).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from .services.rastreamento_service import sincronizar_lote_gps
        from django.core.exceptions import ValidationError as DjangoValidationError

        payload = request.data
        if isinstance(payload, dict):
            entrega_id = payload.get('entrega_id')
            veiculo_id = payload.get('veiculo_id')
            coordenadas = payload.get('coordenadas') or payload.get('pontos') or []
        elif isinstance(payload, list):
            coordenadas = payload
            entrega_id = None
            veiculo_id = None
        else:
            return Response(
                {"erro": "Formato inválido. Esperado objeto com 'coordenadas' ou lista de pontos."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not isinstance(coordenadas, list):
            return Response(
                {"erro": "Formato inválido. 'coordenadas' deve ser uma lista."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(coordenadas) > 200:
            return Response(
                {"erro": f"O tamanho do lote ({len(coordenadas)} pontos) excede o limite máximo permitido de 200 pontos."},
                status=status.HTTP_400_BAD_REQUEST
            )

        tenant = getattr(request, 'tenant', None)

        # Se houver entrega_id explicitamente informada:
        if entrega_id:
            try:
                res = sincronizar_lote_gps(
                    tenant=tenant,
                    entrega_id=int(entrega_id),
                    pontos=coordenadas,
                    veiculo_id=int(veiculo_id) if veiculo_id else None
                )
                return Response({
                    "sucesso": True,
                    "total_sincronizado": res['inseridos'],
                    "duplicados": res['duplicados'],
                    "descartados_precisao": res['descartados_precisao']
                }, status=status.HTTP_200_OK)
            except DjangoValidationError as e:
                msg = e.message if hasattr(e, 'message') else str(e)
                return Response({"erro": msg}, status=status.HTTP_400_BAD_REQUEST)

        # Se os itens tiverem entrega_id internamente:
        grupos = {}
        for c in coordenadas:
            eid = c.get('entrega_id')
            if eid:
                grupos.setdefault(eid, []).append(c)

        total_inseridos = 0
        total_duplicados = 0
        total_descartados = 0

        for eid, pts in grupos.items():
            entrega = Entrega.objects.filter(id=eid).first()
            if not entrega:
                continue
            t = tenant or entrega.tenant
            try:
                r = sincronizar_lote_gps(tenant=t, entrega_id=eid, pontos=pts, veiculo_id=veiculo_id)
                total_inseridos += r['inseridos']
                total_duplicados += r['duplicados']
                total_descartados += r['descartados_precisao']
            except Exception as e:
                logger.warning(f"Erro ao sincronizar lote da entrega {eid}: {e}")

        return Response({
            "sucesso": True,
            "total_sincronizado": total_inseridos,
            "duplicados": total_duplicados,
            "descartados_precisao": total_descartados
        }, status=status.HTTP_200_OK)


class OtimizarOrdemParadasAPIView(TenantViewSetMixin, APIView):
    """
    Gera a roteirização otimizada para os pontos de entrega (vendas) vinculados à entrega.
    """
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica]

    def post(self, request, pk=None, *args, **kwargs):
        from .services.routing import otimizar_ordem_paradas
        try:
            resultado = otimizar_ordem_paradas(pk)
            return Response(resultado, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"erro": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception(f"Erro ao otimizar rotas da entrega #{pk}")
            return Response({"erro": f"Erro interno ao roteirizar paradas: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==============================================================================
# SPRINT 10C: FRETE INTERNO, ALOCAÇÃO DE EQUIPE, MARGEM E TCO
# ==============================================================================

class TabelaFreteInternoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    CRUD da tabela de frete interno (por km ou por parada) (Sprint 10C - Tarefa 5).
    """
    serializer_class = TabelaFreteInternoSerializer
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return TabelaFreteInterno.unscoped.filter(tenant=tenant).select_related('veiculo')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class AlocacaoMotoristaVeiculoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    CRUD da alocação de equipe (motorista/ajudante) no veículo (Sprint 10C - Tarefa 6).
    """
    serializer_class = AlocacaoMotoristaVeiculoSerializer
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return AlocacaoMotoristaVeiculo.unscoped.filter(tenant=tenant).select_related('veiculo', 'motorista', 'ajudante')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class MargemVeiculoAPIView(TenantViewSetMixin, APIView):
    """
    Cálculo de margem de contribuição do veículo (Frete Imputado ou Comercial) (Sprint 10C - Tarefa 5).
    """
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get(self, request):
        from logistica.services.margem_veiculo_service import calcular_margem_contribuicao_veiculo
        tenant = getattr(request, 'tenant', None)
        ser = MargemVeiculoInputSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        resultado = calcular_margem_contribuicao_veiculo(
            tenant=tenant,
            veiculo_id=vd['veiculo_id'],
            data_inicio=vd['data_inicio'],
            data_fim=vd['data_fim'],
            politica=vd.get('politica')
        )
        return Response(resultado, status=status.HTTP_200_OK)


class TCOVeiculoAPIView(TenantViewSetMixin, APIView):
    """
    Cálculo do TCO por km e por parada com validação estrita de odômetro (Sprint 10C - Tarefa 6).
    """
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get(self, request):
        from logistica.services.margem_veiculo_service import calcular_tco_veiculo
        tenant = getattr(request, 'tenant', None)
        ser = TCOVeiculoInputSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        resultado = calcular_tco_veiculo(
            tenant=tenant,
            veiculo_id=vd['veiculo_id'],
            ano=vd['ano'],
            mes=vd['mes']
        )
        return Response(resultado, status=status.HTTP_200_OK)


# ==============================================================================
# SPRINT 12A VIEWSETS & APIS
# ==============================================================================

class CapacidadeVeiculoTipoCilindroViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    CRUD de capacidade máxima de cilindros por tipo suportada por veículo (Sprint 12A - Tarefa 1).
    """
    serializer_class = CapacidadeVeiculoTipoCilindroSerializer
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return CapacidadeVeiculoTipoCilindro.unscoped.filter(tenant=tenant).select_related('veiculo', 'tipo_cilindro')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class MotoristaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Gestão de motoristas com dados regulatórios CNH e MOPP (Sprint 12A - Tarefa 1).
    """
    serializer_class = MotoristaSerializer
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return Motorista.unscoped.filter(tenant=tenant).select_related('usuario')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class RegraIncompatibilidadeCargaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Regras de incompatibilidade química entre classes de risco de gases (Sprint 12A - Tarefa 2).
    """
    serializer_class = RegraIncompatibilidadeCargaSerializer
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return RegraIncompatibilidadeCarga.unscoped.filter(tenant=tenant)

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)

    @action(detail=False, methods=['post'], url_path='seed')
    def seed(self, request):
        tenant = getattr(request, 'tenant', None)
        from logistica.services.carga import seed_regras_incompatibilidade
        criadas = seed_regras_incompatibilidade(tenant)
        return Response({
            'mensagem': f'{len(criadas)} regras de incompatibilidade verificadas/criadas com sucesso.',
            'total_regras': len(criadas)
        }, status=status.HTTP_200_OK)


class ParadaEntregaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Gestão e execução de paradas de entrega no fluxo logístico e PWA (Sprint 12A - Tarefas 3 e 4).
    """
    serializer_class = ParadaEntregaSerializer
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return ParadaEntrega.unscoped.filter(tenant=tenant).select_related('entrega', 'cliente', 'venda')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)

    @action(detail=True, methods=['post'], url_path='atualizar-status')
    def atualizar_status(self, request, pk=None):
        parada = self.get_object()
        novo_status = request.data.get('status')
        motivo_falha = request.data.get('motivo_falha')
        odometro_leitura = request.data.get('odometro_leitura')
        from logistica.services.paradas_service import atualizar_status_parada
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            parada_atualizada = atualizar_status_parada(
                parada_id=parada.id,
                novo_status=novo_status,
                motivo_falha=motivo_falha,
                odometro_km=Decimal(str(odometro_leitura)) if odometro_leitura is not None else None,
                usuario=request.user
            )
            return Response(ParadaEntregaSerializer(parada_atualizada).data, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='travar-ordem')
    def travar_ordem(self, request, pk=None):
        parada = self.get_object()
        travada = request.data.get('travada', not parada.travada)
        parada.travada = bool(travada)
        parada.save(update_fields=['travada'])
        return Response({'id': parada.id, 'travada': parada.travada}, status=status.HTTP_200_OK)


class IndicadoresLogisticaAPIView(TenantViewSetMixin, APIView):
    """
    Indicadores logísticos consolidados: pontualidade, km planejado vs real, paradas por hora (Sprint 12A - Tarefa 9).
    """
    permission_classes = [permissions.IsAuthenticated, RequiresModuleLogistica, IsTenantMember]

    def get(self, request):
        from logistica.services.indicadores_service import apurar_indicadores_logistica
        tenant = getattr(request, 'tenant', None)
        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        resultado = apurar_indicadores_logistica(tenant=tenant, data_inicio=data_inicio, data_fim=data_fim)
        return Response(resultado, status=status.HTTP_200_OK)


