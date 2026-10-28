from rest_framework import serializers
from faturamento.models import ConfiguracaoFiscalTenant, NotaFiscal, FaturaCobranca

class ConfiguracaoFiscalTenantSerializer(serializers.ModelSerializer):
    senha_certificado = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = ConfiguracaoFiscalTenant
        fields = [
            'id', 'tenant', 'cnpj_emissor', 'inscricao_estadual',
            'certificado_pfx', 'senha_certificado', 'ambiente',
            'token_api_focus', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['id', 'tenant', 'criado_em', 'atualizado_em']

    def create(self, validated_data):
        senha = validated_data.pop('senha_certificado', None)
        instance = super().create(validated_data)
        if senha:
            instance.set_senha_certificado(senha)
            instance.save(update_fields=['senha_certificado'])
        return instance

    def update(self, instance, validated_data):
        senha = validated_data.pop('senha_certificado', None)
        instance = super().update(instance, validated_data)
        if senha:
            instance.set_senha_certificado(senha)
            instance.save(update_fields=['senha_certificado'])
        return instance


class NotaFiscalSerializer(serializers.ModelSerializer):
    destinatario_nome = serializers.SerializerMethodField()

    class Meta:
        model = NotaFiscal
        fields = [
            'id', 'uuid', 'tenant', 'venda', 'fatura_estadia',
            'destinatario_nome', 'chave_acesso', 'numero_nfe', 'serie_nfe',
            'status', 'valor_total', 'xml_url', 'danfe_url',
            'motivo_rejeicao', 'data_emissao', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['id', 'uuid', 'tenant', 'chave_acesso', 'status', 'criado_em', 'atualizado_em']

    def get_destinatario_nome(self, obj):
        if obj.venda and obj.venda.cliente:
            return obj.venda.cliente.nome
        if obj.fatura_estadia and obj.fatura_estadia.cliente:
            return obj.fatura_estadia.cliente.nome
        return None


class FaturaCobrancaSerializer(serializers.ModelSerializer):
    class Meta:
        model = FaturaCobranca
        fields = [
            'id', 'uuid', 'tenant', 'venda', 'estadia',
            'gateway_id', 'status', 'valor', 'qr_code_pix',
            'linha_digitavel', 'link_pagamento', 'data_vencimento',
            'data_pagamento', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['id', 'uuid', 'tenant', 'criado_em', 'atualizado_em']
