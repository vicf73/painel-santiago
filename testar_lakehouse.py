"""
Suite de Testes Automatizados Pré-Publicação (Fase 4 - Projeto Santiago)
Valida em poucos segundos:
  1. Sintaxe Python (py_compile) de todos os módulos ETL
  2. Sintaxe JavaScript (node --check) se Node estiver disponível
  3. Integridade do DuckDB Silver & Relatório DQ
  4. Consistência dos 7 Marts Gold (marts_gold.json + score_v2_metricas.json)
  5. Presença de snapshots mensais imutáveis de dívida
"""

import os
import sys
import json
import py_compile
import subprocess

import duckdb

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))


def testar():
    print("=" * 72)
    print(" SUITE DE TESTES AUTOMATIZADOS PRÉ-PUBLICAÇÃO (SANTIAGO)")
    print("=" * 72)

    # 1. Sintaxe Python
    arqs_py = [
        "etl_santiago_supabase.py", "etl_lakehouse.py", "publicar_painel_web.py",
        "etl/manifesto.py", "etl/bronze.py", "etl/silver.py",
        "etl/qualidade.py", "etl/score_v2.py", "etl/gold.py",
    ]
    for rel in arqs_py:
        py_compile.compile(os.path.join(BASE, rel), doraise=True)
    print(f"  [1/5] Sintaxe Python ({len(arqs_py)} ficheiros): OK")

    # 2. Sintaxe JS
    arqs_js = ["config_santiago.js", "js/api.js", "js/gold.js", "js/contratos.js", "js/divida.js", "js/auth.js"]
    for rel in arqs_js:
        r = subprocess.run(["node", "--check", os.path.join(BASE, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"Erro JS em {rel}: {r.stderr}")
    print(f"  [2/5] Sintaxe JavaScript ({len(arqs_js)} ficheiros): OK")

    # 3. DuckDB Silver + DQ
    db_path = os.path.join(BASE, "lake", "silver", "santiago.duckdb")
    assert os.path.exists(db_path), f"DuckDB ausente: {db_path}"
    con = duckdb.connect(db_path, read_only=True)
    for tbl, min_rows in [
        ("dim_local_consumo", 100000),
        ("fct_fatura", 500000),
        ("fct_cobranca", 1000000),
        ("fct_divida_snapshot", 1000000),
        ("fct_inspecao_cea", 50000),
        ("fct_ordem_servico", 20000),
        ("mart_score_v2", 100000),
    ]:
        n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        assert n >= min_rows, f"Tabela {tbl} abaixo do mínimo esperado: {n} < {min_rows}"
    con.close()

    dq_path = os.path.join(BASE, "lake", "silver", "relatorio_dq.json")
    with open(dq_path, "r", encoding="utf-8") as f:
        dq = json.load(f)
    assert dq.get("todos_testes_ok") is True, "Relatório DQ reportou falhas!"
    print("  [3/5] DuckDB Silver + Relatório DQ: OK")

    # 4. Marts Gold + Score v2
    gold_path = os.path.join(BASE, "lake", "gold", "marts_gold.json")
    with open(gold_path, "r", encoding="utf-8") as f:
        gold = json.load(f)
    chaves_esp = {"kpis_executivos", "faturacao_mensal", "cobranca_mensal", "aging_divida", "ads_conta_corrente", "operacional_cea_os", "score_v2_validacao"}
    assert chaves_esp.issubset(set(gold.keys())), f"Chaves Gold em falta: {chaves_esp - set(gold.keys())}"
    auc = gold["score_v2_validacao"].get("auc_teste_out_of_time", 0)
    assert auc >= 0.75, f"AUC Out-of-Time abaixo do limite: {auc}"
    print(f"  [4/5] Marts Gold (7 chaves) + Score v2 (AUC={auc}): OK")

    # 5. Snapshots imutáveis de dívida
    snap_dir = os.path.join(BASE, "lake", "silver", "snapshots_divida")
    snaps = [f for f in os.listdir(snap_dir) if f.endswith(".parquet")] if os.path.isdir(snap_dir) else []
    assert len(snaps) >= 1, "Nenhum snapshot mensal de dívida arquivado!"
    print(f"  [5/5] Snapshots Imutáveis de Dívida ({len(snaps)} arquivo(s)): OK")

    print("=" * 72)
    print(" TODOS OS TESTES PRÉ-PUBLICAÇÃO PASSARAM ✔")
    print("=" * 72)


if __name__ == "__main__":
    testar()
