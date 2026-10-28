"""
Serviço canônico de validação de carga, incompatibilidade química e conformidade regulatória ANTT (Sprint 12A - Tarefa 2).
Valida peso físico total, limites por tipo de cilindro, incompatibilidade de classes de risco (NBR 14619) e validades (CNH, MOPP, CIV, CIPP).
"""
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date
from typing import List, Dict, Any, Optional

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from core.guards import assert_tenant_writable
from core.money import quantize
from logistica.models import (
    Entrega,
    Veiculo,
    Motorista,
    CapacidadeVeiculoTipoCilindro,
    RegraIncompatibilidadeCarga,
    LiberacaoCarga,
)


@dataclass
class ResultadoValidacaoCarga:
    valido: bool
    erros_bloqueantes: List[str] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    peso_total_kg: Decimal = Decimal('0.00')
    capacidade_veiculo_kg: Decimal = Decimal('0.00')
    percentual_peso: Decimal = Decimal('0.00')
    contagem_por_tipo: Dict[str, int] = field(default_factory=dict)
    classes_risco_presentes: List[str] = field(default_factory=list)
    detalhes: Dict[str, Any] = field(default_factory=dict)

    @property
    def bloqueado(self) -> bool:
        return len(self.erros_bloqueantes) > 0


def seed_regras_incompatibilidade(tenant) -> int:
    """
    Cadastra matriz inicial de regras de incompatibilidade ANTT / ABNT NBR 14619 para o tenant.
    Marcada com norma_referencia para conferência técnica do Responsável Técnico.
    """
    regras_base = [
        # Inflamáveis (2.1) x Oxidantes (5.1 ou 2.2 com subclasse 5.1): BLOQUEAR
        {
            'classe_a': '2.1',
            'classe_b': '5.1',
            'acao': 'BLOQUEAR',
            'mensagem': 'Incompatibilidade crítica: Proibido transportar Gases Inflamáveis (2.1) junto com Oxidantes/Comburentes (5.1). Risco de combustão acelerada e explosão.'
        },
        {
            'classe_a': '5.1',
            'classe_b': '2.1',
            'acao': 'BLOQUEAR',
            'mensagem': 'Incompatibilidade crítica: Proibido transportar Gases Oxidantes (5.1) junto com Inflamáveis (2.1).'
        },
        # Tóxicos (2.3) x Inflamáveis (2.1): BLOQUEAR
        {
            'classe_a': '2.3',
            'classe_b': '2.1',
            'acao': 'BLOQUEAR',
            'mensagem': 'Proibido transportar Gases Tóxicos (2.3) e Inflamáveis (2.1) no mesmo compartimento de carga sem isolamento estanque.'
        },
        {
            'classe_a': '2.1',
            'classe_b': '2.3',
            'acao': 'BLOQUEAR',
            'mensagem': 'Proibido transportar Gases Inflamáveis (2.1) junto com Tóxicos (2.3).'
        },
        # Asfixiantes (2.2) x Inflamáveis (2.1): AVISAR
        {
            'classe_a': '2.2',
            'classe_b': '2.1',
            'acao': 'AVISAR',
            'mensagem': 'Atenção: Transporte conjunto de Gás Asfixiante (2.2) e Inflamável (2.1) exige ventilação contínua da carroceria conforme NBR 14619.'
        },
        {
            'classe_a': '2.1',
            'classe_b': '2.2',
            'acao': 'AVISAR',
            'mensagem': 'Atenção: Transporte conjunto de Gás Inflamável (2.1) e Asfixiante (2.2) exige ventilação adequada da carroceria.'
        },
    ]

    criadas = 0
    for r in regras_base:
        _, created = RegraIncompatibilidadeCarga.objects.get_or_create(
            tenant=tenant,
            classe_a=r['classe_a'],
            classe_b=r['classe_b'],
            defaults={
                'acao': r['acao'],
                'mensagem': r['mensagem'],
                'norma_referencia': 'Resolução ANTT nº 5.998/2022 e ABNT NBR 14619',
                'ativo': True
            }
        )
        if created:
            criadas += 1
    return criadas


def validar_carga(entrega: Entrega) -> ResultadoValidacaoCarga:
    """
    Executa a validação rigorosa de segurança e regulação antes de liberar a rota (Sprint 12A - Tarefa 2):
    1. Peso total (gás + tara dos cilindros) contra a capacidade máxima do veículo.
    2. Quantidade de recipientes por modelo/tipo de cilindro contra CapacidadeVeiculoTipoCilindro.
    3. Incompatibilidade química de classes de risco (RegraIncompatibilidadeCarga).
    4. Validade da CNH e categoria compatível do motorista.
    5. Validade do curso MOPP para transporte de produtos perigosos.
    6. Validade do CIV (Inspeção Veicular) e CIPP (Inspeção de Produtos Perigosos) do veículo.
    """
    erros: List[str] = []
    avisos: List[str] = []
    detalhes: Dict[str, Any] = {}
    hoje = timezone.localdate()
    tenant = entrega.tenant

    veiculo = entrega.veiculo
    motorista_user = entrega.motorista

    # 1. Resolução do Veículo
    if not veiculo:
        erros.append("Entrega não possui veículo vinculado.")
        capacidade_veiculo = Decimal('0.00')
    else:
        capacidade_veiculo = quantize(veiculo.capacidade_carga_kg or veiculo.capacidade_carga or Decimal('0.00'))

    # 2. Resolução do Motorista (pelo model Motorista ou perfil vinculado ao usuário)
    motorista_cadastrado = None
    if motorista_user:
        motorista_cadastrado = Motorista.objects.filter(tenant=tenant, usuario=motorista_user).first()
        if not motorista_cadastrado:
            # Fallback se não associado pelo usuario FK mas pelo nome/username
            motorista_cadastrado = Motorista.objects.filter(tenant=tenant, nome__iexact=motorista_user.get_full_name() or motorista_user.username).first()

    # Se a entrega tiver vínculo direto com motorista_objeto
    if hasattr(entrega, 'motorista_objeto') and entrega.motorista_objeto:
        motorista_cadastrado = entrega.motorista_objeto

    if not motorista_user and not motorista_cadastrado:
        erros.append("Entrega não possui motorista designado.")

    # 3. Validação de Documentação e Habilitação do Motorista
    if motorista_cadastrado:
        if not motorista_cadastrado.cnh_validade:
            erros.append(f"Motorista {motorista_cadastrado.nome} sem data de validade da CNH cadastrada.")
        elif motorista_cadastrado.cnh_validade < hoje:
            erros.append(f"CNH do motorista {motorista_cadastrado.nome} está vencida desde {motorista_cadastrado.cnh_validade.strftime('%d/%m/%Y')}.")

        if not motorista_cadastrado.mopp_validade:
            erros.append(f"Motorista {motorista_cadastrado.nome} sem certificado de curso MOPP cadastrado para produtos perigosos.")
        elif motorista_cadastrado.mopp_validade < hoje:
            erros.append(f"Certificado MOPP do motorista {motorista_cadastrado.nome} está vencido desde {motorista_cadastrado.mopp_validade.strftime('%d/%m/%Y')}.")

        cat = (motorista_cadastrado.cnh_categoria or '').upper().strip()
        if cat in ('A', 'B'):
            avisos.append(f"Motorista com CNH categoria {cat}. Verifique se o PBT do veículo não exige categoria C ou superior.")
        detalhes['motorista'] = {
            'nome': motorista_cadastrado.nome,
            'cnh_validade': motorista_cadastrado.cnh_validade.isoformat() if motorista_cadastrado.cnh_validade else None,
            'mopp_validade': motorista_cadastrado.mopp_validade.isoformat() if motorista_cadastrado.mopp_validade else None,
            'categoria': motorista_cadastrado.cnh_categoria,
        }

    # 4. Validação de Documentação do Veículo (CIV e CIPP)
    if veiculo:
        if veiculo.civ_validade and veiculo.civ_validade < hoje:
            erros.append(f"CIV (Certificado de Inspeção Veicular) do veículo {veiculo.placa} está vencido desde {veiculo.civ_validade.strftime('%d/%m/%Y')}.")
        if veiculo.cipp_validade and veiculo.cipp_validade < hoje:
            erros.append(f"CIPP (Inspeção para Transporte de Produtos Perigosos) do veículo {veiculo.placa} está vencido desde {veiculo.cipp_validade.strftime('%d/%m/%Y')}.")

        rntrc_atual = (veiculo.rntrc or veiculo.rntrc_antt or '').strip()
        if not rntrc_atual:
            avisos.append(f"Veículo {veiculo.placa} sem RNTRC ANTT informado.")

    # 5. Apuração Física da Carga: Peso e Quantidade por Tipo
    peso_total = Decimal('0.00')
    contagem_por_tipo: Dict[str, int] = {}
    classes_risco_set = set()

    vendas = list(entrega.vendas.all().prefetch_related('itens__produto', 'itens__sku__modelo_cilindro', 'itens__sku__gas'))

    for venda in vendas:
        for item in venda.itens.all():
            qtd = int(item.quantidade or 0)
            if qtd <= 0:
                continue

            # Identificação física do cilindro e peso
            sku = item.sku
            prod = item.produto

            tara_unit = Decimal('0.00')
            gas_unit = Decimal('0.00')
            tipo_desc = 'Cilindro Padrão'

            if sku and sku.modelo_cilindro:
                mod = sku.modelo_cilindro
                tara_unit = mod.tara_nominal_kg or Decimal('0.00')
                gas_unit = sku.massa_gas_kg or mod.massa_gas_padrao_kg or Decimal('0.00')
                tipo_desc = mod.descricao
            elif prod:
                # Estimativa de produto legado
                tara_unit = Decimal('15.00')
                gas_unit = Decimal('10.00')
                tipo_desc = prod.nome

            peso_unit_cheio = tara_unit + gas_unit
            peso_item = Decimal(qtd) * peso_unit_cheio
            peso_total += peso_item

            contagem_por_tipo[tipo_desc] = contagem_por_tipo.get(tipo_desc, 0) + qtd

            # Classe de risco ANTT
            classe_item = None
            if sku and sku.gas:
                from produtos.models import ClasseRiscoGas
                cr = ClasseRiscoGas.objects.filter(tenant=tenant, gas=sku.gas).first()
                if cr:
                    classe_item = cr.classe_risco
                    if cr.subclasse:
                        classes_risco_set.add(cr.subclasse.strip())
            elif prod and prod.categoria == 'Medicinal':
                classe_item = '2.2'  # Oxigênio medicinal com risco 5.1
                classes_risco_set.add('5.1')
            elif prod:
                classe_item = '2.1' if 'acetileno' in prod.nome.lower() or 'glp' in prod.nome.lower() else '2.2'

            if classe_item:
                classes_risco_set.add(classe_item.strip())

    peso_total = quantize(peso_total)

    # 6. Validação de Peso Total contra Capacidade do Veículo
    if veiculo and capacidade_veiculo > Decimal('0.00'):
        if peso_total > capacidade_veiculo:
            excesso = peso_total - capacidade_veiculo
            erros.append(
                f"Sobrecarga de Peso: Peso total carregado ({peso_total:.2f} kg) excede a capacidade máxima "
                f"do veículo {veiculo.placa} ({capacidade_veiculo:.2f} kg) em {excesso:.2f} kg."
            )

    # 7. Validação de Capacidade Específica por Tipo de Cilindro (CapacidadeVeiculoTipoCilindro)
    if veiculo:
        capacidades_cadastradas = CapacidadeVeiculoTipoCilindro.objects.filter(
            tenant=tenant,
            veiculo=veiculo
        ).select_related('tipo_cilindro')

        for cap in capacidades_cadastradas:
            nome_tipo = cap.tipo_cilindro.descricao if cap.tipo_cilindro else cap.tipo_cilindro_codigo
            qtd_carregada = contagem_por_tipo.get(nome_tipo, 0)
            if cap.quantidade_maxima > 0 and qtd_carregada > cap.quantidade_maxima:
                erros.append(
                    f"Limite por tipo excedido: Carregados {qtd_carregada} cilindros do tipo '{nome_tipo}', "
                    f"mas o veículo {veiculo.placa} suporta no máximo {cap.quantidade_maxima} unidades desse tipo. "
                    f"A carga excede o limite estrutural suportado para este tipo de cilindro."
                )

    # 8. Validação de Incompatibilidade Química entre Classes de Risco (RegraIncompatibilidadeCarga)
    classes_lista = sorted(list(classes_risco_set))
    if len(classes_lista) > 1:
        regras_incomp = RegraIncompatibilidadeCarga.objects.filter(
            tenant=tenant,
            ativo=True,
            classe_a__in=classes_lista,
            classe_b__in=classes_lista
        )

        for reg in regras_incomp:
            if reg.classe_a in classes_risco_set and reg.classe_b in classes_risco_set:
                msg = reg.mensagem or f"Incompatibilidade química detectada entre classes {reg.classe_a} e {reg.classe_b} ({reg.norma_referencia})."
                if reg.acao == 'BLOQUEAR':
                    erros.append(f"Incompatibilidade química (BLOQUEIO): {msg}")
                else:
                    avisos.append(f"Incompatibilidade química (ALERTA): {msg}")

    # Percentual de ocupação
    percentual_peso = Decimal('0.00')
    if capacidade_veiculo > Decimal('0.00'):
        percentual_peso = quantize((peso_total / capacidade_veiculo) * Decimal('100.00'))

    detalhes.update({
        'peso_total_kg': peso_total,
        'capacidade_veiculo_kg': capacidade_veiculo,
        'percentual_peso': percentual_peso,
        'contagem_por_tipo': contagem_por_tipo,
        'classes_risco': classes_lista,
        'total_paradas': len(vendas),
    })

    valido = len(erros) == 0

    return ResultadoValidacaoCarga(
        valido=valido,
        erros_bloqueantes=erros,
        avisos=avisos,
        peso_total_kg=peso_total,
        capacidade_veiculo_kg=capacidade_veiculo,
        percentual_peso=percentual_peso,
        contagem_por_tipo=contagem_por_tipo,
        classes_risco_presentes=classes_lista,
        detalhes=detalhes
    )


@transaction.atomic
def liberar_carga_bloqueada(
    entrega: Entrega,
    responsavel,
    motivo: str
) -> LiberacaoCarga:
    """
    Realiza a liberação formal e auditada de saída em rota para entrega com inconsistências de validação de carga.
    - Exige permissão logistica.liberar_carga_bloqueada (ou superuser/gerente).
    - Exige justificativa formal obrigatória (mínimo 5 caracteres).
    - Registra a liberação auditada em LiberacaoCarga e permite transição da Entrega para 'Em Rota'.
    """
    assert_tenant_writable(entrega.tenant)

    if not responsavel or not responsavel.is_authenticated:
        raise PermissionDenied("Usuário não autenticado.")

    # Duas camadas de permissão
    from core.models import Membership
    tem_permissao = (
        responsavel.is_superuser
        or responsavel.has_perm('logistica.liberar_carga_bloqueada')
        or Membership.objects.filter(
            tenant=entrega.tenant,
            user=responsavel,
            papel__in=['ADMIN', 'GERENTE'],
            ativo=True
        ).exists()
    )
    if not tem_permissao:
        raise PermissionDenied("Usuário não possui a permissão 'logistica.liberar_carga_bloqueada' para liberar esta carga.")

    motivo_limpo = (motivo or '').strip()
    if len(motivo_limpo) < 5:
        raise ValidationError("O motivo da liberação é obrigatório e deve possuir no mínimo 5 caracteres.")

    # Realiza validação técnica para arquivar erros que foram formalmente assumidos pelo gestor
    res = validar_carga(entrega)

    liberacao = LiberacaoCarga.objects.create(
        tenant=entrega.tenant,
        entrega=entrega,
        responsavel=responsavel,
        motivo=motivo_limpo,
        erros_ignorados=res.erros_bloqueantes
    )

    # Permite transição para Em Rota
    entrega.status = 'Em Rota'
    entrega.data_saida = timezone.now()
    entrega.save(update_fields=['status', 'data_saida'])

    return liberacao


@transaction.atomic
def despachar_entrega_para_rota(entrega: Entrega, usuario=None) -> Entrega:
    """
    Transiciona a entrega para 'Em Rota' apenas após validação de carga sem bloqueios ou prévia liberação formal auditada.
    """
    assert_tenant_writable(entrega.tenant)

    # Verifica se já possui liberação formal gravada
    tem_liberacao = LiberacaoCarga.objects.filter(tenant=entrega.tenant, entrega=entrega).exists()

    if not tem_liberacao:
        res = validar_carga(entrega)
        if not res.valido:
            erros_str = " | ".join(res.erros_bloqueantes)
            raise ValidationError(
                f"Não é permitido despachar Entrega #{entrega.id} para rota: Carga com inconsistências bloqueantes: {erros_str}. "
                f"Exige liberação formal por gestor autorizado."
            )

    entrega.status = 'Em Rota'
    entrega.data_saida = timezone.now()
    entrega.save(update_fields=['status', 'data_saida'])
    return entrega
