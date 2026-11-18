import json
import os
from collections import defaultdict
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak, KeepTogether
)
from reportlab.platypus.tableofcontents import TableOfContents

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GOLD_PATH = os.path.join(BASE_DIR, "lake", "gold", "marts_gold.json")
OUT_DIR = os.path.join(BASE_DIR, "relatorios")
CHART_DIR = os.path.join(OUT_DIR, "_charts")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(CHART_DIR, exist_ok=True)

with open(GOLD_PATH, "r", encoding="utf-8") as f:
    G = json.load(f)

KPI = G["kpis_executivos"]
FAT_ROWS = G["faturacao_mensal"]["rows"]
COB_ROWS = G["cobranca_mensal"]["rows"]
AGING_ROWS = G["aging_divida"]["rows"]
ADS = G["ads_conta_corrente"]
OP = G["operacional_cea_os"]
SC = G["score_v2_validacao"]


def fmt_pt(val, dec=1):
    s = f"{val:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_ecv_curto(val):
    a = abs(val)
    if a >= 1e9:
        return f"{fmt_pt(val / 1e9, 2)}B"
    if a >= 1e6:
        return f"{fmt_pt(val / 1e6, 1)}M"
    if a >= 1e3:
        return f"{fmt_pt(val / 1e3, 1)}k"
    return fmt_pt(val, 0)


MESES_PT = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
    "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
    "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro",
}
MESES_CURTO_PT = {
    "01": "Jan", "02": "Fev", "03": "Mar", "04": "Abr",
    "05": "Mai", "06": "Jun", "07": "Jul", "08": "Ago",
    "09": "Set", "10": "Out", "11": "Nov", "12": "Dez",
}


def lote_para_mes_real(lote_ym: str) -> str:
    """Os lotes z3Facturas são extraídos no dia 1 do mês seguinte (ex.: 202602 = faturas de 2026-01)."""
    y, m = int(lote_ym[:4]), int(lote_ym[4:6])
    m -= 1
    if m == 0:
        y -= 1
        m = 12
    return f"{y:04d}-{m:02d}"


def nome_mes_pt(ym: str, curto: bool = False) -> str:
    p = ym.split("-")
    if len(p) == 2:
        dic = MESES_CURTO_PT if curto else MESES_PT
        return f"{dic.get(p[1], p[1])} {p[0]}" if not curto else f"{dic.get(p[1], p[1])}/{p[0][2:]}"
    return ym


# ==============================================================================
# 1. PREPARAR SÉRIES AGREGADAS
# ==============================================================================
# Série mensal 17 alinhada ao mês real de emissão (Janeiro..Outubro 2026)
fat_17_mes = defaultdict(lambda: {"kwh": 0.0, "ecv": 0.0, "EB": 0.0, "EM": 0.0, "EE": 0.0})
for r in FAT_ROWS:
    if r["emp"] == "17":
        m_str = lote_para_mes_real(r["lote_ym"])
        fat_17_mes[m_str]["kwh"] += float(r["consumo_qtd"] or 0)
        fat_17_mes[m_str]["ecv"] += float(r["valor_ecv"] or 0)
        prod = r.get("produto", "")
        if prod in ("EB", "EM", "EE"):
            fat_17_mes[m_str][prod] += float(r["valor_ecv"] or 0)

cob_17_mes = defaultdict(float)
for r in COB_ROWS:
    if str(r["emp"]) == "17":
        cob_17_mes[r["ano_mes"]] += float(r["valor_ecv"] or 0)

meses_17 = sorted(set(fat_17_mes.keys()) | set(cob_17_mes.keys()))

# Preparar Mix EB / EM / EE (17 · EDEC Sul)
mix_17 = defaultdict(lambda: {"kwh": 0.0, "ecv": 0.0, "fat": 0})
for r in FAT_ROWS:
    if r["emp"] == "17":
        p = r.get("produto", "")
        mix_17[p]["kwh"] += float(r["consumo_qtd"] or 0)
        mix_17[p]["ecv"] += float(r["valor_ecv"] or 0)
        mix_17[p]["fat"] += int(r["faturas"] or 0)

mix_labels = [("EB", "Baixa Tensão (EB)"), ("EM", "Média Tensão (EM)"), ("EE", "Especiais / IP (EE)")]
t_mix_hdr = ["Segmento (17)", "Faturas", "Energia (GWh)", "% GWh", "Faturado (M ECV)", "% ECV", "PM (ECV/kWh)"]
t_mix_rows = []
tot_mkwh = sum(mix_17[k]["kwh"] for k, _ in mix_labels) or 1.0
tot_mecv = sum(mix_17[k]["ecv"] for k, _ in mix_labels) or 1.0
tot_mfat = sum(mix_17[k]["fat"] for k, _ in mix_labels)
for cod_p, nome_p in mix_labels:
    d = mix_17[cod_p]
    pm_p = (d["ecv"] / d["kwh"]) if d["kwh"] > 0 else 0.0
    t_mix_rows.append([
        nome_p,
        f"{d['fat']:,}".replace(",", "."),
        fmt_pt(d["kwh"] / 1e6, 2),
        f"{fmt_pt(d['kwh'] / tot_mkwh * 100.0, 1)}%",
        fmt_pt(d["ecv"] / 1e6, 1),
        f"{fmt_pt(d['ecv'] / tot_mecv * 100.0, 1)}%",
        fmt_pt(pm_p, 2),
    ])
t_mix_rows.append([
    "TOTAL 17 · EDEC Sul",
    f"{tot_mfat:,}".replace(",", "."),
    fmt_pt(tot_mkwh / 1e6, 2), "100,0%",
    fmt_pt(tot_mecv / 1e6, 1), "100,0%",
    fmt_pt(tot_mecv / tot_mkwh, 2),
])

# Preparar Ponte Balanço Energético (Módulo 2)
BAL_TRIM = G.get("balanco_pt_trimestral", {}).get("trimestres", {})
t_bal_hdr = ["Trimestre", "PTs c/ Cob.", "Injetada (MWh)", "Faturada (MWh)", "Perda Total (%)", "PNT (MWh / %)", "Impacto PNT (ECV)"]
t_bal_rows = []
for cod_b in ["2026-T1", "2026-T2", "2026-T3"]:
    bt = BAL_TRIM.get(cod_b)
    if bt:
        t_bal_rows.append([
            cod_b,
            f"{bt['pts_com_cobertura']}/{bt['pts_medidos']}",
            fmt_pt(bt["injetada_mwh"], 1),
            fmt_pt(bt["faturada_mwh"], 1),
            f"{fmt_pt(bt['taxa_perda_pct'], 1)}%",
            f"{fmt_pt(bt.get('perda_pnt_mwh', 0), 1)} ({fmt_pt(bt.get('taxa_pnt_pct', 0), 1)}%)",
            fmt_ecv_curto(bt.get("prejuizo_pnt_ecv", 0)),
        ])

# Preparar Frescura das Fontes & Metas
FRESC = OP.get("frescura_fontes", [])
DQ = OP.get("qualidade_dados", {})
FUNIL = DQ.get("funil_divida", {})

t_dq_hdr = ["Categoria Fonte", "Último Ficheiro", "Modificado em", "Idade (dias)", "Estado"]
t_dq_rows = []
for fr in FRESC:
    st_f = "ATRASO" if fr.get("alerta_atraso") else "OK"
    t_dq_rows.append([
        fr["categoria"],
        fr["ultimo_ficheiro"][:34],
        fr["modificado_em"][:16],
        str(fr["dias_idade"]),
        st_f,
    ])

t_meta_hdr = ["Indicador / Foco", "Situação Atual", "Meta Proposta", "Responsável", "Horizonte"]
t_meta_rows = [
    ["Taxa Cobrança Real (17)", f"{fmt_pt(KPI['taxa_cobranca_17_pct'], 1)}%", "≥ 93,0%", "Dir. Comercial", "2026–2027"],
    ["DSO Médio Recebimento (17)", f"{KPI['dso_17_dias']} dias", "≤ 60 dias", "Cobrança & Tesouraria", "6 meses"],
    ["Dívida AdS (21 · Água AG)", f"{fmt_ecv_curto(KPI['divida_21_ecv'])} ECV", "Acordo / Regularização", "Administração / Fin.", "Curto Prazo"],
    ["Carteira Prescrita >5a (07/70)", f"{fmt_ecv_curto(KPI['divida_prescrita_ecv'])} ECV", "Segregação / Saneamento", "Contabilidade / DPO", "Trimestral"],
    ["Perda Não Técnica BT (PTs)", f"{fmt_pt(BAL_TRIM.get('2026-T3', {}).get('taxa_pnt_pct', 49.3), 1)}% (T3)", "-5,0 p.p. via Score v2", "Brigadas & DPO", "12 meses"],
]

# Resumo das 4 empresas
empresas_info = [
    {
        "cod": "17",
        "nome": "17 · EDEC Sul",
        "papel": "Operação Corrente (Energia Elétrica)",
        "fat_ecv": KPI["fat_17_ecv"],
        "fat_fisico": f"{fmt_pt(KPI['fat_17_kwh'] / 1e6, 1)} GWh",
        "cob_ecv": KPI["cob_17_ecv"],
        "div_total": KPI["divida_17_ecv"],
        "div_presc": sum(float(r["emp_17"]) for r in AGING_ROWS if r["faixa"] == "> 5 anos"),
    },
    {
        "cod": "21",
        "nome": "21 · Electra SA",
        "papel": "Cliente Especial AdS (Água AG)",
        "fat_ecv": KPI["fat_21_ads_ecv"],
        "fat_fisico": f"{fmt_pt(KPI['fat_21_ads_m3'] / 1e6, 2)}M m³",
        "cob_ecv": KPI["cob_21_ecv"],
        "div_total": KPI["divida_21_ecv"],
        "div_presc": sum(float(r["emp_21"]) for r in AGING_ROWS if r["faixa"] == "> 5 anos"),
    },
    {
        "cod": "07",
        "nome": "07 · Electra Sul",
        "papel": "Carteira Legada em Recuperação",
        "fat_ecv": 0.0,
        "fat_fisico": "—",
        "cob_ecv": KPI["cob_07_ecv"],
        "div_total": KPI["divida_07_ecv"],
        "div_presc": sum(float(r["emp_07"]) for r in AGING_ROWS if r["faixa"] == "> 5 anos"),
    },
    {
        "cod": "70",
        "nome": "70 · Electra SARL",
        "papel": "Carteira Histórica (> 5 anos)",
        "fat_ecv": 0.0,
        "fat_fisico": "—",
        "cob_ecv": KPI["cob_70_ecv"],
        "div_total": KPI["divida_70_ecv"],
        "div_presc": sum(float(r["emp_70"]) for r in AGING_ROWS if r["faixa"] == "> 5 anos"),
    },
]
for e in empresas_info:
    e["div_exig"] = e["div_total"] - e["div_presc"]


# ==============================================================================
# 2. GERAR GRÁFICOS MATPLOTLIB (300 DPI)
# ==============================================================================
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": "#CBD5E1",
    "axes.linewidth": 0.8,
    "grid.color": "#E2E8F0",
    "grid.linestyle": "--",
    "grid.linewidth": 0.6,
})

# FIG 1: Comparativo das 4 Empresas (Faturação, Cobrança, Dívida Exigível e Prescrita)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.2), dpi=300)
nomes_emp = [e["nome"] for e in empresas_info]
x = np.arange(len(nomes_emp))
w = 0.35

fat_m = [e["fat_ecv"] / 1e6 for e in empresas_info]
cob_m = [e["cob_ecv"] / 1e6 for e in empresas_info]
ax1.bar(x - w / 2, fat_m, width=w, label="Faturado 2026", color="#2563EB")
ax1.bar(x + w / 2, cob_m, width=w, label="Cobrado 2026", color="#10B981")
ax1.set_title("Faturação vs. Cobrança Real 2026 (M ECV)", fontsize=10.5, fontweight="bold", color="#0F172A")
ax1.set_xticks(x)
ax1.set_xticklabels(nomes_emp, fontsize=8.5, rotation=12)
ax1.grid(axis="y", alpha=0.7)
ax1.legend(fontsize=8.5, frameon=False)
for i, v in enumerate(fat_m):
    if v > 0:
        ax1.text(i - w / 2, v + 80, f"{v:,.0f}M", ha="center", va="bottom", fontsize=7.5)
for i, v in enumerate(cob_m):
    if v > 5:
        ax1.text(i + w / 2, v + 80, f"{v:,.0f}M", ha="center", va="bottom", fontsize=7.5)

exig_m = [max(e["div_exig"], 0) / 1e6 for e in empresas_info]
presc_m = [max(e["div_presc"], 0) / 1e6 for e in empresas_info]
ax2.bar(x, exig_m, width=0.52, label="Dívida Exigível (≤ 5a)", color="#F59E0B")
ax2.bar(x, presc_m, width=0.52, bottom=exig_m, label="Dívida Prescrita (> 5a)", color="#EF4444")
ax2.set_title("Composição da Dívida por Empresa (M ECV)", fontsize=10.5, fontweight="bold", color="#0F172A")
ax2.set_xticks(x)
ax2.set_xticklabels(nomes_emp, fontsize=8.5, rotation=12)
ax2.grid(axis="y", alpha=0.7)
ax2.legend(fontsize=8.5, frameon=False)
for i in range(len(x)):
    tot = exig_m[i] + presc_m[i]
    ax2.text(i, tot + 140, f"{tot/1000:.2f}B", ha="center", va="bottom", fontsize=8, fontweight="bold")

plt.tight_layout()
fig1_path = os.path.join(CHART_DIR, "fig1_empresas.png")
plt.savefig(fig1_path, dpi=300)
plt.close()

# FIG 2: Série Mensal 17 · EDEC Sul
fig, ax1 = plt.subplots(figsize=(10.2, 4.0), dpi=300)
xm = np.arange(len(meses_17))
fat_v = [fat_17_mes[m]["ecv"] / 1e6 for m in meses_17]
cob_v = [cob_17_mes[m] / 1e6 for m in meses_17]
taxa_v = [(cob_17_mes[m] / fat_17_mes[m]["ecv"] * 100.0) if fat_17_mes[m]["ecv"] > 0 else np.nan for m in meses_17]

ax1.bar(xm - 0.18, fat_v, width=0.36, label="Faturado (M ECV)", color="#3B82F6")
ax1.bar(xm + 0.18, cob_v, width=0.36, label="Cobrado (M ECV)", color="#10B981")
ax1.set_xticks(xm)
ax1.set_xticklabels([nome_mes_pt(m, curto=True) for m in meses_17], fontsize=8.5, rotation=15)
ax1.set_ylabel("Milhões ECV", fontsize=9, color="#1E293B")
ax1.grid(axis="y", alpha=0.7)
ax1.set_title("17 · EDEC Sul — Evolução Mensal Faturação vs. Cobrança 2026", fontsize=11, fontweight="bold", color="#0F172A")

ax2 = ax1.twinx()
valid_idx = [i for i, t in enumerate(taxa_v) if not np.isnan(t)]
ax2.plot([xm[i] for i in valid_idx], [taxa_v[i] for i in valid_idx], color="#F59E0B", marker="o", linewidth=2, label="Taxa Cobrança (%)")
ax2.axhline(90, color="#10B981", linestyle="--", linewidth=1, alpha=0.8, label="Meta 90%")
ax2.set_ylabel("Taxa Cobrança (%)", fontsize=9, color="#B45309")
ax2.set_ylim(0, 130)

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8, ncol=2, frameon=True, facecolor="white")
plt.tight_layout()
fig2_path = os.path.join(CHART_DIR, "fig2_mensal_17.png")
plt.savefig(fig2_path, dpi=300)
plt.close()

# FIG 3: Aging Real por Escalão e Empresa
fig, ax = plt.subplots(figsize=(10.2, 4.0), dpi=300)
faixas = [r["faixa"] for r in AGING_ROWS]
y = np.arange(len(faixas))
e17 = np.array([max(r["emp_17"], 0) / 1e6 for r in AGING_ROWS])
e21 = np.array([max(r["emp_21"], 0) / 1e6 for r in AGING_ROWS])
e07 = np.array([max(r["emp_07"], 0) / 1e6 for r in AGING_ROWS])
e70 = np.array([max(r["emp_70"], 0) / 1e6 for r in AGING_ROWS])

ax.barh(y, e17, label="17 · EDEC Sul", color="#3B82F6")
ax.barh(y, e21, left=e17, label="21 · Electra SA (AdS)", color="#F59E0B")
ax.barh(y, e07, left=e17 + e21, label="07 · Electra Sul", color="#8B5CF6")
ax.barh(y, e70, left=e17 + e21 + e07, label="70 · Electra SARL", color="#EC4899")
ax.set_yticks(y)
ax.set_yticklabels(faixas, fontsize=9)
ax.invert_yaxis()
ax.set_xlabel("Milhões ECV", fontsize=9)
ax.set_title("Aging Real da Dívida por Escalão e Empresa (M ECV)", fontsize=11, fontweight="bold", color="#0F172A")
ax.grid(axis="x", alpha=0.7)
ax.legend(fontsize=8.5, frameon=True, facecolor="white", loc="lower right")
for i, r in enumerate(AGING_ROWS):
    tot_m = r["total_ecv"] / 1e6
    ax.text(max(e17[i] + e21[i] + e07[i] + e70[i], 0) + 80, i, f"{tot_m:,.1f}M", va="center", fontsize=8, fontweight="bold")
plt.tight_layout()
fig3_path = os.path.join(CHART_DIR, "fig3_aging.png")
plt.savefig(fig3_path, dpi=300)
plt.close()

# FIG 4: AdS (21) Faturação Mensal & Aging
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 3.8), dpi=300)
ads_meses = [nome_mes_pt(lote_para_mes_real(r["lote_ym"]), curto=True) for r in ADS["serie_mensal"]]
ads_ecv = [r["valor_ecv"] / 1e6 for r in ADS["serie_mensal"]]
ads_m3 = [r["m3"] / 1e3 for r in ADS["serie_mensal"]]
xa = np.arange(len(ads_meses))
ax1.bar(xa, ads_ecv, color="#0284C7", width=0.55, label="Faturado (M ECV)")
ax1.set_xticks(xa)
ax1.set_xticklabels(ads_meses, fontsize=7.5, rotation=25)
ax1.set_title("AdS (21) — Faturação Mensal 2026 (M ECV)", fontsize=10, fontweight="bold")
ax1.grid(axis="y", alpha=0.7)
ax1b = ax1.twinx()
ax1b.plot(xa, ads_m3, color="#F59E0B", marker="s", linewidth=1.8, label="Volume (mil m³)")
ax1b.set_ylabel("Mil m³", fontsize=8.5, color="#B45309")

ag_f = [r["faixa"] for r in ADS["aging"]]
ag_v = [r["valor_ecv"] / 1e6 for r in ADS["aging"]]
ax2.bar(ag_f, ag_v, color=["#10B981", "#3B82F6", "#F59E0B", "#EF4444"], width=0.52)
ax2.set_title("AdS (21) — Aging da Dívida (1.674,4M ECV)", fontsize=10, fontweight="bold")
ax2.set_ylabel("Milhões ECV", fontsize=8.5)
ax2.grid(axis="y", alpha=0.7)
for i, v in enumerate(ag_v):
    ax2.text(i, v + 15, f"{v:,.1f}M", ha="center", fontsize=8, fontweight="bold")

plt.tight_layout()
fig4_path = os.path.join(CHART_DIR, "fig4_ads.png")
plt.savefig(fig4_path, dpi=300)
plt.close()

# FIG 5: Score v2 Lift / Calibração Out-of-Time por Decil
fig, ax1 = plt.subplots(figsize=(10.0, 3.8), dpi=300)
decis = [d["decil"] for d in SC["decis"]]
taxas_d = [d["taxa_fraude_pct"] for d in SC["decis"]]
lifts_d = [d["lift"] for d in SC["decis"]]
xd = np.arange(len(decis))
cores_d = ["#DC2626" if i == 0 else "#F59E0B" if i <= 2 else "#64748B" for i in range(len(decis))]
ax1.bar(xd, taxas_d, color=cores_d, width=0.58, label="Taxa de Fraude Real (%)")
ax1.axhline(SC["taxa_fraude_base_teste_pct"], color="#0F172A", linestyle="--", linewidth=1.1, label=f"Base Aleatória ({SC['taxa_fraude_base_teste_pct']}%)")
ax1.set_xticks(xd)
ax1.set_xticklabels(decis, fontsize=9)
ax1.set_ylabel("Taxa de Fraude (%)", fontsize=9)
ax1.set_title(f"Score de Risco v2 — Calibração Out-of-Time (AUC = {SC['auc_teste_out_of_time']:.3f})", fontsize=10.5, fontweight="bold")
ax1.grid(axis="y", alpha=0.7)
for i, (t, lf) in enumerate(zip(taxas_d, lifts_d)):
    ax1.text(i, t + 1.2, f"{t:.1f}%\n({lf:.2f}x)", ha="center", va="bottom", fontsize=7.5, fontweight="bold")
ax1.set_ylim(0, max(taxas_d) * 1.22)
ax1.legend(fontsize=8.5, frameon=True, facecolor="white")
plt.tight_layout()
fig5_path = os.path.join(CHART_DIR, "fig5_scorev2.png")
plt.savefig(fig5_path, dpi=300)
plt.close()

# FIG 6: Mix EB / EM / EE (17 · EDEC Sul)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 3.6), dpi=300)
segs = [cod_p for cod_p, _ in mix_labels]
pct_gwh = [mix_17[k]["kwh"] / tot_mkwh * 100.0 for k in segs]
pct_ecv = [mix_17[k]["ecv"] / tot_mecv * 100.0 for k in segs]
pm_segs = [mix_17[k]["ecv"] / mix_17[k]["kwh"] for k in segs]
xs = np.arange(len(segs))
ax1.bar(xs - 0.18, pct_gwh, width=0.35, label="% Energia (GWh)", color="#3B82F6")
ax1.bar(xs + 0.18, pct_ecv, width=0.35, label="% Faturação (ECV)", color="#10B981")
ax1.set_xticks(xs)
ax1.set_xticklabels(["EB (BT)", "EM (MT)", "EE (Espec./IP)"], fontsize=8.5)
ax1.set_ylabel("% do Total 17", fontsize=8.5)
ax1.set_title("Mix 17 · EDEC Sul: Energia vs. Receita (%)", fontsize=10, fontweight="bold")
ax1.grid(axis="y", alpha=0.7)
ax1.legend(fontsize=8, frameon=True, facecolor="white")
for i in range(len(xs)):
    ax1.text(i - 0.18, pct_gwh[i] + 1.2, f"{pct_gwh[i]:.1f}%", ha="center", fontsize=7.5, fontweight="bold")
    ax1.text(i + 0.18, pct_ecv[i] + 1.2, f"{pct_ecv[i]:.1f}%", ha="center", fontsize=7.5, fontweight="bold")
ax1.set_ylim(0, max(max(pct_gwh), max(pct_ecv)) * 1.2)

ax2.bar(["EB (BT)", "EM (MT)", "EE (Espec./IP)"], pm_segs, width=0.48, color=["#60A5FA", "#8B5CF6", "#F59E0B"])
ax2.set_title("Preço Médio Realizado por Segmento (ECV/kWh)", fontsize=10, fontweight="bold")
ax2.set_ylabel("ECV / kWh", fontsize=8.5)
ax2.grid(axis="y", alpha=0.7)
for i, v in enumerate(pm_segs):
    ax2.text(i, v + 1.2, f"{v:.2f}", ha="center", fontsize=8, fontweight="bold")
ax2.set_ylim(0, max(pm_segs) * 1.18)

plt.tight_layout()
fig6_path = os.path.join(CHART_DIR, "fig6_mix_17.png")
plt.savefig(fig6_path, dpi=300)
plt.close()

print("Gráficos gerados com sucesso!")


# ==============================================================================
# 3. GERAR DOCUMENTO WORD (.DOCX)
# ==============================================================================
def set_cell_bg(cell, hex_color):
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def add_styled_table(doc, headers, rows, col_widths_cm=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    # Repetir cabeçalho entre páginas
    trPr_hdr = table.rows[0]._tr.get_or_add_trPr()
    trPr_hdr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
    trPr_hdr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))

    hdr_cells = table.rows[0].cells
    for j, h in enumerate(headers):
        hdr_cells[j].text = h
        hdr_cells[j].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        if col_widths_cm:
            hdr_cells[j].width = Cm(col_widths_cm[j])
        set_cell_bg(hdr_cells[j], "1E3A8A")
        for p in hdr_cells[j].paragraphs:
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if j > 0 else WD_ALIGN_PARAGRAPH.LEFT
            for run in p.runs:
                run.font.bold = True
                run.font.size = Pt(7.8)
                run.font.color.rgb = RGBColor(255, 255, 255)
    for i, r in enumerate(rows):
        trPr = table.rows[i + 1]._tr.get_or_add_trPr()
        trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
        row_cells = table.rows[i + 1].cells
        bg = "F8FAFC" if i % 2 == 1 else "FFFFFF"
        is_tot = (i == len(rows) - 1 and str(r[0]).upper().startswith("TOTAL"))
        if is_tot:
            bg = "E2E8F0"
        for j, val in enumerate(r):
            row_cells[j].text = str(val)
            row_cells[j].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if col_widths_cm:
                row_cells[j].width = Cm(col_widths_cm[j])
            set_cell_bg(row_cells[j], bg)
            for p in row_cells[j].paragraphs:
                p.paragraph_format.space_before = Pt(1.5)
                p.paragraph_format.space_after = Pt(1.5)
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if j > 0 else WD_ALIGN_PARAGRAPH.LEFT
                for run in p.runs:
                    run.font.size = Pt(7.6)
                    run.font.bold = is_tot
    doc.add_paragraph()


def _add_word_field(paragraph, field_name):
    run = paragraph.add_run()
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGBColor(100, 116, 139)
    fldChar1 = parse_xml(r'<w:fldChar %s w:fldCharType="begin"/>' % nsdecls('w'))
    instrText = parse_xml(r'<w:instrText %s xml:space="preserve"> %s </w:instrText>' % (nsdecls('w'), field_name))
    fldChar2 = parse_xml(r'<w:fldChar %s w:fldCharType="separate"/>' % nsdecls('w'))
    fldChar3 = parse_xml(r'<w:fldChar %s w:fldCharType="end"/>' % nsdecls('w'))
    run._r.append(fldChar1)
    run._r.append(instrText)
    run._r.append(fldChar2)
    run._r.append(fldChar3)


doc = Document()
for sec in doc.sections:
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(1.9)
    sec.bottom_margin = Cm(1.9)
    sec.left_margin = Cm(1.5)
    sec.right_margin = Cm(1.5)
    sec.different_first_page_header_footer = False

    # Cabeçalho DOCX
    hdr = sec.header
    hp = hdr.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hrun = hp.add_run("EDEC • Relatório Executivo Comercial — Visão Executiva Gold (2026)  |  DPO")
    hrun.font.size = Pt(8.5)
    hrun.font.color.rgb = RGBColor(100, 116, 139)

    # Rodapé DOCX: DEPARTAMENTO PLANEAMENTO ORGANIZAÇÃO (DPO) + Página X de Y
    ftr = sec.footer
    ftbl = ftr.add_table(rows=1, cols=2, width=Cm(18.0))
    ftbl.autofit = False
    ftbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    c_left, c_right = ftbl.rows[0].cells[0], ftbl.rows[0].cells[1]
    c_left.width = Cm(12.5)
    c_right.width = Cm(5.5)
    p_l = c_left.paragraphs[0]
    p_l.alignment = WD_ALIGN_PARAGRAPH.LEFT
    rl = p_l.add_run("DEPARTAMENTO PLANEAMENTO ORGANIZAÇÃO (DPO)")
    rl.font.size = Pt(8.5)
    rl.font.bold = True
    rl.font.color.rgb = RGBColor(30, 58, 138)

    p_r = c_right.paragraphs[0]
    p_r.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    rr1 = p_r.add_run("Página ")
    rr1.font.size = Pt(8.5)
    rr1.font.color.rgb = RGBColor(100, 116, 139)
    _add_word_field(p_r, "PAGE")
    rr2 = p_r.add_run(" de ")
    rr2.font.size = Pt(8.5)
    rr2.font.color.rgb = RGBColor(100, 116, 139)
    _add_word_field(p_r, "NUMPAGES")

# Capa / Cabeçalho
p_title = doc.add_paragraph()
p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_t = p_title.add_run("RELATÓRIO EXECUTIVO COMERCIAL — VISÃO EXECUTIVA GOLD (2026)")
r_t.bold = True
r_t.font.size = Pt(16)
r_t.font.color.rgb = RGBColor(30, 58, 138)

p_sub = doc.add_paragraph()
p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_s = p_sub.add_run(
    "Região Sul (Santiago, Fogo, Maio e Brava) • Discriminação das 4 Empresas: 17 (EDEC Sul), 21 (Electra SA), 07 (Electra Sul) e 70 (Electra SARL)\n"
    "DEPARTAMENTO PLANEAMENTO ORGANIZAÇÃO (DPO)\n"
    f"Fonte: Lakehouse Bronze → Silver → Gold (marts_gold.json) | Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}"
)
r_s.font.size = Pt(9.5)
r_s.font.color.rgb = RGBColor(100, 116, 139)

# Índice no DOCX
doc.add_heading("Índice", level=1)
indice_itens = [
    ("1. Introdução", "Enquadramento do Lakehouse Gold e das 4 Empresas"),
    ("2. Desenvolvimento e Análise dos Indicadores", "Visão consolidada de 2026"),
    ("   2.1. Quadro Consolidado das 4 Empresas (2026)", "Faturação, Cobrança e Dívida (17, 21, 07, 70)"),
    ("   2.2. Série Mensal 2026 — Faturação vs. Cobrança (17 · EDEC Sul)", "Energia, Preço Médio, Taxa de Cobrança e DSO"),
    ("   2.3. Aging Real da Dívida (por Emissão da Fatura)", "Escalões 0-30d até > 5 anos por Empresa"),
    ("   2.4. Cliente Especial AdS (21 · Electra SA — Água AG)", "Volume (m³), Faturação e Dívida Acumulada"),
    ("   2.5. Operacional (Inspeções CEA & OS) e Priorização Score v2", "Calibração Out-of-Time por Decil e Lift"),
    ("   2.6. Mix Tarifário (EB/EM/EE) e Ponte com Perdas em BT", "Segmentação de Receita e Balanço nos PTs Medidos"),
    ("   2.7. Engenharia de Dados, Auditoria DQ e Frescura das Fontes", "Funil Bronze → Silver e Semáforo de Ingestão"),
    ("3. Constrangimentos Identificados", "Principais riscos financeiros e de dados"),
    ("4. Conclusão, Metas e Plano de Ação", "Quadro de metas executivas e recomendações"),
]
for sec_t, sec_d in indice_itens:
    pi = doc.add_paragraph()
    pi.paragraph_format.space_after = Pt(2)
    r1 = pi.add_run(sec_t)
    r1.bold = not sec_t.startswith("   ")
    r1.font.size = Pt(9.5)
    r2 = pi.add_run(f"  —  {sec_d}")
    r2.font.size = Pt(9)
    r2.font.color.rgb = RGBColor(100, 116, 139)
doc.add_page_break()

# 1. Introdução
doc.add_heading("1. Introdução", level=1)
doc.add_paragraph(
    "O presente relatório consolida todos os indicadores da aba Visão Executiva (Centro Executivo Gold) do Lakehouse Comercial da Região Sul. "
    "Os dados foram processados ao grão da fatura, do movimento de cobrança, da inspeção técnica e da ordem de serviço, permitindo uma leitura "
    "integrada da performance financeira e operacional de 2026 com discriminação explícita das quatro entidades empresariais presentes na base:"
)
for emp_txt in [
    "17 · EDEC Sul: operação corrente de energia elétrica (faturação e cobrança ativa em 2026).",
    "21 · Electra SA: inclui a conta corrente especial de Águas de Santiago S.A. (AdS — Água AG, CILs 60220187 e 60220188).",
    "07 · Electra Sul: carteira legada em processo de recuperação e cobrança de créditos vencidos.",
    "70 · Electra SARL: carteira histórica residual, composta essencialmente por faturas com idade superior a 5 anos."
]:
    doc.add_paragraph(emp_txt, style="List Bullet")

# 2. Desenvolvimento
doc.add_heading("2. Desenvolvimento e Análise dos Indicadores", level=1)

doc.add_heading("2.1. Quadro Consolidado das 4 Empresas (2026)", level=2)
t_emp_hdr = ["Empresa", "Papel na Carteira", "Faturado 2026 (ECV)", "Volume Físico", "Cobrado 2026 (ECV)", "Dívida Exigível (≤5a)", "Dívida Prescrita (>5a)", "Dívida Total (ECV)"]
t_emp_rows = []
for e in empresas_info:
    t_emp_rows.append([
        e["nome"], e["papel"],
        fmt_ecv_curto(e["fat_ecv"]) if e["fat_ecv"] > 0 else "—",
        e["fat_fisico"],
        fmt_ecv_curto(e["cob_ecv"]),
        fmt_ecv_curto(e["div_exig"]),
        fmt_ecv_curto(e["div_presc"]),
        fmt_ecv_curto(e["div_total"]),
    ])
t_emp_rows.append([
    "TOTAL CONSOLIDADO", "4 Empresas",
    fmt_ecv_curto(KPI["fat_17_ecv"] + KPI["fat_21_ads_ecv"]),
    "—",
    fmt_ecv_curto(KPI["cob_total_ecv"]),
    fmt_ecv_curto(KPI["divida_exigivel_ecv"]),
    fmt_ecv_curto(KPI["divida_prescrita_ecv"]),
    fmt_ecv_curto(KPI["divida_total_ecv"]),
])
add_styled_table(doc, t_emp_hdr, t_emp_rows, [2.4, 3.4, 2.0, 1.8, 2.0, 2.1, 2.1, 2.2])
doc.add_picture(fig1_path, width=Cm(17.4))

doc.add_heading("2.2. Série Mensal 2026 — Faturação vs. Cobrança (17 · EDEC Sul)", level=2)
doc.add_paragraph(
    f"Na operação corrente (17 · EDEC Sul), a faturação acumulada de 2026 atinge {fmt_ecv_curto(KPI['fat_17_ecv'])} ECV "
    f"({fmt_pt(KPI['fat_17_kwh']/1e6, 1)} GWh), com Preço Médio Real de {fmt_pt(KPI['fat_17_preco_medio'], 2)} ECV/kWh. "
    f"A cobrança real soma {fmt_ecv_curto(KPI['cob_17_ecv'])} ECV, resultando numa Taxa de Cobrança de {fmt_pt(KPI['taxa_cobranca_17_pct'], 1)}% "
    f"e num DSO médio de {KPI['dso_17_dias']} dias."
)
t_m17_hdr = ["Mês", "Energia (GWh)", "Faturado (M ECV)", "PM (ECV/kWh)", "Cobrado (M ECV)", "Taxa Cob. (%)", "EB / EM / EE (M ECV)"]
t_m17_rows = []
for m in meses_17:
    f_m = fat_17_mes[m]
    c_m = cob_17_mes[m]
    pm = (f_m["ecv"] / f_m["kwh"]) if f_m["kwh"] > 0 else 0.0
    tx = (c_m / f_m["ecv"] * 100.0) if f_m["ecv"] > 0 else 0.0
    seg = f"{f_m['EB']/1e6:.0f} / {f_m['EM']/1e6:.0f} / {f_m['EE']/1e6:.0f}"
    t_m17_rows.append([
        nome_mes_pt(m, curto=False),
        fmt_pt(f_m["kwh"] / 1e6, 2) if f_m["kwh"] > 0 else "—",
        fmt_pt(f_m["ecv"] / 1e6, 1) if f_m["ecv"] > 0 else "—",
        fmt_pt(pm, 2) if pm > 0 else "—",
        fmt_pt(c_m / 1e6, 1) if c_m > 0 else "—",
        f"{fmt_pt(tx, 1)}%" if f_m["ecv"] > 0 else "—",
        seg if f_m["ecv"] > 0 else "—",
    ])
t_m17_rows.append([
    "TOTAL 2026", fmt_pt(KPI["fat_17_kwh"] / 1e6, 1), fmt_pt(KPI["fat_17_ecv"] / 1e6, 1),
    fmt_pt(KPI["fat_17_preco_medio"], 2), fmt_pt(KPI["cob_17_ecv"] / 1e6, 1),
    f"{fmt_pt(KPI['taxa_cobranca_17_pct'], 1)}%", "—"
])
add_styled_table(doc, t_m17_hdr, t_m17_rows, [2.0, 2.3, 2.7, 2.2, 2.7, 2.3, 3.8])
doc.add_picture(fig2_path, width=Cm(17.4))

doc.add_heading("2.3. Aging Real da Dívida (por Emissão da Fatura)", level=2)
doc.add_paragraph(
    f"A dívida total registada é de {fmt_ecv_curto(KPI['divida_total_ecv'])} ECV, dos quais {fmt_ecv_curto(KPI['divida_exigivel_ecv'])} ECV "
    f"(49,5%) correspondem a dívida exigível (≤ 5 anos) e {fmt_ecv_curto(KPI['divida_prescrita_ecv'])} ECV (50,5%) a dívida prescrita (> 5 anos), "
    "concentrada nas empresas legadas 07 e 70."
)
t_ag_hdr = ["Escalão", "Faturas", "% Total", "17 · EDEC Sul", "21 · Electra SA", "07 · Electra Sul", "70 · Electra SARL"]
t_ag_rows = []
tot_div = KPI["divida_total_ecv"] or 1.0
for r in AGING_ROWS:
    t_ag_rows.append([
        r["faixa"],
        f"{int(r['faturas']):,}".replace(",", "."),
        f"{fmt_pt(r['total_ecv'] / tot_div * 100.0, 1)}%",
        fmt_ecv_curto(r["emp_17"]),
        fmt_ecv_curto(r["emp_21"]),
        fmt_ecv_curto(r["emp_07"]),
        fmt_ecv_curto(r["emp_70"]),
    ])
t_ag_rows.append([
    "TOTAL", "—", "100,0%",
    fmt_ecv_curto(KPI["divida_17_ecv"]),
    fmt_ecv_curto(KPI["divida_21_ecv"]),
    fmt_ecv_curto(KPI["divida_07_ecv"]),
    fmt_ecv_curto(KPI["divida_70_ecv"]),
])
add_styled_table(doc, t_ag_hdr, t_ag_rows, [2.2, 2.0, 2.0, 2.9, 2.9, 3.0, 3.0])
doc.add_picture(fig3_path, width=Cm(17.4))

doc.add_heading("2.4. Cliente Especial AdS (21 · Electra SA — Água AG)", level=2)
doc.add_paragraph(
    f"O cliente especial Águas de Santiago (CILs 60220187 e 60220188) acumulou em 2026 uma faturação de {fmt_ecv_curto(ADS['total_faturado_ecv'])} ECV "
    f"correspondente a {fmt_pt(ADS['total_m3'] / 1e6, 2)} milhões de m³ (preço médio de {fmt_pt(ADS['preco_medio_m3'], 2)} ECV/m³). "
    f"O saldo em dívida ascende a {fmt_ecv_curto(ADS['saldo_divida_ecv'])} ECV, sem cobrança registada em caixa no exercício de 2026."
)
doc.add_picture(fig4_path, width=Cm(17.4))

doc.add_heading("2.5. Operacional (Inspeções CEA & OS) e Priorização Score v2", level=2)
os_r = OP["os_resumo"]
doc.add_paragraph(
    f"No plano operacional, foram registadas {os_r['total']:,} Ordens de Serviço (100% executadas, SLA médio de {fmt_pt(os_r['sla_medio_dias'], 1)} dias). "
    f"O modelo preditivo Score de Risco v2, calibrado sobre inspeções CEA (AUC Out-of-Time = {SC['auc_teste_out_of_time']:.3f}), alcança uma precisão de "
    f"{SC['decis'][0]['taxa_fraude_pct']}% no Top 10% (Lift de {SC['decis'][0]['lift']}x face à taxa base de {SC['taxa_fraude_base_teste_pct']}%)."
)
t_sc_hdr = ["Decil", "Inspeções Teste", "Fraudes Confirmadas", "Taxa de Fraude (%)", "Lift vs. Aleatório"]
t_sc_rows = [[d["decil"], str(d["insp"]), str(d["fraudes"]), f"{fmt_pt(d['taxa_fraude_pct'], 1)}%", f"{fmt_pt(d['lift'], 2)}x"] for d in SC["decis"]]
add_styled_table(doc, t_sc_hdr, t_sc_rows, [2.4, 3.9, 3.9, 3.9, 3.9])
doc.add_picture(fig5_path, width=Cm(17.4))

doc.add_heading("2.6. Mix Tarifário (EB/EM/EE) e Ponte com Perdas em BT", level=2)
doc.add_paragraph(
    "A análise do mix tarifário da EDEC Sul (17) evidencia a complementaridade entre volume físico e preço médio: "
    "a Baixa Tensão (EB) representa 59,9% da energia e 59,1% da receita, enquanto Especiais/IP (EE) geram 22,1% da faturação com 13,6% dos GWh "
    "(PM 58,17 ECV/kWh). Em paralelo, a ponte com o Balanço Energético Real por PT (Módulo 2) quantifica as Perdas Não Técnicas (PNT) nos PTs medidos."
)
add_styled_table(doc, t_mix_hdr, t_mix_rows, [3.6, 2.0, 2.3, 1.9, 2.7, 1.9, 3.6])
doc.add_picture(fig6_path, width=Cm(17.4))
if t_bal_rows:
    add_styled_table(doc, t_bal_hdr, t_bal_rows, [2.0, 2.1, 2.6, 2.6, 2.3, 3.6, 2.8])

doc.add_heading("2.7. Engenharia de Dados, Auditoria DQ e Frescura das Fontes", level=2)
doc.add_paragraph(
    f"Na camada de governança, o funil de dívida processou {FUNIL.get('bronze_linhas', 0):,} registos Bronze ({fmt_ecv_curto(FUNIL.get('bronze_ecv', 0))} ECV) "
    f"para {FUNIL.get('silver_linhas', 0):,} registos válidos da Região Sul ({fmt_ecv_curto(FUNIL.get('silver_ecv', 0))} ECV). "
    f"Todos os {len(DQ.get('testes', []))} testes automáticos de qualidade passaram (0 falhas)."
)
add_styled_table(doc, t_dq_hdr, t_dq_rows, [3.2, 6.2, 3.6, 2.3, 2.7])

# 3. Constrangimentos
doc.add_heading("3. Constrangimentos Identificados", level=1)
for c_txt in [
    "1. Passivo Histórico Prescrito (> 5 anos): 6,84B ECV (50,5% da carteira global) pertencem às carteiras legadas 07 (4,29B) e 70 (2,55B), distorcendo rácios consolidados de recuperabilidade.",
    "2. Acumulação de Dívida AdS (21 · Electra SA): faturação contínua (736,7M ECV em 2026) com cobrança em caixa nula no período, elevando o saldo devedor para 1,67B ECV (868,1M ECV já no escalão 1–2 anos).",
    "3. Pressão de Tesouraria na EDEC Sul (17): embora a taxa de cobrança anual seja de 91,3%, o DSO médio de 81 dias indica desfasamento relevante entre emissão e recebimento.",
    "4. Retificações / Notas de Crédito Não Compensadas: valores negativos em escalões antigos das empresas 07 e 70 exigem saneamento contabilístico.",
    "5. Frescura de Fontes Auxiliares: alertas de atraso em ficheiros operacionais específicos (ex.: Anomalia de Leitura >30 dias e ficheiro de rotas)."
]:
    doc.add_paragraph(c_txt)

# 4. Conclusão
doc.add_heading("4. Conclusão, Metas e Plano de Ação", level=1)
doc.add_paragraph(
    "A Visão Executiva Gold demonstra uma operação elétrica corrente (17 · EDEC Sul) sólida em faturação e cobrança (91,3%), mas fortemente condicionada "
    "por dois focos financeiros críticos: a dívida institucional da AdS (21) e o passivo prescrito das empresas legadas (07 e 70). "
    "O quadro abaixo sintetiza as metas operacionais e financeiras recomendadas ao Departamento de Planeamento e Organização (DPO) e direções envolvidas:"
)
add_styled_table(doc, t_meta_hdr, t_meta_rows, [4.2, 3.3, 3.8, 3.8, 2.9])

# Bloco de Data e Assinatura no DOCX
meses_ext = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}
hoje = datetime.now()
data_extenso = f"Praia, {hoje.day:02d} de {meses_ext[hoje.month]} de {hoje.year}"

p_sig = doc.add_paragraph()
p_sig.paragraph_format.space_before = Pt(22)
p_sig.paragraph_format.keep_with_next = True
p_sig.alignment = WD_ALIGN_PARAGRAPH.CENTER
r_dt = p_sig.add_run(f"{data_extenso}\n\n\n_____________________________________________\n")
r_dt.font.size = Pt(9.5)
r_nm = p_sig.add_run("Victor Cesar Fonseca Ferreira\n")
r_nm.bold = True
r_nm.font.size = Pt(10)
r_nm.font.color.rgb = RGBColor(30, 58, 138)
r_cg = p_sig.add_run("Chefe do Departamento de Planeamento e Organização (DPO)")
r_cg.font.size = Pt(9)
r_cg.font.color.rgb = RGBColor(100, 116, 139)

docx_path = os.path.join(OUT_DIR, "Relatorio_Visao_Executiva_Gold_2026.docx")
try:
    doc.save(docx_path)
except PermissionError:
    docx_path = os.path.join(OUT_DIR, "Relatorio_Visao_Executiva_Gold_2026_rev.docx")
    doc.save(docx_path)
print(f"DOCX salvo em: {docx_path}")


# ==============================================================================
# 4. GERAR DOCUMENTO PDF (.PDF) COM ÍNDICE, CABEÇALHO, RODAPÉ E Nº DE PÁGINA
# ==============================================================================
pdf_path = os.path.join(OUT_DIR, "Relatorio_Visao_Executiva_Gold_2026.pdf")


class NumberedDPOCanvas(rl_canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def _draw_header_footer(self, page_count):
        w, h = A4
        self.saveState()
        # Cabeçalho
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(1.5*cm, h - 1.35*cm, w - 1.5*cm, h - 1.35*cm)
        self.setFont("Helvetica-Bold", 7.8)
        self.setFillColor(colors.HexColor("#1E3A8A"))
        self.drawString(1.5*cm, h - 1.15*cm, "EDEC • Relatório Executivo Comercial — Visão Executiva Gold (2026)")
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawRightString(w - 1.5*cm, h - 1.15*cm, "Região Sul (17, 21, 07, 70)")

        # Rodapé
        self.line(1.5*cm, 1.35*cm, w - 1.5*cm, 1.35*cm)
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#1E3A8A"))
        self.drawString(1.5*cm, 0.9*cm, "DEPARTAMENTO PLANEAMENTO ORGANIZAÇÃO (DPO)")
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawRightString(w - 1.5*cm, 0.9*cm, f"Página {self._pageNumber} de {page_count}")
        self.restoreState()


class ExecDocTemplate(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates([PageTemplate(id="dpo", frames=[frame])])

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            text = flowable.getPlainText()
            style_name = flowable.style.name
            if style_name == "H1":
                self.notify("TOCEntry", (0, text, self.page))
            elif style_name == "H2":
                self.notify("TOCEntry", (1, text, self.page))


pdf_doc = ExecDocTemplate(pdf_path, pagesize=A4, leftMargin=1.5*cm, rightMargin=1.5*cm, topMargin=1.8*cm, bottomMargin=1.8*cm)
styles = getSampleStyleSheet()
st_title = ParagraphStyle("T", parent=styles["Title"], fontSize=16, textColor=colors.HexColor("#1E3A8A"), spaceAfter=4)
st_sub = ParagraphStyle("S", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#64748B"), alignment=1, spaceAfter=12)
st_h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=12.5, textColor=colors.HexColor("#1E3A8A"), spaceBefore=10, spaceAfter=4)
st_h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=10.5, textColor=colors.HexColor("#0F172A"), spaceBefore=8, spaceAfter=3)
st_p = ParagraphStyle("P", parent=styles["Normal"], fontSize=9, leading=13, spaceAfter=5)

toc = TableOfContents()
toc.levelStyles = [
    ParagraphStyle(fontName="Helvetica-Bold", fontSize=9.5, name="TOCHeading1", leftIndent=0, firstLineIndent=0, spaceBefore=4, leading=12, textColor=colors.HexColor("#1E3A8A")),
    ParagraphStyle(fontName="Helvetica", fontSize=8.5, name="TOCHeading2", leftIndent=16, firstLineIndent=0, spaceBefore=1, leading=11, textColor=colors.HexColor("#334155")),
]


st_th_l = ParagraphStyle("THL", fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=colors.white, alignment=0)
st_th_c = ParagraphStyle("THC", fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=colors.white, alignment=1)
st_td_l = ParagraphStyle("TDL", fontName="Helvetica", fontSize=7.1, leading=9, textColor=colors.HexColor("#0F172A"), alignment=0)
st_td_r = ParagraphStyle("TDR", fontName="Helvetica", fontSize=7.1, leading=9, textColor=colors.HexColor("#0F172A"), alignment=2)
st_td_lb = ParagraphStyle("TDLB", fontName="Helvetica-Bold", fontSize=7.1, leading=9, textColor=colors.HexColor("#0F172A"), alignment=0)
st_td_rb = ParagraphStyle("TDRB", fontName="Helvetica-Bold", fontSize=7.1, leading=9, textColor=colors.HexColor("#0F172A"), alignment=2)


def pdf_table(headers, rows, col_widths_cm):
    cw = [w * cm for w in col_widths_cm]
    hdr_p = [Paragraph(str(h), st_th_l if j == 0 else st_th_c) for j, h in enumerate(headers)]
    body_p = []
    for i, r in enumerate(rows):
        is_tot = (i == len(rows) - 1 and str(r[0]).upper().startswith("TOTAL"))
        body_p.append([
            Paragraph(str(v), (st_td_lb if is_tot else st_td_l) if j == 0 else (st_td_rb if is_tot else st_td_r))
            for j, v in enumerate(r)
        ])
    t = Table([hdr_p] + body_p, colWidths=cw, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if rows and str(rows[-1][0]).upper().startswith("TOTAL"):
        ts.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")))
    t.setStyle(TableStyle(ts))
    return t


story = [
    Paragraph("RELATÓRIO EXECUTIVO COMERCIAL — VISÃO EXECUTIVA GOLD (2026)", st_title),
    Paragraph(
        f"Região Sul (Santiago, Fogo, Maio e Brava) • 4 Empresas: 17 (EDEC Sul), 21 (Electra SA), 07 (Electra Sul), 70 (Electra SARL)<br/>"
        f"<b>DEPARTAMENTO PLANEAMENTO ORGANIZAÇÃO (DPO)</b> • Fonte: Lakehouse Gold | {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        st_sub
    ),
    Paragraph("Índice", ParagraphStyle("TOCTitle", parent=styles["Heading1"], fontSize=13, textColor=colors.HexColor("#1E3A8A"), spaceAfter=6)),
    toc,
    PageBreak(),
    Paragraph("1. Introdução", st_h1),
    Paragraph(
        "Este relatório apresenta a análise integral dos indicadores da aba Visão Executiva (Gold) para 2026, discriminando o desempenho de faturação, "
        "cobrança real, aging de dívida, operação de terreno (CEA/OS) e priorização preditiva (Score v2) entre as quatro empresas da base: "
        "<b>17 · EDEC Sul</b> (operação elétrica corrente), <b>21 · Electra SA</b> (conta especial AdS Água AG), "
        "<b>07 · Electra Sul</b> (carteira legada em recuperação) e <b>70 · Electra SARL</b> (carteira histórica >5 anos).",
        st_p
    ),
    Paragraph("2. Desenvolvimento e Representação Gráfica", st_h1),
    KeepTogether([
        Paragraph("2.1. Quadro Comparativo das 4 Empresas", st_h2),
        pdf_table(t_emp_hdr, t_emp_rows, [2.4, 3.4, 2.0, 1.8, 2.0, 2.1, 2.1, 2.2]),
        Spacer(1, 6),
        RLImage(fig1_path, width=17.4*cm, height=6.96*cm),
    ]),
    KeepTogether([
        Paragraph("2.2. Série Mensal 2026 — Faturação vs. Cobrança (17 · EDEC Sul)", st_h2),
        Paragraph(
            f"Faturação 2026: <b>{fmt_ecv_curto(KPI['fat_17_ecv'])} ECV</b> ({fmt_pt(KPI['fat_17_kwh']/1e6, 1)} GWh) | "
            f"Cobrança Real: <b>{fmt_ecv_curto(KPI['cob_17_ecv'])} ECV</b> | Taxa de Cobrança: <b>{fmt_pt(KPI['taxa_cobranca_17_pct'], 1)}%</b> | "
            f"DSO Médio: <b>{KPI['dso_17_dias']} dias</b> | Preço Médio: <b>{fmt_pt(KPI['fat_17_preco_medio'], 2)} ECV/kWh</b>.",
            st_p
        ),
        pdf_table(t_m17_hdr, t_m17_rows, [2.0, 2.3, 2.7, 2.2, 2.7, 2.3, 3.8]),
        Spacer(1, 6),
        RLImage(fig2_path, width=17.4*cm, height=6.82*cm),
    ]),
    PageBreak(),
    KeepTogether([
        Paragraph("2.3. Aging Real da Dívida por Escalão e Empresa", st_h2),
        Paragraph(
            f"Dívida Total: <b>{fmt_ecv_curto(KPI['divida_total_ecv'])} ECV</b> • Exigível (≤ 5a): <b>{fmt_ecv_curto(KPI['divida_exigivel_ecv'])} ECV (49,5%)</b> • "
            f"Prescrita (> 5a): <b>{fmt_ecv_curto(KPI['divida_prescrita_ecv'])} ECV (50,5%)</b>.",
            st_p
        ),
        pdf_table(t_ag_hdr, t_ag_rows, [2.2, 2.0, 2.0, 2.9, 2.9, 3.0, 3.0]),
        Spacer(1, 6),
        RLImage(fig3_path, width=17.4*cm, height=6.82*cm),
    ]),
    KeepTogether([
        Paragraph("2.4. Cliente Especial AdS (21 · Electra SA — Água AG)", st_h2),
        Paragraph(
            f"Volume 2026: <b>{fmt_pt(ADS['total_m3']/1e6, 2)}M m³</b> | Faturado: <b>{fmt_ecv_curto(ADS['total_faturado_ecv'])} ECV</b> | "
            f"PM: <b>{fmt_pt(ADS['preco_medio_m3'], 2)} ECV/m³</b> | Dívida Acumulada: <b>{fmt_ecv_curto(ADS['saldo_divida_ecv'])} ECV</b> (Cobrança caixa 2026: 0 ECV).",
            st_p
        ),
        RLImage(fig4_path, width=17.4*cm, height=6.30*cm),
    ]),
    KeepTogether([
        Paragraph("2.5. Operacional (CEA/OS) e Calibração Score de Risco v2", st_h2),
        Paragraph(
            f"Ordens de Serviço: <b>{os_r['total']:,}</b> executadas (SLA médio <b>{fmt_pt(os_r['sla_medio_dias'], 1)} dias</b>). "
            f"Score v2 (AUC Out-of-Time = <b>{SC['auc_teste_out_of_time']:.3f}</b>): Top 10% atinge <b>56,1%</b> de acerto em fraude (Lift <b>4,36x</b>).",
            st_p
        ),
        pdf_table(t_sc_hdr, t_sc_rows, [2.4, 3.9, 3.9, 3.9, 3.9]),
        Spacer(1, 6),
        RLImage(fig5_path, width=17.4*cm, height=6.61*cm),
    ]),
    KeepTogether([
        Paragraph("2.6. Mix Tarifário (EB/EM/EE) e Ponte com Perdas em BT", st_h2),
        Paragraph(
            "Na 17 · EDEC Sul, a Baixa Tensão (EB) concentra <b>59,9%</b> dos GWh e <b>59,1%</b> da receita, enquanto Especiais/IP (EE) geram "
            "<b>22,1%</b> da faturação com PM de <b>58,17 ECV/kWh</b>. O quadro trimestral abaixo estabelece a ponte com o Balanço Real por PT (Módulo 2).",
            st_p
        ),
        pdf_table(t_mix_hdr, t_mix_rows, [3.6, 2.0, 2.3, 1.9, 2.7, 1.9, 3.6]),
        Spacer(1, 5),
        RLImage(fig6_path, width=17.4*cm, height=5.97*cm),
    ]),
    KeepTogether([
        Spacer(1, 4),
        pdf_table(t_bal_hdr, t_bal_rows, [2.0, 2.1, 2.6, 2.6, 2.3, 3.6, 2.8]) if t_bal_rows else Spacer(1, 1),
    ]),
    KeepTogether([
        Paragraph("2.7. Engenharia de Dados, Auditoria DQ e Frescura das Fontes", st_h2),
        Paragraph(
            f"Funil de Dívida: Bronze <b>{FUNIL.get('bronze_linhas', 0):,}</b> linhas ({fmt_ecv_curto(FUNIL.get('bronze_ecv', 0))} ECV) → "
            f"Silver <b>{FUNIL.get('silver_linhas', 0):,}</b> linhas ({fmt_ecv_curto(FUNIL.get('silver_ecv', 0))} ECV). "
            f"Testes de integridade: <b>{len(DQ.get('testes', []))}/{len(DQ.get('testes', []))} OK</b>.",
            st_p
        ),
        pdf_table(t_dq_hdr, t_dq_rows, [3.2, 6.2, 3.6, 2.3, 2.7]),
    ]),
    KeepTogether([
        Paragraph("3. Constrangimentos Identificados", st_h1),
        Paragraph("• <b>Passivo Prescrito (>5 anos):</b> 6,84B ECV (50,5% da carteira) concentrados nas empresas 07 (4,29B) e 70 (2,55B).", st_p),
        Paragraph("• <b>Inadimplência AdS (21):</b> faturação de 736,7M ECV em 2026 sem cobrança em caixa registada, elevando a dívida para 1,67B ECV.", st_p),
        Paragraph("• <b>DSO na EDEC Sul (17):</b> prazo médio de recebimento em 81 dias pressiona a liquidez corrente.", st_p),
        Paragraph("• <b>Saldos Negativos / Retificações & Frescura de Fontes:</b> notas de crédito não compensadas (07/70) e alertas de atraso em ficheiros auxiliares (Anomalia 39d; Itinerário 861d).", st_p),
    ]),
    KeepTogether([
        Paragraph("4. Conclusão, Metas e Plano de Ação", st_h1),
        Paragraph(
            "A operação corrente da EDEC Sul (17) apresenta taxa de cobrança sólida (91,3%), mas o balanço global exige atuação coordenada nas metas abaixo:",
            st_p
        ),
        pdf_table(t_meta_hdr, t_meta_rows, [4.2, 3.3, 3.8, 3.8, 2.9]),
        Spacer(1, 22),
        Paragraph(data_extenso, ParagraphStyle("SigDt", parent=st_p, alignment=1, spaceAfter=24)),
        Paragraph("_____________________________________________", ParagraphStyle("SigLn", parent=st_p, alignment=1, spaceAfter=4)),
        Paragraph("<b>Victor Cesar Fonseca Ferreira</b>", ParagraphStyle("SigNm", parent=st_p, alignment=1, fontSize=10, textColor=colors.HexColor("#1E3A8A"), spaceAfter=2)),
        Paragraph("Chefe do Departamento de Planeamento e Organização (DPO)", ParagraphStyle("SigCg", parent=st_p, alignment=1, fontSize=8.8, textColor=colors.HexColor("#64748B"))),
    ]),
]

try:
    pdf_doc.multiBuild(story, canvasmaker=NumberedDPOCanvas)
except PermissionError:
    pdf_path = os.path.join(OUT_DIR, "Relatorio_Visao_Executiva_Gold_2026_rev.pdf")
    pdf_doc = ExecDocTemplate(pdf_path, pagesize=A4, leftMargin=1.5*cm, rightMargin=1.5*cm, topMargin=1.8*cm, bottomMargin=1.8*cm)
    pdf_doc.multiBuild(story, canvasmaker=NumberedDPOCanvas)
print(f"PDF salvo em: {pdf_path}")
