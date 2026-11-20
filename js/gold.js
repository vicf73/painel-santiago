// =========================================================================
// MÓDULO 0: VISÃO EXECUTIVA & MARTS GOLD (LAKEHOUSE SANTIAGO)
// Consome public.santiago_marts_gold via PostgREST autenticado (JWT/RLS)
// Suporta filtro reativo em tempo real por Unidade Comercial (desc_uni)
// e Quadro Dedicado do Conceito RX0 / RXO (Taxa de Religação).
// =========================================================================

let goldCarregado = false;
window._goldMapa = null;
window._goldUnidadeAtual = "TODAS";

const fmtM = (v) => {
  const n = Number(v || 0);
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2).replace(".", ",") + " B";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1).replace(".", ",") + " k";
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

    window._goldMapa = mapa;
    popularSeletorUnidadesGold(mapa);
    aplicarFiltroUnidadeGold(window._goldUnidadeAtual || "TODAS");

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

function obterListaUnidadesGold(mapa) {
  const cat = mapa?.kpis_executivos?.unidades_comerciais;
  if (Array.isArray(cat) && cat.length) return cat;
  const setU = new Set();
  for (const r of (mapa?.faturacao_mensal?.rows || [])) {
    if (r.desc_uni) setU.add(r.desc_uni);
  }
  return Array.from(setU).sort().map(u => ({ desc_uni: u, ilha: "" }));
}

function popularSeletorUnidadesGold(mapa) {
  const sel = document.getElementById("gold-filtro-uc");
  if (!sel) return;
  const ucs = obterListaUnidadesGold(mapa);
  const atual = window._goldUnidadeAtual || "TODAS";
  sel.innerHTML = [
    `<option value="TODAS">Todas as Unidades (Região Sul · ${ucs.length || 10})</option>`,
    ...ucs.map(u => `<option value="${u.desc_uni}">${u.desc_uni}${u.ilha ? ` (${u.ilha})` : ""}</option>`)
  ].join("");
  sel.value = ucs.some(u => u.desc_uni === atual) ? atual : "TODAS";
}

function selecionarUnidadeGold(uc) {
  const novo = (uc && uc === window._goldUnidadeAtual && uc !== "TODAS") ? "TODAS" : (uc || "TODAS");
  const sel = document.getElementById("gold-filtro-uc");
  if (sel) sel.value = novo;
  aplicarFiltroUnidadeGold(novo);
}

function calcularKpisUnidadeGold(mapa, uc, fatRows, cobRows, agingRows, rx0Rows) {
  const baseK = mapa.kpis_executivos || {};
  const ehTodas = !uc || uc === "TODAS";

  const fat17Rows = fatRows.filter(r => r.emp === "17");
  const fat17Ecv = ehTodas && !fatRows.some(r => r.desc_uni)
    ? Number(baseK.fat_17_ecv || 0)
    : fat17Rows.reduce((s, r) => s + Number(r.valor_ecv || 0), 0);
  const fat17Kwh = ehTodas && !fatRows.some(r => r.desc_uni)
    ? Number(baseK.fat_17_kwh || 0)
    : fat17Rows.reduce((s, r) => s + Number(r.consumo_qtd || 0), 0);

  const lotes17 = Array.from(new Set(fat17Rows.map(r => r.lote_ym))).sort();
  const ult3 = new Set(lotes17.slice(-3));
  const fat17_90d = fat17Rows.filter(r => ult3.has(r.lote_ym)).reduce((s, r) => s + Number(r.valor_ecv || 0), 0);

  const sumCob = (emp) => cobRows.filter(r => r.emp === emp).reduce((s, r) => s + Number(r.valor_ecv || 0), 0);
  const cob17 = ehTodas && !cobRows.some(r => r.desc_uni) ? Number(baseK.cob_17_ecv || 0) : sumCob("17");
  const cob21 = ehTodas && !cobRows.some(r => r.desc_uni) ? Number(baseK.cob_21_ecv || 0) : sumCob("21");
  const cob07 = ehTodas && !cobRows.some(r => r.desc_uni) ? Number(baseK.cob_07_ecv || 0) : sumCob("7");
  const cob70 = ehTodas && !cobRows.some(r => r.desc_uni) ? Number(baseK.cob_70_ecv || 0) : sumCob("70");
  const cobTot = cob17 + cob21 + cob07 + cob70;

  const div17 = agingRows.reduce((s, r) => s + Number(r.emp_17 || 0), 0);
  const div21 = agingRows.reduce((s, r) => s + Number(r.emp_21 || 0), 0);
  const div07 = agingRows.reduce((s, r) => s + Number(r.emp_07 || 0), 0);
  const div70 = agingRows.reduce((s, r) => s + Number(r.emp_70 || 0), 0);
  const divTot = agingRows.reduce((s, r) => s + Number(r.total_ecv || 0), 0);
  const divPresc = agingRows.filter(r => r.faixa === "> 5 anos").reduce((s, r) => s + Number(r.total_ecv || 0), 0);

  const taxaCob17 = fat17Ecv > 0 ? Number(((cob17 / fat17Ecv) * 100).toFixed(1)) : 0.0;
  const dso17 = fat17_90d > 0 ? Math.round((div17 / fat17_90d) * 90) : 0;

  const rxFat = rx0Rows.reduce((s, r) => s + Number(r.faturado_ecv || 0), 0);
  const rxCob = rx0Rows.reduce((s, r) => s + Number(r.cobrado_caixa_ecv || 0), 0);
  const rxLiq = rx0Rows.reduce((s, r) => s + Number(r.liquidado_ecv || 0), 0);
  const rxDiv = rx0Rows.reduce((s, r) => s + Number(r.em_divida_ecv || 0), 0);
  const rxQtd = rx0Rows.reduce((s, r) => s + Number(r.faturas || 0), 0);

  return {
    ...baseK,
    fat_17_ecv: fat17Ecv,
    fat_17_kwh: fat17Kwh,
    fat_17_90d_ecv: fat17_90d,
    cob_17_ecv: cob17,
    cob_21_ecv: cob21,
    cob_07_ecv: cob07,
    cob_70_ecv: cob70,
    cob_total_ecv: cobTot,
    taxa_cobranca_17_pct: taxaCob17,
    dso_17_dias: dso17,
    divida_total_ecv: divTot,
    divida_17_ecv: div17,
    divida_21_ecv: div21,
    divida_07_ecv: div07,
    divida_70_ecv: div70,
    divida_prescrita_ecv: divPresc,
    divida_exigivel_ecv: divTot - divPresc,
    rx0_faturas: rxQtd,
    rx0_faturado_ecv: rxFat,
    rx0_cobrado_caixa_ecv: rxCob,
    rx0_liquidado_ecv: rxLiq,
    rx0_em_divida_ecv: rxDiv,
    rx0_taxa_cobranca_pct: rxFat > 0 ? Number(((rxCob / rxFat) * 100).toFixed(1)) : 0.0,
    rx0_taxa_liquidacao_pct: rxFat > 0 ? Number(((rxLiq / rxFat) * 100).toFixed(1)) : 0.0,
  };
}

function obterPrepagoFiltradoGold(prep, uc) {
  if (!prep) return { resumo: {}, ranking_pts: [] };
  if (!uc || uc === "TODAS") return prep;
  if (prep.por_unidade && prep.por_unidade[uc]) {
    return prep.por_unidade[uc];
  }
  return {
    resumo: {
      total_medidores: 0, em_poligono: 0, total_m_ecv: 0, total_mwh: 0,
      preco_medio_kwh: 0, sem_compra_30d: 0, sem_compra_60d: 0,
      sem_compra_90d: 0, desvio_50_pct: 0, valor_baixo_qtd: 0, criticos_qtd: 0,
    },
    ranking_pts: [],
  };
}

function aplicarFiltroUnidadeGold(uc) {
  const mapa = window._goldMapa;
  if (!mapa) return;
  const unidade = uc || "TODAS";
  window._goldUnidadeAtual = unidade;
  const ehTodas = unidade === "TODAS";

  const badge = document.getElementById("gold-uc-context-badge");
  if (badge) {
    badge.textContent = ehTodas ? "REGIÃO SUL (10 UNIDADES)" : `UNIDADE: ${unidade.toUpperCase()}`;
    badge.style.background = ehTodas ? "rgba(96,165,250,0.14)" : "rgba(251,191,36,0.18)";
    badge.style.color = ehTodas ? "#60A5FA" : "#FBBF24";
    badge.style.borderColor = ehTodas ? "rgba(96,165,250,0.4)" : "rgba(251,191,36,0.5)";
  }
  const btnLimpar = document.getElementById("gold-btn-limpar-uc");
  if (btnLimpar) btnLimpar.style.display = ehTodas ? "none" : "inline-flex";

  const allFat = mapa.faturacao_mensal?.rows || [];
  const allCob = mapa.cobranca_mensal?.rows || [];
  const fatRows = ehTodas ? allFat : allFat.filter(r => r.desc_uni === unidade);
  const cobRows = ehTodas ? allCob : allCob.filter(r => r.desc_uni === unidade);

  const agingRows = ehTodas
    ? (mapa.aging_divida?.rows || [])
    : (mapa.aging_divida?.rows_por_unidade || []).filter(r => r.desc_uni === unidade);

  const allRx0 = mapa.religacao_rx0?.rows_mensal_unidade || [];
  const rx0Rows = ehTodas ? allRx0 : allRx0.filter(r => r.desc_uni === unidade);

  const prepFiltrado = obterPrepagoFiltradoGold(mapa.prepago_analise || {}, unidade);
  const kpis = calcularKpisUnidadeGold(mapa, unidade, fatRows, cobRows, agingRows, rx0Rows);

  renderizarKpisGold(kpis, prepFiltrado, unidade);
  renderizarSerieFatCobGold(fatRows, cobRows);
  renderizarAgingGold(agingRows, unidade);
  renderizarRx0Gold(mapa.religacao_rx0 || {}, unidade);
  renderizarMatrizComparativaUnidadesGold(mapa, unidade);
  renderizarAdSGold(mapa.ads_conta_corrente || {}, unidade);
  renderizarOperacionalDQGold(mapa.operacional_cea_os || {}, unidade);
  renderizarScoreV2Gold(mapa.score_v2_validacao || {}, unidade);
  renderizarPrepagoGold(prepFiltrado, kpis, unidade);
}

function renderizarKpisGold(k, prep = {}, uc = "TODAS") {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  const ehTodas = !uc || uc === "TODAS";
  const escopoTxt = ehTodas ? "REGIÃO SUL" : uc.toUpperCase();
  set("g-lbl-fat17-scope", ehTodas ? "2026 · SUL" : uc.toUpperCase());
  set("g-lbl-cob-scope", ehTodas ? "4 EMPRESAS" : uc.toUpperCase());
  set("g-lbl-div-scope", escopoTxt);

  const pr = prep.resumo || {};
  const prepEcv = Number(pr.total_m_ecv || 0) * 1e6;
  const tot17Cons = Number(k.fat_17_ecv || 0) + prepEcv;
  set("g-kpi-fat17", `${fmtM(k.fat_17_ecv)} ECV`);
  set("g-kpi-fat17-sub", `${(Number(k.fat_17_kwh || 0) / 1e6).toFixed(2)} GWh • c/ Pré-Pago: ${fmtM(tot17Cons)}`);

  set("g-kpi-cob-tot", `${fmtM(k.cob_total_ecv)} ECV`);
  set("g-kpi-cob-tot-sub", `17: ${fmtM(k.cob_17_ecv)} • 07: ${fmtM(k.cob_07_ecv)} • 70: ${fmtM(k.cob_70_ecv)}`);

  set("g-kpi-taxa-cob", `${k.taxa_cobranca_17_pct ?? 0}%`);
  set("g-kpi-taxa-cob-sub", `EDEC (17): ${fmtM(k.cob_17_ecv)} / ${fmtM(k.fat_17_ecv)} ECV`);

  set("g-kpi-dso", `${k.dso_17_dias ?? 0} dias`);
  set("g-kpi-dso-sub", `Dívida 17 (${fmtM(k.divida_17_ecv)}) / Fat. 90d (${fmtM(k.fat_17_90d_ecv)})`);

  set("g-kpi-div-exig", `${fmtM(k.divida_exigivel_ecv)} ECV`);
  set("g-kpi-div-exig-sub", `Total: ${fmtM(k.divida_total_ecv)} • Prescrita >5a: ${fmtM(k.divida_prescrita_ecv)}`);

  set("g-kpi-rx0", `${fmtM(k.rx0_faturado_ecv)} ECV`);
  set("g-kpi-rx0-sub", `Cob: ${k.rx0_taxa_cobranca_pct ?? 0}% • Liq: ${k.rx0_taxa_liquidacao_pct ?? 0}% (${Number(k.rx0_faturas || 0).toLocaleString("pt-PT")} taxas)`);

  const adsEhPraia = ehTodas || uc === "Praia";
  set("g-kpi-ads", adsEhPraia ? `${fmtM(k.fat_21_ads_ecv)} ECV` : "0 ECV");
  set("g-kpi-ads-sub", adsEhPraia
    ? `${(Number(k.fat_21_ads_m3 || 0) / 1e6).toFixed(2)}M m³ • Dívida AdS: ${fmtM(k.divida_21_ecv)}`
    : "Contrato AdS concentrado na UC Praia");

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
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:16px; color:var(--text-muted);">Sem dados mensais para a Unidade selecionada.</td></tr>`;
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
    const gap = f.fat_ecv - cob;
    const taxaNum = f.fat_ecv > 0 ? (cob / f.fat_ecv) * 100 : 0;
    const taxa = taxaNum.toFixed(1).replace(".", ",");
    const pm = f.fat_kwh > 0 ? (f.fat_ecv / f.fat_kwh).toFixed(2).replace(".", ",") : "0,00";
    const corTaxa = taxaNum >= 90 ? "#34D399" : taxaNum >= 75 ? "#FBBF24" : "#F87171";
    const corGap = gap <= 0 ? "#34D399" : "#F87171";

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
        <td style="text-align:right; font-family:var(--font-mono); color:${corGap}; white-space:nowrap;">${gap > 0 ? "−" : "+"}${fmtM(Math.abs(gap))}</td>
        <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap; min-width:74px;">
          <div style="font-weight:800; color:${corTaxa};">${taxa}%</div>
          <div style="height:3px; background:rgba(148,163,184,0.18); border-radius:2px; margin-top:2px; overflow:hidden;">
            <div style="width:${Math.min(100, Math.max(0, taxaNum)).toFixed(0)}%; height:100%; background:${corTaxa};"></div>
          </div>
        </td>
        <td style="text-align:right; font-family:var(--font-mono); font-size:10px; color:var(--text-secondary); white-space:nowrap;" title="EB: ${fmtM(f.eb)} | EM: ${fmtM(f.em)} | EE: ${fmtM(f.ee)}">
          ${fmtM(f.eb)} / ${fmtM(f.em)} / ${fmtM(f.ee)}
        </td>
      </tr>
    `;
  }).join("");

  if (tfoot) {
    const gapTot = totFat - totCob;
    const corGapTot = gapTot <= 0 ? "#34D399" : "#F87171";
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
        <td style="text-align:right; color:${corGapTot}; white-space:nowrap;">${gapTot > 0 ? "−" : "+"}${fmtM(Math.abs(gapTot))}</td>
        <td style="text-align:right; color:${corTot}; white-space:nowrap;">${taxaTot}%</td>
        <td style="text-align:right; font-size:10px; color:var(--text-secondary); white-space:nowrap;">${fmtM(totEb)} / ${fmtM(totEm)} / ${fmtM(totEe)}</td>
      </tr>
    `;
  }
}

function renderizarAgingGold(rows, uc = "TODAS") {
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
    const lblTot = (!uc || uc === "TODAS") ? "TOTAL SUL" : `TOTAL ${uc.toUpperCase()}`;
    tfoot.innerHTML = `
      <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
        <td>${lblTot}</td>
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

function renderizarRx0Gold(rx0Data, uc = "TODAS") {
  const kpisBox = document.getElementById("g-rx0-kpis-box");
  const badgeEl = document.getElementById("g-rx0-scope-badge");
  const tbodyM = document.getElementById("g-tbody-rx0-mensal");
  const tfootM = document.getElementById("g-tfoot-rx0-mensal");
  const tbodyU = document.getElementById("g-tbody-rx0-uc");
  const tfootU = document.getElementById("g-tfoot-rx0-uc");
  if (!tbodyM || !tbodyU) return;

  const ehTodas = !uc || uc === "TODAS";
  const allRows = rx0Data?.rows_mensal_unidade || [];
  const rowsFiltradas = ehTodas ? allRows : allRows.filter(r => r.desc_uni === uc);

  const totFatQtd = rowsFiltradas.reduce((s, r) => s + Number(r.faturas || 0), 0);
  const totCils = rowsFiltradas.reduce((s, r) => s + Number(r.cils || 0), 0);
  const totFatEcv = rowsFiltradas.reduce((s, r) => s + Number(r.faturado_ecv || 0), 0);
  const totCobQtd = rowsFiltradas.reduce((s, r) => s + Number(r.cobrado_caixa_qtd || 0), 0);
  const totCobEcv = rowsFiltradas.reduce((s, r) => s + Number(r.cobrado_caixa_ecv || 0), 0);
  const totLiqQtd = rowsFiltradas.reduce((s, r) => s + Number(r.liquidado_qtd || 0), 0);
  const totLiqEcv = rowsFiltradas.reduce((s, r) => s + Number(r.liquidado_ecv || 0), 0);
  const totDivQtd = rowsFiltradas.reduce((s, r) => s + Number(r.em_divida_qtd || 0), 0);
  const totDivEcv = rowsFiltradas.reduce((s, r) => s + Number(r.em_divida_ecv || 0), 0);

  const pctCob = totFatEcv > 0 ? ((totCobEcv / totFatEcv) * 100).toFixed(1).replace(".", ",") : "0,0";
  const pctLiq = totFatEcv > 0 ? ((totLiqEcv / totFatEcv) * 100).toFixed(1).replace(".", ",") : "0,0";
  const pctDiv = totFatEcv > 0 ? ((totDivEcv / totFatEcv) * 100).toFixed(1).replace(".", ",") : "0,0";
  const ticketMedio = totFatQtd > 0 ? Math.round(totFatEcv / totFatQtd).toLocaleString("pt-PT") : "0";

  if (badgeEl) {
    badgeEl.innerHTML = `Escopo: <strong style="color:#A78BFA;">${ehTodas ? "Região Sul (10 Unidades)" : uc}</strong> • Ticket Médio Religação: <strong>${ticketMedio} ECV</strong>`;
  }

  if (kpisBox) {
    kpisBox.innerHTML = `
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:6px; padding:10px 12px;">
        <div style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono);">FATURADO RX0 (TAXA RELIGAÇÃO)</div>
        <div style="font-size:18px; font-weight:800; color:#A78BFA; font-family:var(--font-display); margin-top:2px;">${fmtM(totFatEcv)} ECV</div>
        <div style="font-size:11px; color:var(--text-secondary);">${fmtInt(totFatQtd)} taxas emitidas • Ticket: ${ticketMedio} ECV</div>
      </div>
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:6px; padding:10px 12px;">
        <div style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono);">COBRADO EM CAIXA (RECIBO DIRETO)</div>
        <div style="font-size:18px; font-weight:800; color:#60A5FA; font-family:var(--font-display); margin-top:2px;">${fmtM(totCobEcv)} ECV <span style="font-size:12px;">(${pctCob}%)</span></div>
        <div style="font-size:11px; color:var(--text-secondary);">${fmtInt(totCobQtd)} faturas RX0 com recibo em caixa</div>
      </div>
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:6px; padding:10px 12px;">
        <div style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono);">LIQUIDADO EFETIVO (SEM DÍVIDA)</div>
        <div style="font-size:18px; font-weight:800; color:#34D399; font-family:var(--font-display); margin-top:2px;">${fmtM(totLiqEcv)} ECV <span style="font-size:12px;">(${pctLiq}%)</span></div>
        <div style="font-size:11px; color:var(--text-secondary);">${fmtInt(totLiqQtd)} de ${fmtInt(totFatQtd)} faturas regularizadas</div>
      </div>
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:6px; padding:10px 12px;">
        <div style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono);">SALDO RX0 EM DÍVIDA ABERTA</div>
        <div style="font-size:18px; font-weight:800; color:#F87171; font-family:var(--font-display); margin-top:2px;">${fmtM(totDivEcv)} ECV <span style="font-size:12px;">(${pctDiv}%)</span></div>
        <div style="font-size:11px; color:var(--text-secondary);">${fmtInt(totDivQtd)} faturas com RX0 por cobrar</div>
      </div>
    `;
  }

  // Tabela Esquerda: Evolução Mensal RX0
  const porMes = {};
  for (const r of rowsFiltradas) {
    const ym = r.lote_ym;
    if (!porMes[ym]) {
      porMes[ym] = { faturas: 0, cils: 0, fat: 0, cob: 0, liq: 0, div: 0 };
    }
    porMes[ym].faturas += Number(r.faturas || 0);
    porMes[ym].cils += Number(r.cils || 0);
    porMes[ym].fat += Number(r.faturado_ecv || 0);
    porMes[ym].cob += Number(r.cobrado_caixa_ecv || 0);
    porMes[ym].liq += Number(r.liquidado_ecv || 0);
    porMes[ym].div += Number(r.em_divida_ecv || 0);
  }
  const nomesMes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  const fmtLote = (lote) => {
    const ano = Number(String(lote).slice(0, 4));
    const mes = Number(String(lote).slice(4, 6));
    const d = new Date(ano, mes - 2, 1);
    return `${nomesMes[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`;
  };
  const lotes = Object.keys(porMes).sort();

  if (!lotes.length) {
    tbodyM.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:14px; color:var(--text-muted);">Sem faturas RX0 para a Unidade selecionada.</td></tr>`;
    if (tfootM) tfootM.innerHTML = "";
  } else {
    tbodyM.innerHTML = lotes.map(ym => {
      const m = porMes[ym];
      const pCob = m.fat > 0 ? ((m.cob / m.fat) * 100).toFixed(1).replace(".", ",") : "0,0";
      const pLiqNum = m.fat > 0 ? (m.liq / m.fat) * 100 : 0;
      const pLiq = pLiqNum.toFixed(1).replace(".", ",");
      const cor = pLiqNum >= 90 ? "#34D399" : pLiqNum >= 75 ? "#FBBF24" : "#F87171";
      return `
        <tr>
          <td style="font-family:var(--font-mono); font-weight:700; white-space:nowrap;">${fmtLote(ym)}</td>
          <td style="text-align:right; font-family:var(--font-mono);">${fmtInt(m.faturas)}</td>
          <td style="text-align:right; font-family:var(--font-mono); color:var(--text-secondary);">${fmtInt(m.cils)}</td>
          <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtM(m.fat)}</td>
          <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${fmtM(m.cob)}</td>
          <td style="text-align:right; font-family:var(--font-mono); color:#34D399; font-weight:700;">${fmtM(m.liq)}</td>
          <td style="text-align:right; font-family:var(--font-mono); color:#F87171;">${fmtM(m.div)}</td>
          <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap; min-width:86px;">
            <div style="font-weight:800; color:${cor};">${pCob}% / ${pLiq}%</div>
            <div style="height:3px; background:rgba(148,163,184,0.18); border-radius:2px; margin-top:2px; overflow:hidden;">
              <div style="width:${Math.min(100, Math.max(0, pLiqNum)).toFixed(0)}%; height:100%; background:${cor};"></div>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    if (tfootM) {
      tfootM.innerHTML = `
        <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
          <td>TOTAL 2026</td>
          <td style="text-align:right;">${fmtInt(totFatQtd)}</td>
          <td style="text-align:right; color:var(--text-secondary);">${fmtInt(totCils)}</td>
          <td style="text-align:right;">${fmtM(totFatEcv)}</td>
          <td style="text-align:right; color:#60A5FA;">${fmtM(totCobEcv)}</td>
          <td style="text-align:right; color:#34D399;">${fmtM(totLiqEcv)}</td>
          <td style="text-align:right; color:#F87171;">${fmtM(totDivEcv)}</td>
          <td style="text-align:right; color:#34D399;">${pctCob}% / ${pctLiq}%</td>
        </tr>
      `;
    }
  }

  // Tabela Direita: Ranking por Unidade Comercial (sempre mostra todas as UCs com destaque para a UC selecionada)
  const porUc = {};
  for (const r of allRows) {
    const u = r.desc_uni || "Praia";
    if (!porUc[u]) porUc[u] = { desc_uni: u, faturas: 0, cils: 0, fat: 0, cob: 0, liq: 0, div: 0 };
    porUc[u].faturas += Number(r.faturas || 0);
    porUc[u].cils += Number(r.cils || 0);
    porUc[u].fat += Number(r.faturado_ecv || 0);
    porUc[u].cob += Number(r.cobrado_caixa_ecv || 0);
    porUc[u].liq += Number(r.liquidado_ecv || 0);
    porUc[u].div += Number(r.em_divida_ecv || 0);
  }
  const listaUc = Object.values(porUc).sort((a, b) => b.fat - a.fat);
  const totAllFat = listaUc.reduce((s, x) => s + x.fat, 0);
  const totAllCob = listaUc.reduce((s, x) => s + x.cob, 0);
  const totAllLiq = listaUc.reduce((s, x) => s + x.liq, 0);
  const totAllDiv = listaUc.reduce((s, x) => s + x.div, 0);
  const totAllQtd = listaUc.reduce((s, x) => s + x.faturas, 0);
  const totAllCils = listaUc.reduce((s, x) => s + x.cils, 0);

  tbodyU.innerHTML = listaUc.map(item => {
    const ativa = item.desc_uni === uc;
    const pLiqNum = item.fat > 0 ? (item.liq / item.fat) * 100 : 0;
    const pLiq = pLiqNum.toFixed(1).replace(".", ",");
    const quota = totAllFat > 0 ? ((item.fat / totAllFat) * 100).toFixed(1).replace(".", ",") : "0,0";
    const cor = pLiqNum >= 90 ? "#34D399" : pLiqNum >= 75 ? "#FBBF24" : "#F87171";
    return `
      <tr style="cursor:pointer; ${ativa ? "background:rgba(251,191,36,0.14); font-weight:700;" : ""}" onclick="selecionarUnidadeGold('${item.desc_uni.replace(/'/g, "\\'")}')" title="Clicar para filtrar a Visão Executiva por ${item.desc_uni}">
        <td style="font-family:var(--font-mono); font-weight:700; color:${ativa ? "#FBBF24" : "#60A5FA"}; white-space:nowrap;">
          ${ativa ? "▶ " : ""}${item.desc_uni} <span style="color:var(--text-muted); font-size:10px; font-weight:400;">(${quota}%)</span>
        </td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtInt(item.faturas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:var(--text-secondary);">${fmtInt(item.cils)}</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtM(item.fat)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA;">${fmtM(item.cob)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#34D399;">${fmtM(item.liq)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#F87171;">${fmtM(item.div)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:${cor}; font-weight:800;">${pLiq}%</td>
      </tr>
    `;
  }).join("");

  if (tfootU) {
    const pAllLiq = totAllFat > 0 ? ((totAllLiq / totAllFat) * 100).toFixed(1).replace(".", ",") : "0,0";
    tfootU.innerHTML = `
      <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
        <td>TOTAL REGIÃO SUL</td>
        <td style="text-align:right;">${fmtInt(totAllQtd)}</td>
        <td style="text-align:right; color:var(--text-secondary);">${fmtInt(totAllCils)}</td>
        <td style="text-align:right;">${fmtM(totAllFat)}</td>
        <td style="text-align:right; color:#60A5FA;">${fmtM(totAllCob)}</td>
        <td style="text-align:right; color:#34D399;">${fmtM(totAllLiq)}</td>
        <td style="text-align:right; color:#F87171;">${fmtM(totAllDiv)}</td>
        <td style="text-align:right; color:#34D399;">${pAllLiq}%</td>
      </tr>
    `;
  }
}

function renderizarMatrizComparativaUnidadesGold(mapa, ucAtual = "TODAS") {
  const tbody = document.getElementById("g-tbody-comparativo-uc");
  const tfoot = document.getElementById("g-tfoot-comparativo-uc");
  if (!tbody) return;

  const ucs = obterListaUnidadesGold(mapa);
  const fatRows = mapa.faturacao_mensal?.rows || [];
  const cobRows = mapa.cobranca_mensal?.rows || [];
  const agingUc = mapa.aging_divida?.rows_por_unidade || [];
  const rx0Rows = mapa.religacao_rx0?.rows_mensal_unidade || [];
  const prepUc = mapa.prepago_analise?.por_unidade || {};
  const top100 = mapa.score_v2_validacao?.fila_brigada_top100 || [];

  const dadosUc = ucs.map(uObj => {
    const u = uObj.desc_uni;
    const f17 = fatRows.filter(r => r.emp === "17" && r.desc_uni === u);
    const kwh17 = f17.reduce((s, r) => s + Number(r.consumo_qtd || 0), 0);
    const fat17 = f17.reduce((s, r) => s + Number(r.valor_ecv || 0), 0);
    const cob17 = cobRows.filter(r => r.emp === "17" && r.desc_uni === u).reduce((s, r) => s + Number(r.valor_ecv || 0), 0);
    const ag = agingUc.filter(r => r.desc_uni === u);
    const divTot = ag.reduce((s, r) => s + Number(r.total_ecv || 0), 0);
    const divPresc = ag.filter(r => r.faixa === "> 5 anos").reduce((s, r) => s + Number(r.total_ecv || 0), 0);
    const divExig = divTot - divPresc;
    const rx = rx0Rows.filter(r => r.desc_uni === u);
    const rxFat = rx.reduce((s, r) => s + Number(r.faturado_ecv || 0), 0);
    const rxLiq = rx.reduce((s, r) => s + Number(r.liquidado_ecv || 0), 0);
    const pp = prepUc[u]?.resumo || {};
    const alvos = top100.filter(r => r.desc_uni === u).length;
    return {
      desc_uni: u, ilha: uObj.ilha,
      kwh17, fat17, cob17, divExig, rxFat, rxLiq,
      ppMed: Number(pp.total_medidores || 0),
      ppEcv: Number(pp.total_m_ecv || 0) * 1e6,
      alvos
    };
  }).sort((a, b) => b.fat17 - a.fat17);

  let sKwh = 0, sFat = 0, sCob = 0, sDiv = 0, sRxFat = 0, sRxLiq = 0, sPpMed = 0, sPpEcv = 0, sAlvos = 0;

  tbody.innerHTML = dadosUc.map(d => {
    const ativa = d.desc_uni === ucAtual;
    const taxaNum = d.fat17 > 0 ? (d.cob17 / d.fat17) * 100 : 0;
    const taxa = taxaNum.toFixed(1).replace(".", ",");
    const corTaxa = taxaNum >= 90 ? "#34D399" : taxaNum >= 75 ? "#FBBF24" : "#F87171";
    const rxPct = d.rxFat > 0 ? ((d.rxLiq / d.rxFat) * 100).toFixed(0) : "0";

    sKwh += d.kwh17; sFat += d.fat17; sCob += d.cob17; sDiv += d.divExig;
    sRxFat += d.rxFat; sRxLiq += d.rxLiq; sPpMed += d.ppMed; sPpEcv += d.ppEcv; sAlvos += d.alvos;

    return `
      <tr style="cursor:pointer; ${ativa ? "background:rgba(251,191,36,0.14); font-weight:700;" : ""}" onclick="selecionarUnidadeGold('${d.desc_uni.replace(/'/g, "\\'")}')" title="Clicar para filtrar toda a Visão Executiva por ${d.desc_uni}">
        <td style="font-family:var(--font-mono); font-weight:700; color:${ativa ? "#FBBF24" : "#60A5FA"}; white-space:nowrap;">
          ${ativa ? "▶ " : ""}${d.desc_uni} <span style="color:var(--text-muted); font-size:10px; font-weight:400;">(${d.ilha})</span>
        </td>
        <td style="text-align:right; font-family:var(--font-mono);">${(d.kwh17 / 1e6).toFixed(2).replace(".", ",")}</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtM(d.fat17)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${fmtM(d.cob17)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:${corTaxa}; font-weight:800;">${taxa}%</td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtM(d.divExig)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#A78BFA;">${d.rxFat > 0 ? `${fmtM(d.rxFat)} (${rxPct}%)` : "—"}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#34D399;">${d.ppMed > 0 ? `${fmtInt(d.ppMed)} (${fmtM(d.ppEcv)})` : "—"}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:${d.alvos > 0 ? "#F87171" : "var(--text-muted)"}; font-weight:700;">${d.alvos}</td>
      </tr>
    `;
  }).join("");

  if (tfoot) {
    const tTaxa = sFat > 0 ? ((sCob / sFat) * 100).toFixed(1).replace(".", ",") : "0,0";
    const tRxPct = sRxFat > 0 ? ((sRxLiq / sRxFat) * 100).toFixed(0) : "0";
    tfoot.innerHTML = `
      <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
        <td>TOTAL REGIÃO SUL (10 UCs)</td>
        <td style="text-align:right;">${(sKwh / 1e6).toFixed(2).replace(".", ",")}</td>
        <td style="text-align:right;">${fmtM(sFat)}</td>
        <td style="text-align:right; color:#60A5FA;">${fmtM(sCob)}</td>
        <td style="text-align:right; color:#34D399;">${tTaxa}%</td>
        <td style="text-align:right;">${fmtM(sDiv)}</td>
        <td style="text-align:right; color:#A78BFA;">${fmtM(sRxFat)} (${tRxPct}%)</td>
        <td style="text-align:right; color:#34D399;">${fmtInt(sPpMed)} (${fmtM(sPpEcv)})</td>
        <td style="text-align:right; color:#F87171;">${sAlvos}</td>
      </tr>
    `;
  }
}

function renderizarAdSGold(ads, uc = "TODAS") {
  const tbody = document.getElementById("g-tbody-ads");
  const tfoot = document.getElementById("g-tfoot-ads");
  const agingBox = document.getElementById("g-ads-aging-pills");
  const resumoBadge = document.getElementById("g-ads-resumo-badge");

  const ativaAdS = !uc || uc === "TODAS" || uc === "Praia";

  if (resumoBadge) {
    resumoBadge.innerHTML = ativaAdS
      ? `Dívida Aberta: <strong style="color:#FBBF24;">${fmtM(ads.saldo_divida_ecv)} ECV</strong> • PM: <strong>${Number(ads.preco_medio_m3 || 0).toFixed(2).replace(".", ",")} ECV/m³</strong>`
      : `Contrato AdS pertence à <strong>Unidade Comercial Praia</strong>`;
  }

  if (tbody) {
    const serie = ativaAdS ? (ads.serie_mensal || []) : [];
    const nomesMes = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
    const fmtMesAdS = (lote) => {
      const ano = Number(String(lote).slice(0, 4));
      const mes = Number(String(lote).slice(4, 6));
      const d = new Date(ano, mes - 2, 1);
      return `${nomesMes[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`;
    };
    const maxVal = Math.max(1, ...serie.map(r => Number(r.valor_ecv || 0)));

    if (!serie.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:12px; color:var(--text-muted);">${ativaAdS ? "Sem registos AdS." : `Sem contratos AdS na Unidade ${uc} (exclusivo UC Praia).`}</td></tr>`;
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
    const ag = ativaAdS ? (ads.aging || []) : [];
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

function renderizarOperacionalDQGold(op, uc = "TODAS") {
  const ceaBox = document.getElementById("g-cea-os-box");
  const dqBox = document.getElementById("g-dq-box");
  const ehTodas = !uc || uc === "TODAS";
  if (ceaBox) {
    const anos = (!ehTodas && op.cea_por_unidade && op.cea_por_unidade[uc])
      ? op.cea_por_unidade[uc]
      : (op.cea_por_ano || []);
    const osr = (!ehTodas && op.os_por_unidade && op.os_por_unidade[uc])
      ? op.os_por_unidade[uc]
      : (op.os_resumo || { total: 0, executadas: 0, sla_medio_dias: 0, sla_mediana_dias: 0 });
    ceaBox.innerHTML = `
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
        <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:6px; padding:10px 12px;">
          <div style="font-size:10.5px; color:var(--text-muted); font-family:var(--font-mono);">ORDENS DE SERVIÇO (${ehTodas ? "SUL" : uc.toUpperCase()})</div>
          <div style="font-size:18px; font-weight:800; font-family:var(--font-display); margin-top:2px;">${fmtInt(osr.total)} OS</div>
          <div style="font-size:11px; color:var(--text-secondary);">Executadas: ${fmtInt(osr.executadas)} • SLA médio: <strong>${osr.sla_medio_dias ?? 0}d</strong> (mediana ${osr.sla_mediana_dias ?? 0}d)</div>
        </div>
        <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:6px; padding:10px 12px;">
          <div style="font-size:10.5px; color:var(--text-muted); font-family:var(--font-mono);">HISTÓRICO INSPEÇÕES CEA (${ehTodas ? "SUL" : uc.toUpperCase()})</div>
          <div style="font-size:18px; font-weight:800; font-family:var(--font-display); margin-top:2px;">${fmtInt(anos.reduce((s, a) => s + a.total, 0))} insp.</div>
          <div style="font-size:11px; color:var(--text-secondary);">Base calibrada no Score v2 (AUC 0.901)</div>
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
    alert("Nenhum alvo disponível para o filtro atual.");
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
  const sufixoUc = (window._goldUnidadeAtual && window._goldUnidadeAtual !== "TODAS") ? `_${window._goldUnidadeAtual.replace(/\s+/g, "_")}` : "";
  salvarOuBaixarCSV(`EDEC_Brigadas_ScoreV2_Top100${sufixoUc}_${new Date().toISOString().slice(0, 10)}.csv`, "\uFEFF" + linhas.join("\r\n"));
}

function renderizarScoreV2Gold(sv2, uc = "TODAS") {
  const badgesEl = document.getElementById("g-scorev2-badges");
  const tbodyDecis = document.getElementById("g-tbody-decis");
  const tbodyTop = document.getElementById("g-tbody-top100");
  if (!sv2 || !sv2.auc_teste_out_of_time) return;

  const ehTodas = !uc || uc === "TODAS";
  const allTop = sv2.fila_brigada_top100 || [];
  const top = ehTodas ? allTop : allTop.filter(r => r.desc_uni === uc);
  window._scoreV2Top100 = top;

  if (badgesEl) {
    const top10 = sv2.cortes?.top_10pct || {};
    badgesEl.innerHTML = `
      <span class="badge badge-ok" style="font-family:var(--font-mono);">AUC Out-of-Time: ${sv2.auc_teste_out_of_time}</span>
      <span class="badge" style="background:rgba(96,165,250,0.14); color:#60A5FA; border:1px solid rgba(96,165,250,0.35); font-family:var(--font-mono);">
        Top 10%: ${top10.precision_pct || 0}% acerto (Lift ${top10.lift || 1}x vs base ${sv2.taxa_fraude_base_teste_pct}%)
      </span>
      <span class="badge" style="background:rgba(248,113,113,0.14); color:#F87171; border:1px solid rgba(248,113,113,0.35); font-family:var(--font-mono);">
        Alvos (${ehTodas ? "Sul" : uc}): ${top.length}
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
    if (!top.length) {
      tbodyTop.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:14px; color:var(--text-muted);">Sem alvos no Top 100 regional para a Unidade ${uc}.</td></tr>`;
    } else {
      tbodyTop.innerHTML = top.map(r => `
        <tr style="cursor:pointer;" onclick="if(typeof abrirDossiePorCIL==='function') abrirDossiePorCIL(${r.cil})">
          <td style="font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${r.cil}</td>
          <td style="max-width:170px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${r.nome || "--"}</td>
          <td style="font-family:var(--font-mono); font-size:11px;">${r.pt} <span style="color:var(--text-muted); font-size:10px;">(${r.desc_uni || ""})</span></td>
          <td style="text-align:right; font-family:var(--font-mono); font-weight:800; color:#F87171;">${r.prob_fraude_pct}%</td>
          <td style="text-align:right; font-family:var(--font-mono);">${fmtM(r.divida_exigivel_ecv)}</td>
          <td style="font-size:11px; color:var(--text-secondary);">${r.motivos_v2}</td>
        </tr>
      `).join("");
    }
  }
}

function renderizarPrepagoGold(prep, kpis = {}, uc = "TODAS") {
  const box = document.getElementById("g-prepago-resumo-box");
  const tbody = document.getElementById("g-tbody-prepago-pts");
  const pr = prep?.resumo;
  if (!box || !pr) return;

  const emPoligono = pr.em_poligono !== undefined
    ? Number(pr.em_poligono || 0)
    : (prep.medidores || []).filter(m => m.pt_origem === "Polígono Exato").length;
  const recTotal17 = Number(kpis.fat_17_ecv || 0) + Number(pr.total_m_ecv || 0) * 1e6;

  box.innerHTML = `
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-family:var(--font-mono); font-size:11px;">
      <div style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); border-radius:4px; padding:8px 10px;">
        <div style="color:var(--text-muted); font-size:9.5px;">MEDIDORES ATIVOS (${!uc || uc === "TODAS" ? "SUL" : uc.toUpperCase()})</div>
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
    if (!topPts.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:12px; color:var(--text-muted);">Sem medidores Pré-Pago associados a PTs na Unidade ${uc}.</td></tr>`;
    } else {
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
}
