from rest_framework import serializers
from fiscal.models import (
    ConfiguracaoFiscalFilial,
    RegraTributaria,
    RegraTributariaTributo,
    DocumentoFiscal,
    DocumentoFiscalItem,
    ItemDocumentoTributo,
    DocumentoFiscalEvento,
    TarefaInutilizacaoNumeracao,
)


class ConfiguracaoFiscalFilialSerializer(serializers.ModelSerializer):
    filial_nome = serializers.CharField(source='filial.nome', read_only=True)
    certificado_expira_em_breve = serializers.SerializerMethodField()
    credenciais_gateway = serializers.DictField(write_only=True, required=False)
    tem_credenciais = serializers.SerializerMethodField()

    class Meta:
        model = ConfiguracaoFiscalFilial
        fields = [
            'id', 'filial', 'filial_nome', 'regime_tributario', 'crt', 'ambiente',
            'serie_nfe', 'proximo_numero_nfe', 'serie_mdfe', 'proximo_numero_mdfe',
            'serie_cte', 'proximo_numero_cte', 'inscricao_municipal', 'cnae',
            'certificado_valido_ate', 'certificado_expira_em_breve', 'prazo_cancelamento_horas',
            'tem_credenciais', 'credenciais_gateway', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['id', 'criado_em', 'atualizado_em']

    def get_certificado_expira_em_breve(self, obj) -> bool:
        return obj.certificado_expira_em_breve(30)

    def get_tem_credenciais(self, obj) -> bool:
        return bool(obj.credenciais_gateway_cifradas)

    def create(self, validated_data):
        creds = validated_data.pop('credenciais_gateway', None)
        instance = super().create(validated_data)
        if creds:
            instance.set_credenciais(creds)
            instance.save()
        return instance

    def update(self, instance, validated_data):
        creds = validated_data.pop('credenciais_gateway', None)
        instance = super().update(instance, validated_data)
        if creds is not None:
            instance.set_credenciais(creds)
            instance.save()
        return instance


class RegraTributariaTributoSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegraTributariaTributo
        fields = [
            'id', 'tributo', 'cst_csosn', 'reducao_base_pct',
            'aliquota', 'modo_calculo', 'codigo_beneficio'
        ]
        read_only_fields = ['id']


class RegraTributariaSerializer(serializers.ModelSerializer):
    tributos = RegraTributariaTributoSerializer(many=True, required=False)
    aprovada_por_nome = serializers.CharField(source='aprovada_por.get_full_name', read_only=True)
    is_aprovada = serializers.BooleanField(read_only=True)

    class Meta:
        model = RegraTributaria
        fields = [
            'id', 'descricao', 'vigencia_inicio', 'vigencia_fim',
            'uf_origem', 'uf_destino', 'tipo_operacao', 'ncm', 'cfop',
            'aprovada_por', 'aprovada_por_nome', 'aprovada_em', 'is_aprovada',
            'tributos', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['id', 'aprovada_por', 'aprovada_em', 'criado_em', 'atualizado_em']

    def create(self, validated_data):
        tributos_data = validated_data.pop('tributos', [])
        regra = RegraTributaria.objects.create(**validated_data)
        for t_data in tributos_data:
            RegraTributariaTributo.objects.create(
                tenant=regra.tenant,
                regra=regra,
                **t_data
            )
        return regra


class ItemDocumentoTributoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemDocumentoTributo
        fields = ['id', 'tributo', 'cst', 'base', 'aliquota', 'valor']


class DocumentoFiscalItemSerializer(serializers.ModelSerializer):
    tributos = ItemDocumentoTributoSerializer(many=True, read_only=True)

    class Meta:
        model = DocumentoFiscalItem
        fields = [
            'id', 'numero_item', 'produto_id', 'descricao', 'ncm', 'cest',
            'cfop', 'unidade', 'quantidade', 'valor_unitario', 'valor_total', 'tributos'
        ]


class DocumentoFiscalEventoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoFiscalEvento
        fields = [
            'id', 'tipo_evento', 'sequencial', 'protocolo',
            'justificativa', 'data_evento', 'status'
        ]


class DocumentoFiscalSerializer(serializers.ModelSerializer):
    filial_nome = serializers.CharField(source='filial.nome', read_only=True)
    itens = DocumentoFiscalItemSerializer(many=True, read_only=True)
    eventos = DocumentoFiscalEventoSerializer(many=True, read_only=True)

    class Meta:
        model = DocumentoFiscal
        fields = [
            'id', 'filial', 'filial_nome', 'modelo', 'tipo_operacao', 'status',
            'ambiente', 'numero', 'serie', 'chave_acesso', 'protocolo',
            'danfe_url', 'valor_total', 'origem_tipo', 'origem_id',
            'motivo_rejeicao', 'acao_sugerida', 'tentativas', 'idempotency_key',
            'data_autorizacao', 'itens', 'eventos', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = fields


class TarefaInutilizacaoNumeracaoSerializer(serializers.ModelSerializer):
    filial_nome = serializers.CharField(source='filial.nome', read_only=True)

    class Meta:
        model = TarefaInutilizacaoNumeracao
        fields = [
            'id', 'filial', 'filial_nome', 'modelo', 'serie',
            'numero_inicial', 'numero_final', 'motivo', 'protocolo',
            'status', 'tentativas', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['id', 'protocolo', 'status', 'tentativas', 'criado_em', 'atualizado_em']


# ==============================================================================
# SERIALIZERS SPRINT 11B
# ==============================================================================

class MovimentoComodatoFiscalSerializer(serializers.ModelSerializer):
    cilindro_numero_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    filial_nome = serializers.CharField(source='filial.nome', read_only=True)

    class Meta:
        from fiscal.models import MovimentoComodatoFiscal
        model = MovimentoComodatoFiscal
        fields = [
            'id', 'cilindro', 'cilindro_numero_serie', 'cliente', 'cliente_nome',
            'filial', 'filial_nome', 'documento_fiscal', 'tipo', 'data_movimento',
            'valor_bem', 'chave_nfe', 'observacao', 'criado_em'
        ]
        read_only_fields = ['id', 'criado_em']


class ConfiguracaoMDFeSerializer(serializers.ModelSerializer):
    filial_nome = serializers.CharField(source='filial.nome', read_only=True)

    class Meta:
        from fiscal.models import ConfiguracaoMDFe
        model = ConfiguracaoMDFe
        fields = [
            'id', 'filial', 'filial_nome', 'uf', 'exigir_sempre_interestadual',
            'exigir_intermunicipal', 'prazo_alerta_horas', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['id', 'criado_em', 'atualizado_em']


class DocumentoFiscalEntradaSerializer(serializers.ModelSerializer):
    filial_nome = serializers.CharField(source='filial.nome', read_only=True)

    class Meta:
        from fiscal.models import DocumentoFiscalEntrada
        model = DocumentoFiscalEntrada
        fields = [
            'id', 'filial', 'filial_nome', 'chave_acesso', 'numero', 'serie',
            'data_emissao', 'fornecedor_nome', 'fornecedor_cnpj', 'valor_total',
            'valor_produtos', 'valor_frete', 'credito_icms', 'credito_pis',
            'credito_cofins', 'credito_ipi', 'tipo_entrada', 'status',
            'titulo_pagar', 'criado_em'
        ]
        read_only_fields = ['id', 'criado_em']


class ApuracaoImpostoSerializer(serializers.ModelSerializer):
    filial_nome = serializers.CharField(source='filial.nome', read_only=True)

    class Meta:
        from fiscal.models import ApuracaoImposto
        model = ApuracaoImposto
        fields = [
            'id', 'filial', 'filial_nome', 'periodo', 'tributo', 'debitos',
            'creditos', 'saldo_credor_anterior', 'saldo_apurado', 'status',
            'titulo_pagar', 'fechado_em', 'criado_em'
        ]
        read_only_fields = ['id', 'saldo_apurado', 'criado_em']


class ItemOrdemRecargaTerceiroSerializer(serializers.ModelSerializer):
    gas_sigla = serializers.CharField(source='gas.sigla', read_only=True)

    class Meta:
        from fiscal.models import ItemOrdemRecargaTerceiro
        model = ItemOrdemRecargaTerceiro
        fields = [
            'id', 'numero_serie_cilindro', 'gas', 'gas_sigla',
            'volume_m3', 'lote_envase', 'valor_servico'
        ]
        read_only_fields = ['id']


class OrdemRecargaTerceiroSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    filial_nome = serializers.CharField(source='filial.nome', read_only=True)
    itens = ItemOrdemRecargaTerceiroSerializer(many=True, read_only=True)

    class Meta:
        from fiscal.models import OrdemRecargaTerceiro
        model = OrdemRecargaTerceiro
        fields = [
            'id', 'cliente', 'cliente_nome', 'filial', 'filial_nome',
            'numero_ordem', 'documento_entrada', 'documento_saida', 'status',
            'tipo_faturamento', 'custo_servico', 'observacoes', 'itens',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['id', 'criado_em', 'atualizado_em']

