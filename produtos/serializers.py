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
    FabricanteCilindro,
    ClasseAtivo,
    LoteAquisicaoCilindros,
    AtivoImobilizado,
    TabelaIndenizacaoCilindro,
    HistoricoRetesteHidrostatico,
    EnvioReteste,
    ItemEnvioReteste,
    BaixaPatrimonial,
    TanqueCriogenico,
    MedicaoTanque,
    EntradaGasGranel,
    MovimentoEstoqueGas,
    FechamentoPeriodoTanque,
    CustoEnergiaRampa,
    CustoLoteEnvase,
    MovimentoEstoqueProduto,
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
    fabricante_catalogo_nome = serializers.CharField(source='fabricante_catalogo.nome', read_only=True, default=None)
    classe_ativo_nome = serializers.CharField(source='classe_ativo.nome', read_only=True, default=None)
    is_proprio = serializers.BooleanField(read_only=True)
    depreciacao_mensal_rs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    depreciacao_diaria_rs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    valor_contabil_liquido_atual = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Cilindro
        fields = [
            'id', 'tenant', 'codigo_qr', 'numero_serie_ogiva', 'fabricante', 'fabricante_catalogo',
            'fabricante_catalogo_nome', 'ano_fabricacao', 'norma_fabricacao', 'pressao_servico_bar',
            'pressao_teste_bar', 'tipo_valvula_rosca',
            'modelo', 'modelo_descricao', 'volume_litros',
            'gas_dedicado', 'gas_sigla', 'gas_nome', 'gas_cor_padrao_abnt', 'gas_categoria',
            'tara_real_kg', 'propriedade', 'propriedade_display', 'cliente_proprietario', 'is_proprio',
            'numero_patrimonio', 'data_aquisicao', 'data_inicio_depreciacao', 'valor_aquisicao',
            'valor_residual', 'vida_util_meses', 'chave_nfe_aquisicao', 'fornecedor_aquisicao',
            'lote_aquisicao', 'classe_ativo', 'classe_ativo_nome',
            'depreciacao_mensal_rs', 'depreciacao_diaria_rs', 'valor_contabil_liquido_atual',
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
            'laudo_descontaminacao', 'exigiu_novo_reteste', 'reteste_vinculado',
            'validade_estanqueidade',
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


# ==============================================================================
# SERIALIZERS DE PATRIMÔNIO E ATIVOS IMOBILIZADOS (SPRINT 8A)
# ==============================================================================

class FabricanteCilindroSerializer(serializers.ModelSerializer):
    class Meta:
        model = FabricanteCilindro
        fields = [
            'id', 'tenant', 'nome', 'pais_origem', 'norma_fabricacao_padrao',
            'ativo', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']


class ClasseAtivoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    metodo_depreciacao_display = serializers.CharField(source='get_metodo_depreciacao_display', read_only=True)

    class Meta:
        model = ClasseAtivo
        fields = [
            'id', 'tenant', 'codigo', 'nome', 'tipo', 'tipo_display',
            'vida_util_meses_padrao', 'percentual_residual_padrao',
            'metodo_depreciacao', 'metodo_depreciacao_display',
            'codigo_conta_imobilizado', 'codigo_conta_depreciacao_acumulada',
            'codigo_conta_despesa_depreciacao', 'ativo',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']


class AtivoImobilizadoSerializer(serializers.ModelSerializer):
    classe_codigo = serializers.CharField(source='classe.codigo', read_only=True)
    classe_nome = serializers.CharField(source='classe.nome', read_only=True)
    filial_nome = serializers.CharField(source='filial.nome', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    depreciacao_mensal_rs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    depreciacao_diaria_rs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    valor_contabil_liquido_atual = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = AtivoImobilizado
        fields = [
            'id', 'tenant', 'filial', 'filial_nome', 'classe', 'classe_codigo', 'classe_nome',
            'numero_patrimonio', 'descricao', 'data_aquisicao', 'data_inicio_depreciacao',
            'valor_aquisicao', 'valor_residual', 'vida_util_meses',
            'fornecedor_nome', 'fornecedor_documento', 'chave_nfe_aquisicao',
            'status', 'status_display',
            'depreciacao_mensal_rs', 'depreciacao_diaria_rs', 'valor_contabil_liquido_atual',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']


class LoteAquisicaoCilindrosSerializer(serializers.ModelSerializer):
    classe_codigo = serializers.CharField(source='classe.codigo', read_only=True)
    classe_nome = serializers.CharField(source='classe.nome', read_only=True)

    class Meta:
        model = LoteAquisicaoCilindros
        fields = [
            'id', 'tenant', 'classe', 'classe_codigo', 'classe_nome',
            'fornecedor_nome', 'fornecedor_documento', 'chave_nfe',
            'data_aquisicao', 'quantidade', 'valor_total', 'valor_unitario',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']


class TabelaIndenizacaoCilindroSerializer(serializers.ModelSerializer):
    tipo_cilindro_descricao = serializers.CharField(source='tipo_cilindro.descricao', read_only=True)
    gas_sigla = serializers.CharField(source='gas.sigla', read_only=True, default=None)
    gas_nome = serializers.CharField(source='gas.nome', read_only=True, default=None)

    class Meta:
        model = TabelaIndenizacaoCilindro
        fields = [
            'id', 'tenant', 'tipo_cilindro', 'tipo_cilindro_descricao',
            'gas', 'gas_sigla', 'gas_nome', 'valor',
            'vigencia_inicio', 'vigencia_fim', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']


# ==============================================================================
# SERIALIZERS DE RETESTE HIDROSTÁTICO, ENVIOS E BAIXA PATRIMONIAL (SPRINT 8B)
# ==============================================================================

class HistoricoRetesteHidrostaticoSerializer(serializers.ModelSerializer):
    cilindro_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    usuario_nome = serializers.CharField(source='usuario.get_full_name', read_only=True, default=None)
    resultado_display = serializers.CharField(source='get_resultado_display', read_only=True)

    class Meta:
        model = HistoricoRetesteHidrostatico
        fields = [
            'id', 'tenant', 'cilindro', 'cilindro_serie', 'cilindro_qr',
            'origem_registro', 'retifica', 'data_execucao',
            'numero_certificado', 'oficina_nome', 'oficina_cnpj', 'registro_inmetro',
            'pressao_teste_bar', 'expansao_total_cm3', 'expansao_permanente_cm3',
            'expansao_permanente_percentual', 'limite_expansao_percentual_aplicado',
            'tara_gravada_kg', 'tara_real_kg', 'variacao_tara_percentual',
            'resultado', 'resultado_display', 'motivo_reprovacao',
            'data_proximo_reteste', 'custo_servico_reteste', 'observacoes',
            'usuario', 'usuario_nome', 'criado_em'
        ]
        read_only_fields = ['tenant', 'expansao_permanente_percentual', 'variacao_tara_percentual', 'criado_em']


class ItemEnvioRetesteSerializer(serializers.ModelSerializer):
    cilindro_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)

    class Meta:
        model = ItemEnvioReteste
        fields = [
            'id', 'tenant', 'envio', 'cilindro', 'cilindro_serie', 'cilindro_qr',
            'status_anterior', 'retornado', 'reteste_vinculado', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']


class EnvioRetesteSerializer(serializers.ModelSerializer):
    itens = ItemEnvioRetesteSerializer(many=True, read_only=True)
    criado_por_nome = serializers.CharField(source='criado_por.get_full_name', read_only=True, default=None)
    total_cilindros = serializers.IntegerField(source='itens.count', read_only=True)

    class Meta:
        model = EnvioReteste
        fields = [
            'id', 'tenant', 'oficina_nome', 'oficina_cnpj', 'data_envio',
            'observacoes', 'criado_por', 'criado_por_nome', 'total_cilindros',
            'itens', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']


class BaixaPatrimonialSerializer(serializers.ModelSerializer):
    cilindro_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    usuario_nome = serializers.CharField(source='usuario.get_full_name', read_only=True, default=None)
    usuario_estorno_nome = serializers.CharField(source='usuario_estorno.get_full_name', read_only=True, default=None)

    class Meta:
        model = BaixaPatrimonial
        fields = [
            'id', 'tenant', 'cilindro', 'cilindro_serie', 'cilindro_qr',
            'tipo', 'tipo_display', 'data', 'valor_contabil_baixa',
            'valor_recebido', 'resultado', 'documento_ref',
            'motivo', 'status_anterior', 'estornada', 'data_estorno',
            'motivo_estorno', 'usuario', 'usuario_nome',
            'usuario_estorno', 'usuario_estorno_nome', 'criado_em'
        ]
        read_only_fields = ['tenant', 'valor_contabil_baixa', 'resultado', 'estornada', 'data_estorno', 'criado_em']


class TanqueCriogenicoSerializer(serializers.ModelSerializer):
    gas_sigla = serializers.CharField(source='gas.sigla', read_only=True)
    gas_nome = serializers.CharField(source='gas.nome', read_only=True)
    filial_nome = serializers.CharField(source='filial.nome', read_only=True, default=None)

    class Meta:
        model = TanqueCriogenico
        fields = [
            'id', 'tenant', 'filial', 'filial_nome', 'codigo', 'descricao',
            'gas', 'gas_sigla', 'gas_nome', 'capacidade_kg',
            'saldo_atual_kg', 'saldo_valor_atual', 'custo_medio_kg_atual',
            'pressao_operacao_bar', 'tolerancia_perda_pct', 'tolerancia_pesagem_pct',
            'ativo_imobilizado', 'ativo', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'saldo_atual_kg', 'saldo_valor_atual', 'custo_medio_kg_atual', 'criado_em', 'atualizado_em']


class MedicaoTanqueSerializer(serializers.ModelSerializer):
    tanque_codigo = serializers.CharField(source='tanque.codigo', read_only=True)
    usuario_nome = serializers.CharField(source='usuario.get_full_name', read_only=True, default=None)

    class Meta:
        model = MedicaoTanque
        fields = [
            'id', 'tenant', 'tanque', 'tanque_codigo', 'data_hora',
            'massa_kg_medida', 'pressao_bar', 'nivel_percentual',
            'origem', 'usuario', 'usuario_nome', 'observacoes', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']


class EntradaGasGranelSerializer(serializers.ModelSerializer):
    tanque_codigo = serializers.CharField(source='tanque.codigo', read_only=True)
    usuario_nome = serializers.CharField(source='usuario.get_full_name', read_only=True, default=None)

    class Meta:
        model = EntradaGasGranel
        fields = [
            'id', 'tenant', 'tanque', 'tanque_codigo', 'fornecedor_nome',
            'fornecedor_documento', 'chave_nfe', 'data_entrada',
            'quantidade_kg_nf', 'quantidade_kg_recebida',
            'custo_total_nf', 'custo_frete', 'impostos_recuperaveis',
            'custo_unitario_kg_efetivo', 'divergencia_peso_kg',
            'divergencia_peso_pct', 'alerta_divergencia',
            'observacoes', 'usuario', 'usuario_nome', 'criado_em'
        ]
        read_only_fields = [
            'tenant', 'custo_unitario_kg_efetivo', 'divergencia_peso_kg',
            'divergencia_peso_pct', 'alerta_divergencia', 'criado_em'
        ]


class MovimentoEstoqueGasSerializer(serializers.ModelSerializer):
    tanque_codigo = serializers.CharField(source='tanque.codigo', read_only=True)
    gas_sigla = serializers.CharField(source='gas.sigla', read_only=True)
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    usuario_nome = serializers.CharField(source='usuario.get_full_name', read_only=True, default=None)

    class Meta:
        model = MovimentoEstoqueGas
        fields = [
            'id', 'tenant', 'tanque', 'tanque_codigo', 'gas', 'gas_sigla',
            'tipo', 'tipo_display', 'quantidade_kg', 'custo_unitario',
            'custo_total', 'saldo_quantidade_apos', 'saldo_valor_apos',
            'custo_medio_apos', 'origem_tipo', 'origem_id', 'justificativa',
            'usuario', 'usuario_nome', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']


class FechamentoPeriodoTanqueSerializer(serializers.ModelSerializer):
    tanque_codigo = serializers.CharField(source='tanque.codigo', read_only=True)
    fechado_por_nome = serializers.CharField(source='fechado_por.get_full_name', read_only=True, default=None)

    class Meta:
        model = FechamentoPeriodoTanque
        fields = [
            'id', 'tenant', 'tanque', 'tanque_codigo', 'data_inicio', 'data_fim',
            'saldo_inicial_kg', 'total_entradas_kg', 'total_consumo_envase_kg',
            'saldo_final_calculado_kg', 'saldo_final_medido_kg',
            'perda_evaporacao_kg', 'perda_evaporacao_pct', 'custo_perda',
            'excedeu_tolerancia', 'justificativa', 'movimento_perda',
            'fechado_por', 'fechado_por_nome', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']


class CustoEnergiaRampaSerializer(serializers.ModelSerializer):
    filial_nome = serializers.CharField(source='filial.nome', read_only=True, default=None)

    class Meta:
        model = CustoEnergiaRampa
        fields = [
            'id', 'tenant', 'filial', 'filial_nome', 'mes_ano',
            'kwh_consumido', 'valor_total', 'kwh_por_kg_padrao',
            'custo_kwh_estimado', 'reconciliado', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']


class CustoLoteEnvaseSerializer(serializers.ModelSerializer):
    lote_codigo = serializers.CharField(source='lote.codigo_lote', read_only=True)
    tanque_codigo = serializers.CharField(source='tanque_origem.codigo', read_only=True)
    usuario_estorno_nome = serializers.CharField(source='usuario_estorno.get_full_name', read_only=True, default=None)

    class Meta:
        model = CustoLoteEnvase
        fields = [
            'id', 'tenant', 'lote', 'lote_codigo', 'tanque_origem', 'tanque_codigo',
            'massa_gas_kg', 'custo_gas', 'custo_perda_rateada', 'custo_energia',
            'custo_mao_de_obra', 'custo_total', 'quantidade_cilindros',
            'custo_por_cilindro', 'custo_por_kg', 'estornado', 'data_estorno',
            'motivo_estorno', 'usuario_estorno', 'usuario_estorno_nome', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']


class MovimentoEstoqueProdutoSerializer(serializers.ModelSerializer):
    sku_nome = serializers.CharField(source='sku.nome_comercial', read_only=True, default=None)
    produto_nome = serializers.CharField(source='produto.nome', read_only=True, default=None)
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)

    class Meta:
        model = MovimentoEstoqueProduto
        fields = [
            'id', 'tenant', 'filial', 'sku', 'sku_nome', 'produto', 'produto_nome',
            'tipo', 'tipo_display', 'quantidade', 'custo_unitario', 'custo_total',
            'saldo_quantidade_apos', 'saldo_valor_apos', 'custo_medio_apos',
            'origem_tipo', 'origem_id', 'justificativa', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']




