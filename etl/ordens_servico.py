"""
Módulo Gold — Inteligência de Ordens de Serviço & Retorno de Tesouraria (Aba 5 - Lakehouse Santiago)
Cruza as 66.352 Ordens de Serviço (fct_ordem_servico) com:
  - fct_cobranca (Conversão em Caixa 7d/15d/30d e Time-to-Cash após corte)
  - fct_divida_snapshot (Dívida Exigível retida em Cortes Pendentes OP e Autoconexão)
  - fct_fatura_conceito (Auditoria de Fuga de Faturação da Taxa de Religação RX0/RXO)
  - dim_contrato / dim_tpct / dim_local_consumo / dim_uc_geo (Segmento, Tarifa, PT e Unidade Comercial)
"""

import os
import json
import time
from datetime import datetime, timezone
import duckdb


SQL_FAMILIA_CASE = """
CASE
    WHEN o.desc_os ILIKE '%Corte%' THEN '1. Corte por Falta de Pagamento'
    WHEN o.desc_os ILIKE '%Religa%' OR o.desc_os ILIKE '%Realiga%' THEN '2. Religação de Fornecimento'
    WHEN o.desc_os IN (
        'Colocar e Ligar Contador', 'Ligar Contador', 'Ligação do Local de Consumo - Avença',
        'Ligação Provisória', 'Verificação do Contador p/ Contrato novo',
        'Verificaçao Contador/Vistoria p/Contrato', 'Colocação de Contador',
        'Levantamento Aparelho, Lig.Loc.Consumo'
    ) THEN '3. Novas Ligações & Contratação'
    WHEN o.desc_os IN (
        'Alteração Titular Contrato, mudança nome', 'Desligar Contador por rescisão Contrato',
        'Desligação da Ligação Provisória', 'Alterar Potência', 'Ligar e alterar Potência',
        'Vistoria Alteração Potência', 'Substituir e Alterar Potência',
        'Substituir, Ligar e Alterar Potência', 'Fim de Contrato Estaleiros'
    ) THEN '4. Gestão Contratual, Rescisão & Potência'
    WHEN o.desc_os IN (
        'Substituir Contador', 'Substituir e Ligar Contador', 'Revisão da Ligação',
        'Mudar Contador de Local', 'Levantamento de Contador',
        'Levantamento de Contador p/ verificação', 'Execução/Alteração e Reparação de Ramal',
        'Reparação Contador'
    ) THEN '5. Manutenção, Substituição & Rede'
    WHEN o.desc_os IN ('Leituras especiais', 'Local Consumo Sem Leitura') THEN '6. Leituras Especiais'
    ELSE '7. Inspeção, Fraude & Vistorias Técnicas'
END
"""


def executar_ordens_servico(base_santiago: str) -> dict:
    t0 = time.time()
    silver_dir = os.path.join(base_santiago, "lake", "silver")
    gold_dir = os.path.join(base_santiago, "lake", "gold")
    os.makedirs(gold_dir, exist_ok=True)
    db_path = os.path.join(silver_dir, "santiago.duckdb")

    con = duckdb.connect(db_path, read_only=True)

    # View temporária enriquecida das 66.352 Ordens de Serviço
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW vw_os_enriq AS
        WITH cli_info AS (
            SELECT DISTINCT ON (c.cil)
                c.cil,
                c.nome,
                COALESCE(t.grup_tp_cli, 'Doméstico') AS segmento,
                COALESCE(c.tarifa, 'D1') AS tarifa,
                COALESCE(c.produto, 'EB') AS produto,
                COALESCE(c.desc_uni, 'Praia') AS desc_uni_cli
            FROM dim_contrato c
            LEFT JOIN dim_tpct t ON c.tpct = t.cod_tpct
            ORDER BY c.cil, c.prio_titular ASC
        ),
        loc_info AS (
            SELECT cil, pt, localidade, desc_uni AS desc_uni_loc
            FROM dim_local_consumo
        )
        SELECT
            o.num_os,
            o.emp,
            o.uc,
            COALESCE(u.desc_uni, l.desc_uni_loc, i.desc_uni_cli, 'Praia') AS desc_uni,
            o.cil,
            COALESCE(i.nome, '') AS nome,
            COALESCE(l.pt, 'Sem PT') AS pt,
            COALESCE(l.localidade, '') AS localidade,
            COALESCE(i.segmento, 'Doméstico') AS segmento,
            COALESCE(i.tarifa, 'D1') AS tarifa,
            o.tipo_os,
            COALESCE(o.desc_os, 'Outros') AS desc_os,
            {SQL_FAMILIA_CASE} AS familia,
            COALESCE(o.est_os, 'OR') AS est_os,
            o.dt_solic,
            o.dt_emissao,
            o.dt_exec,
            COALESCE(o.dt_exec, o.dt_emissao, o.dt_solic) AS dt_ref,
            CASE WHEN o.sla_dias >= 0 AND o.sla_dias <= 365 THEN o.sla_dias END AS sla_val
        FROM fct_ordem_servico o
        LEFT JOIN dim_uc_geo u ON o.uc = u.uc
        LEFT JOIN cli_info i ON o.cil = i.cil
        LEFT JOIN loc_info l ON o.cil = l.cil
    """)

    # 1. Desdobramento das 66.352 OS por Unidade Comercial, Família, Tipo de Serviço e Segmento
    rows_fam = con.execute("""
        SELECT
            desc_uni,
            familia,
            desc_os,
            segmento,
            COUNT(*) AS emitidas,
            COUNT(*) FILTER (WHERE est_os = 'OR') AS or_realizadas,
            COUNT(*) FILTER (WHERE est_os = 'OP') AS op_pendentes,
            COUNT(*) FILTER (WHERE est_os = 'OA') AS oa_anuladas,
            COUNT(*) FILTER (WHERE est_os IN ('OE', 'OG')) AS oe_og_curso,
            COUNT(*) FILTER (WHERE est_os = 'OC') AS oc_canceladas,
            COUNT(DISTINCT cil) AS cils,
            ROUND(COALESCE(SUM(sla_val), 0), 1) AS soma_sla,
            COUNT(sla_val) AS qtd_sla
        FROM vw_os_enriq
        GROUP BY 1, 2, 3, 4
        ORDER BY familia, emitidas DESC
    """).fetchall()
    familias_rows = [
        {
            "desc_uni": r[0], "familia": r[1], "desc_os": r[2], "segmento": r[3],
            "emitidas": int(r[4]), "or_realizadas": int(r[5]), "op_pendentes": int(r[6]),
            "oa_anuladas": int(r[7]), "oe_og_curso": int(r[8]), "oc_canceladas": int(r[9]),
            "cils": int(r[10]), "soma_sla": float(r[11] or 0), "qtd_sla": int(r[12] or 0),
        }
        for r in rows_fam
    ]

    # 2. Retorno de Tesouraria (7d, 15d, 30d após OS de Corte) + Dívida Exigível Retida por Estado e Segmento
    con.execute("""
        CREATE OR REPLACE TEMP VIEW vw_cortes_cob AS
        WITH cortes AS (
            SELECT num_os, desc_uni, cil, nome, pt, localidade, segmento, tarifa, desc_os, est_os, dt_ref
            FROM vw_os_enriq
            WHERE familia = '1. Corte por Falta de Pagamento'
        ),
        cob_pos AS (
            SELECT
                ct.num_os,
                SUM(CASE WHEN cb.dt_cobranca BETWEEN ct.dt_ref AND ct.dt_ref + INTERVAL 7 DAY THEN cb.valor_ecv ELSE 0 END) AS cob_7d,
                SUM(CASE WHEN cb.dt_cobranca BETWEEN ct.dt_ref AND ct.dt_ref + INTERVAL 15 DAY THEN cb.valor_ecv ELSE 0 END) AS cob_15d,
                SUM(CASE WHEN cb.dt_cobranca BETWEEN ct.dt_ref AND ct.dt_ref + INTERVAL 30 DAY THEN cb.valor_ecv ELSE 0 END) AS cob_30d,
                MIN(CASE WHEN cb.dt_cobranca >= ct.dt_ref THEN cb.dt_cobranca - ct.dt_ref END) AS dias_ate_pagar
            FROM cortes ct
            LEFT JOIN fct_cobranca cb
              ON ct.cil = cb.cil
             AND cb.dt_cobranca BETWEEN ct.dt_ref AND ct.dt_ref + INTERVAL 30 DAY
            GROUP BY ct.num_os
        )
        SELECT
            ct.*,
            COALESCE(cp.cob_7d, 0) AS cob_7d,
            COALESCE(cp.cob_15d, 0) AS cob_15d,
            COALESCE(cp.cob_30d, 0) AS cob_30d,
            cp.dias_ate_pagar
        FROM cortes ct
        LEFT JOIN cob_pos cp ON ct.num_os = cp.num_os
    """)

    rows_ret = con.execute("""
        WITH div_cil AS (
            SELECT cil, SUM(CASE WHEN NOT is_prescrita THEN val_divida_ecv ELSE 0 END) AS div_exig
            FROM fct_divida_snapshot
            GROUP BY cil
        ),
        ag_os AS (
            SELECT
                desc_uni,
                est_os,
                segmento,
                CASE WHEN tarifa = 'S1' THEN 'S1 (Social)'
                     WHEN tarifa IN ('E1', 'E2', 'M1', 'M2') THEN 'MT/Especial (E/M)'
                     ELSE 'D1 (Convencional)' END AS grupo_tarifa,
                COUNT(*) AS qtd_os,
                COUNT(DISTINCT cil) AS cils,
                COUNT(*) FILTER (WHERE cob_7d > 0) AS pagaram_7d,
                COUNT(*) FILTER (WHERE cob_30d > 0) AS pagaram_30d,
                ROUND(SUM(cob_7d), 0) AS receita_7d_ecv,
                ROUND(SUM(cob_30d), 0) AS receita_30d_ecv,
                ROUND(COALESCE(SUM(dias_ate_pagar), 0), 1) AS soma_dias_pag,
                COUNT(dias_ate_pagar) AS qtd_dias_pag
            FROM vw_cortes_cob
            GROUP BY 1, 2, 3, 4
        ),
        div_est AS (
            SELECT
                c.desc_uni, c.est_os, c.segmento,
                CASE WHEN c.tarifa = 'S1' THEN 'S1 (Social)'
                     WHEN c.tarifa IN ('E1', 'E2', 'M1', 'M2') THEN 'MT/Especial (E/M)'
                     ELSE 'D1 (Convencional)' END AS grupo_tarifa,
                ROUND(SUM(COALESCE(d.div_exig, 0)), 0) AS div_exig_ecv
            FROM (SELECT DISTINCT desc_uni, est_os, segmento, tarifa, cil FROM vw_cortes_cob) c
            LEFT JOIN div_cil d ON c.cil = d.cil
            GROUP BY 1, 2, 3, 4
        )
        SELECT
            a.desc_uni, a.est_os, a.segmento, a.grupo_tarifa,
            a.qtd_os, a.cils, a.pagaram_7d, a.pagaram_30d,
            a.receita_7d_ecv, a.receita_30d_ecv,
            a.soma_dias_pag, a.qtd_dias_pag,
            COALESCE(de.div_exig_ecv, 0) AS div_exig_ecv
        FROM ag_os a
        LEFT JOIN div_est de
          ON a.desc_uni = de.desc_uni AND a.est_os = de.est_os
         AND a.segmento = de.segmento AND a.grupo_tarifa = de.grupo_tarifa
        ORDER BY a.est_os, a.qtd_os DESC
    """).fetchall()
    retorno_tesouraria_rows = [
        {
            "desc_uni": r[0], "est_os": r[1], "segmento": r[2], "grupo_tarifa": r[3],
            "qtd_os": int(r[4]), "cils": int(r[5]),
            "pagaram_7d": int(r[6]), "pagaram_30d": int(r[7]),
            "receita_7d_ecv": float(r[8] or 0), "receita_30d_ecv": float(r[9] or 0),
            "soma_dias_pag": float(r[10] or 0), "qtd_dias_pag": int(r[11] or 0),
            "divida_exigivel_ecv": float(r[12] or 0),
        }
        for r in rows_ret
    ]

    # 3. Calendário Prescritivo "QUANDO CORTAR" (Dia da Semana e Janela do Mês para Cortes Realizados OR)
    rows_sem = con.execute("""
        SELECT
            desc_uni,
            segmento,
            CAST(EXTRACT(ISODOW FROM dt_ref) AS INTEGER) AS dow,
            COUNT(*) AS cortes_or,
            COUNT(*) FILTER (WHERE cob_7d > 0) AS convertidos_7d,
            ROUND(SUM(cob_7d), 0) AS caixa_7d_ecv,
            ROUND(COALESCE(SUM(CASE WHEN cob_7d > 0 THEN dias_ate_pagar END), 0), 1) AS soma_dias,
            COUNT(CASE WHEN cob_7d > 0 THEN dias_ate_pagar END) AS qtd_dias
        FROM vw_cortes_cob
        WHERE est_os = 'OR' AND dt_ref IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY dow
    """).fetchall()
    quando_cortar_semana = [
        {
            "desc_uni": r[0], "segmento": r[1], "dow": int(r[2]),
            "cortes_or": int(r[3]), "convertidos_7d": int(r[4]),
            "caixa_7d_ecv": float(r[5] or 0),
            "soma_dias": float(r[6] or 0), "qtd_dias": int(r[7] or 0),
        }
        for r in rows_sem
    ]

    rows_mes = con.execute("""
        SELECT
            desc_uni,
            segmento,
            CASE
                WHEN EXTRACT(DAY FROM dt_ref) <= 10 THEN '1. Início do Mês (Dias 01–10)'
                WHEN EXTRACT(DAY FROM dt_ref) <= 20 THEN '2. Meio do Mês (Dias 11–20)'
                ELSE '3. Fim do Mês / Pós-Salário (Dias 21–31)'
            END AS janela_mes,
            COUNT(*) AS cortes_or,
            COUNT(*) FILTER (WHERE cob_15d > 0) AS convertidos_15d,
            ROUND(SUM(cob_15d), 0) AS caixa_15d_ecv,
            ROUND(COALESCE(SUM(CASE WHEN cob_15d > 0 THEN dias_ate_pagar END), 0), 1) AS soma_dias,
            COUNT(CASE WHEN cob_15d > 0 THEN dias_ate_pagar END) AS qtd_dias
        FROM vw_cortes_cob
        WHERE est_os = 'OR' AND dt_ref IS NOT NULL
        GROUP BY 1, 2, 3
        ORDER BY janela_mes
    """).fetchall()
    quando_cortar_mes = [
        {
            "desc_uni": r[0], "segmento": r[1], "janela_mes": r[2],
            "cortes_or": int(r[3]), "convertidos_15d": int(r[4]),
            "caixa_15d_ecv": float(r[5] or 0),
            "soma_dias": float(r[6] or 0), "qtd_dias": int(r[7] or 0),
        }
        for r in rows_mes
    ]

    # 4. Auditoria Cruzada por Unidade Comercial (Backlog OP + Fuga RX0 + Autoconexão Pós-Corte + Novas Ligações)
    rows_aud_uc = con.execute("""
        WITH div_cil AS (
            SELECT
                cil,
                COUNT(*) AS faturas_div,
                SUM(val_divida_ecv) AS div_tot,
                SUM(CASE WHEN NOT is_prescrita THEN val_divida_ecv ELSE 0 END) AS div_exig
            FROM fct_divida_snapshot
            GROUP BY cil
        ),
        op_cils AS (
            SELECT DISTINCT desc_uni, cil
            FROM vw_os_enriq
            WHERE familia = '1. Corte por Falta de Pagamento' AND est_os = 'OP'
        ),
        op_uc AS (
            SELECT
                o.desc_uni,
                COUNT(DISTINCT o.cil) AS cils_op,
                ROUND(SUM(COALESCE(d.div_exig, 0)), 0) AS div_exig_op_ecv
            FROM op_cils o
            LEFT JOIN div_cil d ON o.cil = d.cil
            GROUP BY o.desc_uni
        ),
        rel_2026 AS (
            SELECT desc_uni, cil, COUNT(*) AS qtd_rel_or, MAX(dt_ref) AS dt_ult_relig
            FROM vw_os_enriq
            WHERE familia = '2. Religação de Fornecimento' AND est_os = 'OR' AND EXTRACT(YEAR FROM dt_ref) = 2026
            GROUP BY 1, 2
        ),
        rx_2026 AS (
            SELECT cil, COUNT(DISTINCT numfact) AS qtd_rx0, SUM(val_conceito) AS val_rx0
            FROM fct_fatura_conceito
            WHERE conceito IN ('RXO', 'RX0') AND val_conceito > 0
            GROUP BY cil
        ),
        fuga_uc AS (
            SELECT
                r.desc_uni,
                COUNT(*) AS cils_relig_2026,
                SUM(r.qtd_rel_or) AS os_relig_or_2026,
                COUNT(x.cil) AS cils_com_rx0,
                COUNT(*) - COUNT(x.cil) AS cils_sem_rx0,
                SUM(CASE WHEN r.qtd_rel_or > COALESCE(x.qtd_rx0, 0) THEN r.qtd_rel_or - COALESCE(x.qtd_rx0, 0) ELSE 0 END) AS atos_sem_rx0,
                ROUND(SUM(CASE WHEN r.qtd_rel_or > COALESCE(x.qtd_rx0, 0) THEN (r.qtd_rel_or - COALESCE(x.qtd_rx0, 0)) * 1533.8 ELSE 0 END), 0) AS perda_estimada_rx0_ecv
            FROM rel_2026 r
            LEFT JOIN rx_2026 x ON r.cil = x.cil
            GROUP BY r.desc_uni
        ),
        ult_corte AS (
            SELECT desc_uni, cil, MAX(dt_ref) AS dt_ult_corte, COUNT(*) AS qtd_cortes
            FROM vw_os_enriq
            WHERE familia = '1. Corte por Falta de Pagamento' AND est_os = 'OR'
            GROUP BY 1, 2
        ),
        ult_rel AS (
            SELECT cil, MAX(dt_ref) AS dt_ult_relig
            FROM vw_os_enriq
            WHERE familia = '2. Religação de Fornecimento' AND est_os = 'OR'
            GROUP BY 1
        ),
        pag_pos AS (
            SELECT c.cil, SUM(cb.valor_ecv) AS val_pago
            FROM ult_corte c
            JOIN fct_cobranca cb ON c.cil = cb.cil AND cb.dt_cobranca >= c.dt_ult_corte
            GROUP BY c.cil
        ),
        auto_uc AS (
            SELECT
                c.desc_uni,
                COUNT(*) FILTER (WHERE (r.dt_ult_relig IS NULL OR r.dt_ult_relig < c.dt_ult_corte) AND COALESCE(p.val_pago, 0) = 0) AS cils_autoconexao,
                ROUND(SUM(COALESCE(d.div_exig, 0)) FILTER (WHERE (r.dt_ult_relig IS NULL OR r.dt_ult_relig < c.dt_ult_corte) AND COALESCE(p.val_pago, 0) = 0), 0) AS div_autoconexao_ecv
            FROM ult_corte c
            LEFT JOIN ult_rel r ON c.cil = r.cil
            LEFT JOIN pag_pos p ON c.cil = p.cil
            LEFT JOIN div_cil d ON c.cil = d.cil
            GROUP BY c.desc_uni
        ),
        base_uc AS (
            SELECT
                desc_uni,
                COUNT(*) AS total_os,
                COUNT(*) FILTER (WHERE est_os = 'OR') AS total_or,
                COUNT(*) FILTER (WHERE familia = '1. Corte por Falta de Pagamento') AS cortes_emit,
                COUNT(*) FILTER (WHERE familia = '1. Corte por Falta de Pagamento' AND est_os = 'OR') AS cortes_or,
                COUNT(*) FILTER (WHERE familia = '1. Corte por Falta de Pagamento' AND est_os = 'OP') AS cortes_op,
                COUNT(*) FILTER (WHERE familia = '1. Corte por Falta de Pagamento' AND est_os = 'OA') AS cortes_oa,
                COUNT(*) FILTER (WHERE familia = '3. Novas Ligações & Contratação' AND est_os = 'OR') AS novas_lig_or,
                COUNT(*) FILTER (WHERE familia = '3. Novas Ligações & Contratação' AND est_os IN ('OE', 'OG', 'OP')) AS novas_lig_fila
            FROM vw_os_enriq
            GROUP BY desc_uni
        )
        SELECT
            b.desc_uni,
            b.total_os, b.total_or, b.cortes_emit, b.cortes_or, b.cortes_op, b.cortes_oa,
            COALESCE(o.cils_op, 0) AS cils_op,
            COALESCE(o.div_exig_op_ecv, 0) AS div_exig_op_ecv,
            COALESCE(f.os_relig_or_2026, 0) AS os_relig_or_2026,
            COALESCE(f.cils_relig_2026, 0) AS cils_relig_2026,
            COALESCE(f.cils_com_rx0, 0) AS cils_com_rx0,
            COALESCE(f.cils_sem_rx0, 0) AS cils_sem_rx0,
            COALESCE(f.atos_sem_rx0, 0) AS atos_sem_rx0,
            COALESCE(f.perda_estimada_rx0_ecv, 0) AS perda_estimada_rx0_ecv,
            COALESCE(a.cils_autoconexao, 0) AS cils_autoconexao,
            COALESCE(a.div_autoconexao_ecv, 0) AS div_autoconexao_ecv,
            b.novas_lig_or,
            b.novas_lig_fila
        FROM base_uc b
        LEFT JOIN op_uc o ON b.desc_uni = o.desc_uni
        LEFT JOIN fuga_uc f ON b.desc_uni = f.desc_uni
        LEFT JOIN auto_uc a ON b.desc_uni = a.desc_uni
        ORDER BY b.total_os DESC
    """).fetchall()
    auditoria_por_unidade = [
        {
            "desc_uni": r[0],
            "total_os": int(r[1]), "total_or": int(r[2]),
            "cortes_emit": int(r[3]), "cortes_or": int(r[4]),
            "cortes_op": int(r[5]), "cortes_oa": int(r[6]),
            "cils_op": int(r[7]), "div_exig_op_ecv": float(r[8] or 0),
            "os_relig_or_2026": int(r[9]), "cils_relig_2026": int(r[10]),
            "cils_com_rx0": int(r[11]), "cils_sem_rx0": int(r[12]),
            "atos_sem_rx0": int(r[13]), "perda_estimada_rx0_ecv": float(r[14] or 0),
            "cils_autoconexao": int(r[15]), "div_autoconexao_ecv": float(r[16] or 0),
            "novas_lig_or": int(r[17]), "novas_lig_fila": int(r[18]),
        }
        for r in rows_aud_uc
    ]

    # 5. FILA 1: Top 250 Alvos de Corte Pendente (OP) ordenados por Retorno Esperado de Tesouraria (EV_30d)
    rows_top_ev = con.execute("""
        WITH op_agg AS (
            SELECT
                cil,
                ANY_VALUE(nome) AS nome,
                ANY_VALUE(desc_uni) AS desc_uni,
                ANY_VALUE(pt) AS pt,
                ANY_VALUE(localidade) AS localidade,
                ANY_VALUE(segmento) AS segmento,
                ANY_VALUE(tarifa) AS tarifa,
                COUNT(*) AS qtd_os_op,
                MIN(dt_solic) AS min_dt_solic,
                MAX(dt_ref) AS ult_dt_os
            FROM vw_os_enriq
            WHERE familia = '1. Corte por Falta de Pagamento' AND est_os = 'OP'
            GROUP BY cil
        ),
        div_cil AS (
            SELECT
                cil,
                COUNT(*) AS faturas_abertas,
                ROUND(SUM(CASE WHEN NOT is_prescrita THEN val_divida_ecv ELSE 0 END), 0) AS div_exigivel_ecv,
                ROUND(SUM(CASE WHEN aging_dias <= 365 THEN val_divida_ecv ELSE 0 END), 0) AS div_1ano_ecv
            FROM fct_divida_snapshot
            GROUP BY cil
        )
        SELECT
            o.cil,
            o.nome,
            o.desc_uni,
            o.pt,
            o.localidade,
            o.segmento,
            o.tarifa,
            o.qtd_os_op,
            CAST(o.ult_dt_os AS VARCHAR) AS dt_os,
            COALESCE(d.faturas_abertas, 0) AS faturas_abertas,
            COALESCE(d.div_exigivel_ecv, 0) AS div_exigivel_ecv,
            CASE
                WHEN o.segmento = 'Empresa Privada' THEN 82.8
                WHEN o.segmento IN ('Autarquia', 'Estado', 'Empresa Publica') THEN 71.4
                WHEN o.tarifa = 'S1' THEN 70.1
                ELSE 72.8
            END AS prob_conversao_pct,
            ROUND(
                COALESCE(d.div_exigivel_ecv, 0) * (
                    CASE
                        WHEN o.segmento = 'Empresa Privada' THEN 0.828
                        WHEN o.segmento IN ('Autarquia', 'Estado', 'Empresa Publica') THEN 0.714
                        WHEN o.tarifa = 'S1' THEN 0.701
                        ELSE 0.728
                    END
                ) + 1903.0, 0
            ) AS ev_30d_ecv
        FROM op_agg o
        JOIN div_cil d ON o.cil = d.cil
        WHERE d.div_exigivel_ecv >= 5000
        ORDER BY ev_30d_ecv DESC
        LIMIT 250
    """).fetchall()
    fila_corte_op_ev = [
        {
            "cil": int(r[0]), "nome": r[1], "desc_uni": r[2], "pt": r[3], "localidade": r[4],
            "segmento": r[5], "tarifa": r[6], "qtd_os_op": int(r[7]), "dt_os": r[8] or "",
            "faturas_abertas": int(r[9]), "div_exigivel_ecv": float(r[10] or 0),
            "prob_conversao_pct": float(r[11] or 0), "ev_30d_ecv": float(r[12] or 0),
        }
        for r in rows_top_ev
    ]

    # 6. FILA 2: Top 250 CILs com Religação Realizada (OR) em 2026 SEM Taxa RX0 Faturada (Auditoria de Fuga RX0)
    rows_top_fuga = con.execute("""
        WITH rel_2026 AS (
            SELECT
                cil,
                ANY_VALUE(nome) AS nome,
                ANY_VALUE(desc_uni) AS desc_uni,
                ANY_VALUE(pt) AS pt,
                ANY_VALUE(localidade) AS localidade,
                ANY_VALUE(segmento) AS segmento,
                ANY_VALUE(tarifa) AS tarifa,
                COUNT(*) AS qtd_rel_or,
                MAX(dt_ref) AS ult_dt_relig
            FROM vw_os_enriq
            WHERE familia = '2. Religação de Fornecimento' AND est_os = 'OR' AND EXTRACT(YEAR FROM dt_ref) = 2026
            GROUP BY cil
        ),
        rx_2026 AS (
            SELECT cil, COUNT(DISTINCT numfact) AS qtd_rx0, SUM(val_conceito) AS val_rx0
            FROM fct_fatura_conceito
            WHERE conceito IN ('RXO', 'RX0') AND val_conceito > 0
            GROUP BY cil
        ),
        cob_2026 AS (
            SELECT cil, ROUND(SUM(valor_ecv), 0) AS cob_ecv
            FROM fct_cobranca WHERE ano_cob >= 2026 GROUP BY cil
        )
        SELECT
            r.cil, r.nome, r.desc_uni, r.pt, r.localidade, r.segmento, r.tarifa,
            r.qtd_rel_or,
            COALESCE(x.qtd_rx0, 0) AS qtd_rx0_faturadas,
            r.qtd_rel_or - COALESCE(x.qtd_rx0, 0) AS atos_sem_rx0,
            CAST(r.ult_dt_relig AS VARCHAR) AS dt_ult_relig,
            (r.qtd_rel_or - COALESCE(x.qtd_rx0, 0)) * 2069 AS rx0_nao_faturado_ecv,
            COALESCE(c.cob_ecv, 0) AS cobranca_2026_ecv
        FROM rel_2026 r
        LEFT JOIN rx_2026 x ON r.cil = x.cil
        LEFT JOIN cob_2026 c ON r.cil = c.cil
        WHERE r.qtd_rel_or > COALESCE(x.qtd_rx0, 0)
        ORDER BY atos_sem_rx0 DESC, cobranca_2026_ecv DESC
        LIMIT 250
    """).fetchall()
    fila_fuga_rx0 = [
        {
            "cil": int(r[0]), "nome": r[1], "desc_uni": r[2], "pt": r[3], "localidade": r[4],
            "segmento": r[5], "tarifa": r[6], "qtd_rel_or": int(r[7]),
            "qtd_rx0_faturadas": int(r[8]), "atos_sem_rx0": int(r[9]),
            "dt_ult_relig": r[10] or "", "rx0_nao_faturado_ecv": float(r[11] or 0),
            "cobranca_2026_ecv": float(r[12] or 0),
        }
        for r in rows_top_fuga
    ]

    # 7. FILA 3: Top 250 Suspeitos de Autoconexão Clandestina Pós-Corte (Cortado OR, sem Religação, 0 ECV pagos)
    rows_top_auto = con.execute("""
        WITH ult_corte AS (
            SELECT
                cil,
                ANY_VALUE(nome) AS nome,
                ANY_VALUE(desc_uni) AS desc_uni,
                ANY_VALUE(pt) AS pt,
                ANY_VALUE(localidade) AS localidade,
                ANY_VALUE(segmento) AS segmento,
                ANY_VALUE(tarifa) AS tarifa,
                MAX(dt_ref) AS dt_ult_corte,
                COUNT(*) AS qtd_cortes_or
            FROM vw_os_enriq
            WHERE familia = '1. Corte por Falta de Pagamento' AND est_os = 'OR'
            GROUP BY cil
        ),
        ult_rel AS (
            SELECT cil, MAX(dt_ref) AS dt_ult_relig
            FROM vw_os_enriq
            WHERE familia = '2. Religação de Fornecimento' AND est_os = 'OR'
            GROUP BY cil
        ),
        pag_pos AS (
            SELECT c.cil, SUM(cb.valor_ecv) AS val_pago
            FROM ult_corte c
            JOIN fct_cobranca cb ON c.cil = cb.cil AND cb.dt_cobranca >= c.dt_ult_corte
            GROUP BY c.cil
        ),
        div_cil AS (
            SELECT
                cil,
                COUNT(*) AS faturas_abertas,
                ROUND(SUM(CASE WHEN NOT is_prescrita THEN val_divida_ecv ELSE 0 END), 0) AS div_exigivel_ecv
            FROM fct_divida_snapshot
            GROUP BY cil
        )
        SELECT
            c.cil, c.nome, c.desc_uni, c.pt, c.localidade, c.segmento, c.tarifa,
            c.qtd_cortes_or,
            CAST(c.dt_ult_corte AS VARCHAR) AS dt_ult_corte,
            COALESCE(d.faturas_abertas, 0) AS faturas_abertas,
            COALESCE(d.div_exigivel_ecv, 0) AS div_exigivel_ecv
        FROM ult_corte c
        LEFT JOIN ult_rel r ON c.cil = r.cil
        LEFT JOIN pag_pos p ON c.cil = p.cil
        JOIN div_cil d ON c.cil = d.cil
        WHERE (r.dt_ult_relig IS NULL OR r.dt_ult_relig < c.dt_ult_corte)
          AND COALESCE(p.val_pago, 0) = 0
          AND d.div_exigivel_ecv > 0
        ORDER BY d.div_exigivel_ecv DESC
        LIMIT 250
    """).fetchall()
    fila_autoconexao = [
        {
            "cil": int(r[0]), "nome": r[1], "desc_uni": r[2], "pt": r[3], "localidade": r[4],
            "segmento": r[5], "tarifa": r[6], "qtd_cortes_or": int(r[7]),
            "dt_ult_corte": r[8] or "", "faturas_abertas": int(r[9]),
            "div_exigivel_ecv": float(r[10] or 0),
        }
        for r in rows_top_auto
    ]

    con.close()

    # Totais Globais Consolidados
    tot_emit = sum(r["emitidas"] for r in familias_rows)
    tot_or = sum(r["or_realizadas"] for r in familias_rows)
    tot_op = sum(r["op_pendentes"] for r in familias_rows)
    tot_oa = sum(r["oa_anuladas"] for r in familias_rows)
    tot_oe_og = sum(r["oe_og_curso"] for r in familias_rows)
    tot_oc = sum(r["oc_canceladas"] for r in familias_rows)
    tot_sla_s = sum(r["soma_sla"] for r in familias_rows)
    tot_sla_n = sum(r["qtd_sla"] for r in familias_rows)

    cortes_emit = sum(r["emitidas"] for r in familias_rows if r["familia"].startswith("1."))
    cortes_or = sum(r["or_realizadas"] for r in familias_rows if r["familia"].startswith("1."))
    cortes_op = sum(r["op_pendentes"] for r in familias_rows if r["familia"].startswith("1."))
    cortes_oa = sum(r["oa_anuladas"] for r in familias_rows if r["familia"].startswith("1."))

    ret_or = [r for r in retorno_tesouraria_rows if r["est_os"] == "OR"]
    ret_oa = [r for r in retorno_tesouraria_rows if r["est_os"] == "OA"]
    caixa_or_30d = sum(r["receita_30d_ecv"] for r in ret_or)
    caixa_oa_30d = sum(r["receita_30d_ecv"] for r in ret_oa)
    pag_or_30d = sum(r["pagaram_30d"] for r in ret_or)
    qtd_or_ret = sum(r["qtd_os"] for r in ret_or)
    dias_or_s = sum(r["soma_dias_pag"] for r in ret_or)
    dias_or_n = sum(r["qtd_dias_pag"] for r in ret_or)

    div_op_tot = sum(r["div_exig_op_ecv"] for r in auditoria_por_unidade)
    cils_op_tot = sum(r["cils_op"] for r in auditoria_por_unidade)
    atos_sem_rx0_tot = sum(r["atos_sem_rx0"] for r in auditoria_por_unidade)
    cils_sem_rx0_tot = sum(r["cils_sem_rx0"] for r in auditoria_por_unidade)
    perda_rx0_tot = sum(r["perda_estimada_rx0_ecv"] for r in auditoria_por_unidade)
    cils_auto_tot = sum(r["cils_autoconexao"] for r in auditoria_por_unidade)
    div_auto_tot = sum(r["div_autoconexao_ecv"] for r in auditoria_por_unidade)
    novas_lig_or_tot = sum(r["novas_lig_or"] for r in auditoria_por_unidade)
    novas_lig_fila_tot = sum(r["novas_lig_fila"] for r in auditoria_por_unidade)

    resultado = {
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resumo": {
            "total_os": tot_emit,
            "or_realizadas": tot_or,
            "op_pendentes": tot_op,
            "oa_anuladas": tot_oa,
            "oe_og_curso": tot_oe_og,
            "oc_canceladas": tot_oc,
            "taxa_execucao_pct": round((tot_or / tot_emit) * 100.0, 1) if tot_emit > 0 else 0.0,
            "sla_medio_dias": round(tot_sla_s / tot_sla_n, 1) if tot_sla_n > 0 else 0.0,
            "cortes_emitidas": cortes_emit,
            "cortes_or": cortes_or,
            "cortes_op": cortes_op,
            "cortes_oa": cortes_oa,
            "eficacia_corte_pct": round((cortes_or / cortes_emit) * 100.0, 1) if cortes_emit > 0 else 0.0,
            "caixa_pos_corte_or_30d_ecv": round(caixa_or_30d, 0),
            "caixa_pre_aviso_oa_30d_ecv": round(caixa_oa_30d, 0),
            "caixa_total_induzido_30d_ecv": round(caixa_or_30d + caixa_oa_30d, 0),
            "taxa_conversao_or_30d_pct": round((pag_or_30d / qtd_or_ret) * 100.0, 1) if qtd_or_ret > 0 else 0.0,
            "time_to_cash_or_dias": round(dias_or_s / dias_or_n, 1) if dias_or_n > 0 else 0.0,
            "cils_corte_pendente_op": cils_op_tot,
            "divida_exigivel_retida_op_ecv": round(div_op_tot, 0),
            "atos_relig_sem_rx0_2026": atos_sem_rx0_tot,
            "cils_relig_sem_rx0_2026": cils_sem_rx0_tot,
            "perda_estimada_rx0_ecv": round(perda_rx0_tot, 0),
            "cils_autoconexao_pos_corte": cils_auto_tot,
            "divida_autoconexao_ecv": round(div_auto_tot, 0),
            "novas_ligacoes_or": novas_lig_or_tot,
            "novas_ligacoes_fila": novas_lig_fila_tot,
        },
        "auditoria_por_unidade": auditoria_por_unidade,
        "familias_rows": familias_rows,
        "retorno_tesouraria_rows": retorno_tesouraria_rows,
        "quando_cortar_semana": quando_cortar_semana,
        "quando_cortar_mes": quando_cortar_mes,
        "fila_corte_op_ev": fila_corte_op_ev,
        "fila_fuga_rx0": fila_fuga_rx0,
        "fila_autoconexao": fila_autoconexao,
    }

    out_path = os.path.join(gold_dir, "ordens_servico.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    r = resultado["resumo"]
    print(f" ORDENS DE SERVIÇO GOLD CONCLUÍDA em {time.time() - t0:.2f}s -> {out_path}")
    print(f"   - Total OS: {r['total_os']:,} | Realizadas OR: {r['or_realizadas']:,} ({r['taxa_execucao_pct']}%) | Backlog Corte OP: {r['cortes_op']:,} ({r['divida_exigivel_retida_op_ecv']/1e6:.1f}M ECV)")
    print(f"   - Retorno Caixa 30d: {r['caixa_total_induzido_30d_ecv']/1e6:.1f}M ECV | Conversão OR: {r['taxa_conversao_or_30d_pct']}% em {r['time_to_cash_or_dias']}d")
    print(f"   - Auditoria Fuga RX0: {r['atos_relig_sem_rx0_2026']:,} religações s/ taxa ({r['perda_estimada_rx0_ecv']/1e6:.2f}M ECV) | Autoconexão: {r['cils_autoconexao_pos_corte']:,} CILs ({r['divida_autoconexao_ecv']/1e6:.2f}M ECV)")
    return resultado


if __name__ == "__main__":
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    executar_ordens_servico(BASE)
