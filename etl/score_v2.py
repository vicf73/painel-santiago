"""
Fase 3 - Motor de Score de Risco v2 Calibrado em Inspeções Reais CEA (83k+ registos)
Treina Regressão Logística L2 com validação temporal (out-of-time),
mede AUC, Precision@k e Lift por decil, pontua toda a carteira (121k CILs)
e exporta o mart `score_v2_validacao` para a Camada Gold / Supabase.
"""

import os
import json
import time
from datetime import datetime, timezone

import duckdb
import numpy as np
import pandas as pd


FEATURES = [
    "consumo_t3_zero",
    "queda_consumo_50",
    "ratio_vs_pt_baixo",
    "tem_anomalia_fraude",
    "tem_anomalia_avaria",
    "tem_anomalia_acesso",
    "contador_20a",
    "sem_leitura_5m",
    "contrato_baixa_divida",
    "contrato_inspecao",
    "cf1_tem_auto",
    "cea_impedimento",
    "divida_exigivel_log",
    "sem_pag_2026",
    "taxa_fraude_pt_treino",
]

LABELS_PT = {
    "consumo_t3_zero": "Contrato Vigor c/ Consumo T3=0",
    "queda_consumo_50": "Queda Consumo >50% (T3 vs T_prev)",
    "ratio_vs_pt_baixo": "Consumo <40% da Mediana do PT/Tarifa",
    "tem_anomalia_fraude": "Anomalia Leitura: Suspeita Fraude",
    "tem_anomalia_avaria": "Anomalia Leitura: Avaria/Parado",
    "tem_anomalia_acesso": "Anomalia Leitura: Sem Acesso/Difícil",
    "contador_20a": "Contador Obsoleto (>20 anos)",
    "sem_leitura_5m": "Sem Leitura >5 meses",
    "contrato_baixa_divida": "Contrato em Baixa p/ Dívida",
    "contrato_inspecao": "Estado Contratual de Inspeção",
    "cf1_tem_auto": "Histórico Auto de Fraude CF1",
    "cea_impedimento": "Impedimento de Acesso em CEA Anterior",
    "divida_exigivel_log": "Volume Dívida Exigível",
    "sem_pag_2026": "Devedor Sem Pagamento 2026",
    "taxa_fraude_pt_treino": "Histórico de Fraude no PT",
}


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


def _treinar_logreg_l2(X: np.ndarray, y: np.ndarray, l2: float = 1.0, lr: float = 0.15, epochs: int = 800):
    n, d = X.shape
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    Xs = (X - mean) / std

    w = np.zeros(d, dtype=np.float64)
    b = float(np.log(max(y.mean(), 1e-4) / max(1.0 - y.mean(), 1e-4)))

    # Balanceamento leve para estabilidade numérica sem distorcer ranking
    for _ in range(epochs):
        p = _sigmoid(Xs @ w + b)
        err = p - y
        grad_w = (Xs.T @ err) / n + (l2 / n) * w
        grad_b = err.mean()
        w -= lr * grad_w
        b -= lr * grad_b

    return {"w": w, "b": b, "mean": mean, "std": std}


def _prever_logreg(modelo: dict, X: np.ndarray) -> np.ndarray:
    Xs = (X - modelo["mean"]) / modelo["std"]
    return _sigmoid(Xs @ modelo["w"] + modelo["b"])


def _auc_roc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    pos = y_true == 1
    neg = y_true == 0
    n_pos = int(pos.sum())
    n_neg = int(neg.sum())
    if n_pos == 0 or n_neg == 0:
        return 0.5
    order = np.argsort(y_score)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(y_score) + 1)
    # Empates médios aproximados não são críticos para 40k pontos contínuos
    sum_ranks_pos = ranks[pos].sum()
    return float((sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def executar_score_v2(base_santiago: str) -> dict:
    t0 = time.time()
    bronze_dir = os.path.join(base_santiago, "lake", "bronze").replace("\\", "/")
    silver_dir = os.path.join(base_santiago, "lake", "silver")
    db_path = os.path.join(silver_dir, "santiago.duckdb")

    print("=" * 72)
    print(" FASE 3 - SCORE DE RISCO V2 (CALIBRAÇÃO EM 83K INSPEÇÕES CEA)")
    print("=" * 72)

    con = duckdb.connect(db_path)

    # 1. Construir matriz de features por CIL no DuckDB
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE tmp_features_cil AS
        WITH lotes_17 AS (
            SELECT DISTINCT lote_ym FROM fct_fatura WHERE emp = '17' ORDER BY lote_ym
        ),
        ult3 AS (SELECT lote_ym FROM lotes_17 ORDER BY lote_ym DESC LIMIT 3),
        prev3 AS (SELECT lote_ym FROM lotes_17 ORDER BY lote_ym DESC LIMIT 3 OFFSET 3),
        fat_cil AS (
            SELECT
                cil,
                SUM(CASE WHEN lote_ym IN (SELECT lote_ym FROM ult3) THEN consumo_qtd ELSE 0 END) AS t3_atual,
                SUM(CASE WHEN lote_ym IN (SELECT lote_ym FROM prev3) THEN consumo_qtd ELSE 0 END) AS t3_prev
            FROM fct_fatura
            WHERE emp = '17' AND cil IS NOT NULL
            GROUP BY cil
        ),
        med_pt_tarifa AS (
            SELECT
                lc.pt,
                lc.tarifa,
                MEDIAN(f.t3_atual) AS med_t3_pt
            FROM dim_local_consumo lc
            JOIN fat_cil f ON lc.cil = f.cil
            WHERE lc.pt IS NOT NULL AND f.t3_atual > 0
            GROUP BY lc.pt, lc.tarifa
        ),
        div_cil AS (
            SELECT
                cil,
                SUM(val_divida_ecv) AS divida_total,
                SUM(CASE WHEN NOT is_prescrita THEN val_divida_ecv ELSE 0 END) AS divida_exigivel
            FROM fct_divida_snapshot
            GROUP BY cil
        ),
        cob_cil AS (
            SELECT cil, SUM(valor_ecv) AS cob_2026
            FROM fct_cobranca
            WHERE ano_cob >= 2026
            GROUP BY cil
        ),
        apa AS (
            SELECT DISTINCT ON (TRY_CAST(CIL AS BIGINT))
                TRY_CAST(CIL AS BIGINT) AS cil,
                TRY_STRPTIME(NULLIF(TRIM(DA_INST), ''), '%Y%m%d')::DATE AS dt_inst,
                TRY_STRPTIME(NULLIF(TRIM(DATA_LEIT), ''), '%Y%m%d')::DATE AS dt_leit
            FROM read_parquet('{bronze_dir}/aparelho/aparelho.parquet')
            WHERE TRY_CAST(CIL AS BIGINT) BETWEEN 10000000 AND 99999999
        ),
        anom AS (
            SELECT DISTINCT ON (TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT))
                TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT) AS cil,
                TRIM(Anomalia) AS anomalia
            FROM read_parquet('{bronze_dir}/dim_auxiliares/anomalia.parquet')
            WHERE TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT) IS NOT NULL
        ),
        cf1 AS (
            SELECT
                TRY_CAST(CAST("Adição" AS DOUBLE) AS BIGINT) AS cil,
                COUNT(*) AS cf1_qtd
            FROM read_parquet('{bronze_dir}/dim_auxiliares/cf1_autos.parquet')
            WHERE TRY_CAST(CAST("Adição" AS DOUBLE) AS BIGINT) IS NOT NULL
            GROUP BY 1
        ),
        cea_imp AS (
            SELECT
                cil,
                MAX(CASE WHEN UPPER(COALESCE(resultado_inspecao, '')) LIKE '%ACESSO%' THEN 1 ELSE 0 END) AS cea_impedimento
            FROM fct_inspecao_cea
            GROUP BY cil
        )
        SELECT
            lc.cil,
            lc.ilha,
            lc.desc_uni,
            lc.nome,
            lc.localidade,
            lc.pt,
            lc.tarifa,
            lc.estctr,
            COALESCE(f.t3_atual, 0) AS t3_atual,
            COALESCE(f.t3_prev, 0) AS t3_prev,
            COALESCE(d.divida_total, 0) AS divida_total,
            COALESCE(d.divida_exigivel, 0) AS divida_exigivel,
            COALESCE(cb.cob_2026, 0) AS cob_2026,
            a.anomalia,
            CASE WHEN lc.estctr IN (10,11,12,13,14,15) AND COALESCE(f.t3_atual, 0) <= 0 THEN 1.0 ELSE 0.0 END AS consumo_t3_zero,
            CASE WHEN COALESCE(f.t3_prev, 0) > 30 AND COALESCE(f.t3_atual, 0) < 0.5 * f.t3_prev THEN 1.0 ELSE 0.0 END AS queda_consumo_50,
            CASE WHEN m.med_t3_pt > 30 AND COALESCE(f.t3_atual, 0) < 0.4 * m.med_t3_pt AND lc.estctr IN (10,11,12,13,14,15) THEN 1.0 ELSE 0.0 END AS ratio_vs_pt_baixo,
            CASE WHEN COALESCE(a.anomalia, '') IN ('Suspeita de Fraude','Ligado Directo','Local de Consumo Sem Contador','Sem Selos de Invólucro','Falta Selo no Aparelho','Contador Parado Local Habitado') THEN 1.0 ELSE 0.0 END AS tem_anomalia_fraude,
            CASE WHEN COALESCE(a.anomalia, '') IN ('Contador Cortado','Display Apagado','Funções Congeladas','Contador Desconhecido','Aparelho Avariado','Contador Parado','Contador Subst. Sem Tratamento','Número do Aparelho Errado','Dispositivo Quebrado','Aparelho Queimado') THEN 1.0 ELSE 0.0 END AS tem_anomalia_avaria,
            CASE WHEN COALESCE(a.anomalia, '') IN ('Leitura Impossível','Leitura Difícil','Além da Escada','Não Comunica - sem Leitura') THEN 1.0 ELSE 0.0 END AS tem_anomalia_acesso,
            CASE WHEN ap.dt_inst IS NOT NULL AND ap.dt_inst < (CURRENT_DATE - INTERVAL '20 years')::DATE THEN 1.0 ELSE 0.0 END AS contador_20a,
            CASE WHEN ap.dt_leit IS NOT NULL AND ap.dt_leit < (CURRENT_DATE - INTERVAL '5 months')::DATE THEN 1.0 ELSE 0.0 END AS sem_leitura_5m,
            CASE WHEN lc.estctr = 25 THEN 1.0 ELSE 0.0 END AS contrato_baixa_divida,
            CASE WHEN lc.estctr IN (16, 17, 26, 27, 28) THEN 1.0 ELSE 0.0 END AS contrato_inspecao,
            CASE WHEN COALESCE(c1.cf1_qtd, 0) > 0 THEN 1.0 ELSE 0.0 END AS cf1_tem_auto,
            COALESCE(ci.cea_impedimento, 0)::DOUBLE AS cea_impedimento,
            LN(1.0 + GREATEST(0.0, COALESCE(d.divida_exigivel, 0))) AS divida_exigivel_log,
            CASE WHEN COALESCE(d.divida_total, 0) > 0 AND COALESCE(cb.cob_2026, 0) <= 0 THEN 1.0 ELSE 0.0 END AS sem_pag_2026
        FROM dim_local_consumo lc
        LEFT JOIN fat_cil f ON lc.cil = f.cil
        LEFT JOIN med_pt_tarifa m ON lc.pt = m.pt AND lc.tarifa = m.tarifa
        LEFT JOIN div_cil d ON lc.cil = d.cil
        LEFT JOIN cob_cil cb ON lc.cil = cb.cil
        LEFT JOIN apa ap ON lc.cil = ap.cil
        LEFT JOIN anom a ON lc.cil = a.cil
        LEFT JOIN cf1 c1 ON lc.cil = c1.cil
        LEFT JOIN cea_imp ci ON lc.cil = ci.cil;
    """)

    # 2. Dataset rotulado de inspeções CEA conclusivas (divisão temporal out-of-time: < 2025-07-01 vs >= 2025-07-01)
    df_cea = con.execute("""
        WITH rotulos AS (
            SELECT
                cil,
                dt_inspecao,
                CASE
                    WHEN UPPER(resultado_inspecao) LIKE '%FRAUDE%' THEN 1
                    WHEN UPPER(resultado_inspecao) IN ('EXECUTADA', 'OUTROS', 'SUBSTITUIÇÃO DO CONTADOR') THEN 0
                    ELSE NULL
                END AS y
            FROM fct_inspecao_cea
            WHERE dt_inspecao IS NOT NULL
        ),
        dedup_cea AS (
            SELECT cil, MAX(dt_inspecao) AS dt_inspecao, MAX(y) AS y
            FROM rotulos
            WHERE y IS NOT NULL
            GROUP BY cil
        )
        SELECT d.dt_inspecao, d.y, f.*
        FROM dedup_cea d
        JOIN tmp_features_cil f ON d.cil = f.cil
    """).df()

    # Taxa de fraude por PT calculada APENAS no treino (< 2025-07-01) para evitar leakage
    dt_corte = pd.Timestamp("2025-07-01")
    df_cea["dt_inspecao"] = pd.to_datetime(df_cea["dt_inspecao"])
    mask_treino = df_cea["dt_inspecao"] < dt_corte
    mask_teste = df_cea["dt_inspecao"] >= dt_corte

    taxa_global_treino = float(df_cea.loc[mask_treino, "y"].mean())
    pt_stats = (
        df_cea.loc[mask_treino]
        .groupby("pt")["y"]
        .agg(["count", "mean"])
        .reset_index()
    )
    # Suavização Bayesiana (m=20)
    pt_stats["taxa_suav"] = (pt_stats["count"] * pt_stats["mean"] + 20.0 * taxa_global_treino) / (pt_stats["count"] + 20.0)
    mapa_pt_taxa = dict(zip(pt_stats["pt"], pt_stats["taxa_suav"]))

    df_cea["taxa_fraude_pt_treino"] = df_cea["pt"].map(mapa_pt_taxa).fillna(taxa_global_treino)

    X_train = df_cea.loc[mask_treino, FEATURES].to_numpy(dtype=np.float64)
    y_train = df_cea.loc[mask_treino, "y"].to_numpy(dtype=np.float64)
    X_test = df_cea.loc[mask_teste, FEATURES].to_numpy(dtype=np.float64)
    y_test = df_cea.loc[mask_teste, "y"].to_numpy(dtype=np.float64)

    modelo = _treinar_logreg_l2(X_train, y_train, l2=5.0, lr=0.15, epochs=900)
    p_train = _prever_logreg(modelo, X_train)
    p_test = _prever_logreg(modelo, X_test)

    auc_train = _auc_roc(y_train, p_train)
    auc_test = _auc_roc(y_test, p_test)
    base_rate_test = float(y_test.mean())

    # Precision@k e Lift@k no teste out-of-time
    ordem_test = np.argsort(-p_test)
    y_ord = y_test[ordem_test]
    cortes = {}
    for pct in [5, 10, 20]:
        k = max(1, int(len(y_ord) * pct / 100.0))
        prec = float(y_ord[:k].mean())
        lift = prec / base_rate_test if base_rate_test > 0 else 1.0
        cortes[f"top_{pct}pct"] = {
            "k": k,
            "precision_pct": round(prec * 100, 1),
            "lift": round(lift, 2),
        }

    # Tabela por decil no teste out-of-time
    df_eval = pd.DataFrame({"y": y_test, "p": p_test})
    df_eval["decil"] = pd.qcut(df_eval["p"].rank(method="first", ascending=False), 10, labels=[f"D{i}" for i in range(1, 11)])
    decis = []
    for d_lbl, grp in df_eval.groupby("decil", observed=False):
        taxa_d = float(grp["y"].mean())
        decis.append({
            "decil": str(d_lbl),
            "insp": int(len(grp)),
            "fraudes": int(grp["y"].sum()),
            "taxa_fraude_pct": round(taxa_d * 100, 1),
            "lift": round(taxa_d / base_rate_test, 2) if base_rate_test > 0 else 1.0,
        })

    # 3. Pontuar toda a carteira (121.805 CILs)
    df_all = con.execute("SELECT * FROM tmp_features_cil").df()
    df_all["taxa_fraude_pt_treino"] = df_all["pt"].map(mapa_pt_taxa).fillna(taxa_global_treino)
    X_all = df_all[FEATURES].to_numpy(dtype=np.float64)
    p_all = _prever_logreg(modelo, X_all)

    # Normalizar para Score 0..100 por percentil/escala calibrada
    df_all["prob_fraude_v2"] = np.round(p_all * 100.0, 1)
    df_all["score_v2"] = np.clip(np.round((p_all / max(p_all.max(), 0.01)) * 100.0), 0, 100).astype(int)

    # Explicabilidade por CIL (top 3 contribuições positivas w_j * x_std_j)
    Xs_all = (X_all - modelo["mean"]) / modelo["std"]
    contrib = Xs_all * modelo["w"]
    motivos_lista = []
    for i in range(len(df_all)):
        c_row = contrib[i]
        idxs = np.argsort(-c_row)
        top_m = [LABELS_PT[FEATURES[j]] for j in idxs[:3] if c_row[j] > 0.05]
        motivos_lista.append(" + ".join(top_m) if top_m else "Perfil Base")
    df_all["motivos_v2"] = motivos_lista

    # Persistir tabela mart_score_v2 no DuckDB Silver/Gold
    con.register("df_score_v2_reg", df_all[["cil", "prob_fraude_v2", "score_v2", "motivos_v2"]])
    con.execute("CREATE OR REPLACE TABLE mart_score_v2 AS SELECT * FROM df_score_v2_reg")
    con.close()

    # Top 100 CILs prioritários para brigada de campo (com PT ou endereço)
    top100 = (
        df_all.sort_values(by=["prob_fraude_v2", "divida_exigivel"], ascending=[False, False])
        .head(100)
    )
    fila_top100 = [
        {
            "cil": int(r["cil"]),
            "nome": str(r["nome"] or "")[:45],
            "ilha": str(r["ilha"] or ""),
            "desc_uni": str(r["desc_uni"] or ""),
            "pt": str(r["pt"] or "S/ PT"),
            "prob_fraude_pct": float(r["prob_fraude_v2"]),
            "score_v2": int(r["score_v2"]),
            "divida_exigivel_ecv": round(float(r["divida_exigivel"] or 0), 0),
            "t3_kwh": round(float(r["t3_atual"] or 0), 0),
            "motivos_v2": str(r["motivos_v2"]),
        }
        for _, r in top100.iterrows()
    ]

    pesos_fmt = sorted(
        [
            {"feature": LABELS_PT[f], "peso_std": round(float(w), 3)}
            for f, w in zip(FEATURES, modelo["w"])
        ],
        key=lambda x: abs(x["peso_std"]),
        reverse=True,
    )

    resultado = {
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duracao_s": round(time.time() - t0, 2),
        "n_treino": int(len(y_train)),
        "n_teste_out_of_time": int(len(y_test)),
        "taxa_fraude_base_teste_pct": round(base_rate_test * 100, 1),
        "auc_treino": round(auc_train, 3),
        "auc_teste_out_of_time": round(auc_test, 3),
        "cortes": cortes,
        "decis": decis,
        "top_pesos": pesos_fmt[:10],
        "fila_brigada_top100": fila_top100,
    }

    gold_dir = os.path.join(base_santiago, "lake", "gold")
    os.makedirs(gold_dir, exist_ok=True)
    with open(os.path.join(gold_dir, "score_v2_metricas.json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"   Treino (<2025-07): {len(y_train):,} insp. | Teste Out-of-Time (>=2025-07): {len(y_test):,} insp. (Base fraude: {base_rate_test*100:.1f}%)")
    print(f"   AUC Treino: {auc_train:.3f} | AUC Teste Out-of-Time: {auc_test:.3f}")
    print(f"   Top 10% -> Precision: {cortes['top_10pct']['precision_pct']}% | Lift: {cortes['top_10pct']['lift']}x")
    print(f"   Top 20% -> Precision: {cortes['top_20pct']['precision_pct']}% | Lift: {cortes['top_20pct']['lift']}x")
    print(f"   Carteira pontuada: {len(df_all):,} CILs -> mart_score_v2 em {time.time() - t0:.2f}s")
    return resultado
