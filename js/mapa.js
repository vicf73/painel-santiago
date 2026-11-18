    // =========================================================================
    // MÓDULO 2: GOOGLE MAPS + POLÍGONOS REAIS DOS PTs MEDIDOS (SL7000)
    // =========================================================================
    let DADOS_PTS_3D = [];
    let BALANCO_TRIMS = {};
    let trimestreAtualPT = "2026-T3";
    let ptSelecionado3D = null;

    let mapMod2 = null;
    let layerGoogleSat = null;
    let layerGoogleRuas = null;
    let layerPoligonosPT = null;
    let usandoGoogleRuas = false;
    let poligonosPorPT = {};

    async function carregarBalancoPTReal(trimCod = trimestreAtualPT) {
      trimestreAtualPT = trimCod;
      if (!Object.keys(BALANCO_TRIMS).length) {
        try {
          const resp = await fetch(
            `${SUPABASE_URL}/rest/v1/santiago_marts_gold?chave=eq.balanco_pt_trimestral&select=dados`,
            { headers: HEADERS }
          );
          if (resp.ok) {
            const rows = await resp.json();
            if (rows.length && rows[0].dados?.trimestres) {
              BALANCO_TRIMS = rows[0].dados.trimestres;
            }
          }
        } catch (err) {
          console.error("Erro ao carregar Balanço PT:", err);
        }
      }

      const tri = BALANCO_TRIMS[trimCod];
      if (!tri) return;

      const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      setTxt("m2-kpi-pts", `${tri.pts_com_cobertura} de ${tri.pts_medidos}`);
      setTxt("m2-kpi-pts-sub", `PTs medidos c/ cobertura CL_PT (${tri.label || trimCod})`);
      setTxt("m2-kpi-inj", `${Number(tri.injetada_mwh || 0).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MWh`);
      setTxt("m2-kpi-inj-sub", `Soma nos ${tri.pts_com_cobertura} PTs medidos`);
      setTxt("m2-kpi-fat", `${Number(tri.faturada_mwh || 0).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MWh`);
      setTxt("m2-kpi-fat-sub", `Clientes BT + IP nos ${tri.pts_com_cobertura} PTs`);
      setTxt("m2-kpi-perda", `${Number(tri.perda_mwh || 0).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MWh (${tri.taxa_perda_pct}%)`);
      setTxt("m2-kpi-perda-sub", `PNT: ${Number(tri.perda_pnt_mwh || 0).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MWh (${tri.taxa_pnt_pct || 0}%) • Téc: 5,0%`);
      const pntMilhoes = Number(tri.prejuizo_pnt_ecv || 0) / 1e6;
      const totMilhoes = Number(tri.prejuizo_total_ecv || 0) / 1e6;
      setTxt("m2-kpi-fin", `~${pntMilhoes.toLocaleString("pt-PT", { maximumFractionDigits: 1 })}M ECV`);
      setTxt("m2-kpi-fin-sub", `Perda Total: ~${totMilhoes.toLocaleString("pt-PT", { maximumFractionDigits: 1 })}M ECV / trim.`);

      const recBar = document.getElementById("m2-reconciliacao-bar");
      if (recBar && tri.reconciliacao) {
        const rec = tri.reconciliacao;
        const pctMed = rec.total_bt_mwh > 0 ? ((rec.medidos_mwh / rec.total_bt_mwh) * 100).toFixed(1) : "0.0";
        const pctOrf = rec.total_bt_mwh > 0 ? ((rec.sem_pt_mwh / rec.total_bt_mwh) * 100).toFixed(1) : "0.0";
        recBar.innerHTML = `
          <span style="font-weight:700; color:var(--text-primary);">📋 Reconciliação BT Ilha:</span>
          <span>Total Faturado BT: <b>${Number(rec.total_bt_mwh).toLocaleString("pt-PT")} MWh</b></span>
          <span style="color:#34D399;">✔ Em PTs Medidos: <b>${Number(rec.medidos_mwh).toLocaleString("pt-PT")} MWh (${pctMed}%)</b></span>
          <span>PTs Não Medidos: <b>${Number(rec.nao_medidos_mwh).toLocaleString("pt-PT")} MWh</b></span>
          <span style="color:#FBBF24;">⚠️ Energia Órfã (Sem PT): <b>${Number(rec.sem_pt_mwh).toLocaleString("pt-PT")} MWh (${pctOrf}% • ${Number(rec.cils_sem_pt).toLocaleString("pt-PT")} CILs)</b></span>
        `;
      }

      DADOS_PTS_3D = (tri.pts || [])
        .filter(p => p.status !== "sem_cobertura" && p.injetada_kwh > 0)
        .map(p => ({
          id: p.pt,
          nome: p.localidade || p.pt,
          concelho: p.localidade || "Santiago",
          contador: p.contador,
          contador_ip: p.contador_ip || "",
          fat_ip_kwh: Number(p.fat_ip_kwh || 0),
          peso_ip_pct: Number(p.peso_ip_pct || 0),
          lat: p.lat,
          lon: p.lon,
          poligono: p.poligono || [],
          injetada: Number(p.injetada_kwh) / 1000.0,
          faturada: Number(p.faturada_kwh) / 1000.0,
          perda: Number(p.perda_kwh) / 1000.0,
          taxa: Number(p.taxa_perda_pct),
          perda_tecnica: Number(p.perda_tecnica_kwh || 0) / 1000.0,
          perda_pnt: Number(p.perda_pnt_kwh || 0) / 1000.0,
          taxa_pnt: Number(p.taxa_pnt_pct || 0),
          prejuizo_ecv: Number(p.prejuizo_ecv || 0),
          prejuizo_pnt_ecv: Number(p.prejuizo_pnt_ecv || 0),
          delta_taxa_pp: p.delta_taxa_pp !== undefined ? p.delta_taxa_pp : null,
          delta_perda_kwh: p.delta_perda_kwh !== undefined ? p.delta_perda_kwh : null,
          divida: Number(p.divida_ecv || 0),
          clientes: Number(p.qtd_clientes || 0),
          qtd_fat_zero: Number(p.qtd_fat_zero || 0),
          consumo_medio_cli_mes: Number(p.consumo_medio_cli_mes || 0),
          qtd_risco_alto: Number(p.qtd_risco_alto || 0),
          insp_total: Number(p.insp_total || 0),
          insp_fraude: Number(p.insp_fraude || 0),
          diagnostico: p.diagnostico || "ok",
          top_cils_risco: p.top_cils_risco || [],
          status: p.status,
        }));

      ptSelecionado3D = DADOS_PTS_3D[0] || null;
      popularFiltroSelectPTs();
      iniciarMapaGooglePTs();
      desenharPoligonosPTs();
      renderizarRankingPTs3D();
      renderizarMatrizPriorizacaoPTs();
      if (ptSelecionado3D) atualizarCardPT(ptSelecionado3D);
      renderizarTabelaCompletaPTs(tri.pts || []);
    }

    function popularFiltroSelectPTs() {
      const sel = document.getElementById("m2-filtro-pt");
      if (!sel) return;
      const ordenados = [...DADOS_PTS_3D].sort((a, b) => a.id.localeCompare(b.id));
      sel.innerHTML = ordenados.map(p =>
        `<option value="${p.id}">${p.id} — ${p.taxa.toFixed(1)}% (${p.clientes} cli.)</option>`
      ).join("");
      if (ptSelecionado3D) sel.value = ptSelecionado3D.id;
    }

    function mudarTrimestreBalancoPT(trimCod) {
      carregarBalancoPTReal(trimCod);
    }

    function iniciarMapaGooglePTs() {
      const container = document.getElementById("map-mod2-pts");
      if (!container || typeof L === "undefined") return;

      if (!mapMod2) {
        mapMod2 = L.map("map-mod2-pts", { zoomControl: true }).setView([15.05, -23.60], 11);
        layerGoogleSat = L.tileLayer("https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}", {
          maxZoom: 20,
          attribution: "Google Satellite Hybrid"
        });
        layerGoogleRuas = L.tileLayer("https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}", {
          maxZoom: 20,
          attribution: "Google Maps"
        });
        layerGoogleSat.addTo(mapMod2);
        layerPoligonosPT = L.featureGroup().addTo(mapMod2);
      }
      setTimeout(() => mapMod2.invalidateSize(), 80);
    }

    function alternarCamadaMapaPT() {
      if (!mapMod2) return;
      usandoGoogleRuas = !usandoGoogleRuas;
      if (usandoGoogleRuas) {
        mapMod2.removeLayer(layerGoogleSat);
        layerGoogleRuas.addTo(mapMod2);
      } else {
        mapMod2.removeLayer(layerGoogleRuas);
        layerGoogleSat.addTo(mapMod2);
      }
    }

    function corPorStatusPT(st) {
      if (st === "critico") return "#E15759";
      if (st === "alerta") return "#F28E2B";
      return "#59A14F";
    }

    function desenharPoligonosPTs() {
      if (!mapMod2 || !layerPoligonosPT) return;
      layerPoligonosPT.clearLayers();
      poligonosPorPT = {};
      const boundsAll = [];

      DADOS_PTS_3D.forEach(pt => {
        const cor = corPorStatusPT(pt.status);
        let layer = null;
        if (pt.poligono && pt.poligono.length >= 1 && Array.isArray(pt.poligono[0])) {
          const ehMulti = Array.isArray(pt.poligono[0][0]);
          if (ehMulti || pt.poligono.length >= 3) {
            layer = L.polygon(pt.poligono, {
              color: cor,
              weight: 2,
              opacity: 0.95,
              fillColor: cor,
              fillOpacity: 0.30,
            });
          }
        }
        if (!layer && pt.lat && pt.lon) {
          layer = L.circle([pt.lat, pt.lon], {
            radius: 120,
            color: cor,
            weight: 2,
            fillColor: cor,
            fillOpacity: 0.35,
          });
        }
        if (layer) {
          layer.bindTooltip(
            `<b>${pt.id}</b> (${pt.nome})<br>Perda: <b>${pt.taxa.toFixed(1)}%</b> · Injetada: ${pt.injetada.toFixed(1)} MWh · ${pt.clientes} clientes`,
            { sticky: true }
          );
          layer.on("click", () => selecionarPT3D(pt));
          layer.addTo(layerPoligonosPT);
          poligonosPorPT[pt.id] = layer;
        }
      });

      const grpBounds = layerPoligonosPT.getBounds();
      if (grpBounds && grpBounds.isValid()) {
        mapMod2.fitBounds(grpBounds, { padding: [24, 24], maxZoom: 14 });
      }
    }

    function labelDiagnosticoPT(diag) {
      const map = {
        erro_cadastro_neg: { txt: "Erro Cadastro / TC (< -5%)", cor: "#F87171" },
        salto_injecao: { txt: "Salto Injeção (> ±40%)", cor: "#FBBF24" },
        ip_zerado: { txt: "Contador IP Zerado", cor: "#FBBF24" },
        subfaturacao_extrema: { txt: "Subfaturação Extrema", cor: "#E15759" },
        sem_cobertura: { txt: "S/ Cobertura CL_PT", cor: "var(--text-muted)" },
        ok: { txt: "Consistente", cor: "#34D399" }
      };
      return map[diag] || map.ok;
    }

    function filtrarTabelaPTs() {
      const tri = BALANCO_TRIMS[trimestreAtualPT];
      if (tri && tri.pts) renderizarTabelaCompletaPTs(tri.pts);
    }

    function renderizarTabelaCompletaPTs(pts) {
      const tbody = document.getElementById("m2-tbody-pts");
      const tfoot = document.getElementById("m2-tfoot-pts");
      if (!tbody) return;

      const filtroDiag = document.getElementById("m2-filtro-diag")?.value || "todos";
      const ptsFiltrados = pts.filter(p => {
        if (filtroDiag === "critico") return p.status === "critico";
        if (filtroDiag === "piora") return p.delta_taxa_pp !== null && p.delta_taxa_pp !== undefined && Number(p.delta_taxa_pp) >= 3.0;
        if (filtroDiag === "anomalias") return ["erro_cadastro_neg", "salto_injecao", "ip_zerado", "subfaturacao_extrema"].includes(p.diagnostico);
        return true;
      });

      let totCli = 0, totFatZero = 0, totMed20a = 0, totLeit5m = 0, totIpKwh = 0, totInj = 0, totFat = 0, totPrejPnt = 0, totRisco = 0, qtdMedCob = 0;
      tbody.innerHTML = ptsFiltrados.map(p => {
        const cor = p.status === "critico" ? "#F87171" : p.status === "alerta" ? "#FBBF24" : p.status === "normal" ? "#34D399" : "var(--text-muted)";
        const ipKwh = Number(p.fat_ip_kwh || 0);
        const ipTxt = p.contador_ip
          ? `<div style="font-family:var(--font-mono); font-size:10.5px; color:var(--text-secondary);">${p.contador_ip}</div><div style="font-family:var(--font-mono); font-weight:700; color:#FBBF24;">${Math.round(ipKwh).toLocaleString("pt-PT")} kWh</div>`
          : `<span style="color:var(--text-muted); opacity:0.45;">—</span>`;

        const dpp = p.delta_taxa_pp;
        const deltaHtml = (dpp === null || dpp === undefined)
          ? `<span style="color:var(--text-muted);">—</span>`
          : `<span style="font-weight:700; color:${dpp > 2 ? "#F87171" : dpp < -2 ? "#34D399" : "var(--text-secondary)"};">${dpp > 0 ? "+" : ""}${Number(dpp).toFixed(1)} p.p.</span>`;

        const diag = labelDiagnosticoPT(p.diagnostico);
        const prejM = (Number(p.prejuizo_pnt_ecv || 0) / 1e6).toFixed(2);

        if (p.status !== "sem_cobertura") {
          qtdMedCob += 1;
          totCli += Number(p.qtd_clientes || 0);
          totFatZero += Number(p.qtd_fat_zero || 0);
          totMed20a += Number(p.qtd_med_20a || 0);
          totLeit5m += Number(p.qtd_leit_5m || 0);
          totIpKwh += ipKwh;
          totInj += Number(p.injetada_kwh || 0);
          totFat += Number(p.faturada_kwh || 0);
          totPrejPnt += Number(p.prejuizo_pnt_ecv || 0);
          totRisco += Number(p.qtd_risco_alto || 0);
        }

        return `
          <tr style="cursor:pointer;" onclick="selecionarPT3DPorId('${p.pt}')">
            <td style="font-family:var(--font-mono); font-weight:700; color:#60A5FA; white-space:nowrap;">${p.pt}</td>
            <td style="font-family:var(--font-mono); font-size:11px; color:var(--text-secondary); white-space:nowrap;">${p.contador || "--"}</td>
            <td style="font-size:11px; color:var(--text-secondary);">${p.localidade || "--"}</td>
            <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${Number(p.qtd_clientes || 0).toLocaleString("pt-PT")}</td>
            <td style="text-align:right; font-family:var(--font-mono); color:#FBBF24;">${Number(p.qtd_fat_zero || 0).toLocaleString("pt-PT")}</td>
            <td style="text-align:right; font-family:var(--font-mono); color:#A78BFA;">${Number(p.qtd_med_20a || 0).toLocaleString("pt-PT")}</td>
            <td style="text-align:right; font-family:var(--font-mono); color:#F87171;">${Number(p.qtd_leit_5m || 0).toLocaleString("pt-PT")}</td>
            <td style="text-align:right; white-space:nowrap;">${ipTxt}</td>
            <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap;">${(p.injetada_kwh / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap;">${(p.faturada_kwh / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right; font-family:var(--font-mono); font-weight:800; color:${cor}; white-space:nowrap;">${p.taxa_perda_pct}% <span style="font-size:10px; font-weight:500; color:var(--text-muted);">(${p.taxa_pnt_pct ?? (p.taxa_perda_pct - 5).toFixed(1)}%)</span></td>
            <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap;">${deltaHtml}</td>
            <td style="text-align:right; font-family:var(--font-mono); color:#FBBF24; white-space:nowrap;">${prejM}M</td>
            <td style="text-align:right; font-family:var(--font-mono); font-weight:700; color:#F87171;">${p.qtd_risco_alto || 0}</td>
            <td style="text-align:right; font-family:var(--font-mono);">${Number(p.consumo_medio_cli_mes || 0).toFixed(0)}</td>
            <td style="text-align:center;"><span class="badge" style="color:${diag.cor}; border:1px solid ${diag.cor}; font-size:9.5px; white-space:nowrap;">${diag.txt}</span></td>
          </tr>
        `;
      }).join("");

      if (tfoot) {
        const taxaTot = totInj > 0 ? (((totInj - totFat) / totInj) * 100).toFixed(1) : "0.0";
        const pntTot = totInj > 0 ? (((totInj - totFat - totInj * 0.05) / totInj) * 100).toFixed(1) : "0.0";
        tfoot.innerHTML = `
          <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
            <td>TOTAL (${qtdMedCob} de ${ptsFiltrados.length} PTs)</td>
            <td>—</td>
            <td style="font-size:10.5px; color:var(--text-muted);">PTs medidos c/ cobertura</td>
            <td style="text-align:right;">${totCli.toLocaleString("pt-PT")}</td>
            <td style="text-align:right; color:#FBBF24;">${totFatZero.toLocaleString("pt-PT")}</td>
            <td style="text-align:right; color:#A78BFA;">${totMed20a.toLocaleString("pt-PT")}</td>
            <td style="text-align:right; color:#F87171;">${totLeit5m.toLocaleString("pt-PT")}</td>
            <td style="text-align:right; color:#FBBF24;">${(totIpKwh / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right;">${(totInj / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right;">${(totFat / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right; color:#F87171;">${taxaTot}% (${pntTot}%)</td>
            <td style="text-align:right;">—</td>
            <td style="text-align:right; color:#FBBF24;">${(totPrejPnt / 1e6).toFixed(1)}M</td>
            <td style="text-align:right; color:#F87171;">${totRisco.toLocaleString("pt-PT")}</td>
            <td colspan="2"></td>
          </tr>
        `;
      }
    }

    function selecionarPT3D(pt) {
      ptSelecionado3D = pt;
      atualizarCardPT(pt);
      renderizarMatrizPriorizacaoPTs();

      Object.entries(poligonosPorPT).forEach(([id, lyr]) => {
        if (id === pt.id) {
          lyr.setStyle({ weight: 4, fillOpacity: 0.48 });
          if (lyr.getBounds && mapMod2) {
            mapMod2.fitBounds(lyr.getBounds(), { padding: [40, 40], maxZoom: 16 });
          } else if (pt.lat && pt.lon && mapMod2) {
            mapMod2.setView([pt.lat, pt.lon], 16);
          }
        } else {
          lyr.setStyle({ weight: 2, fillOpacity: 0.24 });
        }
      });
    }

    function atualizarCardPT(pt) {
      if (!pt) return;
      const sel = document.getElementById("m2-filtro-pt");
      if (sel && sel.value !== pt.id) sel.value = pt.id;
      document.getElementById("pt-sel-codigo").textContent = `${pt.id} • ${pt.nome}`;
      document.getElementById("pt-sel-local").textContent = `Contador ${pt.contador || "--"} • ${pt.concelho}`;
      document.getElementById("pt-sel-taxa").textContent = `${pt.taxa.toFixed(1)}%`;
      document.getElementById("pt-sel-injetada").textContent = `${pt.injetada.toFixed(1)} MWh`;
      document.getElementById("pt-sel-faturada").textContent = `${pt.faturada.toFixed(1)} MWh`;
      document.getElementById("pt-sel-perda").textContent = `${pt.perda.toFixed(1)} MWh`;

      const pctFat = pt.injetada > 0 ? Math.min(100, Math.max(0, (pt.faturada / pt.injetada) * 100)) : 0;
      const pctTec = pt.injetada > 0 ? 5.0 : 0;
      const pctPnt = pt.injetada > 0 ? Math.min(100, Math.max(0, (pt.perda_pnt / pt.injetada) * 100)) : 0;
      const lblFat = document.getElementById("pt-lbl-fat-pct");
      const lblTec = document.getElementById("pt-lbl-tec-pct");
      const lblPerda = document.getElementById("pt-lbl-perda-pct");
      if (lblFat) lblFat.textContent = `📗 Faturada (Cli+IP • ${pctFat.toFixed(1)}%):`;
      if (lblTec) lblTec.textContent = `⚙️ Perda Técnica Ref. (5,0%):`;
      if (lblPerda) lblPerda.textContent = `🚨 Perda Não Técnica (PNT • ${pt.taxa_pnt.toFixed(1)}%):`;
      document.getElementById("pt-sel-tec").textContent = `${pt.perda_tecnica.toFixed(1)} MWh`;
      document.getElementById("pt-sel-perda").textContent = `${pt.perda_pnt.toFixed(1)} MWh`;
      document.getElementById("pt-bar-faturada").style.width = `${pctFat.toFixed(1)}%`;
      document.getElementById("pt-bar-tec").style.width = `${pctTec.toFixed(1)}%`;
      document.getElementById("pt-bar-perda").style.width = `${pctPnt.toFixed(1)}%`;

      document.getElementById("pt-sel-prejuizo").textContent = `~${Math.round(pt.prejuizo_pnt_ecv).toLocaleString("pt-PT")} ECV`;
      const dpp = pt.delta_taxa_pp;
      document.getElementById("pt-sel-delta").textContent = (dpp !== null && dpp !== undefined)
        ? `Δ Trim.: ${dpp > 0 ? "+" : ""}${Number(dpp).toFixed(1)} p.p.`
        : "Δ Trim.: 1º período";
      document.getElementById("pt-sel-divida").textContent = `${pt.divida.toLocaleString("pt-PT")} ECV`;
      document.getElementById("pt-sel-clientes").textContent = `${pt.clientes} clientes (${pt.qtd_fat_zero} fat. 0)`;
      document.getElementById("pt-sel-risco").textContent = `${pt.qtd_risco_alto} alto risco (${pt.clientes > 0 ? ((pt.qtd_risco_alto / pt.clientes) * 100).toFixed(1) : "0.0"}%)`;
      document.getElementById("pt-sel-cons-med").textContent = `Média: ${pt.consumo_medio_cli_mes.toFixed(1)} kWh/cli/mês • IP: ${pt.peso_ip_pct.toFixed(1)}%`;
      document.getElementById("pt-sel-insp").textContent = `${pt.insp_fraude} fraudes / ${pt.insp_total} insp.`;
      const diag = labelDiagnosticoPT(pt.diagnostico);
      const elDiag = document.getElementById("pt-sel-diag");
      if (elDiag) elDiag.innerHTML = `<span style="color:${diag.cor}; font-weight:700;">● ${diag.txt}</span>`;

      renderizarAlvosPT(pt);

      const badge = document.getElementById("pt-sel-badge");
      if (pt.status === "critico") {
        badge.className = "badge badge-danger";
        badge.textContent = "🚨 PERDA CRÍTICA";
      } else if (pt.status === "alerta") {
        badge.className = "badge badge-warn";
        badge.textContent = "⚠️ ALERTA DE PERDA";
      } else {
        badge.className = "badge badge-ok";
        badge.textContent = "📗 BALANÇO NORMAL";
      }
    }

    function renderizarAlvosPT(pt) {
      const tbody = document.getElementById("m2-tbody-alvos-pt");
      const lbl = document.getElementById("m2-alvos-pt-nome");
      if (lbl) lbl.textContent = pt ? pt.id : "--";
      if (!tbody) return;
      const lista = (pt && pt.top_cils_risco) ? pt.top_cils_risco : [];
      if (!lista.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:20px;">Sem clientes pontuados neste PT.</td></tr>`;
        return;
      }
      tbody.innerHTML = lista.map(c => {
        const corSc = c.score_v2 >= 80 ? "#F87171" : c.score_v2 >= 60 ? "#FBBF24" : "#34D399";
        return `
          <tr>
            <td style="font-family:var(--font-mono); font-weight:700; color:#60A5FA;">${c.cil}</td>
            <td style="font-size:11px; max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${c.nome}">${c.nome}</td>
            <td style="font-family:var(--font-mono); font-size:10.5px;">${c.tarifa || "--"}</td>
            <td style="text-align:right; font-family:var(--font-mono); font-weight:800; color:${corSc};">${c.score_v2} <span style="font-size:9.5px; color:var(--text-muted);">(${c.prob_pct}%)</span></td>
            <td style="text-align:right; font-family:var(--font-mono);">${Number(c.divida_ecv || 0).toLocaleString("pt-PT")}</td>
            <td style="font-size:10.5px; color:var(--text-secondary); max-width:210px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${c.motivos}">${c.motivos || "--"}</td>
          </tr>
        `;
      }).join("");
    }

    function exportarAlvosPTCSV() {
      if (!ptSelecionado3D || !ptSelecionado3D.top_cils_risco?.length) return;
      const cols = ["PT", "CIL", "Nome", "Tarifa", "Score_v2", "Prob_Fraude_Pct", "Divida_ECV", "Motivos"];
      const linhas = ptSelecionado3D.top_cils_risco.map(c => [
        ptSelecionado3D.id,
        c.cil,
        `"${String(c.nome || "").replace(/"/g, '""')}"`,
        c.tarifa || "",
        c.score_v2,
        c.prob_pct,
        c.divida_ecv,
        `"${String(c.motivos || "").replace(/"/g, '""')}"`
      ].join(";"));
      const csv = "\uFEFF" + [cols.join(";"), ...linhas].join("\n");
      salvarOuBaixarCSV(`alvos_inspecao_${ptSelecionado3D.id}_${trimestreAtualPT}.csv`, csv);
    }

    function renderizarMatrizPriorizacaoPTs() {
      const box = document.getElementById("m2-matriz-priorizacao");
      if (!box) return;
      const pts = DADOS_PTS_3D.filter(p => p.perda >= -50 && p.taxa >= -20 && p.taxa <= 105);
      if (!pts.length) {
        box.innerHTML = `<div style="padding:30px; text-align:center; color:var(--text-muted);">Sem dados para matriz.</div>`;
        return;
      }

      const w = 520, h = 280, padL = 48, padR = 18, padT = 16, padB = 34;
      const maxX = 100;
      const maxY = Math.max(100, ...pts.map(p => p.perda)) * 1.08;
      const sx = x => padL + (Math.max(0, Math.min(maxX, x)) / maxX) * (w - padL - padR);
      const sy = y => h - padB - (Math.max(0, y) / maxY) * (h - padT - padB);

      const perdasOrd = [...pts].map(p => p.perda).sort((a, b) => a - b);
      const medY = perdasOrd[Math.floor(perdasOrd.length / 2)] || 50;
      const x30 = sx(30), yMed = sy(medY);

      const bolhas = pts.map(p => {
        const cx = sx(p.taxa).toFixed(1);
        const cy = sy(p.perda).toFixed(1);
        const r = Math.max(4, Math.min(13, 3.5 + Math.sqrt(p.qtd_risco_alto || 1) * 1.1)).toFixed(1);
        const cor = corPorStatusPT(p.status);
        const ativo = ptSelecionado3D && ptSelecionado3D.id === p.id;
        return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${cor}" fill-opacity="${ativo ? 0.95 : 0.65}" stroke="${ativo ? "#FFFFFF" : cor}" stroke-width="${ativo ? 2.2 : 1}" style="cursor:pointer;" onclick="selecionarPT3DPorId('${p.id}')"><title>${p.id} (${p.nome})\nPerda: ${p.taxa.toFixed(1)}% (${p.perda.toFixed(1)} MWh)\nPrejuízo PNT: ~${(p.prejuizo_pnt_ecv / 1e6).toFixed(2)}M ECV\nRisco v2 >=70: ${p.qtd_risco_alto} cli.</title></circle>`;
      }).join("");

      box.innerHTML = `
        <svg viewBox="0 0 ${w} ${h}" style="width:100%; height:100%; display:block; font-family:var(--font-mono);">
          <rect x="${x30}" y="${padT}" width="${w - padR - x30}" height="${yMed - padT}" fill="#E15759" fill-opacity="0.07" />
          <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="var(--border-dim)" />
          <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h - padB}" stroke="var(--border-dim)" />
          <line x1="${x30}" y1="${padT}" x2="${x30}" y2="${h - padB}" stroke="#E15759" stroke-dasharray="4 3" stroke-opacity="0.65" />
          <line x1="${padL}" y1="${yMed}" x2="${w - padR}" y2="${yMed}" stroke="#FBBF24" stroke-dasharray="4 3" stroke-opacity="0.65" />
          <text x="${x30 + 4}" y="${padT + 11}" fill="#F87171" font-size="9" font-weight="700">30% Crítico</text>
          <text x="${padL + 4}" y="${yMed - 4}" fill="#FBBF24" font-size="9">Mediana: ${medY.toFixed(0)} MWh</text>
          <text x="${w / 2}" y="${h - 8}" text-anchor="middle" fill="var(--text-muted)" font-size="10">Taxa de Perda Total (%)</text>
          <text x="14" y="${h / 2}" text-anchor="middle" fill="var(--text-muted)" font-size="10" transform="rotate(-90 14 ${h / 2})">Perda (MWh)</text>
          <text x="${sx(0)}" y="${h - padB + 12}" text-anchor="middle" fill="var(--text-muted)" font-size="9">0%</text>
          <text x="${sx(50)}" y="${h - padB + 12}" text-anchor="middle" fill="var(--text-muted)" font-size="9">50%</text>
          <text x="${sx(100)}" y="${h - padB + 12}" text-anchor="middle" fill="var(--text-muted)" font-size="9">100%</text>
          <text x="${padL - 5}" y="${sy(maxY * 0.9) + 3}" text-anchor="end" fill="var(--text-muted)" font-size="9">${(maxY * 0.9).toFixed(0)}</text>
          ${bolhas}
        </svg>
      `;
    }

    function renderizarRankingPTs3D() {
      const container = document.getElementById("ranking-pts-3d-list");
      if (!container) return;

      const ordenados = [...DADOS_PTS_3D].sort((a, b) => b.perda - a.perda).slice(0, 5);
      container.innerHTML = ordenados.map((pt, i) => {
        const isAtivo = pt.id === ptSelecionado3D?.id ? "active" : "";
        const cor = pt.status === "critico" ? "#E15759" : (pt.status === "alerta" ? "#F28E2B" : "#59A14F");
        return `
          <div class="rank-item ${isAtivo}" onclick="selecionarPT3DPorId('${pt.id}')" style="border-left:3.5px solid ${cor};">
            <div class="rank-top">
              <span><b>#${i+1}</b> ${pt.id}</span>
              <span style="color:${cor}; font-weight:700;">${pt.taxa.toFixed(1)}% (${pt.perda.toFixed(1)} MWh)</span>
            </div>
            <div class="rank-metrics">
              <span>${pt.concelho}</span>
              <span style="font-family:var(--font-mono);">${pt.divida.toLocaleString("pt-PT")} ECV</span>
            </div>
            <div class="rank-bar-track">
              <div class="rank-bar-fill" style="width:${Math.min(100, Math.max(0, pt.taxa))}%; background:${cor};"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    function selecionarPT3DPorId(ptId) {
      const pt = DADOS_PTS_3D.find(p => p.id === ptId);
      if (pt) selecionarPT3D(pt);
    }

    function resetarCamera3D() {
      if (mapMod2) {
        desenharPoligonosPTs();
      }
    }

    function filtrarPTNaTriagem() {
      if (!ptSelecionado3D) return;
      selecionarModulo("mod1");
      if (typeof resetarFiltrosMod1Inputs === "function") {
        resetarFiltrosMod1Inputs();
      }
      const inputPT = document.getElementById("f-pt");
      const inputBusca = document.getElementById("f-busca");
      const tipoBusca = document.getElementById("f-tipo-busca");
      if (inputBusca) inputBusca.value = "";
      if (tipoBusca) tipoBusca.value = "auto";
      if (inputPT) inputPT.value = ptSelecionado3D.id;
      if (typeof aplicarFiltros === "function") {
        aplicarFiltros(1);
      }
    }

    function ativarMicrointeracaoTilt3D() {
      const cards = document.querySelectorAll(".kpi-card, .pnt-pattern-card, .action-card, .pt-card-balance");
      cards.forEach(card => {
        card.addEventListener("mousemove", (e) => {
          const rect = card.getBoundingClientRect();
          const x = e.clientX - rect.left;
          const y = e.clientY - rect.top;
          const cx = rect.width / 2;
          const cy = rect.height / 2;
          const rotX = ((y - cy) / cy) * -4;
          const rotY = ((x - cx) / cx) * 4;
          card.style.transform = `perspective(1000px) rotateX(${rotX}deg) rotateY(${rotY}deg) translateY(-2px)`;
        });
        card.addEventListener("mouseleave", () => {
          card.style.transform = "";
        });
      });
    }
