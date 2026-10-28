
from core.context import tenant_context
from core.models import Filial, Tenant


def obter_filial_matriz(tenant: Tenant) -> Filial | None:
    """Retorna a filial Matriz do Tenant se já existir."""
    return Filial.unscoped.filter(tenant=tenant, matriz=True).first()


def obter_ou_criar_filial_matriz(tenant: Tenant) -> Filial:
    """
    Garante que o Tenant possua uma filial Matriz cadastrada.
    Se já existir, devolve a matriz existente.
    Caso contrário, instancia a matriz usando os dados cadastrais do Tenant.
    """
    matriz = obter_filial_matriz(tenant)
    if matriz:
        return matriz

    with tenant_context(tenant):
        cnpj_limpo = tenant.cnpj or "00.000.000/0001-00"
        nome_filial = f"Matriz - {tenant.nome_fantasia or tenant.razao_social}"

        matriz, _ = Filial.unscoped.get_or_create(
            tenant=tenant,
            matriz=True,
            defaults={
                'nome': nome_filial[:255],
                'cnpj': cnpj_limpo,
                'inscricao_estadual': 'ISENTO',
                'uf': 'SP',
                'municipio_ibge': '3550308',  # São Paulo default se não informado
                'ativo': True,
            }
        )
        return matriz
