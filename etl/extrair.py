"""
Módulo 1.2 (Extração) - Leitura das Fontes TXT e Excel (Projeto Santiago)
"""

from etl_santiago_supabase import (
    carregar_contratos,
    carregar_dimensoes_codigos,
    carregar_dim_divida,
    carregar_dim_aparelho,
    carregar_dimensoes_santiago,
    carregar_dim_itinerario,
    carregar_dim_cf1_autos,
    carregar_dim_cobranca,
)

__all__ = [
    "carregar_contratos",
    "carregar_dimensoes_codigos",
    "carregar_dim_divida",
    "carregar_dim_aparelho",
    "carregar_dimensoes_santiago",
    "carregar_dim_itinerario",
    "carregar_dim_cf1_autos",
    "carregar_dim_cobranca",
]
