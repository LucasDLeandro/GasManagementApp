"""
Assistente de importação e confirmação de Saldo de Abertura (Sprint 9B - Tarefa 11 / Lacuna F-15).
Modo simulação antes de confirmar.
Gera lançamento contábil contra a conta de PL «Saldos de Abertura».
Uma única vez por tenant, salvo estorno.
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.guards import assert_modulo, assert_tenant_writable
from core.money import quantize
from financeiro.models import (
    ImportacaoSaldoAbertura,
    LancamentoContabil,
    PlanoContas,
    TituloFinanceiro,
)
from financeiro.services.periodo import checar_periodo_aberto
from financeiro.services.razao import estornar, lancar
from financeiro.services.titulos import criar_titulo


@transaction.atomic
def simular_saldo_abertura(
    *,
    tenant,
    data_corte,
    dados_carga: dict,
    usuario=None
) -> ImportacaoSaldoAbertura:
    """
    Executa a simulação do saldo de abertura sem escriturar o Razão contábil.
    Calcula os totais de Ativo, Passivo e o Patrimônio Líquido de Abertura equilibrado.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    checar_periodo_aberto(tenant, data_corte)

    # 1. Apuração dos totais da carga
    total_ativo = Decimal('0.00')
    total_passivo = Decimal('0.00')

    # Bancos / Disponibilidades
    for b in dados_carga.get('saldos_bancarios', []):
        total_ativo += quantize(Decimal(str(b.get('saldo', '0.00'))), 2)

    # Clientes a Receber
    for c in dados_carga.get('titulos_receber', []):
        total_ativo += quantize(Decimal(str(c.get('valor', '0.00'))), 2)

    # Estoques
    for e in dados_carga.get('estoques', []):
        total_ativo += quantize(Decimal(str(e.get('valor_total', '0.00'))), 2)

    # Imobilizado (Custo histórico líquido da depreciação acumulada)
    for imob in dados_carga.get('imobilizado', []):
        v_custo = quantize(Decimal(str(imob.get('custo_aquisicao', '0.00'))), 2)
        v_deprec = quantize(Decimal(str(imob.get('depreciacao_acumulada', '0.00'))), 2)
        total_ativo += (v_custo - v_deprec)

    # Fornecedores / Passivos a Pagar
    for f in dados_carga.get('titulos_pagar', []):
        total_passivo += quantize(Decimal(str(f.get('valor', '0.00'))), 2)

    total_ativo = quantize(total_ativo, 2)
    total_passivo = quantize(total_passivo, 2)
    pl_abertura = quantize(total_ativo - total_passivo, 2)

    importacao = ImportacaoSaldoAbertura.objects.create(
        tenant=tenant,
        data_corte=data_corte,
        status='SIMULACAO',
        total_ativo=total_ativo,
        total_passivo=total_passivo,
        total_pl_abertura=pl_abertura,
        dados_json=dados_carga,
        executado_por=usuario
    )

    return importacao


@transaction.atomic
def confirmar_saldo_abertura(
    *,
    tenant,
    importacao_id,
    usuario=None
) -> ImportacaoSaldoAbertura:
    """
    Confirma formalmente a importação de abertura:
    - Escritura o lançamento no Razão contra a conta de PL «Saldos de Abertura».
    - Cria os títulos a receber e a pagar com origem_tipo='SALDO_ABERTURA'.
    - Trava a unicidade de confirmação.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    importacao = ImportacaoSaldoAbertura.objects.select_for_update().get(id=importacao_id)
    if importacao.tenant_id != tenant.id:
        raise ValidationError("Importação de saldo de abertura pertence a outro Tenant.")

    if importacao.status != 'SIMULACAO':
        raise ValidationError(f"A importação #{importacao.id} está com status '{importacao.status}' e não pode ser confirmada.")

    # Validação de unicidade de confirmação ativa
    if ImportacaoSaldoAbertura.objects.filter(tenant=tenant, status='CONFIRMADO').exists():
        raise ValidationError("Já existe um Saldo de Abertura confirmado para este Tenant.")

    checar_periodo_aberto(tenant, importacao.data_corte)

    dados = importacao.dados_json or {}

    # Contas contábeis de contrapartida
    c_banco = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.1.01').first()
    c_clientes = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.2.01').first()
    c_estoque = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.1.3.01').first()
    c_imob = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.2.1.01').first()
    c_deprec = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural='1.2.1.02').first()
    c_fornecedores = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['2.1.1.01', '2.1.1']).first()
    c_pl_abertura = PlanoContas.objects.filter(tenant=tenant, codigo_estrutural__in=['2.3.4.01', '2.3.4', '2.3.3.01', '2.3.3']).first()

    if not c_pl_abertura:
        c_pl_abertura = PlanoContas.objects.filter(tenant=tenant, tipo='ANALITICA', codigo_estrutural__startswith='2.3').first()

    partidas = []

    # 1. Ativos (Débitos)
    if importacao.total_ativo > Decimal('0.00'):
        # Saldo bancário
        for b in dados.get('saldos_bancarios', []):
            val = quantize(Decimal(str(b.get('saldo', '0.00'))), 2)
            if val > Decimal('0.00') and c_banco:
                partidas.append({'conta': c_banco, 'tipo_partida': 'DEBITO', 'valor': val})

        # Clientes
        for c in dados.get('titulos_receber', []):
            val = quantize(Decimal(str(c.get('valor', '0.00'))), 2)
            if val > Decimal('0.00') and c_clientes:
                partidas.append({'conta': c_clientes, 'tipo_partida': 'DEBITO', 'valor': val})
                cl_obj = c.get('cliente')
                if not cl_obj and c.get('cliente_id'):
                    from clientes.models import Cliente
                    cl_obj = Cliente.objects.filter(tenant=tenant, id=c.get('cliente_id')).first()

                # Cria título financeiro a receber
                criar_titulo(
                    tenant=tenant,
                    tipo='RECEBER',
                    conta_gerencial=c_clientes,
                    valor_bruto=val,
                    data_emissao=importacao.data_corte,
                    cliente=cl_obj,
                    origem_tipo='SALDO_ABERTURA',
                    origem_id=f"ABERTURA_REC_{importacao.id}_{len(partidas)}",
                    historico=f"Saldo de Abertura Cliente: {c.get('historico', 'Carga Inicial')}",
                    criado_por=usuario
                )

        # Estoques
        for e in dados.get('estoques', []):
            val = quantize(Decimal(str(e.get('valor_total', '0.00'))), 2)
            if val > Decimal('0.00') and c_estoque:
                partidas.append({'conta': c_estoque, 'tipo_partida': 'DEBITO', 'valor': val})

        # Imobilizado
        for imob in dados.get('imobilizado', []):
            v_custo = quantize(Decimal(str(imob.get('custo_aquisicao', '0.00'))), 2)
            v_deprec = quantize(Decimal(str(imob.get('depreciacao_acumulada', '0.00'))), 2)
            if v_custo > Decimal('0.00') and c_imob:
                partidas.append({'conta': c_imob, 'tipo_partida': 'DEBITO', 'valor': v_custo})
            if v_deprec > Decimal('0.00') and c_deprec:
                partidas.append({'conta': c_deprec, 'tipo_partida': 'CREDITO', 'valor': v_deprec})

    # 2. Passivos (Créditos)
    for f in dados.get('titulos_pagar', []):
        val = quantize(Decimal(str(f.get('valor', '0.00'))), 2)
        if val > Decimal('0.00') and c_fornecedores:
            partidas.append({'conta': c_fornecedores, 'tipo_partida': 'CREDITO', 'valor': val})
            fn_obj = f.get('fornecedor')
            if not fn_obj and f.get('fornecedor_id'):
                from financeiro.models import Fornecedor
                fn_obj = Fornecedor.objects.filter(tenant=tenant, id=f.get('fornecedor_id')).first()

            # Cria título financeiro a pagar
            criar_titulo(
                tenant=tenant,
                tipo='PAGAR',
                conta_gerencial=c_fornecedores,
                valor_bruto=val,
                data_emissao=importacao.data_corte,
                fornecedor=fn_obj,
                beneficiario_texto=f.get('beneficiario_texto', 'Fornecedor Abertura') if not fn_obj else '',
                origem_tipo='SALDO_ABERTURA',
                origem_id=f"ABERTURA_PAG_{importacao.id}_{len(partidas)}",
                historico=f"Saldo de Abertura Fornecedor: {f.get('historico', 'Carga Inicial')}",
                criado_por=usuario
            )

    # 3. Contrapartida no Patrimônio Líquido («Saldos de Abertura»)
    soma_debitos = sum(p['valor'] for p in partidas if p['tipo_partida'] == 'DEBITO')
    soma_creditos = sum(p['valor'] for p in partidas if p['tipo_partida'] == 'CREDITO')

    if soma_debitos > soma_creditos:
        diferenca = quantize(soma_debitos - soma_creditos, 2)
        partidas.append({'conta': c_pl_abertura, 'tipo_partida': 'CREDITO', 'valor': diferenca})
    elif soma_creditos > soma_debitos:
        diferenca = quantize(soma_creditos - soma_debitos, 2)
        partidas.append({'conta': c_pl_abertura, 'tipo_partida': 'DEBITO', 'valor': diferenca})

    # 4. Escritura Lançamento Contábil
    lancamento = None
    if partidas:
        lancamento, _ = lancar(
            tenant=tenant,
            data_competencia=importacao.data_corte,
            historico=f"Balanço de Abertura Patrimonial - Data de Corte {importacao.data_corte.strftime('%d/%m/%Y')}",
            partidas=partidas,
            origem_tipo='ImportacaoSaldoAbertura',
            origem_id=str(importacao.id),
            usuario=usuario
        )

    # 5. Atualiza registro de importação
    importacao.status = 'CONFIRMADO'
    importacao.confirmado_em = timezone.now()
    importacao.lancamento = lancamento
    importacao.save(update_fields=['status', 'confirmado_em', 'lancamento'])

    return importacao


@transaction.atomic
def estornar_saldo_abertura(
    *,
    tenant,
    importacao_id,
    motivo: str = "Estorno formal de saldo de abertura",
    usuario=None
) -> ImportacaoSaldoAbertura:
    """
    Estorna formalmente o saldo de abertura confirmado.
    """
    assert_tenant_writable(tenant)
    assert_modulo(tenant, 'financeiro')

    motivo = (motivo or "Estorno formal de saldo de abertura").strip()
    if not motivo:
        raise ValidationError("O motivo formal do estorno do saldo de abertura é obrigatório.")

    importacao = ImportacaoSaldoAbertura.objects.select_for_update().get(id=importacao_id)
    if importacao.tenant_id != tenant.id:
        raise ValidationError("Importação de saldo de abertura pertence a outro Tenant.")

    if importacao.status != 'CONFIRMADO':
        raise ValidationError(f"Apenas importações confirmadas podem ser estornadas (status atual: {importacao.status}).")

    # 1. Estorna o lançamento no Razão
    if importacao.lancamento:
        estornar(importacao.lancamento, motivo=motivo.strip(), usuario=usuario)

    # 2. Cancela títulos criados
    titulos = TituloFinanceiro.objects.filter(
        tenant=tenant,
        origem_tipo='SALDO_ABERTURA',
        origem_id__startswith=f"ABERTURA_"
    )
    for t in titulos:
        t.status = 'CANCELADO'
        t.save(update_fields=['status', 'atualizado_em'])
        t.parcelas.update(status='CANCELADA', saldo_em_aberto=Decimal('0.00'))

    # 3. Marca como estornado
    importacao.status = 'ESTORNADO'
    importacao.save(update_fields=['status'])

    return importacao
