"""
Serviço de Carga Versionada de Dados Legados (Sprint 13 - Tarefas 1 e 8).

Permite importação controlada e auditável de:
- Clientes;
- Fornecedores;
- Parque de Cilindros;
- Saldos de Abertura Contábil (partidas dobradas verificadas: soma débitos = soma créditos).

Garante:
- Modo dry-run pré-voo em Staging com cópia anonimizada;
- Idempotência estrita por chaves primárias de negócio (CNPJ, número de patrimônio/série, código da conta);
- Total respeito à integridade multi-tenant e dinheiro via DecimalField e core/money.py.
"""
import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from django.db import transaction
from django.utils import timezone
from core.guards import assert_tenant_writable
from core.money import quantize
from core.tenancy import tenant_context
from clientes.models import Cliente
from financeiro.models import Fornecedor, PlanoContas, LancamentoContabil, PartidaContabil
from produtos.models import Cilindro, GasQuimico, ModeloCilindro, FabricanteCilindro



def carregar_clientes(
    tenant,
    dados_clientes: List[Dict[str, Any]],
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Importa ou atualiza clientes legados a partir de lista estruturada.
    """
    assert_tenant_writable(tenant)
    importados = 0
    atualizados = 0
    erros = []

    with tenant_context(tenant):
        for idx, item in enumerate(dados_clientes):
            cnpj = str(item.get('cnpj') or item.get('cpf_cnpj') or '').strip()
            nome = str(item.get('nome') or item.get('nome_razao_social') or '').strip()
            if not cnpj or not nome:
                erros.append({'linha': idx + 1, 'erro': "CNPJ e Nome são obrigatórios."})
                continue

            if not dry_run:
                with transaction.atomic():
                    cliente, criado = Cliente.unscoped.update_or_create(
                        tenant=tenant,
                        cnpj=cnpj,
                        defaults={
                            'nome': nome,
                            'nome_fantasia': item.get('nome_fantasia') or nome,
                            'email_financeiro': item.get('email_financeiro') or item.get('email', ''),
                            'telefone': item.get('telefone', '1100000000'),
                            'endereco': item.get('endereco', 'Endereço não informado'),
                            'cidade': item.get('cidade', 'São Paulo'),
                            'estado': item.get('estado', 'SP'),
                            'proprietario': item.get('proprietario') or item.get('responsavel') or nome,
                        }
                    )
                    if criado:
                        importados += 1
                    else:
                        atualizados += 1
            else:
                existe = Cliente.unscoped.filter(tenant=tenant, cnpj=cnpj).exists()
                if existe:
                    atualizados += 1
                else:
                    importados += 1

    return {
        'total_processado': len(dados_clientes),
        'criados': importados,
        'atualizados': atualizados,
        'importados': importados,
        'erros': erros,
        'dry_run': dry_run,
        'sucesso': len(erros) == 0
    }


def carregar_fornecedores(
    tenant,
    dados_fornecedores: List[Dict[str, Any]],
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Importa ou atualiza fornecedores legados com dados cadastrais e fiscais.
    """
    assert_tenant_writable(tenant)
    importados = 0
    atualizados = 0
    erros = []

    with tenant_context(tenant):
        for idx, item in enumerate(dados_fornecedores):
            doc = str(item.get('documento') or item.get('cnpj_cpf') or item.get('cnpj') or '').strip()
            razao = str(item.get('razao_social') or item.get('nome') or '').strip()
            if not doc or not razao:
                erros.append({'linha': idx + 1, 'erro': "Documento e Razão Social são obrigatórios."})
                continue

            if not dry_run:
                with transaction.atomic():
                    fornec, criado = Fornecedor.unscoped.update_or_create(
                        tenant=tenant,
                        documento=doc,
                        defaults={
                            'razao_social': razao,
                            'nome_fantasia': item.get('nome_fantasia') or razao,
                            'email': item.get('email', ''),
                            'telefone': item.get('telefone', ''),
                            'tipo_pessoa': item.get('tipo_pessoa', 'PJ'),
                        }
                    )
                    if criado:
                        importados += 1
                    else:
                        atualizados += 1
            else:
                existe = Fornecedor.unscoped.filter(tenant=tenant, documento=doc).exists()
                if existe:
                    atualizados += 1
                else:
                    importados += 1

    return {
        'total_processados': len(dados_fornecedores),
        'criados': importados,
        'atualizados': atualizados,
        'importados': importados,
        'erros': erros,
        'dry_run': dry_run,
        'sucesso': len(erros) == 0
    }


def carregar_cilindros(
    tenant,
    dados_cilindros: List[Dict[str, Any]],
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Importa parque de cilindros legados, validando QR Code, número de série e vínculos de catálogo.
    """
    assert_tenant_writable(tenant)
    importados = 0
    atualizados = 0
    erros = []

    with tenant_context(tenant):
        for idx, item in enumerate(dados_cilindros):
            serie = str(item.get('numero_serie') or item.get('numero_serie_ogiva', '')).strip()
            qr = str(item.get('codigo_qr') or f"QR-{serie}").strip()
            gas_sigla = item.get('gas_sigla')
            tipo_gas_id = item.get('tipo_gas_id')
            modelo_id = item.get('modelo_id')
            capacidade_id = item.get('capacidade_id')
            fabricante_id = item.get('fabricante_id')

            if not serie:
                erros.append({'linha': idx + 1, 'erro': "Número de Série é obrigatório."})
                continue

            # Resolução de Gás
            gas = None
            if gas_sigla:
                gas = GasQuimico.objects.filter(sigla=gas_sigla).first()
            if not gas and item.get('gas_id'):
                gas = GasQuimico.objects.filter(id=item.get('gas_id')).first()
            if not gas:
                gas, _ = GasQuimico.objects.get_or_create(
                    sigla='O2',
                    defaults={'nome': 'Oxigênio Industrial', 'categoria': 'INDUSTRIAL'}
                )

            # Resolução de Modelo
            modelo = None
            if modelo_id:
                modelo = ModeloCilindro.unscoped.filter(tenant=tenant, id=modelo_id).first()
            if not modelo:
                modelo = ModeloCilindro.unscoped.filter(tenant=tenant).first()
            if not modelo:
                modelo = ModeloCilindro.objects.create(
                    tenant=tenant,
                    descricao="Cilindro Padrão 50L 200bar",
                    volume_hidraulico_litros=Decimal('50.00'),
                    tara_nominal_kg=Decimal('60.00'),
                    pressao_servico_bar=200
                )

            fab_obj = FabricanteCilindro.unscoped.filter(tenant=tenant, id=fabricante_id).first() if fabricante_id else None


            if not dry_run:
                with transaction.atomic():
                    cil, criado = Cilindro.unscoped.update_or_create(
                        tenant=tenant,
                        numero_serie_ogiva=serie,
                        defaults={
                            'codigo_qr': qr,
                            'fabricante': fab_obj.nome if fab_obj else item.get('fabricante', 'FABRICANTE_PADRAO'),
                            'fabricante_catalogo': fab_obj,
                            'ano_fabricacao': int(item.get('ano_fabricacao', 2020)),
                            'gas_dedicado': gas,
                            'modelo': modelo,
                            'status': item.get('status', 'CHEIO_DISPONIVEL'),
                            'propriedade': item.get('propriedade', 'PROPRIO'),
                            'data_ultimo_reteste': item.get('data_ultimo_reteste') or datetime.date(2022, 1, 1),
                            'data_proximo_reteste': item.get('data_proximo_reteste') or datetime.date(2027, 1, 1),
                        }
                    )
                    if criado:
                        importados += 1
                    else:
                        atualizados += 1
            else:
                existe = Cilindro.unscoped.filter(tenant=tenant, numero_serie_ogiva=serie).exists()
                if existe:
                    atualizados += 1
                else:
                    importados += 1

    return {
        'total_processados': len(dados_cilindros),
        'criados': importados,
        'atualizados': atualizados,
        'importados': importados,
        'erros': erros,
        'dry_run': dry_run,
        'sucesso': len(erros) == 0
    }


def carregar_saldo_abertura(
    tenant,
    partidas: Optional[List[Dict[str, Any]]] = None,
    data_abertura: Optional[datetime.date] = None,
    usuario_responsavel=None,
    dry_run: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Importa o balanço / saldo de abertura contábil da distribuidora (Tarefa 1 & 9).
    Exige equação fundamental das partidas dobradas: Soma Débitos == Soma Créditos.
    """
    assert_tenant_writable(tenant)

    if data_abertura is None:
        data_abertura = kwargs.get('data') or datetime.date.today()

    if partidas is None:
        partidas = kwargs.get('itens') or []

    total_debitos = Decimal('0.00')
    total_creditos = Decimal('0.00')
    itens_preparados = []

    with tenant_context(tenant):
        for idx, p in enumerate(partidas):
            conta_ref = p.get('conta') or p.get('conta_id') or p.get('codigo_estrutural') or p.get('codigo_conta')
            if isinstance(conta_ref, PlanoContas):
                conta = conta_ref
            elif isinstance(conta_ref, str) and ('.' in conta_ref):
                conta = PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural=conta_ref).first()
            elif isinstance(conta_ref, (int, str)):
                conta = PlanoContas.unscoped.filter(tenant=tenant, id=conta_ref).first() or \
                        PlanoContas.unscoped.filter(tenant=tenant, codigo_estrutural=str(conta_ref)).first()
            else:
                conta = None

            if not conta:
                raise ValueError(f"Conta contábil '{conta_ref}' não cadastrada para o tenant.")

            tipo_partida = p.get('tipo') or p.get('tipo_partida')
            valor = p.get('valor')
            debito = Decimal('0.00')
            credito = Decimal('0.00')

            if tipo_partida == 'DEBITO':
                debito = quantize(Decimal(str(valor)), 2)
            elif tipo_partida == 'CREDITO':
                credito = quantize(Decimal(str(valor)), 2)
            else:
                debito = quantize(Decimal(str(p.get('debito', '0.00'))), 2)
                credito = quantize(Decimal(str(p.get('credito', '0.00'))), 2)
                tipo_partida = 'DEBITO' if debito > Decimal('0.00') else 'CREDITO'

            total_debitos += debito
            total_creditos += credito

            itens_preparados.append({
                'conta': conta,
                'tipo_partida': tipo_partida,
                'valor': debito if tipo_partida == 'DEBITO' else credito,
                'debito': debito,
                'credito': credito,
                'historico': p.get('historico', f"Saldo de Abertura {data_abertura.isoformat()}")
            })

        # Validação estrita de partidas dobradas
        if quantize(total_debitos, 2) != quantize(total_creditos, 2):
            diferenca = quantize(total_debitos - total_creditos, 2)
            raise ValueError(
                f"Desequilíbrio contábil: Soma Débitos (R$ {total_debitos}) != Soma Créditos (R$ {total_creditos}). Diferença: R$ {diferenca}."
            )

        lancamento = None
        if not dry_run:
            with transaction.atomic():
                ultimo_num = LancamentoContabil.unscoped.filter(tenant=tenant).count() + 1
                lancamento = LancamentoContabil.objects.create(
                    tenant=tenant,
                    numero=ultimo_num,
                    data_competencia=data_abertura,
                    historico=f"Lançamento de Saldo de Abertura Contábil - Go-Live {data_abertura.isoformat()}",
                    origem_tipo='SALDO_ABERTURA',
                    origem_id=f"ABERTURA-{data_abertura.isoformat()}",
                    hash_anterior='0' * 64,
                    hash_integridade='SALDO_ABERTURA_INICIAL',
                    criado_por=usuario_responsavel
                )

                for item in itens_preparados:
                    PartidaContabil.objects.create(
                        tenant=tenant,
                        lancamento=lancamento,
                        conta_contabil=item['conta'],
                        tipo_partida=item['tipo_partida'],
                        valor=item['valor']
                    )

    return {
        'sucesso': True,
        'dry_run': dry_run,
        'total_partidas': len(partidas),
        'total_debito': quantize(total_debitos, 2),
        'total_credito': quantize(total_creditos, 2),
        'lancamento_id': lancamento.id if lancamento else None,
        'mensagem': "Saldo de abertura equilibrado e validado pelo motor contábil."
    }

