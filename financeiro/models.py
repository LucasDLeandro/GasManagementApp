import hashlib
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.money import quantize
from core.tenancy import (
    TenantAwareModel,
    TenantQuerySet,
    TenantManager,
    get_current_tenant,
    TenantNotSet,
    get_default_tenant_pk,
)
from faturamento.crypto import encrypt_secret, decrypt_secret

UnscopedManager = models.Manager


# ==============================================================================
# ENUMS E CHOICES
# ==============================================================================

NATUREZA_SALDO_CHOICES = [
    ('DEVEDORA', 'Devedora'),
    ('CREDORA', 'Credora'),
]

TIPO_CONTA_CHOICES = [
    ('SINTETICA', 'Sintética (Totalizadora)'),
    ('ANALITICA', 'Analítica (Lançamentos)'),
]

GRUPO_FLUXO_CHOICES = [
    ('OPERACIONAL', 'Atividades Operacionais'),
    ('INVESTIMENTO', 'Atividades de Investimento'),
    ('FINANCIAMENTO', 'Atividades de Financiamento'),
    ('NAO_APLICAVEL', 'Não Aplicável'),
]

# 12 Linhas do DRE Estruturado
TIPO_DRE_CHOICES = [
    ('RECEITA_BRUTA', '1. Receita Operacional Bruta'),
    ('DEDUCOES_RECEITA', '2. Deduções da Receita Bruta e Tributos'),
    ('CPV_CSP', '3. Custos dos Produtos e Serviços Vendidos (CPV/CSP)'),
    ('DESPESAS_LOGISTICA_FROTA', '4. Despesas com Logística e Frotas'),
    ('DESPESAS_COMERCIAIS', '5. Despesas Comerciais e Vendas'),
    ('DESPESAS_ADMINISTRATIVAS', '6. Despesas Gerais e Administrativas'),
    ('PERDAS_PDD', '7. Provisão para Devedores Duvidosos (PDD)'),
    ('OUTRAS_RECEITAS_OPERACIONAIS', '8. Outras Receitas Operacionais'),
    ('OUTRAS_DESPESAS_OPERACIONAIS', '9. Outras Despesas Operacionais e Baixa de Imobilizado'),
    ('DEPRECIACAO_AMORTIZACAO', '10. Depreciação e Amortização'),
    ('RESULTADO_FINANCEIRO', '11. Resultado Financeiro Líquido'),
    ('IMPOSTOS_SOBRE_LUCRO', '12. Provisão para IRPJ e CSLL'),
]

TIPO_CONTA_FINANCEIRA_CHOICES = [
    ('CONTA_CORRENTE', 'Conta Corrente Bancária'),
    ('CONTA_INVESTIMENTO', 'Conta de Investimento'),
    ('CAIXA_ROTA_MOTORISTA', 'Caixa de Rota / Motorista'),
    ('CARTAO_COMBUSTIVEL_FROTA', 'Cartão Combustível / Frota'),
]

TIPO_MOVIMENTO_CONTA_CHOICES = [
    ('ENTRADA', 'Entrada'),
    ('SAIDA', 'Saída'),
    ('TRANSFERENCIA_ENTRADA', 'Transferência - Entrada'),
    ('TRANSFERENCIA_SAIDA', 'Transferência - Saída'),
    ('TARIFA', 'Tarifa Bancária'),
    ('RENDIMENTO', 'Rendimento de Aplicação'),
    ('AJUSTE', 'Ajuste de Saldo'),
]

TIPO_PARTIDA_CHOICES = [
    ('DEBITO', 'Débito (D)'),
    ('CREDITO', 'Crédito (C)'),
]

STATUS_PERIODO_CHOICES = [
    ('ABERTO', 'Aberto'),
    ('FECHADO', 'Fechado'),
]

TIPO_TITULO_CHOICES = [
    ('RECEBER', 'A Receber'),
    ('PAGAR', 'A Pagar'),
]

STATUS_TITULO_CHOICES = [
    ('RASCUNHO', 'Rascunho'),
    ('EM_APROVACAO', 'Em Aprovação'),
    ('ABERTO', 'Aberto'),
    ('PARCIAL', 'Parcialmente Liquidado'),
    ('LIQUIDADO', 'Liquidado'),
    ('CANCELADO', 'Cancelado'),
]

ORIGEM_TITULO_CHOICES = [
    ('VENDA', 'Venda Faturada'),
    ('FATURA_ESTADIA', 'Fatura de Estadia'),
    ('ORDEM_SERVICO_FROTA', 'Ordem de Serviço Frota'),
    ('FATURA_POSTO', 'Fatura de Posto'),
    ('COMPRA_GRANEL', 'Compra de Gás a Granel'),
    ('COMPRA_IMOBILIZADO', 'Compra de Imobilizado'),
    ('EXTRAVIO', 'Cobrança de Extravio'),
    ('SALDO_ABERTURA', 'Saldo de Abertura'),
    ('MANUAL', 'Lançamento Manual'),
]

TIPO_RETENCAO_CHOICES = [
    ('ISS', 'ISS'),
    ('IRRF', 'IRRF'),
    ('PIS', 'PIS'),
    ('COFINS', 'COFINS'),
    ('CSLL', 'CSLL'),
    ('INSS', 'INSS'),
]

STATUS_PARCELA_CHOICES = [
    ('PENDENTE', 'Pendente'),
    ('PARCIAL', 'Parcialmente Paga'),
    ('PAGA', 'Paga / Liquidada'),
    ('RENEGOCIADA', 'Renegociada'),
    ('CANCELADA', 'Cancelada'),
    ('EM_PROTESTO', 'Em Protesto'),
]

DECISAO_APROVACAO_CHOICES = [
    ('APROVADO', 'Aprovado'),
    ('REJEITADO', 'Rejeitado'),
]

STATUS_IMPORTACAO_ABERTURA_CHOICES = [
    ('SIMULACAO', 'Modo Simulação'),
    ('CONFIRMADO', 'Confirmado e Escriturado'),
    ('ESTORNADO', 'Estornado'),
]



# ==============================================================================
# 1. PLANO DE CONTAS CONTÁBIL (CORREÇÃO F-04)
# ==============================================================================

class PlanoContas(TenantAwareModel):
    """
    Plano de Contas contábil hierárquico por Tenant (Sprint 9A - Tarefa 1).
    Contas sintéticas agrupam e totalizam saldos; contas analíticas aceitam lançamentos em partidas dobradas.
    """
    codigo_estrutural = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name="Código Estrutural (ex: 1.1.1.01)"
    )
    nome = models.CharField(max_length=200, verbose_name="Nome da Conta Contábil")
    pai = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='filhos',
        verbose_name="Conta Pai"
    )
    nivel = models.PositiveSmallIntegerField(default=1, verbose_name="Nível Hierárquico")
    natureza_saldo = models.CharField(
        max_length=10,
        choices=NATUREZA_SALDO_CHOICES,
        default='DEVEDORA',
        verbose_name="Natureza do Saldo"
    )
    tipo = models.CharField(
        max_length=10,
        choices=TIPO_CONTA_CHOICES,
        default='ANALITICA',
        verbose_name="Tipo da Conta"
    )
    aceita_lancamento = models.BooleanField(
        default=True,
        verbose_name="Aceita Lançamento Direto",
        help_text="Apenas contas analíticas podem aceitar lançamentos contábeis."
    )
    tipo_dre = models.CharField(
        max_length=40,
        choices=TIPO_DRE_CHOICES,
        null=True,
        blank=True,
        verbose_name="Mapeamento DRE",
        help_text="Mapeia a conta a uma das 12 linhas da Demonstração do Resultado do Exercício."
    )
    grupo_fluxo = models.CharField(
        max_length=20,
        choices=GRUPO_FLUXO_CHOICES,
        default='NAO_APLICAVEL',
        verbose_name="Grupo de Fluxo de Caixa (DFC)"
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Plano de Contas"
        verbose_name_plural = "Planos de Contas"
        ordering = ['codigo_estrutural']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'codigo_estrutural'],
                name='uniq_plano_contas_tenant_codigo'
            )
        ]

    def __str__(self):
        return f"{self.codigo_estrutural} - {self.nome}"

    def clean(self):
        super().clean()
        if self.tipo == 'SINTETICA' and self.aceita_lancamento:
            raise ValidationError({
                'aceita_lancamento': "Contas sintéticas são totalizadoras e não podem aceitar lançamentos diretos."
            })
        if self.pai:
            if self.pai.tenant_id != self.tenant_id:
                raise ValidationError({'pai': "A conta pai deve pertencer ao mesmo Tenant."})
            if self.pai.tipo != 'SINTETICA':
                raise ValidationError({'pai': "A conta pai deve ser obrigatoriamente do tipo Sintética."})


# ==============================================================================
# 2. CENTRO DE CUSTO (CORREÇÃO F-11)
# ==============================================================================

class CentroCusto(TenantAwareModel):
    """
    Estrutura de Centros de Custo (Sprint 9A - Tarefa 3).
    Representa unidades operacionais, de negócio ou departamentos.
    Nota: Não substitui a dimensão de veículo na partida contábil.
    """
    codigo = models.CharField(max_length=30, db_index=True, verbose_name="Código do Centro de Custo")
    nome = models.CharField(max_length=150, verbose_name="Nome do Centro de Custo")
    pai = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='filhos',
        verbose_name="Centro de Custo Pai"
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Centro de Custo"
        verbose_name_plural = "Centros de Custo"
        ordering = ['codigo']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'codigo'],
                name='uniq_centro_custo_tenant_codigo'
            )
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


# ==============================================================================
# 3. FORNECEDOR E CONDIÇÃO DE PAGAMENTO (LACUNA F-14)
# ==============================================================================

class Fornecedor(TenantAwareModel):
    """
    Cadastro centralizado de fornecedores com dados bancários criptografados (Sprint 9A - Tarefa 4).
    """
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.PROTECT,
        db_index=True,
        related_name='financeiro_fornecedores',
        default=get_default_tenant_pk,
        verbose_name="Empresa (Tenant)"
    )
    razao_social = models.CharField(max_length=255, verbose_name="Razão Social / Nome")
    nome_fantasia = models.CharField(max_length=255, blank=True, default='', verbose_name="Nome Fantasia")
    documento = models.CharField(max_length=30, db_index=True, verbose_name="CNPJ ou CPF")
    tipo_pessoa = models.CharField(
        max_length=10,
        choices=[('PJ', 'Pessoa Jurídica'), ('PF', 'Pessoa Física')],
        default='PJ',
        verbose_name="Tipo de Pessoa"
    )
    email = models.EmailField(blank=True, default='', verbose_name="E-mail Financeiro/Comercial")
    telefone = models.CharField(max_length=30, blank=True, default='', verbose_name="Telefone de Contato")
    dados_bancarios = models.TextField(
        blank=True,
        default='',
        verbose_name="Dados Bancários (Criptografado)",
        help_text="Armazenado sob criptografia simétrica Fernet."
    )
    retencoes_padrao_json = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Alíquotas de Retenções Fiscais Padrão (IR, PIS, COFINS, CSLL, ISS)"
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Fornecedor"
        verbose_name_plural = "Fornecedores"
        ordering = ['razao_social']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'documento'],
                name='uniq_fornecedor_tenant_documento'
            )
        ]

    def __str__(self):
        return f"{self.razao_social} ({self.documento})"

    def set_dados_bancarios(self, texto_puro: str):
        self.dados_bancarios = encrypt_secret(texto_puro)

    @property
    def dados_bancarios_descriptografados(self) -> str:
        return decrypt_secret(self.dados_bancarios)


class CondicaoPagamento(TenantAwareModel):
    """
    Condições comerciais de pagamento a fornecedores e recebimento de clientes (Sprint 9A - Tarefa 4).
    parcelas_json define prazos em dias e percentuais (somando rigorosamente 100%).
    """
    nome = models.CharField(max_length=100, verbose_name="Descrição da Condição (ex: 30/60 Dias)")
    parcelas_json = models.JSONField(
        default=list,
        verbose_name="Lista de Parcelas (dias e percentual)"
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Condição de Pagamento"
        verbose_name_plural = "Condições de Pagamento"
        ordering = ['nome']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'nome'],
                name='uniq_condicao_pagamento_tenant_nome'
            )
        ]

    def __str__(self):
        return self.nome

    def clean(self):
        super().clean()
        if not self.parcelas_json:
            raise ValidationError({'parcelas_json': "A condição de pagamento deve possuir ao menos uma parcela."})

        soma = Decimal('0.0000')
        for idx, p in enumerate(self.parcelas_json):
            if 'dias' not in p or 'percentual' not in p:
                raise ValidationError({
                    'parcelas_json': f"Parcela {idx + 1} inválida: campos 'dias' e 'percentual' são obrigatórios."
                })
            pct = quantize(Decimal(str(p['percentual'])), 4)
            soma += pct

        if quantize(soma, 2) != Decimal('100.00'):
            raise ValidationError({
                'parcelas_json': f"A soma dos percentuais das parcelas ({soma}%) deve ser exatamente 100%."
            })


# ==============================================================================
# 4. PERÍODO CONTÁBIL (CORREÇÃO F-17)
# ==============================================================================

class PeriodoContabil(TenantAwareModel):
    """
    Controle mensal de fechamento e competência contábil e financeira (Sprint 9A - Tarefa 5).
    Períodos fechados bloqueiam lançamentos contábeis e liquidação/movimentação de contas.
    """
    ano = models.PositiveSmallIntegerField(verbose_name="Ano de Competência")
    mes = models.PositiveSmallIntegerField(verbose_name="Mês de Competência (1 a 12)")
    status = models.CharField(
        max_length=10,
        choices=STATUS_PERIODO_CHOICES,
        default='ABERTO',
        verbose_name="Status do Período"
    )
    fechado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='periodos_fechados',
        verbose_name="Fechado por"
    )
    fechado_em = models.DateTimeField(null=True, blank=True, verbose_name="Fechado em")
    reaberto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='periodos_reabertos',
        verbose_name="Reaberto por"
    )
    reaberto_em = models.DateTimeField(null=True, blank=True, verbose_name="Reaberto em")
    motivo_reabertura = models.TextField(blank=True, default='', verbose_name="Motivo Formal da Reabertura")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Período Contábil"
        verbose_name_plural = "Períodos Contábeis"
        ordering = ['-ano', '-mes']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'ano', 'mes'],
                name='uniq_periodo_contabil_tenant_ano_mes'
            )
        ]

    def __str__(self):
        return f"{self.mes:02d}/{self.ano} ({self.get_status_display()})"


# ==============================================================================
# 5. CONTAS FINANCEIRAS E MOVIMENTAÇÃO (LACUNA F-16)
# ==============================================================================

class ContaFinanceira(TenantAwareModel):
    """
    Conta bancária, caixa operacional ou aplicação financeira (Sprint 9A - Tarefa 6).
    Vinculada obrigatoriamente a uma conta contábil analítica do ativo de disponibilidades.
    """
    filial = models.ForeignKey(
        'core.Filial',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='contas_financeiras',
        verbose_name="Filial"
    )
    nome = models.CharField(max_length=150, verbose_name="Nome da Conta (ex: Itaú Matriz Movimento)")
    tipo = models.CharField(
        max_length=30,
        choices=TIPO_CONTA_FINANCEIRA_CHOICES,
        default='CONTA_CORRENTE',
        verbose_name="Tipo de Conta Financeira"
    )
    banco_codigo = models.CharField(max_length=10, blank=True, default='', verbose_name="Código do Banco (ex: 341)")
    agencia = models.CharField(max_length=20, blank=True, default='', verbose_name="Agência")
    conta = models.CharField(max_length=30, blank=True, default='', verbose_name="Número da Conta")
    saldo_inicial = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Saldo Inicial (R$)"
    )
    data_saldo_inicial = models.DateField(default=timezone.localdate, verbose_name="Data do Saldo Inicial")
    responsavel_caixa = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='caixas_financeiros_responsaveis',
        verbose_name="Responsável pelo Caixa / Motorista"
    )
    conta_contabil = models.ForeignKey(
        PlanoContas,
        on_delete=models.PROTECT,
        related_name='contas_financeiras',
        verbose_name="Conta Contábil Vinculada (Analítica)"
    )
    conciliacao_fechada_ate = models.DateField(
        null=True,
        blank=True,
        verbose_name="Conciliação Fechada Até",
        help_text="Bloqueia desfazer ou alterar conciliações em datas iguais ou anteriores."
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Conta Financeira"
        verbose_name_plural = "Contas Financeiras"
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"

    @property
    def saldo_atual(self) -> Decimal:
        """Retorna o saldo derivado da conta financeira na data atual."""
        from financeiro.services.conta import saldo_em
        return saldo_em(self)

    def clean(self):
        super().clean()
        if self.conta_contabil:
            if not self.conta_contabil.aceita_lancamento or self.conta_contabil.tipo != 'ANALITICA':
                raise ValidationError({
                    'conta_contabil': "A conta contábil vinculada à conta financeira deve ser estritamente Analítica e aceitar lançamentos."
                })
            if self.conta_contabil.tenant_id != self.tenant_id:
                raise ValidationError({
                    'conta_contabil': "A conta contábil deve pertencer ao mesmo Tenant."
                })


TIPO_IMPORTACAO_EXTRATO_CHOICES = [
    ('OFX', 'Extrato OFX'),
    ('CNAB_RETORNO', 'Arquivo de Retorno CNAB'),
]

STATUS_EXTRATO_ITEM_CHOICES = [
    ('NAO_CONCILIADO', 'Não Conciliado'),
    ('SUGERIDO', 'Sugerido'),
    ('CONCILIADO', 'Conciliado'),
    ('IGNORADO', 'Ignorado'),
]


class ImportacaoExtrato(TenantAwareModel):
    """
    Registro de importação de arquivo de extrato bancário ou retorno CNAB (Sprint 10A - Tarefa 2).
    """
    conta = models.ForeignKey(
        ContaFinanceira,
        on_delete=models.PROTECT,
        related_name='importacoes_extrato',
        verbose_name="Conta Financeira"
    )
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_IMPORTACAO_EXTRATO_CHOICES,
        default='OFX',
        verbose_name="Tipo de Importação"
    )
    arquivo = models.FileField(
        upload_to='extratos/%Y/%m/',
        verbose_name="Arquivo Importado"
    )
    hash_arquivo = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="Hash SHA-256 do Arquivo",
        help_text="Impede reimportação do mesmo arquivo pelo tenant."
    )
    periodo_ini = models.DateField(null=True, blank=True, verbose_name="Período Inicial")
    periodo_fim = models.DateField(null=True, blank=True, verbose_name="Período Final")
    saldo_final_arquivo = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Saldo Final Informado no Arquivo (R$)"
    )
    saldo_sistema_apurado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Saldo do Razão/Movimento na Data Final (R$)"
    )
    diferenca_saldo = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Diferença Apurada (R$)"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='extratos_importados',
        verbose_name="Importado por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Importação de Extrato"
        verbose_name_plural = "Importações de Extratos"
        ordering = ['-criado_em']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'hash_arquivo'],
                name='unique_importacao_extrato_hash'
            )
        ]

    def __str__(self):
        return f"Importação {self.tipo} - {self.conta.nome} ({self.criado_em.strftime('%d/%m/%Y %H:%M')})"


class ExtratoBancarioItem(TenantAwareModel):
    """
    Item individualizado do extrato bancário para conciliação (Sprint 10A - Tarefa 3).
    """
    importacao = models.ForeignKey(
        ImportacaoExtrato,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='itens',
        verbose_name="Importação de Origem"
    )
    conta = models.ForeignKey(
        ContaFinanceira,
        on_delete=models.CASCADE,
        related_name='itens_extrato',
        verbose_name="Conta Financeira"
    )
    data = models.DateField(db_index=True, verbose_name="Data do Lançamento")
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor (com sinal: negativo=débito, positivo=crédito)"
    )
    descricao = models.CharField(max_length=255, verbose_name="Descrição do Extrato")
    documento = models.CharField(max_length=50, blank=True, default='', verbose_name="Número do Documento")
    fitid = models.CharField(max_length=100, blank=True, default='', verbose_name="FITID / Identificador Único do Banco")
    hash_dedup = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        verbose_name="Hash de Desduplicação"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_EXTRATO_ITEM_CHOICES,
        default='NAO_CONCILIADO',
        db_index=True,
        verbose_name="Status da Conciliação"
    )
    movimento = models.ForeignKey(
        'MovimentoConta',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='itens_extrato_bancario',
        verbose_name="Movimento de Conta Conciliado"
    )
    score = models.PositiveSmallIntegerField(default=0, verbose_name="Score de Matching (0-100)")
    regra_aplicada = models.CharField(max_length=50, blank=True, default='', verbose_name="Regra de Conciliação Aplicada")
    motivo_sugestao = models.TextField(blank=True, default='', verbose_name="Motivo / Detalhes da Sugestão")
    parcelas_sugeridas_ids = models.JSONField(default=list, blank=True, verbose_name="IDs de Parcelas Sugeridas")
    conciliado = models.BooleanField(default=False, verbose_name="Conciliado (Legado Sprint 9A)")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Item de Extrato Bancário"
        verbose_name_plural = "Itens de Extratos Bancários"
        ordering = ['-data', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'conta', 'hash_dedup'],
                condition=~models.Q(hash_dedup=''),
                name='unique_extrato_item_dedup'
            )
        ]

    def save(self, *args, **kwargs):
        self.conciliado = (self.status == 'CONCILIADO')
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.data.strftime('%d/%m/%Y')} - {self.descricao}: R$ {self.valor} [{self.status}]"


class MovimentoConta(TenantAwareModel):
    """
    Extrato financeiro interno perpétuo da ContaFinanceira (Sprint 9A - Tarefa 7).
    O saldo de uma conta bancária é sempre derivado de MovimentoConta.
    """
    conta = models.ForeignKey(
        ContaFinanceira,
        on_delete=models.PROTECT,
        related_name='movimentos',
        verbose_name="Conta Financeira"
    )
    data_movimento = models.DateField(default=timezone.localdate, verbose_name="Data do Movimento")
    tipo = models.CharField(
        max_length=30,
        choices=TIPO_MOVIMENTO_CONTA_CHOICES,
        verbose_name="Tipo de Movimentação"
    )
    tipo_ajuste = models.CharField(
        max_length=10,
        choices=[('ENTRADA', 'Ajuste a Favor (Entrada)'), ('SAIDA', 'Ajuste a Débito (Saída)')],
        default='ENTRADA',
        blank=True,
        verbose_name="Sinal do Ajuste"
    )
    grupo_fluxo = models.CharField(
        max_length=20,
        choices=[
            ('OPERACIONAL', 'Operacional'),
            ('INVESTIMENTO', 'Investimento'),
            ('FINANCIAMENTO', 'Financiamento'),
        ],
        default='OPERACIONAL',
        db_index=True,
        verbose_name="Grupo de Fluxo de Caixa (DFC)"
    )
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor da Movimentação (R$)",
        help_text="Valor monetário estritamente positivo."
    )
    baixa = models.ForeignKey(
        'faturamento.FaturaCobranca',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='movimentos_conta',
        verbose_name="Fatura / Cobrança Baixada"
    )
    lancamento = models.ForeignKey(
        'LancamentoContabil',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='movimentos_conta',
        verbose_name="Lançamento no Razão Contábil"
    )
    extrato_item = models.ForeignKey(
        ExtratoBancarioItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='movimentos_conciliados',
        verbose_name="Item de Extrato Vinculado"
    )
    conciliado = models.BooleanField(default=False, verbose_name="Conciliado")
    historico = models.CharField(max_length=255, blank=True, default='', verbose_name="Histórico da Operação")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora de Registro")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Movimento de Conta Financeira"
        verbose_name_plural = "Movimentos de Contas Financeiras"
        ordering = ['-data_movimento', '-criado_em']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valor__gt=Decimal('0.00')),
                name='check_movimento_conta_valor_positivo'
            )
        ]

    def __str__(self):
        return f"{self.conta.nome} - {self.get_tipo_display()} R$ {self.valor} em {self.data_movimento}"


# ==============================================================================
# 6. RAZÃO CONTÁBIL, LANÇAMENTOS E PARTIDAS (CORREÇÃO F-02, F-18)
# ==============================================================================

class LancamentoContabilQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Lançamento contábil é estritamente imutável: atualizações são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Lançamento contábil é estritamente imutável: exclusões são proibidas.")


class LancamentoContabilManager(TenantManager.from_queryset(LancamentoContabilQuerySet)):
    pass


class UnscopedLancamentoContabilQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Lançamento contábil é estritamente imutável: atualizações são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Lançamento contábil é estritamente imutável: exclusões são proibidas.")


class UnscopedLancamentoContabilManager(models.Manager.from_queryset(UnscopedLancamentoContabilQuerySet)):
    pass


class LancamentoContabil(TenantAwareModel):
    """
    Cabeçalho do Lançamento no Livro Razão Contábil (Sprint 9A - Tarefa 8 / Correção F-02 e F-18).
    Totalmente imutável, sequenciado por tenant sob lock, e protegido por hash encadeado sha256.
    """
    filial = models.ForeignKey(
        'core.Filial',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='lancamentos_contabeis',
        verbose_name="Filial"
    )
    numero = models.PositiveBigIntegerField(
        db_index=True,
        verbose_name="Número Sequencial por Empresa (Gerado sob Lock)"
    )
    data_competencia = models.DateField(db_index=True, verbose_name="Data de Competência")
    data_registro = models.DateField(default=timezone.localdate, verbose_name="Data de Escrituração")
    historico = models.TextField(verbose_name="Histórico Contábil")
    origem_tipo = models.CharField(max_length=50, blank=True, default='', verbose_name="Tipo de Origem")
    origem_id = models.CharField(max_length=50, blank=True, default='', verbose_name="ID da Origem")
    lancamento_estornado = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='estornos',
        verbose_name="Lançamento Original Estornado"
    )
    hash_anterior = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name="Hash SHA-256 do Lançamento Anterior"
    )
    hash_integridade = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="Hash SHA-256 de Integridade Encadeado"
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="Usuário Escriturador"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora de Gravação")

    objects = LancamentoContabilManager()
    unscoped = UnscopedLancamentoContabilManager()

    class Meta:
        verbose_name = "Lançamento Contábil"
        verbose_name_plural = "Lançamentos Contábeis (Razão)"
        ordering = ['numero']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'numero'],
                name='uniq_lancamento_tenant_numero'
            )
        ]

    def __str__(self):
        return f"Lançamento #{self.numero} ({self.data_competencia}) - {self.historico[:50]}"

    @property
    def foi_estornado(self) -> bool:
        return self.estornos.exists()

    def save(self, *args, **kwargs):
        if not self._state.adding and not kwargs.pop('force', False):
            raise ValidationError("Lançamento contábil é imutável: alterações após gravação são estritamente proibidas.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Lançamento contábil é imutável: exclusões são estritamente proibidas.")


class PartidaContabilQuerySet(TenantQuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Partida contábil é estritamente imutável: atualizações são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Partida contábil é estritamente imutável: exclusões são proibidas.")


class PartidaContabilManager(TenantManager.from_queryset(PartidaContabilQuerySet)):
    pass


class UnscopedPartidaContabilQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().update(*args, **kwargs)
        raise ValidationError("Partida contábil é estritamente imutável: atualizações são proibidas.")

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Partida contábil é estritamente imutável: exclusões são proibidas.")


class UnscopedPartidaContabilManager(models.Manager.from_queryset(UnscopedPartidaContabilQuerySet)):
    pass


class PartidaContabil(TenantAwareModel):
    """
    Linha de débito ou crédito de um lançamento contábil (Sprint 9A - Tarefa 8).
    Contém as dimensões analíticas opcionais (centro de custo, veículo, produto/gás, cliente, entrega).
    """
    lancamento = models.ForeignKey(
        LancamentoContabil,
        on_delete=models.PROTECT,
        related_name='partidas',
        verbose_name="Lançamento Contábil"
    )
    conta_contabil = models.ForeignKey(
        PlanoContas,
        on_delete=models.PROTECT,
        related_name='partidas',
        verbose_name="Conta Contábil Analítica"
    )
    tipo_partida = models.CharField(
        max_length=10,
        choices=TIPO_PARTIDA_CHOICES,
        verbose_name="Tipo (Débito ou Crédito)"
    )
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor da Partida (R$)"
    )

    # Dimensões Analíticas Opcionais
    centro_custo = models.ForeignKey(
        CentroCusto,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='partidas',
        verbose_name="Centro de Custo"
    )
    veiculo = models.ForeignKey(
        'logistica.Veiculo',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='partidas',
        verbose_name="Veículo / Placa"
    )
    produto_gas = models.ForeignKey(
        'produtos.GasQuimico',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='partidas',
        verbose_name="Produto / Gás Químico"
    )
    cliente = models.ForeignKey(
        'clientes.Cliente',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='partidas',
        verbose_name="Cliente"
    )
    entrega = models.ForeignKey(
        'logistica.Entrega',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='partidas',
        verbose_name="Entrega"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = PartidaContabilManager()
    unscoped = UnscopedPartidaContabilManager()

    class Meta:
        verbose_name = "Partida Contábil"
        verbose_name_plural = "Partidas Contábeis"
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valor__gt=Decimal('0.00')),
                name='check_partida_valor_positivo'
            )
        ]

    def __str__(self):
        sinal = "(D)" if self.tipo_partida == 'DEBITO' else "(C)"
        return f"Lançamento #{self.lancamento.numero} {sinal} {self.conta_contabil.codigo_estrutural}: R$ {self.valor}"

    @property
    def tipo(self) -> str:
        return 'D' if self.tipo_partida == 'DEBITO' else 'C'

    def save(self, *args, **kwargs):
        if not self._state.adding and not kwargs.pop('force', False):
            raise ValidationError("Partida contábil é imutável: alterações após gravação são estritamente proibidas.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if kwargs.pop('force', False):
            return super().delete(*args, **kwargs)
        raise ValidationError("Partida contábil é imutável: exclusões são estritamente proibidas.")


# ==============================================================================
# SPRINT 9B: TÍTULOS, PARCELAS, BAIXAS, RATEIO, RETENÇÕES E APROVAÇÕES
# ==============================================================================

class ParametroFinanceiroTenant(TenantAwareModel):
    """
    Parâmetros e políticas financeiras customizadas por Tenant (Sprint 9B).
    """
    aliquota_efetiva_deducoes = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0565'),
        verbose_name="Alíquota Efetiva de Deduções Estimadas (F-19)"
    )
    percentual_multa_padrao = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0200'),
        verbose_name="Percentual de Multa de Mora Padrão"
    )
    percentual_juros_diario_padrao = models.DecimalField(
        max_digits=8,
        decimal_places=6,
        default=Decimal('0.000333'),
        verbose_name="Percentual de Juros de Mora Diário Padrão"
    )
    valor_primeira_alcada = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('1000.00'),
        verbose_name="Piso para Aprovação de Contas a Pagar"
    )
    tolerancia_quebra_caixa = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('5.00'),
        verbose_name="Tolerância de Quebra de Caixa (R$)"
    )
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Parâmetro Financeiro do Tenant"
        verbose_name_plural = "Parâmetros Financeiros dos Tenants"
        constraints = [
            models.UniqueConstraint(fields=['tenant'], name='unique_parametro_financeiro_tenant')
        ]

    def __str__(self):
        return f"Parâmetros Financeiros - {self.tenant.nome}"


class TituloFinanceiro(TenantAwareModel):
    """
    Obrigações a pagar e a receber ligadas ao Razão contábil (Sprint 9B - Tarefas 1 e 2 / Correção F-12).
    """
    filial = models.ForeignKey(
        'core.Filial',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='titulos_financeiros',
        verbose_name="Filial"
    )
    tipo = models.CharField(
        max_length=10,
        choices=TIPO_TITULO_CHOICES,
        db_index=True,
        verbose_name="Tipo (Receber / Pagar)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_TITULO_CHOICES,
        default='RASCUNHO',
        db_index=True,
        verbose_name="Status do Título"
    )
    cliente = models.ForeignKey(
        'clientes.Cliente',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='titulos_financeiros',
        verbose_name="Cliente"
    )
    fornecedor = models.ForeignKey(
        Fornecedor,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='titulos_financeiros',
        verbose_name="Fornecedor"
    )
    beneficiario_texto = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name="Beneficiário (Folha, Tributos, etc.)"
    )
    conta_gerencial = models.ForeignKey(
        PlanoContas,
        on_delete=models.PROTECT,
        related_name='titulos_gerenciais',
        verbose_name="Conta Gerencial / Contábil Analítica"
    )
    condicao_pagamento = models.ForeignKey(
        CondicaoPagamento,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='titulos_financeiros',
        verbose_name="Condição de Pagamento"
    )
    data_emissao = models.DateField(default=timezone.localdate, verbose_name="Data de Emissão")
    data_competencia = models.DateField(default=timezone.localdate, verbose_name="Data de Competência")
    valor_bruto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Bruto (R$)"
    )
    valor_retencoes = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor de Retenções (R$)"
    )
    valor_liquido_esperado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Líquido Esperado (R$)"
    )
    origem_tipo = models.CharField(
        max_length=30,
        choices=ORIGEM_TITULO_CHOICES,
        default='MANUAL',
        db_index=True,
        verbose_name="Tipo de Origem"
    )
    origem_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        db_index=True,
        verbose_name="ID do Registro de Origem"
    )
    historico = models.CharField(max_length=255, blank=True, default='', verbose_name="Histórico")
    postergavel = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Postergável em Gestão de Caixa"
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='titulos_criados',
        verbose_name="Criado por"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Título Financeiro"
        verbose_name_plural = "Títulos Financeiros"
        ordering = ['-data_emissao', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'tipo', 'origem_tipo', 'origem_id'],
                condition=~models.Q(origem_tipo='MANUAL') & models.Q(origem_id__gt=''),
                name='unique_titulo_origem_nao_manual'
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(tipo='RECEBER', cliente__isnull=False) |
                    models.Q(tipo='PAGAR', fornecedor__isnull=False) |
                    models.Q(tipo='PAGAR', beneficiario_texto__gt='')
                ),
                name='chk_titulo_partes_validas'
            ),
            models.CheckConstraint(
                condition=models.Q(valor_bruto__gt=Decimal('0.00')),
                name='chk_titulo_valor_bruto_positivo'
            ),
        ]

    def __str__(self):
        favorecido = self.cliente.nome if self.cliente else (self.fornecedor.razao_social if self.fornecedor else self.beneficiario_texto)
        return f"Título #{self.id} ({self.tipo}) - {favorecido}: R$ {self.valor_liquido_esperado} [{self.status}]"

    @property
    def valor_total(self) -> Decimal:
        return self.valor_bruto

    @property
    def valor_nominal(self) -> Decimal:
        return self.valor_liquido_esperado

    @property
    def rateios_centros_custo(self):
        return self.rateios


class RetencaoTitulo(TenantAwareModel):
    """
    Retenções tributárias incidentes sobre o título financeiro (Sprint 9B - Tarefa 3 / Correção F-13).
    """
    titulo = models.ForeignKey(
        TituloFinanceiro,
        on_delete=models.CASCADE,
        related_name='retencoes',
        verbose_name="Título Financeiro"
    )
    tipo = models.CharField(
        max_length=10,
        choices=TIPO_RETENCAO_CHOICES,
        verbose_name="Tipo de Tributo / Retenção"
    )
    base = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Base de Cálculo (R$)"
    )
    aliquota = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        verbose_name="Alíquota (%)"
    )
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor da Retenção (R$)"
    )
    conta_passivo = models.ForeignKey(
        PlanoContas,
        on_delete=models.PROTECT,
        related_name='retencoes_passivo',
        verbose_name="Conta Contábil de Passivo (Obrigações a Recolher)"
    )
    data_recolhimento = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data Prevista de Recolhimento"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Retenção de Título"
        verbose_name_plural = "Retenções de Títulos"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valor__gt=Decimal('0.00')),
                name='chk_retencao_valor_positivo'
            ),
            models.CheckConstraint(
                condition=models.Q(base__gt=Decimal('0.00')),
                name='chk_retencao_base_positiva'
            ),
        ]

    def __str__(self):
        return f"Retenção {self.tipo} ({self.aliquota}%): R$ {self.valor}"


class RateioCentroCusto(TenantAwareModel):
    """
    Rateio por centro de custo e veículo de um título financeiro (Sprint 9B - Tarefa 4).
    """
    titulo = models.ForeignKey(
        TituloFinanceiro,
        on_delete=models.CASCADE,
        related_name='rateios',
        verbose_name="Título Financeiro"
    )
    centro_custo = models.ForeignKey(
        CentroCusto,
        on_delete=models.PROTECT,
        related_name='rateios_titulos',
        verbose_name="Centro de Custo"
    )
    veiculo = models.ForeignKey(
        'logistica.Veiculo',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='rateios_titulos',
        verbose_name="Veículo"
    )
    percentual = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        verbose_name="Percentual do Rateio (%)"
    )
    valor_rateado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Rateado (R$)"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Rateio por Centro de Custo"
        verbose_name_plural = "Rateios por Centro de Custo"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valor_rateado__gt=Decimal('0.00')),
                name='chk_rateio_valor_positivo'
            ),
        ]

    def __str__(self):
        return f"Rateio {self.centro_custo.codigo} ({self.percentual}%): R$ {self.valor_rateado}"

    @property
    def valor(self) -> Decimal:
        return self.valor_rateado


class ParcelaFinanceiraQuerySet(TenantQuerySet):
    def com_status_vencida(self):
        hoje = timezone.localdate()
        return self.annotate(
            esta_vencida_db=models.Case(
                models.When(
                    saldo_em_aberto__gt=Decimal('0.00'),
                    data_vencimento__lt=hoje,
                    then=models.Value(True)
                ),
                default=models.Value(False),
                output_field=models.BooleanField()
            )
        )


class ParcelaFinanceiraManager(models.Manager.from_queryset(ParcelaFinanceiraQuerySet)):
    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant is None:
            raise TenantNotSet(
                "Isolamento Fail-Closed: Nenhuma consulta pode ser realizada em um modelo "
                "TenantAwareModel sem um Tenant ativo no contexto atual. Use tenant_context(tenant) "
                "ou .unscoped se a operação for administrativa/interna."
            )
        return super().get_queryset().filter(tenant=tenant)


class UnscopedParcelaFinanceiraManager(models.Manager.from_queryset(ParcelaFinanceiraQuerySet)):
    pass


class ParcelaFinanceira(TenantAwareModel):
    """
    Parcela individualizada de um título financeiro (Sprint 9B - Tarefa 5 / Correção F-06).
    VENCIDA não é status gravado: é a property / annotation esta_vencida.
    """
    titulo = models.ForeignKey(
        TituloFinanceiro,
        on_delete=models.CASCADE,
        related_name='parcelas',
        verbose_name="Título Financeiro"
    )
    numero_parcela = models.PositiveIntegerField(default=1, verbose_name="Número da Parcela")
    total_parcelas = models.PositiveIntegerField(default=1, verbose_name="Total de Parcelas")
    data_vencimento = models.DateField(db_index=True, verbose_name="Data de Vencimento")
    valor_nominal = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Nominal (R$)"
    )
    saldo_em_aberto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Saldo em Aberto (R$)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_PARCELA_CHOICES,
        default='PENDENTE',
        db_index=True,
        verbose_name="Status da Parcela"
    )
    nosso_numero = models.CharField(max_length=50, blank=True, default='', verbose_name="Nosso Número")
    linha_digitavel = models.CharField(max_length=100, blank=True, default='', verbose_name="Linha Digitável")
    codigo_barras = models.CharField(max_length=100, blank=True, default='', verbose_name="Código de Barras")
    payload_pix = models.TextField(blank=True, default='', verbose_name="Payload PIX Copia e Cola")
    txid_pix = models.CharField(max_length=100, blank=True, default='', verbose_name="TXID PIX")
    url_segunda_via_boleto = models.URLField(blank=True, default='', verbose_name="URL da 2ª Via do Boleto")
    gateway_charge_id = models.CharField(max_length=100, blank=True, default='', verbose_name="Charge ID no Gateway")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = ParcelaFinanceiraManager()
    unscoped = UnscopedParcelaFinanceiraManager()

    class Meta:
        verbose_name = "Parcela Financeira"
        verbose_name_plural = "Parcelas Financeiras"
        ordering = ['data_vencimento', 'numero_parcela']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'titulo', 'numero_parcela'],
                name='unique_parcela_por_titulo'
            ),
            models.CheckConstraint(
                condition=models.Q(valor_nominal__gt=Decimal('0.00')),
                name='chk_parcela_nominal_positivo'
            ),
            models.CheckConstraint(
                condition=models.Q(saldo_em_aberto__gte=Decimal('0.00')),
                name='chk_parcela_saldo_nao_negativo'
            ),
        ]

    @property
    def esta_vencida(self) -> bool:
        if self.saldo_em_aberto > Decimal('0.00') and self.data_vencimento < timezone.localdate():
            return True
        return False

    def __str__(self):
        return f"Parcela {self.numero_parcela}/{self.total_parcelas} Título #{self.titulo_id}: R$ {self.saldo_em_aberto} (Venc: {self.data_vencimento.strftime('%d/%m/%Y')})"


class BaixaParcela(TenantAwareModel):
    """
    Registro de liquidação / pagamento de uma parcela (Sprint 9B - Tarefa 6).
    Gera MovimentoConta e LançamentoContabil no Razão contábil.
    """
    parcela = models.ForeignKey(
        ParcelaFinanceira,
        on_delete=models.PROTECT,
        related_name='baixas',
        verbose_name="Parcela Baixada"
    )
    conta_financeira = models.ForeignKey(
        ContaFinanceira,
        on_delete=models.PROTECT,
        related_name='baixas',
        verbose_name="Conta Financeira (Caixa / Banco)"
    )
    data_liquidacao = models.DateField(default=timezone.localdate, verbose_name="Data da Liquidação")
    valor_principal = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Principal Baixado (R$)"
    )
    valor_juros = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Juros de Mora (R$)"
    )
    valor_multa = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Multa de Mora (R$)"
    )
    valor_desconto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Desconto Concedido / Obtido (R$)"
    )
    valor_total_movimentado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Total Efetivamente Movimentado (R$)"
    )
    valor_tarifa = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Tarifa Bancária (R$)"
    )
    comprovante = models.CharField(max_length=255, blank=True, default='', verbose_name="Comprovante / Referência")
    executado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='baixas_executadas',
        verbose_name="Executado por"
    )
    movimento_conta = models.ForeignKey(
        MovimentoConta,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='baixas_associadas',
        verbose_name="Movimento de Conta Gerado"
    )
    lancamento = models.ForeignKey(
        LancamentoContabil,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='baixas_associadas',
        verbose_name="Lançamento no Razão"
    )
    estornado = models.BooleanField(default=False, db_index=True, verbose_name="Estornado")
    estornado_em = models.DateTimeField(null=True, blank=True, verbose_name="Estornado em")
    estornado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='baixas_estornadas',
        verbose_name="Estornado por"
    )
    motivo_estorno = models.TextField(blank=True, default='', verbose_name="Motivo do Estorno")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Baixa de Parcela"
        verbose_name_plural = "Baixas de Parcelas"
        ordering = ['-data_liquidacao', '-id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valor_principal__gt=Decimal('0.00')),
                name='chk_baixa_principal_positivo'
            ),
        ]

    def __str__(self):
        status_txt = " [ESTORNADO]" if self.estornado else ""
        return f"Baixa #{self.id} Parcela #{self.parcela_id} - R$ {self.valor_total_movimentado}{status_txt}"

    @property
    def lancamento_contabil(self):
        """Compatibilidade de acesso ao lançamento contábil gerado pela baixa."""
        return self.lancamento


class Renegociacao(TenantAwareModel):
    """
    Renegociação de parcelas em atraso com consolidação de saldo e repactuação (Sprint 9B - Tarefa 7).
    """
    titulo = models.ForeignKey(
        TituloFinanceiro,
        on_delete=models.CASCADE,
        related_name='renegociacoes',
        verbose_name="Título Financeiro"
    )
    motivo = models.TextField(verbose_name="Motivo da Renegociação")
    desconto_concedido = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Desconto Extra Concedido (R$)"
    )
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='renegociacoes_aprovadas',
        verbose_name="Aprovado por"
    )
    aprovado_em = models.DateTimeField(null=True, blank=True, verbose_name="Aprovado em")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Renegociação de Título"
        verbose_name_plural = "Renegociações de Títulos"

    def __str__(self):
        return f"Renegociação #{self.id} Título #{self.titulo_id}: Desconto R$ {self.desconto_concedido}"

    @property
    def novas_parcelas(self):
        """Retorna QuerySet das novas parcelas geradas pela renegociação."""
        origem_ids = self.parcelas_origem.values_list('parcela_id', flat=True)
        return self.titulo.parcelas.exclude(id__in=origem_ids)


class RenegociacaoParcelaOrigem(TenantAwareModel):
    """
    Parcelas de origem incorporadas na renegociação (marcadas como RENEGOCIADA).
    """
    renegociacao = models.ForeignKey(
        Renegociacao,
        on_delete=models.CASCADE,
        related_name='parcelas_origem',
        verbose_name="Renegociação"
    )
    parcela = models.ForeignKey(
        ParcelaFinanceira,
        on_delete=models.PROTECT,
        related_name='renegociacoes_como_origem',
        verbose_name="Parcela de Origem"
    )
    saldo_incorporado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Saldo em Aberto Incorporado (R$)"
    )

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Parcela de Origem da Renegociação"
        verbose_name_plural = "Parcelas de Origem da Renegociação"

    def __str__(self):
        return f"Renegociação #{self.renegociacao_id} - Parcela #{self.parcela_id}: R$ {self.saldo_incorporado}"


class AlcadaAprovacao(TenantAwareModel):
    """
    Alçadas e limites para aprovação de contas a pagar (Sprint 9B - Tarefa 8 / Correção F-03).
    """
    tipo = models.CharField(
        max_length=20,
        default='PAGAR',
        choices=[('PAGAR', 'Contas a Pagar')],
        verbose_name="Tipo de Título"
    )
    valor_ate = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Limite Superior (R$)"
    )
    grupo_aprovador = models.CharField(
        max_length=100,
        default='DIRETORIA',
        verbose_name="Grupo / Nível Aprovador"
    )
    ordem = models.PositiveIntegerField(default=1, verbose_name="Ordem de Avaliação")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Alçada de Aprovação"
        verbose_name_plural = "Alçadas de Aprovação"
        ordering = ['ordem', 'valor_ate']

    def __str__(self):
        return f"Alçada #{self.ordem} ({self.tipo}): Até R$ {self.valor_ate} [{self.grupo_aprovador}]"


class AprovacaoTitulo(TenantAwareModel):
    """
    Registro formal de decisão de aprovação de título financeiro (Sprint 9B - Tarefa 8).
    """
    titulo = models.ForeignKey(
        TituloFinanceiro,
        on_delete=models.CASCADE,
        related_name='aprovacoes',
        verbose_name="Título Financeiro"
    )
    aprovador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='titulos_aprovados',
        verbose_name="Usuário Aprovador"
    )
    decisao = models.CharField(
        max_length=20,
        choices=DECISAO_APROVACAO_CHOICES,
        verbose_name="Decisão"
    )
    motivo = models.TextField(blank=True, default='', verbose_name="Motivo / Parecer")
    data_decisao = models.DateTimeField(default=timezone.now, verbose_name="Data/Hora da Decisão")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Aprovação de Título"
        verbose_name_plural = "Aprovações de Títulos"
        ordering = ['-data_decisao']

    def __str__(self):
        return f"Aprovação Título #{self.titulo_id} por {self.aprovador}: {self.decisao}"


class PendenciaContabilizacao(TenantAwareModel):
    """
    Armazenamento de falhas de processamento contábil para reprocessamento assíncrono (Sprint 9B - Tarefa 10).
    Garante que eventos de negócio de origem nunca são perdidos nem bloqueados.
    """
    evento = models.CharField(max_length=100, db_index=True, verbose_name="Nome do Evento")
    origem_id = models.CharField(max_length=100, blank=True, default='', db_index=True, verbose_name="ID de Origem")
    payload_json = models.JSONField(default=dict, blank=True, verbose_name="Payload Original do Evento")
    erro_mensagem = models.TextField(verbose_name="Mensagem de Erro / Traceback")
    tentativas = models.PositiveIntegerField(default=1, verbose_name="Tentativas")
    resolvido = models.BooleanField(default=False, db_index=True, verbose_name="Resolvido")
    resolvido_em = models.DateTimeField(null=True, blank=True, verbose_name="Resolvido em")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Pendência de Contabilização"
        verbose_name_plural = "Pendências de Contabilização"
        ordering = ['-criado_em']

    def __str__(self):
        status_txt = "RESOLVIDO" if self.resolvido else "PENDENTE"
        return f"Pendência {self.evento} (Origem: {self.origem_id}) [{status_txt}]"


class ImportacaoSaldoAbertura(TenantAwareModel):
    """
    Assistente de importação e confirmação de saldos de abertura patrimonial (Sprint 9B - Tarefa 11 / Lacuna F-15).
    """
    data_corte = models.DateField(verbose_name="Data de Corte do Balanço Inicial")
    status = models.CharField(
        max_length=20,
        choices=STATUS_IMPORTACAO_ABERTURA_CHOICES,
        default='SIMULACAO',
        db_index=True,
        verbose_name="Status da Importação"
    )
    total_ativo = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total do Ativo Inicial (R$)"
    )
    total_passivo = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total do Passivo Inicial (R$)"
    )
    total_pl_abertura = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Total PL / Saldos de Abertura (R$)"
    )
    dados_json = models.JSONField(default=dict, blank=True, verbose_name="Estrutura de Dados da Carga Inicial")
    lancamento = models.ForeignKey(
        LancamentoContabil,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='saldo_abertura_importacoes',
        verbose_name="Lançamento Contábil no Razão"
    )
    executado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='saldos_abertura_executados',
        verbose_name="Executado por"
    )
    confirmado_em = models.DateTimeField(null=True, blank=True, verbose_name="Confirmado em")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Importação de Saldo de Abertura"
        verbose_name_plural = "Importações de Saldos de Abertura"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant'],
                condition=models.Q(status='CONFIRMADO'),
                name='unique_saldo_abertura_confirmado_por_tenant'
            )
        ]

    def __str__(self):
        return f"Saldo Abertura {self.data_corte.strftime('%d/%m/%Y')} [{self.status}]: Ativo R$ {self.total_ativo} / Passivo R$ {self.total_passivo}"


# ==============================================================================
# SPRINT 9C: DESPESAS DE CAMPO, CARTÃO FROTA E CAIXA DE ROTA
# ==============================================================================

def despesa_cupom_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    ano_mes = timezone.now().strftime('%Y/%m')
    client_uuid = str(instance.client_uuid) if instance.client_uuid else uuid.uuid4().hex
    return f"despesas_campo/{tenant_id}/{ano_mes}/{client_uuid}.{ext}"


def fatura_posto_upload_path(instance, filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else 'csv'
    tenant_id = str(instance.tenant_id) if instance.tenant_id else 'default'
    ano_mes = timezone.now().strftime('%Y/%m')
    return f"faturas_posto/{tenant_id}/{ano_mes}/{uuid.uuid4().hex}.{ext}"


class PrecoReferenciaCombustivel(TenantAwareModel):
    """
    Tabela de preços de referência de combustíveis por UF, município e semana (Sprint 9C - Tarefa 3).
    Carregada periodicamente por CSV para abastecer o motor de auditoria antifraude.
    """
    uf = models.CharField(max_length=2, db_index=True, verbose_name="UF")
    municipio = models.CharField(max_length=100, db_index=True, verbose_name="Município")
    combustivel = models.CharField(max_length=30, db_index=True, verbose_name="Tipo de Combustível")
    semana = models.CharField(max_length=10, db_index=True, verbose_name="Semana de Referência (ex: 2026-W42)")
    preco_medio = models.DecimalField(max_digits=14, decimal_places=3, verbose_name="Preço Médio de Referência (R$)")
    preco_minimo = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, verbose_name="Preço Mínimo (R$)")
    preco_maximo = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, verbose_name="Preço Máximo (R$)")
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Preço de Referência de Combustível"
        verbose_name_plural = "Preços de Referência de Combustíveis"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'uf', 'municipio', 'combustivel', 'semana'],
                name='uniq_preco_ref_combustivel'
            )
        ]

    def __str__(self):
        return f"{self.municipio}/{self.uf} - {self.combustivel} ({self.semana}): R$ {self.preco_medio}"


class PreLancamentoDespesaCampo(TenantAwareModel):
    """
    Pré-lançamento de despesa de campo emitido pelo motorista via PWA (Sprint 9C - Tarefa 2 / F-05).
    Nunca cria TituloFinanceiro direto. Fica retido em conferência com análise de anomalias antifraude.
    """
    TIPO_CHOICES = [
        ('ABASTECIMENTO', 'Abastecimento'),
        ('PEDAGIO', 'Pedágio'),
        ('MANUTENCAO_EMERGENCIAL', 'Manutenção Emergencial'),
        ('OUTRO', 'Outro'),
    ]

    FORMA_PAGAMENTO_CHOICES = [
        ('CARTAO_FROTA', 'Cartão Frota'),
        ('DINHEIRO_ROTA', 'Dinheiro da Rota'),
        ('REEMBOLSO', 'Reembolso ao Motorista'),
    ]

    STATUS_CHOICES = [
        ('PENDENTE_CONFERENCIA', 'Pendente de Conferência'),
        ('APROVADO', 'Aprovado'),
        ('REJEITADO', 'Rejeitado'),
        ('CONSOLIDADO', 'Consolidado em Fatura'),
    ]

    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, db_index=True, verbose_name="Tipo de Despesa")
    veiculo = models.ForeignKey(
        'logistica.Veiculo',
        on_delete=models.PROTECT,
        related_name='pre_lancamentos_despesa',
        verbose_name="Veículo"
    )
    motorista = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='despesas_campo_criadas',
        verbose_name="Motorista Lançador"
    )
    entrega = models.ForeignKey(
        'logistica.Entrega',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='despesas_campo',
        verbose_name="Entrega / Rota Vinculada"
    )
    data_hora = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Data e Hora")
    odometro_informado = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Odômetro Informado (km)"
    )
    litros = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Litros Abastecidos"
    )
    valor_informado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Informado (R$)"
    )
    preco_litro_calculado = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Preço por Litro Calculado (R$)"
    )
    forma_pagamento = models.CharField(
        max_length=30,
        choices=FORMA_PAGAMENTO_CHOICES,
        default='CARTAO_FROTA',
        verbose_name="Forma de Pagamento"
    )
    posto_nome = models.CharField(max_length=150, blank=True, default='', verbose_name="Nome / Bandeira do Posto")
    posto_cnpj = models.CharField(max_length=20, blank=True, default='', verbose_name="CNPJ do Posto")
    foto_cupom = models.FileField(
        upload_to=despesa_cupom_upload_path,
        null=True,
        blank=True,
        verbose_name="Foto do Cupom / NF"
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, verbose_name="Latitude")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, verbose_name="Longitude")
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='PENDENTE_CONFERENCIA',
        db_index=True,
        verbose_name="Status de Conferência"
    )
    alerta_auditoria = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Possui Alertas de Auditoria"
    )
    motivos_alerta_json = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Códigos de Alertas Detectados"
    )
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='despesas_campo_aprovadas',
        verbose_name="Aprovado por"
    )
    motivo_rejeicao = models.TextField(blank=True, default='', verbose_name="Motivo da Rejeição")
    client_uuid = models.UUIDField(db_index=True, verbose_name="UUID do Cliente Offline (Idempotência)")

    lancamento_contabil = models.ForeignKey(
        LancamentoContabil,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='despesas_campo_diretas',
        verbose_name="Lançamento Contábil Direto (Caixa de Rota)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Pré-Lançamento de Despesa de Campo"
        verbose_name_plural = "Pré-Lançamentos de Despesas de Campo"
        ordering = ['-data_hora', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'client_uuid'],
                name='uniq_despesa_campo_client_uuid'
            )
        ]

    def __str__(self):
        return f"{self.tipo} - {self.veiculo.placa} ({self.data_hora.strftime('%d/%m/%Y')}) R$ {self.valor_informado} [{self.status}]"

    def clean(self):
        super().clean()
        if not self.client_uuid:
            self.client_uuid = uuid.uuid4()
        if self.tipo == 'ABASTECIMENTO' and self.litros and self.litros > Decimal('0.000'):
            self.preco_litro_calculado = quantize(self.valor_informado / self.litros, 3)

    def save(self, *args, **kwargs):
        if not self.client_uuid:
            self.client_uuid = uuid.uuid4()
        super().save(*args, **kwargs)


class FaturaConsolidadaPosto(TenantAwareModel):
    """
    Fatura consolidada de cartão de frota ou posto conveniado (Sprint 9C - Tarefa 6).
    Importada via CSV para conciliação automatizada com os pré-lançamentos de campo.
    """
    STATUS_CHOICES = [
        ('IMPORTADA', 'Importada'),
        ('CONCILIADA', 'Conciliada'),
        ('APROVADA', 'Aprovada'),
        ('CANCELADA', 'Cancelada'),
    ]

    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.PROTECT,
        related_name='faturas_posto',
        verbose_name="Fornecedor / Emissor do Cartão"
    )
    numero_fatura = models.CharField(max_length=50, verbose_name="Número da Fatura / Boleto")
    data_emissao = models.DateField(verbose_name="Data de Emissão")
    data_vencimento = models.DateField(verbose_name="Data de Vencimento")
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Total da Fatura (R$)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='IMPORTADA', db_index=True)
    arquivo_csv = models.FileField(upload_to=fatura_posto_upload_path, null=True, blank=True, verbose_name="Arquivo CSV Importado")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Fatura Consolidada de Posto/Cartão"
        verbose_name_plural = "Faturas Consolidadas de Postos/Cartões"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'fornecedor', 'numero_fatura'],
                name='uniq_fatura_posto_numero'
            )
        ]

    def __str__(self):
        return f"Fatura #{self.numero_fatura} - {self.fornecedor.razao_social} (R$ {self.valor_total})"


class ItemFaturaPosto(TenantAwareModel):
    """
    Item individual de consumo extraído da fatura consolidada (Sprint 9C - Tarefa 6).
    """
    STATUS_CASAMENTO_CHOICES = [
        ('CASADO', 'Casado com Pré-Lançamento'),
        ('SEM_PRE_LANCAMENTO', 'Sem Pré-Lançamento Correspondente (Suspeito)'),
        ('VALOR_DIVERGENTE', 'Valor ou Litros Divergentes'),
    ]

    fatura = models.ForeignKey(
        FaturaConsolidadaPosto,
        on_delete=models.CASCADE,
        related_name='itens',
        verbose_name="Fatura Consolidada"
    )
    veiculo = models.ForeignKey(
        'logistica.Veiculo',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='itens_fatura_posto',
        verbose_name="Veículo Identificado"
    )
    placa_informada = models.CharField(max_length=15, blank=True, default='', verbose_name="Placa Informada no Arquivo")
    numero_cartao = models.CharField(max_length=30, blank=True, default='', verbose_name="Número do Cartão")
    data_hora = models.DateTimeField(verbose_name="Data e Hora do Abastecimento")
    litros = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, verbose_name="Litros")
    valor = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor do Item (R$)")
    posto_nome = models.CharField(max_length=150, blank=True, default='', verbose_name="Nome do Posto")
    posto_cnpj = models.CharField(max_length=20, blank=True, default='', verbose_name="CNPJ do Posto")
    pre_lancamento = models.OneToOneField(
        PreLancamentoDespesaCampo,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='item_fatura_associado',
        verbose_name="Pré-Lançamento de Campo Casado"
    )
    status_casamento = models.CharField(
        max_length=30,
        choices=STATUS_CASAMENTO_CHOICES,
        default='SEM_PRE_LANCAMENTO',
        db_index=True,
        verbose_name="Status do Casamento"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Item de Fatura de Posto"
        verbose_name_plural = "Itens de Fatura de Posto"
        ordering = ['data_hora', 'id']

    def __str__(self):
        return f"Item {self.placa_informada} ({self.data_hora.strftime('%d/%m/%Y %H:%M')}) - R$ {self.valor} [{self.status_casamento}]"


class FechamentoCaixaRota(TenantAwareModel):
    """
    Fechamento cego e prestação de contas do dinheiro físico de rota do motorista (Sprint 9C - Tarefa 8).
    Garante que a contagem cega ocorra antes da visualização do saldo esperado.
    """
    STATUS_CHOICES = [
        ('ABERTO', 'Aberto'),
        ('CONFERIDO', 'Conferido com Sucesso'),
        ('DIVERGENTE', 'Divergente / Com Quebra'),
        ('FECHADO', 'Fechado e Transferido à Tesouraria'),
    ]

    conta_caixa = models.ForeignKey(
        ContaFinanceira,
        on_delete=models.PROTECT,
        related_name='fechamentos_caixa_rota',
        verbose_name="Conta Caixa de Rota"
    )
    motorista = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='fechamentos_caixa_rota',
        verbose_name="Motorista"
    )
    data = models.DateField(db_index=True, verbose_name="Data do Fechamento")
    saldo_esperado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Saldo Esperado em Caixa (R$)"
    )
    valor_contado_cego = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Valor Contado Cego pelo Motorista (R$)"
    )
    valor_entregue_tesouraria = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Valor Físico Entregue à Tesouraria (R$)"
    )
    diferenca = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Diferença Apurada (Contado - Esperado)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='ABERTO',
        db_index=True,
        verbose_name="Status do Fechamento"
    )
    conferido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='fechamentos_conferidos',
        verbose_name="Tesoureiro / Conferente"
    )
    transferencia = models.ForeignKey(
        MovimentoConta,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='fechamento_caixa_rota_origem',
        verbose_name="Movimento de Transferência para o Cofre"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Fechamento de Caixa de Rota"
        verbose_name_plural = "Fechamentos de Caixa de Rota"
        ordering = ['-data', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'motorista', 'data'],
                name='uniq_fechamento_caixa_motorista_data'
            )
        ]

    def __str__(self):
        return f"Caixa Rota - {self.motorista.get_full_name() or self.motorista.username} ({self.data.strftime('%d/%m/%Y')}): Status {self.status}"


class QuebraCaixa(TenantAwareModel):
    """
    Registro formal de diferença apurada acima da tolerância no fechamento de caixa de rota (Sprint 9C - Tarefa 8).
    """
    TIPO_CHOICES = [
        ('SOBRA', 'Sobra de Caixa'),
        ('FALTA', 'Falta de Caixa'),
    ]

    TRATAMENTO_CHOICES = [
        ('DESPESA_OPERACIONAL', 'Despesa Operacional (Absorvida pela Empresa)'),
        ('RECEBIVEL_FUNCIONARIO', 'Conta a Receber / Adiantamento Funcionário (Cobrada do Motorista)'),
        ('RECEITA_OPERACIONAL', 'Outras Receitas Operacionais (Sobra)'),
    ]

    fechamento = models.OneToOneField(
        FechamentoCaixaRota,
        on_delete=models.CASCADE,
        related_name='quebra_registrada',
        verbose_name="Fechamento de Caixa"
    )
    motorista = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='quebras_caixa',
        verbose_name="Motorista Responsável"
    )
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, verbose_name="Tipo da Quebra")
    valor = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor da Diferença (R$)")
    tratamento = models.CharField(max_length=30, choices=TRATAMENTO_CHOICES, verbose_name="Tratamento Contábil")
    lancamento_contabil = models.ForeignKey(
        LancamentoContabil,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='quebras_caixa',
        verbose_name="Lançamento Contábil no Razão"
    )
    observacao = models.TextField(blank=True, default='', verbose_name="Observações da Quebra")
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Quebra de Caixa"
        verbose_name_plural = "Quebras de Caixa"

    def __str__(self):
        return f"Quebra {self.tipo} R$ {self.valor} ({self.motorista.username}) [{self.tratamento}]"


class ChequeRecebido(TenantAwareModel):
    """
    Controle simplificado de cheques recebidos pelo motorista em rota (Sprint 9C - Tarefa 8).
    """
    STATUS_CHOICES = [
        ('EM_CARTEIRA', 'Em Carteira / Com o Motorista'),
        ('DEPOSITADO', 'Depositado / Entregue à Tesouraria'),
        ('COMPENSADO', 'Compensado'),
        ('DEVOLVIDO', 'Devolvido'),
    ]

    fechamento = models.ForeignKey(
        FechamentoCaixaRota,
        on_delete=models.CASCADE,
        related_name='cheques',
        verbose_name="Fechamento de Caixa"
    )
    numero = models.CharField(max_length=30, verbose_name="Número do Cheque")
    banco = models.CharField(max_length=50, verbose_name="Banco Emissor")
    valor = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor do Cheque (R$)")
    bom_para = models.DateField(null=True, blank=True, verbose_name="Data de Compensação (Bom Para)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='EM_CARTEIRA', verbose_name="Status do Cheque")
    emitente_nome = models.CharField(max_length=150, blank=True, default='', verbose_name="Nome do Emitente")
    emitente_documento = models.CharField(max_length=20, blank=True, default='', verbose_name="CPF/CNPJ do Emitente")
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Cheque Recebido em Rota"
        verbose_name_plural = "Cheques Recebidos em Rota"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'banco', 'numero'],
                name='uniq_cheque_recebido_numero'
            )
        ]

    def __str__(self):
        return f"Cheque {self.banco} #{self.numero} - R$ {self.valor} [{self.status}]"


# ==============================================================================
# SPRINT 10A: CONCILIAÇÃO BANCÁRIA, COBRANÇA REGISTRADA E RÉGUA DE COBRANÇA
# ==============================================================================

TIPO_REGRA_CONCILIACAO_CHOICES = [
    ('TARIFA', 'Tarifa Bancária'),
    ('RENDIMENTO', 'Rendimento de Aplicação'),
    ('IMPOSTO', 'Tributos e Encargos (IOF, etc.)'),
    ('OUTROS', 'Outros Lançamentos Automáticos'),
]


class RegraConciliacao(TenantAwareModel):
    """
    Regra automática para conciliação de tarifas, rendimentos e despesas bancárias rotineiras (Sprint 10A - Tarefa 5).
    """
    padrao_descricao = models.CharField(
        max_length=150,
        verbose_name="Padrão de Descrição (Texto ou Substring)",
        help_text="Texto contido na descrição do extrato (ex: 'TAR PACOTE', 'REND APLIC')"
    )
    tipo_regra = models.CharField(
        max_length=30,
        choices=TIPO_REGRA_CONCILIACAO_CHOICES,
        default='TARIFA',
        verbose_name="Tipo da Regra"
    )
    conta_contabil = models.ForeignKey(
        PlanoContas,
        on_delete=models.PROTECT,
        related_name='regras_conciliacao',
        verbose_name="Conta Contábil de Contrapartida"
    )
    centro_custo = models.ForeignKey(
        CentroCusto,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='regras_conciliacao',
        verbose_name="Centro de Custo Padrão"
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Regra de Conciliação Bancária"
        verbose_name_plural = "Regras de Conciliação Bancária"
        ordering = ['padrao_descricao']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'padrao_descricao'],
                name='unique_regra_conciliacao_padrao'
            )
        ]

    def __str__(self):
        return f"Regra [{self.tipo_regra}]: '{self.padrao_descricao}' -> {self.conta_contabil.nome}"


ADAPTADOR_COBRANCA_CHOICES = [
    ('GATEWAY_PSP', 'Gateway PSP (Asaas)'),
    ('ARQUIVO_CNAB', 'Arquivo CNAB 240/400 (Itaú)'),
]


class ConfiguracaoCobranca(TenantAwareModel):
    """
    Configuração de emissão de cobrança registrada (Boleto / PIX) por conta financeira (Sprint 10A - Tarefa 7).
    """
    conta_financeira = models.OneToOneField(
        ContaFinanceira,
        on_delete=models.CASCADE,
        related_name='configuracao_cobranca',
        verbose_name="Conta Financeira"
    )
    adaptador = models.CharField(
        max_length=30,
        choices=ADAPTADOR_COBRANCA_CHOICES,
        default='GATEWAY_PSP',
        verbose_name="Adaptador de Cobrança"
    )
    carteira = models.CharField(max_length=20, blank=True, default='109', verbose_name="Carteira de Cobrança")
    instrucoes_boleto = models.TextField(
        blank=True,
        default='Sr. Caixa, não receber após 30 dias do vencimento. Cobrar juros e multa conforme previsto.',
        verbose_name="Instruções Impressas no Boleto"
    )
    percentual_multa = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0200'),
        verbose_name="Percentual de Multa por Atraso (%)"
    )
    percentual_juros_mensal = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0100'),
        verbose_name="Percentual de Juros de Mora Mensal (%)"
    )
    dias_protesto = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Dias para Notificação de Protesto",
        help_text="0 = Sem protesto automático."
    )
    api_key = models.TextField(blank=True, default='', verbose_name="Chave de API do PSP")
    webhook_secret = models.CharField(max_length=150, blank=True, default='', verbose_name="Segredo do Webhook (Assinatura HMAC)")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Configuração de Cobrança"
        verbose_name_plural = "Configurações de Cobrança"

    def __str__(self):
        return f"Cobrança {self.get_adaptador_display()} - {self.conta_financeira.nome}"


CANAL_COBRANCA_CHOICES = [
    ('EMAIL', 'E-mail'),
    ('WHATSAPP', 'WhatsApp'),
]


class ReguaCobranca(TenantAwareModel):
    """
    Etapas da régua de cobrança preventiva e reativa (Sprint 10A - Tarefa 8).
    Ex: D-3, D0, D+3, D+7, D+15.
    """
    nome = models.CharField(max_length=100, verbose_name="Nome da Etapa")
    dias_offset = models.IntegerField(
        verbose_name="Dias de Deslocamento do Vencimento",
        help_text="Negativo antes do vencimento (ex: -3 = D-3), 0 no vencimento (D0), positivo após (ex: +3 = D+3)."
    )
    canal = models.CharField(
        max_length=20,
        choices=CANAL_COBRANCA_CHOICES,
        default='EMAIL',
        verbose_name="Canal de Envio"
    )
    template_assunto = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name="Assunto do E-mail (quando canal E-mail)"
    )
    template_corpo = models.TextField(
        verbose_name="Modelo de Mensagem",
        help_text="Variáveis suportadas: {cliente_nome}, {valor}, {vencimento}, {linha_digitavel}, {pix_copia_cola}, {link_segunda_via}"
    )
    template_externo_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name="ID do Template Aprovado (Meta / WhatsApp BSP)"
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Etapa de Régua de Cobrança"
        verbose_name_plural = "Etapas de Régua de Cobrança"
        ordering = ['dias_offset']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'dias_offset', 'canal'],
                name='unique_regua_cobranca_offset_canal'
            )
        ]

    def __str__(self):
        sinal = f"+{self.dias_offset}" if self.dias_offset > 0 else str(self.dias_offset)
        return f"Régua D{sinal} [{self.get_canal_display()}]: {self.nome}"


STATUS_ENVIO_COBRANCA_CHOICES = [
    ('SUCESSO', 'Enviado com Sucesso'),
    ('FALHA', 'Falha no Envio'),
    ('BLOQUEADO', 'Bloqueado (Sem Consentimento / Limite Excedido)'),
]


class EnvioCobranca(TenantAwareModel):
    """
    Log de auditoria e controle de idempotência de notificações enviadas pela régua (Sprint 10A - Tarefa 8).
    """
    parcela = models.ForeignKey(
        ParcelaFinanceira,
        on_delete=models.CASCADE,
        related_name='envios_cobranca',
        verbose_name="Parcela Notificada"
    )
    regua = models.ForeignKey(
        ReguaCobranca,
        on_delete=models.PROTECT,
        related_name='envios',
        verbose_name="Etapa da Régua"
    )
    data_envio = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora de Envio")
    canal = models.CharField(max_length=20, choices=CANAL_COBRANCA_CHOICES, verbose_name="Canal Utilizado")
    destinatario = models.CharField(max_length=150, verbose_name="Destinatário (E-mail ou Telefone)")
    status = models.CharField(
        max_length=20,
        choices=STATUS_ENVIO_COBRANCA_CHOICES,
        default='SUCESSO',
        verbose_name="Status do Envio"
    )
    idempotency_key = models.CharField(
        max_length=150,
        db_index=True,
        verbose_name="Chave de Idempotência (ex: regua_10_parc_25_20261022)"
    )
    detalhes = models.TextField(blank=True, default='', verbose_name="Detalhes da Resposta / Motivo Bloqueio")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Log de Envio de Cobrança"
        verbose_name_plural = "Logs de Envios de Cobrança"
        ordering = ['-data_envio']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'idempotency_key'],
                name='unique_envio_cobranca_idempotency'
            )
        ]

    def __str__(self):
        return f"Envio {self.canal} #{self.id} - Parcela #{self.parcela_id} [{self.status}]"


class ConsentimentoContato(TenantAwareModel):
    """
    Registro de consentimento explícito e opt-out LGPD para cobrança e comunicações (Sprint 10A - Tarefa 8).
    """
    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.CASCADE,
        related_name='consentimentos_contato',
        verbose_name="Cliente"
    )
    canal = models.CharField(
        max_length=20,
        choices=CANAL_COBRANCA_CHOICES,
        verbose_name="Canal Autorizado"
    )
    consentiu_em = models.DateTimeField(default=timezone.now, verbose_name="Data do Consentimento")
    origem = models.CharField(
        max_length=100,
        default='CONTRATO_ADESAO',
        verbose_name="Origem do Consentimento (ex: CONTRATO, PORTAL, SAC)"
    )
    revogado_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data da Revogação (Opt-out)"
    )

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Consentimento de Contato (LGPD)"
        verbose_name_plural = "Consentimentos de Contato (LGPD)"
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'cliente', 'canal'],
                name='unique_consentimento_cliente_canal'
            )
        ]

    def __str__(self):
        status_txt = "REVOGADO" if self.revogado_em else "ATIVO"
        return f"Consentimento {self.canal} - {self.cliente.nome} [{status_txt}]"

    @property
    def esta_ativo(self) -> bool:
        return self.revogado_em is None


# ==============================================================================
# SPRINT 10B: DEPRECIAÇÃO, DRE, ORÇAMENTO, PDD E SNAPSHOTS
# ==============================================================================

TIPO_ALVO_DEPRECIACAO_CHOICES = [
    ('LOTE_CILINDROS', 'Lote de Cilindros'),
    ('CILINDRO_AVULSO', 'Cilindro Avulso'),
    ('ATIVO_IMOBILIZADO', 'Ativo Imobilizado Geral'),
]


class DepreciacaoMensal(TenantAwareModel):
    """
    Ledger de Depreciação Mensal por Ativo/Lote (Sprint 10B - Tarefa 1).
    Registra a quota mensal de depreciação linear, o valor contábil líquido após
    a depreciação e a referência ao lançamento agregado escriturado no Razão.
    """
    periodo = models.DateField(db_index=True, verbose_name="Período de Competência (1º dia do mês)")
    tipo_alvo = models.CharField(max_length=30, choices=TIPO_ALVO_DEPRECIACAO_CHOICES, db_index=True, verbose_name="Tipo de Alvo")
    alvo_id = models.CharField(max_length=100, db_index=True, verbose_name="ID do Alvo")
    quota = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Quota Mensal Depreciada (R$)")
    depreciacao_acumulada_apos = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Depreciação Acumulada Após Quota (R$)")
    valor_contabil_apos = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Contábil Líquido Após Quota (R$)")
    lancamento = models.ForeignKey(
        LancamentoContabil,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='depreciacoes_mensais',
        verbose_name="Lançamento Contábil no Razão"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Depreciação Mensal (Ledger)"
        verbose_name_plural = "Depreciações Mensais (Ledger)"
        ordering = ['-periodo', 'tipo_alvo', 'alvo_id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'periodo', 'tipo_alvo', 'alvo_id'],
                name='unique_depreciacao_mensal_alvo_periodo'
            )
        ]

    def __str__(self):
        return f"Depreciação {self.periodo.strftime('%m/%Y')} - {self.tipo_alvo} #{self.alvo_id} (R$ {self.quota})"


class RevisaoVidaUtil(TenantAwareModel):
    """
    Revisão de Vida Útil e Valor Residual de Ativos Imobilizados (CPC 23 / Prospectiva) (Sprint 10B - Tarefa 3).
    Quotas futuras = (valor contábil líquido - residual) / meses restantes; o passado não muda.
    """
    tipo_alvo = models.CharField(max_length=30, choices=TIPO_ALVO_DEPRECIACAO_CHOICES, db_index=True, verbose_name="Tipo de Alvo")
    alvo_id = models.CharField(max_length=100, db_index=True, verbose_name="ID do Alvo")
    data_revisao = models.DateField(verbose_name="Data da Revisão")
    nova_vida_meses = models.PositiveIntegerField(verbose_name="Nova Vida Útil Restante (Meses)")
    novo_valor_residual = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Novo Valor Residual (R$)")
    motivo = models.TextField(verbose_name="Motivo e Justificativa Técnica/Econômica")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='revisoes_vida_util',
        verbose_name="Responsável pela Revisão"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Revisão de Vida Útil (CPC 23)"
        verbose_name_plural = "Revisões de Vida Útil (CPC 23)"
        ordering = ['-data_revisao']

    def __str__(self):
        return f"Revisão Vida Útil {self.tipo_alvo} #{self.alvo_id} em {self.data_revisao} ({self.nova_vida_meses} meses)"


class SaldoMensalConta(TenantAwareModel):
    """
    Snapshot de Saldos Mensais por Conta e Dimensões Analíticas (Sprint 10B - Tarefa 6).
    Atualizado deterministicamente dentro da mesma transação de cada lancar(), viabilizando
    consultas analíticas de DRE e Balancetes de alta performance (p95 < 2s).
    """
    ano_mes = models.CharField(max_length=7, db_index=True, verbose_name="Ano/Mês de Competência (ex: 2026-01)")
    conta = models.ForeignKey(
        PlanoContas,
        on_delete=models.CASCADE,
        related_name='saldos_mensais',
        verbose_name="Conta Contábil"
    )
    centro_custo = models.ForeignKey(
        CentroCusto,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='saldos_mensais',
        verbose_name="Centro de Custo"
    )
    veiculo = models.ForeignKey(
        'logistica.Veiculo',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='saldos_mensais',
        verbose_name="Veículo"
    )
    filial = models.ForeignKey(
        'core.Filial',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='saldos_mensais',
        verbose_name="Filial"
    )
    produto_gas = models.ForeignKey(
        'produtos.GasQuimico',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='saldos_mensais',
        verbose_name="Produto / Gás Químico"
    )
    debitos = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Total Débitos no Mês (R$)")
    creditos = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Total Créditos no Mês (R$)")
    saldo_final = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Saldo Final Acumulado (R$)")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Snapshot de Saldo Mensal"
        verbose_name_plural = "Snapshots de Saldos Mensais"
        ordering = ['ano_mes', 'conta']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'ano_mes', 'conta', 'centro_custo', 'veiculo', 'filial', 'produto_gas'],
                name='unique_saldo_mensal_conta_dimensoes'
            )
        ]
        indexes = [
            models.Index(fields=['tenant', 'ano_mes', 'conta'], name='idx_saldo_mensal_periodo_cta'),
        ]

    def __str__(self):
        return f"Saldo {self.ano_mes} - {self.conta.codigo_estrutural} [D: {self.debitos} | C: {self.creditos}]"


REGIME_TRIBUTARIO_CHOICES = [
    ('LUCRO_REAL', 'Lucro Real'),
    ('LUCRO_PRESUMIDO', 'Lucro Presumido'),
    ('SIMPLES_NACIONAL', 'Simples Nacional'),
]


class ParametroTributarioLucro(TenantAwareModel):
    """
    Parâmetros Fiscais de Provisão de IRPJ e CSLL (Sprint 10B - Tarefa 8).
    Define alíquotas, percentuais de presunção e contas para cálculo mensal automático.
    """
    regime = models.CharField(max_length=20, choices=REGIME_TRIBUTARIO_CHOICES, default='LUCRO_PRESUMIDO', verbose_name="Regime de Tributação")
    aliquota_irpj = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0.1500'), verbose_name="Alíquota Básica IRPJ (padrão 15%)")
    aliquota_adicional_irpj = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0.1000'), verbose_name="Alíquota Adicional IRPJ (padrão 10%)")
    teto_isencao_adicional_mensal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('20000.00'), verbose_name="Teto Mensal Isenção Adicional IRPJ (R$)")
    aliquota_csll = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0.0900'), verbose_name="Alíquota CSLL (padrão 9%)")
    presuncao_irpj = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0.0800'), verbose_name="Percentual de Presunção IRPJ (Comércio/GLP: 8%)")
    presuncao_csll = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0.1200'), verbose_name="Percentual de Presunção CSLL (Comércio/GLP: 12%)")
    conta_despesa_irpj = models.ForeignKey(PlanoContas, null=True, blank=True, on_delete=models.SET_NULL, related_name='param_tributario_despesa_irpj', verbose_name="Conta Despesa IRPJ")
    conta_despesa_csll = models.ForeignKey(PlanoContas, null=True, blank=True, on_delete=models.SET_NULL, related_name='param_tributario_despesa_csll', verbose_name="Conta Despesa CSLL")
    conta_passivo_irpj = models.ForeignKey(PlanoContas, null=True, blank=True, on_delete=models.SET_NULL, related_name='param_tributario_passivo_irpj', verbose_name="Conta Passivo IRPJ a Recolher")
    conta_passivo_csll = models.ForeignKey(PlanoContas, null=True, blank=True, on_delete=models.SET_NULL, related_name='param_tributario_passivo_csll', verbose_name="Conta Passivo CSLL a Recolher")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Parâmetro Tributário de Lucro (IRPJ/CSLL)"
        verbose_name_plural = "Parâmetros Tributários de Lucro (IRPJ/CSLL)"

    def __str__(self):
        return f"Parâmetro Tributário [{self.get_regime_display()}]"


STATUS_ORCAMENTO_CHOICES = [
    ('RASCUNHO', 'Rascunho'),
    ('APROVADO', 'Aprovado'),
]


class Orcamento(TenantAwareModel):
    """
    Plano Orçamentário Anual do Tenant (Sprint 10B - Tarefa 9).
    Permite comparar os saldos realizados com as projeções analíticas no DRE.
    """
    ano = models.PositiveSmallIntegerField(verbose_name="Ano de Exercício")
    nome = models.CharField(max_length=150, verbose_name="Nome / Descrição do Orçamento")
    status = models.CharField(max_length=20, choices=STATUS_ORCAMENTO_CHOICES, default='RASCUNHO', verbose_name="Status")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='orcamentos_criados', verbose_name="Criado por")
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='orcamentos_aprovados', verbose_name="Aprovado por")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Orçamento Anual"
        verbose_name_plural = "Orçamentos Anuais"
        ordering = ['-ano', 'nome']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'ano', 'nome'],
                name='unique_orcamento_tenant_ano_nome'
            )
        ]

    def __str__(self):
        return f"Orçamento {self.ano} - {self.nome} [{self.get_status_display()}]"


class OrcamentoMensalConta(TenantAwareModel):
    """
    Item Mensal Orçado por Conta Contábil e Dimensões (Sprint 10B - Tarefa 9).
    """
    orcamento = models.ForeignKey(
        Orcamento,
        on_delete=models.CASCADE,
        related_name='itens',
        verbose_name="Orçamento"
    )
    mes = models.PositiveSmallIntegerField(verbose_name="Mês (1 a 12)")
    conta = models.ForeignKey(
        PlanoContas,
        on_delete=models.PROTECT,
        related_name='orcamentos_mensais',
        verbose_name="Conta Contábil"
    )
    centro_custo = models.ForeignKey(
        CentroCusto,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="Centro de Custo"
    )
    filial = models.ForeignKey(
        'core.Filial',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="Filial"
    )
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor Orçado (R$)")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Orçamento Mensal por Conta"
        verbose_name_plural = "Orçamentos Mensais por Conta"
        ordering = ['mes', 'conta']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'orcamento', 'mes', 'conta', 'centro_custo', 'filial'],
                name='unique_orcamento_mensal_conta_item'
            )
        ]

    def __str__(self):
        return f"Orçado Mês {self.mes:02d} - {self.conta.codigo_estrutural}: R$ {self.valor}"


class ParametroPDD(TenantAwareModel):
    """
    Parâmetro e Faixa de Atraso para Provisão de Devedores Duvidosos (PDD) (Sprint 10B - Tarefa 10).
    Define o percentual de perda estimada com base nos dias de vencimento.
    """
    dias_atraso_min = models.PositiveIntegerField(verbose_name="Dias de Atraso Mínimo")
    dias_atraso_max = models.PositiveIntegerField(verbose_name="Dias de Atraso Máximo")
    percentual_provisao = models.DecimalField(max_digits=6, decimal_places=4, verbose_name="Percentual de Provisão")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Parâmetro de PDD"
        verbose_name_plural = "Parâmetros de PDD"
        ordering = ['dias_atraso_min']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'dias_atraso_min', 'dias_atraso_max'],
                name='unique_parametro_pdd_faixa'
            )
        ]

    def __str__(self):
        return f"PDD {self.dias_atraso_min} a {self.dias_atraso_max} dias: {self.percentual_provisao * 100:.2f}%"


STATUS_LANCAMENTO_MANUAL_CHOICES = [
    ('PENDENTE', 'Pendente de Aprovação'),
    ('APROVADO', 'Aprovado e Escriturado'),
    ('REJEITADO', 'Rejeitado'),
]


class LancamentoManualPendente(TenantAwareModel):
    """
    Solicitação de Lançamento Manual / Provisão com Alçada de Aprovação (Sprint 10B - Tarefa 11).
    Partidas dobradas validadas que aguardam aprovação de alçada antes da escrituração definitiva.
    """
    data_competencia = models.DateField(verbose_name="Data de Competência")
    historico = models.CharField(max_length=255, verbose_name="Histórico Contábil")
    partidas_json = models.JSONField(verbose_name="Partidas Dobradas (JSON)")
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Total dos Débitos/Créditos (R$)")
    status = models.CharField(max_length=20, choices=STATUS_LANCAMENTO_MANUAL_CHOICES, default='PENDENTE', verbose_name="Status")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='lancamentos_manuais_criados', verbose_name="Criado por")
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='lancamentos_manuais_aprovados', verbose_name="Aprovado por")
    aprovado_em = models.DateTimeField(null=True, blank=True, verbose_name="Aprovado em")
    lancamento = models.ForeignKey(LancamentoContabil, null=True, blank=True, on_delete=models.SET_NULL, related_name='lancamentos_manuais_origem', verbose_name="Lançamento Escriturado")
    motivo_rejeicao = models.TextField(blank=True, default='', verbose_name="Motivo de Rejeição")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Lançamento Manual Pendente"
        verbose_name_plural = "Lançamentos Manuais Pendentes"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Lançamento Manual R$ {self.valor_total} ({self.data_competencia}) - [{self.get_status_display()}]"


# ==============================================================================
# SPRINT 10C: FLUXO DE CAIXA, CENÁRIOS, ALERTA E GESTÃO
# ==============================================================================

class PerfilPagamentoCliente(TenantAwareModel):
    """
    Perfil estatístico de comportamento de pagamento do cliente (Sprint 10C - Tarefa 2 / Correção F-22).
    Recalculado periodicamente com base nas baixas dos últimos 12 meses.
    Clientes com amostra_n < 5 utilizam o perfil global do tenant.
    """
    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.CASCADE,
        related_name='perfil_pagamento',
        verbose_name="Cliente"
    )
    atraso_medio_dias = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Atraso Médio Histórico (Dias)"
    )
    p80_atraso_dias = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Percentil 80 de Atraso (Dias)"
    )
    taxa_inadimplencia = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0000'),
        verbose_name="Taxa de Inadimplência Histórica (0.0000 a 1.0000)"
    )
    amostra_n = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantidade de Baixas Analisadas (12 Meses)"
    )
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Perfil de Pagamento do Cliente"
        verbose_name_plural = "Perfis de Pagamento de Clientes"
        ordering = ['-atualizado_em']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'cliente'],
                name='uniq_perfil_pagamento_tenant_cliente'
            )
        ]

    def __str__(self):
        return f"Perfil {self.cliente.nome}: Atraso Médio {self.atraso_medio_dias}d (P80 {self.p80_atraso_dias}d, Inadimplência {self.taxa_inadimplencia * 100:.2f}%)"


class RecorrenciaFinanceira(TenantAwareModel):
    """
    Obrigações e direitos financeiros recorrentes (Sprint 10C - Tarefa 2).
    Utilizado na projeção de fluxo de caixa para folha, aluguel, tributos e financiamentos.
    """
    TIPO_CHOICES = [
        ('PAGAR', 'Pagar'),
        ('RECEBER', 'Receber'),
    ]

    descricao = models.CharField(max_length=255, verbose_name="Descrição da Recorrência")
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='PAGAR', verbose_name="Tipo de Operação")
    valor = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Valor Recorrente (R$)")
    dia_do_mes = models.PositiveSmallIntegerField(verbose_name="Dia do Mês de Vencimento (1 a 31)")
    conta = models.ForeignKey(
        ContaFinanceira,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='recorrencias',
        verbose_name="Conta Financeira Prevista"
    )
    centro_custo = models.ForeignKey(
        CentroCusto,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='recorrencias',
        verbose_name="Centro de Custo"
    )
    inicio = models.DateField(verbose_name="Data de Início da Recorrência")
    fim = models.DateField(null=True, blank=True, verbose_name="Data de Fim da Recorrência (Opcional)")
    ativo = models.BooleanField(default=True, verbose_name="Recorrência Ativa")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Recorrência Financeira"
        verbose_name_plural = "Recorrências Financeiras"
        ordering = ['dia_do_mes', 'descricao']

    def __str__(self):
        return f"{self.descricao} ({self.tipo} R$ {self.valor} dia {self.dia_do_mes})"


class AlertaCaixa(TenantAwareModel):
    """
    Histórico e registro de alertas de ruptura de caixa projetada (Sprint 10C - Tarefa 4).
    Armazena o diagnóstico e sugestões de antecipação / postergação.
    """
    data_alerta = models.DateField(default=timezone.localdate, db_index=True, verbose_name="Data do Alerta")
    horizonte_dias = models.PositiveIntegerField(default=30, verbose_name="Horizonte Projetado (Dias)")
    saldo_minimo_configurado = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Saldo Mínimo Configurado (R$)")
    menor_saldo_projetado = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Menor Saldo Projetado (R$)")
    data_menor_saldo = models.DateField(verbose_name="Data do Menor Saldo Projetado")
    resolvido = models.BooleanField(default=False, verbose_name="Resolvido")
    detalhes_json = models.JSONField(default=dict, blank=True, verbose_name="Detalhes / Recomendações")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Alerta de Caixa"
        verbose_name_plural = "Alertas de Caixa"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Alerta Caixa {self.data_alerta}: Menor Saldo R$ {self.menor_saldo_projetado} em {self.data_menor_saldo}"


class ParametroGestaoTenant(TenantAwareModel):
    """
    Parâmetros estratégicos de gestão e tesouraria por Tenant (Sprint 10C - Tarefas 3, 4, 5 e 7).
    """
    POLITICA_RECEITA_VEICULO_CHOICES = [
        ('CONTRIBUICAO_COMERCIAL', 'Contribuição Comercial da Entrega'),
        ('CONTRIBUICAO_FRETE', 'Contribuição de Frete'),
    ]

    saldo_minimo_caixa = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('10000.00'),
        verbose_name="Saldo Mínimo de Caixa Desejado (R$)"
    )
    tma_mensal = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('0.0150'),
        verbose_name="Taxa Mínima de Atratividade Mensal (TMA)"
    )
    politica_receita_veiculo = models.CharField(
        max_length=30,
        choices=POLITICA_RECEITA_VEICULO_CHOICES,
        default='CONTRIBUICAO_COMERCIAL',
        verbose_name="Política de Receita de Veículo"
    )
    fator_majoracao_pessimista = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal('1.5000'),
        verbose_name="Fator de Majoração do Cenário Pessimista (ex: 1.5 = +50%)"
    )
    horizonte_alerta_dias = models.PositiveIntegerField(
        default=30,
        verbose_name="Horizonte de Dias para Disparo de Alerta de Caixa"
    )

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Parâmetro de Gestão do Tenant"
        verbose_name_plural = "Parâmetros de Gestão dos Tenants"
        constraints = [
            models.UniqueConstraint(fields=['tenant'], name='uniq_parametro_gestao_tenant')
        ]

    def __str__(self):
        return f"Parâmetros de Gestão - {self.tenant.nome_fantasia}"


# ==============================================================================
# 22. POLÍTICA DE CRÉDITO, LIMITES E PROMESSA DE PAGAMENTO (SPRINT 11C)
# ==============================================================================

class ParametroCredito(TenantAwareModel):
    """
    Parâmetros de política de crédito comercial por Tenant (Sprint 11C - Tarefa 1).
    Controla tolerância para bloqueio de inadimplência, limites e segurança assistencial.
    """
    POLITICA_MEDICINAL_CHOICES = [
        ('ALERTAR_E_ESCALAR', 'Alertar e Escalar à Gerência (Padrão Assistencial - Sem Bloqueio)'),
        ('BLOQUEAR_SEMPRE', 'Bloquear Sempre (Endurecimento Formal Auditado)'),
    ]

    dias_tolerancia = models.PositiveIntegerField(
        default=5,
        verbose_name="Dias de Tolerância de Atraso (X da v2.0)"
    )
    valor_minimo_considerado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('50.00'),
        verbose_name="Valor Mínimo de Dívida Considerado para Bloqueio (R$)"
    )
    limite_credito_padrao = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('5000.00'),
        verbose_name="Limite de Crédito Padrão para Clientes (R$)"
    )
    max_dias_promessa = models.PositiveIntegerField(
        default=30,
        verbose_name="Máximo de Dias para Data da Promessa"
    )
    max_promessas_ativas = models.PositiveIntegerField(
        default=2,
        verbose_name="Máximo de Promessas Ativas Simultâneas por Cliente"
    )
    politica_gas_medicinal = models.CharField(
        max_length=30,
        choices=POLITICA_MEDICINAL_CHOICES,
        default='ALERTAR_E_ESCALAR',
        verbose_name="Política de Crédito para Gás Medicinal / Hospitalar"
    )

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Parâmetro de Crédito do Tenant"
        verbose_name_plural = "Parâmetros de Crédito dos Tenants"
        constraints = [
            models.UniqueConstraint(fields=['tenant'], name='unique_tenant_parametro_credito')
        ]

    def __str__(self):
        return f"Parâmetro de Crédito - {self.tenant.nome_fantasia} (Tolerância: {self.dias_tolerancia}d)"


class LimiteCreditoCliente(TenantAwareModel):
    """
    Limite de crédito individualizado por cliente com vigência (Sprint 11C - Tarefa 1).
    Sobrepõe o limite_credito_padrao do tenant enquanto estiver ativo e vigente.
    """
    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.CASCADE,
        related_name='limites_credito_cliente',
        verbose_name="Cliente"
    )
    limite = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Limite de Crédito Individual (R$)"
    )
    vigencia_inicio = models.DateField(
        default=timezone.localdate,
        verbose_name="Início da Vigência"
    )
    vigencia_fim = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fim da Vigência"
    )
    observacao = models.TextField(
        blank=True,
        default='',
        verbose_name="Observações / Justificativa do Limite"
    )
    ativo = models.BooleanField(
        default=True,
        verbose_name="Ativo"
    )

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Limite de Crédito do Cliente"
        verbose_name_plural = "Limites de Crédito dos Clientes"
        ordering = ['-vigencia_inicio', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'cliente'],
                condition=models.Q(ativo=True),
                name='unique_tenant_cliente_limite_credito_ativo'
            )
        ]

    def __str__(self):
        return f"Limite {self.cliente.nome}: R$ {self.limite} [{'ATIVO' if self.ativo else 'INATIVO'}]"


class PromessaPagamento(TenantAwareModel):
    """
    Registro de acordo de promessa de pagamento para parcelas vencidas (Sprint 11C - Tarefa 2).
    A promessa ativa suspende o bloqueio comercial e a régua de cobrança automática.
    """
    STATUS_CHOICES = [
        ('ATIVA', 'Ativa'),
        ('CUMPRIDA', 'Cumprida / Liquidada'),
        ('QUEBRADA', 'Quebrada / Vencida sem Quitação'),
        ('CANCELADA', 'Cancelada'),
    ]

    cliente = models.ForeignKey(
        'clientes.Cliente',
        on_delete=models.CASCADE,
        related_name='promessas_pagamento',
        verbose_name="Cliente"
    )
    parcelas = models.ManyToManyField(
        ParcelaFinanceira,
        related_name='promessas_pagamento',
        blank=True,
        verbose_name="Parcelas Vinculadas"
    )
    data_promessa = models.DateField(
        verbose_name="Data Prometida de Pagamento"
    )
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor Prometido (R$)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='ATIVA',
        db_index=True,
        verbose_name="Status da Promessa"
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='promessas_pagamento_criadas',
        verbose_name="Registrado por"
    )
    observacao = models.TextField(
        blank=True,
        default='',
        verbose_name="Observação / Justificativa"
    )
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        verbose_name = "Promessa de Pagamento"
        verbose_name_plural = "Promessas de Pagamento"
        ordering = ['-data_promessa', '-criado_em']

    def __str__(self):
        return f"Promessa {self.cliente.nome} - R$ {self.valor} até {self.data_promessa.strftime('%d/%m/%Y')} [{self.status}]"




