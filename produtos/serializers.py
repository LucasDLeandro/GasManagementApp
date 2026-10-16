from rest_framework import serializers
from .models import (
    Produto,
    Cilindro,
    EnvaseCilindro,
    LoteEnvase,
    GasQuimico,
    ModeloCilindro,
    InspecaoPreEnvase,
    RecebimentoCilindroCheio,
    ReclassificacaoCilindro,
    AuditoriaBloqueioSanitario,
    RecallCampanha,
    ItemRecallCliente,
    MovimentacaoCilindro,
)


class ProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Produto
        fields = '__all__'


class GasQuimicoSerializer(serializers.ModelSerializer):
    class Meta:
        model = GasQuimico
        fields = '__all__'


class ModeloCilindroSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModeloCilindro
        fields = '__all__'


class LoteEnvaseSerializer(serializers.ModelSerializer):
    gas_sigla = serializers.CharField(source='gas.sigla', read_only=True)
    gas_nome = serializers.CharField(source='gas.nome', read_only=True)
    esta_vencido = serializers.BooleanField(read_only=True)
    status_qualidade_display = serializers.CharField(source='get_status_qualidade_display', read_only=True)

    class Meta:
        model = LoteEnvase
        fields = [
            'id', 'tenant', 'gas', 'gas_sigla', 'gas_nome', 'codigo_lote',
            'status_qualidade', 'status_qualidade_display',
            'data_envase', 'data_validade', 'pureza_percentual',
            'responsavel_tecnico', 'responsavel_tecnico_fk',
            'rt_nome_snapshot', 'rt_conselho_snapshot', 'rt_registro_snapshot',
            'laudo_pdf', 'esta_vencido', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']


class MovimentacaoCilindroSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True, default=None)
    registrado_por_nome = serializers.SerializerMethodField()
    estornada = serializers.SerializerMethodField()
    estorna_movimentacao_id = serializers.PrimaryKeyRelatedField(source='estorna_movimentacao', read_only=True)

    class Meta:
        model = MovimentacaoCilindro
        fields = [
            'id', 'tenant', 'cilindro', 'tipo', 'tipo_display',
            'status_anterior', 'status_novo', 'cliente', 'cliente_nome',
            'entrega', 'ocorrido_em', 'registrado_em', 'registrado_por',
            'registrado_por_nome', 'client_uuid', 'estorna_movimentacao',
            'estorna_movimentacao_id', 'estornada', 'observacao',
            'lote_envase', 'documento_fiscal_ref'
        ]

    def get_registrado_por_nome(self, obj):
        if obj.registrado_por:
            return obj.registrado_por.get_full_name() or obj.registrado_por.username
        return 'Sistema'

    def get_estornada(self, obj):
        return hasattr(obj, 'estornada_por') and obj.estornada_por is not None


class CilindroSerializer(serializers.ModelSerializer):
    gas_sigla = serializers.CharField(source='gas_dedicado.sigla', read_only=True)
    gas_nome = serializers.CharField(source='gas_dedicado.nome', read_only=True)
    gas_cor_padrao_abnt = serializers.CharField(source='gas_dedicado.cor_padrao_abnt', read_only=True)
    gas_categoria = serializers.CharField(source='gas_dedicado.categoria', read_only=True)
    modelo_descricao = serializers.CharField(source='modelo.descricao', read_only=True)
    volume_litros = serializers.DecimalField(source='modelo.volume_hidraulico_litros', max_digits=6, decimal_places=2, read_only=True)
    pressao_servico_bar = serializers.IntegerField(source='modelo.pressao_servico_bar', read_only=True)
    cliente_posse_nome = serializers.CharField(source='cliente_posse_atual.nome', read_only=True, default=None)
    reteste_vencido = serializers.BooleanField(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    propriedade_display = serializers.CharField(source='get_propriedade_display', read_only=True)
    lote_atual_codigo = serializers.SerializerMethodField()

    class Meta:
        model = Cilindro
        fields = [
            'id', 'tenant', 'codigo_qr', 'numero_serie_ogiva', 'fabricante', 'ano_fabricacao',
            'modelo', 'modelo_descricao', 'volume_litros', 'pressao_servico_bar',
            'gas_dedicado', 'gas_sigla', 'gas_nome', 'gas_cor_padrao_abnt', 'gas_categoria',
            'tara_real_kg', 'propriedade', 'propriedade_display', 'cliente_proprietario',
            'data_ultimo_reteste', 'data_proximo_reteste',
            'status', 'status_display', 'cliente_posse_atual', 'cliente_posse_nome',
            'posse_desde', 'envase_atual', 'recebimento_externo_atual', 'lote_atual_codigo',
            'bloqueio_sanitario', 'motivo_bloqueio_sanitario', 'reteste_vencido'
        ]
        read_only_fields = ['tenant', 'status', 'cliente_posse_atual', 'posse_desde', 'envase_atual', 'recebimento_externo_atual']

    def get_lote_atual_codigo(self, obj):
        if obj.envase_atual and obj.envase_atual.lote:
            return obj.envase_atual.lote.codigo_lote
        elif obj.recebimento_externo_atual:
            return obj.recebimento_externo_atual.lote_fornecedor
        return None


class EnvaseCilindroSerializer(serializers.ModelSerializer):
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    cilindro_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    lote_codigo = serializers.CharField(source='lote.codigo_lote', read_only=True)
    operador_nome = serializers.CharField(source='operador.get_full_name', read_only=True)

    class Meta:
        model = EnvaseCilindro
        fields = [
            'id', 'tenant', 'cilindro', 'cilindro_qr', 'cilindro_serie',
            'lote', 'lote_codigo', 'pressao_final_bar', 'envasado_em',
            'operador', 'operador_nome', 'observacoes'
        ]
        read_only_fields = ['tenant']


class InspecaoPreEnvaseSerializer(serializers.ModelSerializer):
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    operador_nome = serializers.CharField(source='operador.get_full_name', read_only=True)

    class Meta:
        model = InspecaoPreEnvase
        fields = [
            'id', 'tenant', 'cilindro', 'cilindro_qr', 'operador', 'operador_nome',
            'valvula_integra', 'pressao_residual_positiva', 'pintura_cor_padrao_ok',
            'rotulo_identificacao_ok', 'aprovado', 'observacoes', 'realizado_em'
        ]
        read_only_fields = ['tenant', 'aprovado', 'realizado_em']


class RecebimentoCilindroCheioSerializer(serializers.ModelSerializer):
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    responsavel_nome = serializers.CharField(source='responsavel_recebimento.get_full_name', read_only=True)

    class Meta:
        model = RecebimentoCilindroCheio
        fields = [
            'id', 'tenant', 'cilindro', 'cilindro_qr', 'fornecedor_nome', 'fornecedor_cnpj',
            'nota_fiscal', 'lote_fornecedor', 'data_envase_origem', 'data_validade',
            'pressao_recebimento_bar', 'laudo_pdf', 'responsavel_tecnico',
            'rt_nome_snapshot', 'rt_registro_snapshot',
            'responsavel_recebimento', 'responsavel_nome', 'recebido_em', 'observacoes'
        ]
        read_only_fields = ['tenant', 'recebido_em']


class ReclassificacaoCilindroSerializer(serializers.ModelSerializer):
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    gas_origem_sigla = serializers.CharField(source='gas_origem.sigla', read_only=True)
    gas_destino_sigla = serializers.CharField(source='gas_destino.sigla', read_only=True)
    executado_por_nome = serializers.CharField(source='executado_por.get_full_name', read_only=True)
    adequacao_pintura_executada = serializers.BooleanField(source='pintura_adequada_abnt', read_only=True)

    class Meta:
        model = ReclassificacaoCilindro
        fields = [
            'id', 'tenant', 'cilindro', 'cilindro_qr', 'gas_origem', 'gas_origem_sigla',
            'gas_destino', 'gas_destino_sigla', 'descontaminacao_purga_executada',
            'troca_valvula_executada', 'pintura_adequada_abnt', 'adequacao_pintura_executada',
            'homologado_por_rt', 'rt_nome_snapshot', 'rt_registro_snapshot',
            'executado_por', 'executado_por_nome', 'observacoes', 'realizado_em'
        ]
        read_only_fields = ['tenant', 'realizado_em']


class AuditoriaBloqueioSanitarioSerializer(serializers.ModelSerializer):
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    cilindro_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    responsavel_nome = serializers.CharField(source='responsavel.get_full_name', read_only=True)

    class Meta:
        model = AuditoriaBloqueioSanitario
        fields = [
            'id', 'tenant', 'cilindro', 'cilindro_qr', 'cilindro_serie',
            'acao', 'motivo', 'responsavel', 'responsavel_nome',
            'responsavel_tecnico', 'rt_nome_snapshot', 'rt_registro_snapshot',
            'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']


class ItemRecallClienteSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source='cliente.nome', read_only=True)
    cliente_cnpj = serializers.CharField(source='cliente.cnpj', read_only=True)
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    cilindro_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    status_notificacao_display = serializers.CharField(source='get_status_notificacao_display', read_only=True)
    tipo_exposicao_display = serializers.CharField(source='get_tipo_exposicao_display', read_only=True)

    class Meta:
        model = ItemRecallCliente
        fields = [
            'id', 'campanha', 'cliente', 'cliente_nome', 'cliente_cnpj',
            'cilindro', 'cilindro_qr', 'cilindro_serie', 'envase_cilindro',
            'tipo_exposicao', 'tipo_exposicao_display',
            'status_notificacao', 'status_notificacao_display',
            'notificado_em', 'recolhido_em', 'observacoes'
        ]
        read_only_fields = ['tenant']


class RecallCampanhaSerializer(serializers.ModelSerializer):
    lote_codigo = serializers.CharField(source='lote.codigo_lote', read_only=True)
    criado_por_nome = serializers.CharField(source='criado_por.get_full_name', read_only=True)
    itens_cliente = ItemRecallClienteSerializer(many=True, read_only=True)

    class Meta:
        model = RecallCampanha
        fields = [
            'id', 'tenant', 'lote', 'lote_codigo', 'codigo_campanha',
            'status', 'motivo', 'texto_notificacao', 'criado_por',
            'criado_por_nome', 'homologado_por_rt', 'rt_nome_snapshot',
            'rt_registro_snapshot', 'aberto_em', 'homologado_em',
            'concluido_em', 'itens_cliente'
        ]
        read_only_fields = ['tenant', 'aberto_em']

