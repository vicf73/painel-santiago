"""
Módulo 1.2 (Transformação) - Joins, Score de Risco e Critérios PNT (Projeto Santiago)
"""

from etl_santiago_supabase import (
    calcular_score_risco,
    atribuir_criterio_perdas,
    executar_transformacao,
)

__all__ = [
    "calcular_score_risco",
    "atribuir_criterio_perdas",
    "executar_transformacao",
]
