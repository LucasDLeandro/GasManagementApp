import uuid
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.http import HttpResponse, FileResponse, Http404
from django.core.files.base import ContentFile
import base64

from core.mixins import TenantViewSetMixin
from core.tenancy import get_current_tenant
from .models import Veiculo, Rota, ManutencaoFrota, TabelaFrete, ValidacaoCarga, Entrega, ComprovanteEntrega
from .serializers import (
    VeiculoSerializer,
    RotaSerializer,
    ManutencaoFrotaSerializer,
    TabelaFreteSerializer,
    ValidacaoCargaSerializer,
    EntregaSerializer,
    ComprovanteEntregaSerializer
)
from vendas.models import ItemVenda
from produtos.models import Cilindro
from clientes.models import Cliente
from produtos.services import registrar_entrega_cilindro, registrar_recolha_cilindro
from .services import (
    validar_capacidade_veiculo_entrega,
    gerar_romaneio_carga_antt_pdf,
    gerar_ficha_emergencia_antt_pdf,
    gerar_envelope_transporte_antt_pdf
)

class LogisticaTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'logistica/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        tenant = get_current_tenant()
        if tenant:
            motoristas_qs = User.objects.filter(
                memberships__tenant=tenant,
                memberships__papel='MOTORISTA',
                memberships__ativo=True,
                is_active=True
            ).distinct()
            if motoristas_qs.exists():
                context['motoristas'] = motoristas_qs
            else:
                context['motoristas'] = User.objects.filter(is_active=True)
        else:
            context['motoristas'] = User.objects.filter(is_active=True)
        return context

class AppCampoView(LoginRequiredMixin, TemplateView):
    """
    Superfície Mobile / PWA dedicada ao Motorista de Campo (Fase 4).
    Acesso direto via /campo/ com suporte offline-first, pre-flight sync e auditoria ANTT/LGPD.
    """
    template_name = 'logistica/app_campo.html'

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
    permission_classes = [IsAuthenticated]

class RotaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Rota.unscoped.all()
    serializer_class = RotaSerializer
    permission_classes = [IsAuthenticated]

class ManutencaoFrotaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = ManutencaoFrota.unscoped.all()
    serializer_class = ManutencaoFrotaSerializer
    permission_classes = [IsAuthenticated]

class TabelaFreteViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = TabelaFrete.unscoped.all()
    serializer_class = TabelaFreteSerializer
    permission_classes = [IsAuthenticated]

class ValidacaoCargaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = ValidacaoCarga.unscoped.all()
    serializer_class = ValidacaoCargaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        entrega_id = self.request.query_params.get('entrega', None)
        if entrega_id:
            qs = qs.filter(entrega_id=entrega_id)
        return qs

    def perform_create(self, serializer):
        validacao = serializer.save(tenant=get_current_tenant())
        item = ItemVenda.objects.filter(venda=validacao.venda, produto=validacao.produto).first()
        if item:
            item.quantidade += validacao.quantidade_alterada
            if item.quantidade < 0:
                item.quantidade = 0
            item.save()
            validacao.venda.calcular_total()

from core.permissions import IsMotoristaOrAdmin

class EntregaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    queryset = Entrega.unscoped.all()
    serializer_class = EntregaSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ['concluir_romaneio', 'comprovante_assinatura', 'pacote_rota', 'minha_rota_ativa']:
            return [IsMotoristaOrAdmin()]
        return [permission() for permission in self.permission_classes]

    def perform_update(self, serializer):
        instance = serializer.instance
        novo_status = serializer.validated_data.get('status', instance.status)
        novo_veiculo = serializer.validated_data.get('veiculo', instance.veiculo)
        
        if novo_status == 'Em Rota':
            veiculo = novo_veiculo or instance.veiculo
            if veiculo and veiculo.capacidade_carga and float(veiculo.capacidade_carga) > 0:
                peso = instance.peso_total_carregado
                cap = float(veiculo.capacidade_carga)
                if peso > cap:
                    from rest_framework.exceptions import ValidationError as DRFValidationError
                    raise DRFValidationError({
                        'non_field_errors': [
                            f"Trava de Segurança ANTT: Não é permitido iniciar rota com veículo em sobrecarga! "
                            f"Peso atual de {peso:.2f} kg excede a capacidade máxima de {cap:.2f} kg do veículo {veiculo.placa}."
                        ]
                    })
        serializer.save()

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get('status', None)
        if status_param:
            statuses = status_param.split(',')
            qs = qs.filter(status__in=statuses)
        return qs

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

        return Response({
            'status': 'sucesso',
            'mensagem': f'Romaneio #{entrega.id} concluído com sucesso e notificação enviada.',
            'entrega_id': entrega.id,
            'status_entrega': entrega.status
        })

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

