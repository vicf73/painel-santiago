"""
Módulo 4 - Análise de Pré-Pagamento (Medidores, Tokens & Risco de Fraude).

Cruza:
  - _arquivo_antigo/medidor/*.csv (parque de medidores pré-pago)
  - _arquivo_antigo/trans_tok/*.csv (transações de compra de tokens/energia)
  - _arquivo_antigo/medidor_prepago.xlsx (georreferenciação e PT/POLIG_NOVO)

Gera: lake/gold/prepago.json -> sincronizado em santiago_marts_gold (chave: prepago_analise)
"""

import glob
import json
import os
import time
from datetime import datetime, timezone

import duckdb
import pandas as pd


def _ponto_no_anel(lat: float, lon: float, anel: list) -> bool:
    """Algoritmo Ray-Casting para testar se (lat, lon) está dentro de um anel fechado."""
    dentro = False
    n = len(anel)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = anel[i]
        yj, xj = anel[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            dentro = not dentro
        j = i
    return dentro


def _carregar_poligonos_prepago(arq_dir: str) -> tuple[list, dict]:
    """Carrega polígonos GeoJSON de Santiago com bounding boxes para Point-in-Polygon."""
    gj_path = os.path.join(arq_dir, "poligonos.geojson")
    if not os.path.exists(gj_path):
        return [], {}
    with open(gj_path, "r", encoding="utf-8") as f:
        gj = json.load(f)

    lista_idx = []
    mapa_polig = {}
    for feat in gj.get("features", []):
        props = feat.get("properties") or {}
        pt_nome = str(props.get("POLIG_NOVO") or "").strip()
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if not pt_nome or not coords:
            continue

        aneis_ext = []
        if gtype == "MultiPolygon":
            for poly in coords:
                if poly and poly[0]:
                    aneis_ext.append([[round(float(c[1]), 6), round(float(c[0]), 6)] for c in poly[0]])
        elif gtype == "Polygon":
            if coords[0]:
                aneis_ext.append([[round(float(c[1]), 6), round(float(c[0]), 6)] for c in coords[0]])
        if not aneis_ext:
            continue

        lats = [p[0] for anel in aneis_ext for p in anel]
        lons = [p[1] for anel in aneis_ext for p in anel]
        bbox = (min(lats), max(lats), min(lons), max(lons))
        lista_idx.append((pt_nome, aneis_ext, bbox))
        mapa_polig[pt_nome] = aneis_ext
    return lista_idx, mapa_polig


def _associar_pt_espacial(lat: float, lon: float, poligonos_idx: list) -> str | None:
    for pt_nome, aneis, (min_la, max_la, min_lo, max_lo) in poligonos_idx:
        if not (min_la <= lat <= max_la and min_lo <= lon <= max_lo):
            continue
        for anel in aneis:
            if _ponto_no_anel(lat, lon, anel):
                return pt_nome
    return None


def executar_prepago(base_santiago: str) -> dict:
    t0 = time.time()
    print("=" * 72)
    print(" MÓDULO 4 - PRÉ-PAGAMENTO (MEDIDORES, TOKENS & RISCO)")
    print("=" * 72)

    arq_dir = os.path.join(base_santiago, "_arquivo_antigo")
    med_files = sorted(glob.glob(os.path.join(arq_dir, "medidor", "*.csv")))
    tok_files = sorted(glob.glob(os.path.join(arq_dir, "trans_tok", "*.csv")))
    geo_xlsx = os.path.join(arq_dir, "medidor_prepago.xlsx")

    if not med_files or not tok_files:
        print("   [AVISO] Ficheiros de medidor ou trans_tok não encontrados em _arquivo_antigo.")
        return {}

    con = duckdb.connect()
    silver_db = os.path.join(base_santiago, "lake", "silver", "santiago.duckdb")
    if os.path.exists(silver_db):
        con.execute(f"ATTACH '{silver_db.replace(chr(92), '/')}' AS silver (READ_ONLY)")
        con.execute("""
            CREATE OR REPLACE TEMP TABLE tmp_pt_uni AS
            SELECT LOWER(REGEXP_REPLACE(TRIM(pt), '[\r\n\t]+', '', 'g')) AS pt_norm, MODE(desc_uni) AS desc_uni
            FROM silver.dim_local_consumo
            WHERE pt IS NOT NULL AND desc_uni IS NOT NULL
            GROUP BY 1
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE tmp_loc_uni AS
            SELECT LOWER(TRIM(localidade)) AS loc_norm, MODE(desc_uni) AS desc_uni
            FROM silver.dim_local_consumo
            WHERE localidade IS NOT NULL AND desc_uni IS NOT NULL
            GROUP BY 1
        """)
        con.execute("DETACH silver")
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE tmp_pt_uni (pt_norm VARCHAR, desc_uni VARCHAR)")
        con.execute("CREATE OR REPLACE TEMP TABLE tmp_loc_uni (loc_norm VARCHAR, desc_uni VARCHAR)")

    med_paths_sql = ", ".join("'" + p.replace("\\", "/") + "'" for p in med_files)
    tok_paths_sql = ", ".join("'" + p.replace("\\", "/") + "'" for p in tok_files)

    # 1. Carregar polígonos oficiais (poligonos.geojson) + georreferenciação (medidor_prepago.xlsx)
    poligonos_idx, mapa_polig_gj = _carregar_poligonos_prepago(arq_dir)
    if os.path.exists(geo_xlsx):
        df_geo = pd.read_excel(
            geo_xlsx,
            usecols=["n_serie", "POLIG_NOVO", "localidade", "latitude", "longitude"],
        )
        df_geo["n_serie"] = df_geo["n_serie"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
        df_geo = df_geo.drop_duplicates(subset=["n_serie"], keep="first")

        pts_finais = []
        pts_origem = []
        qtd_espacial = 0
        for row in df_geo.itertuples(index=False):
            la = getattr(row, "latitude", None)
            lo = getattr(row, "longitude", None)
            pt_cad = getattr(row, "POLIG_NOVO", None)
            pt_cad_str = str(pt_cad).strip() if pd.notna(pt_cad) and str(pt_cad).strip() else None
            pt_match = None
            if pd.notna(la) and pd.notna(lo) and poligonos_idx:
                pt_match = _associar_pt_espacial(float(la), float(lo), poligonos_idx)
            if pt_match:
                pts_finais.append(pt_match)
                pts_origem.append("Polígono Exato")
                qtd_espacial += 1
            elif pt_cad_str:
                pts_finais.append(pt_cad_str)
                pts_origem.append("Cadastro")
            else:
                pts_finais.append(None)
                pts_origem.append("Sem PT")
        df_geo["POLIG_NOVO"] = pts_finais
        df_geo["pt_origem"] = pts_origem
        print(f"   - Associação Espacial (Point-in-Polygon): {qtd_espacial:,} medidores alocados a {len(poligonos_idx)} polígonos")
    else:
        df_geo = pd.DataFrame(columns=["n_serie", "POLIG_NOVO", "pt_origem", "localidade", "latitude", "longitude"])
    con.register("df_geo_reg", df_geo)

    # 2. Tabela de medidores ativos
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE tmp_medidores AS
        SELECT DISTINCT ON (REGEXP_REPLACE(TRIM(column17), '^`', ''))
            REGEXP_REPLACE(TRIM(column17), '^`', '') AS medidor,
            TRIM(COALESCE(column00, '')) AS nome,
            TRIM(COALESCE(column08, '')) AS estado,
            TRIM(COALESCE(column10, '')) AS tarifa,
            TRIM(COALESCE(column13, '')) AS localidade_csv,
            TRIM(COALESCE(column25, '')) AS modelo,
            TRY_STRPTIME(SPLIT_PART(TRIM(column24), ' ', 1), '%Y-%m-%d')::DATE AS dt_instalacao,
            g.POLIG_NOVO AS pt,
            COALESCE(g.pt_origem, 'Sem GPS') AS pt_origem,
            COALESCE(NULLIF(TRIM(g.localidade), ''), TRIM(COALESCE(column13, ''))) AS localidade,
            COALESCE(
                pu.desc_uni,
                lu.desc_uni,
                CASE
                    WHEN UPPER(COALESCE(g.localidade, column13, '')) LIKE '%TARRAFAL%' THEN 'Tarrafal'
                    WHEN UPPER(COALESCE(g.localidade, column13, '')) LIKE '%ASSOMADA%' OR UPPER(COALESCE(g.localidade, column13, '')) LIKE '%CATARINA%' THEN 'Santa Catarina'
                    WHEN UPPER(COALESCE(g.localidade, column13, '')) LIKE '%BADEJO%' OR UPPER(COALESCE(g.localidade, column13, '')) LIKE '%CRUZ%' THEN 'Santa Cruz'
                    WHEN UPPER(COALESCE(g.localidade, column13, '')) LIKE '%CALHETA%' THEN 'Calheta S. Miguel'
                    WHEN UPPER(COALESCE(g.localidade, column13, '')) LIKE '%DOMINGOS%' THEN 'São Domingos'
                    WHEN UPPER(COALESCE(g.localidade, column13, '')) LIKE '%PRAIA%' OR UPPER(COALESCE(g.localidade, column13, '')) LIKE '%ACHADA%' OR UPPER(COALESCE(g.localidade, column13, '')) LIKE '%PALMAREJO%' THEN 'Praia'
                    ELSE 'Outras / S. Unidade'
                END
            ) AS desc_uni,
            TRY_CAST(g.latitude AS DOUBLE) AS lat,
            TRY_CAST(g.longitude AS DOUBLE) AS lon
        FROM read_csv([{med_paths_sql}], header=false, ignore_errors=true, auto_detect=true, union_by_name=true) m
        LEFT JOIN df_geo_reg g ON REGEXP_REPLACE(TRIM(m.column17), '^`', '') = g.n_serie
        LEFT JOIN tmp_pt_uni pu ON LOWER(REGEXP_REPLACE(TRIM(CAST(g.POLIG_NOVO AS VARCHAR)), '[\r\n\t]+', '', 'g')) = pu.pt_norm
        LEFT JOIN tmp_loc_uni lu ON LOWER(TRIM(COALESCE(NULLIF(TRIM(g.localidade), ''), TRIM(COALESCE(m.column13, ''))))) = lu.loc_norm
        WHERE TRIM(COALESCE(column17, '')) <> ''
    """)

    # 3. Tabela de transações de energia (apenas linhas com kWh > 0 e token de energia)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE tmp_trans_energia AS
        SELECT
            TRIM(CAST(column00 AS VARCHAR)) AS medidor,
            TRIM(COALESCE(column01, '')) AS canal,
            TRY_STRPTIME(SPLIT_PART(TRIM(column05), ' ', 1), '%Y-%m-%d')::DATE AS dt_trans,
            ABS(TRY_CAST(column06 AS DOUBLE)) AS valor_ecv,
            TRY_CAST(column10 AS DOUBLE) AS kwh
        FROM read_csv([{tok_paths_sql}], header=false, ignore_errors=true, auto_detect=true, union_by_name=true)
        WHERE TRY_CAST(column10 AS DOUBLE) > 0
          AND TRY_STRPTIME(SPLIT_PART(TRIM(column05), ' ', 1), '%Y-%m-%d') IS NOT NULL
    """)

    dt_max_row = con.execute("SELECT MAX(dt_trans), MIN(dt_trans) FROM tmp_trans_energia").fetchone()
    dt_max = dt_max_row[0]
    dt_min = dt_max_row[1]
    if dt_max is None:
        con.close()
        return {}

    # 4. Métricas agregadas por medidor (histórico anterior vs últimos 60 dias)
    # Período histórico = [dt_min, dt_max - 60d); Recente = [dt_max - 60d, dt_max]
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE tmp_medidor_metricas AS
        WITH bounds AS (
            SELECT
                DATE '{dt_min}' AS dt_min,
                DATE '{dt_max}' AS dt_max,
                (DATE '{dt_max}' - INTERVAL '60 days')::DATE AS dt_corte_60,
                GREATEST(DATEDIFF('day', DATE '{dt_min}', (DATE '{dt_max}' - INTERVAL '60 days')::DATE) / 30.0, 1.0) AS meses_hist
        ),
        agg AS (
            SELECT
                t.medidor,
                COUNT(*) AS qtd_compras,
                ROUND(SUM(t.valor_ecv), 1) AS total_ecv,
                ROUND(SUM(t.kwh), 1) AS total_kwh,
                ROUND(AVG(t.valor_ecv), 0) AS ticket_medio_ecv,
                MAX(t.dt_trans) AS dt_ultima_compra,
                SUM(CASE WHEN t.dt_trans < b.dt_corte_60 THEN t.kwh ELSE 0 END) AS kwh_hist,
                SUM(CASE WHEN t.dt_trans >= b.dt_corte_60 THEN t.kwh ELSE 0 END) AS kwh_recente,
                SUM(CASE WHEN t.dt_trans >= b.dt_corte_60 THEN 1 ELSE 0 END) AS compras_recente
            FROM tmp_trans_energia t, bounds b
            GROUP BY t.medidor
        )
        SELECT
            m.medidor,
            m.nome,
            m.estado,
            m.tarifa,
            m.modelo,
            COALESCE(NULLIF(TRIM(m.pt), ''), 'Sem PT') AS pt,
            m.pt_origem,
            m.localidade,
            m.desc_uni,
            m.lat,
            m.lon,
            COALESCE(a.qtd_compras, 0) AS qtd_compras,
            COALESCE(a.total_ecv, 0) AS total_ecv,
            COALESCE(a.total_kwh, 0) AS total_kwh,
            COALESCE(a.ticket_medio_ecv, 0) AS ticket_medio_ecv,
            a.dt_ultima_compra,
            CASE
                WHEN a.dt_ultima_compra IS NULL THEN 365
                ELSE DATEDIFF('day', a.dt_ultima_compra, b.dt_max)
            END AS dias_sem_compra,
            ROUND(COALESCE(a.kwh_hist, 0) / b.meses_hist, 1) AS kwh_mes_hist,
            ROUND(COALESCE(a.kwh_recente, 0) / 2.0, 1) AS kwh_mes_recente,
            COALESCE(a.compras_recente, 0) AS compras_recente
        FROM tmp_medidores m
        CROSS JOIN bounds b
        LEFT JOIN agg a ON m.medidor = a.medidor
    """)

    # Classificação de risco por medidor
    con.execute("""
        CREATE OR REPLACE TEMP TABLE tmp_medidor_risco AS
        SELECT
            *,
            CASE
                WHEN kwh_mes_hist > 0 THEN ROUND(((kwh_mes_recente - kwh_mes_hist) / kwh_mes_hist) * 100.0, 1)
                ELSE NULL
            END AS desvio_pct,
            CASE
                WHEN dias_sem_compra > 60 THEN 'critico'
                WHEN kwh_mes_hist >= 20 AND ((kwh_mes_recente - kwh_mes_hist) / kwh_mes_hist) <= -0.60 THEN 'critico'
                WHEN dias_sem_compra BETWEEN 31 AND 60 THEN 'alerta'
                WHEN qtd_compras > 0 AND (kwh_mes_recente < 15 OR (ticket_medio_ecv < 500 AND qtd_compras >= 3)) THEN 'alerta'
                WHEN kwh_mes_hist >= 15 AND ((kwh_mes_recente - kwh_mes_hist) / kwh_mes_hist) <= -0.30 THEN 'desvio'
                ELSE 'normal'
            END AS risco
        FROM tmp_medidor_metricas
    """)

    # 5. KPIs globais
    k_row = con.execute("""
        SELECT
            COUNT(*) AS total_medidores,
            SUM(CASE WHEN lat IS NOT NULL AND lon IS NOT NULL THEN 1 ELSE 0 END) AS com_geo,
            ROUND(SUM(total_kwh) / 1000.0, 1) AS total_mwh,
            ROUND(SUM(total_ecv) / 1e6, 2) AS total_m_ecv,
            SUM(CASE WHEN dias_sem_compra > 30 THEN 1 ELSE 0 END) AS sem_compra_30d,
            SUM(CASE WHEN dias_sem_compra > 60 THEN 1 ELSE 0 END) AS sem_compra_60d,
            SUM(CASE WHEN dias_sem_compra > 90 THEN 1 ELSE 0 END) AS sem_compra_90d,
            SUM(CASE WHEN kwh_mes_hist >= 15 AND desvio_pct <= -50.0 THEN 1 ELSE 0 END) AS desvio_50_pct,
            SUM(CASE WHEN qtd_compras > 0 AND (kwh_mes_recente < 15 OR (ticket_medio_ecv < 500 AND qtd_compras >= 3)) THEN 1 ELSE 0 END) AS valor_baixo_qtd,
            SUM(CASE WHEN risco = 'critico' THEN 1 ELSE 0 END) AS criticos_qtd,
            SUM(CASE WHEN risco = 'alerta' THEN 1 ELSE 0 END) AS alertas_qtd,
            SUM(CASE WHEN risco = 'desvio' THEN 1 ELSE 0 END) AS desvios_qtd
        FROM tmp_medidor_risco
    """).fetchone()

    tot_mwh = float(k_row[2] or 0)
    tot_mecv = float(k_row[3] or 0)
    pm_kwh = round((tot_mecv * 1e6) / (tot_mwh * 1000.0), 2) if tot_mwh > 0 else 0.0

    resumo = {
        "dt_min": str(dt_min),
        "dt_max": str(dt_max),
        "total_medidores": int(k_row[0] or 0),
        "com_geo": int(k_row[1] or 0),
        "total_mwh": tot_mwh,
        "total_m_ecv": tot_mecv,
        "preco_medio_kwh": pm_kwh,
        "sem_compra_30d": int(k_row[4] or 0),
        "sem_compra_60d": int(k_row[5] or 0),
        "sem_compra_90d": int(k_row[6] or 0),
        "desvio_50_pct": int(k_row[7] or 0),
        "valor_baixo_qtd": int(k_row[8] or 0),
        "criticos_qtd": int(k_row[9] or 0),
        "alertas_qtd": int(k_row[10] or 0),
        "desvios_qtd": int(k_row[11] or 0),
    }

    # 6. Série mensal
    serie_rows = con.execute("""
        SELECT
            strftime(dt_trans, '%Y-%m') AS ano_mes,
            COUNT(*) AS compras,
            COUNT(DISTINCT medidor) AS medidores_ativos,
            ROUND(SUM(kwh) / 1000.0, 1) AS mwh,
            ROUND(SUM(valor_ecv) / 1e6, 2) AS m_ecv
        FROM tmp_trans_energia
        WHERE dt_trans >= DATE '2026-01-01'
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    serie_mensal = [
        {"ano_mes": r[0], "compras": int(r[1]), "medidores_ativos": int(r[2]), "mwh": float(r[3]), "m_ecv": float(r[4])}
        for r in serie_rows
    ]

    serie_uni_rows = con.execute("""
        SELECT
            m.desc_uni,
            strftime(t.dt_trans, '%Y-%m') AS ano_mes,
            COUNT(*) AS compras,
            COUNT(DISTINCT t.medidor) AS medidores_ativos,
            ROUND(SUM(t.kwh) / 1000.0, 1) AS mwh,
            ROUND(SUM(t.valor_ecv) / 1e6, 2) AS m_ecv
        FROM tmp_trans_energia t
        JOIN tmp_medidores m ON t.medidor = m.medidor
        WHERE t.dt_trans >= DATE '2026-01-01'
        GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchall()
    from collections import defaultdict
    serie_mensal_por_uni = defaultdict(list)
    for uni, ym, comp, med_at, mwh_v, mecv_v in serie_uni_rows:
        serie_mensal_por_uni[uni].append({
            "ano_mes": ym, "compras": int(comp), "medidores_ativos": int(med_at),
            "mwh": float(mwh_v), "m_ecv": float(mecv_v)
        })

    # 7. Top canais de venda e faixas de recarga
    canais_rows = con.execute("""
        SELECT
            canal,
            COUNT(*) AS compras,
            ROUND(SUM(valor_ecv) / 1e6, 2) AS m_ecv,
            ROUND(SUM(kwh) / 1000.0, 1) AS mwh
        FROM tmp_trans_energia
        GROUP BY 1 ORDER BY 3 DESC LIMIT 8
    """).fetchall()
    canais = [{"canal": r[0] or "Outro", "compras": int(r[1]), "m_ecv": float(r[2]), "mwh": float(r[3])} for r in canais_rows]

    faixas_rows = con.execute("""
        SELECT
            CASE
                WHEN valor_ecv < 500 THEN '< 500 ECV'
                WHEN valor_ecv < 1000 THEN '500–999 ECV'
                WHEN valor_ecv < 3000 THEN '1.000–2.999 ECV'
                ELSE '>= 3.000 ECV'
            END AS faixa,
            COUNT(*) AS compras,
            ROUND(SUM(valor_ecv) / 1e6, 2) AS m_ecv
        FROM tmp_trans_energia
        GROUP BY 1
    """).fetchall()
    faixas_recarga = [{"faixa": r[0], "compras": int(r[1]), "m_ecv": float(r[2])} for r in faixas_rows]

    # 8. Ranking de PTs com maior risco pré-pago
    pt_rows = con.execute("""
        SELECT
            pt,
            ANY_VALUE(localidade) AS localidade,
            COUNT(*) AS total_med,
            SUM(CASE WHEN risco = 'critico' THEN 1 ELSE 0 END) AS criticos,
            SUM(CASE WHEN risco = 'alerta' THEN 1 ELSE 0 END) AS alertas,
            SUM(CASE WHEN dias_sem_compra > 60 THEN 1 ELSE 0 END) AS sem_60d,
            ROUND(SUM(total_ecv) / 1e6, 2) AS m_ecv
        FROM tmp_medidor_risco
        WHERE pt <> 'Sem PT'
        GROUP BY 1
        ORDER BY criticos DESC, alertas DESC
        LIMIT 30
    """).fetchall()
    ranking_pts = [
        {"pt": r[0], "localidade": r[1] or "", "total_med": int(r[2]), "criticos": int(r[3]), "alertas": int(r[4]), "sem_60d": int(r[5]), "m_ecv": float(r[6])}
        for r in pt_rows
    ]

    # 9. Todos os medidores com classificação de risco e georreferenciação
    med_list_rows = con.execute("""
        SELECT
            medidor, nome, tarifa, modelo, pt, pt_origem, localidade, desc_uni, lat, lon,
            qtd_compras, total_ecv, total_kwh, ticket_medio_ecv,
            CAST(dt_ultima_compra AS VARCHAR) AS dt_ultima,
            dias_sem_compra, kwh_mes_hist, kwh_mes_recente, desvio_pct, risco
        FROM tmp_medidor_risco
        ORDER BY
            CASE risco WHEN 'critico' THEN 1 WHEN 'alerta' THEN 2 WHEN 'desvio' THEN 3 ELSE 4 END,
            CASE WHEN lat IS NOT NULL AND lon IS NOT NULL THEN 0 ELSE 1 END,
            dias_sem_compra DESC,
            kwh_mes_hist DESC
    """).fetchall()
    medidores_risco = [
        {
            "medidor": r[0],
            "nome": str(r[1] or "")[:45],
            "tarifa": r[2],
            "modelo": r[3],
            "pt": r[4],
            "pt_origem": r[5] or "Sem GPS",
            "localidade": r[6] or "",
            "desc_uni": r[7] or "",
            "lat": round(float(r[8]), 6) if r[8] is not None else None,
            "lon": round(float(r[9]), 6) if r[9] is not None else None,
            "qtd_compras": int(r[10]),
            "total_ecv": float(r[11]),
            "total_kwh": float(r[12]),
            "ticket_medio_ecv": float(r[13]),
            "dt_ultima": r[14] or "",
            "dias_sem_compra": int(r[15]),
            "kwh_mes_hist": float(r[16]),
            "kwh_mes_recente": float(r[17]),
            "desvio_pct": float(r[18]) if r[18] is not None else None,
            "risco": r[19],
        }
        for r in med_list_rows
    ]

    pts_ativos_prepago = {m["pt"] for m in medidores_risco if m["pt"] and m["pt"] != "Sem PT"}
    poligonos_pts = {pt: mapa_polig_gj[pt] for pt in pts_ativos_prepago if pt in mapa_polig_gj}

    con.close()

    gold_dir = os.path.join(base_santiago, "lake", "gold")
    os.makedirs(gold_dir, exist_ok=True)
    out_json = os.path.join(gold_dir, "prepago.json")
    payload = {
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resumo": resumo,
        "serie_mensal": serie_mensal,
        "serie_mensal_por_uni": dict(serie_mensal_por_uni),
        "canais": canais,
        "faixas_recarga": faixas_recarga,
        "ranking_pts": ranking_pts,
        "poligonos_pts": poligonos_pts,
        "medidores": medidores_risco,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(
        f"   - Medidores: {resumo['total_medidores']:,} ({resumo['com_geo']:,} c/ Geo) | "
        f"Vendas: {resumo['total_mwh']:,.1f} MWh ({resumo['total_m_ecv']:,.2f}M ECV)"
    )
    print(
        f"   - Risco: Críticos={resumo['criticos_qtd']:,} (>60d s/ compra={resumo['sem_compra_60d']:,}) | "
        f"Alertas={resumo['alertas_qtd']:,} | Desvio>=50%={resumo['desvio_50_pct']:,}"
    )
    print(f" MÓDULO 4 CONCLUÍDO em {time.time() - t0:.2f}s -> {out_json}")
    return payload
