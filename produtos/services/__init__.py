"""
Serviços de domínio do app produtos.

O ciclo de vida do cilindro (FSM, envase, entrega/recolha, sanitário, recall)
fica em ciclo_cilindro.py; os demais submódulos cobrem patrimônio, reteste,
baixa, granel, custos e estoque. Este pacote reexporta as funções mais usadas
para manter `from produtos.services import ...` funcionando.
"""
from .ciclo_cilindro import *  # noqa: F401,F403
from .ciclo_cilindro import TRANSIÇÕES_PERMITIDAS_CILINDRO  # noqa: F401
from .indenizacao import calcular_indenizacao  # noqa: F401
from .baixa import (  # noqa: F401
    baixar_cilindro_patrimonial,
    estornar_baixa,
    registrar_extravio,
)
from .reteste import (  # noqa: F401
    enviar_cilindros_para_reteste,
    registrar_retorno_reteste,
    retificar_reteste,
)
