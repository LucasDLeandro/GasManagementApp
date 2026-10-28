from django.core.exceptions import ValidationError
from django.utils import timezone

def validar_aptidao_medicinal(tenant, exigir_envase=False):
    """
    Validador de Aptidão Sanitária e Regulatória para Operações com Gases Medicinais (ANVISA).
    Conforme RDC nº 658/2022, IN nº 129/2022, RDC nº 870/2024, RDC nº 887/2024 (ANVISA) e Resolução CFF nº 731/2022.

    Parâmetros:
    - tenant: Instância de core.models.Tenant.
    - exigir_envase: Booleano indicando se a operação envolve enchimento/fabricação de gás medicinal
                     (exige modo ENVASADORA ou MISTO e Certificado de Boas Práticas - CBPF).

    Lança ValidationError detalhado caso o tenant esteja inapto para a operação.
    Retorna True se estiver 100% conforme.
    """
    if not tenant:
        raise ValidationError("Tenant não especificado para validação regulatória ANVISA.")

    # 1. Verifica existência do Perfil Regulatório
    perfil = getattr(tenant, 'perfil_regulatorio', None)
    if not perfil:
        from core.models import PerfilRegulatorioTenant
        perfil = PerfilRegulatorioTenant.objects.filter(tenant=tenant).first()

    if not perfil:
        raise ValidationError(
            f"Bloqueio Regulatório ANVISA: O tenant '{tenant.nome_fantasia}' não possui Perfil Regulatório "
            f"cadastrado para operar gases medicinais."
        )

    hoje = timezone.now().date()

    # 2. Licença Sanitária (Estadual / Municipal)
    if not perfil.licenca_sanitaria_numero or not perfil.licenca_sanitaria_validade:
        raise ValidationError(
            f"Bloqueio Regulatório ANVISA: O tenant '{tenant.nome_fantasia}' não possui Licença Sanitária "
            f"válida informada no Perfil Regulatório."
        )

    if hoje > perfil.licenca_sanitaria_validade:
        raise ValidationError(
            f"Bloqueio Regulatório ANVISA: A Licença Sanitária ({perfil.licenca_sanitaria_numero}) do tenant "
            f"'{tenant.nome_fantasia}' está vencida desde {perfil.licenca_sanitaria_validade.strftime('%d/%m/%Y')}."
        )

    # 3. Autorização de Funcionamento ANVISA (AFE)
    if perfil.afe_validade and hoje > perfil.afe_validade:
        raise ValidationError(
            f"Bloqueio Regulatório ANVISA: A Autorização de Funcionamento ANVISA - AFE ({perfil.afe_numero}) "
            f"do tenant '{tenant.nome_fantasia}' está vencida desde {perfil.afe_validade.strftime('%d/%m/%Y')}."
        )

    # 4. Responsável Técnico (RT) Vigente (CRF / CRQ)
    rt = perfil.responsavel_tecnico_vigente
    if not rt:
        raise ValidationError(
            f"Bloqueio Regulatório ANVISA: O tenant '{tenant.nome_fantasia}' não possui Responsável Técnico (RT) "
            f"vinculado ao Perfil Regulatório para responder perante a ANVISA."
        )

    if not rt.esta_vigente:
        status_rt = "inativo" if not rt.ativo else "com vigência expirada"
        raise ValidationError(
            f"Bloqueio Regulatório ANVISA: O Responsável Técnico '{rt.nome_completo}' ({rt.conselho_classe}-{rt.uf_conselho} "
            f"{rt.numero_registro}) do tenant '{tenant.nome_fantasia}' está {status_rt}."
        )

    # 5. Exigências Específicas para Envase / Fabricação de Gases Medicinais
    if exigir_envase:
        if perfil.modo_operacao == 'DISTRIBUIDORA':
            raise ValidationError(
                f"Bloqueio Regulatório ANVISA: O tenant '{tenant.nome_fantasia}' possui modo de operação "
                f"'{perfil.get_modo_operacao_display()}' e não possui autorização sanitária para envase/fabricação "
                f"de gases medicinais (exclusivo para Envasadoras ou Misto conforme RDC nº 658/2022 e IN nº 129/2022)."
            )

        if not perfil.cbpf_cbpda_numero or not perfil.cbpf_cbpda_validade:
            raise ValidationError(
                f"Bloqueio Regulatório ANVISA: O envase de gases medicinais exige Certificado de Boas Práticas "
                f"de Fabricação (CBPF) emitido pela ANVISA. Certificado ausente no Perfil Regulatório do tenant '{tenant.nome_fantasia}'."
            )

        if hoje > perfil.cbpf_cbpda_validade:
            raise ValidationError(
                f"Bloqueio Regulatório ANVISA: O Certificado de Boas Práticas de Fabricação (CBPF nº {perfil.cbpf_cbpda_numero}) "
                f"do tenant '{tenant.nome_fantasia}' está vencido desde {perfil.cbpf_cbpda_validade.strftime('%d/%m/%Y')}."
            )

    return True


def regras_sanitarias(tenant, exigir_envase: bool = False):
    """
    Regras sanitárias e regulatórias da ANVISA (RDC 887/2024, IN 129/2022, CBPF, assinatura de RT).
    Único ponto canônico do sistema onde PerfilRegulatorioTenant.modo_operacao é avaliado (Sprint 7B).
    """
    return validar_aptidao_medicinal(tenant, exigir_envase=exigir_envase)

