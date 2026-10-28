"""
ViewSets e Endpoints DRF para o módulo Financeiro (Sprint 9A - Tarefa 12).
Todas as views estão estritamente protegidas por RequiresModuleFinanceiro, IsTenantMember e IsTenantSubscriptionActive.
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.mixins import TenantViewSetMixin
from core.permissions import (
    IsTenantMember,
    IsTenantSubscriptionActive,
    RequiresModuleFinanceiro,
    CanViewDRE,
)
from financeiro.models import (
    PlanoContas,
    CentroCusto,
    Fornecedor,
    CondicaoPagamento,
    PeriodoContabil,
    ContaFinanceira,
    MovimentoConta,
    LancamentoContabil,
    TituloFinanceiro,
    ParcelaFinanceira,
    BaixaParcela,
    Renegociacao,
    AlcadaAprovacao,
    PendenciaContabilizacao,
    ImportacaoSaldoAbertura,
    PrecoReferenciaCombustivel,
    PreLancamentoDespesaCampo,
    FaturaConsolidadaPosto,
    ItemFaturaPosto,
    FechamentoCaixaRota,
    QuebraCaixa,
    ChequeRecebido,
    DepreciacaoMensal,
    RevisaoVidaUtil,
    SaldoMensalConta,
    ParametroTributarioLucro,
    Orcamento,
    OrcamentoMensalConta,
    ParametroPDD,
    LancamentoManualPendente,
    PerfilPagamentoCliente,
    RecorrenciaFinanceira,
    AlertaCaixa,
    ParametroGestaoTenant,
)
from financeiro.seeds import (
    seed_plano_contas_padrao,
    seed_centros_custo_padrao,
    seed_condicoes_pagamento_padrao,
)
from financeiro.serializers import (
    PlanoContasSerializer,
    CentroCustoSerializer,
    FornecedorSerializer,
    CondicaoPagamentoSerializer,
    PeriodoContabilSerializer,
    FecharPeriodoSerializer,
    ReabrirPeriodoSerializer,
    ContaFinanceiraSerializer,
    MovimentoContaSerializer,
    TransferenciaContasSerializer,
    LancamentoContabilSerializer,
    LancarInputSerializer,
    EstornarInputSerializer,
    TituloFinanceiroSerializer,
    TituloCriarInputSerializer,
    TransicionarInputSerializer,
    AprovacaoInputSerializer,
    BaixaInputSerializer,
    BaixaEmLoteInputSerializer,
    BaixaParcelaSerializer,
    ParcelaFinanceiraSerializer,
    RenegociacaoInputSerializer,
    RenegociacaoSerializer,
    AlcadaAprovacaoSerializer,
    PendenciaContabilizacaoSerializer,
    ImportacaoSaldoAberturaSerializer,
    SimularSaldoAberturaInputSerializer,
    PrecoReferenciaCombustivelSerializer,
    PreLancamentoDespesaCampoSerializer,
    PreLancamentoDespesaRejeitarSerializer,
    PreLancamentoDespesaLoteSerializer,
    ItemFaturaPostoSerializer,
    FaturaConsolidadaPostoSerializer,
    ImportarFaturaCSVSerializer,
    ChequeRecebidoSerializer,
    QuebraCaixaSerializer,
    FechamentoCaixaRotaSerializer,
    RegistrarContagemCegaSerializer,
    ConferirFecharCaixaSerializer,
    DepreciacaoMensalSerializer,
    RevisaoVidaUtilSerializer,
    SaldoMensalContaSerializer,
    ParametroTributarioLucroSerializer,
    OrcamentoSerializer,
    ParametroPDDSerializer,
    LancamentoManualPendenteSerializer,
    PerfilPagamentoClienteSerializer,
    RecorrenciaFinanceiraSerializer,
    AlertaCaixaSerializer,
    ParametroGestaoTenantSerializer,
)
from financeiro.services.conta import saldo_em, transferir_entre_contas
from financeiro.services.periodo import fechar_periodo, reabrir_periodo
from financeiro.services.razao import lancar, estornar, verificar_integridade_razao
from financeiro.services.titulos import (
    criar_titulo,
    transicionar,
    aprovar_titulo,
    renegociar_parcelas,
    calcular_encargos,
)
from financeiro.services.baixas import (
    baixar_parcela,
    baixar_em_lote,
    estornar_baixa,
)
from financeiro.services.saldo_abertura import (
    simular_saldo_abertura,
    confirmar_saldo_abertura,
    estornar_saldo_abertura,
)
from financeiro.services.despesas_campo import (
    criar_pre_lancamento_despesa,
    aprovar_despesa_campo,
    rejeitar_despesa_campo,
    aprovar_despesas_campo_em_lote,
)
from financeiro.services.fatura_posto import (
    importar_fatura_csv,
    conciliar_itens_fatura,
    aprovar_fatura_posto,
)
from financeiro.services.caixa_rota import (
    obter_ou_criar_fechamento_caixa,
    registrar_contagem_cega,
    conferir_e_fechar_caixa,
    registrar_cheque_recebido,
)
from financeiro.antifraude import importar_precos_referencia_csv
from financeiro.selectors.relatorios_frota import (
    relatorio_consumo_veiculos,
    ranking_motoristas_anomalias,
    relatorio_quebras_caixa,
)
from financeiro.contabilizacao import reprocessar_pendencia
from financeiro.selectors.balancete import obter_balancete_verificacao
from financeiro.selectors.razao import consultar_razao_conta, consultar_lancamento



class BaseFinanceiroViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """ViewSet base com isolamento multi-tenant e verificação de módulo ativo."""
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]


class BaseFinanceiroReadOnlyViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet base somente-leitura com isolamento multi-tenant e verificação de módulo ativo."""
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]


class PlanoContasViewSet(BaseFinanceiroViewSet):
    serializer_class = PlanoContasSerializer
    queryset = PlanoContas.unscoped.all()

    def get_queryset(self):
        qs = super().get_queryset()
        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo)
        return qs.order_by('codigo_estrutural')

    @action(detail=False, methods=['post'], url_path='seed-padrao')
    def seed_padrao(self, request):
        tenant = getattr(request, 'tenant', None)
        seed_plano_contas_padrao(tenant)
        return Response(
            {"detail": "Plano de contas padrão aplicado com sucesso."},
            status=status.HTTP_200_OK
        )


class CentroCustoViewSet(BaseFinanceiroViewSet):
    serializer_class = CentroCustoSerializer
    queryset = CentroCusto.unscoped.all()

    @action(detail=False, methods=['post'], url_path='seed-padrao')
    def seed_padrao(self, request):
        tenant = getattr(request, 'tenant', None)
        seed_centros_custo_padrao(tenant)
        return Response(
            {"detail": "Centros de custo padrão aplicados com sucesso."},
            status=status.HTTP_200_OK
        )


class FornecedorViewSet(BaseFinanceiroViewSet):
    serializer_class = FornecedorSerializer
    queryset = Fornecedor.unscoped.all()


class CondicaoPagamentoViewSet(BaseFinanceiroViewSet):
    serializer_class = CondicaoPagamentoSerializer
    queryset = CondicaoPagamento.unscoped.all()

    @action(detail=False, methods=['post'], url_path='seed-padrao')
    def seed_padrao(self, request):
        tenant = getattr(request, 'tenant', None)
        seed_condicoes_pagamento_padrao(tenant)
        return Response(
            {"detail": "Condições de pagamento padrão aplicadas com sucesso."},
            status=status.HTTP_200_OK
        )


class PeriodoContabilViewSet(BaseFinanceiroViewSet):
    serializer_class = PeriodoContabilSerializer
    queryset = PeriodoContabil.unscoped.all()

    @action(detail=False, methods=['post'], url_path='fechar')
    def fechar(self, request):
        ser = FecharPeriodoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            periodo = fechar_periodo(
                tenant=tenant,
                ano=ser.validated_data['ano'],
                mes=ser.validated_data['mes'],
                usuario=request.user
            )
            return Response(PeriodoContabilSerializer(periodo).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='reabrir')
    def reabrir(self, request):
        ser = ReabrirPeriodoSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            periodo = reabrir_periodo(
                tenant=tenant,
                ano=ser.validated_data['ano'],
                mes=ser.validated_data['mes'],
                motivo=ser.validated_data['motivo'],
                usuario=request.user
            )
            return Response(PeriodoContabilSerializer(periodo).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ContaFinanceiraViewSet(BaseFinanceiroViewSet):
    serializer_class = ContaFinanceiraSerializer
    queryset = ContaFinanceira.unscoped.all()

    @action(detail=True, methods=['get'], url_path='saldo')
    def saldo(self, request, pk=None):
        conta = self.get_object()
        dt_param = request.query_params.get('data')
        data_consulta = None
        if dt_param:
            try:
                data_consulta = timezone.datetime.strptime(dt_param, '%Y-%m-%d').date()
            except ValueError:
                return Response({"detail": "Formato de data inválido. Use AAAA-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        saldo_valor = saldo_em(conta, data_consulta)
        return Response({
            'conta_id': conta.id,
            'nome': conta.nome,
            'data_consulta': str(data_consulta or timezone.localdate()),
            'saldo': str(saldo_valor)
        })

    @action(detail=False, methods=['post'], url_path='transferir')
    def transferir(self, request):
        ser = TransferenciaContasSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            lancamento, mov_saida, mov_entrada = transferir_entre_contas(
                tenant=tenant,
                conta_origem_id=ser.validated_data['conta_origem_id'],
                conta_destino_id=ser.validated_data['conta_destino_id'],
                valor=ser.validated_data['valor'],
                data_transferencia=ser.validated_data.get('data_transferencia'),
                historico=ser.validated_data.get('historico', ''),
                usuario=request.user
            )
            return Response({
                'detail': "Transferência realizada com sucesso.",
                'lancamento_numero': lancamento.numero,
                'movimento_saida_id': mov_saida.id,
                'movimento_entrada_id': mov_entrada.id,
                'valor': str(ser.validated_data['valor'])
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class MovimentoContaViewSet(BaseFinanceiroReadOnlyViewSet):
    serializer_class = MovimentoContaSerializer
    queryset = MovimentoConta.unscoped.all()

    def get_queryset(self):
        qs = super().get_queryset()
        conta_id = self.request.query_params.get('conta_id')
        if conta_id:
            qs = qs.filter(conta_id=conta_id)
        dt_ini = self.request.query_params.get('data_inicio')
        if dt_ini:
            qs = qs.filter(data_movimento__gte=dt_ini)
        dt_fim = self.request.query_params.get('data_fim')
        if dt_fim:
            qs = qs.filter(data_movimento__lte=dt_fim)
        return qs.order_by('-data_movimento', '-criado_em')


class RazaoViewSet(BaseFinanceiroReadOnlyViewSet):
    serializer_class = LancamentoContabilSerializer
    queryset = LancamentoContabil.unscoped.all()

    def get_queryset(self):
        qs = super().get_queryset()
        dt_ini = self.request.query_params.get('data_inicio')
        if dt_ini:
            qs = qs.filter(data_competencia__gte=dt_ini)
        dt_fim = self.request.query_params.get('data_fim')
        if dt_fim:
            qs = qs.filter(data_competencia__lte=dt_fim)
        return qs.order_by('-numero')

    @action(detail=False, methods=['post'], url_path='lancar')
    def criar_lancamento(self, request):
        ser = LancarInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            lancamento, partidas = lancar(
                tenant=tenant,
                data_competencia=ser.validated_data['data_competencia'],
                historico=ser.validated_data['historico'],
                partidas=ser.validated_data['partidas'],
                filial_id=ser.validated_data.get('filial_id'),
                origem_tipo=ser.validated_data.get('origem_tipo', ''),
                origem_id=ser.validated_data.get('origem_id', ''),
                usuario=request.user
            )
            return Response(LancamentoContabilSerializer(lancamento).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='estornar')
    def estornar_lancamento(self, request, pk=None):
        ser = EstornarInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            lancamento_estorno, _ = estornar(
                lancamento_id=pk,
                motivo=ser.validated_data['motivo'],
                usuario=request.user
            )
            return Response(LancamentoContabilSerializer(lancamento_estorno).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='consultar-conta')
    def consultar_conta(self, request):
        tenant = getattr(request, 'tenant', None)
        conta_id = request.query_params.get('conta_id')
        dt_ini = request.query_params.get('data_inicio')
        dt_fim = request.query_params.get('data_fim')

        if not conta_id or not dt_ini or not dt_fim:
            return Response(
                {"detail": "Parâmetros conta_id, data_inicio e data_fim são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            dados = consultar_razao_conta(
                tenant=tenant,
                conta_id=int(conta_id),
                data_inicio=dt_ini,
                data_fim=dt_fim
            )
            return Response(dados, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='verificar-integridade')
    def verificar_integridade(self, request):
        tenant = getattr(request, 'tenant', None)
        valido, erros = verificar_integridade_razao(tenant)
        return Response({
            'valido': valido,
            'total_erros': len(erros),
            'erros': erros
        }, status=status.HTTP_200_OK if valido else status.HTTP_409_CONFLICT)


class BalanceteAPIView(TenantViewSetMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        dt_ini = request.query_params.get('data_inicio')
        dt_fim = request.query_params.get('data_fim')
        filial_id = request.query_params.get('filial_id')
        apenas_mov = request.query_params.get('apenas_com_movimento', 'false').lower() == 'true'

        if not dt_ini or not dt_fim:
            hoje = timezone.localdate()
            dt_ini = hoje.replace(day=1).isoformat()
            dt_fim = hoje.isoformat()

        balancete = obter_balancete_verificacao(
            tenant=tenant,
            data_inicio=dt_ini,
            data_fim=dt_fim,
            filial=filial_id,
            apenas_com_movimento=apenas_mov
        )
        return Response(balancete, status=status.HTTP_200_OK)


# ==============================================================================
# SPRINT 9B: TÍTULOS, BAIXAS, ALÇADAS, PENDÊNCIAS E SALDO DE ABERTURA
# ==============================================================================

class TituloFinanceiroViewSet(BaseFinanceiroViewSet):
    queryset = TituloFinanceiro.unscoped.all()
    serializer_class = TituloFinanceiroSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo.upper())
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())
        cliente_id = self.request.query_params.get('cliente_id')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)
        fornecedor_id = self.request.query_params.get('fornecedor_id')
        if fornecedor_id:
            qs = qs.filter(fornecedor_id=fornecedor_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = TituloCriarInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        tenant = getattr(request, 'tenant', None)

        try:
            titulo = criar_titulo(
                tenant=tenant,
                tipo=d['tipo'],
                conta_gerencial=d['conta_gerencial_id'],
                valor_bruto=d['valor_bruto'],
                data_emissao=d.get('data_emissao'),
                data_competencia=d.get('data_competencia'),
                filial=d.get('filial_id'),
                cliente=d.get('cliente_id'),
                fornecedor=d.get('fornecedor_id'),
                beneficiario_texto=d.get('beneficiario_texto', ''),
                condicao_pagamento=d.get('condicao_pagamento_id'),
                origem_tipo=d.get('origem_tipo', 'MANUAL'),
                origem_id=d.get('origem_id', ''),
                historico=d.get('historico', ''),
                retencoes=d.get('retencoes'),
                rateios=d.get('rateios'),
                criado_por=request.user
            )
            return Response(TituloFinanceiroSerializer(titulo).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='transicionar')
    def transicionar(self, request, pk=None):
        titulo = self.get_object()
        serializer = TransicionarInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            transicionar(
                titulo,
                serializer.validated_data['novo_status'],
                motivo=serializer.validated_data.get('motivo', ''),
                usuario=request.user
            )
            return Response(TituloFinanceiroSerializer(titulo).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='aprovar')
    def aprovar(self, request, pk=None):
        titulo = self.get_object()
        serializer = AprovacaoInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            aprovacao = aprovar_titulo(
                titulo_id=titulo.id,
                usuario=request.user,
                decisao=serializer.validated_data['decisao'],
                motivo=serializer.validated_data.get('motivo', '')
            )
            titulo.refresh_from_db()
            return Response({
                'status': 'sucesso',
                'decisao': aprovacao.decisao,
                'titulo': TituloFinanceiroSerializer(titulo).data
            }, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='renegociar')
    def renegociar(self, request, pk=None):
        titulo = self.get_object()
        serializer = RenegociacaoInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        tenant = getattr(request, 'tenant', None)
        try:
            reneg = renegociar_parcelas(
                tenant=tenant,
                titulo_id=titulo.id,
                parcelas_origem_ids=d['parcelas_origem_ids'],
                novas_parcelas_data=d['novas_parcelas'],
                motivo=d['motivo'],
                desconto_concedido=d.get('desconto_concedido', Decimal('0.00')),
                usuario=request.user
            )
            titulo.refresh_from_db()
            return Response({
                'renegociacao': RenegociacaoSerializer(reneg).data,
                'titulo': TituloFinanceiroSerializer(titulo).data
            }, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='baixar')
    def baixar(self, request, pk=None):
        titulo = self.get_object()
        parcela_id = request.data.get('parcela_id')
        if not parcela_id:
            return Response({'detail': 'parcela_id é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = BaixaInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        tenant = getattr(request, 'tenant', None)

        try:
            baixa = baixar_parcela(
                tenant=tenant,
                parcela_id=int(parcela_id),
                conta_financeira_id=d['conta_financeira_id'],
                valor_principal=d['valor_principal'],
                data_liquidacao=d.get('data_liquidacao'),
                valor_juros=d.get('valor_juros', Decimal('0.00')),
                valor_multa=d.get('valor_multa', Decimal('0.00')),
                valor_desconto=d.get('valor_desconto', Decimal('0.00')),
                valor_tarifa=d.get('valor_tarifa', Decimal('0.00')),
                comprovante=d.get('comprovante', ''),
                usuario=request.user
            )
            return Response(BaixaParcelaSerializer(baixa).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='baixa-em-lote')
    def baixa_em_lote(self, request):
        serializer = BaixaEmLoteInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        tenant = getattr(request, 'tenant', None)

        try:
            baixas = baixar_em_lote(
                tenant=tenant,
                itens_baixa=d['itens'],
                conta_financeira_id=d['conta_financeira_id'],
                data_liquidacao=d.get('data_liquidacao'),
                comprovante=d.get('comprovante', ''),
                usuario=request.user
            )
            return Response({
                'total_baixadas': len(baixas),
                'baixas': BaixaParcelaSerializer(baixas, many=True).data
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ParcelaFinanceiraViewSet(BaseFinanceiroReadOnlyViewSet):
    queryset = ParcelaFinanceira.unscoped.all()
    serializer_class = ParcelaFinanceiraSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        titulo_id = self.request.query_params.get('titulo_id')
        if titulo_id:
            qs = qs.filter(titulo_id=titulo_id)
        if self.request.query_params.get('esta_vencida', '').lower() == 'true':
            qs = qs.filter(saldo_em_aberto__gt=Decimal('0.00'), data_vencimento__lt=timezone.localdate())
        return qs

    @action(detail=True, methods=['get'], url_path='calcular-encargos')
    def calcular_encargos(self, request, pk=None):
        parcela = self.get_object()
        data_ref = request.query_params.get('data')
        if data_ref:
            try:
                data_ref = timezone.datetime.strptime(data_ref, '%Y-%m-%d').date()
            except ValueError:
                data_ref = timezone.localdate()
        else:
            data_ref = timezone.localdate()

        res = calcular_encargos(parcela, data_calculo=data_ref)
        return Response(res, status=status.HTTP_200_OK)


class BaixaParcelaViewSet(BaseFinanceiroReadOnlyViewSet):
    queryset = BaixaParcela.unscoped.all()
    serializer_class = BaixaParcelaSerializer

    @action(detail=True, methods=['post'], url_path='estornar')
    def estornar(self, request, pk=None):
        baixa = self.get_object()
        serializer = EstornarInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)
        try:
            b_estornada = estornar_baixa(
                tenant=tenant,
                baixa_id=baixa.id,
                motivo=serializer.validated_data['motivo'],
                usuario=request.user
            )
            return Response(BaixaParcelaSerializer(b_estornada).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='recibo')
    def recibo(self, request, pk=None):
        baixa = self.get_object()
        parcela = baixa.parcela
        titulo = parcela.titulo
        recibo_dados = {
            'recibo_numero': f"REC-{baixa.id:06d}",
            'data_emissao': baixa.data_liquidacao.strftime('%d/%m/%Y'),
            'valor_total': str(baixa.valor_total_movimentado),
            'valor_principal': str(baixa.valor_principal),
            'valor_juros': str(baixa.valor_juros),
            'valor_multa': str(baixa.valor_multa),
            'valor_desconto': str(baixa.valor_desconto),
            'favorecido_pagador': titulo.cliente.nome if titulo.cliente else (titulo.fornecedor.razao_social if titulo.fornecedor else titulo.beneficiario_texto),
            'tipo_operacao': 'RECEBIMENTO' if titulo.tipo == 'RECEBER' else 'PAGAMENTO',
            'conta_financeira': baixa.conta_financeira.nome,
            'historico': f"Liquidação da Parcela {parcela.numero_parcela}/{parcela.total_parcelas} do Título #{titulo.id}",
            'estornado': baixa.estornado
        }
        return Response(recibo_dados, status=status.HTTP_200_OK)


class AlcadaAprovacaoViewSet(BaseFinanceiroViewSet):
    queryset = AlcadaAprovacao.unscoped.all()
    serializer_class = AlcadaAprovacaoSerializer


class PendenciaContabilizacaoViewSet(BaseFinanceiroReadOnlyViewSet):
    queryset = PendenciaContabilizacao.unscoped.all()
    serializer_class = PendenciaContabilizacaoSerializer

    @action(detail=True, methods=['post'], url_path='reprocessar')
    def reprocessar(self, request, pk=None):
        pendencia = self.get_object()
        p_reprocessada = reprocessar_pendencia(pendencia.id, usuario=request.user)
        return Response(PendenciaContabilizacaoSerializer(p_reprocessada).data, status=status.HTTP_200_OK)


class SaldoAberturaViewSet(BaseFinanceiroViewSet):
    queryset = ImportacaoSaldoAbertura.unscoped.all()
    serializer_class = ImportacaoSaldoAberturaSerializer

    @action(detail=False, methods=['post'], url_path='simular')
    def simular(self, request):
        serializer = SimularSaldoAberturaInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        tenant = getattr(request, 'tenant', None)
        try:
            importacao = simular_saldo_abertura(
                tenant=tenant,
                data_corte=d['data_corte'],
                dados_carga=d['dados_carga'],
                usuario=request.user
            )
            return Response(ImportacaoSaldoAberturaSerializer(importacao).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='confirmar')
    def confirmar(self, request, pk=None):
        importacao = self.get_object()
        tenant = getattr(request, 'tenant', None)
        try:
            imp_confirmada = confirmar_saldo_abertura(
                tenant=tenant,
                importacao_id=importacao.id,
                usuario=request.user
            )
            return Response(ImportacaoSaldoAberturaSerializer(imp_confirmada).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='estornar')
    def estornar(self, request, pk=None):
        importacao = self.get_object()
        serializer = EstornarInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)
        try:
            imp_estornada = estornar_saldo_abertura(
                tenant=tenant,
                importacao_id=importacao.id,
                motivo=serializer.validated_data['motivo'],
                usuario=request.user
            )
            return Response(ImportacaoSaldoAberturaSerializer(imp_estornada).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ==============================================================================
# SPRINT 9C: DESPESAS DE CAMPO, ANTIFRAUDE, FATURAS E CAIXA DE ROTA
# ==============================================================================

class PreLancamentoDespesaCampoViewSet(BaseFinanceiroViewSet):
    """
    Fila de conferência de despesas de campo (abastecimento, pedágio, manutenção, outro).
    Implementa antifraude e segregação de funções.
    """
    queryset = PreLancamentoDespesaCampo.unscoped.all()
    serializer_class = PreLancamentoDespesaCampoSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status_filtro = self.request.query_params.get('status')
        if status_filtro:
            qs = qs.filter(status=status_filtro)
        alerta = self.request.query_params.get('alerta_auditoria')
        if alerta is not None:
            if alerta.lower() in ('true', '1'):
                qs = qs.filter(alerta_auditoria=True)
            elif alerta.lower() in ('false', '0'):
                qs = qs.filter(alerta_auditoria=False)
        veiculo_id = self.request.query_params.get('veiculo')
        if veiculo_id:
            qs = qs.filter(veiculo_id=veiculo_id)
        motorista_id = self.request.query_params.get('motorista')
        if motorista_id:
            qs = qs.filter(motorista_id=motorista_id)
        forma_pagamento = self.request.query_params.get('forma_pagamento')
        if forma_pagamento:
            qs = qs.filter(forma_pagamento=forma_pagamento)
        return qs.order_by('-data_hora')

    def create(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        try:
            despesa = criar_pre_lancamento_despesa(
                tenant=tenant,
                tipo=vd['tipo'],
                veiculo_id=vd['veiculo'].id if hasattr(vd['veiculo'], 'id') else vd['veiculo'],
                motorista_id=vd.get('motorista').id if vd.get('motorista') else request.user.id,
                data_hora=vd['data_hora'],
                valor_informado=vd['valor_informado'],
                forma_pagamento=vd.get('forma_pagamento', 'CARTAO_FROTA'),
                entrega_id=vd.get('entrega').id if vd.get('entrega') else None,
                odometro_informado=vd.get('odometro_informado'),
                litros=vd.get('litros'),
                posto_nome=vd.get('posto_nome', ''),
                posto_cnpj=vd.get('posto_cnpj', ''),
                foto_cupom=request.FILES.get('foto_cupom') or vd.get('foto_cupom'),
                latitude=vd.get('latitude'),
                longitude=vd.get('longitude'),
                client_uuid=vd.get('client_uuid'),
            )
            return Response(self.get_serializer(despesa).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='sincronizar')
    def sincronizar(self, request):
        tenant = getattr(request, 'tenant', None)
        itens = request.data.get('itens', [])
        resultados = []
        for item in itens:
            try:
                despesa = criar_pre_lancamento_despesa(
                    tenant=tenant,
                    tipo=item.get('tipo', 'OUTRO'),
                    veiculo_id=item.get('veiculo_id') or item.get('veiculo'),
                    motorista_id=item.get('motorista_id') or request.user.id,
                    data_hora=item.get('data_hora') or timezone.now(),
                    valor_informado=Decimal(str(item.get('valor_informado', '0.00'))),
                    forma_pagamento=item.get('forma_pagamento', 'CARTAO_FROTA'),
                    entrega_id=item.get('entrega_id'),
                    odometro_informado=Decimal(str(item['odometro_informado'])) if item.get('odometro_informado') is not None else None,
                    litros=Decimal(str(item['litros'])) if item.get('litros') is not None else None,
                    posto_nome=item.get('posto_nome', ''),
                    posto_cnpj=item.get('posto_cnpj', ''),
                    latitude=Decimal(str(item['latitude'])) if item.get('latitude') is not None else None,
                    longitude=Decimal(str(item['longitude'])) if item.get('longitude') is not None else None,
                    client_uuid=item.get('client_uuid'),
                )
                resultados.append({
                    'client_uuid': item.get('client_uuid'),
                    'status': despesa.status,
                    'id': despesa.id,
                    'alerta_auditoria': despesa.alerta_auditoria,
                    'motivos_alerta': despesa.motivos_alerta_json,
                    'sucesso': True
                })
            except Exception as e:
                resultados.append({
                    'client_uuid': item.get('client_uuid'),
                    'sucesso': False,
                    'erro': str(e)
                })
        return Response({'resultados': resultados}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='aprovar')
    def aprovar(self, request, pk=None):
        despesa = self.get_object()
        tenant = getattr(request, 'tenant', None)
        try:
            despesa_aprovada = aprovar_despesa_campo(tenant, despesa.id, request.user)
            return Response(self.get_serializer(despesa_aprovada).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='rejeitar')
    def rejeitar(self, request, pk=None):
        despesa = self.get_object()
        tenant = getattr(request, 'tenant', None)
        serializer = PreLancamentoDespesaRejeitarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        motivo = serializer.validated_data['motivo']
        try:
            despesa_rejeitada = rejeitar_despesa_campo(tenant, despesa.id, request.user, motivo)
            return Response(self.get_serializer(despesa_rejeitada).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='aprovar-lote')
    def aprovar_lote(self, request):
        tenant = getattr(request, 'tenant', None)
        serializer = PreLancamentoDespesaLoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data['ids']
        try:
            aprovadas = aprovar_despesas_campo_em_lote(tenant, ids, request.user)
            return Response({
                'aprovadas_count': len(aprovadas),
                'aprovadas_ids': [d.id for d in aprovadas]
            }, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class FaturaConsolidadaPostoViewSet(BaseFinanceiroViewSet):
    """
    Importação de faturas de cartão/posto, conciliação com pré-lançamentos e geração de contas a pagar.
    """
    queryset = FaturaConsolidadaPosto.unscoped.all()
    serializer_class = FaturaConsolidadaPostoSerializer

    @action(detail=False, methods=['post'], url_path='importar-csv')
    def importar_csv(self, request):
        tenant = getattr(request, 'tenant', None)
        serializer = ImportarFaturaCSVSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        arquivo = vd['arquivo']
        try:
            conteudo_csv = arquivo.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            arquivo.seek(0)
            conteudo_csv = arquivo.read().decode('latin-1')

        try:
            fatura = importar_fatura_csv(
                tenant=tenant,
                cartao_ou_convenio=vd['cartao_ou_convenio'],
                csv_content=conteudo_csv,
                usuario=request.user,
                numero_fatura=vd.get('numero_fatura', '')
            )
            return Response(self.get_serializer(fatura).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='conciliar')
    def conciliar(self, request, pk=None):
        fatura = self.get_object()
        tenant = getattr(request, 'tenant', None)
        try:
            res = conciliar_itens_fatura(tenant, fatura.id)
            return Response(res, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='aprovar')
    def aprovar(self, request, pk=None):
        fatura = self.get_object()
        tenant = getattr(request, 'tenant', None)
        try:
            titulos = aprovar_fatura_posto(tenant, fatura.id, request.user)
            return Response({
                'fatura_id': fatura.id,
                'titulos_gerados_count': len(titulos),
                'titulos_ids': [t.id for t in titulos]
            }, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class FechamentoCaixaRotaViewSet(BaseFinanceiroViewSet):
    """
    Fechamento do caixa físico da rota com contagem cega e apuração de quebra de caixa.
    """
    queryset = FechamentoCaixaRota.unscoped.all()
    serializer_class = FechamentoCaixaRotaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        motorista_id = self.request.query_params.get('motorista')
        if motorista_id:
            qs = qs.filter(motorista_id=motorista_id)
        data_param = self.request.query_params.get('data')
        if data_param:
            qs = qs.filter(data=data_param)
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs.order_by('-data', '-criado_em')

    @action(detail=False, methods=['post'], url_path='obter-ou-criar')
    def obter_ou_criar(self, request):
        tenant = getattr(request, 'tenant', None)
        motorista_id = request.data.get('motorista_id') or request.user.id
        data_fechamento = request.data.get('data') or timezone.localdate()
        conta_caixa_id = request.data.get('conta_caixa_id')
        try:
            fechamento = obter_ou_criar_fechamento_caixa(
                tenant=tenant,
                motorista_id=motorista_id,
                data_fechamento=data_fechamento,
                conta_caixa_id=conta_caixa_id
            )
            return Response(self.get_serializer(fechamento).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='contagem-cega')
    def contagem_cega(self, request, pk=None):
        fechamento = self.get_object()
        tenant = getattr(request, 'tenant', None)
        serializer = RegistrarContagemCegaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        valor_contado = serializer.validated_data['valor_contado_cego']
        try:
            f_atualizado = registrar_contagem_cega(tenant, fechamento.id, valor_contado)
            return Response(self.get_serializer(f_atualizado).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='conferir-fechar')
    def conferir_fechar(self, request, pk=None):
        fechamento = self.get_object()
        tenant = getattr(request, 'tenant', None)
        serializer = ConferirFecharCaixaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        try:
            f_fechado = conferir_e_fechar_caixa(
                tenant=tenant,
                fechamento_id=fechamento.id,
                conferente=request.user,
                valor_entregue_tesouraria=vd['valor_entregue_tesouraria'],
                conta_cofre_id=vd.get('conta_cofre_id')
            )
            return Response(self.get_serializer(f_fechado).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='cheque')
    def registrar_cheque(self, request, pk=None):
        fechamento = self.get_object()
        try:
            cheque = registrar_cheque_recebido(
                fechamento=fechamento,
                numero=request.data.get('numero', ''),
                banco=request.data.get('banco', ''),
                valor=Decimal(str(request.data.get('valor', '0.00'))),
                bom_para=request.data.get('bom_para')
            )
            return Response(ChequeRecebidoSerializer(cheque).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PrecoReferenciaCombustivelViewSet(BaseFinanceiroViewSet):
    """
    Tabela de preços médios semanais de combustíveis por UF/Município (ANP).
    """
    queryset = PrecoReferenciaCombustivel.unscoped.all()
    serializer_class = PrecoReferenciaCombustivelSerializer

    @action(detail=False, methods=['post'], url_path='importar-csv')
    def importar_csv(self, request):
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            return Response({'detail': 'Arquivo CSV obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            conteudo_csv = arquivo.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            arquivo.seek(0)
            conteudo_csv = arquivo.read().decode('latin-1')

        try:
            criados = importar_precos_referencia_csv(conteudo_csv)
            return Response({'criados_count': criados}, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class RelatorioConsumoVeiculosAPIView(APIView):
    """Relatório de consumo km/L por veículo."""
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        veiculo_id = request.query_params.get('veiculo_id')
        dados = relatorio_consumo_veiculos(
            tenant=tenant,
            data_inicio=data_inicio,
            data_fim=data_fim,
            veiculo_id=int(veiculo_id) if veiculo_id else None
        )
        return Response(dados, status=status.HTTP_200_OK)


class RankingMotoristasAnomaliasAPIView(APIView):
    """Ranking de motoristas por anomalias detectadas no antifraude."""
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        dados = ranking_motoristas_anomalias(
            tenant=tenant,
            data_inicio=data_inicio,
            data_fim=data_fim
        )
        return Response(dados, status=status.HTTP_200_OK)


class RelatorioQuebrasCaixaAPIView(APIView):
    """Relatório de quebras e divergências de caixa por motorista."""
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        motorista_id = request.query_params.get('motorista_id')
        dados = relatorio_quebras_caixa(
            tenant=tenant,
            data_inicio=data_inicio,
            data_fim=data_fim,
            motorista_id=int(motorista_id) if motorista_id else None
        )
        return Response(dados, status=status.HTTP_200_OK)


# ==============================================================================
# SPRINT 10A: VIEWS E VIEWSETS DE CONCILIAÇÃO, COBRANÇA E RÉGUA
# ==============================================================================

from rest_framework import viewsets
from financeiro.models import (
    ImportacaoExtrato,
    ExtratoBancarioItem,
    RegraConciliacao,
    ConfiguracaoCobranca,
    ReguaCobranca,
    EnvioCobranca,
    ConsentimentoContato,
)
from financeiro.serializers import (
    ImportacaoExtratoSerializer,
    ExtratoBancarioItemSerializer,
    ConciliarManualmenteSerializer,
    CriarLancamentoDiretoSerializer,
    DividirItemExtratoSerializer,
    IgnorarItemExtratoSerializer,
    DesfazerConciliacaoSerializer,
    RegraConciliacaoSerializer,
    ConfiguracaoCobrancaSerializer,
    ReguaCobrancaSerializer,
    EnvioCobrancaSerializer,
    ConsentimentoContatoSerializer,
)
from financeiro.services.conciliacao_service import (
    importar_extrato,
    conciliar_manualmente,
    criar_lancamento_direto,
    dividir_item_extrato,
    ignorar_item_extrato,
    desfazer_conciliacao,
)
from financeiro.services.cobranca_service import (
    emitir_cobranca_parcela,
    processar_webhook_cobranca,
)
from financeiro.services.regua_service import (
    executar_regua_cobranca,
    registrar_consentimento,
    revogar_consentimento,
)
from financeiro.selectors.conciliacao import obter_painel_conciliacao
from financeiro.banco.ports import AssinaturaInvalidaError


class ImportacaoExtratoViewSet(viewsets.ModelViewSet):
    """Importação e histórico de arquivos de extrato bancário (OFX e CNAB Retorno)."""
    serializer_class = ImportacaoExtratoSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ImportacaoExtrato.objects.none()
        return ImportacaoExtrato.objects.filter(tenant=tenant).select_related('conta', 'usuario')

    def create(self, request, *args, **kwargs):
        tenant = getattr(request, 'tenant', None)
        conta_id = request.data.get('conta') or request.data.get('conta_id')
        tipo = request.data.get('tipo', 'OFX')
        arquivo = request.FILES.get('arquivo')

        if not conta_id:
            return Response({'conta': "Campo conta_id é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
        if not arquivo:
            return Response({'arquivo': "Arquivo de extrato é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            conteudo = arquivo.read()
            importacao = importar_extrato(
                tenant=tenant,
                conta_id=int(conta_id),
                tipo=tipo,
                arquivo_bytes=conteudo,
                nome_arquivo=arquivo.name,
                usuario=request.user
            )
            serializer = self.get_serializer(importacao)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ExtratoBancarioItemViewSet(viewsets.ReadOnlyModelViewSet):
    """Itens individualizados de extrato bancário com ações de conciliação."""
    serializer_class = ExtratoBancarioItemSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ExtratoBancarioItem.objects.none()
        qs = ExtratoBancarioItem.objects.filter(tenant=tenant).select_related('conta', 'importacao')
        conta_id = self.request.query_params.get('conta_id')
        if conta_id:
            qs = qs.filter(conta_id=int(conta_id))
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    @action(detail=True, methods=['post'], url_path='conciliar-manualmente')
    def conciliar(self, request, pk=None):
        tenant = getattr(request, 'tenant', None)
        serializer = ConciliarManualmenteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = conciliar_manualmente(
                tenant=tenant,
                item_id=int(pk),
                parcelas_ids=serializer.validated_data['parcelas_ids'],
                usuario=request.user
            )
            return Response(self.get_serializer(item).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='criar-lancamento-direto')
    def lancamento_direto(self, request, pk=None):
        tenant = getattr(request, 'tenant', None)
        serializer = CriarLancamentoDiretoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = criar_lancamento_direto(
                tenant=tenant,
                item_id=int(pk),
                conta_contabil_id=serializer.validated_data['conta_contabil_id'],
                centro_custo_id=serializer.validated_data.get('centro_custo_id'),
                historico=serializer.validated_data.get('historico', ''),
                usuario=request.user
            )
            return Response(self.get_serializer(item).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='dividir')
    def dividir(self, request, pk=None):
        tenant = getattr(request, 'tenant', None)
        serializer = DividirItemExtratoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            novos = dividir_item_extrato(
                tenant=tenant,
                item_id=int(pk),
                partes=serializer.validated_data['partes'],
                usuario=request.user
            )
            return Response(self.get_serializer(novos, many=True).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='ignorar')
    def ignorar(self, request, pk=None):
        tenant = getattr(request, 'tenant', None)
        serializer = IgnorarItemExtratoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = ignorar_item_extrato(
                tenant=tenant,
                item_id=int(pk),
                motivo=serializer.validated_data['motivo'],
                usuario=request.user
            )
            return Response(self.get_serializer(item).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='desfazer')
    def desfazer(self, request, pk=None):
        tenant = getattr(request, 'tenant', None)
        serializer = DesfazerConciliacaoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = desfazer_conciliacao(
                tenant=tenant,
                item_id=int(pk),
                motivo=serializer.validated_data['motivo'],
                usuario=request.user
            )
            return Response(self.get_serializer(item).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PainelConciliacaoAPIView(APIView):
    """Painel estruturado de conciliação lado a lado (Extrato à esquerda, Sistema à direita)."""
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        conta_id = request.query_params.get('conta_id')
        if not conta_id:
            return Response({'detail': "Parâmetro conta_id é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            painel = obter_painel_conciliacao(tenant=tenant, conta_id=int(conta_id))
            from financeiro.serializers import ParcelaFinanceiraSerializer
            data = {
                'conta_id': painel['conta'].id,
                'conta_nome': painel['conta'].nome,
                'saldo_razao': str(painel['saldo_razao']),
                'saldo_extrato': str(painel['saldo_extrato']) if painel['saldo_extrato'] is not None else None,
                'diferenca': str(painel['diferenca']) if painel['diferenca'] is not None else None,
                'conciliacao_fechada_ate': painel['conciliacao_fechada_ate'].isoformat() if painel['conciliacao_fechada_ate'] else None,
                'total_pendentes': painel['total_pendentes'],
                'itens_extrato': ExtratoBancarioItemSerializer(painel['itens_extrato'], many=True).data,
                'parcelas_sistema': ParcelaFinanceiraSerializer(painel['parcelas_sistema'], many=True).data,
            }
            return Response(data, status=status.HTTP_200_OK)
        except ContaFinanceira.DoesNotExist:
            return Response({'detail': "Conta financeira não encontrada."}, status=status.HTTP_404_NOT_FOUND)


class RegraConciliacaoViewSet(viewsets.ModelViewSet):
    """Regras de conciliação automática para tarifas, rendimentos e despesas bancárias."""
    serializer_class = RegraConciliacaoSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return RegraConciliacao.objects.none()
        return RegraConciliacao.objects.filter(tenant=tenant).select_related('conta_contabil', 'centro_custo')

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ConfiguracaoCobrancaViewSet(viewsets.ModelViewSet):
    """Configurações de emissão de cobrança registrada (Boleto/PIX) por conta."""
    serializer_class = ConfiguracaoCobrancaSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ConfiguracaoCobranca.objects.none()
        return ConfiguracaoCobranca.objects.filter(tenant=tenant).select_related('conta_financeira')

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class ReguaCobrancaViewSet(viewsets.ModelViewSet):
    """Etapas e réguas preventivas/reativas de cobrança (D-3, D0, D+3, etc.)."""
    serializer_class = ReguaCobrancaSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ReguaCobranca.objects.none()
        return ReguaCobranca.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class EnvioCobrancaViewSet(viewsets.ReadOnlyModelViewSet):
    """Auditoria de envios efetuados ou bloqueados pela régua de cobrança."""
    serializer_class = EnvioCobrancaSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return EnvioCobranca.objects.none()
        return EnvioCobranca.objects.filter(tenant=tenant).select_related('parcela', 'regua')


class ConsentimentoContatoViewSet(viewsets.ModelViewSet):
    """Gestão de consentimento LGPD de clientes para comunicação de cobrança."""
    serializer_class = ConsentimentoContatoSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return ConsentimentoContato.objects.none()
        return ConsentimentoContato.objects.filter(tenant=tenant).select_related('cliente')

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=['post'], url_path='revogar')
    def revogar(self, request, pk=None):
        tenant = getattr(request, 'tenant', None)
        obj = self.get_object()
        revogar_consentimento(tenant=tenant, cliente_id=obj.cliente_id, canal=obj.canal)
        obj.refresh_from_db()
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)


class EmitirCobrancaParcelaAPIView(APIView):
    """Emissão idempotente de Boleto e PIX para parcela financeira."""
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def post(self, request):
        tenant = getattr(request, 'tenant', None)
        parcela_id = request.data.get('parcela_id')
        if not parcela_id:
            return Response({'detail': "Campo parcela_id é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            parcela = emitir_cobranca_parcela(tenant=tenant, parcela_id=int(parcela_id))
            from financeiro.serializers import ParcelaFinanceiraSerializer
            return Response(ParcelaFinanceiraSerializer(parcela).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class WebhookCobrancaAPIView(APIView):
    """Endpoint receptor de webhooks de gateways de pagamento (Asaas, etc.) com validação HMAC."""
    permission_classes = []  # Aberto para gateways bancários externos autenticados via assinatura criptográfica

    def post(self, request):
        # Localiza o tenant via header, query param ou subdomínio
        tenant_id = request.headers.get('X-Tenant-ID') or request.query_params.get('tenant_id')
        from core.models import Tenant
        tenant = None
        if tenant_id:
            tenant = Tenant.objects.filter(id=tenant_id).first()
        else:
            tenant = getattr(request, 'tenant', None)
            if not tenant:
                tenant = Tenant.objects.first()

        if not tenant:
            return Response({'detail': "Tenant não localizado para o webhook."}, status=status.HTTP_400_BAD_REQUEST)

        signature = request.headers.get('Asaas-Access-Token') or request.headers.get('X-Signature') or ''
        raw_body = request.body

        try:
            resultado = processar_webhook_cobranca(
                tenant=tenant,
                payload=request.data,
                signature=signature,
                raw_body=raw_body
            )
            return Response(resultado, status=status.HTTP_200_OK)
        except AssinaturaInvalidaError as e:
            return Response({'detail': str(e)}, status=status.HTTP_401_UNAUTHORIZED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class MarcarProtestoManualAPIView(APIView):
    """Marcação manual de protesto / negativação em parcela financeira (Sprint 10A - Tarefa 9)."""
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def post(self, request, pk):
        tenant = getattr(request, 'tenant', None)
        try:
            parcela = ParcelaFinanceira.objects.select_for_update().get(id=pk, tenant=tenant)
            if parcela.status == 'PAGA':
                return Response({'detail': "Não é possível protestar uma parcela já liquidada."}, status=status.HTTP_400_BAD_REQUEST)
            parcela.status = 'EM_PROTESTO'
            parcela.save(update_fields=['status', 'atualizado_em'])
            from financeiro.serializers import ParcelaFinanceiraSerializer
            return Response(ParcelaFinanceiraSerializer(parcela).data, status=status.HTTP_200_OK)
        except ParcelaFinanceira.DoesNotExist:
            return Response({'detail': "Parcela não encontrada."}, status=status.HTTP_404_NOT_FOUND)


# ==============================================================================
# SPRINT 10B: DEPRECIAÇÃO, DRE, ORÇAMENTO, PDD, SNAPSHOTS E EXPORTAÇÕES
# ==============================================================================

class DepreciacaoViewSet(BaseFinanceiroViewSet):
    """
    Ledger e cálculo de depreciação mensal de ativos imobilizados e cilindros (Sprint 10B - Tarefa 1).
    """
    queryset = DepreciacaoMensal.unscoped.all()
    serializer_class = DepreciacaoMensalSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        tipo_alvo = self.request.query_params.get('tipo_alvo')
        if tipo_alvo:
            qs = qs.filter(tipo_alvo=tipo_alvo.upper())
        periodo = self.request.query_params.get('periodo')
        if periodo:
            qs = qs.filter(periodo=periodo)
        return qs.order_by('-periodo', 'tipo_alvo', 'alvo_id')

    @action(detail=False, methods=['post'], url_path='calcular-mensal')
    def calcular_mensal(self, request):
        from financeiro.serializers import CalcularDepreciacaoMensalInputSerializer, LancamentoContabilSerializer
        from financeiro.services.depreciacao_service import calcular_depreciacao_mensal

        ser = CalcularDepreciacaoMensalInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            itens, lancamento = calcular_depreciacao_mensal(
                tenant=tenant,
                periodo=ser.validated_data['periodo'],
                usuario=request.user
            )
            return Response({
                'total_alvos_depreciados': len(itens),
                'lancamento': LancamentoContabilSerializer(lancamento).data if lancamento else None,
                'detalhe_ledger': DepreciacaoMensalSerializer(itens, many=True).data
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='revisar-vida-util')
    def revisar_vida(self, request):
        from financeiro.serializers import RevisaoVidaUtilSerializer
        from financeiro.services.depreciacao_service import revisar_vida_util

        tipo_alvo = request.data.get('tipo_alvo')
        alvo_id = request.data.get('alvo_id')
        data_revisao = request.data.get('data_revisao')
        nova_vida_meses = request.data.get('nova_vida_meses')
        novo_valor_residual = request.data.get('novo_valor_residual')
        motivo = request.data.get('motivo', '')
        tenant = getattr(request, 'tenant', None)

        if not (tipo_alvo and alvo_id and data_revisao and nova_vida_meses):
            return Response(
                {'detail': "Campos tipo_alvo, alvo_id, data_revisao e nova_vida_meses são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            rev = revisar_vida_util(
                tenant=tenant,
                tipo_alvo=tipo_alvo,
                alvo_id=str(alvo_id),
                data_revisao=data_revisao,
                nova_vida_meses=int(nova_vida_meses),
                novo_valor_residual=Decimal(str(novo_valor_residual)) if novo_valor_residual is not None else None,
                motivo=motivo,
                usuario=request.user
            )
            return Response(RevisaoVidaUtilSerializer(rev).data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='baixar-patrimonio')
    def baixar_patrimonio(self, request):
        from financeiro.serializers import BaixarPatrimonioInputSerializer, LancamentoContabilSerializer
        from financeiro.services.depreciacao_service import baixar_patrimonio_contabil

        ser = BaixarPatrimonioInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)
        vd = ser.validated_data

        try:
            lancamento, resultado_alienacao = baixar_patrimonio_contabil(
                tenant=tenant,
                tipo_alvo=vd['tipo_alvo'],
                alvo_id=vd['alvo_id'],
                data_baixa=vd['data_baixa'],
                motivo=vd['motivo'],
                valor_recebido=vd.get('valor_recebido', Decimal('0.00')),
                conta_caixa_id=vd.get('conta_caixa_id'),
                usuario=request.user
            )
            return Response({
                'status': 'sucesso',
                'resultado_alienacao': str(resultado_alienacao),
                'lancamento': LancamentoContabilSerializer(lancamento).data if lancamento else None
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='capitalizar-reteste')
    def capitalizar_reteste(self, request):
        from financeiro.services.depreciacao_service import capitalizar_reteste_componente

        cilindro_id = request.data.get('cilindro_id')
        reteste_id = request.data.get('reteste_id')
        custo_servico_reteste = request.data.get('custo_servico_reteste')
        data_reteste = request.data.get('data_reteste')
        periodicidade_meses = request.data.get('periodicidade_meses', 60)
        tenant = getattr(request, 'tenant', None)

        if not (cilindro_id and reteste_id and custo_servico_reteste and data_reteste):
            return Response(
                {'detail': "Campos cilindro_id, reteste_id, custo_servico_reteste e data_reteste são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            ativo = capitalizar_reteste_componente(
                tenant=tenant,
                cilindro_id=cilindro_id,
                reteste_id=reteste_id,
                custo_servico_reteste=Decimal(str(custo_servico_reteste)),
                data_reteste=data_reteste,
                periodicidade_meses=int(periodicidade_meses)
            )
            return Response({
                'status': 'sucesso',
                'ativo_imobilizado_id': ativo.id,
                'numero_patrimonio': ativo.numero_patrimonio,
                'valor_aquisicao': str(ativo.valor_aquisicao),
                'vida_util_meses': ativo.vida_util_meses
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class RevisaoVidaUtilViewSet(BaseFinanceiroReadOnlyViewSet):
    """Histórico de revisões prospectivas de vida útil (CPC 23)."""
    queryset = RevisaoVidaUtil.unscoped.all()
    from financeiro.serializers import RevisaoVidaUtilSerializer
    serializer_class = RevisaoVidaUtilSerializer


class SaldoMensalContaViewSet(BaseFinanceiroReadOnlyViewSet):
    """
    Snapshots de Saldos Mensais por Conta Contábil e Dimensões (Sprint 10B - Tarefa 6).
    """
    queryset = SaldoMensalConta.unscoped.all()
    from financeiro.serializers import SaldoMensalContaSerializer
    serializer_class = SaldoMensalContaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        ano_mes = self.request.query_params.get('ano_mes')
        if ano_mes:
            qs = qs.filter(ano_mes=ano_mes)
        conta_id = self.request.query_params.get('conta_id')
        if conta_id:
            qs = qs.filter(conta_id=conta_id)
        return qs.order_by('ano_mes', 'conta')

    @action(detail=False, methods=['post'], url_path='reconstruir')
    def reconstruir(self, request):
        from financeiro.serializers import ReconstruirSaldosInputSerializer
        from financeiro.services.snapshot_service import reconstruir_saldos

        ser = ReconstruirSaldosInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            total = reconstruir_saldos(tenant=tenant, periodo=ser.validated_data['periodo'])
            return Response({
                'status': 'sucesso',
                'periodo': ser.validated_data['periodo'],
                'snapshots_reconstruidos': total
            }, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='verificar-integridade')
    def verificar_integridade(self, request):
        from financeiro.services.snapshot_service import verificar_integridade_snapshots

        periodo = request.query_params.get('periodo')
        if not periodo:
            return Response({'detail': "Parâmetro 'periodo' (AAAA-MM) é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
        tenant = getattr(request, 'tenant', None)

        valido, divergencias = verificar_integridade_snapshots(tenant=tenant, periodo=periodo)
        return Response({
            'periodo': periodo,
            'valido': valido,
            'total_divergencias': len(divergencias),
            'divergencias': divergencias
        }, status=status.HTTP_200_OK if valido else status.HTTP_409_CONFLICT)


class DREAPIView(TenantViewSetMixin, APIView):
    """
    Demonstração do Resultado do Exercício (DRE) por Competência (Sprint 10B - Tarefa 7).
    Apresenta as 12 linhas da v2.0 com tratamento de 8.1 (antes do EBITDA) e 8.2 (fora do EBITDA).
    """
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        from financeiro.serializers import DREConsultaInputSerializer
        from financeiro.services.dre_service import dre

        ser = DREConsultaInputSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        tenant = getattr(request, 'tenant', None)

        try:
            resultado = dre(
                tenant=tenant,
                periodo_ini=vd['periodo_ini'],
                periodo_fim=vd['periodo_fim'],
                filial=vd.get('filial_id'),
                centro_custo=vd.get('centro_custo_id'),
                produto_gas=vd.get('produto_gas_id'),
                comparar_com=vd.get('comparar_com'),
                orcamento_id=vd.get('orcamento_id')
            )
            return Response(resultado, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ParametroTributarioLucroViewSet(BaseFinanceiroViewSet):
    """Parâmetros e cálculo de provisão de IRPJ e CSLL (Sprint 10B - Tarefa 8)."""
    queryset = ParametroTributarioLucro.unscoped.all()
    from financeiro.serializers import ParametroTributarioLucroSerializer
    serializer_class = ParametroTributarioLucroSerializer

    @action(detail=False, methods=['post'], url_path='calcular-provisao')
    def calcular_provisao(self, request):
        from financeiro.serializers import LancamentoContabilSerializer
        from financeiro.services.tributario_service import calcular_e_lancar_provisao_tributaria

        periodo = request.data.get('periodo')
        if not periodo:
            return Response({'detail': "Parâmetro 'periodo' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
        tenant = getattr(request, 'tenant', None)

        try:
            lancamento = calcular_e_lancar_provisao_tributaria(
                tenant=tenant,
                periodo=periodo,
                usuario=request.user
            )
            return Response({
                'status': 'sucesso',
                'lancamento': LancamentoContabilSerializer(lancamento).data if lancamento else None
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class OrcamentoViewSet(BaseFinanceiroViewSet):
    """Orçamento Anual e Itens Mensais (Sprint 10B - Tarefa 9)."""
    queryset = Orcamento.unscoped.all()
    from financeiro.serializers import OrcamentoSerializer
    serializer_class = OrcamentoSerializer

    @action(detail=True, methods=['post'], url_path='aprovar')
    def aprovar(self, request, pk=None):
        from financeiro.services.orcamento_service import aprovar_orcamento
        tenant = getattr(request, 'tenant', None)
        try:
            orc = aprovar_orcamento(tenant=tenant, orcamento_id=pk, usuario=request.user)
            from financeiro.serializers import OrcamentoSerializer
            return Response(OrcamentoSerializer(orc).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='importar-csv')
    def importar_csv(self, request):
        from financeiro.serializers import ImportarOrcamentoCSVSerializer
        from financeiro.services.orcamento_service import importar_orcamento_csv

        ser = ImportarOrcamentoCSVSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            total = importar_orcamento_csv(
                tenant=tenant,
                orcamento_id=ser.validated_data['orcamento_id'],
                csv_file=ser.validated_data['arquivo']
            )
            return Response({
                'status': 'sucesso',
                'linhas_importadas': total
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ParametroPDDViewSet(BaseFinanceiroViewSet):
    """Parâmetros e execução de Provisão para Devedores Duvidosos (Sprint 10B - Tarefa 10)."""
    queryset = ParametroPDD.unscoped.all()
    from financeiro.serializers import ParametroPDDSerializer
    serializer_class = ParametroPDDSerializer

    @action(detail=False, methods=['post'], url_path='calcular')
    def calcular(self, request):
        from financeiro.serializers import CalcularPDDInputSerializer, LancamentoContabilSerializer
        from financeiro.services.pdd_service import calcular_pdd

        ser = CalcularPDDInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            res = calcular_pdd(
                tenant=tenant,
                periodo=ser.validated_data['periodo'],
                usuario=request.user
            )
            lanc = res.get('lancamento')
            return Response({
                'periodo': str(res['periodo']),
                'provisao_necessaria': str(res['provisao_necessaria']),
                'provisao_vigente': str(res['provisao_vigente']),
                'ajuste': str(res['ajuste']),
                'lancamento': LancamentoContabilSerializer(lanc).data if lanc else None
            }, status=status.HTTP_201_CREATED if lanc else status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='baixar-perda')
    def baixar_perda(self, request):
        from financeiro.serializers import BaixarPerdaPDDInputSerializer, LancamentoContabilSerializer
        from financeiro.services.pdd_service import baixar_perda_pdd

        ser = BaixarPerdaPDDInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)

        try:
            lanc = baixar_perda_pdd(
                tenant=tenant,
                parcela_id=ser.validated_data['parcela_id'],
                motivo=ser.validated_data['motivo'],
                usuario=request.user
            )
            return Response({
                'status': 'sucesso',
                'lancamento': LancamentoContabilSerializer(lanc).data
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class LancamentoManualViewSet(BaseFinanceiroViewSet):
    """Lançamentos Manuais e Provisões com Alçadas e Aprovação (Sprint 10B - Tarefa 11)."""
    queryset = LancamentoManualPendente.unscoped.all()
    from financeiro.serializers import LancamentoManualPendenteSerializer
    serializer_class = LancamentoManualPendenteSerializer

    def create(self, request, *args, **kwargs):
        from financeiro.serializers import CriarLancamentoManualInputSerializer, LancamentoContabilSerializer
        from financeiro.services.lancamento_manual_service import criar_lancamento_manual

        ser = CriarLancamentoManualInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)
        vd = ser.validated_data

        try:
            pendente, lancamento = criar_lancamento_manual(
                tenant=tenant,
                data_competencia=vd['data_competencia'],
                historico=vd['historico'],
                partidas_data=vd['partidas'],
                usuario=request.user
            )
            if lancamento:
                return Response({
                    'status': 'ESCRITURADO_DIRETO',
                    'lancamento': LancamentoContabilSerializer(lancamento).data
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'status': 'PENDENTE_APROVACAO',
                    'solicitacao': LancamentoManualPendenteSerializer(pendente).data
                }, status=status.HTTP_202_ACCEPTED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='aprovar')
    def aprovar(self, request, pk=None):
        from financeiro.serializers import LancamentoContabilSerializer
        from financeiro.services.lancamento_manual_service import aprovar_lancamento_manual
        obj = self.get_object()
        tenant = getattr(request, 'tenant', None)

        try:
            lanc = aprovar_lancamento_manual(tenant=tenant, pendente_id=obj.id, usuario=request.user)
            return Response({
                'status': 'sucesso',
                'lancamento': LancamentoContabilSerializer(lanc).data
            }, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='rejeitar')
    def rejeitar(self, request, pk=None):
        from financeiro.services.lancamento_manual_service import rejeitar_lancamento_manual
        obj = self.get_object()
        tenant = getattr(request, 'tenant', None)
        motivo = request.data.get('motivo', '')

        try:
            pendente = rejeitar_lancamento_manual(tenant=tenant, pendente_id=obj.id, motivo=motivo, usuario=request.user)
            from financeiro.serializers import LancamentoManualPendenteSerializer
            return Response(LancamentoManualPendenteSerializer(pendente).data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='importar-provisoes-csv')
    def importar_provisoes(self, request):
        from financeiro.serializers import ImportarProvisoesCSVSerializer, LancamentoManualPendenteSerializer
        from financeiro.services.lancamento_manual_service import importar_provisoes_csv

        ser = ImportarProvisoesCSVSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, 'tenant', None)
        vd = ser.validated_data

        try:
            solicitacoes = importar_provisoes_csv(
                tenant=tenant,
                csv_file=vd['arquivo'],
                data_competencia=vd['data_competencia'],
                historico_padrao=vd.get('historico_padrao', 'Importação de Provisões Folha/Tributos'),
                usuario=request.user
            )
            return Response({
                'status': 'sucesso',
                'total_solicitacoes_criadas': len(solicitacoes),
                'solicitacoes': LancamentoManualPendenteSerializer(solicitacoes, many=True).data
            }, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ExportacaoContabilAPIView(TenantViewSetMixin, APIView):
    """
    Exportação Contábil em CSV e XLSX para Balancete, Razão, DRE e Layout Genérico (Sprint 10B - Tarefa 12).
    """
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        from financeiro.services.exportacao_service import (
            exportar_balancete_csv,
            exportar_razao_csv,
            exportar_dre_csv,
            exportar_contabil_generico_csv,
        )

        tenant = getattr(request, 'tenant', None)
        tipo = request.query_params.get('tipo', 'balancete').lower()
        dt_ini = request.query_params.get('data_inicio') or request.query_params.get('periodo_ini')
        dt_fim = request.query_params.get('data_fim') or request.query_params.get('periodo_fim')

        hoje = timezone.localdate()
        if not dt_ini:
            dt_ini = hoje.replace(day=1).isoformat()
        if not dt_fim:
            dt_fim = hoje.isoformat()

        if tipo == 'balancete':
            content = exportar_balancete_csv(tenant, dt_ini, dt_fim, request.query_params.get('filial_id'))
            filename = f"balancete_{dt_ini}_{dt_fim}.csv"
        elif tipo == 'razao':
            conta_id = request.query_params.get('conta_id')
            if not conta_id:
                return Response({'detail': "Parâmetro 'conta_id' é obrigatório para exportação de Razão."}, status=status.HTTP_400_BAD_REQUEST)
            content = exportar_razao_csv(tenant, int(conta_id), dt_ini, dt_fim)
            filename = f"razao_conta_{conta_id}_{dt_ini}_{dt_fim}.csv"
        elif tipo == 'dre':
            content = exportar_dre_csv(
                tenant,
                dt_ini[:7],
                dt_fim[:7],
                filial=request.query_params.get('filial_id'),
                centro_custo=request.query_params.get('centro_custo_id'),
                produto_gas=request.query_params.get('produto_gas_id')
            )
            filename = f"dre_{dt_ini[:7]}_{dt_fim[:7]}.csv"
        elif tipo in ('generico', 'contabil_generico'):
            content = exportar_contabil_generico_csv(tenant, dt_ini, dt_fim)
            filename = f"exportacao_contabil_generica_{dt_ini}_{dt_fim}.csv"
        else:
            return Response({'detail': f"Tipo de exportação '{tipo}' inválido."}, status=status.HTTP_400_BAD_REQUEST)

        response = HttpResponse(content, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# ==============================================================================
# SPRINT 10C: FLUXO DE CAIXA, CENÁRIOS, ALERTA E GESTÃO
# ==============================================================================

class PerfilPagamentoClienteViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Exibição e recálculo de perfil de pagamento de clientes (Sprint 10C - Tarefa 2).
    """
    serializer_class = PerfilPagamentoClienteSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return PerfilPagamentoCliente.unscoped.filter(tenant=tenant).select_related('cliente')

    @action(detail=False, methods=['post'], url_path='recalcular')
    def recalcular(self, request):
        from financeiro.services.projecao_caixa_service import recalcular_perfil_pagamento_clientes
        tenant = getattr(request, 'tenant', None)
        perfis = recalcular_perfil_pagamento_clientes(tenant=tenant)
        return Response({
            'total_clientes_processados': len(perfis),
            'mensagem': 'Perfis de pagamento recalculados com sucesso.'
        }, status=status.HTTP_200_OK)


class RecorrenciaFinanceiraViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    CRUD de despesas e receitas recorrentes (Sprint 10C - Tarefa 2).
    """
    serializer_class = RecorrenciaFinanceiraSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return RecorrenciaFinanceira.unscoped.filter(tenant=tenant).select_related('conta', 'centro_custo')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class AlertaCaixaViewSet(TenantViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Visualização e gestão de alertas de caixa (Sprint 10C - Tarefa 4).
    """
    serializer_class = AlertaCaixaSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return AlertaCaixa.unscoped.filter(tenant=tenant)

    @action(detail=True, methods=['post'], url_path='resolver')
    def resolver(self, request, pk=None):
        alerta = self.get_object()
        alerta.resolvido = True
        alerta.save(update_fields=['resolvido'])
        return Response({'status': 'ALERTA_RESOLVIDO', 'id': alerta.id}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='verificar')
    def verificar(self, request):
        from financeiro.services.alerta_caixa_service import verificar_e_gerar_alerta_caixa
        tenant = getattr(request, 'tenant', None)
        res = verificar_e_gerar_alerta_caixa(tenant=tenant)
        if res.get('alerta_gerado'):
            alerta = AlertaCaixa.unscoped.get(id=res['alerta_id'], tenant=tenant)
            ser = self.get_serializer(alerta)
            return Response(ser.data, status=status.HTTP_201_CREATED)
        return Response({'mensagem': 'Saldo de caixa saudável. Nenhum alerta necessário.'}, status=status.HTTP_200_OK)


class ParametroGestaoTenantViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    """
    Configuração de parâmetros estratégicos de gestão da empresa (Sprint 10C).
    """
    serializer_class = ParametroGestaoTenantSerializer
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        return ParametroGestaoTenant.unscoped.filter(tenant=tenant)

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class FluxoCaixaRealizadoAPIView(TenantViewSetMixin, APIView):
    """
    Fluxo de caixa realizado: derivado de MovimentoConta, agrupado por grupo_fluxo e conta (Sprint 10C - Tarefa 1).
    Exige permissão CanViewDRE.
    """
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        CanViewDRE,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        from financeiro.services.fluxo_caixa_service import obter_fluxo_caixa_realizado
        tenant = getattr(request, 'tenant', None)
        data_inicio = request.query_params.get('data_inicio')
        data_fim = request.query_params.get('data_fim')
        conta_id = request.query_params.get('conta_id')
        conta_id_int = int(conta_id) if conta_id else None

        resultado = obter_fluxo_caixa_realizado(
            tenant=tenant,
            data_inicio=data_inicio,
            data_fim=data_fim,
            conta_id=conta_id_int
        )
        return Response(resultado, status=status.HTTP_200_OK)


class ProjecaoCaixaCenariosAPIView(TenantViewSetMixin, APIView):
    """
    Projeção de fluxo de caixa em 3 cenários diários (Otimista, Realista, Pessimista) (Sprint 10C - Tarefa 3).
    Exige permissão CanViewDRE.
    """
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        CanViewDRE,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        from financeiro.services.projecao_caixa_service import projetar_fluxo_caixa_cenarios
        tenant = getattr(request, 'tenant', None)
        dias = int(request.query_params.get('dias', 90))
        fator_str = request.query_params.get('fator_majoracao')
        fator = Decimal(fator_str) if fator_str else None

        resultado = projetar_fluxo_caixa_cenarios(
            tenant=tenant,
            dias_horizonte=dias,
            fator_majoracao_pessimista=fator
        )
        return Response(resultado, status=status.HTTP_200_OK)


# ==============================================================================
# SPRINT 11C: CRÉDITO, LIMITES E PROMESSA DE PAGAMENTO
# ==============================================================================

class ParametroCreditoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_serializer_class(self):
        from financeiro.serializers import ParametroCreditoSerializer
        return ParametroCreditoSerializer

    def get_queryset(self):
        from financeiro.models import ParametroCredito
        tenant = getattr(self.request, 'tenant', None)
        return ParametroCredito.unscoped.filter(tenant=tenant)

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class LimiteCreditoClienteViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_serializer_class(self):
        from financeiro.serializers import LimiteCreditoClienteSerializer
        return LimiteCreditoClienteSerializer

    def get_queryset(self):
        from financeiro.models import LimiteCreditoCliente
        tenant = getattr(self.request, 'tenant', None)
        return LimiteCreditoCliente.unscoped.filter(tenant=tenant).select_related('cliente')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant)


class PromessaPagamentoViewSet(TenantViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get_serializer_class(self):
        from financeiro.serializers import PromessaPagamentoSerializer
        return PromessaPagamentoSerializer

    def get_queryset(self):
        from financeiro.models import PromessaPagamento
        tenant = getattr(self.request, 'tenant', None)
        return PromessaPagamento.unscoped.filter(tenant=tenant).select_related('cliente', 'criado_por').prefetch_related('parcelas')

    def perform_create(self, serializer):
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(tenant=tenant, criado_por=self.request.user)

    @action(detail=False, methods=['post'], url_path='atualizar-status-diario')
    def atualizar_status_diario(self, request):
        from financeiro.services.credito_service import atualizar_status_promessas_diario
        tenant = getattr(request, 'tenant', None)
        res = atualizar_status_promessas_diario(tenant=tenant)
        return Response(res, status=status.HTTP_200_OK)


class PainelBloqueiosAPIView(TenantViewSetMixin, APIView):
    """
    Painel de acompanhamento de clientes com bloqueio comercial, promessas ativas e liberações recentes (Sprint 11C - Tarefa 8).
    """
    permission_classes = [
        IsAuthenticated,
        IsTenantMember,
        RequiresModuleFinanceiro,
        IsTenantSubscriptionActive,
    ]

    def get(self, request):
        from clientes.models import Cliente
        from financeiro.models import PromessaPagamento
        from vendas.models import Venda, LiberacaoBloqueio
        from financeiro.services.credito_service import avaliar_credito

        tenant = getattr(request, 'tenant', None)
        hoje = timezone.localdate()

        # 1. Vendas atualmente bloqueadas
        vendas_bloqueadas = Venda.unscoped.filter(
            tenant=tenant,
            status='BLOQUEADO_FINANCEIRO'
        ).select_related('cliente', 'vendedor').order_by('-data_venda')[:50]

        vendas_bloq_data = [
            {
                'venda_id': v.id,
                'cliente_id': v.cliente_id,
                'cliente_nome': v.cliente.nome,
                'cliente_cnpj': v.cliente.cnpj,
                'valor_total': v.valor_total,
                'data_venda': v.data_venda.isoformat(),
                'vendedor_nome': v.vendedor.username if v.vendedor else None,
            }
            for v in vendas_bloqueadas
        ]

        # 2. Promessas ativas e vencendo nos próximos 7 dias
        promessas_ativas = PromessaPagamento.unscoped.filter(
            tenant=tenant,
            status='ATIVA'
        ).select_related('cliente').order_by('data_promessa')[:50]

        promessas_data = [
            {
                'id': p.id,
                'cliente_id': p.cliente_id,
                'cliente_nome': p.cliente.nome,
                'data_promessa': p.data_promessa.isoformat(),
                'valor': p.valor,
                'dias_restantes': (p.data_promessa - hoje).days,
                'status': p.status,
            }
            for p in promessas_ativas
        ]

        # 3. Liberações recentes de vendas
        liberacoes = LiberacaoBloqueio.unscoped.filter(
            tenant=tenant
        ).select_related('venda', 'usuario').order_by('-data')[:30]

        liberacoes_data = [
            {
                'id': lib.id,
                'venda_id': lib.venda_id,
                'usuario': lib.usuario.username,
                'motivo': lib.motivo,
                'valor': lib.valor,
                'data': lib.data.isoformat(),
            }
            for lib in liberacoes
        ]

        return Response({
            'total_vendas_bloqueadas': len(vendas_bloq_data),
            'vendas_bloqueadas': vendas_bloq_data,
            'total_promessas_ativas': len(promessas_data),
            'promessas_ativas': promessas_data,
            'liberacoes_recentes': liberacoes_data,
        }, status=status.HTTP_200_OK)







