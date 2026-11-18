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


def _convex_hull(pontos: list[tuple[float, float]]) -> list[list[float]]:
    """Calcula a envoltória convexa (Monotone Chain) para gerar o polígono real do PT."""
    pts = sorted(set((round(lat, 5), round(lon, 5)) for lat, lon in pontos))
    if len(pts) < 3:
        return [[p[0], p[1]] for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return [[p[0], p[1]] for p in hull]


def _carregar_poligonos_geojson(base_santiago: str) -> dict[str, list]:
    """Lê polígonos oficiais (GeoJSON WGS84) e converte [lon, lat] -> [lat, lon] para Leaflet."""
    candidatos = [
        os.path.join(base_santiago, "poligonos.geojson"),
        os.path.join(base_santiago, "_arquivo_antigo", "poligonos.geojson"),
    ]
    fp = next((p for p in candidatos if os.path.exists(p)), None)
    if not fp:
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            gj = json.load(f)
    except Exception:
        return {}

    mapa = {}
    for feat in gj.get("features", []):
        props = feat.get("properties") or {}
        nome_raw = props.get("POLIG_NOVO") or props.get("PT") or props.get("nome") or ""
        pt_k = re.sub(r"[\r\n\t]+", "", str(nome_raw).strip()).lower()
        if not pt_k:
            continue
        geom = feat.get("geometry") or {}
        gtype = geom.get("type", "")
        coords = geom.get("coordinates") or []
        aneis = []
        if gtype == "Polygon" and coords:
            aneis.append([[round(float(pt[1]), 6), round(float(pt[0]), 6)] for pt in coords[0] if len(pt) >= 2])
        elif gtype == "MultiPolygon" and coords:
            for poly in coords:
                if poly and poly[0]:
                    aneis.append([[round(float(pt[1]), 6), round(float(pt[0]), 6)] for pt in poly[0] if len(pt) >= 2])
        aneis = [a for a in aneis if len(a) >= 3]
        if aneis:
            if pt_k in mapa:
                mapa[pt_k].extend(aneis)
            else:
                mapa[pt_k] = aneis
    return mapa

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
            LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) AS pt_norm,
            ANY_VALUE(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) AS pt,
            COUNT(*) AS qtd_clientes,
            ROUND(AVG(TRY_CAST(REPLACE(lc.lat, ',', '.') AS DOUBLE)), 6) AS lat,
            ROUND(AVG(TRY_CAST(REPLACE(lc.lon, ',', '.') AS DOUBLE)), 6) AS lon,
            ROUND(SUM(COALESCE(d.divida_ecv, 0)), 0) AS divida_ecv
        FROM dim_local_consumo lc
        LEFT JOIN div_cil d ON lc.cil = d.cil
        WHERE lc.pt IS NOT NULL
          AND COALESCE(lc.produto, '') <> 'EM'
          AND COALESCE(lc.tarifa, '') NOT LIKE 'M%'
        GROUP BY 1
    """)

    # Idade dos medidores (> 20 anos) e leitura desatualizada (> 5 meses) por PT
    bronze_dir = os.path.join(base_santiago, "lake", "bronze").replace("\\", "/")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE tmp_pt_aparelho AS
        WITH ap_cil AS (
            SELECT
                TRY_CAST(CIL AS BIGINT) AS cil,
                MAX(TRY_STRPTIME(NULLIF(TRIM(DA_INST), ''), '%Y%m%d')) AS dt_inst,
                MAX(TRY_STRPTIME(NULLIF(TRIM(DATA_LEIT), ''), '%Y%m%d')) AS dt_leit
            FROM read_parquet('{bronze_dir}/aparelho/aparelho.parquet')
            WHERE TRY_CAST(CIL AS BIGINT) IS NOT NULL
            GROUP BY 1
        ),
        ref_dt AS (
            SELECT COALESCE(MAX(dt_leit), CURRENT_DATE) AS dt_ref
            FROM ap_cil
            WHERE dt_leit <= CURRENT_DATE + INTERVAL '30 days'
        )
        SELECT
            LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) AS pt_norm,
            SUM(CASE WHEN a.dt_inst BETWEEN DATE '1950-01-01' AND (SELECT dt_ref - INTERVAL '20 years' FROM ref_dt) THEN 1 ELSE 0 END) AS qtd_med_20a,
            SUM(CASE WHEN a.dt_leit BETWEEN DATE '1990-01-01' AND (SELECT dt_ref - INTERVAL '5 months' FROM ref_dt) THEN 1 ELSE 0 END) AS qtd_leit_5m
        FROM dim_local_consumo lc
        JOIN ap_cil a ON lc.cil = a.cil
        WHERE lc.pt IS NOT NULL
          AND COALESCE(lc.produto, '') <> 'EM'
          AND COALESCE(lc.tarifa, '') NOT LIKE 'M%'
        GROUP BY 1
    """)

    # Pontos geográficos válidos em Santiago para construir polígonos reais de cada PT
    pts_geo_rows = con.execute("""
        SELECT
            LOWER(REGEXP_REPLACE(TRIM(pt), '[\r\n\t]+', '', 'g')) AS pt_norm,
            TRY_CAST(REPLACE(lat, ',', '.') AS DOUBLE) AS lat_v,
            TRY_CAST(REPLACE(lon, ',', '.') AS DOUBLE) AS lon_v
        FROM dim_local_consumo
        WHERE pt IS NOT NULL
          AND COALESCE(produto, '') <> 'EM'
          AND COALESCE(tarifa, '') NOT LIKE 'M%'
          AND TRY_CAST(REPLACE(lat, ',', '.') AS DOUBLE) BETWEEN 14.85 AND 15.36
          AND TRY_CAST(REPLACE(lon, ',', '.') AS DOUBLE) BETWEEN -23.82 AND -23.40
    """).fetchall()
    from collections import defaultdict
    mapa_pts_coords = defaultdict(list)
    for pt_n, la, lo in pts_geo_rows:
        mapa_pts_coords[pt_n].append((float(la), float(lo)))
    mapa_poligonos_hull = {
        pt_n: _convex_hull(coords)
        for pt_n, coords in mapa_pts_coords.items()
    }
    mapa_poligonos_gj = _carregar_poligonos_geojson(base_santiago)
    if mapa_poligonos_gj:
        print(f"   - Polígonos GeoJSON carregados: {len(mapa_poligonos_gj)} PTs oficiais")

    # Mapear CONTADOR_IP -> CIL (para somar IP dos PTs onde o CIL não está com pt atribuído)
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

    # Cruzamento por PT: Score de Risco v2 + Inspeções CEA + Top 10 CILs de risco por PT
    con.execute("""
        CREATE OR REPLACE TEMP TABLE tmp_pt_risco_insp AS
        WITH insp_cil AS (
            SELECT
                cil,
                COUNT(*) AS total_insp,
                SUM(CASE WHEN UPPER(COALESCE(resultado_inspecao, '')) LIKE '%FRAUDE%'
                           OR UPPER(COALESCE(resultado_inspecao, '')) LIKE '%ROUBO%' THEN 1 ELSE 0 END) AS fraude_insp
            FROM fct_inspecao_cea
            GROUP BY cil
        )
        SELECT
            LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) AS pt_norm,
            SUM(CASE WHEN COALESCE(s.score_v2, 0) >= 70 THEN 1 ELSE 0 END) AS qtd_risco_alto,
            SUM(COALESCE(ic.total_insp, 0)) AS insp_total,
            SUM(COALESCE(ic.fraude_insp, 0)) AS insp_fraude
        FROM dim_local_consumo lc
        LEFT JOIN mart_score_v2 s ON lc.cil = s.cil
        LEFT JOIN insp_cil ic ON lc.cil = ic.cil
        WHERE lc.pt IS NOT NULL
          AND COALESCE(lc.produto, '') <> 'EM'
          AND COALESCE(lc.tarifa, '') NOT LIKE 'M%'
        GROUP BY 1
    """)

    # Idade dos medidores (> 20 anos) e leitura desatualizada (> 5 meses) por PT
    bronze_dir = os.path.join(base_santiago, "lake", "bronze").replace("\\", "/")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE tmp_pt_aparelho AS
        WITH ap_cil AS (
            SELECT
                TRY_CAST(CIL AS BIGINT) AS cil,
                MAX(TRY_STRPTIME(NULLIF(TRIM(DA_INST), ''), '%Y%m%d')) AS dt_inst,
                MAX(TRY_STRPTIME(NULLIF(TRIM(DATA_LEIT), ''), '%Y%m%d')) AS dt_leit
            FROM read_parquet('{bronze_dir}/aparelho/aparelho.parquet')
            WHERE TRY_CAST(CIL AS BIGINT) IS NOT NULL
            GROUP BY 1
        ),
        ref_dt AS (
            SELECT COALESCE(MAX(dt_leit), CURRENT_DATE) AS dt_ref
            FROM ap_cil
            WHERE dt_leit <= CURRENT_DATE + INTERVAL '30 days'
        )
        SELECT
            LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) AS pt_norm,
            SUM(CASE WHEN a.dt_inst BETWEEN DATE '1950-01-01' AND (SELECT dt_ref - INTERVAL '20 years' FROM ref_dt) THEN 1 ELSE 0 END) AS qtd_med_20a,
            SUM(CASE WHEN a.dt_leit BETWEEN DATE '1990-01-01' AND (SELECT dt_ref - INTERVAL '5 months' FROM ref_dt) THEN 1 ELSE 0 END) AS qtd_leit_5m
        FROM dim_local_consumo lc
        JOIN ap_cil a ON lc.cil = a.cil
        WHERE lc.pt IS NOT NULL
          AND COALESCE(lc.produto, '') <> 'EM'
          AND COALESCE(lc.tarifa, '') NOT LIKE 'M%'
        GROUP BY 1
    """)

    top_cils_rows = con.execute("""
        WITH medidos AS (
            SELECT DISTINCT LOWER(REGEXP_REPLACE(TRIM(pt), '[\r\n\t]+', '', 'g')) AS pt_norm
            FROM dim_pt_contador
        ),
        div_cil AS (
            SELECT cil, SUM(val_divida_ecv) AS divida_ecv
            FROM fct_divida_snapshot
            GROUP BY cil
        ),
        ranked AS (
            SELECT
                LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) AS pt_norm,
                lc.cil,
                COALESCE(lc.nome, '') AS nome,
                COALESCE(lc.tarifa, '') AS tarifa,
                COALESCE(s.score_v2, 0) AS score_v2,
                ROUND(COALESCE(s.prob_fraude_v2, 0) * 100, 1) AS prob_pct,
                COALESCE(s.motivos_v2, '') AS motivos_v2,
                ROUND(COALESCE(d.divida_ecv, 0), 0) AS divida_ecv,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g'))
                    ORDER BY COALESCE(s.score_v2, 0) DESC, COALESCE(d.divida_ecv, 0) DESC
                ) AS rn
            FROM dim_local_consumo lc
            JOIN medidos m ON LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) = m.pt_norm
            LEFT JOIN mart_score_v2 s ON lc.cil = s.cil
            LEFT JOIN div_cil d ON lc.cil = d.cil
            WHERE lc.pt IS NOT NULL
              AND COALESCE(lc.produto, '') <> 'EM'
              AND COALESCE(lc.tarifa, '') NOT LIKE 'M%'
              AND COALESCE(s.score_v2, 0) > 0
        )
        SELECT pt_norm, cil, nome, tarifa, score_v2, prob_pct, motivos_v2, divida_ecv
        FROM ranked
        WHERE rn <= 10
        ORDER BY pt_norm, rn
    """).fetchall()

    from collections import defaultdict as _dd_cils
    mapa_top_cils = _dd_cils(list)
    for pt_n, cil, nome, tarifa, sc, pr, mot, div_c in top_cils_rows:
        mapa_top_cils[pt_n].append({
            "cil": int(cil),
            "nome": str(nome)[:42],
            "tarifa": tarifa,
            "score_v2": int(sc),
            "prob_pct": float(pr),
            "motivos": str(mot)[:120],
            "divida_ecv": float(div_c),
        })

    TAXA_PERDA_TECNICA_REF = 0.05  # 5% referência técnica BT (DSO)
    PRECO_MEDIO_KWH = 35.81        # ECV/kWh real EDEC Sul

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
            fat_cil AS (
                SELECT
                    f.cil,
                    LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) AS pt_norm,
                    SUM(f.consumo_qtd) AS kwh_tri
                FROM fct_fatura f
                JOIN dim_local_consumo lc ON f.cil = lc.cil
                WHERE f.emp = '17'
                  AND f.lote_ym IN ({lotes_sql})
                  AND lc.pt IS NOT NULL
                  AND COALESCE(f.produto, '') <> 'EM'
                  AND COALESCE(lc.produto, '') <> 'EM'
                  AND COALESCE(lc.tarifa, '') NOT LIKE 'M%'
                GROUP BY 1, 2
            ),
            fat_pt AS (
                SELECT
                    pt_norm,
                    SUM(kwh_tri) AS fat_clientes_kwh,
                    SUM(CASE WHEN kwh_tri > 0 THEN 1 ELSE 0 END) AS clientes_fat_pos
                FROM fat_cil
                GROUP BY 1
            ),
            fat_ip AS (
                SELECT
                    i.pt,
                    MAX(i.contador_ip) AS contador_ip,
                    MAX(ip.cil_ip) AS cil_ip,
                    SUM(COALESCE(f.consumo_qtd, 0)) AS fat_ip_total_kwh,
                    SUM(CASE WHEN LOWER(COALESCE(ip.pt_atual_cil, '')) IS DISTINCT FROM LOWER(i.pt) THEN COALESCE(f.consumo_qtd, 0) ELSE 0 END) AS fat_ip_extra_kwh
                FROM inj i
                LEFT JOIN tmp_ip_cil ip ON i.contador_ip = ip.contador_ip
                LEFT JOIN fct_fatura f ON ip.cil_ip = f.cil AND f.emp = '17' AND f.lote_ym IN ({lotes_sql})
                GROUP BY i.pt
            )
            SELECT
                i.pt,
                i.num_contador,
                i.localidade,
                COALESCE(NULLIF(fi.contador_ip, ''), i.contador_ip) AS contador_ip,
                ROUND(COALESCE(fi.fat_ip_total_kwh, 0), 1) AS fat_ip_kwh,
                ROUND(i.injetada_kwh, 1) AS injetada_kwh,
                ROUND(COALESCE(fp.fat_clientes_kwh, 0) + COALESCE(fi.fat_ip_extra_kwh, 0), 1) AS faturada_kwh,
                COALESCE(g.qtd_clientes, 0) AS qtd_clientes,
                COALESCE(fp.clientes_fat_pos, 0) AS clientes_fat_pos,
                COALESCE(g.divida_ecv, 0) AS divida_ecv,
                g.lat,
                g.lon,
                COALESCE(ri.qtd_risco_alto, 0) AS qtd_risco_alto,
                COALESCE(ri.insp_total, 0) AS insp_total,
                COALESCE(ri.insp_fraude, 0) AS insp_fraude,
                COALESCE(ap.qtd_med_20a, 0) AS qtd_med_20a,
                COALESCE(ap.qtd_leit_5m, 0) AS qtd_leit_5m
            FROM inj i
            LEFT JOIN fat_pt fp ON LOWER(REGEXP_REPLACE(TRIM(i.pt), '[\r\n\t]+', '', 'g')) = fp.pt_norm
            LEFT JOIN fat_ip fi ON i.pt = fi.pt
            LEFT JOIN tmp_pt_geo_div g ON LOWER(REGEXP_REPLACE(TRIM(i.pt), '[\r\n\t]+', '', 'g')) = g.pt_norm
            LEFT JOIN tmp_pt_risco_insp ri ON LOWER(REGEXP_REPLACE(TRIM(i.pt), '[\r\n\t]+', '', 'g')) = ri.pt_norm
            LEFT JOIN tmp_pt_aparelho ap ON LOWER(REGEXP_REPLACE(TRIM(i.pt), '[\r\n\t]+', '', 'g')) = ap.pt_norm
            ORDER BY (i.injetada_kwh - (COALESCE(fp.fat_clientes_kwh, 0) + COALESCE(fi.fat_ip_extra_kwh, 0))) DESC
        """).fetchall()

        # Reconciliação global BT da ilha (energia medida vs não medida vs órfã sem PT)
        rec_row = con.execute(f"""
            WITH medidos AS (
                SELECT DISTINCT LOWER(REGEXP_REPLACE(TRIM(pt), '[\r\n\t]+', '', 'g')) AS pt_norm
                FROM dim_pt_contador
            )
            SELECT
                ROUND(SUM(f.consumo_qtd) / 1000.0, 1) AS total_bt_mwh,
                ROUND(SUM(CASE WHEN m.pt_norm IS NOT NULL THEN f.consumo_qtd ELSE 0 END) / 1000.0, 1) AS medidos_mwh,
                ROUND(SUM(CASE WHEN lc.pt IS NOT NULL AND m.pt_norm IS NULL THEN f.consumo_qtd ELSE 0 END) / 1000.0, 1) AS nao_medidos_mwh,
                ROUND(SUM(CASE WHEN lc.pt IS NULL OR TRIM(lc.pt) = '' THEN f.consumo_qtd ELSE 0 END) / 1000.0, 1) AS sem_pt_mwh,
                COUNT(DISTINCT CASE WHEN lc.pt IS NULL OR TRIM(lc.pt) = '' THEN f.cil END) AS cils_sem_pt
            FROM fct_fatura f
            LEFT JOIN dim_local_consumo lc ON f.cil = lc.cil
            LEFT JOIN medidos m ON LOWER(REGEXP_REPLACE(TRIM(lc.pt), '[\r\n\t]+', '', 'g')) = m.pt_norm
            WHERE f.emp = '17'
              AND f.lote_ym IN ({lotes_sql})
              AND COALESCE(f.produto, '') <> 'EM'
              AND COALESCE(lc.produto, '') <> 'EM'
              AND COALESCE(lc.tarifa, '') NOT LIKE 'M%'
        """).fetchone()

        lista_pts = []
        tot_inj_valid = 0.0
        tot_fat_valid = 0.0
        tot_tec_valid = 0.0
        for r in rows:
            (pt, cont, loc, cont_ip, fat_ip_kwh, inj, fat,
             qcli, qcli_pos, div, lat, lon, q_risco, n_insp, n_fraude, q_med20a, q_leit5m) = r
            inj_f = float(inj or 0)
            fat_f = float(fat or 0)
            fat_ip_f = float(fat_ip_kwh or 0)
            qcli_i = int(qcli or 0)
            qcli_pos_i = int(qcli_pos or 0)
            q_fat_zero = max(qcli_i - qcli_pos_i, 0)
            perda = inj_f - fat_f
            taxa = (perda / inj_f * 100.0) if inj_f > 0 else 0.0
            perda_tec = round(inj_f * TAXA_PERDA_TECNICA_REF, 1)
            perda_pnt = round(perda - perda_tec, 1)
            taxa_pnt = round((perda_pnt / inj_f * 100.0), 1) if inj_f > 0 else 0.0
            prejuizo_ecv = round(max(perda, 0.0) * PRECO_MEDIO_KWH, 0)
            prejuizo_pnt_ecv = round(max(perda_pnt, 0.0) * PRECO_MEDIO_KWH, 0)
            cons_medio_mes = round(max(fat_f - fat_ip_f, 0.0) / max(qcli_i, 1) / 3.0, 1) if qcli_i > 0 else 0.0
            peso_ip = round((fat_ip_f / fat_f * 100.0), 1) if fat_f > 0 else 0.0

            if qcli_i <= 0 or fat_f <= 0:
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
                tot_tec_valid += perda_tec

            pt_norm_k = re.sub(r"[\r\n\t]+", "", str(pt or "").strip()).lower()
            polig = mapa_poligonos_gj.get(pt_norm_k) or mapa_poligonos_hull.get(pt_norm_k, [])
            lista_pts.append({
                "pt": pt,
                "contador": cont,
                "contador_ip": cont_ip or "",
                "fat_ip_kwh": fat_ip_f,
                "peso_ip_pct": peso_ip,
                "localidade": loc or "",
                "injetada_kwh": inj_f,
                "faturada_kwh": fat_f,
                "perda_kwh": round(perda, 1),
                "taxa_perda_pct": round(taxa, 1),
                "perda_tecnica_kwh": perda_tec,
                "perda_pnt_kwh": perda_pnt,
                "taxa_pnt_pct": taxa_pnt,
                "prejuizo_ecv": prejuizo_ecv,
                "prejuizo_pnt_ecv": prejuizo_pnt_ecv,
                "qtd_clientes": qcli_i,
                "qtd_fat_zero": q_fat_zero,
                "qtd_med_20a": int(q_med20a or 0),
                "qtd_leit_5m": int(q_leit5m or 0),
                "consumo_medio_cli_mes": cons_medio_mes,
                "qtd_risco_alto": int(q_risco or 0),
                "insp_total": int(n_insp or 0),
                "insp_fraude": int(n_fraude or 0),
                "divida_ecv": float(div or 0),
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
                "poligono": polig,
                "status": status,
                "top_cils_risco": mapa_top_cils.get(pt_norm_k, []),
            })

        perda_glob = tot_inj_valid - tot_fat_valid
        perda_pnt_glob = perda_glob - tot_tec_valid
        taxa_glob = (perda_glob / tot_inj_valid * 100.0) if tot_inj_valid > 0 else 0.0
        taxa_pnt_glob = (perda_pnt_glob / tot_inj_valid * 100.0) if tot_inj_valid > 0 else 0.0
        com_cob = [x for x in lista_pts if x["status"] != "sem_cobertura"]
        resultados_trim[cod] = {
            "codigo": cod,
            "label": tri["label"],
            "pts_medidos": len(lista_pts),
            "pts_com_cobertura": len(com_cob),
            "injetada_mwh": round(tot_inj_valid / 1000.0, 1),
            "faturada_mwh": round(tot_fat_valid / 1000.0, 1),
            "perda_mwh": round(perda_glob / 1000.0, 1),
            "perda_tecnica_mwh": round(tot_tec_valid / 1000.0, 1),
            "perda_pnt_mwh": round(perda_pnt_glob / 1000.0, 1),
            "taxa_perda_pct": round(taxa_glob, 1),
            "taxa_pnt_pct": round(taxa_pnt_glob, 1),
            "prejuizo_total_ecv": round(max(perda_glob, 0.0) * PRECO_MEDIO_KWH, 0),
            "prejuizo_pnt_ecv": round(max(perda_pnt_glob, 0.0) * PRECO_MEDIO_KWH, 0),
            "reconciliacao": {
                "total_bt_mwh": float(rec_row[0] or 0),
                "medidos_mwh": float(rec_row[1] or 0),
                "nao_medidos_mwh": float(rec_row[2] or 0),
                "sem_pt_mwh": float(rec_row[3] or 0),
                "cils_sem_pt": int(rec_row[4] or 0),
            },
            "pts": lista_pts,
        }
        print(
            f"   - {cod} ({tri['label']}): {len(lista_pts)} PTs medidos ({len(com_cob)} c/ cobertura) | "
            f"Inj={tot_inj_valid/1000:,.1f} MWh | Fat={tot_fat_valid/1000:,.1f} MWh | "
            f"Perda={taxa_glob:.1f}% (Téc=5.0%, PNT={taxa_pnt_glob:.1f}%)"
        )

    # Enriquecer tendência temporal (delta face ao trimestre anterior) e diagnóstico automático
    pares_seq = [("2026-T2", "2026-T1"), ("2026-T3", "2026-T2")]
    for cod_atual, cod_ant in pares_seq:
        if cod_atual not in resultados_trim or cod_ant not in resultados_trim:
            continue
        mapa_ant = {p["pt"]: p for p in resultados_trim[cod_ant]["pts"]}
        for p in resultados_trim[cod_atual]["pts"]:
            ant = mapa_ant.get(p["pt"])
            if ant:
                p["delta_taxa_pp"] = round(p["taxa_perda_pct"] - ant["taxa_perda_pct"], 1)
                p["delta_perda_kwh"] = round(p["perda_kwh"] - ant["perda_kwh"], 1)
                var_inj = ((p["injetada_kwh"] - ant["injetada_kwh"]) / ant["injetada_kwh"]) if ant["injetada_kwh"] > 0 else 0.0
            else:
                p["delta_taxa_pp"] = None
                p["delta_perda_kwh"] = None
                var_inj = 0.0
            p["_var_inj"] = var_inj

    for cod_t, obj_t in resultados_trim.items():
        for p in obj_t["pts"]:
            if "delta_taxa_pp" not in p:
                p["delta_taxa_pp"] = None
                p["delta_perda_kwh"] = None
            var_inj = p.pop("_var_inj", 0.0)
            if p["status"] == "sem_cobertura":
                diag = "sem_cobertura"
            elif p["perda_kwh"] < -0.05 * p["injetada_kwh"]:
                diag = "erro_cadastro_neg"
            elif abs(var_inj) > 0.40:
                diag = "salto_injecao"
            elif p["contador_ip"] and p["fat_ip_kwh"] <= 0:
                diag = "ip_zerado"
            elif p["taxa_perda_pct"] >= 50.0 and p["consumo_medio_cli_mes"] < 60.0:
                diag = "subfaturacao_extrema"
            else:
                diag = "ok"
            p["diagnostico"] = diag

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
