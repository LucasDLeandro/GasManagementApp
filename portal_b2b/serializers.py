"""
Serializadores do Portal B2B do Cliente Final (Sprint 12B).

Implementa:
- Serializadores de leitura e de escrita com validação estrita.
- Formatação de valores monetários via Decimal (sem float).
- Serialização de solicitações de reposição, notificações, usuários e downloads.
"""
from decimal import Decimal
from rest_framework import serializers

from vendas.models import Venda, ItemVenda
from faturamento.models import FaturaCobranca
from produtos.models import Cilindro, MovimentacaoCilindro
from clientes.models import Cliente, UsuarioClienteB2B
from portal_b2b.models import (
    SolicitacaoReposicao,
    NotificacaoB2B,
    DownloadDocumentoB2B,
    ConviteB2B,
)


class B2BItemVendaSerializer(serializers.ModelSerializer):
    sku_nome = serializers.SerializerMethodField()
    gas_nome = serializers.SerializerMethodField()

    class Meta:
        model = ItemVenda
        fields = [
            'id',
            'sku_nome',
            'gas_nome',
            'forma_faturamento',
            'quantidade',
            'valor_unitario',
            'valor_total',
        ]

    def get_sku_nome(self, obj):
        if obj.sku:
            return obj.sku.nome_comercial
        elif obj.produto:
            return obj.produto.nome
        return "Item Padrão"

    def get_gas_nome(self, obj):
        if obj.sku and obj.sku.gas:
            return obj.sku.gas.nome
        return None


class B2BVendaSerializer(serializers.ModelSerializer):
    itens = B2BItemVendaSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    tipo_operacao_display = serializers.CharField(source='get_tipo_operacao_display', read_only=True)

    class Meta:
        model = Venda
        fields = [
            'id',
            'data_venda',
            'status',
            'status_display',
            'tipo_operacao',
            'tipo_operacao_display',
            'forma_pagamento',
            'condicao_pagamento',
            'valor_total',
            'valor_desconto',
            'documento_fiscal_ref',
            'prazo_entrega',
            'data_entrega_efetiva',
            'observacoes',
            'itens',
        ]


class B2BFaturaSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    venda_id = serializers.IntegerField(source='venda.id', read_only=True, default=None)
    estadia_competencia = serializers.CharField(source='estadia.competencia_ano_mes', read_only=True, default=None)

    class Meta:
        model = FaturaCobranca
        fields = [
            'id',
            'uuid',
            'status',
            'status_display',
            'valor',
            'qr_code_pix',
            'linha_digitavel',
            'link_pagamento',
            'data_vencimento',
            'data_pagamento',
            'venda_id',
            'estadia_competencia',
            'criado_em',
        ]


class B2BCilindroSerializer(serializers.ModelSerializer):
    gas_nome = serializers.CharField(source='gas_dedicado.nome', read_only=True)
    gas_sigla = serializers.CharField(source='gas_dedicado.sigla', read_only=True)
    modelo_nome = serializers.CharField(source='modelo.descricao', read_only=True)
    volume_litros = serializers.DecimalField(source='modelo.volume_hidraulico_litros', max_digits=6, decimal_places=2, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    reteste_vencido = serializers.BooleanField(read_only=True)
    tem_laudo_disponivel = serializers.SerializerMethodField()

    class Meta:
        model = Cilindro
        fields = [
            'id',
            'codigo_qr',
            'numero_serie_ogiva',
            'fabricante',
            'ano_fabricacao',
            'status',
            'status_display',
            'gas_nome',
            'gas_sigla',
            'modelo_nome',
            'volume_litros',
            'posse_desde',
            'data_proximo_reteste',
            'reteste_vencido',
            'tem_laudo_disponivel',
        ]

    def get_tem_laudo_disponivel(self, obj):
        if obj.envase_atual and obj.envase_atual.lote:
            return True
        if obj.recebimento_externo_atual and obj.recebimento_externo_atual.laudo_pdf:
            return True
        return obj.movimentacoes.filter(tipo__in=['ENTREGA_CLIENTE', 'ENVASE']).exists()


class B2BPerfilClienteSerializer(serializers.Serializer):
    cliente_id = serializers.IntegerField()
    cliente_nome = serializers.CharField()
    cnpj = serializers.CharField()
    logradouro = serializers.CharField()
    cidade = serializers.CharField()
    estado = serializers.CharField()
    telefone = serializers.CharField()
    email_financeiro = serializers.CharField(allow_null=True)
    usuario_nome = serializers.CharField()
    usuario_email = serializers.CharField()
    cargo = serializers.CharField(allow_null=True)
    papel = serializers.CharField()
    administrador_cliente = serializers.BooleanField()
    total_cilindros_em_posse = serializers.IntegerField()
    total_faturas_abertas = serializers.IntegerField()
    valor_total_aberto = serializers.DecimalField(max_digits=12, decimal_places=2)


# ==============================================================================
# Reposição em 1 Clique (Sprint 12B)
# ==============================================================================

class B2BItemReposicaoInputSerializer(serializers.Serializer):
    sku_id = serializers.IntegerField(required=False, allow_null=True)
    produto_id = serializers.IntegerField(required=False, allow_null=True)
    quantidade = serializers.IntegerField(min_value=1, default=1)


class B2BSolicitacaoReposicaoInputSerializer(serializers.Serializer):
    chave_idempotencia = serializers.CharField(max_length=100)
    itens = B2BItemReposicaoInputSerializer(many=True)
    observacoes = serializers.CharField(required=False, allow_blank=True, default='')


class B2BSolicitacaoReposicaoSerializer(serializers.ModelSerializer):
    venda_id = serializers.IntegerField(source='venda.id', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SolicitacaoReposicao
        fields = [
            'id',
            'chave_idempotencia',
            'status',
            'status_display',
            'avaliacao_credito',
            'motivos_credito',
            'alerta_assistencial',
            'itens',
            'valor_total',
            'venda_id',
            'observacoes',
            'criado_em',
        ]


# ==============================================================================
# Notificações e Equipe do Cliente (Sprint 12B)
# ==============================================================================

class B2BNotificacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificacaoB2B
        fields = [
            'id',
            'tipo',
            'canal',
            'status',
            'titulo',
            'mensagem',
            'recurso_tipo',
            'recurso_id',
            'criado_em',
        ]


class B2BUsuarioClienteB2BSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    nome = serializers.CharField(source='user.get_full_name', read_only=True)
    esta_bloqueado = serializers.BooleanField(read_only=True)

    class Meta:
        model = UsuarioClienteB2B
        fields = [
            'id',
            'username',
            'email',
            'nome',
            'cargo',
            'telefone_contato',
            'papel',
            'administrador_cliente',
            'ativo',
            'ultimo_acesso',
            'esta_bloqueado',
            'criado_em',
        ]


class B2BConviteInputSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    nome = serializers.CharField(max_length=150, required=False, default='')
    cargo = serializers.CharField(max_length=100, required=False, default='')
    telefone_contato = serializers.CharField(max_length=20, required=False, default='')
    papel = serializers.ChoiceField(choices=UsuarioClienteB2B.PAPEL_CHOICES, default=UsuarioClienteB2B.PAPEL_LEITOR)
    administrador_cliente = serializers.BooleanField(default=False)


class B2BAceiteConviteSerializer(serializers.Serializer):
    token = serializers.CharField()
    nova_senha = serializers.CharField(min_length=10)


class B2BMFASetupSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=6, max_length=8)
