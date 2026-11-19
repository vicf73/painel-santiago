"""
Camada Gold (Fase 2 - Lakehouse Santiago)
Calcula os Marts Executivos no DuckDB Silver (Taxa de Cobrança Real, DSO,
Aging por Empresa, Série Mensal Faturação vs Cobrança, Conta Corrente AdS,
Inspeções CEA & SLA OS) e sincroniza com public.santiago_marts_gold no Supabase.
"""

import os
import json
import time
from datetime import datetime, timezone

import duckdb
import requests


def construir_marts_gold(base_santiago: str) -> dict:
    t0 = time.time()
    silver_dir = os.path.join(base_santiago, "lake", "silver")
    gold_dir = os.path.join(base_santiago, "lake", "gold")
    os.makedirs(gold_dir, exist_ok=True)
    db_path = os.path.join(silver_dir, "santiago.duckdb")

    con = duckdb.connect(db_path, read_only=True)

    # 1. Faturação mensal por empresa e produto
    rows_fat = con.execute("""
        SELECT
            lote_ym,
            emp,
            produto,
            COUNT(*) AS faturas,
            COUNT(DISTINCT cil) AS cils_ativos,
            ROUND(SUM(consumo_qtd), 2) AS consumo_qtd,
            ROUND(SUM(val_total_ecv), 2) AS valor_ecv
        FROM fct_fatura
        GROUP BY lote_ym, emp, produto
        ORDER BY lote_ym, emp, produto
    """).fetchall()
    faturacao_mensal = [
        {
            "lote_ym": r[0], "emp": r[1], "produto": r[2],
            "faturas": int(r[3]), "cils_ativos": int(r[4]),
            "consumo_qtd": float(r[5] or 0), "valor_ecv": float(r[6] or 0),
            "preco_medio_ecv": round(float(r[6] or 0) / float(r[5]), 2) if (r[5] or 0) > 0 else 0.0,
        }
        for r in rows_fat
    ]

    # 2. Cobrança mensal 2026 por empresa
    rows_cob = con.execute("""
        SELECT
            PRINTF('%04d-%02d', ano_cob, mes_cob) AS ano_mes,
            emp,
            COUNT(*) AS movimentos,
            COUNT(DISTINCT cil) AS cils_pagadores,
            ROUND(SUM(valor_ecv), 2) AS valor_ecv,
            ROUND(SUM(CASE WHEN faixa_maturidade IN ('3 mes', '6 mes', '1 ano', '> 1 ano') THEN valor_ecv ELSE 0 END), 2) AS valor_atraso_ecv
        FROM fct_cobranca
        WHERE ano_cob >= 2026
        GROUP BY ano_mes, emp
        ORDER BY ano_mes, emp
    """).fetchall()
    cobranca_mensal = [
        {
            "ano_mes": r[0], "emp": r[1], "movimentos": int(r[2]),
            "cils_pagadores": int(r[3]), "valor_ecv": float(r[4] or 0),
            "valor_atraso_ecv": float(r[5] or 0),
        }
        for r in rows_cob
    ]

    # 3. Aging real da dívida por faixa e por empresa
    rows_ag = con.execute("""
        SELECT
            faixa_aging,
            COUNT(*) AS faturas,
            COUNT(DISTINCT cil) AS cils,
            ROUND(SUM(val_divida_ecv), 2) AS total_ecv,
            ROUND(SUM(CASE WHEN emp = '17' THEN val_divida_ecv ELSE 0 END), 2) AS emp_17,
            ROUND(SUM(CASE WHEN emp = '21' THEN val_divida_ecv ELSE 0 END), 2) AS emp_21,
            ROUND(SUM(CASE WHEN emp = '7'  THEN val_divida_ecv ELSE 0 END), 2) AS emp_07,
            ROUND(SUM(CASE WHEN emp = '70' THEN val_divida_ecv ELSE 0 END), 2) AS emp_70
        FROM fct_divida_snapshot
        GROUP BY faixa_aging
        ORDER BY CASE faixa_aging
            WHEN '0-30d' THEN 1 WHEN '31-90d' THEN 2 WHEN '91-180d' THEN 3
            WHEN '181-365d' THEN 4 WHEN '1-2 anos' THEN 5 WHEN '2-5 anos' THEN 6
            WHEN '> 5 anos' THEN 7 ELSE 8 END
    """).fetchall()
    aging_divida = [
        {
            "faixa": r[0], "faturas": int(r[1]), "cils": int(r[2]),
            "total_ecv": float(r[3] or 0), "emp_17": float(r[4] or 0),
            "emp_21": float(r[5] or 0), "emp_07": float(r[6] or 0), "emp_70": float(r[7] or 0),
        }
        for r in rows_ag
    ]

    # 4. Cliente Especial AdS (21 - Electra SA, CILs 60220187 / 60220188)
    ads_fat = con.execute("""
        SELECT lote_ym, COUNT(*) AS faturas, ROUND(SUM(consumo_qtd), 2) AS m3, ROUND(SUM(val_total_ecv), 2) AS valor_ecv
        FROM fct_fatura
        WHERE emp = '21'
        GROUP BY lote_ym
        ORDER BY lote_ym
    """).fetchall()
    ads_div = con.execute("""
        SELECT faixa_aging, COUNT(*) AS faturas, ROUND(SUM(val_divida_ecv), 2) AS valor_ecv
        FROM fct_divida_snapshot
        WHERE emp = '21' AND cil IN (60220187, 60220188)
        GROUP BY faixa_aging
        ORDER BY CASE faixa_aging
            WHEN '0-30d' THEN 1 WHEN '31-90d' THEN 2 WHEN '91-180d' THEN 3
            WHEN '181-365d' THEN 4 WHEN '1-2 anos' THEN 5 WHEN '2-5 anos' THEN 6
            WHEN '> 5 anos' THEN 7 ELSE 8 END
    """).fetchall()
    ads_div_tot = sum(float(r[2] or 0) for r in ads_div)
    ads_fat_tot = sum(float(r[3] or 0) for r in ads_fat)
    ads_m3_tot = sum(float(r[2] or 0) for r in ads_fat)
    ads_conta_corrente = {
        "total_faturado_ecv": round(ads_fat_tot, 2),
        "total_m3": round(ads_m3_tot, 2),
        "preco_medio_m3": round(ads_fat_tot / ads_m3_tot, 2) if ads_m3_tot > 0 else 0.0,
        "saldo_divida_ecv": round(ads_div_tot, 2),
        "cobranca_caixa_2026_ecv": 0.0,
        "serie_mensal": [
            {
                "lote_ym": r[0], "faturas": int(r[1]), "m3": float(r[2] or 0), "valor_ecv": float(r[3] or 0),
                "preco_medio_m3": round(float(r[3] or 0) / float(r[2]), 2) if (r[2] or 0) > 0 else 0.0,
            }
            for r in ads_fat
        ],
        "aging": [{"faixa": r[0], "faturas": int(r[1]), "valor_ecv": float(r[2] or 0)} for r in ads_div],
    }

    # 5. Operacional CEA & OS
    cea_anos = con.execute("""
        SELECT
            COALESCE(EXTRACT(YEAR FROM dt_inspecao)::INTEGER, 0) AS ano,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE UPPER(COALESCE(resultado_inspecao, '')) LIKE '%EXECUT%') AS executadas,
            COUNT(*) FILTER (WHERE LOWER(COALESCE(situacao_consumidor, '')) LIKE '%regulariz%' OR LOWER(COALESCE(situacao_consumidor, '')) LIKE '%fraude%' OR LOWER(COALESCE(situacao_consumidor, '')) LIKE '%irregular%') AS com_desfecho
        FROM fct_inspecao_cea
        GROUP BY ano
        ORDER BY ano
    """).fetchall()

    os_res = con.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE dt_exec IS NOT NULL) AS executadas,
            ROUND(AVG(CASE WHEN sla_dias >= 0 AND sla_dias <= 365 THEN sla_dias END), 1) AS sla_medio_dias,
            ROUND(MEDIAN(CASE WHEN sla_dias >= 0 AND sla_dias <= 365 THEN sla_dias END), 1) AS sla_mediana_dias
        FROM fct_ordem_servico
    """).fetchone()

    # 6. KPIs Executivos Consolidados (E017 Taxa de Cobrança Real + DSO + Totais)
    fat_17_tot = sum(r["valor_ecv"] for r in faturacao_mensal if r["emp"] == "17")
    fat_17_kwh = sum(r["consumo_qtd"] for r in faturacao_mensal if r["emp"] == "17")
    lotes_17 = sorted({r["lote_ym"] for r in faturacao_mensal if r["emp"] == "17"})
    ultimos_3_lotes = set(lotes_17[-3:])
    fat_17_90d = sum(r["valor_ecv"] for r in faturacao_mensal if r["emp"] == "17" and r["lote_ym"] in ultimos_3_lotes)

    cob_17 = sum(r["valor_ecv"] for r in cobranca_mensal if r["emp"] == "17")
    cob_21 = sum(r["valor_ecv"] for r in cobranca_mensal if r["emp"] == "21")
    cob_07 = sum(r["valor_ecv"] for r in cobranca_mensal if r["emp"] == "7")
    cob_70 = sum(r["valor_ecv"] for r in cobranca_mensal if r["emp"] == "70")
    cob_tot = cob_17 + cob_21 + cob_07 + cob_70

    div_17 = sum(r["emp_17"] for r in aging_divida)
    div_21 = sum(r["emp_21"] for r in aging_divida)
    div_07 = sum(r["emp_07"] for r in aging_divida)
    div_70 = sum(r["emp_70"] for r in aging_divida)
    div_tot = div_17 + div_21 + div_07 + div_70
    div_presc = sum(r["total_ecv"] for r in aging_divida if r["faixa"] == "> 5 anos")

    taxa_cob_17 = round((cob_17 / fat_17_tot) * 100.0, 1) if fat_17_tot > 0 else 0.0
    dso_17 = round((div_17 / fat_17_90d) * 90.0, 0) if fat_17_90d > 0 else 0.0

    con.close()

    dq_path = os.path.join(silver_dir, "relatorio_dq.json")
    dq_data = {}
    if os.path.exists(dq_path):
        with open(dq_path, "r", encoding="utf-8") as f:
            dq_data = json.load(f)

    score_v2_path = os.path.join(gold_dir, "score_v2_metricas.json")
    score_v2_data = {}
    if os.path.exists(score_v2_path):
        with open(score_v2_path, "r", encoding="utf-8") as f:
            score_v2_data = json.load(f)

    balanco_pt_path = os.path.join(gold_dir, "balanco_pt.json")
    balanco_pt_data = {}
    if os.path.exists(balanco_pt_path):
        with open(balanco_pt_path, "r", encoding="utf-8") as f:
            balanco_pt_data = json.load(f)

    prepago_path = os.path.join(gold_dir, "prepago.json")
    prepago_data = {}
    if os.path.exists(prepago_path):
        with open(prepago_path, "r", encoding="utf-8") as f:
            prepago_data = json.load(f)

    # Monitor de frescura das fontes (a partir de manifesto_fontes.json + pastas lake)
    frescura_fontes = []
    manifesto_path = os.path.join(base_santiago, "manifesto_fontes.json")
    if os.path.exists(manifesto_path):
        try:
            with open(manifesto_path, "r", encoding="utf-8") as fm:
                man = json.load(fm)
            por_cat = {}
            for item in man.get("fontes", []):
                cat = item.get("categoria", "OUTROS")
                mod = item.get("modificado_em", "")
                if mod and (cat not in por_cat or mod > por_cat[cat]["mod"]):
                    por_cat[cat] = {"mod": mod, "fich": item.get("ficheiro", "")}
            hoje_dt = datetime.now()
            for cat, info_c in sorted(por_cat.items()):
                try:
                    dt_mod = datetime.strptime(info_c["mod"], "%Y-%m-%d %H:%M:%S")
                    dias = (hoje_dt - dt_mod).days
                except Exception:
                    dias = -1
                frescura_fontes.append({
                    "categoria": cat,
                    "ultimo_ficheiro": info_c["fich"],
                    "modificado_em": info_c["mod"],
                    "dias_idade": dias,
                    "alerta_atraso": bool(dias > 35),
                })
        except Exception:
            pass

    snap_dir = os.path.join(silver_dir, "snapshots_divida")
    qtd_snapshots = len([f for f in os.listdir(snap_dir) if f.endswith(".parquet")]) if os.path.isdir(snap_dir) else 0

    marts = {
        "kpis_executivos": {
            "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fat_17_ecv": round(fat_17_tot, 2),
            "fat_17_kwh": round(fat_17_kwh, 2),
            "fat_17_preco_medio": round(fat_17_tot / fat_17_kwh, 2) if fat_17_kwh > 0 else 0.0,
            "fat_17_90d_ecv": round(fat_17_90d, 2),
            "fat_21_ads_ecv": round(ads_fat_tot, 2),
            "fat_21_ads_m3": round(ads_m3_tot, 2),
            "cob_17_ecv": round(cob_17, 2),
            "cob_21_ecv": round(cob_21, 2),
            "cob_07_ecv": round(cob_07, 2),
            "cob_70_ecv": round(cob_70, 2),
            "cob_total_ecv": round(cob_tot, 2),
            "taxa_cobranca_17_pct": taxa_cob_17,
            "dso_17_dias": int(dso_17),
            "divida_total_ecv": round(div_tot, 2),
            "divida_17_ecv": round(div_17, 2),
            "divida_21_ecv": round(div_21, 2),
            "divida_07_ecv": round(div_07, 2),
            "divida_70_ecv": round(div_70, 2),
            "divida_prescrita_ecv": round(div_presc, 2),
            "divida_exigivel_ecv": round(div_tot - div_presc, 2),
        },
        "faturacao_mensal": {"rows": faturacao_mensal},
        "cobranca_mensal": {"rows": cobranca_mensal},
        "aging_divida": {"rows": aging_divida},
        "ads_conta_corrente": ads_conta_corrente,
        "operacional_cea_os": {
            "cea_por_ano": [
                {"ano": int(r[0]), "total": int(r[1]), "executadas": int(r[2]), "com_desfecho": int(r[3])}
                for r in cea_anos if r[0] > 0
            ],
            "os_resumo": {
                "total": int(os_res[0] or 0),
                "executadas": int(os_res[1] or 0),
                "sla_medio_dias": float(os_res[2] or 0.0),
                "sla_mediana_dias": float(os_res[3] or 0.0),
            },
            "qualidade_dados": dq_data,
            "frescura_fontes": frescura_fontes,
            "snapshots_divida_arquivados": qtd_snapshots,
        },
        "score_v2_validacao": score_v2_data,
        "balanco_pt_trimestral": balanco_pt_data,
        "prepago_analise": prepago_data,
    }

    out_gold = os.path.join(gold_dir, "marts_gold.json")
    with open(out_gold, "w", encoding="utf-8") as f:
        json.dump(marts, f, ensure_ascii=False, indent=2)

    k = marts["kpis_executivos"]
    print(f" GOLD CONCLUÍDA em {time.time() - t0:.2f}s -> {out_gold}")
    print(f"   - Taxa Cobrança Real E017 (2026): {k['taxa_cobranca_17_pct']}% ({k['cob_17_ecv']/1e9:.2f}B / {k['fat_17_ecv']/1e9:.2f}B ECV)")
    print(f"   - DSO EDEC Sul (17): {k['dso_17_dias']} dias | Preço Médio Real: {k['fat_17_preco_medio']} ECV/kWh")
    print(f"   - AdS (21): Faturado={k['fat_21_ads_ecv']/1e6:.1f}M ECV ({k['fat_21_ads_m3']/1e6:.2f}M m³) | Dívida={k['divida_21_ecv']/1e6:.1f}M ECV")
    return marts


def sincronizar_marts_supabase(base_santiago: str, marts: dict) -> bool:
    env_path = os.path.join(base_santiago, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    url = os.environ.get("SUPABASE_URL", "https://esbbohmkgbcrpegqvagk.supabase.co").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    etl_token = os.environ.get("ETL_SECRET_TOKEN", "").strip()
    anon_key = os.environ.get("SUPABASE_KEY", "").strip()

    if not service_key and not etl_token:
        print("  [AVISO] SUPABASE_SERVICE_KEY e ETL_SECRET_TOKEN ausentes no .env; Marts Gold salvos apenas localmente.")
        return False

    payload = [
        {
            "chave": chave,
            "dados": dados,
            "atualizado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for chave, dados in marts.items()
    ]
    sucesso = 0
    for item in payload:
        ok_item = False
        for tentativa in range(2):
            try:
                if etl_token and not service_key:
                    resp = requests.post(
                        f"{url}/rest/v1/rpc/etl_upsert_marts_gold",
                        headers={
                            "apikey": anon_key,
                            "Authorization": f"Bearer {anon_key}",
                            "Content-Type": "application/json",
                        },
                        json={"p_etl_token": etl_token, "p_lote": [item]},
                        timeout=60,
                    )
                else:
                    resp = requests.post(
                        f"{url}/rest/v1/santiago_marts_gold?on_conflict=chave",
                        headers={
                            "apikey": service_key,
                            "Authorization": f"Bearer {service_key}",
                            "Content-Type": "application/json",
                            "Prefer": "resolution=merge-duplicates,return=minimal",
                        },
                        json=[item],
                        timeout=60,
                    )
                if resp.status_code in (200, 201, 204):
                    ok_item = True
                    break
                if resp.status_code >= 500 and tentativa == 0:
                    time.sleep(1.5)
                    continue
                print(f"  [ERRO] Falha ao sincronizar '{item['chave']}': HTTP {resp.status_code} {resp.text[:200]}")
                break
            except Exception as exc:
                if tentativa == 0:
                    time.sleep(1.5)
                    continue
                print(f"  [ERRO] Exceção ao sincronizar '{item['chave']}': {exc}")
        if ok_item:
            sucesso += 1

    if sucesso == len(payload):
        print(f"  [OK] {len(payload)} Marts Gold sincronizados em public.santiago_marts_gold!")
        return True
    print(f"  [AVISO] {sucesso}/{len(payload)} Marts Gold sincronizados.")
    return False
