from datetime import date
from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsTenantMember
from core.guards import assert_modulo, assert_tenant_writable
from fiscal.permissions import (
    RequiresModuleFiscal,
    CanEmitirFiscal,
    CanCancelarFiscal,
    CanInutilizarFiscal,
)
from fiscal.models import (
    ConfiguracaoFiscalFilial,
    RegraTributaria,
    DocumentoFiscal,
    TarefaInutilizacaoNumeracao,
    MovimentoComodatoFiscal,
    ConfiguracaoMDFe,
    DocumentoFiscalEntrada,
    ApuracaoImposto,
    OrdemRecargaTerceiro,
)
from fiscal.serializers import (
    ConfiguracaoFiscalFilialSerializer,
    RegraTributariaSerializer,
    DocumentoFiscalSerializer,
    TarefaInutilizacaoNumeracaoSerializer,
    MovimentoComodatoFiscalSerializer,
    ConfiguracaoMDFeSerializer,
    DocumentoFiscalEntradaSerializer,
    ApuracaoImpostoSerializer,
    OrdemRecargaTerceiroSerializer,
)
from fiscal.services.nfe_venda_service import emitir_nfe_venda
from fiscal.services.eventos_fiscal_service import cancelar_nfe, carta_correcao_nfe, processar_inutilizacao
from fiscal.services.numeracao_service import detectar_lacunas_numeracao
from fiscal.services.certificado_service import verificar_vencimento_certificados, gerar_lote_xmls_contador
from vendas.models import Venda


class ConfiguracaoFiscalFilialViewSet(viewsets.ModelViewSet):
    """Gerenciamento de configurações fiscais por filial (Task 2)."""
    serializer_class = ConfiguracaoFiscalFilialSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ConfiguracaoFiscalFilial.objects.none()
        return ConfiguracaoFiscalFilial.objects.filter(tenant=tenant).select_related('filial')

    def perform_create(self, serializer):
        assert_tenant_writable(self.request.tenant)
        serializer.save(tenant=self.request.tenant)

    def perform_update(self, serializer):
        assert_tenant_writable(self.request.tenant)
        serializer.save()

    @action(detail=False, methods=['get'])
    def alertas_certificados(self, request):
        """Retorna filiais com certificados vencidos ou vencendo nos próximos 30 dias (Task 2)."""
        dias = int(request.query_params.get('dias', 30))
        alertas = verificar_vencimento_certificados(dias=dias)
        # Filtra apenas os alertas do tenant ativo
        alertas_tenant = [a for a in alertas if a['tenant_id'] == str(request.tenant.id)]
        return Response({'alertas': alertas_tenant})


class RegraTributariaViewSet(viewsets.ModelViewSet):
    """Regras tributárias parametrizáveis e auditáveis por contador (Task 4 / F-25)."""
    serializer_class = RegraTributariaSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return RegraTributaria.objects.none()
        return RegraTributaria.objects.filter(tenant=tenant).prefetch_related('tributos')

    def perform_create(self, serializer):
        assert_tenant_writable(self.request.tenant)
        serializer.save(tenant=self.request.tenant)

    def perform_update(self, serializer):
        assert_tenant_writable(self.request.tenant)
        serializer.save()

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsTenantMember, RequiresModuleFiscal, CanEmitirFiscal])
    def aprovar(self, request, pk=None):
        """Aprovação formal da regra tributária pelo contador para liberação em PRODUÇÃO (F-25)."""
        regra = self.get_object()
        assert_tenant_writable(request.tenant)
        regra.aprovada_por = request.user
        regra.aprovada_em = timezone.now()
        regra.save(update_fields=['aprovada_por', 'aprovada_em', 'atualizado_em'])
        return Response({
            'status': 'sucesso',
            'mensagem': f"Regra tributária '{regra.descricao}' aprovada com sucesso.",
            'aprovada_por': request.user.get_full_name() or request.user.username,
            'aprovada_em': regra.aprovada_em.isoformat()
        })


class DocumentoFiscalViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Listagem, detalhamento, emissão e eventos de documentos fiscais eletrônicos (Tasks 5, 7, 8, 10, 11).
    """
    serializer_class = DocumentoFiscalSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return DocumentoFiscal.objects.none()
        qs = DocumentoFiscal.objects.filter(tenant=tenant).select_related('filial').prefetch_related('itens__tributos', 'eventos')

        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st.upper())

        modelo = self.request.query_params.get('modelo')
        if modelo:
            qs = qs.filter(modelo=modelo.upper())

        filial_id = self.request.query_params.get('filial_id')
        if filial_id:
            qs = qs.filter(filial_id=filial_id)

        origem_id = self.request.query_params.get('origem_id')
        if origem_id:
            qs = qs.filter(origem_id=origem_id)

        return qs

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated, IsTenantMember, RequiresModuleFiscal, CanEmitirFiscal])
    def emitir_venda(self, request):
        """Emissão síncrona/idempotente de NF-e para uma venda existente (Task 7)."""
        assert_tenant_writable(request.tenant)
        venda_id = request.data.get('venda_id')
        if not venda_id:
            return Response({'error': 'venda_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        venda = get_object_or_404(Venda, tenant=request.tenant, id=venda_id)
        idempotency_key = request.data.get('idempotency_key') or request.headers.get('X-Idempotency-Key')

        try:
            doc = emitir_nfe_venda(venda=venda, idempotency_key=idempotency_key)
            return Response(DocumentoFiscalSerializer(doc).data, status=status.HTTP_200_OK if doc.status == 'AUTORIZADO' else status.HTTP_202_ACCEPTED)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsTenantMember, RequiresModuleFiscal, CanEmitirFiscal])
    def reenviar(self, request, pk=None):
        """Reenvio de documento rejeitado após correção cadastral (Task 7)."""
        doc = self.get_object()
        assert_tenant_writable(request.tenant)

        if doc.status != 'REJEITADO':
            return Response({'error': f"Apenas documentos com status REJEITADO podem ser reenviados. Status atual: {doc.status}"}, status=status.HTTP_400_BAD_REQUEST)

        if doc.origem_tipo == 'VENDA':
            venda = get_object_or_404(Venda, tenant=request.tenant, id=doc.origem_id)
            try:
                novo_doc = emitir_nfe_venda(venda=venda)
                return Response(DocumentoFiscalSerializer(novo_doc).data, status=status.HTTP_200_OK)
            except Exception as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'error': f"Tipo de origem '{doc.origem_tipo}' não suportado para reenvio automático."}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsTenantMember, RequiresModuleFiscal, CanCancelarFiscal])
    def cancelar(self, request, pk=None):
        """Cancelamento formal de NF-e na SEFAZ com justificativa auditada (Task 8)."""
        doc = self.get_object()
        assert_tenant_writable(request.tenant)
        justificativa = request.data.get('justificativa', '')

        try:
            evento = cancelar_nfe(documento=doc, justificativa=justificativa)
            return Response({
                'status': 'sucesso',
                'mensagem': f"NF-e #{doc.numero} cancelada com sucesso.",
                'protocolo': evento.protocolo,
                'data_evento': evento.data_evento.isoformat()
            })
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsTenantMember, RequiresModuleFiscal, CanEmitirFiscal])
    def carta_correcao(self, request, pk=None):
        """Emissão de CC-e perante a SEFAZ (Task 8)."""
        doc = self.get_object()
        assert_tenant_writable(request.tenant)
        correcao = request.data.get('correcao', '')

        try:
            evento = carta_correcao_nfe(documento=doc, correcao=correcao)
            return Response({
                'status': 'sucesso',
                'mensagem': f"Carta de Correção seq {evento.sequencial} homologada.",
                'protocolo': evento.protocolo,
                'data_evento': evento.data_evento.isoformat()
            })
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def download_xml(self, request, pk=None):
        """Download seguro do XML oficial autorizado da NF-e (Task 10)."""
        doc = self.get_object()
        if not doc.xml_autorizado:
            return Response({'error': 'Documento ainda não possui XML autorizado disponível.'}, status=status.HTTP_404_NOT_FOUND)

        nome_arq = f"{doc.chave_acesso or f'nfe_{doc.numero}_{doc.serie}'}.xml"
        response = HttpResponse(doc.xml_autorizado, content_type='application/xml; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{nome_arq}"'
        return response

    @action(detail=True, methods=['get'])
    def download_danfe(self, request, pk=None):
        """Retorna o link seguro para visualização/impressão do DANFE em PDF (Task 10 e 11)."""
        doc = self.get_object()
        if not doc.danfe_url:
            return Response({'error': 'DANFE ainda não disponível para este documento.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'danfe_url': doc.danfe_url, 'chave_acesso': doc.chave_acesso})

    @action(detail=False, methods=['get'])
    def download_lote_contador(self, request):
        """Exportação compactada em lote de XMLs para contabilidade (Task 10)."""
        filial_id = request.query_params.get('filial_id')
        dt_ini_str = request.query_params.get('data_inicio')
        dt_fim_str = request.query_params.get('data_fim')

        dt_ini = date.fromisoformat(dt_ini_str) if dt_ini_str else None
        dt_fim = date.fromisoformat(dt_fim_str) if dt_fim_str else None

        zip_bytes = gerar_lote_xmls_contador(
            tenant=request.tenant,
            filial_id=int(filial_id) if filial_id else None,
            data_inicio=dt_ini,
            data_fim=dt_fim
        )

        nome_arq = f"xmls_fiscais_{request.tenant.id}_{timezone.localdate().isoformat()}.zip"
        response = HttpResponse(zip_bytes, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{nome_arq}"'
        return response

    @action(detail=False, methods=['get'])
    def divergencias_comodato(self, request):
        """Relatório de conciliação entre posse física e posse fiscal de cilindros (Task 3)."""
        from fiscal.services.comodato_fiscal_service import relatorio_divergencias_comodato
        filial_id = request.query_params.get('filial_id')
        res = relatorio_divergencias_comodato(
            tenant=request.tenant,
            filial=int(filial_id) if filial_id else None
        )
        return Response({'divergencias': res, 'total': len(res)})

    @action(detail=False, methods=['get'])
    def alertas_mdfe(self, request):
        """Auditoria de manifestos de carga (MDF-e) abertos além do prazo regulamentar (Task 8)."""
        from fiscal.services.transporte_service import verificar_mdfes_abertos_alerta
        filial_id = request.query_params.get('filial_id')
        res = verificar_mdfes_abertos_alerta(
            tenant=request.tenant,
            filial=int(filial_id) if filial_id else None
        )
        return Response({'alertas': res, 'total': len(res)})


class TarefaInutilizacaoNumeracaoViewSet(viewsets.ModelViewSet):
    """Gerenciamento e transmissão de inutilizações de numeração fiscal (Tasks 6 e 8)."""
    serializer_class = TarefaInutilizacaoNumeracaoSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal, CanInutilizarFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return TarefaInutilizacaoNumeracao.objects.none()
        return TarefaInutilizacaoNumeracao.objects.filter(tenant=tenant).select_related('filial')

    def perform_create(self, serializer):
        assert_tenant_writable(self.request.tenant)
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=['post'])
    def processar(self, request, pk=None):
        """Transmite o pedido de inutilização pendente para a SEFAZ (Task 8)."""
        tarefa = self.get_object()
        assert_tenant_writable(request.tenant)
        tarefa_proc = processar_inutilizacao(tarefa)
        return Response(TarefaInutilizacaoNumeracaoSerializer(tarefa_proc).data)

    @action(detail=False, methods=['post'])
    def detectar_lacunas(self, request):
        """Auditoria e geração automática de tarefas para saltos de numeração (Task 6)."""
        assert_tenant_writable(request.tenant)
        filial_id = request.data.get('filial_id')
        if not filial_id:
            return Response({'error': 'filial_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        modelo = request.data.get('modelo', 'NFE_55')
        serie = request.data.get('serie')
        tarefas = detectar_lacunas_numeracao(
            tenant=request.tenant,
            filial_id=filial_id,
            modelo=modelo,
            serie=int(serie) if serie else None
        )
        return Response({
            'lacunas_detectadas': len(tarefas),
            'tarefas': TarefaInutilizacaoNumeracaoSerializer(tarefas, many=True).data
        })


# ==============================================================================
# VIEWSETS SPRINT 11B
# ==============================================================================

class MovimentoComodatoFiscalViewSet(viewsets.ReadOnlyModelViewSet):
    """Consulta de movimentos fiscais de comodato e vasilhame (Tasks 2 e 3)."""
    serializer_class = MovimentoComodatoFiscalSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return MovimentoComodatoFiscal.objects.none()
        return MovimentoComodatoFiscal.objects.filter(tenant=tenant).select_related('cilindro', 'cliente', 'filial')


class ConfiguracaoMDFeViewSet(viewsets.ModelViewSet):
    """Parametrização de regras e exigências de MDF-e por UF (Task 8)."""
    serializer_class = ConfiguracaoMDFeSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ConfiguracaoMDFe.objects.none()
        return ConfiguracaoMDFe.objects.filter(tenant=tenant).select_related('filial')

    def perform_create(self, serializer):
        assert_tenant_writable(self.request.tenant)
        serializer.save(tenant=self.request.tenant)


class DocumentoFiscalEntradaViewSet(viewsets.ModelViewSet):
    """Importação e consulta de NF-e de compra de fornecedores (Task 9)."""
    serializer_class = DocumentoFiscalEntradaSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return DocumentoFiscalEntrada.objects.none()
        return DocumentoFiscalEntrada.objects.filter(tenant=tenant).select_related('filial', 'titulo_pagar')

    @action(detail=False, methods=['post'])
    def importar_xml(self, request):
        """Importa XML de NF-e de compra com garantia estrita de idempotência (Task 9)."""
        assert_tenant_writable(request.tenant)
        xml_content = request.data.get('xml_conteudo')
        filial_id = request.data.get('filial_id')

        if not xml_content:
            return Response({'error': 'xml_conteudo é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        filial = request.tenant.filiais.filter(id=filial_id).first() if filial_id else request.tenant.filiais.first()
        if not filial:
            return Response({'error': 'Filial não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        from fiscal.services.importacao_xml_service import importar_xml_nfe_compra
        doc, criado = importar_xml_nfe_compra(
            tenant=request.tenant,
            filial=filial,
            xml_content=xml_content
        )
        return Response(
            {
                'documento': DocumentoFiscalEntradaSerializer(doc).data,
                'foi_criado': criado,
                'mensagem': "NF-e importada com sucesso." if criado else "NF-e já existente (importação idempotente)."
            },
            status=status.HTTP_201_CREATED if criado else status.HTTP_200_OK
        )


class ApuracaoImpostoViewSet(viewsets.ModelViewSet):
    """Apuração gerencial de tributos e controle de saldos (Task 10)."""
    serializer_class = ApuracaoImpostoSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ApuracaoImposto.objects.none()
        return ApuracaoImposto.objects.filter(tenant=tenant).select_related('filial', 'titulo_pagar')

    @action(detail=False, methods=['post'])
    def calcular(self, request):
        """Calcula a apuração para o período e tributo indicados."""
        assert_tenant_writable(request.tenant)
        periodo = request.data.get('periodo')
        tributo = request.data.get('tributo')
        filial_id = request.data.get('filial_id')

        if not periodo or not tributo:
            return Response({'error': 'periodo e tributo são obrigatórios.'}, status=status.HTTP_400_BAD_REQUEST)

        filial = request.tenant.filiais.filter(id=filial_id).first() if filial_id else request.tenant.filiais.first()
        if not filial:
            return Response({'error': 'Filial não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        from fiscal.services.apuracao_service import calcular_apuracao_imposto
        apuracao = calcular_apuracao_imposto(
            tenant=request.tenant,
            filial=filial,
            periodo=periodo,
            tributo=tributo
        )
        return Response(ApuracaoImpostoSerializer(apuracao).data)

    @action(detail=True, methods=['post'])
    def fechar_e_gerar_guia(self, request, pk=None):
        """Consolida o fechamento da apuração e gera o título a pagar se houver imposto devido."""
        apuracao = self.get_object()
        assert_tenant_writable(request.tenant)
        vencimento_str = request.data.get('data_vencimento')
        vencimento = date.fromisoformat(vencimento_str) if vencimento_str else timezone.localdate() + timezone.timedelta(days=20)

        from fiscal.services.apuracao_service import fechar_apuracao_e_gerar_guia
        res = fechar_apuracao_e_gerar_guia(
            apuracao=apuracao,
            data_vencimento=vencimento,
            usuario=request.user
        )
        return Response(ApuracaoImpostoSerializer(res).data)


class OrdemRecargaTerceiroViewSet(viewsets.ModelViewSet):
    """Ordens de recarga e industrialização para cilindros de terceiros (Task 11)."""
    serializer_class = OrdemRecargaTerceiroSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, RequiresModuleFiscal]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return OrdemRecargaTerceiro.objects.none()
        return OrdemRecargaTerceiro.objects.filter(tenant=tenant).select_related('cliente', 'filial', 'documento_saida').prefetch_related('itens')

    @action(detail=True, methods=['post'])
    def faturar(self, request, pk=None):
        """Emite nota fiscal de faturamento do serviço de recarga/industrialização."""
        ordem = self.get_object()
        assert_tenant_writable(request.tenant)
        from fiscal.services.recarga_terceiro_service import faturar_ordem_recarga
        doc = faturar_ordem_recarga(ordem)
        return Response({
            'documento_id': doc.id,
            'numero': doc.numero,
            'status': doc.status,
            'ordem_status': ordem.status
        })
