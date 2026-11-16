"""
Orquestrador Fase 1 - Lakehouse Local Santiago (Bronze -> Silver -> Data Quality)
Uso:
  python etl_lakehouse.py              # Executa Bronze (incremental), Silver (DuckDB) e Qualidade
  python etl_lakehouse.py --so-silver  # Reprocessa apenas Silver e Qualidade sobre os Parquets existentes
"""

import os
import sys
import argparse

sys.stdout.reconfigure(encoding="utf-8")

BASE_SANTIAGO = os.path.dirname(os.path.abspath(__file__))
BASE_ATUAL_SCRIPT = os.environ.get("PASTA_ATUAL_SCRIPT", r"C:\Users\VICTOR FERREIRA\Desktop\Atual_script")

from etl.bronze import executar_bronze
from etl.silver import executar_silver
from etl.qualidade import executar_qualidade_silver
from etl.score_v2 import executar_score_v2
from etl.gold import construir_marts_gold, sincronizar_marts_supabase


def main():
    parser = argparse.ArgumentParser(description="Pipeline Lakehouse Fase 1+2+3 (Bronze -> Silver -> Score v2 -> Gold)")
    parser.add_argument("--so-silver", action="store_true", help="Salta a camada Bronze e reconstrói Silver + Score v2 + Gold")
    parser.add_argument("--so-gold", action="store_true", help="Executa apenas Score v2 + Gold sobre a Silver existente")
    parser.add_argument("--sem-sync", action="store_true", help="Não envia os Marts Gold para o Supabase")
    parser.add_argument("--anos-prescricao", type=int, default=int(os.environ.get("ANOS_PRESCRICAO", "5")))
    args = parser.parse_args()

    if not args.so_silver and not args.so_gold:
        executar_bronze(BASE_SANTIAGO, BASE_ATUAL_SCRIPT)

    if not args.so_gold:
        executar_silver(BASE_SANTIAGO, anos_prescricao=args.anos_prescricao)
        rel = executar_qualidade_silver(BASE_SANTIAGO)
        if not rel["todos_testes_ok"]:
            sys.exit(1)

    executar_score_v2(BASE_SANTIAGO)
    marts = construir_marts_gold(BASE_SANTIAGO)
    if not args.sem_sync:
        sincronizar_marts_supabase(BASE_SANTIAGO, marts)


if __name__ == "__main__":
    main()
