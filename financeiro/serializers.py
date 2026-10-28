"""
Serializers DRF para o módulo Financeiro (Sprint 9A).
"""

from decimal import Decimal
from rest_framework import serializers

from financeiro.models import (
    PlanoContas,
    CentroCusto,
    Fornecedor,
    CondicaoPagamento,
    PeriodoContabil,
    ContaFinanceira,
    MovimentoConta,
    LancamentoContabil,
    PartidaContabil,
    ParametroFinanceiroTenant,
    TituloFinanceiro,
    RetencaoTitulo,
    RateioCentroCusto,
    ParcelaFinanceira,
    BaixaParcela,
    Renegociacao,
    RenegociacaoParcelaOrigem,
    AlcadaAprovacao,
    AprovacaoTitulo,
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
from financeiro.services.conta import saldo_em


class PlanoContasSerializer(serializers.ModelSerializer):
    filhos_count = serializers.IntegerField(source='filhos.count', read_only=True)

    class Meta:
        model = PlanoContas
        fields = [
            'id',
            'codigo_estrutural',
            'nome',
            'pai',
            'nivel',
            'natureza_saldo',
            'tipo',
            'aceita_lancamento',
            'tipo_dre',
            'grupo_fluxo',
            'ativo',
            'filhos_count',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'filhos_count', 'criado_em', 'atualizado_em']


class CentroCustoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CentroCusto
        fields = ['id', 'codigo', 'nome', 'pai', 'ativo', 'criado_em', 'atualizado_em']
        read_only_fields = ['id', 'criado_em', 'atualizado_em']


class FornecedorSerializer(serializers.ModelSerializer):
    dados_bancarios_plain = serializers.CharField(write_only=True, required=False, allow_blank=True)
    dados_bancarios_exibicao = serializers.CharField(source='dados_bancarios_descriptografados', read_only=True)

    class Meta:
        model = Fornecedor
        fields = [
            'id',
            'razao_social',
            'nome_fantasia',
            'documento',
            'tipo_pessoa',
            'email',
            'telefone',
            'dados_bancarios_plain',
            'dados_bancarios_exibicao',
            'retencoes_padrao_json',
            'ativo',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'dados_bancarios_exibicao', 'criado_em', 'atualizado_em']

    def create(self, validated_data):
        plain_bank = validated_data.pop('dados_bancarios_plain', None)
        instance = super().create(validated_data)
        if plain_bank:
            instance.set_dados_bancarios(plain_bank)
            instance.save(update_fields=['dados_bancarios'])
        return instance

    def update(self, instance, validated_data):
        plain_bank = validated_data.pop('dados_bancarios_plain', None)
        instance = super().update(instance, validated_data)
        if plain_bank is not None:
            instance.set_dados_bancarios(plain_bank)
            instance.save(update_fields=['dados_bancarios'])
        return instance


class CondicaoPagamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CondicaoPagamento
        fields = ['id', 'nome', 'parcelas_json', 'ativo', 'criado_em', 'atualizado_em']
        read_only_fields = ['id', 'criado_em', 'atualizado_em']


class PeriodoContabilSerializer(serializers.ModelSerializer):
    fechado_por_nome = serializers.CharField(source='fechado_por.username', read_only=True)
    reaberto_por_nome = serializers.CharField(source='reaberto_por.username', read_only=True)

    class Meta:
        model = PeriodoContabil
        fields = [
            'id',
            'ano',
            'mes',
            'status',
            'fechado_por',
            'fechado_por_nome',
            'fechado_em',
            'reaberto_por',
            'reaberto_por_nome',
            'reaberto_em',
            'motivo_reabertura',
            'criado_em',
        ]
        read_only_fields = ['id', 'fechado_por', 'fechado_em', 'reaberto_por', 'reaberto_em', 'criado_em']


class FecharPeriodoSerializer(serializers.Serializer):
    ano = serializers.IntegerField(min_value=2000, max_value=2100)
    mes = serializers.IntegerField(min_value=1, max_value=12)


class ReabrirPeriodoSerializer(serializers.Serializer):
    ano = serializers.IntegerField(min_value=2000, max_value=2100)
    mes = serializers.IntegerField(min_value=1, max_value=12)
    motivo = serializers.CharField(min_length=5, max_length=500)


class ContaFinanceiraSerializer(serializers.ModelSerializer):
    saldo_atual = serializers.SerializerMethodField()
    conta_contabil_codigo = serializers.CharField(source='conta_contabil.codigo_estrutural', read_only=True)
    conta_contabil_nome = serializers.CharField(source='conta_contabil.nome', read_only=True)

    class Meta:
        model = ContaFinanceira
        fields = [
            'id',
            'filial',
            'nome',
            'tipo',
            'banco_codigo',
            'agencia',
            'conta',
            'saldo_inicial',
            'data_saldo_inicial',
            'saldo_atual',
            'responsavel_caixa',
            'conta_contabil',
            'conta_contabil_codigo',
            'conta_contabil_nome',
            'ativo',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'saldo_atual', 'criado_em', 'atualizado_em']

    def get_saldo_atual(self, obj) -> str:
        return str(saldo_em(obj))


class MovimentoContaSerializer(serializers.ModelSerializer):
    conta_nome = serializers.CharField(source='conta.nome', read_only=True)

    class Meta:
        model = MovimentoConta
        fields = [
            'id',
            'conta',
            'conta_nome',
            'data_movimento',
            'tipo',
            'tipo_ajuste',
            'valor',
            'baixa',
            'lancamento',
            'conciliado',
            'historico',
            'criado_em',
        ]
        read_only_fields = ['id', 'conta_nome', 'criado_em']


class TransferenciaContasSerializer(serializers.Serializer):
    conta_origem_id = serializers.IntegerField()
    conta_destino_id = serializers.IntegerField()
    valor = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    data_transferencia = serializers.DateField(required=False)
    historico = serializers.CharField(max_length=255, required=False, allow_blank=True)


class PartidaContabilSerializer(serializers.ModelSerializer):
    conta_codigo = serializers.CharField(source='conta_contabil.codigo_estrutural', read_only=True)
    conta_nome = serializers.CharField(source='conta_contabil.nome', read_only=True)

    class Meta:
        model = PartidaContabil
        fields = [
            'id',
            'conta_contabil',
            'conta_codigo',
            'conta_nome',
            'tipo_partida',
            'valor',
            'centro_custo',
            'veiculo',
            'produto_gas',
            'cliente',
            'entrega',
            'criado_em',
        ]
        read_only_fields = ['id', 'conta_codigo', 'conta_nome', 'criado_em']


class LancamentoContabilSerializer(serializers.ModelSerializer):
    partidas = PartidaContabilSerializer(many=True, read_only=True)
    estornado = serializers.SerializerMethodField()

    class Meta:
        model = LancamentoContabil
        fields = [
            'id',
            'numero',
            'filial',
            'data_competencia',
            'data_registro',
            'historico',
            'origem_tipo',
            'origem_id',
            'lancamento_estornado',
            'estornado',
            'hash_anterior',
            'hash_integridade',
            'criado_por',
            'criado_em',
            'partidas',
        ]
        read_only_fields = [
            'id',
            'numero',
            'estornado',
            'hash_anterior',
            'hash_integridade',
            'criado_por',
            'criado_em',
            'partidas',
        ]

    def get_estornado(self, obj) -> bool:
        return obj.estornos.exists()


class PartidaInputSerializer(serializers.Serializer):
    conta_id = serializers.IntegerField()
    tipo_partida = serializers.ChoiceField(choices=['DEBITO', 'CREDITO'])
    valor = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    centro_custo_id = serializers.IntegerField(required=False, allow_null=True)
    veiculo_id = serializers.IntegerField(required=False, allow_null=True)
    produto_gas_id = serializers.IntegerField(required=False, allow_null=True)
    cliente_id = serializers.IntegerField(required=False, allow_null=True)
    entrega_id = serializers.IntegerField(required=False, allow_null=True)


class LancarInputSerializer(serializers.Serializer):
    data_competencia = serializers.DateField()
    historico = serializers.CharField(min_length=3)
    filial_id = serializers.IntegerField(required=False, allow_null=True)
    origem_tipo = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    origem_id = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    partidas = PartidaInputSerializer(many=True, min_length=2)


class EstornarInputSerializer(serializers.Serializer):
    motivo = serializers.CharField(min_length=5, max_length=500)


# ==============================================================================
# SPRINT 9B: TÍTULOS, PARCELAS, BAIXAS, RETENÇÕES E APROVAÇÕES
# ==============================================================================

class RetencaoTituloSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetencaoTitulo
        fields = [
            'id',
            'tipo',
            'base',
            'aliquota',
            'valor',
            'conta_passivo',
            'data_recolhimento',
            'criado_em',
        ]
        read_only_fields = ['id', 'criado_em']


class RateioCentroCustoSerializer(serializers.ModelSerializer):
    centro_custo_nome = serializers.CharField(source='centro_custo.nome', read_only=True)

    class Meta:
        model = RateioCentroCusto
        fields = [
            'id',
            'centro_custo',
            'centro_custo_nome',
            'veiculo',
            'percentual',
            'valor_rateado',
            'criado_em',
        ]
        read_only_fields = ['id', 'centro_custo_nome', 'criado_em']


class ParcelaFinanceiraSerializer(serializers.ModelSerializer):
    esta_vencida = serializers.BooleanField(read_only=True)

    class Meta:
        model = ParcelaFinanceira
        fields = [
            'id',
            'titulo',
            'numero_parcela',
            'total_parcelas',
            'data_vencimento',
            'valor_nominal',
            'saldo_em_aberto',
            'status',
            'esta_vencida',
            'nosso_numero',
            'linha_digitavel',
            'payload_pix',
            'gateway_charge_id',
            'criado_em',
        ]
        read_only_fields = ['id', 'esta_vencida', 'criado_em']


class BaixaParcelaSerializer(serializers.ModelSerializer):
    conta_nome = serializers.CharField(source='conta_financeira.nome', read_only=True)
    executado_por_nome = serializers.CharField(source='executado_por.username', read_only=True)

    class Meta:
        model = BaixaParcela
        fields = [
            'id',
            'parcela',
            'conta_financeira',
            'conta_nome',
            'data_liquidacao',
            'valor_principal',
            'valor_juros',
            'valor_multa',
            'valor_desconto',
            'valor_total_movimentado',
            'valor_tarifa',
            'comprovante',
            'executado_por',
            'executado_por_nome',
            'movimento_conta',
            'lancamento',
            'estornado',
            'estornado_em',
            'motivo_estorno',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'conta_nome',
            'executado_por_nome',
            'valor_total_movimentado',
            'movimento_conta',
            'lancamento',
            'estornado',
            'estornado_em',
            'criado_em',
        ]


class TituloFinanceiroSerializer(serializers.ModelSerializer):
    parcelas = ParcelaFinanceiraSerializer(many=True, read_only=True)
    rateios = RateioCentroCustoSerializer(many=True, read_only=True)
    retencoes = RetencaoTituloSerializer(many=True, read_only=True)
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    fornecedor_nome = serializers.CharField(source='fornecedor.razao_social', read_only=True)
    conta_gerencial_codigo = serializers.CharField(source='conta_gerencial.codigo_estrutural', read_only=True)
    conta_gerencial_nome = serializers.CharField(source='conta_gerencial.nome', read_only=True)

    class Meta:
        model = TituloFinanceiro
        fields = [
            'id',
            'filial',
            'tipo',
            'status',
            'cliente',
            'cliente_nome',
            'fornecedor',
            'fornecedor_nome',
            'beneficiario_texto',
            'conta_gerencial',
            'conta_gerencial_codigo',
            'conta_gerencial_nome',
            'condicao_pagamento',
            'data_emissao',
            'data_competencia',
            'valor_bruto',
            'valor_retencoes',
            'valor_liquido_esperado',
            'origem_tipo',
            'origem_id',
            'historico',
            'criado_por',
            'criado_em',
            'atualizado_em',
            'parcelas',
            'rateios',
            'retencoes',
        ]
        read_only_fields = [
            'id',
            'status',
            'cliente_nome',
            'fornecedor_nome',
            'conta_gerencial_codigo',
            'conta_gerencial_nome',
            'valor_retencoes',
            'valor_liquido_esperado',
            'criado_por',
            'criado_em',
            'atualizado_em',
            'parcelas',
            'rateios',
            'retencoes',
        ]


class TituloCriarInputSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=['RECEBER', 'PAGAR'])
    conta_gerencial_id = serializers.IntegerField()
    valor_bruto = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    data_emissao = serializers.DateField(required=False, allow_null=True)
    data_competencia = serializers.DateField(required=False, allow_null=True)
    filial_id = serializers.IntegerField(required=False, allow_null=True)
    cliente_id = serializers.IntegerField(required=False, allow_null=True)
    fornecedor_id = serializers.IntegerField(required=False, allow_null=True)
    beneficiario_texto = serializers.CharField(required=False, allow_blank=True, default='')
    condicao_pagamento_id = serializers.IntegerField(required=False, allow_null=True)
    origem_tipo = serializers.CharField(max_length=30, required=False, default='MANUAL')
    origem_id = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    historico = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    retencoes = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    rateios = serializers.ListField(child=serializers.DictField(), required=False, default=list)


class TransicionarInputSerializer(serializers.Serializer):
    novo_status = serializers.ChoiceField(choices=['EM_APROVACAO', 'ABERTO', 'CANCELADO', 'RASCUNHO'])
    motivo = serializers.CharField(required=False, allow_blank=True, default='')


class AprovacaoInputSerializer(serializers.Serializer):
    decisao = serializers.ChoiceField(choices=['APROVADO', 'REJEITADO'])
    motivo = serializers.CharField(required=False, allow_blank=True, default='')


class BaixaInputSerializer(serializers.Serializer):
    conta_financeira_id = serializers.IntegerField()
    valor_principal = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    data_liquidacao = serializers.DateField(required=False, allow_null=True)
    valor_juros = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    valor_multa = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    valor_desconto = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    valor_tarifa = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    comprovante = serializers.CharField(required=False, allow_blank=True, default='')


class BaixaEmLoteItemSerializer(serializers.Serializer):
    parcela_id = serializers.IntegerField()
    valor_principal = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    valor_juros = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    valor_multa = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    valor_desconto = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    valor_tarifa = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))


class BaixaEmLoteInputSerializer(serializers.Serializer):
    conta_financeira_id = serializers.IntegerField()
    itens = BaixaEmLoteItemSerializer(many=True, min_length=1)
    data_liquidacao = serializers.DateField(required=False, allow_null=True)
    comprovante = serializers.CharField(required=False, allow_blank=True, default='')


class RenegociacaoInputSerializer(serializers.Serializer):
    parcelas_origem_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    motivo = serializers.CharField(min_length=5)
    desconto_concedido = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    novas_parcelas = serializers.ListField(child=serializers.DictField(), min_length=1)


class RenegociacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Renegociacao
        fields = [
            'id',
            'titulo',
            'motivo',
            'desconto_concedido',
            'aprovado_por',
            'aprovado_em',
            'criado_em',
        ]
        read_only_fields = ['id', 'aprovado_por', 'aprovado_em', 'criado_em']


class AlcadaAprovacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlcadaAprovacao
        fields = [
            'id',
            'tipo',
            'valor_ate',
            'grupo_aprovador',
            'ordem',
            'ativo',
            'criado_em',
        ]
        read_only_fields = ['id', 'criado_em']


class PendenciaContabilizacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PendenciaContabilizacao
        fields = [
            'id',
            'evento',
            'origem_id',
            'payload_json',
            'erro_mensagem',
            'tentativas',
            'resolvido',
            'resolvido_em',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'evento',
            'origem_id',
            'payload_json',
            'erro_mensagem',
            'tentativas',
            'resolvido',
            'resolvido_em',
            'criado_em',
        ]


class ImportacaoSaldoAberturaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportacaoSaldoAbertura
        fields = [
            'id',
            'data_corte',
            'status',
            'total_ativo',
            'total_passivo',
            'total_pl_abertura',
            'dados_json',
            'lancamento',
            'executado_por',
            'confirmado_em',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'status',
            'total_ativo',
            'total_passivo',
            'total_pl_abertura',
            'lancamento',
            'executado_por',
            'confirmado_em',
            'criado_em',
        ]


class SimularSaldoAberturaInputSerializer(serializers.Serializer):
    data_corte = serializers.DateField()
    dados_carga = serializers.DictField()


# ==============================================================================
# SPRINT 9C: DESPESAS DE CAMPO, ANTIFRAUDE, FATURAS E CAIXA DE ROTA
# ==============================================================================

class PrecoReferenciaCombustivelSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrecoReferenciaCombustivel
        fields = [
            'id',
            'uf',
            'municipio',
            'combustivel',
            'semana',
            'preco_medio',
            'criado_em',
        ]
        read_only_fields = ['id', 'criado_em']


class PreLancamentoDespesaCampoSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    motorista_nome = serializers.CharField(source='motorista.get_full_name', read_only=True)

    class Meta:
        model = PreLancamentoDespesaCampo
        fields = [
            'id',
            'tenant',
            'tipo',
            'veiculo',
            'veiculo_placa',
            'motorista',
            'motorista_nome',
            'entrega',
            'data_hora',
            'odometro_informado',
            'litros',
            'valor_informado',
            'preco_litro_calculado',
            'forma_pagamento',
            'posto_nome',
            'posto_cnpj',
            'foto_cupom',
            'latitude',
            'longitude',
            'status',
            'alerta_auditoria',
            'motivos_alerta_json',
            'aprovado_por',
            'aprovado_em',
            'motivo_rejeicao',
            'client_uuid',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = [
            'id',
            'tenant',
            'veiculo_placa',
            'motorista_nome',
            'preco_litro_calculado',
            'status',
            'alerta_auditoria',
            'motivos_alerta_json',
            'aprovado_por',
            'aprovado_em',
            'motivo_rejeicao',
            'criado_em',
            'atualizado_em',
        ]


class PreLancamentoDespesaRejeitarSerializer(serializers.Serializer):
    motivo = serializers.CharField(required=True, min_length=3)


class PreLancamentoDespesaLoteSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False
    )


class ItemFaturaPostoSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)

    class Meta:
        model = ItemFaturaPosto
        fields = [
            'id',
            'fatura',
            'veiculo',
            'veiculo_placa',
            'cartao_numero',
            'data_hora',
            'combustivel',
            'litros',
            'valor_total',
            'posto_nome',
            'posto_cnpj',
            'pre_lancamento',
            'status_conciliacao',
            'motivo_divergencia',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'veiculo_placa',
            'pre_lancamento',
            'status_conciliacao',
            'motivo_divergencia',
            'criado_em',
        ]


class FaturaConsolidadaPostoSerializer(serializers.ModelSerializer):
    itens = ItemFaturaPostoSerializer(many=True, read_only=True)
    itens_count = serializers.IntegerField(source='itens.count', read_only=True)

    class Meta:
        model = FaturaConsolidadaPosto
        fields = [
            'id',
            'tenant',
            'cartao_ou_convenio',
            'numero_fatura',
            'periodo_inicio',
            'periodo_fim',
            'valor_total',
            'status',
            'arquivo_csv',
            'itens_count',
            'itens',
            'criado_por',
            'aprovado_por',
            'aprovado_em',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = [
            'id',
            'tenant',
            'status',
            'itens_count',
            'itens',
            'criado_por',
            'aprovado_por',
            'aprovado_em',
            'criado_em',
            'atualizado_em',
        ]


class ImportarFaturaCSVSerializer(serializers.Serializer):
    cartao_ou_convenio = serializers.CharField(max_length=64, required=True)
    numero_fatura = serializers.CharField(max_length=64, required=False, default='')
    arquivo = serializers.FileField(required=True)


class ChequeRecebidoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChequeRecebido
        fields = [
            'id',
            'tenant',
            'fechamento',
            'numero',
            'banco',
            'valor',
            'bom_para',
            'status',
            'criado_em',
        ]
        read_only_fields = ['id', 'tenant', 'criado_em']


class QuebraCaixaSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuebraCaixa
        fields = [
            'id',
            'tenant',
            'fechamento',
            'motorista',
            'data',
            'tipo',
            'valor',
            'tratamento',
            'lancamento',
            'justificativa',
            'criado_em',
        ]
        read_only_fields = ['id', 'tenant', 'lancamento', 'criado_em']


class FechamentoCaixaRotaSerializer(serializers.ModelSerializer):
    motorista_nome = serializers.CharField(source='motorista.get_full_name', read_only=True)
    conta_caixa_nome = serializers.CharField(source='conta_caixa.nome', read_only=True)
    cheques = ChequeRecebidoSerializer(many=True, read_only=True)
    quebras = QuebraCaixaSerializer(many=True, read_only=True)

    class Meta:
        model = FechamentoCaixaRota
        fields = [
            'id',
            'tenant',
            'conta_caixa',
            'conta_caixa_nome',
            'motorista',
            'motorista_nome',
            'data',
            'saldo_esperado',
            'valor_contado_cego',
            'valor_entregue_tesouraria',
            'diferenca',
            'status',
            'conferido_por',
            'transferencia',
            'cheques',
            'quebras',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = [
            'id',
            'tenant',
            'motorista_nome',
            'conta_caixa_nome',
            'saldo_esperado',
            'diferenca',
            'status',
            'conferido_por',
            'transferencia',
            'cheques',
            'quebras',
            'criado_em',
            'atualizado_em',
        ]

    def to_representation(self, instance):
        """
        [Sprint 9C - Contagem Cega de Caixa de Rota]
        O saldo esperado e a diferença NUNCA são expostos antes do registro da contagem cega.
        """
        ret = super().to_representation(instance)
        if instance.valor_contado_cego is None:
            ret['saldo_esperado'] = None
            ret['diferenca'] = None
        return ret


class RegistrarContagemCegaSerializer(serializers.Serializer):
    valor_contado_cego = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=True
    )


class ConferirFecharCaixaSerializer(serializers.Serializer):
    valor_entregue_tesouraria = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=True
    )
    conta_cofre_id = serializers.IntegerField(required=False, allow_null=True)


# ==============================================================================
# SPRINT 10A: SERIALIZERS DE CONCILIAÇÃO, COBRANÇA E RÉGUA
# ==============================================================================

class ImportacaoExtratoSerializer(serializers.ModelSerializer):
    conta_nome = serializers.CharField(source='conta.nome', read_only=True)
    usuario_nome = serializers.CharField(source='usuario.username', read_only=True)

    class Meta:
        from financeiro.models import ImportacaoExtrato
        model = ImportacaoExtrato
        fields = [
            'id',
            'tenant',
            'conta',
            'conta_nome',
            'tipo',
            'arquivo',
            'hash_arquivo',
            'periodo_ini',
            'periodo_fim',
            'saldo_final_arquivo',
            'saldo_sistema_apurado',
            'diferenca_saldo',
            'usuario',
            'usuario_nome',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'tenant',
            'conta_nome',
            'hash_arquivo',
            'periodo_ini',
            'periodo_fim',
            'saldo_final_arquivo',
            'saldo_sistema_apurado',
            'diferenca_saldo',
            'usuario',
            'usuario_nome',
            'criado_em',
        ]


class ExtratoBancarioItemSerializer(serializers.ModelSerializer):
    conta_nome = serializers.CharField(source='conta.nome', read_only=True)

    class Meta:
        from financeiro.models import ExtratoBancarioItem
        model = ExtratoBancarioItem
        fields = [
            'id',
            'tenant',
            'importacao',
            'conta',
            'conta_nome',
            'data',
            'valor',
            'descricao',
            'documento',
            'fitid',
            'hash_dedup',
            'status',
            'movimento',
            'score',
            'regra_aplicada',
            'motivo_sugestao',
            'parcelas_sugeridas_ids',
            'conciliado',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'tenant',
            'conta_nome',
            'hash_dedup',
            'criado_em',
        ]


class ConciliarManualmenteSerializer(serializers.Serializer):
    parcelas_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        required=True
    )


class CriarLancamentoDiretoSerializer(serializers.Serializer):
    conta_contabil_id = serializers.IntegerField(required=True)
    centro_custo_id = serializers.IntegerField(required=False, allow_null=True)
    historico = serializers.CharField(required=False, allow_blank=True, default='')


class DividirItemExtratoSerializer(serializers.Serializer):
    partes = serializers.ListField(
        child=serializers.DictField(),
        min_length=2,
        required=True
    )


class IgnorarItemExtratoSerializer(serializers.Serializer):
    motivo = serializers.CharField(required=False, allow_blank=True, default='Ignorado pelo operador')


class DesfazerConciliacaoSerializer(serializers.Serializer):
    motivo = serializers.CharField(required=False, allow_blank=True, default='Desfazimento de conciliação')


class RegraConciliacaoSerializer(serializers.ModelSerializer):
    conta_contabil_nome = serializers.CharField(source='conta_contabil.nome', read_only=True)
    centro_custo_nome = serializers.CharField(source='centro_custo.nome', read_only=True)

    class Meta:
        from financeiro.models import RegraConciliacao
        model = RegraConciliacao
        fields = [
            'id',
            'tenant',
            'padrao_descricao',
            'tipo_regra',
            'conta_contabil',
            'conta_contabil_nome',
            'centro_custo',
            'centro_custo_nome',
            'ativo',
            'criado_em',
        ]
        read_only_fields = ['id', 'tenant', 'conta_contabil_nome', 'centro_custo_nome', 'criado_em']


class ConfiguracaoCobrancaSerializer(serializers.ModelSerializer):
    conta_financeira_nome = serializers.CharField(source='conta_financeira.nome', read_only=True)

    class Meta:
        from financeiro.models import ConfiguracaoCobranca
        model = ConfiguracaoCobranca
        fields = [
            'id',
            'tenant',
            'conta_financeira',
            'conta_financeira_nome',
            'adaptador',
            'carteira',
            'instrucoes_boleto',
            'percentual_multa',
            'percentual_juros_mensal',
            'dias_protesto',
            'api_key',
            'webhook_secret',
            'ativo',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'tenant', 'conta_financeira_nome', 'criado_em', 'atualizado_em']


class ReguaCobrancaSerializer(serializers.ModelSerializer):
    class Meta:
        from financeiro.models import ReguaCobranca
        model = ReguaCobranca
        fields = [
            'id',
            'tenant',
            'nome',
            'dias_offset',
            'canal',
            'template_assunto',
            'template_corpo',
            'template_externo_id',
            'ativo',
            'criado_em',
        ]
        read_only_fields = ['id', 'tenant', 'criado_em']


class EnvioCobrancaSerializer(serializers.ModelSerializer):
    regua_nome = serializers.CharField(source='regua.nome', read_only=True)

    class Meta:
        from financeiro.models import EnvioCobranca
        model = EnvioCobranca
        fields = [
            'id',
            'tenant',
            'parcela',
            'regua',
            'regua_nome',
            'data_envio',
            'canal',
            'destinatario',
            'status',
            'idempotency_key',
            'detalhes',
        ]
        read_only_fields = ['id', 'tenant', 'regua_nome', 'data_envio']


class ConsentimentoContatoSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)

    class Meta:
        from financeiro.models import ConsentimentoContato
        model = ConsentimentoContato
        fields = [
            'id',
            'tenant',
            'cliente',
            'cliente_nome',
            'canal',
            'consentiu_em',
            'origem',
            'revogado_em',
        ]
        read_only_fields = ['id', 'tenant', 'cliente_nome']


# ==============================================================================
# SPRINT 10B: DEPRECIAÇÃO, DRE, ORÇAMENTO, PDD, SNAPSHOTS E LANÇAMENTOS MANUAIS
# ==============================================================================

class DepreciacaoMensalSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepreciacaoMensal
        fields = [
            'id',
            'tenant',
            'periodo',
            'tipo_alvo',
            'alvo_id',
            'quota',
            'depreciacao_acumulada_apos',
            'valor_contabil_apos',
            'lancamento',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'tenant',
            'depreciacao_acumulada_apos',
            'valor_contabil_apos',
            'lancamento',
            'criado_em',
        ]


class CalcularDepreciacaoMensalInputSerializer(serializers.Serializer):
    periodo = serializers.DateField(required=True)


class RevisaoVidaUtilSerializer(serializers.ModelSerializer):
    usuario_nome = serializers.CharField(source='usuario.username', read_only=True)

    class Meta:
        model = RevisaoVidaUtil
        fields = [
            'id',
            'tenant',
            'tipo_alvo',
            'alvo_id',
            'data_revisao',
            'nova_vida_meses',
            'novo_valor_residual',
            'motivo',
            'usuario',
            'usuario_nome',
            'criado_em',
        ]
        read_only_fields = ['id', 'tenant', 'usuario', 'usuario_nome', 'criado_em']


class BaixarPatrimonioInputSerializer(serializers.Serializer):
    tipo_alvo = serializers.ChoiceField(choices=['LOTE_CILINDROS', 'CILINDRO_AVULSO', 'ATIVO_IMOBILIZADO'])
    alvo_id = serializers.CharField(max_length=100)
    data_baixa = serializers.DateField(required=True)
    motivo = serializers.CharField(max_length=255)
    valor_recebido = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0.00'))
    conta_caixa_id = serializers.IntegerField(required=False, allow_null=True)


class CapitalizarRetesteInputSerializer(serializers.Serializer):
    reteste_id = serializers.IntegerField(required=True)
    descricao = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


class SaldoMensalContaSerializer(serializers.ModelSerializer):
    conta_codigo = serializers.CharField(source='conta.codigo_estrutural', read_only=True)
    conta_nome = serializers.CharField(source='conta.nome', read_only=True)

    class Meta:
        model = SaldoMensalConta
        fields = [
            'id',
            'tenant',
            'ano_mes',
            'conta',
            'conta_codigo',
            'conta_nome',
            'centro_custo',
            'veiculo',
            'filial',
            'produto_gas',
            'debitos',
            'creditos',
            'saldo_final',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'tenant', 'conta_codigo', 'conta_nome', 'criado_em', 'atualizado_em']


class ReconstruirSaldosInputSerializer(serializers.Serializer):
    periodo = serializers.CharField(max_length=7, required=True)  # Formato AAAA-MM


class ParametroTributarioLucroSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParametroTributarioLucro
        fields = [
            'id',
            'tenant',
            'regime',
            'aliquota_irpj',
            'aliquota_adicional_irpj',
            'teto_isencao_adicional_mensal',
            'aliquota_csll',
            'presuncao_irpj',
            'presuncao_csll',
            'conta_despesa_irpj',
            'conta_despesa_csll',
            'conta_passivo_irpj',
            'conta_passivo_csll',
            'ativo',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'tenant', 'criado_em', 'atualizado_em']


class OrcamentoMensalContaSerializer(serializers.ModelSerializer):
    conta_codigo = serializers.CharField(source='conta.codigo_estrutural', read_only=True)
    conta_nome = serializers.CharField(source='conta.nome', read_only=True)

    class Meta:
        model = OrcamentoMensalConta
        fields = [
            'id',
            'tenant',
            'orcamento',
            'mes',
            'conta',
            'conta_codigo',
            'conta_nome',
            'centro_custo',
            'filial',
            'valor',
        ]
        read_only_fields = ['id', 'tenant', 'conta_codigo', 'conta_nome']


class OrcamentoSerializer(serializers.ModelSerializer):
    itens = OrcamentoMensalContaSerializer(many=True, read_only=True)
    criado_por_nome = serializers.CharField(source='criado_por.username', read_only=True)
    aprovado_por_nome = serializers.CharField(source='aprovado_por.username', read_only=True)

    class Meta:
        model = Orcamento
        fields = [
            'id',
            'tenant',
            'ano',
            'nome',
            'status',
            'criado_por',
            'criado_por_nome',
            'aprovado_por',
            'aprovado_por_nome',
            'criado_em',
            'atualizado_em',
            'itens',
        ]
        read_only_fields = ['id', 'tenant', 'status', 'criado_por', 'criado_por_nome', 'aprovado_por', 'aprovado_por_nome', 'criado_em', 'atualizado_em']


class ImportarOrcamentoCSVSerializer(serializers.Serializer):
    orcamento_id = serializers.IntegerField(required=True)
    arquivo = serializers.FileField(required=True)


class ParametroPDDSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParametroPDD
        fields = [
            'id',
            'tenant',
            'dias_atraso_min',
            'dias_atraso_max',
            'percentual_provisao',
            'ativo',
            'criado_em',
        ]
        read_only_fields = ['id', 'tenant', 'criado_em']


class CalcularPDDInputSerializer(serializers.Serializer):
    periodo = serializers.DateField(required=True)


class BaixarPerdaPDDInputSerializer(serializers.Serializer):
    parcela_id = serializers.IntegerField(required=True)
    motivo = serializers.CharField(min_length=5, required=True)


class LancamentoManualPendenteSerializer(serializers.ModelSerializer):
    criado_por_nome = serializers.CharField(source='criado_por.username', read_only=True)
    aprovado_por_nome = serializers.CharField(source='aprovado_por.username', read_only=True)

    class Meta:
        model = LancamentoManualPendente
        fields = [
            'id',
            'tenant',
            'data_competencia',
            'historico',
            'partidas_json',
            'valor_total',
            'status',
            'criado_por',
            'criado_por_nome',
            'aprovado_por',
            'aprovado_por_nome',
            'aprovado_em',
            'lancamento',
            'motivo_rejeicao',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'tenant',
            'valor_total',
            'status',
            'criado_por',
            'criado_por_nome',
            'aprovado_por',
            'aprovado_por_nome',
            'aprovado_em',
            'lancamento',
            'motivo_rejeicao',
            'criado_em',
        ]


class CriarLancamentoManualInputSerializer(serializers.Serializer):
    data_competencia = serializers.DateField(required=True)
    historico = serializers.CharField(min_length=3, max_length=255, required=True)
    partidas = PartidaInputSerializer(many=True, min_length=2, required=True)


class AprovarRejeitarLancamentoManualInputSerializer(serializers.Serializer):
    decisao = serializers.ChoiceField(choices=['APROVAR', 'REJEITAR'], required=True)
    motivo = serializers.CharField(required=False, allow_blank=True, default='')


class ImportarProvisoesCSVSerializer(serializers.Serializer):
    arquivo = serializers.FileField(required=True)
    data_competencia = serializers.DateField(required=True)
    historico_padrao = serializers.CharField(max_length=255, required=False, default='Importação de Provisões Folha/Tributos')


class DREConsultaInputSerializer(serializers.Serializer):
    periodo_ini = serializers.CharField(max_length=7, required=True)  # ex: 2026-01
    periodo_fim = serializers.CharField(max_length=7, required=True)  # ex: 2026-12
    filial_id = serializers.IntegerField(required=False, allow_null=True)
    centro_custo_id = serializers.IntegerField(required=False, allow_null=True)
    produto_gas_id = serializers.IntegerField(required=False, allow_null=True)
    comparar_com = serializers.ChoiceField(choices=['PERIODO_ANTERIOR', 'ORCAMENTO'], required=False, allow_null=True, default=None)
    orcamento_id = serializers.IntegerField(required=False, allow_null=True)


# ==============================================================================
# SPRINT 10C: FLUXO DE CAIXA, CENÁRIOS E GESTÃO DO DONO
# ==============================================================================

class PerfilPagamentoClienteSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    cliente_cnpj = serializers.CharField(source='cliente.cnpj', default='', read_only=True)

    class Meta:
        model = PerfilPagamentoCliente
        fields = [
            'id',
            'cliente',
            'cliente_nome',
            'cliente_cnpj',
            'atraso_medio_dias',
            'p80_atraso_dias',
            'taxa_inadimplencia',
            'amostra_n',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'atualizado_em']


class RecorrenciaFinanceiraSerializer(serializers.ModelSerializer):
    conta_nome = serializers.CharField(source='conta.nome', default='', read_only=True)
    centro_custo_nome = serializers.CharField(source='centro_custo.nome', default='', read_only=True)

    class Meta:
        model = RecorrenciaFinanceira
        fields = [
            'id',
            'descricao',
            'tipo',
            'valor',
            'dia_do_mes',
            'conta',
            'conta_nome',
            'centro_custo',
            'centro_custo_nome',
            'inicio',
            'fim',
            'ativo',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'criado_em', 'atualizado_em']


class AlertaCaixaSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertaCaixa
        fields = [
            'id',
            'data_alerta',
            'horizonte_dias',
            'saldo_minimo_configurado',
            'menor_saldo_projetado',
            'data_menor_saldo',
            'resolvido',
            'detalhes_json',
            'criado_em',
        ]
        read_only_fields = ['id', 'criado_em']


class ParametroGestaoTenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParametroGestaoTenant
        fields = [
            'id',
            'saldo_minimo_caixa',
            'tma_mensal',
            'politica_receita_veiculo',
            'fator_majoracao_pessimista',
            'horizonte_alerta_dias',
        ]
        read_only_fields = ['id']


class FluxoCaixaConsultaInputSerializer(serializers.Serializer):
    data_inicio = serializers.DateField(required=False)
    data_fim = serializers.DateField(required=False)
    conta_id = serializers.IntegerField(required=False, allow_null=True)


class ProjecaoCaixaInputSerializer(serializers.Serializer):
    dias = serializers.IntegerField(required=False, default=90, min_value=1, max_value=365)
    fator_majoracao = serializers.DecimalField(required=False, max_digits=6, decimal_places=4, default=None, allow_null=True)


# ==============================================================================
# SPRINT 11C: CRÉDITO, LIMITES E PROMESSA DE PAGAMENTO
# ==============================================================================

class ParametroCreditoSerializer(serializers.ModelSerializer):
    class Meta:
        from financeiro.models import ParametroCredito
        model = ParametroCredito
        fields = [
            'id',
            'dias_tolerancia',
            'valor_minimo_considerado',
            'limite_credito_padrao',
            'max_dias_promessa',
            'max_promessas_ativas',
            'politica_gas_medicinal',
        ]
        read_only_fields = ['id']


class LimiteCreditoClienteSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.ReadOnlyField(source='cliente.nome')

    class Meta:
        from financeiro.models import LimiteCreditoCliente
        model = LimiteCreditoCliente
        fields = [
            'id',
            'cliente',
            'cliente_nome',
            'limite',
            'vigencia_inicio',
            'vigencia_fim',
            'observacao',
            'ativo',
        ]
        read_only_fields = ['id', 'cliente_nome']


class PromessaPagamentoSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.ReadOnlyField(source='cliente.nome')
    criado_por_nome = serializers.ReadOnlyField(source='criado_por.username')

    class Meta:
        from financeiro.models import PromessaPagamento
        model = PromessaPagamento
        fields = [
            'id',
            'cliente',
            'cliente_nome',
            'parcelas',
            'data_promessa',
            'valor',
            'status',
            'criado_por',
            'criado_por_nome',
            'observacao',
            'criado_em',
            'atualizado_em',
        ]
        read_only_fields = ['id', 'cliente_nome', 'criado_por', 'criado_por_nome', 'criado_em', 'atualizado_em']






