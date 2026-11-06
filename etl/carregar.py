"""
Módulo 1.2 (Carga) - Exportação CSV/GZ, Upsert Paralelo Supabase, Pós-Carga (Inativos + Modelo Normalizado + Cache KPIs)
"""

from etl_santiago_supabase import (
    exportar_csv_local,
    preparar_registos_supabase,
    sincronizar_supabase,
)

__all__ = [
    "exportar_csv_local",
    "preparar_registos_supabase",
    "sincronizar_supabase",
]
