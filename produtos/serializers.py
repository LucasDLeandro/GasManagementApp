from rest_framework import serializers
from clientes.models import Cliente
from .models import (
    Produto,
    Cilindro,
    EnvaseCilindro,
    LoteEnvase,
    HistoricoQualidadeLote,
    GasQuimico,
    ModeloCilindro,
    SkuRecarga,
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
    material_display = serializers.CharField(source='get_material_display', read_only=True)

    class Meta:
        model = ModeloCilindro
        fields = '__all__'
        read_only_fields = ['tenant']


class SkuRecargaSerializer(serializers.ModelSerializer):
    gas_sigla = serializers.CharField(source='gas.sigla', read_only=True)
    gas_nome = serializers.CharField(source='gas.nome', read_only=True)
    gas_categoria = serializers.CharField(source='gas.categoria', read_only=True)
    modelo_descricao = serializers.CharField(source='modelo_cilindro.descricao', read_only=True)
    unidade_display = serializers.CharField(source='get_unidade_display', read_only=True)

    class Meta:
        model = SkuRecarga
        fields = '__all__'
        read_only_fields = ['tenant']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        for campo in ('quantidade_carga', 'massa_gas_kg', 'preco_base'):
            valor = attrs.get(campo)
            if valor is not None and valor < 0:
                raise serializers.ValidationError({campo: 'O valor não pode ser negativo.'})
        ncm = attrs.get('ncm')
        if ncm and (len(ncm) != 8 or not ncm.isdigit()):
            raise serializers.ValidationError({'ncm': 'O NCM tem 8 dígitos numéricos.'})
        gas = attrs.get('gas') or getattr(self.instance, 'gas', None)
        medicinal = attrs.get('medicinal', getattr(self.instance, 'medicinal', False))
        if medicinal and gas is not None and gas.categoria != 'MEDICINAL':
            raise serializers.ValidationError({'medicinal': 'Só gases da categoria medicinal podem ter SKU medicinal.'})
        return attrs


class CadastroCilindroSerializer(serializers.Serializer):
    """Entrada do cadastro manual de cilindro (produtos.services.cadastro_cilindro)."""
    codigo_qr = serializers.CharField(max_length=100)
    numero_serie_ogiva = serializers.CharField(max_length=100)
    modelo = serializers.PrimaryKeyRelatedField(queryset=ModeloCilindro.unscoped.none())
    gas_dedicado = serializers.PrimaryKeyRelatedField(queryset=GasQuimico.objects.all())
    fabricante_catalogo = serializers.PrimaryKeyRelatedField(queryset=FabricanteCilindro.unscoped.none(), required=False, allow_null=True)
    fabricante = serializers.CharField(max_length=100, required=False, allow_blank=True)
    ano_fabricacao = serializers.IntegerField(min_value=1950)
    norma_fabricacao = serializers.CharField(max_length=50, required=False, allow_blank=True)
    pressao_servico_bar = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    pressao_teste_bar = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    tipo_valvula_rosca = serializers.CharField(max_length=50, required=False, allow_blank=True)
    tara_real_kg = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, required=False, allow_null=True)
    data_ultimo_reteste = serializers.DateField(help_text='Para cilindro novo, a data do teste de fábrica.')
    propriedade = serializers.ChoiceField(choices=Cilindro.PROPRIEDADE_CHOICES, default='PROPRIO')
    cliente_proprietario = serializers.PrimaryKeyRelatedField(queryset=Cliente.unscoped.none(), required=False, allow_null=True)
    numero_patrimonio = serializers.CharField(max_length=50, required=False, allow_blank=True)
    data_aquisicao = serializers.DateField(required=False, allow_null=True)
    valor_aquisicao = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False, allow_null=True)
    chave_nfe_aquisicao = serializers.CharField(max_length=44, required=False, allow_blank=True)
    fornecedor_aquisicao = serializers.CharField(max_length=150, required=False, allow_blank=True)
    classe_ativo = serializers.PrimaryKeyRelatedField(queryset=ClasseAtivo.unscoped.none(), required=False, allow_null=True)
    lote_aquisicao = serializers.PrimaryKeyRelatedField(queryset=LoteAquisicaoCilindros.unscoped.none(), required=False, allow_null=True)
    observacao = serializers.CharField(required=False, allow_blank=True)

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Relacionados só da empresa da requisição (fail-closed: sem tenant, nada é aceito).
        for campo, modelo in (('modelo', ModeloCilindro), ('fabricante_catalogo', FabricanteCilindro),
                              ('cliente_proprietario', Cliente), ('classe_ativo', ClasseAtivo),
                              ('lote_aquisicao', LoteAquisicaoCilindros)):
            self.fields[campo].queryset = modelo.unscoped.filter(tenant=tenant) if tenant else modelo.unscoped.none()

    def validate(self, attrs):
        if attrs.get('propriedade') == 'CLIENTE' and not attrs.get('cliente_proprietario'):
            raise serializers.ValidationError({'cliente_proprietario': 'Informe o cliente dono do cilindro.'})
        if not attrs.get('fabricante_catalogo') and not (attrs.get('fabricante') or '').strip():
            raise serializers.ValidationError({'fabricante': 'Informe o fabricante (do catálogo ou por nome).'})
        lote = attrs.get('lote_aquisicao')
        if lote:
            if lote.quantidade and lote.cilindros.count() >= lote.quantidade:
                raise serializers.ValidationError({
                    'lote_aquisicao': f'A quantidade de cilindros deste lote já atingiu o limite de {lote.quantidade} unidades.'
                })
        return attrs


class HistoricoQualidadeLoteSerializer(serializers.ModelSerializer):
    status_anterior_display = serializers.CharField(source='get_status_anterior_display', read_only=True)
    status_novo_display = serializers.CharField(source='get_status_novo_display', read_only=True)
    usuario_nome = serializers.SerializerMethodField()

    class Meta:
        model = HistoricoQualidadeLote
        fields = [
            'id', 'tenant', 'lote', 'status_anterior', 'status_anterior_display',
            'status_novo', 'status_novo_display', 'justificativa',
            'usuario', 'usuario_nome', 'responsavel_tecnico',
            'rt_nome_snapshot', 'rt_registro_snapshot', 'criado_em'
        ]
        read_only_fields = fields

    def get_usuario_nome(self, obj):
        if obj.usuario:
            return obj.usuario.get_full_name() or obj.usuario.username
        return "Sistema"


class LoteEnvaseSerializer(serializers.ModelSerializer):
    gas_sigla = serializers.CharField(source='gas.sigla', read_only=True)
    gas_nome = serializers.CharField(source='gas.nome', read_only=True)
    esta_vencido = serializers.BooleanField(read_only=True)
    status_qualidade_display = serializers.CharField(source='get_status_qualidade_display', read_only=True)
    ultima_liberacao = serializers.SerializerMethodField()
    transicoes_permitidas = serializers.SerializerMethodField()

    class Meta:
        model = LoteEnvase
        fields = [
            'id', 'tenant', 'gas', 'gas_sigla', 'gas_nome', 'codigo_lote',
            'status_qualidade', 'status_qualidade_display',
            'data_envase', 'data_validade', 'pureza_percentual',
            'responsavel_tecnico', 'responsavel_tecnico_fk',
            'rt_nome_snapshot', 'rt_conselho_snapshot', 'rt_registro_snapshot',
            'laudo_pdf', 'esta_vencido', 'ultima_liberacao', 'transicoes_permitidas',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = [
            'tenant', 'status_qualidade', 'criado_em', 'atualizado_em',
            'ultima_liberacao', 'transicoes_permitidas',
            'responsavel_tecnico', 'responsavel_tecnico_fk',
            'rt_nome_snapshot', 'rt_conselho_snapshot', 'rt_registro_snapshot'
        ]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None and 'codigo_lote' in fields:
            fields['codigo_lote'].read_only = True
        return fields

    def validate_codigo_lote(self, value):
        if self.instance is not None and self.instance.codigo_lote != value:
            raise serializers.ValidationError("O código do lote não pode ser alterado após a criação.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None and self.instance.status_qualidade != 'QUARENTENA':
            raise serializers.ValidationError("Lote liberado não pode ser alterado.")
        return attrs

    def get_ultima_liberacao(self, obj):
        # Otimização anti N+1 (prefetched se disponível)
        if hasattr(obj, 'historicos_ordenados'):
            ultima = obj.historicos_ordenados[0] if obj.historicos_ordenados else None
        else:
            ultima = obj.historico_qualidade.order_by('-criado_em').first()

        if ultima:
            return {
                'status': ultima.status_novo,
                'status_display': ultima.get_status_novo_display(),
                'rt': ultima.rt_nome_snapshot,
                'registro': ultima.rt_registro_snapshot,
                'data': ultima.criado_em.isoformat(),
                'justificativa': ultima.justificativa,
            }
        return {
            'status': obj.status_qualidade,
            'status_display': obj.get_status_qualidade_display(),
            'rt': 'Sem registro (anterior ao histórico)',
            'registro': '—',
            'data': None,
            'justificativa': '',
        }

    def get_transicoes_permitidas(self, obj):
        from produtos.services.ciclo_cilindro import TRANSICOES_QUALIDADE_LOTE, obter_rt_vinculado_para_liberacao
        context = self.context or {}
        pode_liberar = context.get('usuario_pode_liberar_rt')
        if pode_liberar is None:
            request = context.get('request')
            if request and getattr(request, 'user', None) and request.user.is_authenticated:
                tenant = getattr(request, 'tenant', None)
                tenant_id = getattr(tenant, 'id', None) or getattr(request, 'tenant_id', None) or obj.tenant_id
                try:
                    obter_rt_vinculado_para_liberacao(request.user, tenant_id=tenant_id)
                    pode_liberar = True
                except PermissionError:
                    pode_liberar = False
            else:
                pode_liberar = False

        if not pode_liberar:
            return []
        return TRANSICOES_QUALIDADE_LOTE.get(obj.status_qualidade, [])


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
    lote_atual_codigo = serializers.SerializerMethodField()
    envio_reteste_aberto = serializers.SerializerMethodField()
    baixa_ativa_id = serializers.SerializerMethodField()

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
            'bloqueio_sanitario', 'motivo_bloqueio_sanitario', 'reteste_vencido',
            'envio_reteste_aberto', 'baixa_ativa_id'
        ]
        read_only_fields = ['tenant', 'status', 'cliente_posse_atual', 'posse_desde', 'envase_atual', 'recebimento_externo_atual']

    def get_lote_atual_codigo(self, obj):
        if obj.envase_atual and obj.envase_atual.lote:
            return obj.envase_atual.lote.codigo_lote
        elif obj.recebimento_externo_atual:
            return obj.recebimento_externo_atual.lote_fornecedor
        return None

    def get_envio_reteste_aberto(self, obj):
        item = obj.itens_envio_reteste.filter(retornado=False).select_related('envio').order_by('-criado_em').first()
        if not item:
            return None
        return {
            'envio_id': item.envio_id,
            'oficina_nome': item.envio.oficina_nome,
            'oficina_cnpj': item.envio.oficina_cnpj,
            'data_envio': str(item.envio.data_envio),
        }

    def get_baixa_ativa_id(self, obj):
        if obj.status != 'BAIXADO':
            return None
        baixa = obj.baixas_patrimoniais.filter(estornada=False).order_by('-criado_em').first()
        return baixa.id if baixa else None


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
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    itens_cliente = ItemRecallClienteSerializer(many=True, read_only=True)

    class Meta:
        model = RecallCampanha
        fields = [
            'id', 'tenant', 'lote', 'lote_codigo', 'codigo_campanha',
            'status', 'status_display', 'motivo', 'texto_notificacao', 'criado_por',
            'criado_por_nome', 'homologado_por_rt', 'rt_nome_snapshot',
            'rt_registro_snapshot', 'aberto_em', 'homologado_em',
            'concluido_em', 'itens_cliente'
        ]
        # A situação só muda pelos serviços (homologar / registrar andamento), nunca por PATCH.
        read_only_fields = ['tenant', 'aberto_em', 'status', 'criado_por', 'homologado_por_rt',
                            'rt_nome_snapshot', 'rt_registro_snapshot', 'homologado_em', 'concluido_em']


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
    depreciacao_acumulada_rs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = AtivoImobilizado
        fields = [
            'id', 'tenant', 'filial', 'filial_nome', 'classe', 'classe_codigo', 'classe_nome',
            'numero_patrimonio', 'descricao', 'data_aquisicao', 'data_inicio_depreciacao',
            'valor_aquisicao', 'valor_residual', 'vida_util_meses',
            'fornecedor_nome', 'fornecedor_documento', 'chave_nfe_aquisicao',
            'status', 'status_display',
            'depreciacao_mensal_rs', 'depreciacao_diaria_rs', 'valor_contabil_liquido_atual',
            'depreciacao_acumulada_rs',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']


class LoteAquisicaoCilindrosSerializer(serializers.ModelSerializer):
    classe_codigo = serializers.CharField(source='classe.codigo', read_only=True)
    classe_nome = serializers.CharField(source='classe.nome', read_only=True)
    total_cilindros_vinculados = serializers.IntegerField(source='cilindros.count', read_only=True)

    class Meta:
        model = LoteAquisicaoCilindros
        fields = [
            'id', 'tenant', 'classe', 'classe_codigo', 'classe_nome',
            'fornecedor_nome', 'fornecedor_documento', 'chave_nfe',
            'data_aquisicao', 'quantidade', 'valor_total', 'valor_unitario',
            'total_cilindros_vinculados',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['tenant', 'criado_em', 'atualizado_em']

    def validate_chave_nfe(self, value):
        if value:
            import re
            from django.core.exceptions import ValidationError as DjangoValidationError
            from core.validators import validar_chave_nfe
            if not re.match(r'^\d{44}$', str(value)):
                raise serializers.ValidationError('A chave de NF-e deve conter exatamente 44 dígitos numéricos.')
            try:
                validar_chave_nfe(value)
            except DjangoValidationError as exc:
                msg = exc.message if hasattr(exc, 'message') else str(exc)
                raise serializers.ValidationError(msg)
        return value


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

    def validate(self, attrs):
        # 1. Bloquear edição direta de valor na linha existente
        if self.instance and 'valor' in attrs and attrs['valor'] != self.instance.valor:
            raise serializers.ValidationError({
                'valor': 'O valor de indenização vigente não pode ser alterado diretamente por edição. Para alterar o valor, registre uma nova vigência.'
            })

        # 2. Validação de sobreposição de vigências
        tenant = self.instance.tenant if self.instance else (
            self.context.get('request') and getattr(self.context['request'], 'tenant', None)
        )
        tipo = attrs.get('tipo_cilindro') or (self.instance and self.instance.tipo_cilindro)
        gas = attrs.get('gas') if 'gas' in attrs else (self.instance.gas if self.instance else None)
        inicio = attrs.get('vigencia_inicio') or (self.instance and self.instance.vigencia_inicio)
        fim = attrs.get('vigencia_fim') if 'vigencia_fim' in attrs else (self.instance.vigencia_fim if self.instance else None)

        if tenant and tipo and inicio:
            from django.db.models import Q
            qs = TabelaIndenizacaoCilindro.objects.filter(
                tenant=tenant,
                tipo_cilindro=tipo,
                gas=gas,
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)

            # Verifica sobreposição de datas
            if fim:
                q_overlap = Q(vigencia_inicio__lte=fim) & (Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=inicio))
            else:
                q_overlap = Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=inicio)

            if qs.filter(q_overlap).exists():
                raise serializers.ValidationError({
                    'vigencia_inicio': 'Existe sobreposição de vigência com outro registro para o mesmo modelo e gás.'
                })

        return super().validate(attrs)


# ==============================================================================
# SERIALIZERS DE RETESTE HIDROSTÁTICO, ENVIOS E BAIXA PATRIMONIAL (SPRINT 8B)
# ==============================================================================

class HistoricoRetesteHidrostaticoSerializer(serializers.ModelSerializer):
    cilindro_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    usuario_nome = serializers.CharField(source='usuario.get_full_name', read_only=True, default=None)
    resultado_display = serializers.CharField(source='get_resultado_display', read_only=True)
    tem_laudo_pdf = serializers.SerializerMethodField()

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
            'data_proximo_reteste', 'custo_servico_reteste', 'tem_laudo_pdf',
            'observacoes', 'usuario', 'usuario_nome', 'criado_em'
        ]
        read_only_fields = ['tenant', 'expansao_permanente_percentual', 'variacao_tara_percentual', 'criado_em']

    def get_tem_laudo_pdf(self, obj):
        return bool(obj.laudo_pdf)


class ItemEnvioRetesteSerializer(serializers.ModelSerializer):
    cilindro_serie = serializers.CharField(source='cilindro.numero_serie_ogiva', read_only=True)
    cilindro_qr = serializers.CharField(source='cilindro.codigo_qr', read_only=True)
    cilindro_tara_kg = serializers.DecimalField(source='cilindro.tara_real_kg', max_digits=8, decimal_places=3, read_only=True)
    cilindro_modelo_descricao = serializers.CharField(source='cilindro.modelo.descricao', read_only=True, default=None)

    class Meta:
        model = ItemEnvioReteste
        fields = [
            'id', 'tenant', 'envio', 'cilindro', 'cilindro_serie', 'cilindro_qr',
            'cilindro_tara_kg', 'cilindro_modelo_descricao',
            'status_anterior', 'retornado', 'reteste_vinculado', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']


class EnvioRetesteSerializer(serializers.ModelSerializer):
    itens = ItemEnvioRetesteSerializer(many=True, read_only=True)
    criado_por_nome = serializers.CharField(source='criado_por.get_full_name', read_only=True, default=None)
    total_cilindros = serializers.IntegerField(source='itens.count', read_only=True)
    pendentes_retorno = serializers.SerializerMethodField()

    class Meta:
        model = EnvioReteste
        fields = [
            'id', 'tenant', 'oficina_nome', 'oficina_cnpj', 'documento_envio', 'data_envio',
            'observacoes', 'criado_por', 'criado_por_nome', 'total_cilindros',
            'pendentes_retorno', 'itens', 'criado_em'
        ]
        read_only_fields = ['tenant', 'criado_em']

    def get_pendentes_retorno(self, obj):
        return obj.itens.filter(retornado=False).count()


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
        read_only_fields = [
            'tenant', 'status_anterior', 'usuario', 'usuario_estorno',
            'motivo_estorno', 'valor_contabil_baixa', 'resultado',
            'estornada', 'data_estorno', 'criado_em',
        ]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None and 'cilindro' in fields:
            fields['cilindro'].read_only = True
        return fields


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




