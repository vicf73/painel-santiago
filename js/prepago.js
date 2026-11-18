// =========================================================================
// MÓDULO 4: PRÉ-PAGAMENTO — MEDIDORES, TRANSAÇÕES TOKEN & RISCO GEOGRÁFICO
// =========================================================================
let PREPAGO_DADOS = null;
let PREPAGO_FILTRADOS = [];
let prepagoPaginaAtual = 1;
const PREPAGO_PAGE_SIZE = 150;
let mapMod4 = null;
let layerPrepagoSat = null;
let layerPrepagoRuas = null;
let layerPrepagoPontos = null;
let usandoPrepagoRuas = false;

async function carregarDadosPrepago(forcar = false) {
  if (!PREPAGO_DADOS || forcar) {
    try {
      const resp = await fetch(
        `${SUPABASE_URL}/rest/v1/santiago_marts_gold?chave=eq.prepago_analise&select=dados`,
        { headers: HEADERS }
      );
      if (resp.ok) {
        const rows = await resp.json();
        if (rows.length && rows[0].dados?.resumo) {
          PREPAGO_DADOS = rows[0].dados;
        }
      }
    } catch (err) {
      console.error("Erro ao carregar Pré-Pagamento:", err);
    }
  }
  if (!PREPAGO_DADOS) return;

  popularFiltrosPrepago();
  iniciarMapaPrepago();
  renderizarGraficoMensalPrepago();
  renderizarCanaisFaixasPrepago();
  renderizarRankingPTsPrepago();
  aplicarFiltrosPrepago();
}

function atualizarKPIsPrepago() {
  if (!PREPAGO_DADOS) return;
  const r = PREPAGO_DADOS.resumo || {};
  const meds = PREPAGO_FILTRADOS;
  const total = meds.length;
  const comGeo = meds.filter(m => m.lat !== null && m.lon !== null).length;
  const totKwh = meds.reduce((s, m) => s + Number(m.total_kwh || 0), 0);
  const totEcv = meds.reduce((s, m) => s + Number(m.total_ecv || 0), 0);
  const sem30 = meds.filter(m => m.dias_sem_compra > 30).length;
  const sem60 = meds.filter(m => m.dias_sem_compra > 60).length;
  const sem90 = meds.filter(m => m.dias_sem_compra > 90).length;
  const desvio50 = meds.filter(m => m.kwh_mes_hist >= 15 && m.desvio_pct !== null && m.desvio_pct <= -50).length;
  const valBaixo = meds.filter(m => m.qtd_compras > 0 && (m.kwh_mes_recente < 15 || (m.ticket_medio_ecv < 500 && m.qtd_compras >= 3))).length;

  const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  setTxt("p4-kpi-medidores", total.toLocaleString("pt-PT"));
  const pctGeo = total > 0 ? ((comGeo / total) * 100).toFixed(1) : "0.0";
  setTxt("p4-kpi-medidores-sub", `${comGeo.toLocaleString("pt-PT")} c/ GPS (${pctGeo}%) • até ${r.dt_max || "--"}`);

  const mwh = totKwh / 1000.0;
  const mecv = totEcv / 1e6;
  const pm = totKwh > 0 ? (totEcv / totKwh) : 0;
  setTxt("p4-kpi-vendas", `${mwh.toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MWh`);
  setTxt("p4-kpi-vendas-sub", `${mecv.toLocaleString("pt-PT", { maximumFractionDigits: 1 })}M ECV • PM: ${pm.toFixed(2)} ECV/kWh`);

  setTxt("p4-kpi-semcompra", sem60.toLocaleString("pt-PT"));
  setTxt("p4-kpi-semcompra-sub", `>30d: ${sem30.toLocaleString("pt-PT")} • >90d: ${sem90.toLocaleString("pt-PT")}`);

  setTxt("p4-kpi-desvio", desvio50.toLocaleString("pt-PT"));
  setTxt("p4-kpi-desvio-sub", `Queda >= 50% (últ. 60d vs hist.)`);

  setTxt("p4-kpi-valorbaixo", valBaixo.toLocaleString("pt-PT"));
  setTxt("p4-kpi-valorbaixo-sub", `< 15 kWh/mês ou ticket < 500 ECV`);
}

function popularFiltrosPrepago() {
  if (!PREPAGO_DADOS) return;
  const meds = PREPAGO_DADOS.medidores || [];

  const fillSel = (id, vals, placeholder) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const atual = sel.value;
    sel.innerHTML = `<option value="">${placeholder}</option>` + vals.map(v => `<option value="${v}">${v}</option>`).join("");
    if (atual) sel.value = atual;
  };

  const unis = [...new Set(meds.map(m => m.desc_uni).filter(Boolean))].sort();
  const locs = [...new Set(meds.map(m => m.localidade).filter(Boolean))].sort();
  const pts = [...new Set(meds.map(m => m.pt).filter(p => p && p !== "Sem PT"))].sort();

  fillSel("p4-filtro-uni", unis, "Todas Unidades");
  fillSel("p4-filtro-localidade", locs, "Todas Localidades");
  fillSel("p4-filtro-pt", pts, "Todos os PTs");
}

function corRiscoPrepago(risco) {
  if (risco === "critico") return "#E15759";
  if (risco === "alerta") return "#F28E2B";
  if (risco === "desvio") return "#60A5FA";
  return "#34D399";
}

function labelRiscoPrepago(risco) {
  if (risco === "critico") return "CRÍTICO (BYPASS)";
  if (risco === "alerta") return "ALERTA (VALOR BAIXO)";
  if (risco === "desvio") return "DESVIO MODERADO";
  return "NORMAL";
}

function iniciarMapaPrepago() {
  const box = document.getElementById("map-mod4-prepago");
  if (!box || typeof L === "undefined") return;
  if (!mapMod4) {
    mapMod4 = L.map("map-mod4-prepago", { zoomControl: true }).setView([15.05, -23.60], 11);
    layerPrepagoSat = L.tileLayer("https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}", { maxZoom: 20, attribution: "Google Satellite Hybrid" });
    layerPrepagoRuas = L.tileLayer("https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}", { maxZoom: 20, attribution: "Google Maps" });
    layerPrepagoSat.addTo(mapMod4);
    layerPrepagoPontos = L.featureGroup().addTo(mapMod4);
  }
  setTimeout(() => mapMod4.invalidateSize(), 80);
}

function alternarCamadaMapaPrepago() {
  if (!mapMod4) return;
  usandoPrepagoRuas = !usandoPrepagoRuas;
  if (usandoPrepagoRuas) {
    mapMod4.removeLayer(layerPrepagoSat);
    layerPrepagoRuas.addTo(mapMod4);
  } else {
    mapMod4.removeLayer(layerPrepagoRuas);
    layerPrepagoSat.addTo(mapMod4);
  }
}

function centrarMapaPrepago() {
  if (!mapMod4 || !layerPrepagoPontos) return;
  const b = layerPrepagoPontos.getBounds();
  if (b && b.isValid()) mapMod4.fitBounds(b, { padding: [24, 24], maxZoom: 15 });
}

function aplicarFiltrosPrepago() {
  if (!PREPAGO_DADOS) return;
  const fRisco = document.getElementById("p4-filtro-risco")?.value || "";
  const fRegra = document.getElementById("p4-filtro-regra")?.value || "";
  const fUni = document.getElementById("p4-filtro-uni")?.value || "";
  const fLoc = document.getElementById("p4-filtro-localidade")?.value || "";
  const fPT = document.getElementById("p4-filtro-pt")?.value || "";
  const fMod = document.getElementById("p4-filtro-modelo")?.value || "";
  const fBusca = (document.getElementById("p4-filtro-busca")?.value || "").trim().toLowerCase();

  PREPAGO_FILTRADOS = (PREPAGO_DADOS.medidores || []).filter(m => {
    if (fRisco === "sem_60d" && !(m.dias_sem_compra > 60)) return false;
    else if (fRisco && fRisco !== "sem_60d" && m.risco !== fRisco) return false;
    if (fRegra === "desvio_50" && !(m.kwh_mes_hist >= 15 && m.desvio_pct !== null && m.desvio_pct <= -50)) return false;
    if (fRegra === "lt_15kwh" && !(m.qtd_compras > 0 && m.kwh_mes_recente < 15)) return false;
    if (fRegra === "sem_3m" && !(m.dias_sem_compra > 90)) return false;
    if (fUni && m.desc_uni !== fUni) return false;
    if (fLoc && m.localidade !== fLoc) return false;
    if (fPT && m.pt !== fPT) return false;
    if (fMod && !(m.modelo || "").toUpperCase().includes(fMod)) return false;
    if (fBusca) {
      const alvo = `${m.medidor} ${m.nome} ${m.pt} ${m.localidade} ${m.desc_uni || ""}`.toLowerCase();
      if (!alvo.includes(fBusca)) return false;
    }
    return true;
  });

  prepagoPaginaAtual = 1;
  atualizarKPIsPrepago();
  renderizarDonutRiscoPrepago();
  renderizarPontosMapaPrepago();
  renderizarTabelaPrepago();
}

function mudarPaginaPrepago(novaPag) {
  const totalPags = Math.max(1, Math.ceil(PREPAGO_FILTRADOS.length / PREPAGO_PAGE_SIZE));
  prepagoPaginaAtual = Math.min(totalPags, Math.max(1, novaPag));
  renderizarTabelaPrepago();
}

function limparFiltrosPrepago() {
  ["p4-filtro-risco", "p4-filtro-regra", "p4-filtro-uni", "p4-filtro-localidade", "p4-filtro-pt", "p4-filtro-modelo", "p4-filtro-busca"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  aplicarFiltrosPrepago();
}

function renderizarPontosMapaPrepago() {
  if (!mapMod4 || !layerPrepagoPontos) return;
  layerPrepagoPontos.clearLayers();
  const comGeo = PREPAGO_FILTRADOS.filter(m => m.lat !== null && m.lon !== null).slice(0, 600);
  comGeo.forEach(m => {
    const cor = corRiscoPrepago(m.risco);
    const marker = L.circleMarker([m.lat, m.lon], {
      radius: m.risco === "critico" ? 6 : 4.5,
      color: cor,
      weight: 1.5,
      fillColor: cor,
      fillOpacity: 0.78,
    });
    const desvioTxt = m.desvio_pct !== null ? `${m.desvio_pct > 0 ? "+" : ""}${m.desvio_pct}%` : "--";
    marker.bindTooltip(
      `<b>${m.medidor}</b> • ${m.nome}<br>PT: <b>${m.pt}</b> (${m.localidade})<br>Estado: <b>${labelRiscoPrepago(m.risco)}</b><br>Dias s/ compra: <b>${m.dias_sem_compra}d</b> | Desvio: <b>${desvioTxt}</b>`
    );
    marker.addTo(layerPrepagoPontos);
  });
  centrarMapaPrepago();
}

function renderizarRankingPTsPrepago() {
  const box = document.getElementById("p4-ranking-pts");
  if (!box || !PREPAGO_DADOS) return;
  const pts = (PREPAGO_DADOS.ranking_pts || []).slice(0, 10);
  box.innerHTML = pts.map((p, i) => `
    <div class="rank-item" onclick="filtrarPTPrepago('${p.pt}')" style="border-left:3.5px solid #E15759; cursor:pointer;">
      <div class="rank-top">
        <span><b>#${i + 1}</b> ${p.pt}</span>
        <span style="color:#F87171; font-weight:700;">${p.criticos} críticos / ${p.total_med} med.</span>
      </div>
      <div class="rank-metrics">
        <span>${p.localidade || "--"}</span>
        <span style="font-family:var(--font-mono);">>60d s/ compra: ${p.sem_60d} | ${p.m_ecv.toFixed(1)}M ECV</span>
      </div>
    </div>
  `).join("");
}

function filtrarPTPrepago(pt) {
  const sel = document.getElementById("p4-filtro-pt");
  if (sel) {
    sel.value = (sel.value === pt) ? "" : pt;
    aplicarFiltrosPrepago();
  }
}

function renderizarGraficoMensalPrepago() {
  const box = document.getElementById("p4-chart-mensal");
  if (!box || !PREPAGO_DADOS) return;
  const serie = PREPAGO_DADOS.serie_mensal || [];
  if (!serie.length) { box.innerHTML = ""; return; }
  const mesesPt = { "01":"Jan","02":"Fev","03":"Mar","04":"Abr","05":"Mai","06":"Jun","07":"Jul","08":"Ago","09":"Set","10":"Out","11":"Nov","12":"Dez" };
  const w = 520, h = 225, padL = 42, padR = 42, padT = 20, padB = 28;
  const maxEcv = Math.max(10, ...serie.map(s => s.m_ecv)) * 1.18;
  const maxMwh = Math.max(100, ...serie.map(s => s.mwh)) * 1.18;
  const bw = (w - padL - padR) / serie.length;
  const syE = v => h - padB - (v / maxEcv) * (h - padT - padB);
  const syM = v => h - padB - (v / maxMwh) * (h - padT - padB);

  const grid = [0.25, 0.5, 0.75, 1.0].map(f => {
    const y = syE(maxEcv * f).toFixed(1);
    return `<line x1="${padL}" y1="${y}" x2="${w - padR}" y2="${y}" stroke="var(--border-dim)" stroke-dasharray="3 3" stroke-opacity="0.65" />
            <text x="${padL - 5}" y="${Number(y) + 3}" text-anchor="end" fill="var(--text-muted)" font-size="8">${(maxEcv * f).toFixed(0)}M</text>`;
  }).join("");

  const bars = serie.map((s, idx) => {
    const x = padL + idx * bw + bw * 0.2;
    const y = syE(s.m_ecv);
    const bh = (h - padB) - y;
    const lbl = mesesPt[s.ano_mes.slice(5)] || s.ano_mes.slice(5);
    return `
      <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw * 0.6).toFixed(1)}" height="${bh.toFixed(1)}" rx="3" fill="url(#p4BarGrad)">
        <title>${s.ano_mes}: ${s.m_ecv.toFixed(2)}M ECV | ${s.mwh.toFixed(1)} MWh | ${s.compras.toLocaleString("pt-PT")} compras | ${s.medidores_ativos.toLocaleString("pt-PT")} medidores</title>
      </rect>
      <text x="${(x + bw * 0.3).toFixed(1)}" y="${(y - 4).toFixed(1)}" text-anchor="middle" fill="#60A5FA" font-size="7.8" font-weight="700">${s.m_ecv.toFixed(1)}</text>
      <text x="${(x + bw * 0.3).toFixed(1)}" y="${h - 10}" text-anchor="middle" fill="var(--text-muted)" font-size="8.5">${lbl}</text>
    `;
  }).join("");

  const ptsLinha = serie.map((s, idx) => {
    const cx = (padL + idx * bw + bw * 0.5).toFixed(1);
    const cy = syM(s.mwh).toFixed(1);
    return `${cx},${cy}`;
  }).join(" ");

  const dots = serie.map((s, idx) => {
    const cx = (padL + idx * bw + bw * 0.5).toFixed(1);
    const cy = syM(s.mwh).toFixed(1);
    return `<circle cx="${cx}" cy="${cy}" r="3.2" fill="#FBBF24" stroke="#0F172A" stroke-width="1"><title>${s.ano_mes}: ${s.mwh.toFixed(1)} MWh</title></circle>`;
  }).join("");

  box.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" style="width:100%; height:100%; display:block; font-family:var(--font-mono);">
      <defs>
        <linearGradient id="p4BarGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#60A5FA" stop-opacity="0.95"/>
          <stop offset="100%" stop-color="#2563EB" stop-opacity="0.55"/>
        </linearGradient>
      </defs>
      ${grid}
      <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="var(--border-dim)" />
      ${bars}
      <polyline fill="none" stroke="#FBBF24" stroke-width="2" points="${ptsLinha}" />
      ${dots}
      <text x="${w - padR + 5}" y="${syM(maxMwh * 0.9) + 3}" fill="#FBBF24" font-size="8">${Math.round(maxMwh * 0.9)}</text>
      <text x="${w - padR + 5}" y="${syM(maxMwh * 0.45) + 3}" fill="#FBBF24" font-size="8">${Math.round(maxMwh * 0.45)}</text>
    </svg>
  `;
}

function renderizarDonutRiscoPrepago() {
  const box = document.getElementById("p4-chart-donut-risco");
  if (!box) return;
  const meds = PREPAGO_FILTRADOS;
  const total = meds.length || 1;
  const grupos = [
    { key: "critico", label: "Crítico (Bypass)", cor: "#E15759", qtd: meds.filter(m => m.risco === "critico").length },
    { key: "alerta", label: "Alerta (V. Baixo)", cor: "#F28E2B", qtd: meds.filter(m => m.risco === "alerta").length },
    { key: "desvio", label: "Desvio (-30..-59%)", cor: "#60A5FA", qtd: meds.filter(m => m.risco === "desvio").length },
    { key: "normal", label: "Normal", cor: "#34D399", qtd: meds.filter(m => m.risco === "normal").length },
  ];

  const r = 52, cx = 74, cy = 105, circ = 2 * Math.PI * r;
  let offset = 0;
  const arcs = grupos.map(g => {
    const frac = g.qtd / total;
    const len = frac * circ;
    const dash = `${len.toFixed(2)} ${(circ - len).toFixed(2)}`;
    const seg = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="transparent" stroke="${g.cor}" stroke-width="20" stroke-dasharray="${dash}" stroke-dashoffset="${(-offset).toFixed(2)}" style="cursor:pointer;" onclick="document.getElementById('p4-filtro-risco').value='${g.key}'; aplicarFiltrosPrepago();"><title>${g.label}: ${g.qtd.toLocaleString("pt-PT")} (${(frac * 100).toFixed(1)}%)</title></circle>`;
    offset += len;
    return seg;
  }).join("");

  const pctRisco = (((grupos[0].qtd + grupos[1].qtd) / total) * 100).toFixed(1);
  const legenda = grupos.map(g => {
    const pct = ((g.qtd / total) * 100).toFixed(1);
    return `
      <div onclick="document.getElementById('p4-filtro-risco').value='${g.key}'; aplicarFiltrosPrepago();" style="display:flex; justify-content:space-between; align-items:center; padding:5px 6px; border-radius:4px; cursor:pointer; border-bottom:1px solid var(--border-dim);">
        <span style="display:flex; align-items:center; gap:6px; font-size:10.5px;">
          <span style="width:9px; height:9px; border-radius:2px; background:${g.cor}; display:inline-block;"></span>
          ${g.label}
        </span>
        <span style="font-family:var(--font-mono); font-size:10.5px; font-weight:700;">${g.qtd.toLocaleString("pt-PT")} <span style="color:var(--text-muted); font-weight:400;">(${pct}%)</span></span>
      </div>
    `;
  }).join("");

  box.innerHTML = `
    <div style="display:grid; grid-template-columns:150px 1fr; gap:8px; align-items:center; height:100%;">
      <svg viewBox="0 0 150 210" style="width:100%; height:100%;">
        <g transform="rotate(-90 ${cx} ${cy})">${arcs}</g>
        <text x="${cx}" y="${cy - 2}" text-anchor="middle" fill="var(--text-primary)" font-family="var(--font-mono)" font-size="16" font-weight="800">${pctRisco}%</text>
        <text x="${cx}" y="${cy + 14}" text-anchor="middle" fill="var(--text-muted)" font-family="var(--font-mono)" font-size="8.5">Crít.+Alerta</text>
      </svg>
      <div style="display:flex; flex-direction:column; gap:4px;">${legenda}</div>
    </div>
  `;
}

function renderizarCanaisFaixasPrepago() {
  const box = document.getElementById("p4-canais-faixas");
  if (!box || !PREPAGO_DADOS) return;
  const faixas = PREPAGO_DADOS.faixas_recarga || [];
  const canais = (PREPAGO_DADOS.canais || []).slice(0, 4);
  const maxF = Math.max(1, ...faixas.map(f => f.compras));
  const maxC = Math.max(1, ...canais.map(c => c.m_ecv));
  const coresF = ["#E15759", "#F28E2B", "#60A5FA", "#34D399"];

  box.innerHTML = `
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px; font-family:var(--font-mono); font-size:10.5px;">
      <div>
        <div style="font-weight:700; color:var(--text-secondary); margin-bottom:6px;">FAIXAS DE RECARGA</div>
        ${faixas.map((f, i) => {
          const w = ((f.compras / maxF) * 100).toFixed(1);
          const cor = coresF[i % coresF.length];
          return `<div style="margin-bottom:7px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span>${f.faixa}</span><span><b>${f.compras.toLocaleString("pt-PT")}</b> (${f.m_ecv.toFixed(0)}M)</span></div>
            <div style="height:6px; background:var(--bg-panel-elevated); border-radius:3px; overflow:hidden;"><div style="width:${w}%; height:100%; background:${cor};"></div></div>
          </div>`;
        }).join("")}
      </div>
      <div>
        <div style="font-weight:700; color:var(--text-secondary); margin-bottom:6px;">TOP CANAIS (M ECV)</div>
        ${canais.map(c => {
          const w = ((c.m_ecv / maxC) * 100).toFixed(1);
          return `<div style="margin-bottom:7px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span>${c.canal}</span><span><b>${c.m_ecv.toFixed(1)}M</b> (${c.compras.toLocaleString("pt-PT")})</span></div>
            <div style="height:6px; background:var(--bg-panel-elevated); border-radius:3px; overflow:hidden;"><div style="width:${w}%; height:100%; background:#60A5FA;"></div></div>
          </div>`;
        }).join("")}
      </div>
    </div>
  `;
}

function _linhaMedidorPrepagoHTML(m) {
  const cor = corRiscoPrepago(m.risco);
  const desvioTxt = m.desvio_pct !== null ? `${m.desvio_pct > 0 ? "+" : ""}${m.desvio_pct.toFixed(1)}%` : "—";
  const corDesv = (m.desvio_pct !== null && m.desvio_pct <= -50) ? "#F87171" : "var(--text-secondary)";
  return `
    <tr>
      <td style="font-family:var(--font-mono); font-weight:700; color:#60A5FA;">${m.medidor}</td>
      <td style="font-size:11px; max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${m.nome}">${m.nome || "--"}</td>
      <td style="font-size:11px; color:var(--text-secondary); white-space:nowrap;">${m.desc_uni || "--"}</td>
      <td style="font-family:var(--font-mono); font-size:11px;">${m.pt}</td>
      <td style="font-size:11px; color:var(--text-secondary);">${m.localidade || "--"}</td>
      <td style="font-family:var(--font-mono); font-size:10.5px;">${m.modelo || "--"}</td>
      <td style="font-family:var(--font-mono); text-align:center;">${m.dt_ultima || "Sem compra"}</td>
      <td style="font-family:var(--font-mono); text-align:right; font-weight:700; color:${m.dias_sem_compra > 60 ? "#F87171" : "var(--text-primary)"};">${m.dias_sem_compra}d</td>
      <td style="font-family:var(--font-mono); text-align:right;">${m.kwh_mes_hist.toFixed(1)}</td>
      <td style="font-family:var(--font-mono); text-align:right;">${m.kwh_mes_recente.toFixed(1)}</td>
      <td style="font-family:var(--font-mono); text-align:right; font-weight:700; color:${corDesv};">${desvioTxt}</td>
      <td style="text-align:center;"><span class="badge" style="color:${cor}; border:1px solid ${cor}; font-size:9.5px; white-space:nowrap;">${labelRiscoPrepago(m.risco)}</span></td>
    </tr>
  `;
}

function renderizarTabelaPrepago() {
  const tbody = document.getElementById("p4-tbody-medidores");
  const info = document.getElementById("p4-qtd-filtrados");
  const pagBox = document.getElementById("p4-paginacao");
  if (!tbody) return;

  const total = PREPAGO_FILTRADOS.length;
  const totalPags = Math.max(1, Math.ceil(total / PREPAGO_PAGE_SIZE));
  if (prepagoPaginaAtual > totalPags) prepagoPaginaAtual = totalPags;
  const ini = (prepagoPaginaAtual - 1) * PREPAGO_PAGE_SIZE;
  const fim = Math.min(total, ini + PREPAGO_PAGE_SIZE);
  const visiveis = PREPAGO_FILTRADOS.slice(ini, fim);

  if (info) {
    info.textContent = total > 0
      ? `${total.toLocaleString("pt-PT")} medidores (mostrando ${ini + 1}–${fim})`
      : `0 medidores encontrados`;
  }
  if (!visiveis.length) {
    tbody.innerHTML = `<tr><td colspan="12" style="text-align:center; padding:24px; color:var(--text-muted);">Nenhum medidor encontrado com os filtros selecionados.</td></tr>`;
    if (pagBox) pagBox.innerHTML = "";
    return;
  }

  tbody.innerHTML = visiveis.map(_linhaMedidorPrepagoHTML).join("");
  if (pagBox) {
    pagBox.innerHTML = `
      <span style="color:var(--text-muted);">Página <b>${prepagoPaginaAtual}</b> de <b>${totalPags}</b> (${total.toLocaleString("pt-PT")} medidores)</span>
      <div style="display:flex; gap:6px;">
        <button class="btn" onclick="mudarPaginaPrepago(1)" ${prepagoPaginaAtual <= 1 ? "disabled" : ""} style="padding:4px 8px; font-size:11px;">« Primeira</button>
        <button class="btn" onclick="mudarPaginaPrepago(${prepagoPaginaAtual - 1})" ${prepagoPaginaAtual <= 1 ? "disabled" : ""} style="padding:4px 8px; font-size:11px;">‹ Anterior</button>
        <button class="btn" onclick="mudarPaginaPrepago(${prepagoPaginaAtual + 1})" ${prepagoPaginaAtual >= totalPags ? "disabled" : ""} style="padding:4px 8px; font-size:11px;">Próxima ›</button>
        <button class="btn" onclick="mudarPaginaPrepago(${totalPags})" ${prepagoPaginaAtual >= totalPags ? "disabled" : ""} style="padding:4px 8px; font-size:11px;">Última »</button>
      </div>
    `;
  }
}

async function exportarPrepagoCSV(btn) {
  if (!PREPAGO_FILTRADOS.length) {
    if (typeof mostrarToastExportacao === "function") {
      mostrarToastExportacao("⚠️ Nenhum medidor encontrado nos filtros atuais para exportar.", false);
    } else {
      alert("Nenhum medidor encontrado nos filtros atuais para exportar.");
    }
    return;
  }
  const txtOrig = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = `⏳ A exportar ${PREPAGO_FILTRADOS.length.toLocaleString("pt-PT")}...`; }
  try {
    const cols = ["Medidor", "Nome", "Unidade_Com", "PT", "Localidade", "Modelo", "Tarifa", "Ultima_Compra", "Dias_Sem_Compra", "kWh_Mes_Hist", "kWh_Mes_Recente", "Desvio_Pct", "Ticket_Medio_ECV", "Risco", "Lat", "Lon"];
    const esc = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const linhas = PREPAGO_FILTRADOS.map(m => [
      m.medidor, esc(m.nome), esc(m.desc_uni), esc(m.pt), esc(m.localidade), esc(m.modelo), esc(m.tarifa),
      m.dt_ultima || "", m.dias_sem_compra, m.kwh_mes_hist, m.kwh_mes_recente,
      m.desvio_pct ?? "", m.ticket_medio_ecv, m.risco, m.lat ?? "", m.lon ?? ""
    ].join(";"));
    const csv = "\uFEFF" + [cols.join(";"), ...linhas].join("\n");
    await salvarOuBaixarCSV(`EDEC_Prepago_Risco_${PREPAGO_FILTRADOS.length}_med_${new Date().toISOString().slice(0, 10)}.csv`, csv);
  } catch (err) {
    alert("Erro ao exportar CSV Pré-Pagamento: " + err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = txtOrig; }
  }
}
