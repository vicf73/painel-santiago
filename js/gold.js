// =========================================================================
// MÓDULO 0: VISÃO EXECUTIVA & MARTS GOLD (LAKEHOUSE SANTIAGO)
// Consome public.santiago_marts_gold via PostgREST autenticado (JWT/RLS)
// =========================================================================

let goldCarregado = false;

const fmtM = (v) => {
  const n = Number(v || 0);
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2).replace(".", ",") + " B";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " M";
  return Math.round(n).toLocaleString("pt-PT");
};

async function carregarMartsGold(forcar = false) {
  if (goldCarregado && !forcar) return;
  const statusEl = document.getElementById("gold-sync-status");
  if (statusEl) statusEl.textContent = "A carregar Marts Gold...";

  try {
    const resp = await fetch(
      `${SUPABASE_URL}/rest/v1/santiago_marts_gold?select=chave,dados,atualizado_em`,
      { headers: HEADERS }
    );
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const rows = await resp.json();
    const mapa = {};
    let ultimaData = null;
    for (const r of rows) {
      mapa[r.chave] = r.dados;
      if (r.atualizado_em && (!ultimaData || r.atualizado_em > ultimaData)) {
        ultimaData = r.atualizado_em;
      }
    }

    if (!mapa.kpis_executivos) {
      if (statusEl) statusEl.textContent = "Marts Gold ainda não sincronizados.";
      return;
    }

    renderizarKpisGold(mapa.kpis_executivos, mapa.prepago_analise || {});
    renderizarSerieFatCobGold(mapa.faturacao_mensal?.rows || [], mapa.cobranca_mensal?.rows || []);
    renderizarAgingGold(mapa.aging_divida?.rows || []);
    renderizarAdSGold(mapa.ads_conta_corrente || {});
    renderizarOperacionalDQGold(mapa.operacional_cea_os || {});
    renderizarScoreV2Gold(mapa.score_v2_validacao || {});
    renderizarPrepagoGold(mapa.prepago_analise || {}, mapa.kpis_executivos || {});

    if (statusEl && ultimaData) {
      const dt = new Date(ultimaData);
      statusEl.textContent = `Atualizado: ${dt.toLocaleDateString("pt-PT")} ${dt.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}`;
    }
    goldCarregado = true;
  } catch (err) {
    console.error("Erro Marts Gold:", err);
    if (statusEl) statusEl.textContent = "Erro ao carregar Marts Gold";
  }
}

function renderizarKpisGold(k, prep = {}) {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  const pr = prep.resumo || {};
  const prepEcv = Number(pr.total_m_ecv || 0) * 1e6;
  const tot17Cons = Number(k.fat_17_ecv || 0) + prepEcv;
  set("g-kpi-fat17", `${fmtM(k.fat_17_ecv)} ECV`);
  set("g-kpi-fat17-sub", `${(Number(k.fat_17_kwh || 0) / 1e6).toFixed(1)} GWh • c/ Pré-Pago: ${fmtM(tot17Cons)}`);

  set("g-kpi-cob-tot", `${fmtM(k.cob_total_ecv)} ECV`);
  set("g-kpi-cob-tot-sub", `17: ${fmtM(k.cob_17_ecv)} • 07: ${fmtM(k.cob_07_ecv)} • 70: ${fmtM(k.cob_70_ecv)}`);

  set("g-kpi-taxa-cob", `${k.taxa_cobranca_17_pct ?? 0}%`);
  set("g-kpi-taxa-cob-sub", `EDEC Sul (17): ${fmtM(k.cob_17_ecv)} / ${fmtM(k.fat_17_ecv)} ECV`);

  set("g-kpi-dso", `${k.dso_17_dias ?? 0} dias`);
  set("g-kpi-dso-sub", `Dívida 17 (${fmtM(k.divida_17_ecv)}) / Fat. 90d (${fmtM(k.fat_17_90d_ecv)})`);

  set("g-kpi-div-exig", `${fmtM(k.divida_exigivel_ecv)} ECV`);
  set("g-kpi-div-exig-sub", `Total: ${fmtM(k.divida_total_ecv)} • Prescrita >5a: ${fmtM(k.divida_prescrita_ecv)}`);

  set("g-kpi-ads", `${fmtM(k.fat_21_ads_ecv)} ECV`);
  set("g-kpi-ads-sub", `${(Number(k.fat_21_ads_m3 || 0) / 1e6).toFixed(2)}M m³ • Dívida AdS: ${fmtM(k.divida_21_ecv)}`);

  set("g-kpi-prepago", `${Number(pr.total_m_ecv || 0).toFixed(1)} M ECV`);
  set("g-kpi-prepago-sub", `${(Number(pr.total_mwh || 0) / 1000).toFixed(2)} GWh • ${Number(pr.sem_compra_60d || 0).toLocaleString("pt-PT")} >60d s/ compra`);
}

function renderizarSerieFatCobGold(fatRows, cobRows) {
  const tbody = document.getElementById("g-tbody-fat-cob");
  const tfoot = document.getElementById("g-tfoot-fat-cob");
  if (!tbody) return;

  const porLote = {};
  for (const r of fatRows) {
    if (r.emp !== "17") continue;
    const ym = r.lote_ym;
    if (!porLote[ym]) porLote[ym] = { fat_ecv: 0, fat_kwh: 0, eb: 0, ee: 0, em: 0 };
    porLote[ym].fat_ecv += Number(r.valor_ecv || 0);
    porLote[ym].fat_kwh += Number(r.consumo_qtd || 0);
    if (r.produto === "EB") porLote[ym].eb += Number(r.valor_ecv || 0);
    if (r.produto === "EE") porLote[ym].ee += Number(r.valor_ecv || 0);
    if (r.produto === "EM") porLote[ym].em += Number(r.valor_ecv || 0);
  }

  const cobPorMes = {};
  for (const r of cobRows) {
    if (r.emp !== "17") continue;
    cobPorMes[r.ano_mes] = (cobPorMes[r.ano_mes] || 0) + Number(r.valor_ecv || 0);
  }

  const lotes = Object.keys(porLote).sort();
  if (!lotes.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:16px; color:var(--text-muted);">Sem dados mensais.</td></tr>`;
    if (tfoot) tfoot.innerHTML = "";
    return;
  }

  const nomesMes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  const loteParaMesCob = (lote) => {
    const ano = Number(lote.slice(0, 4));
    const mes = Number(lote.slice(4, 6));
    const d = new Date(ano, mes - 2, 1);
    return {
      key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
      label: `${nomesMes[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`
    };
  };

  let totKwh = 0, totFat = 0, totCob = 0, totEb = 0, totEm = 0, totEe = 0;

  tbody.innerHTML = lotes.map(lote => {
    const f = porLote[lote];
    const mInfo = loteParaMesCob(lote);
    const cob = cobPorMes[mInfo.key] || 0;
    const taxaNum = f.fat_ecv > 0 ? (cob / f.fat_ecv) * 100 : 0;
    const taxa = taxaNum.toFixed(1).replace(".", ",");
    const pm = f.fat_kwh > 0 ? (f.fat_ecv / f.fat_kwh).toFixed(2).replace(".", ",") : "0,00";
    const corTaxa = taxaNum >= 90 ? "#34D399" : taxaNum >= 75 ? "#FBBF24" : "#F87171";

    totKwh += f.fat_kwh;
    totFat += f.fat_ecv;
    totCob += cob;
    totEb += f.eb;
    totEm += f.em;
    totEe += f.ee;

    return `
      <tr>
        <td style="font-family:var(--font-mono); font-weight:700; white-space:nowrap;">${mInfo.label}</td>
        <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap;">${(f.fat_kwh / 1e6).toFixed(2).replace(".", ",")}</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700; white-space:nowrap;">${fmtM(f.fat_ecv)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:var(--text-secondary); white-space:nowrap;">${pm}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA; font-weight:700; white-space:nowrap;">${fmtM(cob)}</td>
        <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap; min-width:74px;">
          <div style="font-weight:800; color:${corTaxa};">${taxa}%</div>
          <div style="height:3px; background:rgba(148,163,184,0.18); border-radius:2px; margin-top:2px; overflow:hidden;">
            <div style="width:${Math.min(100, Math.max(0, taxaNum)).toFixed(0)}%; height:100%; background:${corTaxa};"></div>
          </div>
        </td>
        <td style="text-align:right; font-family:var(--font-mono); font-size:10px; color:var(--text-secondary); white-space:nowrap;" title="EB: ${fmtM(f.eb)} | EM: ${fmtM(f.em)} | EE: ${fmtM(f.ee)}">
          ${Math.round(f.eb / 1e6)}M / ${Math.round(f.em / 1e6)}M / ${Math.round(f.ee / 1e6)}M
        </td>
      </tr>
    `;
  }).join("");

  if (tfoot) {
    const taxaTot = totFat > 0 ? ((totCob / totFat) * 100).toFixed(1).replace(".", ",") : "0,0";
    const pmTot = totKwh > 0 ? (totFat / totKwh).toFixed(2).replace(".", ",") : "0,00";
    const corTot = (totFat > 0 && (totCob / totFat) * 100 >= 90) ? "#34D399" : "#FBBF24";
    tfoot.innerHTML = `
      <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
        <td style="white-space:nowrap;">TOTAL 2026</td>
        <td style="text-align:right; white-space:nowrap;">${(totKwh / 1e6).toFixed(2).replace(".", ",")}</td>
        <td style="text-align:right; white-space:nowrap;">${fmtM(totFat)}</td>
        <td style="text-align:right; color:var(--text-secondary); white-space:nowrap;">${pmTot}</td>
        <td style="text-align:right; color:#60A5FA; white-space:nowrap;">${fmtM(totCob)}</td>
        <td style="text-align:right; color:${corTot}; white-space:nowrap;">${taxaTot}%</td>
        <td style="text-align:right; font-size:10px; color:var(--text-secondary); white-space:nowrap;">${Math.round(totEb / 1e6)}M / ${Math.round(totEm / 1e6)}M / ${Math.round(totEe / 1e6)}M</td>
      </tr>
    `;
  }
}

function renderizarAgingGold(rows) {
  const tbody = document.getElementById("g-tbody-aging");
  const tfoot = document.getElementById("g-tfoot-aging");
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:16px; color:var(--text-muted);">Sem dados de aging.</td></tr>`;
    if (tfoot) tfoot.innerHTML = "";
    return;
  }

  const fmtCompacto = (val) => {
    const n = Number(val || 0);
    if (Math.abs(n) < 0.5) return `<span style="color:var(--text-muted); opacity:0.45;">—</span>`;
    const abs = Math.abs(n);
    const sinal = n < 0 ? "−" : "";
    let txt = "";
    if (abs >= 1e9) txt = `${sinal}${(abs / 1e9).toFixed(2).replace(".", ",")} B`;
    else if (abs >= 1e6) txt = `${sinal}${(abs / 1e6).toFixed(1).replace(".", ",")} M`;
    else if (abs >= 1e3) txt = `${sinal}${(abs / 1e3).toFixed(1).replace(".", ",")} k`;
    else txt = `${sinal}${Math.round(abs).toLocaleString("pt-PT")}`;

    if (n < 0) {
      return `<span style="color:#94A3B8; font-style:italic;" title="Créditos / retificações não compensadas (${Math.round(n).toLocaleString('pt-PT')} ECV)">${txt}</span>`;
    }
    return txt;
  };

  const corZona = (faixa) => {
    if (["0-30d", "31-90d", "91-180d", "181-365d"].includes(faixa)) return "#34D399";
    if (["1-2 anos", "2-5 anos"].includes(faixa)) return "#FBBF24";
    return "#F87171";
  };

  const totGeral = rows.reduce((s, r) => s + Number(r.total_ecv || 0), 0);
  const totFat = rows.reduce((s, r) => s + Number(r.faturas || 0), 0);
  const tot17 = rows.reduce((s, r) => s + Number(r.emp_17 || 0), 0);
  const tot21 = rows.reduce((s, r) => s + Number(r.emp_21 || 0), 0);
  const tot07 = rows.reduce((s, r) => s + Number(r.emp_07 || 0), 0);
  const tot70 = rows.reduce((s, r) => s + Number(r.emp_70 || 0), 0);

  tbody.innerHTML = rows.map(r => {
    const pctNum = totGeral > 0 ? (Number(r.total_ecv) / totGeral) * 100 : 0;
    const pct = pctNum.toFixed(1).replace(".", ",");
    const ehPresc = r.faixa === "> 5 anos";
    const cor = corZona(r.faixa);
    return `
      <tr style="${ehPresc ? "background:rgba(244,63,94,0.06);" : ""}">
        <td style="font-family:var(--font-mono); font-weight:700; white-space:nowrap;">
          <span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:${cor}; margin-right:6px;"></span>${r.faixa}
        </td>
        <td style="text-align:right; font-family:var(--font-mono); color:var(--text-secondary);">${fmtInt(r.faturas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); min-width:145px;">
          <div style="font-weight:800; color:var(--text-primary);">${fmtCompacto(r.total_ecv)} <span style="color:var(--text-muted); font-weight:500; font-size:10.5px;">(${pct}%)</span></div>
          <div style="height:4px; background:rgba(148,163,184,0.18); border-radius:2px; margin-top:3px; overflow:hidden;">
            <div style="width:${Math.min(100, Math.max(1, pctNum)).toFixed(1)}%; height:100%; background:${cor};"></div>
          </div>
        </td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA;">${fmtCompacto(r.emp_17)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#FBBF24;">${fmtCompacto(r.emp_21)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#A78BFA;">${fmtCompacto(r.emp_07)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#F472B6;">${fmtCompacto(r.emp_70)}</td>
      </tr>
    `;
  }).join("");

  if (tfoot) {
    tfoot.innerHTML = `
      <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
        <td>TOTAL SUL</td>
        <td style="text-align:right;">${fmtInt(totFat)}</td>
        <td style="text-align:right;">${fmtCompacto(totGeral)} <span style="color:var(--text-muted); font-weight:500; font-size:10.5px;">(100%)</span></td>
        <td style="text-align:right; color:#60A5FA;">${fmtCompacto(tot17)}</td>
        <td style="text-align:right; color:#FBBF24;">${fmtCompacto(tot21)}</td>
        <td style="text-align:right; color:#A78BFA;">${fmtCompacto(tot07)}</td>
        <td style="text-align:right; color:#F472B6;">${fmtCompacto(tot70)}</td>
      </tr>
    `;
  }
}

function renderizarAdSGold(ads) {
  const tbody = document.getElementById("g-tbody-ads");
  const tfoot = document.getElementById("g-tfoot-ads");
  const agingBox = document.getElementById("g-ads-aging-pills");
  const resumoBadge = document.getElementById("g-ads-resumo-badge");

  if (resumoBadge) {
    resumoBadge.innerHTML = `Dívida Aberta: <strong style="color:#FBBF24;">${fmtM(ads.saldo_divida_ecv)} ECV</strong> • PM: <strong>${Number(ads.preco_medio_m3 || 0).toFixed(2).replace(".", ",")} ECV/m³</strong>`;
  }

  if (tbody) {
    const serie = ads.serie_mensal || [];
    const nomesMes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
    const fmtMesAdS = (lote) => {
      const ano = Number(String(lote).slice(0, 4));
      const mes = Number(String(lote).slice(4, 6));
      const d = new Date(ano, mes - 2, 1);
      return `${nomesMes[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`;
    };
    const maxVal = Math.max(1, ...serie.map(r => Number(r.valor_ecv || 0)));

    if (!serie.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:12px;">Sem registos AdS.</td></tr>`;
      if (tfoot) tfoot.innerHTML = "";
    } else {
      let totF = 0, totM3 = 0, totV = 0;
      tbody.innerHTML = serie.map(r => {
        const f = Number(r.faturas || 0);
        const m3 = Number(r.m3 || 0);
        const v = Number(r.valor_ecv || 0);
        const pm = Number(r.preco_medio_m3 || 0).toFixed(2).replace(".", ",");
        const w = Math.min(100, (v / maxVal) * 100).toFixed(0);
        totF += f; totM3 += m3; totV += v;
        return `
          <tr>
            <td style="font-family:var(--font-mono); font-weight:700; white-space:nowrap;">${fmtMesAdS(r.lote_ym)}</td>
            <td style="text-align:right; font-family:var(--font-mono); color:var(--text-secondary); white-space:nowrap;">${f}</td>
            <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap;">${(m3 / 1e3).toFixed(1).replace(".", ",")} k</td>
            <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap; min-width:105px;">
              <div style="font-weight:700; color:#FBBF24;">${fmtM(v)}</div>
              <div style="height:3px; background:rgba(148,163,184,0.18); border-radius:2px; margin-top:2px; overflow:hidden;">
                <div style="width:${w}%; height:100%; background:#FBBF24;"></div>
              </div>
            </td>
            <td style="text-align:right; font-family:var(--font-mono); color:var(--text-secondary); white-space:nowrap;">${pm}</td>
          </tr>
        `;
      }).join("");

      if (tfoot) {
        const pmTot = totM3 > 0 ? (totV / totM3).toFixed(2).replace(".", ",") : "0,00";
        tfoot.innerHTML = `
          <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
            <td style="white-space:nowrap;">TOTAL 2026</td>
            <td style="text-align:right; white-space:nowrap;">${totF}</td>
            <td style="text-align:right; white-space:nowrap;">${(totM3 / 1e6).toFixed(2).replace(".", ",")} M</td>
            <td style="text-align:right; color:#FBBF24; white-space:nowrap;">${fmtM(totV)}</td>
            <td style="text-align:right; color:var(--text-secondary); white-space:nowrap;">${pmTot}</td>
          </tr>
        `;
      }
    }
  }

  if (agingBox) {
    const ag = ads.aging || [];
    const totAg = ag.reduce((s, a) => s + Number(a.valor_ecv || 0), 0);
    agingBox.innerHTML = ag.map(a => {
      const pct = totAg > 0 ? ((Number(a.valor_ecv) / totAg) * 100).toFixed(1).replace(".", ",") : "0,0";
      const crit = a.faixa === "1-2 anos" || a.faixa === "2-5 anos";
      const cor = crit ? "#FBBF24" : "#34D399";
      const bg = crit ? "rgba(251,191,36,0.12)" : "rgba(52,211,153,0.12)";
      const bd = crit ? "rgba(251,191,36,0.35)" : "rgba(52,211,153,0.35)";
      return `
        <span class="badge" style="background:${bg}; color:${cor}; border:1px solid ${bd}; font-family:var(--font-mono); font-size:10.5px; padding:4px 8px;">
          ${a.faixa}: ${fmtM(a.valor_ecv)} (${pct}% · ${a.faturas} fat.)
        </span>
      `;
    }).join("");
  }
}

function renderizarOperacionalDQGold(op) {
  const ceaBox = document.getElementById("g-cea-os-box");
  const dqBox = document.getElementById("g-dq-box");
  if (ceaBox) {
    const anos = op.cea_por_ano || [];
    const osr = op.os_resumo || {};
    ceaBox.innerHTML = `
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
        <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:6px; padding:10px 12px;">
          <div style="font-size:10.5px; color:var(--text-muted); font-family:var(--font-mono);">ORDENS DE SERVIÇO (or_serv)</div>
          <div style="font-size:18px; font-weight:800; font-family:var(--font-display); margin-top:2px;">${fmtInt(osr.total)} OS</div>
          <div style="font-size:11px; color:var(--text-secondary);">Executadas: ${fmtInt(osr.executadas)} • SLA médio: <strong>${osr.sla_medio_dias ?? 0}d</strong> (mediana ${osr.sla_mediana_dias ?? 0}d)</div>
        </div>
        <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:6px; padding:10px 12px;">
          <div style="font-size:10.5px; color:var(--text-muted); font-family:var(--font-mono);">HISTÓRICO INSPEÇÕES CEA</div>
          <div style="font-size:18px; font-weight:800; font-family:var(--font-display); margin-top:2px;">${fmtInt(anos.reduce((s, a) => s + a.total, 0))} insp.</div>
          <div style="font-size:11px; color:var(--text-secondary);">Base pronta para calibração do Score v2 (Fase 3)</div>
        </div>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        ${anos.map(a => `
          <span class="badge" style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); color:var(--text-primary); font-family:var(--font-mono); font-size:10.5px; padding:4px 8px;">
            ${a.ano}: ${fmtInt(a.total)} (${fmtInt(a.executadas)} exec.)
          </span>
        `).join("")}
      </div>
    `;
  }
  if (dqBox) {
    const dq = op.qualidade_dados || {};
    const fd = dq.funil_divida || {};
    const testes = dq.testes || [];
    const frescura = op.frescura_fontes || [];
    const snaps = op.snapshots_divida_arquivados || 0;
    dqBox.innerHTML = `
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
        <span class="badge ${dq.todos_testes_ok ? "badge-ok" : "badge-crit"}" style="font-family:var(--font-mono);">
          ${dq.todos_testes_ok ? "✔ DATA QUALITY APROVADO" : "✖ FALHA DQ"}
        </span>
        <span class="badge" style="background:rgba(96,165,250,0.12); color:#60A5FA; border:1px solid rgba(96,165,250,0.35); font-family:var(--font-mono); font-size:10.5px;">
          📦 Snapshots Dívida: ${snaps} mês(es)
        </span>
        ${testes.map(t => `
          <span class="badge" style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); font-family:var(--font-mono); font-size:10.5px;">
            ${t.passou ? "✔" : "✖"} ${t.teste} (${t.falhas})
          </span>
        `).join("")}
      </div>
      <div style="font-family:var(--font-mono); font-size:11.5px; color:var(--text-secondary); line-height:1.7; margin-bottom:8px;">
        • <strong>Funil Dívida (Bronze → Silver Sul):</strong> Bruto <code>${fmtM(fd.bronze_ecv)} ECV</code> (${fmtInt(fd.bronze_linhas)} fat.)
        − Fora Sul/Inválidos <code>${fmtM(fd.filtrado_fora_sul_ou_invalido_ecv)} ECV</code>
        = Silver Região Sul <strong><code>${fmtM(fd.silver_ecv)} ECV</code></strong> (${fmtInt(fd.silver_linhas)} fat.).
      </div>
      ${frescura.length ? `
        <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
          <span style="font-family:var(--font-mono); font-size:10.5px; color:var(--text-muted);">Frescura Fontes:</span>
          ${frescura.map(f => {
            const atras = f.alerta_atraso;
            const cor = atras ? "#FBBF24" : "#34D399";
            const bg = atras ? "rgba(251,191,36,0.12)" : "rgba(52,211,153,0.10)";
            const bd = atras ? "rgba(251,191,36,0.35)" : "rgba(52,211,153,0.3)";
            return `<span class="badge" style="background:${bg}; color:${cor}; border:1px solid ${bd}; font-family:var(--font-mono); font-size:10px; padding:2px 6px;" title="${f.ultimo_ficheiro} (${f.modificado_em})">${f.categoria}: ${f.dias_idade}d</span>`;
          }).join("")}
        </div>
      ` : ""}
    `;
  }
}

window._scoreV2Top100 = [];

function exportarBrigadasScoreV2CSV() {
  const rows = window._scoreV2Top100 || [];
  if (!rows.length) {
    alert("Abra a aba 0. Visão Executiva (Gold) e aguarde o carregamento antes de exportar.");
    return;
  }
  const cab = ["CIL", "Nome", "Ilha", "Unidade", "PT", "Probabilidade_Fraude_Pct", "Score_v2", "Divida_Exigivel_ECV", "T3_kWh", "Fatores_Explicaveis"];
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const linhas = [
    cab.join(";"),
    ...rows.map(r => [
      r.cil, esc(r.nome), esc(r.ilha), esc(r.desc_uni), esc(r.pt),
      r.prob_fraude_pct, r.score_v2, r.divida_exigivel_ecv, r.t3_kwh, esc(r.motivos_v2)
    ].join(";"))
  ];
  salvarOuBaixarCSV(`EDEC_Brigadas_ScoreV2_Top100_${new Date().toISOString().slice(0, 10)}.csv`, "\uFEFF" + linhas.join("\r\n"));
}

function renderizarScoreV2Gold(sv2) {
  const badgesEl = document.getElementById("g-scorev2-badges");
  const tbodyDecis = document.getElementById("g-tbody-decis");
  const tbodyTop = document.getElementById("g-tbody-top100");
  if (!sv2 || !sv2.auc_teste_out_of_time) return;

  if (badgesEl) {
    const top10 = sv2.cortes?.top_10pct || {};
    badgesEl.innerHTML = `
      <span class="badge badge-ok" style="font-family:var(--font-mono);">AUC Out-of-Time: ${sv2.auc_teste_out_of_time}</span>
      <span class="badge" style="background:rgba(96,165,250,0.14); color:#60A5FA; border:1px solid rgba(96,165,250,0.35); font-family:var(--font-mono);">
        Top 10%: ${top10.precision_pct || 0}% acerto (Lift ${top10.lift || 1}x vs base ${sv2.taxa_fraude_base_teste_pct}%)
      </span>
    `;
  }

  if (tbodyDecis) {
    const decis = sv2.decis || [];
    tbodyDecis.innerHTML = decis.map(d => {
      const cor = d.lift >= 2 ? "#34D399" : d.lift >= 1 ? "#FBBF24" : "var(--text-muted)";
      return `
        <tr>
          <td style="font-family:var(--font-mono); font-weight:700;">${d.decil}</td>
          <td style="text-align:right; font-family:var(--font-mono);">${fmtInt(d.insp)}</td>
          <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtInt(d.fraudes)}</td>
          <td style="text-align:right; font-family:var(--font-mono); color:${cor}; font-weight:700;">${d.taxa_fraude_pct}%</td>
          <td style="text-align:right; font-family:var(--font-mono); color:${cor}; font-weight:800;">${d.lift}x</td>
        </tr>
      `;
    }).join("");
  }

  if (tbodyTop) {
    const top = sv2.fila_brigada_top100 || [];
    window._scoreV2Top100 = top;
    tbodyTop.innerHTML = top.map(r => `
      <tr style="cursor:pointer;" onclick="if(typeof abrirDossiePorCIL==='function') abrirDossiePorCIL(${r.cil})">
        <td style="font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${r.cil}</td>
        <td style="max-width:170px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${r.nome || "--"}</td>
        <td style="font-family:var(--font-mono); font-size:11px;">${r.pt}</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:800; color:#F87171;">${r.prob_fraude_pct}%</td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtM(r.divida_exigivel_ecv)}</td>
        <td style="font-size:11px; color:var(--text-secondary);">${r.motivos_v2}</td>
      </tr>
    `).join("");
  }
}

function renderizarPrepagoGold(prep, kpis = {}) {
  const box = document.getElementById("g-prepago-resumo-box");
  const tbody = document.getElementById("g-tbody-prepago-pts");
  const pr = prep?.resumo;
  if (!box || !pr) return;

  const emPoligono = (prep.medidores || []).filter(m => m.pt_origem === "Polígono Exato").length;
  const recTotal17 = Number(kpis.fat_17_ecv || 0) + Number(pr.total_m_ecv || 0) * 1e6;

  box.innerHTML = `
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-family:var(--font-mono); font-size:11px;">
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:4px; padding:8px 10px;">
        <div style="color:var(--text-muted); font-size:9.5px;">MEDIDORES ATIVOS</div>
        <div style="font-size:15px; font-weight:800; color:#60A5FA;">${Number(pr.total_medidores || 0).toLocaleString("pt-PT")}</div>
        <div style="color:var(--text-muted); font-size:9.5px;">${emPoligono.toLocaleString("pt-PT")} em Polígonos PT</div>
      </div>
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:4px; padding:8px 10px;">
        <div style="color:var(--text-muted); font-size:9.5px;">VENDAS TOKENS (PM ${Number(pr.preco_medio_kwh || 0).toFixed(2)})</div>
        <div style="font-size:15px; font-weight:800; color:#34D399;">${Number(pr.total_m_ecv || 0).toFixed(1)}M ECV</div>
        <div style="color:var(--text-muted); font-size:9.5px;">${Number(pr.total_mwh || 0).toLocaleString("pt-PT")} MWh • Total 17: ${fmtM(recTotal17)}</div>
      </div>
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:4px; padding:8px 10px;">
        <div style="color:var(--text-muted); font-size:9.5px;">SEM COMPRA (&gt;60d / &gt;90d)</div>
        <div style="font-size:15px; font-weight:800; color:#F87171;">${Number(pr.sem_compra_60d || 0).toLocaleString("pt-PT")}</div>
        <div style="color:var(--text-muted); font-size:9.5px;">&gt;30d: ${Number(pr.sem_compra_30d || 0).toLocaleString("pt-PT")} • &gt;90d: ${Number(pr.sem_compra_90d || 0).toLocaleString("pt-PT")}</div>
      </div>
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:4px; padding:8px 10px;">
        <div style="color:var(--text-muted); font-size:9.5px;">DESVIO ≤ -50% / VALOR BAIXO</div>
        <div style="font-size:15px; font-weight:800; color:#FBBF24;">${Number(pr.desvio_50_pct || 0).toLocaleString("pt-PT")} / ${Number(pr.valor_baixo_qtd || 0).toLocaleString("pt-PT")}</div>
        <div style="color:var(--text-muted); font-size:9.5px;">Críticos totais: ${Number(pr.criticos_qtd || 0).toLocaleString("pt-PT")}</div>
      </div>
    </div>
  `;

  if (tbody) {
    const topPts = (prep.ranking_pts || []).slice(0, 5);
    tbody.innerHTML = topPts.map(p => `
      <tr style="cursor:pointer;" onclick="selecionarModulo('mod4'); setTimeout(() => { if(typeof filtrarPTPrepago==='function') filtrarPTPrepago('${p.pt}'); }, 120);">
        <td style="font-family:var(--font-mono); font-weight:700; color:#60A5FA;">${p.pt}</td>
        <td style="font-size:11px; color:var(--text-secondary);">${p.localidade || "--"}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${Number(p.total_med || 0).toLocaleString("pt-PT")}</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700; color:#F87171;">${Number(p.criticos || 0).toLocaleString("pt-PT")}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#FBBF24;">${Number(p.sem_60d || 0).toLocaleString("pt-PT")}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${Number(p.m_ecv || 0).toFixed(1)}M</td>
      </tr>
    `).join("");
  }
}
