"""
Ponto de entrada canônico para validação de carga da Sprint 12A (logistica/carga.py::validar_carga).
"""
from logistica.services.carga import (
    validar_carga,
    liberar_carga_bloqueada,
    despachar_entrega_para_rota,
    seed_regras_incompatibilidade,
    ResultadoValidacaoCarga,
)

__all__ = [
    'validar_carga',
    'liberar_carga_bloqueada',
    'despachar_entrega_para_rota',
    'seed_regras_incompatibilidade',
    'ResultadoValidacaoCarga',
]
