import re
from django.core.exceptions import ValidationError
from core.validators import validar_cnpj


def limpar_formatacao(valor: str) -> str:
    """Remove caracteres não numéricos."""
    if not valor:
        return ""
    return re.sub(r'\D', '', str(valor))


def validar_cpf(cpf: str):
    """Validação oficial de CPF com cálculo dos 2 dígitos verificadores (módulo 11)."""
    if not cpf:
        raise ValidationError("CPF é obrigatório.")
    numeros = limpar_formatacao(cpf)
    if len(numeros) != 11:
        raise ValidationError(f"CPF deve conter exatamente 11 dígitos numéricos. Recebido: {cpf}")

    # Bloqueia números repetidos (111.111.111-11, etc.)
    if numeros == numeros[0] * 11:
        raise ValidationError("CPF inválido (dígitos repetidos).")

    # Primeiro dígito verificador
    soma = sum(int(numeros[i]) * (10 - i) for i in range(9))
    resto = soma % 11
    d1 = 0 if resto < 2 else 11 - resto
    if int(numeros[9]) != d1:
        raise ValidationError("Primeiro dígito verificador do CPF inválido.")

    # Segundo dígito verificador
    soma = sum(int(numeros[i]) * (11 - i) for i in range(10))
    resto = soma % 11
    d2 = 0 if resto < 2 else 11 - resto
    if int(numeros[10]) != d2:
        raise ValidationError("Segundo dígito verificador do CPF inválido.")


def validar_cpf_ou_cnpj(documento: str):
    """Valida se o documento informado é um CPF ou CNPJ matematicamente válido."""
    nums = limpar_formatacao(documento)
    if len(nums) == 11:
        validar_cpf(nums)
    elif len(nums) == 14:
        validar_cnpj(nums)
    else:
        raise ValidationError("Documento deve ser um CPF (11 dígitos) ou CNPJ (14 dígitos) válido.")


TAMANHO_IE_POR_UF = {
    'AC': (13,),
    'AL': (9,),
    'AP': (9,),
    'AM': (9,),
    'BA': (8, 9),
    'CE': (9,),
    'DF': (13,),
    'ES': (9,),
    'GO': (9,),
    'MA': (9,),
    'MT': (11,),
    'MS': (9,),
    'MG': (13,),
    'PA': (9,),
    'PB': (9,),
    'PR': (10,),
    'PE': (9, 14),
    'PI': (9,),
    'RJ': (8,),
    'RN': (9, 10),
    'RS': (10,),
    'RO': (14,),
    'RR': (9,),
    'SC': (9,),
    'SP': (12,),
    'SE': (9,),
    'TO': (9, 11),
}


def validar_inscricao_estadual(ie: str, uf: str):
    """
    Validação estrutural de Inscrição Estadual por UF conforme o SINTEGRA / COTEPE.
    Aceita 'ISENTO' para contribuintes dispensados ou isentos.
    """
    if not ie:
        return

    ie_limpa = str(ie).strip().upper()
    if ie_limpa in ('ISENTO', 'ISENTA', 'ISENTO/IMUNE', ''):
        return

    uf_clean = str(uf).strip().upper() if uf else ""
    nums = limpar_formatacao(ie_limpa)

    if not nums:
        raise ValidationError(f"Inscrição Estadual inválida: {ie}")

    if uf_clean in TAMANHO_IE_POR_UF:
        tamanhos_permitidos = TAMANHO_IE_POR_UF[uf_clean]
        if len(nums) not in tamanhos_permitidos:
            raise ValidationError(
                f"Inscrição Estadual de {uf_clean} deve ter {tamanhos_permitidos} dígitos numéricos. Recebido: {len(nums)} dígitos ({ie})."
            )


def validar_ncm(ncm: str):
    """Valida formato de NCM (Nomenclatura Comum do Mercosul - 8 dígitos numéricos)."""
    if not ncm:
        return
    nums = limpar_formatacao(ncm)
    if len(nums) != 8:
        raise ValidationError(f"NCM deve conter exatamente 8 dígitos numéricos. Recebido: {ncm}")


def validar_cest(cest: str):
    """Valida formato de CEST (Código Especificador da Substituição Tributária - 7 dígitos)."""
    if not cest:
        return
    nums = limpar_formatacao(cest)
    if len(nums) != 7:
        raise ValidationError(f"CEST deve conter exatamente 7 dígitos numéricos quando informado. Recebido: {cest}")


def validar_cfop(cfop: str, uf_origem: str, uf_destino: str):
    """
    Valida a coerência do primeiro dígito do CFOP com as UFs da operação (Task 7):
    - Operações Internas (mesma UF): CFOP deve iniciar com '1' (Entrada) ou '5' (Saída).
    - Operações Interestaduais (UFs distintas): CFOP deve iniciar com '2' (Entrada) ou '6' (Saída).
    - Operações com Exterior: CFOP deve iniciar com '3' (Entrada) ou '7' (Saída).
    """
    if not cfop:
        raise ValidationError("CFOP é obrigatório.")

    cfop_nums = limpar_formatacao(cfop)
    if len(cfop_nums) != 4:
        raise ValidationError(f"CFOP deve conter exatamente 4 dígitos numéricos. Recebido: {cfop}")

    primeiro_digito = cfop_nums[0]
    uf_origem_clean = str(uf_origem).strip().upper() if uf_origem else ""
    uf_destino_clean = str(uf_destino).strip().upper() if uf_destino else ""

    if uf_origem_clean and uf_destino_clean:
        if uf_origem_clean == uf_destino_clean:
            # Operação Interna
            if primeiro_digito not in ('1', '5'):
                raise ValidationError(
                    f"Incoerência de CFOP: Operação interna dentro de {uf_origem_clean} exige CFOP iniciando com 1 ou 5. Recebido: {cfop}"
                )
        else:
            # Operação Interestadual
            if primeiro_digito not in ('2', '6'):
                raise ValidationError(
                    f"Incoerência de CFOP: Operação interestadual ({uf_origem_clean} -> {uf_destino_clean}) exige CFOP iniciando com 2 ou 6. Recebido: {cfop}"
                )
