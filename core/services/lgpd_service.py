"""
Serviço de Gestão de Privacidade e Conformidade LGPD (Sprint 13 - Tarefa 4).

Implementa:
- Mapeamento e inventário de dados pessoais (RoPA / Registro das Atividades de Tratamento);
- Definição formal de bases legais e prazos de retenção (telemetria GPS x obrigações fiscais/sanitárias);
- Atendimento aos direitos do titular:
  * Art. 19: Acesso e exportação estruturada de dados pessoais;
  * Art. 16: Eliminação e anonimização (pseudonimização) resguardando obrigações legais (Art. 16, I - CTN e ANVISA);
- Rotina de expurgo de telemetria fina de GPS (retenção máxima de 90 dias);
- Papéis definidos: Distribuidora = Controlador; Baros SaaS = Operador.
"""
import datetime
import uuid
from typing import Any, Dict, List, Optional
from django.db import transaction
from django.utils import timezone

from core.guards import assert_tenant_writable
from core.models import Tenant, SolicitacaoTitularLGPD, LogAuditoriaDados
from core.tenancy import tenant_context
from clientes.models import Cliente
from logistica.models import CoordenadaRastreamento, Entrega
from vendas.models import Venda


ROPA_MAPEAMENTO_DADOS_PESSOAIS = {
    'versao_inventario': "2026.1-PROD",
    'papel_saas': "OPERADOR",
    'papel_tenant': "CONTROLADOR",
    'papeis': {
        'controlador': "Empresa Distribuidora de Gases (Tenant)",
        'operador': "Baros Tecnologia e Soluções SaaS LTDA",
        'encarregado_dpo': "dpo@baros.com.br"
    },
    'inventario_dados': {
        'motoristas_gps': "Rastreamento e telemetria de trânsito em tempo real",
        'contatos_cobranca': "E-mails e telefones de contas a pagar/receber",
        'clientes_pf': "Dados cadastrais e histórico de aquisição de oxigenoterapia/gás"
    },

    'categorias_dados': [
        {
            'categoria': "Motoristas e Equipe de Entrega",
            'dados_coletados': ["Nome", "CPF", "CNH", "Telefone", "Coordenadas GPS de Trânsito"],
            'finalidade': "Roteirização logística, rastreamento de carga perigosa e comprovação de entrega",
            'base_legal': "Art. 7º, V (Execução de Contrato) e Art. 7º, II (Cumprimento de Obrigação Legal - ANTT Res. 5.998/22)",
            'prazo_retencao': "90 dias para pontos finos de GPS; 5 anos para romaneios de carga perigosa"
        },
        {
            'categoria': "Contatos Comerciais e Financeiros de Clientes",
            'dados_coletados': ["Nome", "E-mail", "Telefone", "Cargo"],
            'finalidade': "Envio de faturas, links de rastreio de entrega e notificações de reteste hidrostático",
            'base_legal': "Art. 7º, V (Execução de Contrato) e Art. 7º, I (Consentimento prévio ativo para canais externos)",
            'prazo_retencao': "Durante a vigência do relacionamento comercial ou até revogação do consentimento"
        },
        {
            'categoria': "Clientes Pessoa Física",
            'dados_coletados': ["Nome", "CPF", "Endereço Residencial", "Telefone", "Histórico de Compras de Gás"],
            'finalidade': "Faturamento, entrega domiciliar (oxigenoterapia) e rastreabilidade sanitária",
            'base_legal': "Art. 7º, II (Obrigação Legal Tributária - NF-e SEFAZ e RDC ANVISA nº 658/2022) e Art. 7º, V (Contrato)",
            'prazo_retencao': "5 anos após emissão da NF-e (Art. 173 do Código Tributário Nacional) e 5 anos após validade do lote medicinal"
        }
    ]
}


def obter_mapeamento_lgpd() -> Dict[str, Any]:
    """
    Retorna o inventário estruturado e a matriz de bases legais da LGPD.
    """
    return ROPA_MAPEAMENTO_DADOS_PESSOAIS


def solicitar_acesso_exportacao_titular(
    tenant: Tenant,
    identificador: Optional[str] = None,
    nome_titular: str = "",
    operador_user=None,
    **kwargs
) -> Dict[str, Any]:
    """
    Atende ao Artigo 19 da LGPD: compila e exporta os dados pessoais associados ao titular.
    """
    assert_tenant_writable(tenant)
    identificador_limpo = str(identificador or kwargs.get('cpf_titular') or kwargs.get('cpf') or '').strip()
    protocolo = f"LGPD-EXP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    with tenant_context(tenant):
        # 1. Localiza cliente(s) por CPF ou e-mail
        clientes = Cliente.unscoped.filter(tenant=tenant).filter(
            cnpj=identificador_limpo
        ) | Cliente.unscoped.filter(tenant=tenant, email_financeiro__iexact=identificador_limpo)

        dados_clientes = []
        for c in clientes:
            vendas = Venda.unscoped.filter(tenant=tenant, cliente=c).values(
                'id', 'status', 'valor_total', 'data_venda'
            )[:20]
            dados_clientes.append({
                'id': c.id,
                'nome': c.nome,
                'cpf_cnpj': c.cnpj,
                'documento': c.cnpj,
                'email': c.email_financeiro,
                'telefone': c.telefone,
                'endereco': f"{c.endereco}, {c.cidade} - {c.estado}",
                'total_pedidos': Venda.unscoped.filter(tenant=tenant, cliente=c).count(),
                'amostra_pedidos': list(vendas)
            })

        nome_export = nome_titular or (dados_clientes[0]['nome'] if dados_clientes else 'Não identificado')
        resultado = {
            'titular': {
                'identificador': identificador_limpo,
                'nome': nome_export
            },
            'dados_cadastrais': dados_clientes,
            'exportado_em': timezone.now().isoformat(),
            'base_legal_atendimento': "Art. 19 da Lei 13.709/2018 (Direito de Acesso)"
        }

        solicitacao = SolicitacaoTitularLGPD.objects.create(
            tenant=tenant,
            protocolo=protocolo,
            tipo='ACESSO_EXPORTACAO',
            identificador_titular=identificador_limpo,
            nome_titular=nome_export,
            status='CONCLUIDO',
            justificativa="Exportação de dados pessoais executada com sucesso.",
            resultado_json=resultado,
            concluido_em=timezone.now(),
            operador_responsavel=operador_user
        )

    return {
        'sucesso': True,
        'status': 'CONCLUIDA',
        'protocolo': protocolo,
        'solicitacao_id': solicitacao.id,
        'dados': dados_clientes[0] if dados_clientes else {'cpf_cnpj': identificador_limpo, 'nome': nome_export},
        'resultado': resultado
    }


def solicitar_eliminacao_anonimizacao_titular(
    tenant: Tenant,
    identificador: Optional[str] = None,
    operador_user=None,
    justificativa: str = "Solicitação de eliminação/esquecimento pelo titular (Art. 16)",
    **kwargs
) -> Dict[str, Any]:
    """
    Atende ao Artigo 16 da LGPD (Eliminação e Anonimização):
    - Anonimiza dados pessoais cadastrais não vinculados a exigências fiscais irrevogáveis;
    - Preserva registros contábeis, notas fiscais e lotes ANVISA sob anonimização/pseudonimização,
      em conformidade estrita com o Art. 16, I da LGPD (Cumprimento de Obrigação Legal ou Regulatória).
    """
    assert_tenant_writable(tenant)
    identificador_limpo = str(identificador or kwargs.get('cpf_titular') or kwargs.get('cpf') or '').strip()
    protocolo = f"LGPD-DEL-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    motivo = kwargs.get('motivo') or justificativa

    with tenant_context(tenant):
        clientes = Cliente.unscoped.filter(tenant=tenant).filter(
            cnpj=identificador_limpo
        ) | Cliente.unscoped.filter(tenant=tenant, email_financeiro__iexact=identificador_limpo)

        total_anonimizados = 0
        pedidos_retidos_obrigacao_legal = 0

        with transaction.atomic():
            for c in clientes:
                # Contabiliza pedidos fiscais retidos obrigatoriamente
                qtd_vendas = Venda.unscoped.filter(tenant=tenant, cliente=c).count()
                pedidos_retidos_obrigacao_legal += qtd_vendas

                # Anonimiza dados cadastrais
                c.nome = f"TITULAR_ANONIMIZADO_{c.id}"
                c.nome_fantasia = "ANONIMIZADO"
                c.email_financeiro = f"anonimizado_{c.id}@anonimizado.local"
                c.telefone = "(00) 00000-0000"
                c.endereco = "Informação Anonimizada por Solicitação do Titular"
                c.proprietario = "ANONIMIZADO"
                c.save(update_fields=[
                    'nome', 'nome_fantasia', 'email_financeiro',
                    'telefone', 'endereco', 'proprietario'
                ])
                total_anonimizados += 1

            resultado = {
                'total_cadastros_anonimizados': total_anonimizados,
                'registros_fiscais_preservados': pedidos_retidos_obrigacao_legal,
                'fundamento_retencao_fiscal': "Art. 16, I da LGPD c/c Art. 173 do Código Tributário Nacional e RDC ANVISA 658/2022 (5 anos obrigatórios)",
                'executado_em': timezone.now().isoformat()
            }

            solicitacao = SolicitacaoTitularLGPD.objects.create(
                tenant=tenant,
                protocolo=protocolo,
                tipo='ELIMINACAO_ANONIMIZACAO',
                identificador_titular=identificador_limpo,
                nome_titular="Titular Anonimizado",
                status='CONCLUIDO',
                justificativa=(
                    f"{motivo}. Dados cadastrais anonimizados. Documentos fiscais e rastreabilidade sanitária "
                    f"preservados pelo prazo legal obrigatório de 5 anos (Art. 16, I da LGPD)."
                ),
                resultado_json=resultado,
                concluido_em=timezone.now(),
                operador_responsavel=operador_user
            )

            from django.contrib.contenttypes.models import ContentType
            ct = ContentType.objects.get_for_model(SolicitacaoTitularLGPD)
            LogAuditoriaDados.objects.create(
                tenant=tenant,
                usuario=operador_user,
                content_type=ct,
                object_id=str(solicitacao.id),
                acao='ALTERACAO',
                diff_json={
                    'evento': 'ANONIMIZACAO_TITULAR_LGPD',
                    'protocolo': protocolo,
                    'identificador': identificador_limpo,
                    'cadastros_anonimizados': total_anonimizados,
                    'pedidos_preservados': pedidos_retidos_obrigacao_legal,
                    'executado_em': timezone.now().isoformat()
                }
            )

    return {
        'sucesso': True,
        'status': 'ANONIMIZADO_COM_RETENCAO_FISCAL',
        'protocolo': protocolo,
        'solicitacao_id': solicitacao.id,
        'total_cadastros_anonimizados': total_anonimizados,
        'pedidos_retidos_obrigacao_legal': pedidos_retidos_obrigacao_legal,
        'resultado': resultado
    }



def expurgar_telemetria_gps_antiga(tenant: Optional[Tenant] = None, dias_retencao: int = 90) -> Dict[str, Any]:
    """
    Executa a rotina de expurgo de telemetria fina de GPS com mais de dias_retencao (padrão 90 dias).
    Garante conformidade com o princípio da minimização de dados e prazo de retenção definido no RIPD.
    """
    limite = timezone.now() - datetime.timedelta(days=dias_retencao)
    qs = CoordenadaRastreamento.unscoped.filter(timestamp__lt=limite)
    if tenant:
        qs = qs.filter(tenant=tenant)


    total_expurgado, _ = qs.delete()

    return {
        'sucesso': True,
        'total_coordenadas_expurgadas': total_expurgado,
        'dias_retencao': dias_retencao,
        'dias_retencao_aplicados': dias_retencao,
        'limite_data': limite.isoformat(),
        'executado_em': timezone.now().isoformat(),
        'status': "EXPURGO_CONCLUIDO"
    }

