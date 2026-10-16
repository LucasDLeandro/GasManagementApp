import csv
import datetime
from django.http import HttpResponse, FileResponse
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin


from core.mixins import TenantViewSetMixin
from core.permissions import (
    IsTenantMember,
    CanOperateRampaEnvase,
    CanApproveLoteOuMedicinal,
    IsResponsavelTecnico,
    IsMotoristaOrAdmin,
)
from core.models import ResponsavelTecnico

from .models import (
    Produto,
    LoteEnvase,
    EnvaseCilindro,
    Cilindro,
    GasQuimico,
    InspecaoPreEnvase,
    RecebimentoCilindroCheio,
    ReclassificacaoCilindro,
    AuditoriaBloqueioSanitario,
    RecallCampanha,
    ItemRecallCliente,
    MovimentacaoCilindro,
)
from .serializers import (
    ProdutoSerializer,
    CilindroSerializer,
    EnvaseCilindroSerializer,
    LoteEnvaseSerializer,
    InspecaoPreEnvaseSerializer,
    RecebimentoCilindroCheioSerializer,
    ReclassificacaoCilindroSerializer,
    AuditoriaBloqueioSanitarioSerializer,
    RecallCampanhaSerializer,
    ItemRecallClienteSerializer,
    MovimentacaoCilindroSerializer,
)
from .services import (
    registrar_envase_cilindro,
    registrar_envase_batelada,
    receber_cilindro_cheio_fornecedor,
    receber_cilindros_fornecedor_batelada,
    validar_cilindro_para_rampa,
    reclassificar_cilindro_gas,
    acionar_bloqueio_sanitario,
    liberar_bloqueio_sanitario,
    atualizar_qualidade_lote,
    abrir_campanha_recall,
    homologar_campanha_recall,
    obter_dossie_recall_lote,
    sincronizar_movimentacoes_offline,
    retornar_de_reteste,
    estornar_movimentacao_ledger,
)



def _parse_bool(val, default=False):
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ('true', '1', 't', 'yes')


class ProdutoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    API endpoint that allows produtos to be viewed or edited with Tenant isolation.
    """
    queryset = Produto.unscoped.all()
    serializer_class = ProdutoSerializer
    permission_classes = [IsTenantMember]


class CilindroViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para consulta, detalhe e reclassificação de Cilindros com isolamento de Tenant.
    Suporta filtros por qr_code, status, reteste_vencido, bloqueio_sanitario e gas.
    """
    queryset = Cilindro.unscoped.all()
    serializer_class = CilindroSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            'modelo', 'gas_dedicado', 'cliente_posse_atual', 'envase_atual', 'recebimento_externo_atual'
        )
        params = self.request.query_params

        search = params.get('search') or params.get('q')
        if search:
            termo = search.strip()
            qs = qs.filter(Q(codigo_qr__icontains=termo) | Q(numero_serie_ogiva__icontains=termo) | Q(fabricante__icontains=termo))

        qr_code = params.get('qr_code')
        if qr_code:
            qs = qs.filter(codigo_qr__iexact=qr_code.strip())

        status_val = params.get('status')
        if status_val:
            qs = qs.filter(status=status_val.strip())

        propriedade_val = params.get('propriedade')
        if propriedade_val:
            qs = qs.filter(propriedade=propriedade_val.strip())

        gas_val = params.get('gas')
        if gas_val:
            if gas_val.isdigit():
                qs = qs.filter(gas_dedicado_id=int(gas_val))
            else:
                qs = qs.filter(gas_dedicado__sigla__iexact=gas_val.strip())

        bloqueio_val = params.get('bloqueio_sanitario')
        if bloqueio_val is not None:
            if bloqueio_val.lower() in ('true', '1'):
                qs = qs.filter(bloqueio_sanitario=True)
            elif bloqueio_val.lower() in ('false', '0'):
                qs = qs.filter(bloqueio_sanitario=False)

        reteste_val = params.get('reteste_vencido')
        if reteste_val is not None:
            today = timezone.now().date()
            if reteste_val.lower() in ('true', '1'):
                qs = qs.filter(data_proximo_reteste__lt=today)
            elif reteste_val.lower() in ('false', '0'):
                qs = qs.filter(data_proximo_reteste__gte=today)

        filtro = params.get('filtro')
        if filtro == 'extravio_candidato':
            limite = timezone.now() - datetime.timedelta(days=180)
            qs = qs.filter(status='EM_POSSE_CLIENTE', posse_desde__lte=limite)

        return qs

    @action(detail=True, methods=['post'], url_path='reclassificar')
    def reclassificar(self, request, pk=None):
        """
        Executa a reclassificação auditada do gás do cilindro (ex: Industrial para Medicinal).
        Se o gás de destino for medicinal, exige aprovação exclusiva de RESPONSAVEL_TECNICO.
        """
        cilindro = self.get_object()
        novo_gas_id = request.data.get('novo_gas_id')
        if not novo_gas_id:
            return Response({'error': 'Campo novo_gas_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            novo_gas = GasQuimico.objects.get(pk=novo_gas_id)
        except GasQuimico.DoesNotExist:
            return Response({'error': 'Gás químico não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        descontaminacao = _parse_bool(request.data.get('descontaminacao_purga_executada'), default=False)
        troca_valvula = _parse_bool(request.data.get('troca_valvula_executada'), default=False)
        adequacao_pintura = _parse_bool(request.data.get('adequacao_pintura_executada'), default=False)
        nova_cor = request.data.get('nova_cor_padrao', '')
        observacoes = request.data.get('observacoes', '')
        homologado_por_rt_id = request.data.get('homologado_por_rt_id')

        homologado_por_rt = None
        current_tenant = getattr(request, 'tenant', None)
        if homologado_por_rt_id:
            homologado_por_rt = ResponsavelTecnico.objects.filter(pk=homologado_por_rt_id, tenant=current_tenant).first()
        elif hasattr(request, 'membership') and request.membership and request.membership.papel == 'RESPONSAVEL_TECNICO':
            homologado_por_rt = ResponsavelTecnico.objects.filter(user=request.user, tenant=current_tenant, ativo=True).first()

        try:
            res = reclassificar_cilindro_gas(
                cilindro=cilindro,
                novo_gas=novo_gas,
                usuario=request.user,
                descontaminacao_purga_executada=descontaminacao,
                troca_valvula_executada=troca_valvula,
                adequacao_pintura_executada=adequacao_pintura,
                nova_cor_padrao=nova_cor,
                homologado_por_rt=homologado_por_rt,
                observacoes=observacoes
            )
            reclassificacao = res[1] if isinstance(res, tuple) else res
            return Response(ReclassificacaoCilindroSerializer(reclassificacao).data, status=status.HTTP_200_OK)
        except PermissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='bloqueio-sanitario')
    def gerenciar_bloqueio_sanitario(self, request, pk=None):
        """
        Aciona ou libera o Bloqueio Sanitário ANVISA no cilindro.
        Ação restrita exclusivamente a usuários com papel de RESPONSAVEL_TECNICO (CRF/CRQ).
        Exige motivo/justificativa técnica gravada em auditoria imutável.
        """
        cilindro = self.get_object()
        acao = str(request.data.get('acao', '')).strip().upper()
        motivo = request.data.get('motivo') or request.data.get('justificativa', '')

        if acao not in ('BLOQUEIO', 'DESBLOQUEIO'):
            return Response(
                {'error': "Campo 'acao' inválido. Valores aceitos: 'BLOQUEIO' ou 'DESBLOQUEIO'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not motivo or not str(motivo).strip():
            return Response(
                {'error': "Justificativa/motivo técnico é obrigatório para registrar a auditoria sanitária."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            if acao == 'BLOQUEIO':
                cil, aud = acionar_bloqueio_sanitario(
                    cilindro=cilindro,
                    motivo=motivo,
                    usuario=request.user
                )
            else:
                cil, aud = liberar_bloqueio_sanitario(
                    cilindro=cilindro,
                    justificativa=motivo,
                    usuario=request.user
                )

            return Response({
                'cilindro': CilindroSerializer(cil).data,
                'auditoria': AuditoriaBloqueioSanitarioSerializer(aud).data
            }, status=status.HTTP_200_OK)
        except PermissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='auditorias-bloqueio')
    def listar_auditorias_bloqueio(self, request, pk=None):
        """
        Retorna a trilha de auditoria completa de bloqueios e liberações sanitárias do cilindro.
        """
        cilindro = self.get_object()
        auditorias = cilindro.auditorias_bloqueio.all().order_by('-criado_em')
        return Response(AuditoriaBloqueioSanitarioSerializer(auditorias, many=True).data)

    @action(detail=True, methods=['get'], url_path='timeline')
    def timeline(self, request, pk=None):
        """
        Retorna a timeline cronológica completa de todas as movimentações do cilindro no Ledger.
        """
        cilindro = self.get_object()
        movs = cilindro.movimentacoes.select_related(
            'cliente', 'entrega', 'registrado_por', 'estorna_movimentacao', 'envase_cilindro'
        ).order_by('-registrado_em')
        return Response(MovimentacaoCilindroSerializer(movs, many=True).data)

    @action(detail=True, methods=['post'], url_path='retorno-reteste')
    def registrar_retorno_reteste(self, request, pk=None):
        """
        Registra o retorno aprovado de reteste hidrostático com atualização de datas e tara.
        """
        cilindro = self.get_object()
        data_reteste_str = request.data.get('nova_data_reteste')
        if not data_reteste_str:
            return Response({'error': 'Campo nova_data_reteste é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            nova_data_reteste = datetime.date.fromisoformat(str(data_reteste_str).strip())
        except ValueError:
            return Response({'error': 'Formato inválido de nova_data_reteste. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        data_prox_str = request.data.get('nova_data_proximo_reteste')
        nova_data_proximo = None
        if data_prox_str:
            try:
                nova_data_proximo = datetime.date.fromisoformat(str(data_prox_str).strip())
            except ValueError:
                pass

        tara_str = request.data.get('nova_tara_kg')
        nova_tara = None
        if tara_str is not None and str(tara_str).strip() != '':
            try:
                nova_tara = float(tara_str)
            except ValueError:
                return Response({'error': 'Valor de nova_tara_kg inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        observacao = request.data.get('observacao', '')

        try:
            cil, mov = retornar_de_reteste(
                cilindro_id=cilindro.id,
                nova_data_reteste=nova_data_reteste,
                nova_data_proximo_reteste=nova_data_proximo,
                nova_tara_kg=nova_tara,
                usuario=request.user,
                observacao=observacao
            )
            return Response({
                'cilindro': CilindroSerializer(cil).data,
                'movimentacao': MovimentacaoCilindroSerializer(mov).data
            }, status=status.HTTP_200_OK)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='estorno')
    def estornar(self, request, pk=None):
        """
        Lança um estorno auditado de movimentação incorreta no ledger (Fase 1).
        Exclusivo para ADMIN, GERENTE e RESPONSAVEL_TECNICO.
        """
        cilindro = self.get_object()
        movimentacao_id = request.data.get('movimentacao_id')
        justificativa = request.data.get('justificativa')

        if not movimentacao_id:
            return Response({'error': 'Campo movimentacao_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)
        if not justificativa or not str(justificativa).strip():
            return Response({'error': 'Justificativa do estorno é obrigatória.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            cil, mov_estorno = estornar_movimentacao_ledger(
                movimentacao_id=movimentacao_id,
                usuario=request.user,
                justificativa=justificativa
            )
            return Response({
                'cilindro': CilindroSerializer(cil).data,
                'movimentacao_estorno': MovimentacaoCilindroSerializer(mov_estorno).data
            }, status=status.HTTP_200_OK)
        except PermissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class EnvaseCilindroViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para consulta histórica de Envases com isolamento estrito de Tenant.
    """
    queryset = EnvaseCilindro.unscoped.all()
    serializer_class = EnvaseCilindroSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().select_related(
            'cilindro', 'lote', 'operador'
        )


class InspecaoPreEnvaseViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para auditoria e histórico de Inspeções Pré-Envase (IN 129/2022).
    """
    queryset = InspecaoPreEnvase.unscoped.all()
    serializer_class = InspecaoPreEnvaseSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().select_related('cilindro', 'operador')


class RecebimentoCilindroCheioViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API endpoint para consulta de recebimento de cilindros cheios (RDC 887/2024).
    """
    queryset = RecebimentoCilindroCheio.unscoped.all()
    serializer_class = RecebimentoCilindroCheioSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().select_related(
            'cilindro', 'responsavel_recebimento', 'responsavel_tecnico'
        )


class ValidarCilindroRampaAPIView(TenantViewSetMixin, APIView):
    """
    Validação em tempo real para acoplamento na rampa de envase em batelada (IN 129/2022).
    Verifica reteste hidrostático, bloqueio sanitário, compatibilidade química de gás e status.
    """
    permission_classes = [CanOperateRampaEnvase]

    def post(self, request):
        codigo_qr = request.data.get('codigo_qr') or request.data.get('termo') or request.data.get('cilindro_id')
        lote_id = request.data.get('lote_id')

        if not codigo_qr:
            return Response({'error': 'Código QR / Nº de Série do cilindro é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)
        if not lote_id:
            return Response({'error': 'Lote de envase é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        current_tenant = getattr(request, 'tenant', None)
        tenant_id = current_tenant.id if current_tenant else None

        valido, motivo, cilindro, lote = validar_cilindro_para_rampa(
            cilindro_ou_id_ou_qr=codigo_qr,
            lote_id=lote_id,
            tenant_id=tenant_id
        )

        cil_data = None
        if cilindro:
            cil_data = CilindroSerializer(cilindro).data

        return Response({
            'valido': valido,
            'motivo': motivo,
            'cilindro': cil_data,
            'lote_codigo': lote.codigo_lote if lote else None,
            'gas_nome': lote.gas.nome if lote and lote.gas else None
        }, status=status.HTTP_200_OK)


class RegistrarEnvaseAPIView(TenantViewSetMixin, APIView):
    """
    Endpoint para registro operacional de envase individual com Checklist Pré-Envase (IN 129/2022).
    Apenas operadores de pátio, RTs ou administradores do tenant podem operar.
    """
    permission_classes = [CanOperateRampaEnvase]

    def post(self, request):
        cilindro_id = request.data.get('cilindro_id')
        codigo_qr = request.data.get('codigo_qr')
        lote_id = request.data.get('lote_id')
        pressao_final_bar = request.data.get('pressao_final_bar')

        valvula_integra = _parse_bool(request.data.get('valvula_integra'), default=True)
        pressao_residual_positiva = _parse_bool(request.data.get('pressao_residual_positiva'), default=True)
        pintura_cor_padrao_ok = _parse_bool(request.data.get('pintura_cor_padrao_ok'), default=True)
        rotulo_identificacao_ok = _parse_bool(request.data.get('rotulo_identificacao_ok'), default=True)
        observacoes_inspecao = request.data.get('observacoes_inspecao', '')
        observacoes_envase = request.data.get('observacoes_envase', '')

        cilindro = None
        if cilindro_id:
            cilindro = Cilindro.objects.filter(pk=cilindro_id).first()
        elif codigo_qr:
            cilindro = Cilindro.objects.filter(codigo_qr__iexact=str(codigo_qr).strip()).first()

        if not cilindro:
            return Response({'error': 'Cilindro não encontrado no tenant atual.'}, status=status.HTTP_404_NOT_FOUND)

        if not lote_id:
            return Response({'error': 'ID do lote é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        lote = LoteEnvase.objects.filter(pk=lote_id).first()
        if not lote:
            return Response({'error': 'Lote de envase não encontrado no tenant atual.'}, status=status.HTTP_404_NOT_FOUND)

        if not pressao_final_bar:
            return Response({'error': 'Pressão final (bar) é obrigatória.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            res = registrar_envase_cilindro(
                cilindro=cilindro,
                lote=lote,
                operador=request.user,
                pressao_final_bar=int(pressao_final_bar),
                valvula_integra=bool(valvula_integra),
                pressao_residual_positiva=bool(pressao_residual_positiva),
                pintura_cor_padrao_ok=bool(pintura_cor_padrao_ok),
                rotulo_identificacao_ok=bool(rotulo_identificacao_ok),
                observacoes_inspecao=observacoes_inspecao,
                observacoes_envase=observacoes_envase
            )
            envase = res[1] if isinstance(res, tuple) else res
            return Response(EnvaseCilindroSerializer(envase).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class RegistrarEnvaseBateladaAPIView(TenantViewSetMixin, APIView):
    """
    Conclusão atômica da batelada de envase na rampa com checklist IN 129/2022.
    """
    permission_classes = [CanOperateRampaEnvase]

    def post(self, request):
        lote_id = request.data.get('lote_id')
        pressao_final_bar = request.data.get('pressao_final_bar')
        itens = request.data.get('itens', [])
        observacoes_batelada = request.data.get('observacoes_batelada', '')

        if not lote_id:
            return Response({'error': 'ID do Lote de envase é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)
        if not pressao_final_bar:
            return Response({'error': 'Pressão final da rampa (bar) é obrigatória.'}, status=status.HTTP_400_BAD_REQUEST)
        if not itens or not isinstance(itens, list):
            return Response({'error': 'A lista de cilindros (itens) é obrigatória e deve conter ao menos 1 cilindro.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lote, envases, movs = registrar_envase_batelada(
                lote_id=lote_id,
                pressao_final_bar=int(pressao_final_bar),
                itens=itens,
                usuario=request.user,
                observacoes_batelada=observacoes_batelada
            )

            return Response({
                'sucesso': True,
                'total_envasados': len(envases),
                'lote_codigo': lote.codigo_lote,
                'lote_id': lote.id,
                'pressao_final_bar': int(pressao_final_bar),
                'envases': EnvaseCilindroSerializer(envases, many=True).data
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class EtiquetasColarinhoAPIView(TenantViewSetMixin, APIView):
    """
    Gera as etiquetas de colarinho regulamentares (ABNT NBR 12176 / IN 129/2022)
    para impressão imediata após a conclusão da batelada de envase.
    """
    permission_classes = [IsTenantMember]

    def get(self, request):
        envase_ids = request.query_params.get('envase_ids')
        lote_id = request.query_params.get('lote_id')

        qs = EnvaseCilindro.objects.select_related(
            'cilindro__gas_dedicado', 'cilindro__modelo', 'lote__gas', 'lote__responsavel_tecnico_fk', 'operador'
        )

        if envase_ids:
            ids = [int(x.strip()) for x in envase_ids.split(',') if x.strip().isdigit()]
            qs = qs.filter(id__in=ids)
        elif lote_id:
            qs = qs.filter(lote_id=int(lote_id))
        else:
            return Response({'error': 'Informe envase_ids ou lote_id.'}, status=status.HTTP_400_BAD_REQUEST)

        current_tenant = getattr(request, 'tenant', None)
        empresa_nome = current_tenant.nome_fantasia if current_tenant else 'GasManagementApp'
        empresa_cnpj = current_tenant.cnpj if current_tenant else ''

        etiquetas = []
        for env in qs:
            lote = env.lote
            cil = env.cilindro
            gas = cil.gas_dedicado

            rt_nome = lote.rt_nome_snapshot or (lote.responsavel_tecnico_fk.nome_completo if lote.responsavel_tecnico_fk else lote.responsavel_tecnico)
            rt_reg = lote.rt_registro_snapshot or (f"{lote.responsavel_tecnico_fk.conselho_classe} {lote.responsavel_tecnico_fk.numero_registro}" if lote.responsavel_tecnico_fk else 'RT-ANVISA')

            etiquetas.append({
                'envase_id': env.id,
                'lote_codigo': lote.codigo_lote,
                'gas_nome': gas.nome,
                'gas_sigla': gas.sigla,
                'gas_formula': getattr(gas, 'formula_quimica', gas.sigla),
                'cor_padrao_abnt': gas.cor_padrao_abnt,
                'categoria': gas.categoria,
                'numero_onu': gas.numero_onu,
                'classe_risco': gas.classe_risco,
                'pureza_percentual': float(lote.pureza_percentual),
                'data_envase': env.envasado_em.strftime('%d/%m/%Y %H:%M'),
                'data_validade': lote.data_validade.strftime('%d/%m/%Y'),
                'pressao_final_bar': env.pressao_final_bar,
                'rt_nome': rt_nome,
                'rt_registro': rt_reg,
                'cilindro_qr': cil.codigo_qr,
                'cilindro_serie': cil.numero_serie_ogiva,
                'modelo_descricao': cil.modelo.descricao,
                'volume_litros': float(cil.modelo.volume_hidraulico_litros),
                'tara_kg': float(cil.tara_real_kg) if cil.tara_real_kg else None,
                'data_proximo_reteste': cil.data_proximo_reteste.strftime('%d/%m/%Y'),
                'empresa_nome': empresa_nome,
                'empresa_cnpj': empresa_cnpj,
                'normas': 'ABNT NBR 12176 / IN nº 129/2022 - ANVISA'
            })

        return Response(etiquetas, status=status.HTTP_200_OK)


class ReceberCilindroCheioAPIView(TenantViewSetMixin, APIView):
    """
    Endpoint para recebimento de cilindros cheios de fornecedores externos (RDC 887/2024).
    Suporta entrada individual ou em lote (múltiplos cascos na mesma NF e Lote de fornecedor).
    """
    permission_classes = [CanOperateRampaEnvase]

    def post(self, request):
        cilindros = request.data.get('cilindros') or request.data.get('cilindro_ids')
        cilindro_id = request.data.get('cilindro_id')
        codigo_qr = request.data.get('codigo_qr')
        fornecedor_nome = request.data.get('fornecedor_nome')
        fornecedor_cnpj = request.data.get('fornecedor_cnpj')
        nota_fiscal = request.data.get('nota_fiscal')
        lote_fornecedor = request.data.get('lote_fornecedor')
        data_envase_origem = request.data.get('data_envase_origem')
        data_validade = request.data.get('data_validade')
        pressao_recebimento_bar = request.data.get('pressao_recebimento_bar')
        laudo_pdf = request.FILES.get('laudo_pdf')
        responsavel_tecnico_id = request.data.get('responsavel_tecnico_id')
        observacoes = request.data.get('observacoes', '')

        if not all([fornecedor_nome, fornecedor_cnpj, nota_fiscal, lote_fornecedor, data_envase_origem, data_validade]):
            return Response(
                {'error': 'Campos fornecedor_nome, fornecedor_cnpj, nota_fiscal, lote_fornecedor, data_envase_origem e data_validade são obrigatórios.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        rt = None
        current_tenant = getattr(request, 'tenant', None)
        if responsavel_tecnico_id:
            rt = ResponsavelTecnico.objects.filter(pk=responsavel_tecnico_id, tenant=current_tenant).first()

        # Caso 1: Entrada em Lote (lista de cilindros)
        if cilindros:
            if isinstance(cilindros, str):
                try:
                    import json
                    cilindros = json.loads(cilindros)
                except Exception:
                    cilindros = [x.strip() for x in cilindros.split(',') if x.strip()]

            if isinstance(cilindros, list) and len(cilindros) > 0:
                resolved_ids = []
                for item in cilindros:
                    if isinstance(item, int) or (isinstance(item, str) and item.isdigit()):
                        c = Cilindro.objects.filter(pk=int(item)).first()
                    else:
                        c = Cilindro.objects.filter(
                            models.Q(codigo_qr__iexact=str(item).strip()) | models.Q(numero_serie_ogiva__iexact=str(item).strip())
                        ).first()
                    if not c:
                        return Response({'error': f"Cilindro '{item}' não localizado no tenant."}, status=status.HTTP_404_NOT_FOUND)
                    resolved_ids.append(c.id)

                try:
                    recs, movs = receber_cilindros_fornecedor_batelada(
                        cilindro_ids=resolved_ids,
                        fornecedor_nome=fornecedor_nome,
                        fornecedor_cnpj=fornecedor_cnpj,
                        nota_fiscal=nota_fiscal,
                        lote_fornecedor=lote_fornecedor,
                        data_envase_origem=data_envase_origem,
                        data_validade=data_validade,
                        pressao_recebimento_bar=int(pressao_recebimento_bar) if pressao_recebimento_bar else 200,
                        laudo_pdf=laudo_pdf,
                        usuario=request.user,
                        responsavel_tecnico=rt,
                        observacoes=observacoes
                    )
                    return Response({
                        'sucesso': True,
                        'total_recebidos': len(recs),
                        'recebimentos': RecebimentoCilindroCheioSerializer(recs, many=True).data
                    }, status=status.HTTP_201_CREATED)
                except ValidationError as e:
                    msg = e.message if hasattr(e, 'message') else str(e)
                    return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Caso 2: Entrada Individual
        cilindro = None
        if cilindro_id:
            cilindro = Cilindro.objects.filter(pk=cilindro_id).first()
        elif codigo_qr:
            cilindro = Cilindro.objects.filter(codigo_qr__iexact=str(codigo_qr).strip()).first()

        if not cilindro:
            return Response({'error': 'Cilindro não encontrado no tenant atual.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            res = receber_cilindro_cheio_fornecedor(
                cilindro=cilindro,
                fornecedor_nome=fornecedor_nome,
                fornecedor_cnpj=fornecedor_cnpj,
                nota_fiscal=nota_fiscal,
                lote_fornecedor=lote_fornecedor,
                data_envase_origem=data_envase_origem,
                data_validade=data_validade,
                responsavel_recebimento=request.user,
                pressao_recebimento_bar=int(pressao_recebimento_bar) if pressao_recebimento_bar else None,
                laudo_pdf=laudo_pdf,
                responsavel_tecnico=rt,
                observacoes=observacoes
            )
            recebimento = res[1] if isinstance(res, tuple) else res
            return Response(RecebimentoCilindroCheioSerializer(recebimento).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class DownloadLaudoLoteView(TenantViewSetMixin, APIView):
    """
    Download seguro e autenticado do laudo de análise (PDF) do lote de envase.
    Garante validação estrita de isolamento multi-tenant (nunca exposto sem autenticação).
    """
    permission_classes = [IsTenantMember]

    def get(self, request, pk):
        lote = LoteEnvase.objects.filter(pk=pk).first()
        if not lote or not lote.laudo_pdf:
            return Response({'error': 'Laudo não encontrado para este lote no tenant atual.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            response = FileResponse(lote.laudo_pdf.open('rb'), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="laudo_lote_{lote.codigo_lote}.pdf"'
            return response
        except (FileNotFoundError, ValueError):
            return Response({'error': 'Arquivo de laudo não encontrado no armazenamento.'}, status=status.HTTP_404_NOT_FOUND)


class DownloadLaudoRecebimentoView(TenantViewSetMixin, APIView):
    """
    Download seguro e autenticado do laudo de análise de cilindro recebido de fornecedor.
    Garante validação estrita de isolamento multi-tenant.
    """
    permission_classes = [IsTenantMember]

    def get(self, request, pk):
        rec = RecebimentoCilindroCheio.objects.filter(pk=pk).first()
        if not rec or not rec.laudo_pdf:
            return Response({'error': 'Laudo de recebimento não encontrado no tenant atual.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            response = FileResponse(rec.laudo_pdf.open('rb'), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="laudo_recebimento_{rec.lote_fornecedor}.pdf"'
            return response
        except (FileNotFoundError, ValueError):
            return Response({'error': 'Arquivo de laudo não encontrado no armazenamento.'}, status=status.HTTP_404_NOT_FOUND)


class ProdutoTemplateView(LoginRequiredMixin, TemplateView):
    """
    View to render the Produto frontend page with modal.
    """
    template_name = 'produtos/index.html'


class LotesAnvisaListAPIView(TenantViewSetMixin, APIView):
    """
    API para listagem dos Lotes Químicos/Medicinais do tenant ativo.
    Alimenta selects, filtros e autocomplete do painel de rastreabilidade ANVISA.
    """
    permission_classes = [IsTenantMember]

    def get(self, request):
        lotes = LoteEnvase.objects.select_related('gas', 'responsavel_tecnico_fk').order_by('-data_envase')
        data = []
        for l in lotes:
            data.append({
                'id': l.id,
                'codigo_lote': l.codigo_lote,
                'gas_nome': l.gas.nome,
                'gas_sigla': l.gas.sigla,
                'data_envase': l.data_envase.strftime('%d/%m/%Y'),
                'data_validade': l.data_validade.strftime('%d/%m/%Y'),
                'pureza_percentual': float(l.pureza_percentual),
                'responsavel_tecnico': l.responsavel_tecnico,
                'rt_nome_snapshot': l.rt_nome_snapshot,
                'rt_conselho_snapshot': l.rt_conselho_snapshot,
                'rt_registro_snapshot': l.rt_registro_snapshot,
                'esta_vencido': l.esta_vencido,
                'total_cilindros': l.cilindros_envasados.count()
            })
        return Response(data)


class LoteEnvaseViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    API endpoint para gestão e consulta de Lotes de Envase com isolamento de Tenant.
    Permite alteração de qualidade ('QUARENTENA', 'APROVADO', 'REPROVADO') restrita ao RT.
    """
    queryset = LoteEnvase.unscoped.all()
    serializer_class = LoteEnvaseSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().select_related('gas', 'responsavel_tecnico_fk')

    @action(detail=True, methods=['post'], url_path='qualidade')
    def atualizar_qualidade(self, request, pk=None):
        """
        Altera o status de qualidade do lote. Se REPROVADO, aciona bloqueio sanitário
        automático em todos os cilindros com carga ativa deste lote. Ação privativa do RT.
        """
        lote = self.get_object()
        novo_status = str(request.data.get('novo_status', '')).strip().upper()
        justificativa = request.data.get('justificativa', '')

        try:
            lote_atualizado = atualizar_qualidade_lote(
                lote=lote,
                novo_status=novo_status,
                justificativa=justificativa,
                usuario=request.user
            )
            return Response(LoteEnvaseSerializer(lote_atualizado).data, status=status.HTTP_200_OK)
        except PermissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class RecallCampanhaViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    API endpoint para abertura, homologação pelo RT e acompanhamento de Campanhas de Recall.
    """
    queryset = RecallCampanha.unscoped.all()
    serializer_class = RecallCampanhaSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return super().get_queryset().select_related(
            'lote', 'lote__gas', 'criado_por', 'homologado_por_rt'
        ).prefetch_related('itens_cliente__cliente', 'itens_cliente__cilindro')

    def create(self, request, *args, **kwargs):
        lote_id = request.data.get('lote_id') or request.data.get('lote')
        codigo_campanha = request.data.get('codigo_campanha')
        motivo = request.data.get('motivo')
        texto_notificacao = request.data.get('texto_notificacao', '')

        if not (lote_id and codigo_campanha and motivo):
            return Response(
                {'error': "Campos 'lote_id', 'codigo_campanha' e 'motivo' são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            campanha = abrir_campanha_recall(
                lote_id=lote_id,
                codigo_campanha=codigo_campanha,
                motivo=motivo,
                texto_notificacao=texto_notificacao,
                usuario=request.user
            )
            return Response(RecallCampanhaSerializer(campanha).data, status=status.HTTP_201_CREATED)
        except PermissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='homologar')
    def homologar(self, request, pk=None):
        """
        Homologação formal pelo RT antes do disparo das notificações aos clientes.
        """
        campanha = self.get_object()
        try:
            camp = homologar_campanha_recall(
                campanha=campanha,
                usuario=request.user
            )
            return Response(RecallCampanhaSerializer(camp).data, status=status.HTTP_200_OK)
        except PermissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            msg = e.message if hasattr(e, 'message') else str(e)
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='dossie')
    def obter_dossie(self, request, pk=None):
        """
        Retorna o dossiê completo de rastreabilidade (contenção ativa e exposição passada) do lote da campanha.
        """
        campanha = self.get_object()
        dossie = obter_dossie_recall_lote(campanha.lote_id, tenant_id=campanha.tenant_id)
        if not dossie:
            return Response({'error': 'Lote não localizado.'}, status=status.HTTP_404_NOT_FOUND)
        data = {k: v for k, v in dossie.items() if k != 'lote_obj'}
        return Response(data)


class ItemRecallClienteViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    API endpoint para acompanhamento e registro de confirmações de recolhimento de cilindros por cliente.
    """
    queryset = ItemRecallCliente.unscoped.all()
    serializer_class = ItemRecallClienteSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            'campanha', 'cliente', 'cilindro', 'envase_cilindro'
        )
        campanha_id = self.request.query_params.get('campanha_id')
        if campanha_id:
            qs = qs.filter(campanha_id=campanha_id)
        tipo = self.request.query_params.get('tipo_exposicao')
        if tipo:
            qs = qs.filter(tipo_exposicao=tipo)
        status_val = self.request.query_params.get('status_notificacao')
        if status_val:
            qs = qs.filter(status_notificacao=status_val)
        return qs

    @action(detail=True, methods=['post'], url_path='confirmar-recolhimento')
    def confirmar_recolhimento(self, request, pk=None):
        """
        Registra formalmente a confirmação de recolhimento ou declaração de consumo pelo cliente.
        """
        item = self.get_object()
        novo_status = request.data.get('status_notificacao', 'RECOLHIDO')
        observacoes = request.data.get('observacoes', '')

        if novo_status not in [c[0] for c in ItemRecallCliente.STATUS_NOTIFICACAO_CHOICES]:
            return Response({'error': f'Status inválido: {novo_status}'}, status=status.HTTP_400_BAD_REQUEST)

        item.status_notificacao = novo_status
        if novo_status == 'RECOLHIDO':
            item.recolhido_em = timezone.now()
        elif novo_status == 'NOTIFICADO' and not item.notificado_em:
            item.notificado_em = timezone.now()

        if observacoes:
            item.observacoes = (item.observacoes + "\n" + observacoes).strip()

        item.save(update_fields=['status_notificacao', 'recolhido_em', 'notificado_em', 'observacoes'])
        return Response(ItemRecallClienteSerializer(item).data, status=status.HTTP_200_OK)


class LoteRecallAPIView(TenantViewSetMixin, APIView):
    """
    Motor de Auditoria e Recall Farmacêutico ANVISA em 1 Clique.
    Conforme RDC nº 658/2022, IN nº 129/2022, RDC nº 870/2024, RDC nº 887/2024 (ANVISA) e Resolução CFF nº 731/2022.
    Retorna com precisão:
    1. Contenção Operacional (Risco Ativo): Cilindros atualmente com a carga física do lote.
    2. Dossiê de Exposição Histórica: Todas as entregas passadas no Ledger vinculadas àquele lote (zero falso positivo).
    Gera Dossiê de Rastreabilidade e Recall em CSV delimitado por ';'.
    """
    permission_classes = [IsTenantMember]

    def get(self, request):
        codigo_lote = request.query_params.get('codigo_lote', '').strip()
        export = request.query_params.get('export', '').strip().lower()

        if not codigo_lote:
            return Response({'error': 'Parâmetro codigo_lote é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        current_tenant = getattr(request, 'tenant', None)
        tenant_id = current_tenant.id if current_tenant else None
        dossie = obter_dossie_recall_lote(codigo_lote, tenant_id=tenant_id)

        if not dossie:
            return Response({'error': f'Lote "{codigo_lote}" não encontrado no tenant atual.'}, status=status.HTTP_404_NOT_FOUND)

        lote_info = dossie['lote']
        contencao_operacional = dossie['contencao_operacional']
        exposicao_historica = dossie['exposicao_historica']
        cilindros_data = dossie['cilindros']
        metricas = dossie['metricas']

        if export == 'csv':
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="Dossie_Rastreabilidade_Recall_Lote_{lote_info["codigo_lote"]}.csv"'
            response.write('\ufeff')

            writer = csv.writer(response, delimiter=';')
            writer.writerow(['DOSSIÊ DE RASTREABILIDADE E RECALL SANITÁRIO (RDC nº 658/2022, IN nº 129/2022, RDC nº 870/2024, RDC nº 887/2024 - ANVISA)'])
            writer.writerow([f"Lote: {lote_info['codigo_lote']}", f"Gás: {lote_info['gas_nome']} ({lote_info['gas_sigla']})", f"Status Qualidade: {lote_info['status_qualidade_display']}", f"Validade: {lote_info['data_validade']}"])
            writer.writerow([])

            # SEÇÃO 1: CONTENÇÃO OPERACIONAL (RISCO ATIVO)
            writer.writerow(['--- SEÇÃO 1: CONTENÇÃO OPERACIONAL (RISCO ATIVO E RECOLHIMENTO FÍSICO) ---'])
            writer.writerow([
                'Código Lote', 'Gás', 'Sigla', 'Código QR', 'Nº Série Ogiva', 'Modelo', 'Pressão (bar)',
                'Data Envase', 'Operador', 'Status Atual', 'Envase Ativo?', 'Bloqueio Sanitário', 'Localização Atual',
                'Ação Necessária', 'Cliente em Posse', 'CNPJ Cliente', 'Telefone Cliente', 'Endereço Completo', 'Posse Desde'
            ])
            for item in contencao_operacional:
                cli = item['cliente'] or {}
                writer.writerow([
                    lote_info['codigo_lote'],
                    lote_info['gas_nome'],
                    lote_info['gas_sigla'],
                    item['codigo_qr'],
                    item['numero_serie_ogiva'],
                    item['modelo'],
                    item['pressao_final_bar'],
                    item['envasado_em'],
                    item['operador'],
                    item['status_atual_display'],
                    'Sim (Ativo)' if item['is_envase_ativo'] else 'Não (Histórico Encerrado)',
                    'Sim (Bloqueado)' if item['bloqueio_sanitario'] else 'Não',
                    item['local_descricao'],
                    item['acao_necessaria'],
                    cli.get('nome', 'N/A'),
                    cli.get('cnpj', 'N/A'),
                    cli.get('telefone', 'N/A'),
                    cli.get('endereco', 'N/A'),
                    item['posse_desde']
                ])

            writer.writerow([])
            # SEÇÃO 2: DOSSIÊ DE EXPOSIÇÃO HISTÓRICA
            writer.writerow(['--- SEÇÃO 2: DOSSIÊ DE EXPOSIÇÃO HISTÓRICA (REGISTRO OFICIAL ANVISA DE ENTREGAS A CLIENTES) ---'])
            writer.writerow([
                'Código Lote', 'Gás', 'Data da Entrega', 'Doc Fiscal / NF-e', 'Cliente Atendido', 'CNPJ Cliente',
                'Telefone Cliente', 'Endereço', 'Nº Série Ogiva', 'Código QR', 'Modelo', 'Operador da Entrega',
                'Status Atual do Cilindro', 'Carga Atual do Cilindro', 'Situação da Exposição'
            ])
            for exp in exposicao_historica:
                cli = exp['cliente']
                writer.writerow([
                    lote_info['codigo_lote'],
                    lote_info['gas_nome'],
                    exp['data_entrega'],
                    exp['documento_fiscal_ref'],
                    cli['nome'],
                    cli['cnpj'],
                    cli['telefone'],
                    cli['endereco'],
                    exp['numero_serie_ogiva'],
                    exp['codigo_qr'],
                    exp['modelo'],
                    exp['operador'],
                    exp['status_atual_display'],
                    f"Lote {exp['lote_atual_cilindro']}" if exp['lote_atual_cilindro'] else "Vazio / Sem Carga",
                    'RISCO ATIVO (Cilindro ainda em uso com este lote)' if exp['is_envase_ativo'] else 'EXPOSIÇÃO ENCERRADA (Cilindro já devolvido/reenvasado)'
                ])
            return response

        data = {
            'lote': lote_info,
            'metricas': metricas,
            'contencao_operacional': contencao_operacional,
            'exposicao_historica': exposicao_historica,
            'cilindros': cilindros_data
        }
        return Response(data)


class RecallAnvisaTemplateView(LoginRequiredMixin, TemplateView):
    """
    Interface Visual de Auditoria, Rastreabilidade e Recall em 1 Clique.
    """
    template_name = 'produtos/recall_anvisa.html'


class SincronizarMovimentacoesOfflineAPIView(APIView):
    """
    Endpoint de sincronização em lote de movimentações offline (PWA - Sprint 6).
    Garante idempotência estrita via `client_uuid`:
    - Reenvios com o mesmo `client_uuid` retornam 'ja_processado' com HTTP 200 sem duplicar registros no Ledger.
    - Suporta entregas com comprovante de assinatura, recolhas com casco divergente e reteste vencido.
    """
    permission_classes = [IsMotoristaOrAdmin]

    def post(self, request):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            from core.tenancy import get_current_tenant
            tenant = get_current_tenant()
        if not tenant and hasattr(request.user, 'memberships'):
            m = request.user.memberships.filter(ativo=True).first()
            if m:
                tenant = m.tenant

        if not tenant:
            return Response({'error': 'Tenant não identificado para a sincronização.'}, status=status.HTTP_400_BAD_REQUEST)

        itens = request.data.get('itens') if isinstance(request.data, dict) else request.data
        if not isinstance(itens, list):
            return Response({'error': 'Formato inválido. Envie uma lista no campo "itens".'}, status=status.HTTP_400_BAD_REQUEST)

        resultado = sincronizar_movimentacoes_offline(
            tenant_id=tenant.id,
            itens_sync=itens,
            usuario=request.user
        )

        return Response(resultado, status=status.HTTP_200_OK)


# ==============================================================================
# PASSAPORTE SANITÁRIO PÚBLICO & ETIQUETAS TÉRMICAS (FASE FINAL CONSOLIDAÇÃO)
# ==============================================================================
import io
import base64
import hashlib
from django.views import View
from django.shortcuts import get_object_or_404, render
from django.http import Http404


class PassaporteSanitarioPublicoView(TemplateView):
    """
    Passaporte Sanitário Público do Cilindro (Consulta via QR Code Hospitalar sem Login).
    Acessível por farmacêuticos hospitalares ou fiscais da ANVISA/VISA em /v/cilindro/<identificador>/
    ou /produtos/passaporte/<codigo_qr>/.
    Garante isolamento absoluto de dados: jamais expõe valores financeiros, contratos ou outros clientes.
    """
    template_name = 'produtos/passaporte_conformidade.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        identificador = (
            self.kwargs.get('identificador') or 
            self.kwargs.get('identificador_ou_token') or 
            self.kwargs.get('codigo_qr') or 
            ''
        ).strip()

        cilindro = Cilindro.unscoped.filter(
            Q(codigo_qr=identificador) | Q(numero_serie_ogiva=identificador)
        ).select_related(
            'modelo', 'gas_dedicado', 'tenant',
            'envase_atual__lote__responsavel_tecnico_fk',
            'recebimento_externo_atual'
        ).first()

        context['cilindro'] = cilindro
        context['codigo_qr'] = identificador

        if cilindro:
            hoje = timezone.now().date()
            motivos_bloqueio = []

            # 1. Checagem Estrutural & Reteste Hidrostático INMETRO
            if cilindro.bloqueio_sanitario:
                motivos_bloqueio.append(
                    f"Bloqueio sanitário preventivo ativo: {cilindro.motivo_bloqueio_sanitario or 'Em investigação / quarentena'}"
                )
            if cilindro.reteste_vencido:
                data_ret = cilindro.data_proximo_reteste.strftime('%d/%m/%Y') if cilindro.data_proximo_reteste else 'não informada'
                motivos_bloqueio.append(f"Validade do ensaio hidrostático (INMETRO) expirada desde {data_ret}")

            # 2. Checagem do Conteúdo / Carga Ativa
            tem_carga = False
            lote_ativo = None
            rt_ativo = None
            tem_laudo_pdf = False
            rec_ativo = None

            if cilindro.envase_atual and cilindro.envase_atual.lote:
                tem_carga = True
                lote_ativo = cilindro.envase_atual.lote
                rt_ativo = lote_ativo.responsavel_tecnico_fk
                tem_laudo_pdf = bool(lote_ativo.laudo_pdf)

                if lote_ativo.status_qualidade != 'APROVADO':
                    motivos_bloqueio.append(
                        f"Lote envasado {lote_ativo.codigo_lote} em status {lote_ativo.get_status_qualidade_display()} (reprovado/quarentena)"
                    )
                if lote_ativo.esta_vencido:
                    data_val = lote_ativo.data_validade.strftime('%d/%m/%Y') if lote_ativo.data_validade else 'N/D'
                    motivos_bloqueio.append(f"Validade farmacêutica do lote {lote_ativo.codigo_lote} expirada em {data_val}")

            elif cilindro.recebimento_externo_atual:
                tem_carga = True
                rec_ativo = cilindro.recebimento_externo_atual
                tem_laudo_pdf = bool(rec_ativo.laudo_pdf)
                if rec_ativo.data_validade and hoje > rec_ativo.data_validade:
                    data_val = rec_ativo.data_validade.strftime('%d/%m/%Y')
                    motivos_bloqueio.append(f"Validade da carga externa (Lote {rec_ativo.lote_fornecedor}) expirada em {data_val}")

            # 3. Status Geral Sanitário
            is_apto = (len(motivos_bloqueio) == 0)

            # 4. Perfil Regulatório do Tenant
            perfil_reg = getattr(cilindro.tenant, 'perfil_regulatorio', None)
            if not perfil_reg:
                from core.models import PerfilRegulatorioTenant
                perfil_reg = PerfilRegulatorioTenant.objects.filter(tenant=cilindro.tenant).first()

            if not rt_ativo and perfil_reg and perfil_reg.responsavel_tecnico_vigente:
                rt_ativo = perfil_reg.responsavel_tecnico_vigente

            # 5. Selo Canônico SHA-256
            raw_stamp = f"{cilindro.codigo_qr}:{cilindro.numero_serie_ogiva}:{cilindro.data_proximo_reteste}:{cilindro.gas_dedicado.sigla}:{'APTO' if is_apto else 'BLOQUEADO'}"
            hash_autenticidade = hashlib.sha256(raw_stamp.encode()).hexdigest()

            # 6. Mapeamento de Cores de Ogiva ABNT NBR 12176
            sigla_gas = (cilindro.gas_dedicado.sigla or '').upper()
            cor_ogiva_hex = "#059669"  # Verde esmeralda (Oxigênio Medicinal padrão)
            if 'IND' in sigla_gas:
                cor_ogiva_hex = "#10b981"
            elif 'N2' in sigla_gas:
                cor_ogiva_hex = "#64748b"
            elif 'AR' in sigla_gas and 'COMP' not in sigla_gas:
                cor_ogiva_hex = "#7c3aed"
            elif 'COMP' in sigla_gas:
                cor_ogiva_hex = "#0284c7"
            elif 'CO2' in sigla_gas:
                cor_ogiva_hex = "#334155"
            elif 'AC' in sigla_gas:
                cor_ogiva_hex = "#dc2626"

            # 7. Trilha Técnica Sanitária (Estritamente sem dados comerciais ou nomes de clientes)
            movimentacoes_sanitarias = MovimentacaoCilindro.unscoped.filter(
                cilindro=cilindro
            ).order_by('-registrado_em')[:8]

            context.update({
                'is_apto': is_apto,
                'motivos_bloqueio': motivos_bloqueio,
                'tem_carga': tem_carga,
                'lote_ativo': lote_ativo,
                'rec_ativo': rec_ativo,
                'rt_ativo': rt_ativo,
                'tem_laudo_pdf': tem_laudo_pdf,
                'laudo_download_url': f"/v/cilindro/{cilindro.codigo_qr}/laudo/",
                'perfil_reg': perfil_reg,
                'cor_ogiva_hex': cor_ogiva_hex,
                'hash_autenticidade': hash_autenticidade,
                'movimentacoes_sanitarias': movimentacoes_sanitarias,
            })

        return context


# Compatibilidade retroativa com testes da Fase 1
PassaporteConformidadeView = PassaporteSanitarioPublicoView


class PassaporteLaudoPublicoView(View):
    """
    Download público e seguro do laudo analítico em PDF da carga ativa do cilindro.
    Acessível via /v/cilindro/<identificador>/laudo/.
    """
    def get(self, request, identificador):
        identificador = identificador.strip()
        cilindro = Cilindro.unscoped.filter(
            Q(codigo_qr=identificador) | Q(numero_serie_ogiva=identificador)
        ).select_related('envase_atual__lote', 'recebimento_externo_atual').first()

        if not cilindro:
            raise Http404("Cilindro não encontrado.")

        arquivo_laudo = None
        nome_arquivo = f"laudo_cilindro_{cilindro.numero_serie_ogiva}.pdf"

        if cilindro.envase_atual and cilindro.envase_atual.lote and cilindro.envase_atual.lote.laudo_pdf:
            arquivo_laudo = cilindro.envase_atual.lote.laudo_pdf
            nome_arquivo = f"laudo_lote_{cilindro.envase_atual.lote.codigo_lote}.pdf"
        elif cilindro.recebimento_externo_atual and cilindro.recebimento_externo_atual.laudo_pdf:
            arquivo_laudo = cilindro.recebimento_externo_atual.laudo_pdf
            nome_arquivo = f"laudo_recebimento_{cilindro.recebimento_externo_atual.lote_fornecedor}.pdf"

        if not arquivo_laudo:
            raise Http404("Nenhum arquivo de laudo analítico em PDF associado à carga atual deste cilindro.")

        try:
            response = FileResponse(arquivo_laudo.open('rb'), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{nome_arquivo}"'
            return response
        except (FileNotFoundError, ValueError):
            raise Http404("Arquivo físico do laudo não localizado no armazenamento.")


class EtiquetaCascoView(LoginRequiredMixin, View):
    """
    Impressão de Etiqueta Patrimonial Térmica do Casco (60x40mm).
    Gera localmente QR Code apontando para o Passaporte Público.
    """
    def get(self, request, pk):
        cilindro = Cilindro.objects.filter(pk=pk).select_related('modelo', 'gas_dedicado', 'tenant').first()
        if not cilindro and request.user.is_superuser:
            cilindro = Cilindro.unscoped.filter(pk=pk).select_related('modelo', 'gas_dedicado', 'tenant').first()
        if not cilindro:
            raise Http404("Cilindro não encontrado.")

        import qrcode
        url_passaporte = request.build_absolute_uri(f"/v/cilindro/{cilindro.codigo_qr}/")
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(url_passaporte)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        qr_data_uri = f"data:image/png;base64,{qr_base64}"

        return render(request, 'produtos/etiqueta_casco.html', {
            'cilindro': cilindro,
            'qr_data_uri': qr_data_uri,
            'url_passaporte': url_passaporte,
            'tenant': cilindro.tenant,
        })


class EtiquetaColarinhoView(LoginRequiredMixin, View):
    """
    Impressão de Etiqueta Térmica de Gargalo/Colarinho de Envase (IN 129/2022 / ANVISA).
    Acionável a partir de LoteEnvase (lote_id) ou de Cilindro com envase ativo (cilindro_id).
    """
    def get(self, request, pk=None, lote_id=None, cilindro_id=None):
        target_lote_id = lote_id or (pk if 'lote' in request.path else None)
        target_cilindro_id = cilindro_id or (pk if 'cilindro' in request.path else None)

        lote = None
        cilindro = None
        pressao_bar = None

        if target_lote_id:
            lote = LoteEnvase.objects.filter(pk=target_lote_id).select_related('gas', 'responsavel_tecnico_fk', 'tenant').first()
            if not lote and request.user.is_superuser:
                lote = LoteEnvase.unscoped.filter(pk=target_lote_id).select_related('gas', 'responsavel_tecnico_fk', 'tenant').first()
            pressao_bar = 200
        elif target_cilindro_id:
            cilindro = Cilindro.objects.filter(pk=target_cilindro_id).select_related(
                'gas_dedicado', 'modelo', 'tenant', 'envase_atual__lote__responsavel_tecnico_fk', 'envase_atual__lote__gas'
            ).first()
            if not cilindro and request.user.is_superuser:
                cilindro = Cilindro.unscoped.filter(pk=target_cilindro_id).select_related(
                    'gas_dedicado', 'modelo', 'tenant', 'envase_atual__lote__responsavel_tecnico_fk', 'envase_atual__lote__gas'
                ).first()
            if cilindro and cilindro.envase_atual:
                lote = cilindro.envase_atual.lote
                pressao_bar = cilindro.envase_atual.pressao_final_bar or (cilindro.modelo.pressao_servico_bar if cilindro.modelo else 200)

        if not lote:
            raise Http404("Lote ou envase ativo não encontrado para impressão de colarinho.")

        gas = lote.gas
        tenant = lote.tenant
        rt = lote.responsavel_tecnico_fk
        if not rt and getattr(lote, 'rt_nome_snapshot', None):
            class RTSnapshot:
                def __init__(self, l):
                    self.nome_completo = l.rt_nome_snapshot
                    self.conselho_classe = l.rt_conselho_snapshot or 'CRF'
                    self.uf_conselho = 'SP'
                    self.numero_registro = l.rt_registro_snapshot or ''
            rt = RTSnapshot(lote)
        if not rt:
            perfil = getattr(tenant, 'perfil_regulatorio', None)
            if perfil:
                rt = perfil.responsavel_tecnico_vigente

        return render(request, 'produtos/etiqueta_colarinho.html', {
            'lote': lote,
            'cilindro': cilindro,
            'gas': gas,
            'tenant': tenant,
            'rt': rt,
            'pressao_bar': pressao_bar,
        })



