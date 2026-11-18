"""
Camada Silver (Fase 1 - Lakehouse Local Santiago)
Constrói o modelo dimensional e tabelas de factos ao grão atómico
em DuckDB (lake/silver/santiago.duckdb) diretamente sobre os Parquets da Bronze.
"""

import os
import time
from datetime import datetime

import duckdb


def executar_silver(base_santiago: str, anos_prescricao: int = 5) -> dict:
    t0 = time.time()
    bronze_dir = os.path.join(base_santiago, "lake", "bronze").replace("\\", "/")
    silver_dir = os.path.join(base_santiago, "lake", "silver")
    os.makedirs(silver_dir, exist_ok=True)
    db_path = os.path.join(silver_dir, "santiago.duckdb")

    print("=" * 72)
    print(" FASE 1 - CAMADA SILVER (DUCKDB DIMENSIONAL + FACTOS ATÓMICOS)")
    print("=" * 72)

    con = duckdb.connect(db_path)

    # 1. Dimensões de Referência
    con.execute("""
        CREATE OR REPLACE TABLE dim_empresa AS
        SELECT * FROM (VALUES
            ('17', 'EDEC Sul',     'Faturação Corrente Energia (EB, EE, EM)', true),
            ('21', 'Electra SA',   'Contrato Especial AdS (Água AG)',         true),
            ('7',  'Electra Sul',  'Dívida Histórica Legada',                 false),
            ('70', 'Electra SARL', 'Dívida Antiga Legada',                    false)
        ) AS t(cod_empresa, nome_empresa, papel_operacional, fatura_corrente);
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE dim_uc_geo AS
        SELECT DISTINCT
            LPAD(CAST(TRY_CAST(CAST(COD_UNI AS DOUBLE) AS BIGINT) AS VARCHAR), 9, '0') AS uc,
            TRIM(DESC_UNI) AS desc_uni,
            NULLIF(TRIM(ILHA), '') AS ilha,
            CASE WHEN TRIM(ILHA) IN ('Santiago', 'Fogo', 'Maio', 'Brava') THEN true ELSE false END AS is_regiao_sul
        FROM read_parquet('{bronze_dir}/dim_auxiliares/cod_uc.parquet')
        WHERE TRY_CAST(CAST(COD_UNI AS DOUBLE) AS BIGINT) IS NOT NULL;
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE dim_estctr AS
        SELECT DISTINCT
            TRY_CAST(CAST("Código" AS DOUBLE) AS INTEGER) AS cod_estctr,
            TRIM("Descrição") AS desc_estctr
        FROM read_parquet('{bronze_dir}/dim_auxiliares/cod_estctr.parquet')
        WHERE TRY_CAST(CAST("Código" AS DOUBLE) AS INTEGER) IS NOT NULL;
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE dim_tpct AS
        SELECT DISTINCT
            TRY_CAST(CAST(COD_CLI AS DOUBLE) AS INTEGER) AS cod_tpct,
            TRIM(GRUP_TP_CLI) AS grup_tp_cli
        FROM read_parquet('{bronze_dir}/dim_auxiliares/cod_tpct.parquet')
        WHERE TRY_CAST(CAST(COD_CLI AS DOUBLE) AS INTEGER) IS NOT NULL;
    """)

    # 2. Contratos (Universo Região Sul + Contratos Especiais AdS)
    con.execute(f"""
        CREATE OR REPLACE TABLE dim_contrato AS
        WITH base AS (
            SELECT
                EMP_CTR AS emp,
                LPAD(TRIM(UC), 9, '0') AS uc,
                TRY_CAST(NIB AS BIGINT) AS nib,
                TRY_CAST(CIL AS BIGINT) AS cil,
                TRY_CAST(ID AS BIGINT) AS id_cliente,
                TRY_CAST(TPCT AS INTEGER) AS tpct,
                NULLIF(TRIM(NOME), '') AS nome,
                NULLIF(TRIM(LOCALIDADE), '') AS localidade,
                UPPER(NULLIF(TRIM(PRODUTO), '')) AS produto,
                NULLIF(TRIM(TARIFA), '') AS tarifa,
                TRY_CAST(ESTCTR AS INTEGER) AS estctr,
                NULLIF(NULLIF(TRIM(DT_INI), '0'), '00000000') AS dt_ini,
                NULLIF(NULLIF(TRIM(DT_BAIXA), '0'), '00000000') AS dt_baixa
            FROM read_parquet('{bronze_dir}/contrato/contrato.parquet')
            UNION ALL
            SELECT '21', '010201000', 60209538, 60220187, 60209538, 72,
                   'AGUAS DE SANTIAGO S.A. (AdS - Água)', 'PRAIA - SEDE / DISTRIBUIÇÃO',
                   'AG', 'CD', 10, '20200101', NULL
            UNION ALL
            SELECT '21', '010201000', 60209538, 60220188, 60209538, 72,
                   'AGUAS DE SANTIAGO S.A. (AdS - Água)', 'PRAIA - SEDE / DISTRIBUIÇÃO',
                   'AG', 'CD', 10, '20200101', NULL
        )
        SELECT
            b.*,
            u.ilha,
            u.desc_uni,
            ROW_NUMBER() OVER (
                PARTITION BY b.cil
                ORDER BY
                    CASE b.emp WHEN '17' THEN 1 WHEN '21' THEN 2 WHEN '7' THEN 3 WHEN '70' THEN 4 ELSE 5 END,
                    CASE WHEN b.estctr IN (10, 11, 12, 13, 14, 15) THEN 0 ELSE 1 END,
                    COALESCE(TRY_CAST(b.dt_ini AS BIGINT), 0) DESC
            ) AS prio_titular
        FROM base b
        JOIN dim_uc_geo u ON b.uc = u.uc AND u.is_regiao_sul
        WHERE b.cil IS NOT NULL AND b.cil BETWEEN 10000000 AND 99999999;
    """)

    # 3. Local de Consumo (CIL único + Geo + Itinerário + IMTT)
    con.execute(f"""
        CREATE OR REPLACE TABLE dim_local_consumo AS
        WITH geo AS (
            SELECT DISTINCT ON (TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT))
                TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT) AS cil,
                NULLIF(TRIM(lat), '') AS lat,
                NULLIF(TRIM("long"), '') AS lon,
                NULLIF(TRIM(REGEXP_REPLACE(PT, '[\r\n\t]+', '', 'g')), '') AS pt
            FROM read_parquet('{bronze_dir}/dim_auxiliares/geo_pt.parquet')
            WHERE TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT) IS NOT NULL
        ),
        itin AS (
            SELECT DISTINCT ON (cil_n)
                CASE WHEN TRY_CAST(CIL AS BIGINT) < 60000000 THEN 60000000 + TRY_CAST(CIL AS BIGINT) ELSE TRY_CAST(CIL AS BIGINT) END AS cil_n,
                TRY_CAST(SEQ AS INTEGER) AS seq
            FROM read_parquet('{bronze_dir}/dim_auxiliares/itinerario.parquet')
            WHERE TRY_CAST(CIL AS BIGINT) IS NOT NULL
        ),
        imtt AS (
            SELECT DISTINCT ON (TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT))
                TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT) AS cil,
                NULLIF(TRIM(TIP), '') AS tip
            FROM read_parquet('{bronze_dir}/dim_auxiliares/imtt.parquet')
            WHERE TRY_CAST(CAST(CIL AS DOUBLE) AS BIGINT) IS NOT NULL
        ),
        ctr_top AS (
            SELECT * FROM dim_contrato WHERE prio_titular = 1
        )
        SELECT
            c.cil, c.ilha, c.uc, c.desc_uni, c.emp AS emp_principal, c.id_cliente AS id_titular_atual,
            c.nome, c.localidade, c.produto, c.tarifa, c.estctr,
            g.lat, g.lon, g.pt, i.seq, m.tip
        FROM ctr_top c
        LEFT JOIN geo g ON c.cil = g.cil
        LEFT JOIN itin i ON c.cil = i.cil_n
        LEFT JOIN imtt m ON c.cil = m.cil;
    """)

    # 4. Facto Faturação (Conceito + Fatura Única)
    con.execute(f"""
        CREATE OR REPLACE TABLE fct_fatura_conceito AS
        SELECT
            EMP AS emp,
            UC AS uc,
            PRODUTO AS produto,
            TRY_CAST(CIL AS BIGINT) AS cil,
            TRY_CAST(ID_CLIENTE AS BIGINT) AS id_cliente,
            TARIFA AS tarifa,
            TRY_STRPTIME(NULLIF(DT_ESTADO, ''), '%Y%m%d')::DATE AS dt_estado,
            TRY_STRPTIME(NULLIF(DT_FATURA, ''), '%Y%m%d')::DATE AS dt_fatura,
            NUMFACT AS numfact,
            VAL_TOT AS val_tot_fatura,
            CONCEITO AS conceito,
            QTD_CONSUMO AS qtd_consumo,
            VAL_CONCEITO AS val_conceito,
            LOTE_YM AS lote_ym
        FROM read_parquet('{bronze_dir}/faturacao_conceito/*.parquet')
        WHERE NUMFACT IS NOT NULL AND TRIM(NUMFACT) <> '';
    """)

    con.execute("""
        CREATE OR REPLACE TABLE fct_fatura AS
        WITH agg_cons AS (
            SELECT
                emp, numfact,
                MAX(uc) AS uc,
                MAX(produto) AS produto,
                MAX(cil) AS cil,
                MAX(id_cliente) AS id_cliente,
                MAX(tarifa) AS tarifa,
                MAX(dt_fatura) AS dt_fatura,
                MAX(lote_ym) AS lote_ym,
                MAX(val_tot_fatura) AS val_total_ecv,
                SUM(CASE WHEN conceito = 'X30' THEN qtd_consumo ELSE 0 END) AS qtd_x30,
                SUM(CASE WHEN conceito = 'X20' THEN qtd_consumo ELSE 0 END) AS qtd_x20,
                SUM(val_conceito) AS soma_conceitos_ecv
            FROM fct_fatura_conceito
            GROUP BY emp, numfact
        )
        SELECT
            emp, numfact, uc, produto, cil, id_cliente, tarifa, dt_fatura, lote_ym,
            val_total_ecv,
            CASE WHEN qtd_x30 <> 0 THEN qtd_x30 ELSE qtd_x20 END AS consumo_qtd,
            soma_conceitos_ecv
        FROM agg_cons;
    """)

    # 5. Facto Cobrança (Grão Movimento × Maturidade × Empresa)
    con.execute(f"""
        CREATE OR REPLACE TABLE fct_cobranca AS
        WITH base AS (
            SELECT
                c.EMP AS emp,
                c.UC AS uc,
                TRY_CAST(c.CIL AS BIGINT) AS cil,
                TRY_STRPTIME(NULLIF(TRIM(c.DATA_COBR), ''), '%Y%m%d')::DATE AS dt_cobranca,
                TRY_STRPTIME(NULLIF(TRIM(c.DATA_FAT), ''), '%Y%m%d')::DATE AS dt_fatura,
                c.TIPO_DOC AS tipo_doc,
                c.VALOR AS valor_ecv,
                c.ARQ_ORIGEM AS arq_origem
            FROM read_parquet('{bronze_dir}/cobranca/*.parquet') c
            JOIN dim_uc_geo u ON c.UC = u.uc AND u.is_regiao_sul
            WHERE c.TIPO_DOC <> 'XX'
              AND LENGTH(TRIM(c.CIL)) = 8
              AND TRY_CAST(c.CIL AS BIGINT) BETWEEN 10000000 AND 99999999
        )
        SELECT
            *,
            EXTRACT(YEAR FROM dt_cobranca)::INTEGER AS ano_cob,
            EXTRACT(MONTH FROM dt_cobranca)::INTEGER AS mes_cob,
            DATEDIFF('day', dt_fatura, dt_cobranca) AS dias_maturidade,
            CASE
                WHEN dt_fatura IS NULL OR dt_cobranca IS NULL OR DATEDIFF('day', dt_fatura, dt_cobranca) < 0 THEN 'Sem Data'
                WHEN DATEDIFF('day', dt_fatura, dt_cobranca) < 31 THEN '1 mes'
                WHEN DATEDIFF('day', dt_fatura, dt_cobranca) < 61 THEN '2 mes'
                WHEN DATEDIFF('day', dt_fatura, dt_cobranca) < 91 THEN '3 mes'
                WHEN DATEDIFF('day', dt_fatura, dt_cobranca) < 181 THEN '6 mes'
                WHEN DATEDIFF('day', dt_fatura, dt_cobranca) < 361 THEN '1 ano'
                ELSE '> 1 ano'
            END AS faixa_maturidade
        FROM base
        WHERE dt_cobranca IS NOT NULL;
    """)

    # 6. Facto Dívida Snapshot (Grão Fatura em Aberto + Aging Real + Prescrição Dinâmica)
    con.execute(f"""
        CREATE OR REPLACE TABLE fct_divida_snapshot AS
        WITH corte AS (
            SELECT CURRENT_DATE AS dt_ref, (CURRENT_DATE - INTERVAL '{int(anos_prescricao)} years')::DATE AS dt_presc
        ),
        base AS (
            SELECT
                d.EMP_ID AS emp,
                LPAD(TRIM(d.UNIDADE), 9, '0') AS uc,
                TRY_CAST(d.CIL AS BIGINT) AS cil,
                TRY_CAST(d.CLI_CONTA AS BIGINT) AS id_cliente,
                NULLIF(TRIM(d.NOME), '') AS nome,
                TRY_CAST(d.TPCT AS INTEGER) AS tpct,
                NULLIF(TRIM(d.TARIFA), '') AS tarifa,
                d.PRODUTO AS produto,
                TRY_STRPTIME(SUBSTR(TRIM(d.DT_EMISSAO), 1, 8), '%Y%m%d')::DATE AS dt_emissao,
                TRIM(d.NUMFACT) AS numfact,
                d.VAL_DIVIDA AS val_divida_ecv
            FROM read_parquet('{bronze_dir}/divida/divida.parquet') d
            JOIN dim_uc_geo u ON LPAD(TRIM(d.UNIDADE), 9, '0') = u.uc AND u.is_regiao_sul
            WHERE LENGTH(TRIM(d.CIL)) = 8
              AND TRY_CAST(d.CIL AS BIGINT) BETWEEN 10000000 AND 99999999
        )
        SELECT
            b.*,
            c.dt_ref AS dt_extracao,
            DATEDIFF('day', b.dt_emissao, c.dt_ref) AS aging_dias,
            CASE
                WHEN b.dt_emissao IS NULL THEN 'Sem Data'
                WHEN DATEDIFF('day', b.dt_emissao, c.dt_ref) <= 30 THEN '0-30d'
                WHEN DATEDIFF('day', b.dt_emissao, c.dt_ref) <= 90 THEN '31-90d'
                WHEN DATEDIFF('day', b.dt_emissao, c.dt_ref) <= 180 THEN '91-180d'
                WHEN DATEDIFF('day', b.dt_emissao, c.dt_ref) <= 365 THEN '181-365d'
                WHEN DATEDIFF('day', b.dt_emissao, c.dt_ref) <= 730 THEN '1-2 anos'
                WHEN DATEDIFF('day', b.dt_emissao, c.dt_ref) <= 1825 THEN '2-5 anos'
                ELSE '> 5 anos'
            END AS faixa_aging,
            CASE WHEN b.dt_emissao IS NOT NULL AND b.dt_emissao < c.dt_presc THEN true ELSE false END AS is_prescrita
        FROM base b
        CROSS JOIN corte c;
    """)

    # 7. Facto Inspeções CEA & Ordens de Serviço
    con.execute(f"""
        CREATE OR REPLACE TABLE fct_inspecao_cea AS
        SELECT
            TRY_STRPTIME(NULLIF(TRIM(Data), ''), '%d/%m/%Y')::DATE AS dt_inspecao,
            NULLIF(TRIM(Folha), '') AS folha,
            NULLIF(TRIM("Descrição Folha"), '') AS desc_folha,
            TRY_CAST(CIL AS BIGINT) AS cil,
            NULLIF(TRIM("Situação Consumidor"), '') AS situacao_consumidor,
            NULLIF(TRIM("Result.Inspecção"), '') AS resultado_inspecao,
            NULLIF(TRIM(Equipa), '') AS equipa,
            NULLIF(TRIM(Fornecimento), '') AS fornecimento,
            NULLIF(TRIM("Estado Contador"), '') AS estado_contador,
            PASTA_ORIGEM AS pasta_origem
        FROM read_parquet('{bronze_dir}/inspecao_cea/inspecao_cea.parquet')
        WHERE TRY_CAST(CIL AS BIGINT) BETWEEN 10000000 AND 99999999;
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE fct_ordem_servico AS
        SELECT
            o.EMP AS emp,
            LPAD(TRIM(o.UC), 9, '0') AS uc,
            TRY_CAST(o.CIL AS BIGINT) AS cil,
            TRY_CAST(o.NUM_OS AS BIGINT) AS num_os,
            TRIM(o.TIPO_OS) AS tipo_os,
            TRIM(o.DESC_OS) AS desc_os,
            TRIM(o.EST_OS) AS est_os,
            TRY_STRPTIME(NULLIF(TRIM(o.DT_SOLIC), ''), '%Y%m%d')::DATE AS dt_solic,
            TRY_STRPTIME(NULLIF(TRIM(o.DT_EMISSAO), ''), '%Y%m%d')::DATE AS dt_emissao,
            TRY_STRPTIME(NULLIF(TRIM(o.DT_EXEC), ''), '%Y%m%d')::DATE AS dt_exec,
            DATEDIFF('day', TRY_STRPTIME(NULLIF(TRIM(o.DT_EMISSAO), ''), '%Y%m%d')::DATE,
                            TRY_STRPTIME(NULLIF(TRIM(o.DT_EXEC), ''), '%Y%m%d')::DATE) AS sla_dias
        FROM read_parquet('{bronze_dir}/ordem_servico/ordem_servico.parquet') o
        JOIN dim_uc_geo u ON LPAD(TRIM(o.UC), 9, '0') = u.uc AND u.is_regiao_sul
        WHERE TRY_CAST(o.CIL AS BIGINT) BETWEEN 10000000 AND 99999999;
    """)

    # 8. Snapshot mensal imutável de dívida (base histórica para Roll-Rate)
    snap_dir = os.path.join(silver_dir, "snapshots_divida")
    os.makedirs(snap_dir, exist_ok=True)
    tag_mes = datetime.now().strftime("%Y-%m")
    snap_pq = os.path.join(snap_dir, f"dt_extracao={tag_mes}.parquet").replace("\\", "/")
    con.execute(f"""
        COPY (
            SELECT emp, cil, numfact, dt_emissao, faixa_aging, val_divida_ecv, is_prescrita, dt_extracao
            FROM fct_divida_snapshot
        ) TO '{snap_pq}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """)

    contagens = {}
    for tbl in [
        "dim_empresa", "dim_uc_geo", "dim_local_consumo", "dim_contrato",
        "fct_fatura", "fct_fatura_conceito", "fct_cobranca",
        "fct_divida_snapshot", "fct_inspecao_cea", "fct_ordem_servico",
    ]:
        contagens[tbl] = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]

    con.close()
    dur = round(time.time() - t0, 2)
    print(f" SILVER CONCLUÍDA em {dur:.2f}s -> {db_path}")
    for k, v in contagens.items():
        print(f"   - {k:22s}: {v:>10,} linhas")

    return {"executado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "duracao_s": dur, "contagens": contagens}
