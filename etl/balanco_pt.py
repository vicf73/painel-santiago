"""
Módulo 2 - Balanço Energético Real por Posto de Transformação (PT)
Substitui o VBA de PT_KWh.xlsm:
  1. Lê cadastro Contador SL7000 <-> PT <-> CONTADOR_IP de PT_KWh.xlsm (aba 'base (2)')
  2. Lê leituras EOB (OBIS 1.1.1.8.0.255) dos ficheiros SL7000 em leitura_pt/ e BL_ENRG/
     com cache incremental Parquet em lake/bronze/balanco_pt/
  3. Calcula Injetada vs Faturada (E017 + IP) por PT nos trimestres 2026-T1, 2026-T2, 2026-T3
  4. Grava mart_balanco_pt no DuckDB Silver e exporta para a Camada Gold / Supabase.
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime, timezone

import duckdb
import openpyxl
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


OBIS_ENERGIA_ATIVA = "1.1.1.8.0.255"

TRIMESTRES_2026 = [
    {
        "codigo": "2026-T3",
        "label": "3º Trimestre 2026 (Jul–Set)",
        "dt_ini": "01-07-2026",
        "dt_fim": "01-10-2026",
        "lotes_fat": ["202608", "202609", "202610"],
    },
    {
        "codigo": "2026-T2",
        "label": "2º Trimestre 2026 (Abr–Jun)",
        "dt_ini": "01-04-2026",
        "dt_fim": "01-07-2026",
        "lotes_fat": ["202605", "202606", "202607"],
    },
    {
        "codigo": "2026-T1",
        "label": "1º Trimestre 2026 (Jan–Mar)",
        "dt_ini": "01-01-2026",
        "dt_fim": "01-04-2026",
        "lotes_fat": ["202602", "202603", "202604"],
    },
]


def _extrair_leituras_sl7000_ficheiro(fp: str) -> list[tuple[str, str, float]]:
    """Extrai (num_contador, aba_data, leitura_kwh) de um ficheiro SL7000 EOB."""
    nome = os.path.basename(fp)
    m = re.search(r"_(\d+)_EOB_", nome)
    if not m:
        return []
    num_cont = m.group(1)
    regs = []
    try:
        wb = openpyxl.load_workbook(fp, data_only=True, read_only=True)
        for s in wb.sheetnames:
            if not re.match(r"^\d{2}-\d{2}-\d{4}$", s.strip()):
                continue
            ws = wb[s]
            for row in ws.iter_rows(min_row=1, max_row=65, min_col=1, max_col=4, values_only=True):
                if row and any(c is not None and OBIS_ENERGIA_ATIVA in str(c) for c in row[:3]):
                    for val in row[1:]:
                        if val is not None and OBIS_ENERGIA_ATIVA not in str(val):
                            s_val = str(val).replace("kWh", "").replace(",", ".").strip()
                            try:
                                regs.append((num_cont, s.strip(), float(s_val)))
                                break
                            except ValueError:
                                pass
                    break
        wb.close()
    except Exception:
        pass
    return regs


def _carregar_cadastro_pts(base_atual: str) -> pd.DataFrame:
    bl_dir = os.path.join(base_atual, "BL_ENRG")
    candidatos = [
        (os.path.join(bl_dir, "PT_KWh.xlsm"), "base (2)"),
        (os.path.join(bl_dir, "balança_1º_trim_2025.xlsx"), "base"),
    ]
    for fp, aba in candidatos:
        if os.path.exists(fp):
            try:
                df = pd.read_excel(fp, sheet_name=aba, usecols=["CONTA_GERAL", "nome PT abreviado", "CONTADOR_IP", "localidade"])
                df = df.dropna(subset=["CONTA_GERAL", "nome PT abreviado"]).copy()
                df["num_contador"] = df["CONTA_GERAL"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
                df["pt"] = df["nome PT abreviado"].astype(str).str.strip()
                df["contador_ip"] = df["CONTADOR_IP"].fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
                df["localidade"] = df["localidade"].fillna("").astype(str).str.strip()
                return df[["num_contador", "pt", "contador_ip", "localidade"]].drop_duplicates("num_contador")
            except Exception:
                continue
    return pd.DataFrame(columns=["num_contador", "pt", "contador_ip", "localidade"])


def _carregar_leituras_cache(base_santiago: str, base_atual: str) -> pd.DataFrame:
    bronze_pt_dir = os.path.join(base_santiago, "lake", "bronze", "balanco_pt")
    os.makedirs(bronze_pt_dir, exist_ok=True)
    out_pq = os.path.join(bronze_pt_dir, "leituras_sl7000.parquet")
    estado_path = os.path.join(bronze_pt_dir, "_estado_sl7000.json")

    pastas_busca = [
        os.path.join(base_santiago, "_arquivo_antigo", "leitura_pt"),
        os.path.join(base_atual, "BL_ENRG", "1º TRI"),
        os.path.join(base_atual, "BL_ENRG", "2º TRI"),
        os.path.join(base_atual, "BL_ENRG", "4º TRI_"),
    ]
    arqs = []
    for p in pastas_busca:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                if os.path.basename(root).lower() == "erro":
                    continue
                for f in files:
                    if f.lower().endswith(".xlsx") and not f.startswith("~$") and "_EOB_" in f:
                        arqs.append(os.path.join(root, f))
    arqs = sorted(arqs)

    assinatura = {
        os.path.relpath(f, base_santiago if f.startswith(base_santiago) else base_atual): f"{os.path.getsize(f)}_{int(os.path.getmtime(f))}"
        for f in arqs
    }

    if os.path.exists(out_pq) and os.path.exists(estado_path):
        try:
            with open(estado_path, "r", encoding="utf-8") as fe:
                if json.load(fe) == assinatura:
                    return pd.read_parquet(out_pq)
        except Exception:
            pass

    todos = []
    for fp in arqs:
        todos.extend(_extrair_leituras_sl7000_ficheiro(fp))

    df_l = pd.DataFrame(todos, columns=["num_contador", "dt_leitura", "leitura_kwh"])
    if len(df_l) > 0:
        df_l = df_l.drop_duplicates(subset=["num_contador", "dt_leitura"], keep="last").reset_index(drop=True)
    pq.write_table(pa.Table.from_pandas(df_l, preserve_index=False), out_pq, compression="zstd")
    with open(estado_path, "w", encoding="utf-8") as fe:
        json.dump(assinatura, fe, ensure_ascii=False)
    return df_l


def executar_balanco_pt(base_santiago: str, base_atual: str) -> dict:
    t0 = time.time()
    print("=" * 72)
    print(" MÓDULO 2 - BALANÇO ENERGÉTICO REAL POR PT (SL7000 vs FATURAÇÃO)")
    print("=" * 72)

    df_cad = _carregar_cadastro_pts(base_atual)
    df_leit = _carregar_leituras_cache(base_santiago, base_atual)

    silver_dir = os.path.join(base_santiago, "lake", "silver")
    db_path = os.path.join(silver_dir, "santiago.duckdb")
    con = duckdb.connect(db_path)

    con.register("df_cad_reg", df_cad)
    con.register("df_leit_reg", df_leit)
    con.execute("CREATE OR REPLACE TABLE dim_pt_contador AS SELECT * FROM df_cad_reg")
    con.execute("CREATE OR REPLACE TABLE fct_leitura_pt_eob AS SELECT * FROM df_leit_reg")

    # Coordenadas médias e dívida atual por PT a partir de dim_local_consumo + fct_divida_snapshot
    con.execute("""
        CREATE OR REPLACE TEMP TABLE tmp_pt_geo_div AS
        WITH div_cil AS (
            SELECT cil, SUM(val_divida_ecv) AS divida_ecv
            FROM fct_divida_snapshot
            GROUP BY cil
        )
        SELECT
            lc.pt,
            COUNT(*) AS qtd_clientes,
            ROUND(AVG(TRY_CAST(REPLACE(lc.lat, ',', '.') AS DOUBLE)), 6) AS lat,
            ROUND(AVG(TRY_CAST(REPLACE(lc.lon, ',', '.') AS DOUBLE)), 6) AS lon,
            ROUND(SUM(COALESCE(d.divida_ecv, 0)), 0) AS divida_ecv
        FROM dim_local_consumo lc
        LEFT JOIN div_cil d ON lc.cil = d.cil
        WHERE lc.pt IS NOT NULL
        GROUP BY lc.pt
    """)

    # Mapear CONTADOR_IP -> CIL (para somar IP dos PTs onde o CIL não está com pt atribuído)
    bronze_dir = os.path.join(base_santiago, "lake", "bronze").replace("\\", "/")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE tmp_ip_cil AS
        SELECT DISTINCT ON (TRIM(a.CONTADOR))
            TRIM(a.CONTADOR) AS contador_ip,
            TRY_CAST(a.CIL AS BIGINT) AS cil_ip,
            lc.pt AS pt_atual_cil
        FROM read_parquet('{bronze_dir}/aparelho/aparelho.parquet') a
        LEFT JOIN dim_local_consumo lc ON TRY_CAST(a.CIL AS BIGINT) = lc.cil
        WHERE TRY_CAST(a.CIL AS BIGINT) IS NOT NULL
    """)

    resultados_trim = {}
    for tri in TRIMESTRES_2026:
        cod = tri["codigo"]
        lotes_sql = ",".join(f"'{m}'" for m in tri["lotes_fat"])
        rows = con.execute(f"""
            WITH inj AS (
                SELECT
                    c.pt,
                    c.num_contador,
                    c.localidade,
                    c.contador_ip,
                    l_ini.leitura_kwh AS leit_ini,
                    l_fim.leitura_kwh AS leit_fim,
                    (l_fim.leitura_kwh - l_ini.leitura_kwh) AS injetada_kwh
                FROM dim_pt_contador c
                JOIN fct_leitura_pt_eob l_ini ON c.num_contador = l_ini.num_contador AND l_ini.dt_leitura = '{tri['dt_ini']}'
                JOIN fct_leitura_pt_eob l_fim ON c.num_contador = l_fim.num_contador AND l_fim.dt_leitura = '{tri['dt_fim']}'
                WHERE (l_fim.leitura_kwh - l_ini.leitura_kwh) > 0
            ),
            fat_pt AS (
                SELECT
                    lc.pt,
                    SUM(f.consumo_qtd) AS fat_clientes_kwh
                FROM fct_fatura f
                JOIN dim_local_consumo lc ON f.cil = lc.cil
                WHERE f.emp = '17'
                  AND f.lote_ym IN ({lotes_sql})
                  AND lc.pt IS NOT NULL
                GROUP BY lc.pt
            ),
            fat_ip AS (
                SELECT
                    i.pt,
                    SUM(CASE WHEN ip.pt_atual_cil IS DISTINCT FROM i.pt THEN COALESCE(f.consumo_qtd, 0) ELSE 0 END) AS fat_ip_extra_kwh
                FROM inj i
                LEFT JOIN tmp_ip_cil ip ON i.contador_ip = ip.contador_ip
                LEFT JOIN fct_fatura f ON ip.cil_ip = f.cil AND f.emp = '17' AND f.lote_ym IN ({lotes_sql})
                GROUP BY i.pt
            )
            SELECT
                i.pt,
                i.num_contador,
                i.localidade,
                ROUND(i.injetada_kwh, 1) AS injetada_kwh,
                ROUND(COALESCE(fp.fat_clientes_kwh, 0) + COALESCE(fi.fat_ip_extra_kwh, 0), 1) AS faturada_kwh,
                COALESCE(g.qtd_clientes, 0) AS qtd_clientes,
                COALESCE(g.divida_ecv, 0) AS divida_ecv,
                g.lat,
                g.lon
            FROM inj i
            LEFT JOIN fat_pt fp ON i.pt = fp.pt
            LEFT JOIN fat_ip fi ON i.pt = fi.pt
            LEFT JOIN tmp_pt_geo_div g ON i.pt = g.pt
            ORDER BY (i.injetada_kwh - (COALESCE(fp.fat_clientes_kwh, 0) + COALESCE(fi.fat_ip_extra_kwh, 0))) DESC
        """).fetchall()

        lista_pts = []
        tot_inj_valid = 0.0
        tot_fat_valid = 0.0
        for r in rows:
            pt, cont, loc, inj, fat, qcli, div, lat, lon = r
            inj_f = float(inj or 0)
            fat_f = float(fat or 0)
            perda = inj_f - fat_f
            taxa = (perda / inj_f * 100.0) if inj_f > 0 else 0.0
            if int(qcli or 0) < 10 or fat_f <= 0:
                status = "sem_cobertura"
            elif taxa >= 30.0:
                status = "critico"
            elif taxa >= 15.0:
                status = "alerta"
            else:
                status = "normal"

            if status != "sem_cobertura" and perda >= -0.05 * inj_f:
                tot_inj_valid += inj_f
                tot_fat_valid += fat_f

            lista_pts.append({
                "pt": pt,
                "contador": cont,
                "localidade": loc or "",
                "injetada_kwh": inj_f,
                "faturada_kwh": fat_f,
                "perda_kwh": round(perda, 1),
                "taxa_perda_pct": round(taxa, 1),
                "qtd_clientes": int(qcli or 0),
                "divida_ecv": float(div or 0),
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
                "status": status,
            })

        perda_glob = tot_inj_valid - tot_fat_valid
        taxa_glob = (perda_glob / tot_inj_valid * 100.0) if tot_inj_valid > 0 else 0.0
        com_cob = [x for x in lista_pts if x["status"] != "sem_cobertura"]
        resultados_trim[cod] = {
            "codigo": cod,
            "label": tri["label"],
            "pts_medidos": len(lista_pts),
            "pts_com_cobertura": len(com_cob),
            "injetada_mwh": round(tot_inj_valid / 1000.0, 1),
            "faturada_mwh": round(tot_fat_valid / 1000.0, 1),
            "perda_mwh": round(perda_glob / 1000.0, 1),
            "taxa_perda_pct": round(taxa_glob, 1),
            "pts": lista_pts,
        }
        print(
            f"   - {cod} ({tri['label']}): {len(lista_pts)} PTs medidos ({len(com_cob)} c/ cobertura) | "
            f"Inj={tot_inj_valid/1000:,.1f} MWh | Fat={tot_fat_valid/1000:,.1f} MWh | Perda={taxa_glob:.1f}%"
        )

    con.close()

    gold_dir = os.path.join(base_santiago, "lake", "gold")
    os.makedirs(gold_dir, exist_ok=True)
    out_json = os.path.join(gold_dir, "balanco_pt.json")
    payload = {
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trimestres": resultados_trim,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f" MÓDULO 2 CONCLUÍDO em {time.time() - t0:.2f}s -> {out_json}")
    return payload
