// =========================================================================
// MÓDULO 5: ORDENS DE SERVIÇO & RETORNO DE TESOURARIA (MULTI-FONTE)
// Cruza fct_ordem_servico (66.352 OS) com Cobrança, Dívida, Taxa RX0 e Contratos
// =========================================================================

let os5Carregado = false;
window._os5Dados = null;
window._os5FilaAtiva = "ev_op";

const fmtMoedaOS = (v) => {
  const n = Number(v || 0);
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2).replace(".", ",") + " B";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2).replace(".", ",") + " M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1).replace(".", ",") + " k";
  return Math.round(n).toLocaleString("pt-PT");
};

const fmtIntOS = (v) => Math.round(Number(v || 0)).toLocaleString("pt-PT");

async function carregarDadosOrdensServico(forcar = false) {
  if (os5Carregado && !forcar && window._os5Dados) {
    aplicarFiltrosOrdensServico();
    return;
  }
  const statusEl = document.getElementById("os5-sync-status");
  if (statusEl) statusEl.textContent = "A carregar inteligência de OS...";

  try {
    let dados = (!forcar && window._goldMapa?.ordens_servico_analise?.resumo)
      ? window._goldMapa.ordens_servico_analise
      : null;

    if (!dados) {
      const resp = await fetch(
        `${SUPABASE_URL}/rest/v1/santiago_marts_gold?select=chave,dados,atualizado_em&chave=eq.ordens_servico_analise`,
        { headers: HEADERS }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const rows = await resp.json();
      if (rows.length && rows[0].dados) {
        dados = rows[0].dados;
      }
    }

    if (!dados || !dados.resumo) {
      if (statusEl) statusEl.textContent = "Mart ordens_servico_analise ainda não sincronizado.";
      return;
    }

    window._os5Dados = dados;
    popularFiltrosOrdensServico(dados);
    aplicarFiltrosOrdensServico();

    if (statusEl && dados.gerado_em) {
      const dt = new Date(dados.gerado_em);
      statusEl.textContent = `Sincronizado: ${dt.toLocaleDateString("pt-PT")} ${dt.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}`;
    }
    os5Carregado = true;
  } catch (err) {
    console.error("Erro ao carregar Módulo 5 (Ordens de Serviço):", err);
    if (statusEl) statusEl.textContent = "Erro ao carregar Ordens de Serviço";
  }
}

function popularFiltrosOrdensServico(dados) {
  const selUc = document.getElementById("os5-filtro-uc");
  const selFam = document.getElementById("os5-filtro-familia");
  const selSeg = document.getElementById("os5-filtro-segmento");

  const ucs = (dados.auditoria_por_unidade || []).map(r => r.desc_uni).filter(Boolean);
  if (selUc && selUc.options.length <= 1) {
    selUc.innerHTML = [
      `<option value="TODAS">Todas as Unidades (Região Sul · ${ucs.length || 10})</option>`,
      ...ucs.map(u => `<option value="${u}">${u}</option>`)
    ].join("");
  }

  const fams = Array.from(new Set((dados.familias_rows || []).map(r => r.familia))).sort();
  if (selFam && selFam.options.length <= 1) {
    selFam.innerHTML = [
      `<option value="TODAS">Todas as 7 Macro-Famílias (66.352 OS)</option>`,
      ...fams.map(f => `<option value="${f}">${f}</option>`)
    ].join("");
  }

  const segs = Array.from(new Set((dados.familias_rows || []).map(r => r.segmento))).sort();
  if (selSeg && selSeg.options.length <= 1) {
    selSeg.innerHTML = [
      `<option value="TODOS">Todos os Segmentos de Consumidor</option>`,
      ...segs.map(s => `<option value="${s}">${s}</option>`)
    ].join("");
  }
}

function selecionarUnidadeOS5(uc) {
  const selUc = document.getElementById("os5-filtro-uc");
  if (!selUc) return;
  const novo = (selUc.value === uc && uc !== "TODAS") ? "TODAS" : (uc || "TODAS");
  selUc.value = novo;
  aplicarFiltrosOrdensServico();
}

function limparFiltrosOrdensServico() {
  const selUc = document.getElementById("os5-filtro-uc");
  const selFam = document.getElementById("os5-filtro-familia");
  const selSeg = document.getElementById("os5-filtro-segmento");
  const busca = document.getElementById("os5-busca-fila");
  if (selUc) selUc.value = "TODAS";
  if (selFam) selFam.value = "TODAS";
  if (selSeg) selSeg.value = "TODOS";
  if (busca) busca.value = "";
  aplicarFiltrosOrdensServico();
}

function aplicarFiltrosOrdensServico() {
  const dados = window._os5Dados;
  if (!dados) return;

  const uc = document.getElementById("os5-filtro-uc")?.value || "TODAS";
  const fam = document.getElementById("os5-filtro-familia")?.value || "TODAS";
  const seg = document.getElementById("os5-filtro-segmento")?.value || "TODOS";
  const modoDetalhe = document.getElementById("os5-modo-detalhe")?.value || "DETALHADO";

  const ehTodasUc = uc === "TODAS";
  const ehTodasFam = fam === "TODAS";
  const ehTodosSeg = seg === "TODOS";

  const badge = document.getElementById("os5-context-badge");
  if (badge) {
    const partes = [
      ehTodasUc ? "REGIÃO SUL (10 UCs)" : `UC: ${uc.toUpperCase()}`,
      ehTodasFam ? "7 FAMÍLIAS" : fam.slice(0, 22),
      ehTodosSeg ? "TODOS SEGMENTOS" : seg.toUpperCase()
    ];
    badge.textContent = partes.join(" • ");
  }

  const famRows = (dados.familias_rows || []).filter(r =>
    (ehTodasUc || r.desc_uni === uc) &&
    (ehTodasFam || r.familia === fam) &&
    (ehTodosSeg || r.segmento === seg)
  );

  const retRows = (dados.retorno_tesouraria_rows || []).filter(r =>
    (ehTodasUc || r.desc_uni === uc) &&
    (ehTodosSeg || r.segmento === seg)
  );

  const semRows = (dados.quando_cortar_semana || []).filter(r =>
    (ehTodasUc || r.desc_uni === uc) &&
    (ehTodosSeg || r.segmento === seg)
  );

  const mesRows = (dados.quando_cortar_mes || []).filter(r =>
    (ehTodasUc || r.desc_uni === uc) &&
    (ehTodosSeg || r.segmento === seg)
  );

  const audRows = (dados.auditoria_por_unidade || []).filter(r =>
    ehTodasUc || r.desc_uni === uc
  );

  renderizarKpisOS5(famRows, retRows, audRows, uc);
  renderizarTabelaFamiliasOS5(famRows, modoDetalhe);
  renderizarMatrizTesourariaOS5(retRows);
  renderizarQuandoCortarOS5(semRows, mesRows);
  renderizarAuditoriaUnidadesOS5(dados.auditoria_por_unidade || [], uc);
  renderizarFilaAcaoOS5();
}

function renderizarKpisOS5(famRows, retRows, audRows, uc) {
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };

  const totEmit = famRows.reduce((s, r) => s + r.emitidas, 0);
  const totOr = famRows.reduce((s, r) => s + r.or_realizadas, 0);
  const totOp = famRows.reduce((s, r) => s + r.op_pendentes, 0);
  const totOa = famRows.reduce((s, r) => s + r.oa_anuladas, 0);
  const slaS = famRows.reduce((s, r) => s + r.soma_sla, 0);
  const slaN = famRows.reduce((s, r) => s + r.qtd_sla, 0);
  const slaMed = slaN > 0 ? (slaS / slaN).toFixed(1).replace(".", ",") : "0,0";
  const txExec = totEmit > 0 ? ((totOr / totEmit) * 100).toFixed(1).replace(".", ",") : "0,0";

  const cortesRows = famRows.filter(r => r.familia.startsWith("1."));
  const cEmit = cortesRows.reduce((s, r) => s + r.emitidas, 0);
  const cOr = cortesRows.reduce((s, r) => s + r.or_realizadas, 0);
  const cOp = cortesRows.reduce((s, r) => s + r.op_pendentes, 0);
  const txCorte = cEmit > 0 ? ((cOr / cEmit) * 100).toFixed(1).replace(".", ",") : "0,0";

  const retOr = retRows.filter(r => r.est_os === "OR");
  const retOa = retRows.filter(r => r.est_os === "OA");
  const cxOr30 = retOr.reduce((s, r) => s + r.receita_30d_ecv, 0);
  const cxOa30 = retOa.reduce((s, r) => s + r.receita_30d_ecv, 0);
  const cxTot30 = cxOr30 + cxOa30;

  const qOr = retOr.reduce((s, r) => s + r.qtd_os, 0);
  const pOr30 = retOr.reduce((s, r) => s + r.pagaram_30d, 0);
  const dOrS = retOr.reduce((s, r) => s + r.soma_dias_pag, 0);
  const dOrN = retOr.reduce((s, r) => s + r.qtd_dias_pag, 0);
  const txConvOr = qOr > 0 ? ((pOr30 / qOr) * 100).toFixed(1).replace(".", ",") : "0,0";
  const ttcOr = dOrN > 0 ? (dOrS / dOrN).toFixed(1).replace(".", ",") : "0,0";

  const divOp = audRows.reduce((s, r) => s + r.div_exig_op_ecv, 0);
  const cilsOp = audRows.reduce((s, r) => s + r.cils_op, 0);
  const atosSemRx0 = audRows.reduce((s, r) => s + r.atos_sem_rx0, 0);
  const cilsSemRx0 = audRows.reduce((s, r) => s + r.cils_sem_rx0, 0);
  const perdaRx0 = audRows.reduce((s, r) => s + r.perda_estimada_rx0_ecv, 0);
  const cilsAuto = audRows.reduce((s, r) => s + r.cils_autoconexao, 0);
  const divAuto = audRows.reduce((s, r) => s + r.div_autoconexao_ecv, 0);
  const novOr = audRows.reduce((s, r) => s + r.novas_lig_or, 0);
  const novFila = audRows.reduce((s, r) => s + r.novas_lig_fila, 0);

  set("os5-kpi-total", `${fmtIntOS(totEmit)} OS`);
  set("os5-kpi-total-sub", `Realizadas OR: ${fmtIntOS(totOr)} (${txExec}%) • SLA: ${slaMed}d`);

  set("os5-kpi-corte-efic", `${txCorte}%`);
  set("os5-kpi-corte-efic-sub", `OR: ${fmtIntOS(cOr)} / ${fmtIntOS(cEmit)} • Pendentes OP: ${fmtIntOS(cOp)}`);

  set("os5-kpi-caixa-30d", `${fmtMoedaOS(cxTot30)} ECV`);
  set("os5-kpi-caixa-30d-sub", `Pós-Corte OR: ${fmtMoedaOS(cxOr30)} • Pré-Aviso OA: ${fmtMoedaOS(cxOa30)}`);

  set("os5-kpi-conv-ttc", `${txConvOr}% (${ttcOr}d)`);
  set("os5-kpi-conv-ttc-sub", `${fmtIntOS(pOr30)} de ${fmtIntOS(qOr)} cortes pagos em até 30d`);

  set("os5-kpi-backlog-op", `${fmtMoedaOS(divOp)} ECV`);
  set("os5-kpi-backlog-op-sub", `Dívida Exigível em ${fmtIntOS(cilsOp)} CILs c/ Corte Pendente OP`);

  set("os5-kpi-fuga-rx0", `${fmtMoedaOS(perdaRx0)} ECV`);
  set("os5-kpi-fuga-rx0-sub", `${fmtIntOS(atosSemRx0)} religações OR (${fmtIntOS(cilsSemRx0)} CILs) s/ Taxa RX0`);

  set("os5-kpi-autoconexao", `${fmtIntOS(cilsAuto)} CILs`);
  set("os5-kpi-autoconexao-sub", `Cortados s/ relig. e s/ pagar • Dívida: ${fmtMoedaOS(divAuto)} ECV`);

  set("os5-kpi-novas-lig", `${fmtIntOS(novFila)} em fila`);
  set("os5-kpi-novas-lig-sub", `Contadores por ligar (OE/OG/OP) • Já ligados OR: ${fmtIntOS(novOr)}`);
}

function renderizarTabelaFamiliasOS5(famRows, modo = "DETALHADO") {
  const tbody = document.getElementById("os5-tbody-familias");
  const tfoot = document.getElementById("os5-tfoot-familias");
  if (!tbody) return;

  if (!famRows.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:16px; color:var(--text-muted);">Sem Ordens de Serviço para os filtros selecionados.</td></tr>`;
    if (tfoot) tfoot.innerHTML = "";
    return;
  }

  const grupos = {};
  for (const r of famRows) {
    const chave = modo === "FAMILIA" ? r.familia : `${r.familia}|||${r.desc_os}`;
    if (!grupos[chave]) {
      grupos[chave] = {
        familia: r.familia,
        desc_os: modo === "FAMILIA" ? "Todos os serviços da família" : r.desc_os,
        emitidas: 0, or_realizadas: 0, op_pendentes: 0, oa_anuladas: 0,
        oe_og_curso: 0, oc_canceladas: 0, soma_sla: 0, qtd_sla: 0
      };
    }
    const g = grupos[chave];
    g.emitidas += r.emitidas;
    g.or_realizadas += r.or_realizadas;
    g.op_pendentes += r.op_pendentes;
    g.oa_anuladas += r.oa_anuladas;
    g.oe_og_curso += r.oe_og_curso;
    g.oc_canceladas += r.oc_canceladas;
    g.soma_sla += r.soma_sla;
    g.qtd_sla += r.qtd_sla;
  }

  const lista = Object.values(grupos).sort((a, b) => b.emitidas - a.emitidas);
  const totGeral = lista.reduce((s, x) => s + x.emitidas, 0);

  let sEmit = 0, sOr = 0, sOp = 0, sOa = 0, sOe = 0, sOc = 0, sSlaS = 0, sSlaN = 0;

  tbody.innerHTML = lista.map(g => {
    sEmit += g.emitidas; sOr += g.or_realizadas; sOp += g.op_pendentes;
    sOa += g.oa_anuladas; sOe += g.oe_og_curso; sOc += g.oc_canceladas;
    sSlaS += g.soma_sla; sSlaN += g.qtd_sla;

    const txNum = g.emitidas > 0 ? (g.or_realizadas / g.emitidas) * 100 : 0;
    const tx = txNum.toFixed(1).replace(".", ",");
    const quota = totGeral > 0 ? ((g.emitidas / totGeral) * 100).toFixed(1).replace(".", ",") : "0,0";
    const sla = g.qtd_sla > 0 ? (g.soma_sla / g.qtd_sla).toFixed(1).replace(".", ",") : "0,0";
    const corTx = txNum >= 75 ? "#34D399" : txNum >= 45 ? "#FBBF24" : "#F87171";

    return `
      <tr>
        <td style="font-family:var(--font-mono); font-size:11px; color:#60A5FA; font-weight:700; white-space:nowrap;">${g.familia}</td>
        <td style="font-weight:600; color:var(--text-primary);">${g.desc_os} <span style="color:var(--text-muted); font-family:var(--font-mono); font-size:10px;">(${quota}%)</span></td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtIntOS(g.emitidas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#34D399; font-weight:700;">${fmtIntOS(g.or_realizadas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:${g.op_pendentes > 0 ? "#F87171" : "var(--text-muted)"}; font-weight:${g.op_pendentes > 100 ? "800" : "400"};">${fmtIntOS(g.op_pendentes)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#FBBF24;">${fmtIntOS(g.oa_anuladas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA;">${fmtIntOS(g.oe_og_curso)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:var(--text-secondary);">${fmtIntOS(g.oc_canceladas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap; min-width:95px;">
          <div style="font-weight:800; color:${corTx};">${tx}% <span style="color:var(--text-muted); font-weight:400; font-size:10px;">(${sla}d)</span></div>
          <div style="height:3px; background:rgba(148,163,184,0.18); border-radius:2px; margin-top:2px; overflow:hidden;">
            <div style="width:${Math.min(100, Math.max(0, txNum)).toFixed(0)}%; height:100%; background:${corTx};"></div>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  if (tfoot) {
    const txTot = sEmit > 0 ? ((sOr / sEmit) * 100).toFixed(1).replace(".", ",") : "0,0";
    const slaTot = sSlaN > 0 ? (sSlaS / sSlaN).toFixed(1).replace(".", ",") : "0,0";
    tfoot.innerHTML = `
      <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
        <td colspan="2">TOTAL ORDENS DE SERVIÇO FILTRADAS</td>
        <td style="text-align:right;">${fmtIntOS(sEmit)}</td>
        <td style="text-align:right; color:#34D399;">${fmtIntOS(sOr)}</td>
        <td style="text-align:right; color:#F87171;">${fmtIntOS(sOp)}</td>
        <td style="text-align:right; color:#FBBF24;">${fmtIntOS(sOa)}</td>
        <td style="text-align:right; color:#60A5FA;">${fmtIntOS(sOe)}</td>
        <td style="text-align:right; color:var(--text-secondary);">${fmtIntOS(sOc)}</td>
        <td style="text-align:right; color:#34D399;">${txTot}% (${slaTot}d)</td>
      </tr>
    `;
  }
}

function renderizarMatrizTesourariaOS5(retRows) {
  const tbody = document.getElementById("os5-tbody-tesouraria");
  const tfoot = document.getElementById("os5-tfoot-tesouraria");
  if (!tbody) return;

  const labelEstado = {
    "OR": "1. OR · Corte Realizado no Terreno",
    "OA": "2. OA · Pagou no Pré-Aviso (Anulada)",
    "OP": "3. OP · Corte Pendente (Não Executado)",
    "OC": "4. OC · Cancelada / Impedimento Local",
    "OE": "5. OE · Em Execução no Terreno"
  };

  const grupos = {};
  for (const r of retRows) {
    if (!["OR", "OA", "OP", "OC", "OE"].includes(r.est_os)) continue;
    const k = `${r.est_os}|||${r.segmento}|||${r.grupo_tarifa}`;
    if (!grupos[k]) {
      grupos[k] = {
        est_os: r.est_os,
        est_label: labelEstado[r.est_os] || r.est_os,
        segmento: r.segmento,
        grupo_tarifa: r.grupo_tarifa,
        qtd_os: 0, pagaram_7d: 0, pagaram_30d: 0,
        receita_7d_ecv: 0, receita_30d_ecv: 0,
        soma_dias_pag: 0, qtd_dias_pag: 0, divida_exigivel_ecv: 0
      };
    }
    const g = grupos[k];
    g.qtd_os += r.qtd_os;
    g.pagaram_7d += r.pagaram_7d;
    g.pagaram_30d += r.pagaram_30d;
    g.receita_7d_ecv += r.receita_7d_ecv;
    g.receita_30d_ecv += r.receita_30d_ecv;
    g.soma_dias_pag += r.soma_dias_pag;
    g.qtd_dias_pag += r.qtd_dias_pag;
    g.divida_exigivel_ecv += r.divida_exigivel_ecv;
  }

  const lista = Object.values(grupos)
    .filter(g => g.qtd_os >= 5)
    .sort((a, b) => a.est_label.localeCompare(b.est_label) || (b.receita_30d_ecv + b.divida_exigivel_ecv) - (a.receita_30d_ecv + a.divida_exigivel_ecv));

  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:16px; color:var(--text-muted);">Sem registos de corte para o filtro selecionado.</td></tr>`;
    if (tfoot) tfoot.innerHTML = "";
    return;
  }

  let sOs = 0, sP7 = 0, sP30 = 0, sR7 = 0, sR30 = 0, sDS = 0, sDN = 0, sDiv = 0;

  tbody.innerHTML = lista.map(g => {
    sOs += g.qtd_os; sP7 += g.pagaram_7d; sP30 += g.pagaram_30d;
    sR7 += g.receita_7d_ecv; sR30 += g.receita_30d_ecv;
    sDS += g.soma_dias_pag; sDN += g.qtd_dias_pag; sDiv += g.divida_exigivel_ecv;

    const tx30Num = g.qtd_os > 0 ? (g.pagaram_30d / g.qtd_os) * 100 : 0;
    const tx7Num = g.qtd_os > 0 ? (g.pagaram_7d / g.qtd_os) * 100 : 0;
    const ttc = g.qtd_dias_pag > 0 ? (g.soma_dias_pag / g.qtd_dias_pag).toFixed(1).replace(".", ",") : "—";
    const ticket = g.pagaram_30d > 0 ? Math.round(g.receita_30d_ecv / g.pagaram_30d) : 0;
    const corEst = g.est_os === "OR" ? "#34D399" : g.est_os === "OA" ? "#60A5FA" : g.est_os === "OP" ? "#F87171" : "#FBBF24";
    const corConv = tx30Num >= 70 ? "#34D399" : tx30Num >= 40 ? "#FBBF24" : "#F87171";

    return `
      <tr style="${g.est_os === "OP" ? "background:rgba(248,113,113,0.05);" : ""}">
        <td style="font-family:var(--font-mono); font-size:11px; font-weight:700; color:${corEst}; white-space:nowrap;">${g.est_label}</td>
        <td style="font-weight:700; white-space:nowrap;">${g.segmento} <span style="color:var(--text-muted); font-family:var(--font-mono); font-size:10.5px;">(${g.grupo_tarifa})</span></td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtIntOS(g.qtd_os)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:${corConv}; font-weight:800;">${tx30Num.toFixed(1).replace(".", ",")}% <span style="color:var(--text-muted); font-weight:400; font-size:10px;">(7d: ${tx7Num.toFixed(0)}%)</span></td>
        <td style="text-align:right; font-family:var(--font-mono); color:${g.est_os === "OP" ? "#F87171" : "#34D399"}; font-weight:700;">${ttc} d</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtMoedaOS(ticket)} ECV</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA;">${fmtMoedaOS(g.receita_7d_ecv)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#34D399; font-weight:800;">${fmtMoedaOS(g.receita_30d_ecv)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:${g.est_os === "OP" ? "#F87171" : "var(--text-secondary)"}; font-weight:${g.est_os === "OP" ? "800" : "400"};">${fmtMoedaOS(g.divida_exigivel_ecv)}</td>
      </tr>
    `;
  }).join("");

  if (tfoot) {
    const txTot = sOs > 0 ? ((sP30 / sOs) * 100).toFixed(1).replace(".", ",") : "0,0";
    const ttcTot = sDN > 0 ? (sDS / sDN).toFixed(1).replace(".", ",") : "0,0";
    const tkTot = sP30 > 0 ? Math.round(sR30 / sP30) : 0;
    tfoot.innerHTML = `
      <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
        <td colspan="2">TOTAL / MÉDIA PONDERADA DE CORTE</td>
        <td style="text-align:right;">${fmtIntOS(sOs)}</td>
        <td style="text-align:right; color:#34D399;">${txTot}%</td>
        <td style="text-align:right;">${ttcTot} d</td>
        <td style="text-align:right;">${fmtMoedaOS(tkTot)} ECV</td>
        <td style="text-align:right; color:#60A5FA;">${fmtMoedaOS(sR7)}</td>
        <td style="text-align:right; color:#34D399;">${fmtMoedaOS(sR30)}</td>
        <td style="text-align:right; color:#F87171;">${fmtMoedaOS(sDiv)}</td>
      </tr>
    `;
  }
}

function renderizarQuandoCortarOS5(semRows, mesRows) {
  const tbodySem = document.getElementById("os5-tbody-semana");
  const tbodyMes = document.getElementById("os5-tbody-mes");

  if (tbodySem) {
    const nomesDow = {
      1: { nome: "1. Segunda-Feira", rec: "Corte Massivo (paga 2ª/3ª)" },
      2: { nome: "2. Terça-Feira", rec: "Corte Massivo (paga 3ª/4ª)" },
      3: { nome: "3. Quarta-Feira ★", rec: "Pico Semanal de Conversão!" },
      4: { nome: "4. Quinta-Feira", rec: "Cortar até 13h (paga até 6ª)" },
      5: { nome: "5. Sexta-Feira ⚠", rec: "Priorizar Religações RX0 & Empresas" },
      6: { nome: "6. Sábado", rec: "Piquete / Religação Urgente" }
    };
    const porDow = {};
    for (const r of semRows) {
      if (r.dow < 1 || r.dow > 6) continue;
      if (!porDow[r.dow]) porDow[r.dow] = { dow: r.dow, cortes: 0, conv: 0, caixa: 0, sDias: 0, nDias: 0 };
      porDow[r.dow].cortes += r.cortes_or;
      porDow[r.dow].conv += r.convertidos_7d;
      porDow[r.dow].caixa += r.caixa_7d_ecv;
      porDow[r.dow].sDias += r.soma_dias;
      porDow[r.dow].nDias += r.qtd_dias;
    }
    const listaSem = Object.values(porDow).filter(d => d.cortes > 0).sort((a, b) => a.dow - b.dow);
    tbodySem.innerHTML = listaSem.map(d => {
      const info = nomesDow[d.dow] || { nome: `Dia ${d.dow}`, rec: "" };
      const txNum = d.cortes > 0 ? (d.conv / d.cortes) * 100 : 0;
      const ttc = d.nDias > 0 ? (d.sDias / d.nDias).toFixed(1).replace(".", ",") : "—";
      const tk = d.conv > 0 ? Math.round(d.caixa / d.conv) : 0;
      const cor = d.dow === 3 ? "#34D399" : d.dow === 5 ? "#F87171" : "#60A5FA";
      return `
        <tr style="${d.dow === 3 ? "background:rgba(52,211,153,0.07);" : d.dow === 5 ? "background:rgba(248,113,113,0.06);" : ""}">
          <td style="font-family:var(--font-mono); font-weight:700; color:${cor}; white-space:nowrap;">${info.nome}</td>
          <td style="text-align:right; font-family:var(--font-mono);">${fmtIntOS(d.cortes)}</td>
          <td style="text-align:right; font-family:var(--font-mono); font-weight:800; color:${cor};">${txNum.toFixed(1).replace(".", ",")}%</td>
          <td style="text-align:right; font-family:var(--font-mono); color:#34D399;">${ttc} d</td>
          <td style="text-align:right; font-family:var(--font-mono);">${fmtMoedaOS(tk)}</td>
          <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtMoedaOS(d.caixa)}</td>
          <td style="font-size:11px; color:var(--text-secondary);">${info.rec}</td>
        </tr>
      `;
    }).join("");
  }

  if (tbodyMes) {
    const recMes = {
      "1. Início do Mês (Dias 01–10)": "Foco: Empresas Privadas + Domésticos D1 Alta Dívida (Maior Ticket)",
      "2. Meio do Mês (Dias 11–20)": "Foco: Comércio / Serviços (D1/E1/E2) + 1ª Revisão de Corte",
      "3. Fim do Mês / Pós-Salário (Dias 21–31)": "Pico de Liquidez Familiar (71,5%): Corte Massivo Doméstico D1/S1"
    };
    const porJan = {};
    for (const r of mesRows) {
      if (!porJan[r.janela_mes]) porJan[r.janela_mes] = { janela: r.janela_mes, cortes: 0, conv: 0, caixa: 0, sDias: 0, nDias: 0 };
      porJan[r.janela_mes].cortes += r.cortes_or;
      porJan[r.janela_mes].conv += r.convertidos_15d;
      porJan[r.janela_mes].caixa += r.caixa_15d_ecv;
      porJan[r.janela_mes].sDias += r.soma_dias;
      porJan[r.janela_mes].nDias += r.qtd_dias;
    }
    const listaMes = Object.values(porJan).sort((a, b) => a.janela.localeCompare(b.janela));
    tbodyMes.innerHTML = listaMes.map(m => {
      const txNum = m.cortes > 0 ? (m.conv / m.cortes) * 100 : 0;
      const ttc = m.nDias > 0 ? (m.sDias / m.nDias).toFixed(1).replace(".", ",") : "—";
      const tk = m.conv > 0 ? Math.round(m.caixa / m.conv) : 0;
      const ehPico = m.janela.startsWith("3.");
      const cor = ehPico ? "#34D399" : "#60A5FA";
      return `
        <tr style="${ehPico ? "background:rgba(52,211,153,0.07);" : ""}">
          <td style="font-family:var(--font-mono); font-weight:700; color:${cor}; white-space:nowrap;">${m.janela}</td>
          <td style="text-align:right; font-family:var(--font-mono);">${fmtIntOS(m.cortes)}</td>
          <td style="text-align:right; font-family:var(--font-mono); font-weight:800; color:${cor};">${txNum.toFixed(1).replace(".", ",")}%</td>
          <td style="text-align:right; font-family:var(--font-mono); color:#34D399;">${ttc} d</td>
          <td style="text-align:right; font-family:var(--font-mono);">${fmtMoedaOS(tk)}</td>
          <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtMoedaOS(m.caixa)}</td>
          <td style="font-size:11px; color:var(--text-secondary);">${recMes[m.janela] || ""}</td>
        </tr>
      `;
    }).join("");
  }
}

function renderizarAuditoriaUnidadesOS5(audRows, ucAtual = "TODAS") {
  const tbody = document.getElementById("os5-tbody-auditoria-uc");
  const tfoot = document.getElementById("os5-tfoot-auditoria-uc");
  if (!tbody) return;

  let sOs = 0, sCOr = 0, sCOp = 0, sDivOp = 0, sRel = 0, sSemRx = 0, sPerdaRx = 0, sAuto = 0, sDivAuto = 0;

  tbody.innerHTML = audRows.map(r => {
    const ativa = r.desc_uni === ucAtual;
    sOs += r.total_os; sCOr += r.cortes_or; sCOp += r.cortes_op; sDivOp += r.div_exig_op_ecv;
    sRel += r.os_relig_or_2026; sSemRx += r.atos_sem_rx0; sPerdaRx += r.perda_estimada_rx0_ecv;
    sAuto += r.cils_autoconexao; sDivAuto += r.div_autoconexao_ecv;

    return `
      <tr style="cursor:pointer; ${ativa ? "background:rgba(251,191,36,0.14); font-weight:700;" : ""}" onclick="selecionarUnidadeOS5('${r.desc_uni.replace(/'/g, "\\'")}')" title="Clicar para filtrar a Aba 5 por ${r.desc_uni}">
        <td style="font-family:var(--font-mono); font-weight:700; color:${ativa ? "#FBBF24" : "#60A5FA"}; white-space:nowrap;">${ativa ? "▶ " : ""}${r.desc_uni}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtIntOS(r.total_os)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#34D399; font-weight:700;">${fmtIntOS(r.cortes_or)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#F87171; font-weight:700;">${fmtIntOS(r.cortes_op)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#F87171; font-weight:800;">${fmtMoedaOS(r.div_exig_op_ecv)}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtIntOS(r.os_relig_or_2026)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#A78BFA; font-weight:700;">${fmtIntOS(r.atos_sem_rx0)} <span style="color:var(--text-muted); font-size:10px;">(${fmtMoedaOS(r.perda_estimada_rx0_ecv)})</span></td>
        <td style="text-align:right; font-family:var(--font-mono); color:#FBBF24; font-weight:700;">${fmtIntOS(r.cils_autoconexao)} <span style="color:var(--text-muted); font-size:10px;">(${fmtMoedaOS(r.div_autoconexao_ecv)})</span></td>
      </tr>
    `;
  }).join("");

  if (tfoot) {
    tfoot.innerHTML = `
      <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
        <td>TOTAL REGIÃO SUL</td>
        <td style="text-align:right;">${fmtIntOS(sOs)}</td>
        <td style="text-align:right; color:#34D399;">${fmtIntOS(sCOr)}</td>
        <td style="text-align:right; color:#F87171;">${fmtIntOS(sCOp)}</td>
        <td style="text-align:right; color:#F87171;">${fmtMoedaOS(sDivOp)}</td>
        <td style="text-align:right;">${fmtIntOS(sRel)}</td>
        <td style="text-align:right; color:#A78BFA;">${fmtIntOS(sSemRx)} (${fmtMoedaOS(sPerdaRx)})</td>
        <td style="text-align:right; color:#FBBF24;">${fmtIntOS(sAuto)} (${fmtMoedaOS(sDivAuto)})</td>
      </tr>
    `;
  }
}

function selecionarFilaAcaoOS5(tipoFila) {
  window._os5FilaAtiva = tipoFila || "ev_op";
  ["ev_op", "fuga_rx0", "autoconexao"].forEach(k => {
    const btn = document.getElementById(`os5-btn-fila-${k}`);
    if (btn) {
      btn.style.background = (k === window._os5FilaAtiva) ? "rgba(96,165,250,0.22)" : "var(--bg-panel-elevated)";
      btn.style.borderColor = (k === window._os5FilaAtiva) ? "#60A5FA" : "var(--border-dim)";
      btn.style.color = (k === window._os5FilaAtiva) ? "#60A5FA" : "var(--text-secondary)";
    }
  });
  renderizarFilaAcaoOS5();
}

function obterLinhasFilaAtivaOS5() {
  const dados = window._os5Dados;
  if (!dados) return [];
  const uc = document.getElementById("os5-filtro-uc")?.value || "TODAS";
  const seg = document.getElementById("os5-filtro-segmento")?.value || "TODOS";
  const termo = (document.getElementById("os5-busca-fila")?.value || "").trim().toLowerCase();

  let base = [];
  if (window._os5FilaAtiva === "fuga_rx0") base = dados.fila_fuga_rx0 || [];
  else if (window._os5FilaAtiva === "autoconexao") base = dados.fila_autoconexao || [];
  else base = dados.fila_corte_op_ev || [];

  return base.filter(r => {
    if (uc !== "TODAS" && r.desc_uni !== uc) return false;
    if (seg !== "TODOS" && r.segmento !== seg) return false;
    if (termo) {
      const txt = `${r.cil} ${r.nome || ""} ${r.pt || ""} ${r.localidade || ""} ${r.desc_uni || ""}`.toLowerCase();
      if (!txt.includes(termo)) return false;
    }
    return true;
  });
}

function renderizarFilaAcaoOS5() {
  const thead = document.getElementById("os5-thead-fila");
  const tbody = document.getElementById("os5-tbody-fila");
  const countBadge = document.getElementById("os5-fila-count");
  if (!thead || !tbody) return;

  const rows = obterLinhasFilaAtivaOS5();
  if (countBadge) countBadge.textContent = `${rows.length} alvos listados`;

  if (window._os5FilaAtiva === "fuga_rx0") {
    thead.innerHTML = `
      <tr>
        <th>CIL</th>
        <th>Cliente</th>
        <th>Unidade / PT</th>
        <th>Segmento / Tarifa</th>
        <th style="text-align:right;">Religações OR (2026)</th>
        <th style="text-align:right;">Taxas RX0 Fat.</th>
        <th style="text-align:right; color:#A78BFA;">Atos SEM RX0</th>
        <th style="text-align:right; color:#F87171;">RX0 Não Faturado</th>
        <th style="text-align:right; color:#34D399;">Cobrança 2026</th>
      </tr>
    `;
    tbody.innerHTML = rows.length ? rows.map(r => `
      <tr style="cursor:pointer;" onclick="if(typeof abrirDossiePorCIL==='function') abrirDossiePorCIL(${r.cil})">
        <td style="font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${r.cil}</td>
        <td style="max-width:190px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${r.nome || "--"}</td>
        <td style="font-family:var(--font-mono); font-size:11px;">${r.desc_uni} • <span style="color:var(--text-secondary);">${r.pt}</span></td>
        <td style="font-family:var(--font-mono); font-size:11px;">${r.segmento} (${r.tarifa})</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${r.qtd_rel_or}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${r.qtd_rx0_faturadas}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#A78BFA; font-weight:800;">${r.atos_sem_rx0}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#F87171; font-weight:700;">${fmtMoedaOS(r.rx0_nao_faturado_ecv)} ECV</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#34D399;">${fmtMoedaOS(r.cobranca_2026_ecv)} ECV</td>
      </tr>
    `).join("") : `<tr><td colspan="9" style="text-align:center; padding:16px; color:var(--text-muted);">Sem alvos para os filtros atuais.</td></tr>`;
  } else if (window._os5FilaAtiva === "autoconexao") {
    thead.innerHTML = `
      <tr>
        <th>CIL</th>
        <th>Cliente</th>
        <th>Unidade / PT</th>
        <th>Segmento / Tarifa</th>
        <th style="text-align:right;">Cortes OR</th>
        <th style="text-align:center;">Último Corte OR</th>
        <th style="text-align:right;">Faturas Abertas</th>
        <th style="text-align:right; color:#F87171;">Dívida Exigível (ECV)</th>
        <th>Ação Recomendada</th>
      </tr>
    `;
    tbody.innerHTML = rows.length ? rows.map(r => `
      <tr style="cursor:pointer;" onclick="if(typeof abrirDossiePorCIL==='function') abrirDossiePorCIL(${r.cil})">
        <td style="font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${r.cil}</td>
        <td style="max-width:190px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${r.nome || "--"}</td>
        <td style="font-family:var(--font-mono); font-size:11px;">${r.desc_uni} • <span style="color:var(--text-secondary);">${r.pt}</span></td>
        <td style="font-family:var(--font-mono); font-size:11px;">${r.segmento} (${r.tarifa})</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${r.qtd_cortes_or}</td>
        <td style="text-align:center; font-family:var(--font-mono); color:#FBBF24;">${r.dt_ult_corte}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtIntOS(r.faturas_abertas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#F87171; font-weight:800;">${fmtMoedaOS(r.div_exigivel_ecv)} ECV</td>
        <td style="font-family:var(--font-mono); font-size:10.5px; color:#FBBF24;">1ª Revisão Corte / Fiscalização CEA</td>
      </tr>
    `).join("") : `<tr><td colspan="9" style="text-align:center; padding:16px; color:var(--text-muted);">Sem alvos para os filtros atuais.</td></tr>`;
  } else {
    thead.innerHTML = `
      <tr>
        <th>CIL</th>
        <th>Cliente</th>
        <th>Unidade / PT</th>
        <th>Segmento / Tarifa</th>
        <th style="text-align:right;">OS Corte OP</th>
        <th style="text-align:right;">Faturas</th>
        <th style="text-align:right;">Dívida Exigível</th>
        <th style="text-align:right; color:#60A5FA;">Prob. Pagar (30d)</th>
        <th style="text-align:right; color:#34D399;">Retorno Esperado (EV 30d)</th>
      </tr>
    `;
    tbody.innerHTML = rows.length ? rows.map(r => `
      <tr style="cursor:pointer;" onclick="if(typeof abrirDossiePorCIL==='function') abrirDossiePorCIL(${r.cil})">
        <td style="font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${r.cil}</td>
        <td style="max-width:190px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${r.nome || "--"}</td>
        <td style="font-family:var(--font-mono); font-size:11px;">${r.desc_uni} • <span style="color:var(--text-secondary);">${r.pt}</span></td>
        <td style="font-family:var(--font-mono); font-size:11px;">${r.segmento} (${r.tarifa})</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#F87171; font-weight:700;">${r.qtd_os_op}</td>
        <td style="text-align:right; font-family:var(--font-mono);">${fmtIntOS(r.faturas_abertas)}</td>
        <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${fmtMoedaOS(r.div_exigivel_ecv)} ECV</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#60A5FA; font-weight:700;">${r.prob_conversao_pct}%</td>
        <td style="text-align:right; font-family:var(--font-mono); color:#34D399; font-weight:800;">${fmtMoedaOS(r.ev_30d_ecv)} ECV</td>
      </tr>
    `).join("") : `<tr><td colspan="9" style="text-align:center; padding:16px; color:var(--text-muted);">Sem alvos para os filtros atuais.</td></tr>`;
  }
}

function exportarFilaAtivaOS5CSV() {
  const rows = obterLinhasFilaAtivaOS5();
  if (!rows.length) {
    alert("Nenhum registo disponível na fila ativa para exportar.");
    return;
  }
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  let cab = [];
  let linhas = [];
  let prefixo = "EDEC_OS5";

  if (window._os5FilaAtiva === "fuga_rx0") {
    prefixo = "EDEC_Auditoria_Religacoes_Sem_RX0";
    cab = ["cil", "Nome", "Unidade", "PT", "Localidade", "Segmento", "Tarifa", "Religacoes_OR_2026", "Taxas_RX0_Faturadas", "Atos_Sem_RX0", "RX0_Nao_Faturado_ECV", "Cobranca_2026_ECV"];
    linhas = rows.map(r => [
      r.cil, esc(r.nome), esc(r.desc_uni), esc(r.pt), esc(r.localidade),
      esc(r.segmento), esc(r.tarifa), r.qtd_rel_or, r.qtd_rx0_faturadas,
      r.atos_sem_rx0, r.rx0_nao_faturado_ecv, r.cobranca_2026_ecv
    ].join(";"));
  } else if (window._os5FilaAtiva === "autoconexao") {
    prefixo = "EDEC_Fiscalizacao_Autoconexao_Pos_Corte";
    cab = ["cil", "Nome", "Unidade", "PT", "Localidade", "Segmento", "Tarifa", "Cortes_OR", "Ultimo_Corte_OR", "Faturas_Abertas", "Divida_Exigivel_ECV"];
    linhas = rows.map(r => [
      r.cil, esc(r.nome), esc(r.desc_uni), esc(r.pt), esc(r.localidade),
      esc(r.segmento), esc(r.tarifa), r.qtd_cortes_or, esc(r.dt_ult_corte),
      r.faturas_abertas, r.div_exigivel_ecv
    ].join(";"));
  } else {
    prefixo = "EDEC_Alvos_Corte_Pendente_OP_EV30d";
    cab = ["cil", "Nome", "Unidade", "PT", "Localidade", "Segmento", "Tarifa", "OS_Corte_OP", "Faturas_Abertas", "Divida_Exigivel_ECV", "Prob_Pagamento_30d_Pct", "Retorno_Esperado_EV30d_ECV"];
    linhas = rows.map(r => [
      r.cil, esc(r.nome), esc(r.desc_uni), esc(r.pt), esc(r.localidade),
      esc(r.segmento), esc(r.tarifa), r.qtd_os_op, r.faturas_abertas,
      r.div_exigivel_ecv, r.prob_conversao_pct, r.ev_30d_ecv
    ].join(";"));
  }

  const uc = document.getElementById("os5-filtro-uc")?.value || "TODAS";
  const sufixoUc = uc !== "TODAS" ? `_${uc.replace(/\s+/g, "_")}` : "";
  const nomeArq = `${prefixo}${sufixoUc}_${new Date().toISOString().slice(0, 10)}.csv`;
  salvarOuBaixarCSV(nomeArq, "\uFEFF" + [cab.join(";"), ...linhas].join("\r\n"));
}
