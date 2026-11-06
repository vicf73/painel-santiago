"""
Pacote Modular ETL Santiago (EDEC) - Etapas 6 e 7
Módulos:
- manifesto: Inventário e validação pré-carga de ficheiros fonte (manifesto_fontes.json)
- extrair: Extração de CONTRATO, DIVIDA, APARELHO, COB_J, cf1_aut e tabelas auxiliares
- transformar: Joins, maturidade, score de risco PNT e classificação de cobrança
- validar: Reconciliação automática das 4 empresas (17, 21, 07, 70) vs Dívida Total
- carregar: Exportação CSV/GZ, Upsert Supabase, controlo de inativos e refresh de KPIs
"""

from .manifesto import gerar_e_validar_manifesto

__all__ = ["gerar_e_validar_manifesto"]
