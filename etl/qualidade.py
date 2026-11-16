"""
Camada de Qualidade de Dados & Reconciliação (Fase 1 - Lakehouse Local Santiago)
Executa testes automáticos (unicidade, nulos, domínios) e o funil completo
Bronze -> Silver no DuckDB, salvando lake/silver/relatorio_dq.json.
"""

import os
import json
from datetime import datetime

import duckdb


def executar_qualidade_silver(base_santiago: str) -> dict:
    bronze_dir = os.path.join(base_santiago, "lake", "bronze").replace("\\", "/")
    silver_dir = os.path.join(base_santiago, "lake", "silver")
    db_path = os.path.join(silver_dir, "santiago.duckdb")

    con = duckdb.connect(db_path, read_only=True)

    testes = []

    def add_teste(nome: str, falhas: int, detalhe: str = ""):
        testes.append({
            "teste": nome,
            "passou": bool(falhas == 0),
            "falhas": int(falhas),
            "detalhe": detalhe,
        })

    # 1. Unicidade de faturas em fct_fatura
    dup_fat = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT emp, numfact FROM fct_fatura GROUP BY emp, numfact HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    add_teste("unique_fct_fatura_emp_numfact", dup_fat)

    # 2. Nulos críticos em fct_divida_snapshot
    nulos_div = con.execute("""
        SELECT COUNT(*) FROM fct_divida_snapshot
        WHERE cil IS NULL OR emp IS NULL OR val_divida_ecv IS NULL
    """).fetchone()[0]
    add_teste("not_null_fct_divida_snapshot", nulos_div)

    # 3. Domínio de empresas válido
    emp_inv = con.execute("""
        SELECT COUNT(*) FROM fct_divida_snapshot
        WHERE emp NOT IN ('17', '21', '7', '70')
    """).fetchone()[0]
    add_teste("valid_empresa_fct_divida", emp_inv)

    # 4. Funil de Reconciliação da Dívida (Bronze Bruto -> Silver Região Sul)
    bruto_div = con.execute(f"""
        SELECT COUNT(*), COALESCE(SUM(VAL_DIVIDA), 0)
        FROM read_parquet('{bronze_dir}/divida/divida.parquet')
    """).fetchone()

    silver_div = con.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(val_divida_ecv), 0),
            COALESCE(SUM(CASE WHEN emp = '17' THEN val_divida_ecv ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN emp = '21' THEN val_divida_ecv ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN emp = '7'  THEN val_divida_ecv ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN emp = '70' THEN val_divida_ecv ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN is_prescrita THEN val_divida_ecv ELSE 0 END), 0)
        FROM fct_divida_snapshot
    """).fetchone()

    aging_div = con.execute("""
        SELECT faixa_aging, COUNT(*) AS faturas, ROUND(SUM(val_divida_ecv), 2) AS valor_ecv
        FROM fct_divida_snapshot
        GROUP BY faixa_aging
        ORDER BY valor_ecv DESC
    """).fetchall()

    # 5. Reconciliação Faturação & Cobrança Silver (2026)
    fat_res = con.execute("""
        SELECT emp, COUNT(*) AS faturas, ROUND(SUM(val_total_ecv), 2) AS val_ecv, ROUND(SUM(consumo_qtd), 2) AS qtd
        FROM fct_fatura
        GROUP BY emp
        ORDER BY emp
    """).fetchall()

    cob_res = con.execute("""
        SELECT emp, COUNT(*) AS movs, COUNT(DISTINCT cil) AS cils, ROUND(SUM(valor_ecv), 2) AS val_ecv
        FROM fct_cobranca
        WHERE ano_cob >= 2026
        GROUP BY emp
        ORDER BY emp
    """).fetchall()

    con.close()

    todos_ok = all(t["passou"] for t in testes)
    relatorio = {
        "executado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "todos_testes_ok": todos_ok,
        "testes": testes,
        "funil_divida": {
            "bronze_linhas": int(bruto_div[0]),
            "bronze_ecv": round(float(bruto_div[1]), 2),
            "silver_linhas": int(silver_div[0]),
            "silver_ecv": round(float(silver_div[1]), 2),
            "filtrado_fora_sul_ou_invalido_ecv": round(float(bruto_div[1]) - float(silver_div[1]), 2),
            "edec_sul_17": round(float(silver_div[2]), 2),
            "electra_sa_21": round(float(silver_div[3]), 2),
            "electra_sul_07": round(float(silver_div[4]), 2),
            "electra_sarl_70": round(float(silver_div[5]), 2),
            "prescrita_ecv": round(float(silver_div[6]), 2),
        },
        "aging_divida": [{"faixa": r[0], "faturas": int(r[1]), "valor_ecv": float(r[2])} for r in aging_div],
        "faturacao_silver": [{"emp": r[0], "faturas": int(r[1]), "val_ecv": float(r[2]), "consumo_qtd": float(r[3])} for r in fat_res],
        "cobranca_silver_2026": [{"emp": r[0], "movs": int(r[1]), "cils": int(r[2]), "val_ecv": float(r[3])} for r in cob_res],
    }

    out_json = os.path.join(silver_dir, "relatorio_dq.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    print("=" * 72)
    print(f" FASE 1 - DATA QUALITY & RECONCILIAÇÃO: {'APROVADO ✔' if todos_ok else 'FALHOU ✖'}")
    print("=" * 72)
    for t in testes:
        print(f"   [{'OK' if t['passou'] else 'ERRO'}] {t['teste']} (falhas={t['falhas']})")
    fd = relatorio["funil_divida"]
    print(f"   Dívida Bronze: {fd['bronze_ecv']:,.2f} ECV -> Silver Sul: {fd['silver_ecv']:,.2f} ECV (Filtrado: {fd['filtrado_fora_sul_ou_invalido_ecv']:,.2f} ECV)")
    print("   Aging Real da Dívida:")
    for a in relatorio["aging_divida"]:
        print(f"     - {a['faixa']:10s}: {a['faturas']:>9,} fat. | {a['valor_ecv']:>16,.2f} ECV")
    print(f"   Relatório salvo em: {out_json}")
    return relatorio
