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

    renderizarKpisGold(mapa.kpis_executivos);
    renderizarSerieFatCobGold(mapa.faturacao_mensal?.rows || [], mapa.cobranca_mensal?.rows || []);
    renderizarAgingGold(mapa.aging_divida?.rows || []);
    renderizarAdSGold(mapa.ads_conta_corrente || {});
    renderizarOperacionalDQGold(mapa.operacional_cea_os || {});

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

function renderizarKpisGold(k) {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  set("g-kpi-fat17", `${fmtM(k.fat_17_ecv)} ECV`);
  set("g-kpi-fat17-sub", `${(Number(k.fat_17_kwh || 0) / 1e6).toFixed(1)} GWh • PM: ${k.fat_17_preco_medio || 0} ECV/kWh`);

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
}

function renderizarSerieFatCobGold(fatRows, cobRows) {
  const tbody = document.getElementById("g-tbody-fat-cob");
  if (!tbody) return;

  // Mapear lote_ym (ex: 202602 = dados de jan/2026 ou mês do lote) para E017
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

  // Cobrança E017 por ano_mes (2026-01 .. 2026-10)
  const cobPorMes = {};
  for (const r of cobRows) {
    if (r.emp !== "17") continue;
    cobPorMes[r.ano_mes] = (cobPorMes[r.ano_mes] || 0) + Number(r.valor_ecv || 0);
  }

  const lotes = Object.keys(porLote).sort();
  if (!lotes.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:16px; color:var(--text-muted);">Sem dados mensais.</td></tr>`;
    return;
  }

  // Lote 202602 corresponde ao mês de atividade 2026-01, ..., 202611 -> 2026-10
  const loteParaMesCob = (lote) => {
    const ano = Number(lote.slice(0, 4));
    const mes = Number(lote.slice(4, 6));
    const d = new Date(ano, mes - 2, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  };

  tbody.innerHTML = lotes.map(lote => {
    const f = porLote[lote];
    const mesCobKey = loteParaMesCob(lote);
    const cob = cobPorMes[mesCobKey] || 0;
    const taxa = f.fat_ecv > 0 ? ((cob / f.fat_ecv) * 100).toFixed(1) : "0.0";
    const pm = f.fat_kwh > 0 ? (f.fat_ecv / f.fat_kwh).toFixed(2) : "0.00";
    const corTaxa = Number(taxa) >= 90 ? "#34D399" : Number(taxa) >= 75 ? "#FBBF24" : "#F87171";
    return `
      <tr>
        <td style="font-family:var(--font-mono); font-weight:700;">${mesCobKey}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${(f.fat_kwh / 1e6).toFixed(2)} GWh</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtM(f.fat_ecv)} ECV</td>
        <td style="text-align:right; font-family:var(--font-mono); color:var(--text-secondary);">${pm}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${fmtM(cob)} ECV</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:800; color:${corTaxa};">${taxa}%</td>
        <td style="text-align:right; font-family:var(--font-mono); font-size:10.5px; color:var(--text-secondary);">EB ${fmtM(f.eb)} • EM ${fmtM(f.em)} • EE ${fmtM(f.ee)}</td>
      </tr>
    `;
  }).join("");
}

function renderizarAgingGold(rows) {
  const tbody = document.getElementById("g-tbody-aging");
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:16px; color:var(--text-muted);">Sem dados de aging.</td></tr>`;
    return;
  }
  const totGeral = rows.reduce((s, r) => s + Number(r.total_ecv || 0), 0);
  tbody.innerHTML = rows.map(r => {
    const pct = totGeral > 0 ? ((Number(r.total_ecv) / totGeral) * 100).toFixed(1) : "0.0";
    const ehPresc = r.faixa === "> 5 anos";
    return `
      <tr style="${ehPresc ? "background:rgba(244,63,94,0.06);" : ""}">
        <td style="font-family:var(--font-mono); font-weight:700;">${r.faixa}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtInt(r.faturas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:800;">${fmtM(r.total_ecv)} ECV <span style="color:var(--text-muted); font-weight:400;">(${pct}%)</span></td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA;">${fmtM(r.emp_17)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#FBBF24;">${fmtM(r.emp_21)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#A78BFA;">${fmtM(r.emp_07)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#F472B6;">${fmtM(r.emp_70)}</td>
      </tr>
    `;
  }).join("");
}

function renderizarAdSGold(ads) {
  const tbody = document.getElementById("g-tbody-ads");
  const agingBox = document.getElementById("g-ads-aging-pills");
  if (tbody) {
    const serie = ads.serie_mensal || [];
    tbody.innerHTML = serie.length ? serie.map(r => `
      <tr>
        <td style="font-family:var(--font-mono); font-weight:700;">${r.lote_ym}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtInt(r.m3)} m³</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700; color:#FBBF24;">${fmtM(r.valor_ecv)} ECV</td>
        <td style="text-align:right; font-family:var(--font-mono);">${r.preco_medio_m3} ECV/m³</td>
      </tr>
    `).join("") : `<tr><td colspan="4" style="text-align:center; padding:12px;">Sem registos AdS.</td></tr>`;
  }
  if (agingBox) {
    const ag = ads.aging || [];
    agingBox.innerHTML = ag.map(a => `
      <span class="badge" style="background:rgba(251,191,36,0.12); color:#FBBF24; border:1px solid rgba(251,191,36,0.35); font-family:var(--font-mono); font-size:10.5px; padding:4px 8px;">
        ${a.faixa}: ${fmtM(a.valor_ecv)} ECV (${a.faturas} fat.)
      </span>
    `).join("");
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
    dqBox.innerHTML = `
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
        <span class="badge ${dq.todos_testes_ok ? "badge-ok" : "badge-crit"}" style="font-family:var(--font-mono);">
          ${dq.todos_testes_ok ? "✔ DATA QUALITY APROVADO" : "✖ FALHA DQ"}
        </span>
        ${testes.map(t => `
          <span class="badge" style="background:var(--bg-panel-elevated); border:1px solid var(--border-dim); font-family:var(--font-mono); font-size:10.5px;">
            ${t.passou ? "✔" : "✖"} ${t.teste} (${t.falhas})
          </span>
        `).join("")}
      </div>
      <div style="font-family:var(--font-mono); font-size:11.5px; color:var(--text-secondary); line-height:1.7;">
        • <strong>Funil Dívida (Bronze → Silver Sul):</strong> Bruto <code>${fmtM(fd.bronze_ecv)} ECV</code> (${fmtInt(fd.bronze_linhas)} fat.)
        − Fora Sul/Inválidos <code>${fmtM(fd.filtrado_fora_sul_ou_invalido_ecv)} ECV</code>
        = Silver Região Sul <strong><code>${fmtM(fd.silver_ecv)} ECV</code></strong> (${fmtInt(fd.silver_linhas)} fat.).
      </div>
    `;
  }
}
