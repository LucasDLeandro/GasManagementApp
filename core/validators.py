import re

from django.core.exceptions import ValidationError


def validar_cnpj(value: str) -> str:
    """
    Validador oficial de CNPJ com cálculo de dígitos verificadores (Módulo 11).
    Aceita CNPJ formatado (XX.XXX.XXX/XXXX-XX) ou apenas numérico (14 dígitos).
    """
    if not value:
        raise ValidationError("CNPJ não informado.")

    # Remove caracteres não numéricos
    cnpj = re.sub(r'\D', '', str(value))

    if len(cnpj) != 14:
        raise ValidationError(f"CNPJ deve conter exatamente 14 dígitos numéricos (recebido: {len(cnpj)}).")

    # Rejeita sequências de dígitos repetidos conhecidas
    if cnpj in [str(i) * 14 for i in range(10)]:
        raise ValidationError("CNPJ inválido (dígitos repetidos).")

    # Cálculo do 1º dígito verificador
    multiplicadores_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma_1 = sum(int(cnpj[i]) * multiplicadores_1[i] for i in range(12))
    resto_1 = soma_1 % 11
    digito_1 = 0 if resto_1 < 2 else 11 - resto_1

    if int(cnpj[12]) != digito_1:
        raise ValidationError("CNPJ inválido (primeiro dígito verificador incorreto).")

    # Cálculo do 2º dígito verificador
    multiplicadores_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma_2 = sum(int(cnpj[i]) * multiplicadores_2[i] for i in range(13))
    resto_2 = soma_2 % 11
    digito_2 = 0 if resto_2 < 2 else 11 - resto_2

    if int(cnpj[13]) != digito_2:
        raise ValidationError("CNPJ inválido (segundo dígito verificador incorreto).")

    return value


def validar_chave_nfe(value: str) -> str:
    """
    Validador oficial de Chave de Acesso de NF-e (44 dígitos numéricos)
    com cálculo do dígito verificador ponderado (Módulo 11) conforme norma SEFAZ.
    """
    if not value:
        return value

    chave = re.sub(r'\D', '', str(value))
    if len(chave) != 44:
        raise ValidationError(f"Chave de NF-e deve conter exatamente 44 dígitos numéricos (recebido: {len(chave)}).")

    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(digito) * pesos[i % 8] for i, digito in enumerate(reversed(chave[:43])))
    resto = soma % 11
    dv_calculado = 0 if resto in (0, 1) else 11 - resto

    if int(chave[43]) != dv_calculado:
        raise ValidationError(
            f"Chave de NF-e inválida: dígito verificador incorreto (calculado: {dv_calculado}, recebido: {chave[43]})."
        )

    return chave

