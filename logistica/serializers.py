from rest_framework import serializers
from django.utils import timezone
from .models import (
    Veiculo,
    VeiculoFoto,
    VeiculoDocumento,
    DocumentoObrigatorioVeiculo,
    VeiculoValorFipe,
    LogExcecaoOperacionalVeiculo,
    Rota,
    ManutencaoFrota,
    TabelaFrete,
    ValidacaoCarga,
    ValidacaoCargaEvidencia,
    ConfiguracaoValidacaoCarga,
    Entrega,
    Abastecimento,
    PrecoCombustivelReferencia,
    ConfiguracaoCombustivelFrota,
    Fornecedor,
    PlanoManutencao,
    OrdemServico,
    OSItem,
    OSAnexo,
    ChecklistModelo,
    ChecklistExecucao,
    ApoliceSeguro,
    ApoliceCobertura,
    ApoliceVeiculo,
    ConfiguracaoSeguros,
    Sinistro,
    SinistroEvento,
    SinistroAnexo,
    SinistroItemCarga,
    ConfiguracaoRentabilidade,
    CustoViagem,
    CustoViagemItem
)
from vendas.models import ItemVenda
from core.models import Membership
from .services import veiculo_apto_para_operar


class VeiculoFotoSerializer(serializers.ModelSerializer):
    imagem_url = serializers.SerializerMethodField()
    miniatura_url = serializers.SerializerMethodField()
    enviada_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = VeiculoFoto
        fields = [
            'id', 'veiculo', 'tipo', 'principal', 'tirada_em',
            'enviada_por', 'enviada_por_nome', 'criado_em',
            'imagem_url', 'miniatura_url'
        ]
        read_only_fields = ['id', 'criado_em', 'imagem_url', 'miniatura_url', 'enviada_por_nome']

    def get_imagem_url(self, obj):
        if obj.imagem:
            return f"/logistica/api/veiculos/fotos/{obj.id}/arquivo/"
        return None

    def get_miniatura_url(self, obj):
        if obj.miniatura:
            return f"/logistica/api/veiculos/fotos/{obj.id}/miniatura/"
        elif obj.imagem:
            return f"/logistica/api/veiculos/fotos/{obj.id}/arquivo/"
        return None

    def get_enviada_por_nome(self, obj):
        if obj.enviada_por:
            return obj.enviada_por.get_full_name() or obj.enviada_por.username
        return None


class VeiculoDocumentoSerializer(serializers.ModelSerializer):
    situacao = serializers.ReadOnlyField()
    dias_para_vencer = serializers.ReadOnlyField()
    arquivo_url = serializers.SerializerMethodField()
    enviado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = VeiculoDocumento
        fields = [
            'id', 'veiculo', 'tipo', 'numero', 'emissao', 'vencimento',
            'observacoes', 'ativo', 'enviado_por', 'enviado_por_nome',
            'criado_em', 'situacao', 'dias_para_vencer', 'arquivo_url'
        ]
        read_only_fields = ['id', 'criado_em', 'situacao', 'dias_para_vencer', 'arquivo_url', 'enviado_por_nome']

    def get_arquivo_url(self, obj):
        if obj.arquivo:
            return f"/logistica/api/veiculos/documentos/{obj.id}/arquivo/"
        return None

    def get_enviado_por_nome(self, obj):
        if obj.enviado_por:
            return obj.enviado_por.get_full_name() or obj.enviado_por.username
        return None


class DocumentoObrigatorioVeiculoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoObrigatorioVeiculo
        fields = '__all__'


class VeiculoValorFipeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VeiculoValorFipe
        fields = '__all__'


class LogExcecaoOperacionalVeiculoSerializer(serializers.ModelSerializer):
    usuario_nome = serializers.SerializerMethodField()

    class Meta:
        model = LogExcecaoOperacionalVeiculo
        fields = '__all__'

    def get_usuario_nome(self, obj):
        if obj.usuario:
            return obj.usuario.get_full_name() or obj.usuario.username
        return None


class VeiculoSerializer(serializers.ModelSerializer):
    motorista_padrao_nome = serializers.SerializerMethodField()
    foto_principal_url = serializers.SerializerMethodField()
    miniatura_principal_url = serializers.SerializerMethodField()
    valor_mercado_estimado = serializers.FloatField(read_only=True)
    apto_operacao = serializers.SerializerMethodField()
    motivos_bloqueio = serializers.SerializerMethodField()
    documentos_resumo = serializers.SerializerMethodField()
    fotos = VeiculoFotoSerializer(many=True, read_only=True)
    documentos = VeiculoDocumentoSerializer(many=True, read_only=True)

    class Meta:
        model = Veiculo
        fields = '__all__'

    def get_motorista_padrao_nome(self, obj):
        if obj.motorista_padrao:
            return obj.motorista_padrao.get_full_name() or obj.motorista_padrao.username
        return None

    def get_foto_principal_url(self, obj):
        fp = obj.foto_principal
        if fp and fp.imagem:
            return f"/logistica/api/veiculos/fotos/{fp.id}/arquivo/"
        return None

    def get_miniatura_principal_url(self, obj):
        fp = obj.foto_principal
        if fp:
            if fp.miniatura:
                return f"/logistica/api/veiculos/fotos/{fp.id}/miniatura/"
            elif fp.imagem:
                return f"/logistica/api/veiculos/fotos/{fp.id}/arquivo/"
        return None

    def get_apto_operacao(self, obj):
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else getattr(obj, 'tenant', None)
        apto, _ = veiculo_apto_para_operar(obj, tenant=tenant)
        return apto

    def get_motivos_bloqueio(self, obj):
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else getattr(obj, 'tenant', None)
        _, motivos = veiculo_apto_para_operar(obj, tenant=tenant)
        return motivos

    def get_documentos_resumo(self, obj):
        docs = obj.documentos.filter(ativo=True)
        total = docs.count()
        vencidos = 0
        vencendo = 0
        em_dia = 0
        hoje = timezone.localdate()
        for d in docs:
            if not d.vencimento:
                em_dia += 1
            elif d.vencimento < hoje:
                vencidos += 1
            elif d.vencimento <= hoje + timezone.timedelta(days=30):
                vencendo += 1
            else:
                em_dia += 1
        return {
            'total': total,
            'em_dia': em_dia,
            'vencendo': vencendo,
            'vencidos': vencidos
        }

    def get_apolice_vigente_info(self, obj):
        hoje = timezone.localdate()
        vinc = ApoliceVeiculo.objects.filter(
            veiculo=obj,
            apolice__ativa=True,
            apolice__vigencia_fim__gte=hoje
        ).select_related('apolice').first()

        if not vinc:
            return None

        ap = vinc.apolice
        cobs = [
            {
                'cobertura': c.cobertura,
                'limite': float(c.limite) if c.limite else None,
                'franquia_valor': float(c.franquia_valor) if c.franquia_valor else 0.0,
                'franquia_percentual': float(c.franquia_percentual) if c.franquia_percentual else None
            }
            for c in ap.coberturas.all()
        ]

        return {
            'apolice_id': ap.id,
            'numero_apolice': ap.numero_apolice,
            'seguradora': ap.seguradora,
            'tipo': ap.tipo,
            'vigencia_fim': ap.vigencia_fim.strftime('%d/%m/%Y'),
            'dias_para_vencimento': ap.dias_para_vencimento,
            'status_vigencia': ap.status_vigencia,
            'semaforo_vigencia': ap.semaforo_vigencia,
            'telefone_assistencia_24h': ap.telefone_assistencia_24h,
            'valor_segurado': float(vinc.valor_segurado) if vinc.valor_segurado else None,
            'tipo_valor': vinc.tipo_valor,
            'coberturas': cobs
        }

    def get_sinistros_recentes_resumo(self, obj):
        sinistros = obj.sinistros.order_by('-data_hora')[:5]
        return [
            {
                'id': s.id,
                'numero': s.numero,
                'tipo': s.tipo,
                'data_hora': s.data_hora.strftime('%d/%m/%Y %H:%M'),
                'status': s.status,
                'prejuizo_liquido': float(s.prejuizo_liquido),
                'houve_vitimas': s.houve_vitimas
            }
            for s in sinistros
        ]

    apolice_vigente_info = serializers.SerializerMethodField()
    sinistros_recentes_resumo = serializers.SerializerMethodField()

class ValidacaoCargaEvidenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValidacaoCargaEvidencia
        fields = ['id', 'arquivo', 'tirada_em', 'descricao', 'criado_em']
        read_only_fields = ['id', 'tirada_em', 'criado_em']


class ConfiguracaoValidacaoCargaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracaoValidacaoCarga
        fields = ['id', 'limite_ajuste_sem_aprovacao_un', 'limite_valor_sem_aprovacao', 'motivos_exigem_foto']


class ValidacaoCargaSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(source='produto.nome', read_only=True)
    venda_id = serializers.IntegerField(source='venda.id', read_only=True)
    cliente_nome = serializers.CharField(source='venda.cliente.nome', read_only=True)
    aprovado_por_nome = serializers.SerializerMethodField(read_only=True)
    criado_por_nome = serializers.SerializerMethodField(read_only=True)
    evidencias = ValidacaoCargaEvidenciaSerializer(many=True, read_only=True)

    class Meta:
        model = ValidacaoCarga
        fields = [
            'id',
            'entrega',
            'venda',
            'venda_id',
            'cliente_nome',
            'produto',
            'produto_nome',
            'quantidade_alterada',
            'etapa_logistica',
            'justificativa',
            'motivo',
            'categoria_item',
            'quantidade_esperada',
            'quantidade_conferida',
            'diferenca',
            'valor_impacto',
            'status',
            'exige_aprovacao',
            'aprovado_por',
            'aprovado_por_nome',
            'aprovado_em',
            'observacao_aprovacao',
            'dispositivo_ip',
            'valida_anterior',
            'criado_por',
            'criado_por_nome',
            'sugere_sinistro',
            'evidencias',
            'data_hora',
            'criado_em',
        ]
        read_only_fields = [
            'id',
            'venda_id',
            'cliente_nome',
            'produto_nome',
            'diferenca',
            'valor_impacto',
            'status',
            'exige_aprovacao',
            'aprovado_por',
            'aprovado_por_nome',
            'aprovado_em',
            'sugere_sinistro',
            'data_hora',
            'criado_em',
        ]

    def get_aprovado_por_nome(self, obj):
        if obj.aprovado_por:
            return obj.aprovado_por.get_full_name() or obj.aprovado_por.username
        return None

    def get_criado_por_nome(self, obj):
        if obj.criado_por:
            return obj.criado_por.get_full_name() or obj.criado_por.username
        return None

class RotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rota
        fields = '__all__'

class ManutencaoFrotaSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    
    class Meta:
        model = ManutencaoFrota
        fields = '__all__'

class TabelaFreteSerializer(serializers.ModelSerializer):
    rota_nome = serializers.CharField(source='rota.nome', read_only=True)

    class Meta:
        model = TabelaFrete
        fields = '__all__'

class EntregaSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    veiculo_modelo = serializers.CharField(source='veiculo.modelo', read_only=True)
    veiculo_capacidade = serializers.DecimalField(source='veiculo.capacidade_carga', max_digits=10, decimal_places=2, read_only=True)
    rota_nome = serializers.CharField(source='rota.nome', read_only=True)
    motorista_nome = serializers.SerializerMethodField()
    peso_total_carregado = serializers.FloatField(read_only=True)
    capacidade_disponivel = serializers.FloatField(read_only=True)
    percentual_lotacao = serializers.FloatField(read_only=True)
    possui_peso_estimado = serializers.BooleanField(read_only=True)
    comprovantes_count = serializers.IntegerField(source='comprovantes.count', read_only=True)
    veiculo_foto_url = serializers.SerializerMethodField()
    veiculo_miniatura_url = serializers.SerializerMethodField()
    veiculo_apto = serializers.SerializerMethodField()
    veiculo_motivos_bloqueio = serializers.SerializerMethodField()
    custo_viagem_resumo = serializers.SerializerMethodField()
    # Para detalhar os pedidos e paradas atrelados
    vendas = serializers.SerializerMethodField()

    class Meta:
        model = Entrega
        fields = '__all__'

    def get_veiculo_foto_url(self, obj):
        if obj.veiculo and obj.veiculo.foto_principal:
            return f"/logistica/api/veiculos/fotos/{obj.veiculo.foto_principal.id}/arquivo/"
        return None

    def get_veiculo_miniatura_url(self, obj):
        if obj.veiculo and obj.veiculo.foto_principal:
            fp = obj.veiculo.foto_principal
            if fp.miniatura:
                return f"/logistica/api/veiculos/fotos/{fp.id}/miniatura/"
            return f"/logistica/api/veiculos/fotos/{fp.id}/arquivo/"
        return None

    def get_veiculo_apto(self, obj):
        if not obj.veiculo:
            return True
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else getattr(obj, 'tenant', None)
        apto, _ = veiculo_apto_para_operar(obj.veiculo, tenant=tenant)
        return apto

    def get_veiculo_motivos_bloqueio(self, obj):
        if not obj.veiculo:
            return []
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else getattr(obj, 'tenant', None)
        _, motivos = veiculo_apto_para_operar(obj.veiculo, tenant=tenant)
        return motivos

    def get_motorista_nome(self, obj):
        if obj.motorista:
            return obj.motorista.get_full_name() or obj.motorista.username
        return None

    def get_vendas(self, obj):
        vendas = obj.vendas.select_related('cliente').prefetch_related('itens__produto').all()
        lista = []
        for v in vendas:
            itens_info = []
            for it in v.itens.all():
                itens_info.append({
                    'produto_nome': it.produto.nome if it.produto else 'Item',
                    'quantidade': it.quantidade
                })
            lista.append({
                "id": v.id,
                "cliente_id": v.cliente.id if v.cliente else None,
                "cliente_nome": v.cliente.nome if v.cliente else 'Cliente Não Informado',
                "cliente_cnpj": v.cliente.cnpj if v.cliente else '',
                "cliente_endereco": v.cliente.endereco if v.cliente else '',
                "cliente_telefone": v.cliente.telefone if v.cliente else '',
                "status": v.status,
                "valor_total": float(v.valor_total),
                "itens": itens_info
            })
        return lista

    def get_custo_viagem_resumo(self, obj):
        cv = getattr(obj, 'custo_viagem', None)
        if cv:
            return {
                'id': cv.id,
                'combustivel_estimado': float(cv.combustivel_estimado or 0),
                'combustivel_real': float(cv.combustivel_real or 0),
                'custo_total_real': float(cv.custo_total_real or 0),
                'receita_frete': float(cv.receita_frete or 0),
                'margem_bruta': float(cv.margem_bruta or 0),
                'margem_percentual': float(cv.margem_percentual) if cv.margem_percentual is not None else None,
                'snapshot_congelado': cv.snapshot_congelado,
                'dados_incompletos': cv.dados_incompletos,
                'motivo_dados_incompletos': cv.motivo_dados_incompletos,
                'alerta_averbacao': cv.alerta_averbacao,
                'motivo_alerta_averbacao': cv.motivo_alerta_averbacao,
                'alerta_baixa_ocupacao': cv.alerta_baixa_ocupacao,
                'motivo_baixa_ocupacao': cv.motivo_baixa_ocupacao,
                'fonte_preco': cv.combustivel_estimado_fonte_preco,
                'data_preco': cv.combustivel_estimado_data_preco.strftime('%d/%m/%Y') if cv.combustivel_estimado_data_preco else None
            }
        return None


class ComprovanteEntregaSerializer(serializers.ModelSerializer):
    entrega_id = serializers.IntegerField(source='entrega.id', read_only=True)
    movimentacao_id = serializers.IntegerField(source='movimentacao.id', read_only=True)
    assinatura_url = serializers.SerializerMethodField()

    class Meta:
        from .models import ComprovanteEntrega
        model = ComprovanteEntrega
        fields = [
            'id',
            'entrega_id',
            'movimentacao_id',
            'recebedor_nome',
            'recebedor_documento',
            'assinatura_url',
            'timestamp_captura',
            'latitude',
            'longitude',
            'hash_integridade_sha256'
        ]
        read_only_fields = ['id', 'hash_integridade_sha256', 'timestamp_captura']

    def get_assinatura_url(self, obj):
        if obj.assinatura_imagem:
            return f"/logistica/api/comprovantes/{obj.id}/assinatura/"
        return None


class PrecoCombustivelReferenciaSerializer(serializers.ModelSerializer):
    esta_defasado = serializers.ReadOnlyField()

    class Meta:
        model = PrecoCombustivelReferencia
        fields = '__all__'


class ConfiguracaoCombustivelFrotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracaoCombustivelFrota
        fields = '__all__'


class AbastecimentoSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    veiculo_modelo = serializers.CharField(source='veiculo.modelo', read_only=True)
    motorista_nome = serializers.SerializerMethodField()
    comprovante_url = serializers.SerializerMethodField()

    class Meta:
        model = Abastecimento
        fields = '__all__'
        read_only_fields = [
            'id', 'km_rodados_desde_anterior', 'consumo_km_l',
            'custo_por_km', 'status_validacao', 'alertas',
            'criado_em', 'atualizado_em'
        ]

    def get_motorista_nome(self, obj):
        if obj.motorista:
            return obj.motorista.get_full_name() or obj.motorista.username
        return None

    def get_comprovante_url(self, obj):
        if obj.comprovante:
            return f"/logistica/api/abastecimentos/{obj.id}/comprovante/"
        return None


# ==============================================================================
# SPRINT L3: MANUTENÇÃO PREVENTIVA E CORRETIVA SERIALIZERS
# ==============================================================================

class FornecedorSerializer(serializers.ModelSerializer):
    total_os = serializers.IntegerField(source='ordens_servico.count', read_only=True)

    class Meta:
        model = Fornecedor
        fields = '__all__'
        read_only_fields = ['id', 'criado_em', 'atualizado_em']


class PlanoManutencaoSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    veiculo_modelo = serializers.CharField(source='veiculo.modelo', read_only=True)
    fornecedor_nome = serializers.CharField(source='fornecedor_preferido.nome', default='', read_only=True)
    proximo_vencimento_km = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    proximo_vencimento_data = serializers.DateField(read_only=True)
    status_info = serializers.SerializerMethodField()

    class Meta:
        model = PlanoManutencao
        fields = '__all__'
        read_only_fields = ['id', 'criado_em', 'atualizado_em']

    def get_status_info(self, obj):
        return obj.calcular_status_vencimento()


class OSItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OSItem
        fields = '__all__'
        read_only_fields = ['id', 'valor_total', 'criado_em']


class OSAnexoSerializer(serializers.ModelSerializer):
    enviado_por_nome = serializers.SerializerMethodField()
    arquivo_url = serializers.SerializerMethodField()

    class Meta:
        model = OSAnexo
        fields = '__all__'
        read_only_fields = ['id', 'criado_em']

    def get_enviado_por_nome(self, obj):
        if obj.enviado_por:
            return obj.enviado_por.get_full_name() or obj.enviado_por.username
        return None

    def get_arquivo_url(self, obj):
        if obj.arquivo:
            return f"/logistica/api/ordens-servico/anexos/{obj.id}/download/"
        return None


class OrdemServicoSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    veiculo_modelo = serializers.CharField(source='veiculo.modelo', read_only=True)
    fornecedor_nome = serializers.CharField(source='fornecedor.nome', default='', read_only=True)
    aprovado_por_nome = serializers.SerializerMethodField()
    plano_descricao = serializers.CharField(source='plano.descricao', default='', read_only=True)
    itens = OSItemSerializer(many=True, read_only=True)
    anexos = OSAnexoSerializer(many=True, read_only=True)
    total_itens = serializers.IntegerField(source='itens.count', read_only=True)
    total_anexos = serializers.IntegerField(source='anexos.count', read_only=True)

    class Meta:
        model = OrdemServico
        fields = '__all__'
        read_only_fields = ['id', 'numero', 'aprovado_por', 'aprovado_em', 'historico_status', 'criado_em', 'atualizado_em']

    def get_aprovado_por_nome(self, obj):
        if obj.aprovado_por:
            return obj.aprovado_por.get_full_name() or obj.aprovado_por.username
        return None


class ChecklistModeloSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistModelo
        fields = '__all__'
        read_only_fields = ['id', 'criado_em', 'atualizado_em']


class ChecklistExecucaoSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    veiculo_modelo = serializers.CharField(source='veiculo.modelo', read_only=True)
    motorista_nome = serializers.SerializerMethodField()
    os_numero = serializers.CharField(source='os_gerada.numero', default='', read_only=True)
    foto_url = serializers.SerializerMethodField()

    class Meta:
        model = ChecklistExecucao
        fields = '__all__'
        read_only_fields = ['id', 'aprovado', 'tem_itens_impeditivos', 'os_gerada', 'criado_em']

    def get_motorista_nome(self, obj):
        if obj.motorista:
            return obj.motorista.get_full_name() or obj.motorista.username
        return None

    def get_foto_url(self, obj):
        if obj.foto:
            return f"/logistica/api/checklists/{obj.id}/foto/"
        return None


class ApoliceCoberturaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApoliceCobertura
        fields = [
            'id', 'apolice', 'cobertura', 'limite', 'franquia_valor',
            'franquia_percentual'
        ]
        read_only_fields = ['id']


class ApoliceVeiculoSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    veiculo_modelo = serializers.CharField(source='veiculo.modelo', read_only=True)

    class Meta:
        model = ApoliceVeiculo
        fields = [
            'id', 'apolice', 'veiculo', 'veiculo_placa', 'veiculo_modelo',
            'valor_segurado', 'tipo_valor'
        ]
        read_only_fields = ['id']


class ApoliceSeguroSerializer(serializers.ModelSerializer):
    arquivo_pdf_url = serializers.SerializerMethodField()
    dias_para_vencimento = serializers.IntegerField(read_only=True)
    status_vigencia = serializers.CharField(read_only=True)
    semaforo_vigencia = serializers.CharField(read_only=True)
    coberturas = ApoliceCoberturaSerializer(many=True, read_only=True)
    veiculos_segurados = ApoliceVeiculoSerializer(many=True, read_only=True)

    class Meta:
        model = ApoliceSeguro
        fields = [
            'id', 'seguradora', 'corretor', 'telefone_assistencia_24h',
            'numero_apolice', 'tipo', 'vigencia_inicio', 'vigencia_fim',
            'premio_total', 'forma_pagamento', 'parcelas', 'arquivo_pdf',
            'arquivo_pdf_url', 'prazo_comunicacao_sinistro_horas',
            'limite_maximo_por_viagem', 'cobre_produto_perigoso',
            'produtos_riscos_excluidos', 'observacoes', 'ativa',
            'dias_para_vencimento', 'status_vigencia', 'semaforo_vigencia',
            'coberturas', 'veiculos_segurados'
        ]
        read_only_fields = ['id', 'dias_para_vencimento', 'status_vigencia', 'semaforo_vigencia']

    def get_arquivo_pdf_url(self, obj):
        if obj.arquivo_pdf:
            return f"/logistica/api/apolices/{obj.id}/pdf/"
        return None


class SinistroEventoSerializer(serializers.ModelSerializer):
    autor_nome = serializers.SerializerMethodField()

    class Meta:
        model = SinistroEvento
        fields = [
            'id', 'sinistro', 'data_hora', 'autor', 'autor_nome',
            'tipo', 'status_anterior', 'status_novo', 'descricao'
        ]
        read_only_fields = ['id', 'sinistro', 'data_hora', 'autor', 'autor_nome', 'tipo', 'status_anterior', 'status_novo', 'descricao']

    def get_autor_nome(self, obj):
        if obj.autor:
            return obj.autor.get_full_name() or obj.autor.username
        return "Sistema / PWA"


class SinistroAnexoSerializer(serializers.ModelSerializer):
    arquivo_url = serializers.SerializerMethodField()
    enviado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = SinistroAnexo
        fields = [
            'id', 'sinistro', 'tipo', 'arquivo', 'arquivo_url',
            'descricao', 'enviado_por', 'enviado_por_nome', 'criado_em'
        ]
        read_only_fields = ['id', 'criado_em', 'arquivo_url', 'enviado_por_nome']

    def get_arquivo_url(self, obj):
        if obj.arquivo:
            return f"/logistica/api/sinistros/anexos/{obj.id}/arquivo/"
        return None

    def get_enviado_por_nome(self, obj):
        if obj.enviado_por:
            return obj.enviado_por.get_full_name() or obj.enviado_por.username
        return None


class SinistroItemCargaSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(source='produto.nome', read_only=True)
    produto_codigo = serializers.CharField(source='produto.codigo', default='', read_only=True)

    class Meta:
        model = SinistroItemCarga
        fields = [
            'id', 'sinistro', 'produto', 'produto_nome', 'produto_codigo',
            'quantidade', 'categoria', 'valor_unitario', 'valor_total',
            'ajuste_estoque_realizado'
        ]
        read_only_fields = ['id', 'valor_total']


class SinistroSerializer(serializers.ModelSerializer):
    veiculo_placa = serializers.CharField(source='veiculo.placa', read_only=True)
    veiculo_modelo = serializers.CharField(source='veiculo.modelo', read_only=True)
    motorista_nome = serializers.SerializerMethodField()
    entrega_id_display = serializers.CharField(source='entrega.id', default='', read_only=True)
    apolice_numero = serializers.CharField(source='apolice.numero_apolice', default='', read_only=True)
    apolice_seguradora = serializers.CharField(source='apolice.seguradora', default='', read_only=True)
    os_vinculada_numero = serializers.CharField(source='os_vinculada.numero', default='', read_only=True)
    prazo_comunicacao_expirado = serializers.BooleanField(read_only=True)
    prazo_comunicacao_urgente = serializers.BooleanField(read_only=True)
    comparativo_fipe = serializers.SerializerMethodField()
    eventos = SinistroEventoSerializer(many=True, read_only=True)
    anexos = SinistroAnexoSerializer(many=True, read_only=True)
    itens_carga = SinistroItemCargaSerializer(many=True, read_only=True)
    criado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = Sinistro
        fields = [
            'id', 'numero', 'client_uuid', 'tipo', 'data_hora',
            'latitude', 'longitude', 'endereco', 'veiculo', 'veiculo_placa',
            'veiculo_modelo', 'motorista', 'motorista_nome', 'entrega',
            'entrega_id_display', 'apolice', 'apolice_numero', 'apolice_seguradora',
            'terceiros', 'houve_vitimas', 'boletim_ocorrencia_numero', 'descricao',
            'status', 'protocolo_seguradora', 'data_comunicacao_seguradora',
            'prazo_limite_comunicacao', 'prazo_comunicacao_expirado',
            'prazo_comunicacao_urgente', 'valor_prejuizo_estimado',
            'valor_franquia', 'valor_indenizacao', 'prejuizo_liquido',
            'os_vinculada', 'os_vinculada_numero', 'comparativo_fipe',
            'eventos', 'anexos', 'itens_carga', 'criado_por', 'criado_por_nome',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = [
            'id', 'numero', 'prejuizo_liquido', 'prazo_limite_comunicacao',
            'criado_por', 'criado_em', 'atualizado_em'
        ]

    def get_motorista_nome(self, obj):
        if obj.motorista:
            return obj.motorista.get_full_name() or obj.motorista.username
        return None

    def get_criado_por_nome(self, obj):
        if obj.criado_por:
            return obj.criado_por.get_full_name() or obj.criado_por.username
        return "Sistema / PWA"

    def get_comparativo_fipe(self, obj):
        return obj.comparativo_perda_total_fipe()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Proteção LGPD de dados pessoais de terceiros
        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            user = request.user
            if not user.is_superuser:
                tenant = instance.tenant or getattr(request, 'tenant', None)
                membership = Membership.objects.filter(tenant=tenant, user=user, ativo=True).first() if tenant else None
                is_gestor = membership and membership.papel in ('ADMIN', 'GERENTE')
                if not is_gestor:
                    data['terceiros'] = {
                        'acesso_restrito_lgpd': True,
                        'mensagem': 'Dados pessoais de terceiros protegidos conforme LGPD (Art. 7º). Acesso restrito a gestores e administradores.'
                    }
        return data


class ConfiguracaoSegurosSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracaoSeguros
        fields = [
            'id', 'exigir_apolice_ativa_para_operar', 'alerta_renovacao_dias'
        ]
        read_only_fields = ['id']


class ConfiguracaoRentabilidadeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfiguracaoRentabilidade
        fields = [
            'id', 'metodo_rateio_seguro', 'vida_util_anos', 'percentual_residual',
            'usar_estimativa_combustivel', 'km_anual_estimado_veiculo',
            'media_lotacao_alerta_minima', 'viagens_baixa_ocupacao_alerta'
        ]
        read_only_fields = ['id']


class CustoViagemItemSerializer(serializers.ModelSerializer):
    comprovante_url = serializers.SerializerMethodField()

    class Meta:
        model = CustoViagemItem
        fields = [
            'id', 'custo_viagem', 'tipo', 'valor', 'descricao',
            'comprovante', 'comprovante_url', 'criado_em'
        ]
        read_only_fields = ['id', 'criado_em', 'comprovante_url']

    def get_comprovante_url(self, obj):
        if obj.comprovante:
            return f"/logistica/api/custos-viagem-itens/{obj.id}/comprovante/"
        return None


class CustoViagemSerializer(serializers.ModelSerializer):
    entrega_status = serializers.CharField(source='entrega.status', read_only=True)
    veiculo_placa = serializers.CharField(source='entrega.veiculo.placa', default='', read_only=True)
    rota_nome = serializers.CharField(source='entrega.rota.nome', default='', read_only=True)
    motorista_nome = serializers.SerializerMethodField()
    itens_avulsos = CustoViagemItemSerializer(many=True, read_only=True)

    class Meta:
        model = CustoViagem
        fields = [
            'id', 'entrega', 'entrega_status', 'veiculo_placa', 'rota_nome',
            'motorista_nome', 'combustivel_real', 'combustivel_estimado',
            'combustivel_estimado_fonte_preco', 'combustivel_estimado_data_preco',
            'combustivel_estimado_consumo_usado', 'combustivel_estimado_preco_litro',
            'pedagios', 'diarias_motorista', 'comissao_motorista', 'outros_custos',
            'rateio_manutencao', 'rateio_depreciacao', 'rateio_seguro',
            'custo_total_real', 'km_planejado', 'km_real', 'receita_frete',
            'valor_carga_transportada', 'margem_bruta', 'margem_percentual',
            'snapshot_congelado', 'dados_incompletos', 'motivo_dados_incompletos',
            'alerta_averbacao', 'motivo_alerta_averbacao', 'alerta_baixa_ocupacao',
            'motivo_baixa_ocupacao', 'ocupacao_viagem_pct', 'itens_avulsos',
            'criado_em', 'atualizado_em'
        ]
        read_only_fields = [
            'id', 'custo_total_real', 'margem_bruta', 'margem_percentual',
            'snapshot_congelado', 'dados_incompletos', 'motivo_dados_incompletos',
            'alerta_averbacao', 'motivo_alerta_averbacao', 'alerta_baixa_ocupacao',
            'motivo_baixa_ocupacao', 'criado_em', 'atualizado_em'
        ]

    def get_motorista_nome(self, obj):
        if obj.entrega and obj.entrega.motorista:
            return obj.entrega.motorista.get_full_name() or obj.entrega.motorista.username
        return None


