    // =========================================================================
    // PAINEL DE DIAGNÓSTICO PNT & PADRÕES DE PERDAS (MODULO 1)
    // =========================================================================
    function resetarFiltrosMod1Inputs() {
      ["f-busca", "f-prioridade", "f-risco", "f-ilha", "f-produto", "f-uni", "f-cf1", "f-cobranca", "f-estado", "f-grupo", "f-anomalia", "f-mat-cont", "f-mat-leit", "f-pt", "f-divida", "f-desvio"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = "";
      });
      const elOrdem = document.getElementById("f-ordem");
      if (elOrdem) elOrdem.value = "score_risco.desc.nullslast,valor.desc.nullslast";
      document.querySelectorAll(".pnt-pattern-card").forEach(c => c.classList.remove("active"));
    }

    function ativarPadraoPerda(padrao) {
      resetarFiltrosMod1Inputs();

      if (padrao === "bypass") {
        document.getElementById("card-pnt-bypass")?.classList.add("active");
        const elDesv = document.getElementById("f-desvio");
        const elEst = document.getElementById("f-estado");
        const elOrd = document.getElementById("f-ordem");
        if (elDesv) elDesv.value = "Desv_Fat";
        if (elEst) elEst.value = "Contrato em Vigor";
        if (elOrd) elOrd.value = "med_fat.desc.nullslast";
      } else if (padrao === "obsoleto") {
        document.getElementById("card-pnt-meter")?.classList.add("active");
        const elMat = document.getElementById("f-mat-cont");
        const elOrd = document.getElementById("f-ordem");
        if (elMat) elMat.value = "> 20 ano";
        if (elOrd) elOrd.value = "med_fat.desc.nullslast";
      } else if (padrao === "cegueira") {
        document.getElementById("card-pnt-blind")?.classList.add("active");
        const elMatL = document.getElementById("f-mat-leit");
        const elOrd = document.getElementById("f-ordem");
        if (elMatL) elMatL.value = "> 5 meses";
        if (elOrd) elOrd.value = "med_fat.desc.nullslast";
      } else if (padrao === "cf1_reincidente") {
        document.getElementById("card-pnt-cf1")?.classList.add("active");
        const elCf1 = document.getElementById("f-cf1");
        const elOrd = document.getElementById("f-ordem");
        if (elCf1) elCf1.value = "__REINCIDENTE__";
        if (elOrd) elOrd.value = "cf1_val_divida.desc.nullslast";
      }

      aplicarFiltros(1);
    }

    function atalhoAuditoria(tipo) {
      if (tipo === "critico") {
        const selR = document.getElementById("f-risco");
        selR.value = (selR.value === "CRÍTICO") ? "" : "CRÍTICO";
      } else if (tipo === "cf1") {
        const selCf1 = document.getElementById("f-cf1");
        selCf1.value = (selCf1.value === "__COM_CF1__") ? "" : "__COM_CF1__";
      } else if (tipo === "sem_pagamento") {
        const selCob = document.getElementById("f-cobranca");
        selCob.value = (selCob.value === "Devedor Sem Pagamento 2026") ? "" : "Devedor Sem Pagamento 2026";
      } else if (tipo === "fraude") {
        document.getElementById("f-anomalia").value = "Suspeita de Fraude";
      }
      aplicarFiltros(1);
    }

    let ultimoTokenFiltro = 0;

    function resetarTodosFiltros() {
      ["f-busca", "f-prioridade", "f-risco", "f-ilha", "f-produto", "f-uni", "f-cf1", "f-cobranca", "f-estado", "f-grupo", "f-anomalia", "f-mat-cont", "f-mat-leit", "f-pt", "f-divida", "f-desvio"].forEach(id => {
        document.getElementById(id).value = "";
      });
      document.getElementById("f-tipo-busca").value = "auto";
      document.getElementById("f-ordem").value = "score_risco.desc.nullslast,valor.desc.nullslast";
      const elTitReset = document.getElementById("lbl-kpi-contratos-titulo");
      const elSubReset = document.getElementById("lbl-kpi-contratos-subtipo");
      if (elTitReset) elTitReset.textContent = "CONTRATOS SUL";
      if (elSubReset) elSubReset.textContent = "REGIÃO SUL";
      aplicarFiltros(1);
    }

    async function aplicarFiltros(pagina = 1, apenasPagina = false) {
      const tokenAtual = ++ultimoTokenFiltro;
      paginaAtual = pagina;
      const offset = (paginaAtual - 1) * PAGE_SIZE;
      const params = construirQueryParams();
      params.append("limit", PAGE_SIZE);
      params.append("offset", offset);

      const t0 = performance.now();
      const tbody = document.getElementById("tabela-corpo");
      tbody.innerHTML = `<tr><td colspan="20" style="text-align:center; padding:28px; color:var(--text-secondary);">Consultando Supabase...</td></tr>`;

      if (!apenasPagina) {
        atualizarKPIsERankings(tokenAtual);
        carregarMapaFiltrado(tokenAtual);
      }

      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?${params.toString()}`, {
          headers: { ...HEADERS, "Prefer": "count=exact" }
        });
        if (tokenAtual !== ultimoTokenFiltro) return;
        const ms = Math.round(performance.now() - t0);
        document.getElementById("latency-pill").textContent = `LATÊNCIA: ${ms} ms`;
        document.getElementById("conn-text").textContent = `ONLINE • SUPABASE (edec-app)`;

        const range = r.headers.get("Content-Range") || "0-0/0";
        const partes = range.split("/");
        totalRegistosFiltrados = parseInt(partes[1] || "0", 10);
        registosPaginaAtual = await r.json();

        document.getElementById("lbl-range").textContent = `${fmtInt(totalRegistosFiltrados)} contratos encontrados`;
        document.getElementById("table-total-badge").textContent = `${fmtInt(totalRegistosFiltrados)} registos`;

        renderizarTabela(registosPaginaAtual);
        atualizarPaginacao();
      } catch (e) {
        if (tokenAtual !== ultimoTokenFiltro) return;
        console.error("Erro na consulta:", e);
        document.getElementById("conn-text").textContent = "ERRO DE CONEXÃO";
        tbody.innerHTML = `<tr><td colspan="20" style="text-align:center; padding:28px; color:#F87171;">Erro ao comunicar com o Supabase: ${e.message}</td></tr>`;
      }
    }

    function badgeRisco(score, nivel) {
      const s = score || 0;
      const n = nivel || "BAIXO";
      if (n === "CRÍTICO") return `<span class="badge badge-danger">🔴 ${s} • CRÍTICO</span>`;
      if (n === "ALTO") return `<span class="badge badge-warn">🟠 ${s} • ALTO</span>`;
      if (n === "MÉDIO") return `<span class="badge badge-info">🟡 ${s} • MÉDIO</span>`;
      return `<span class="badge badge-ok">🟢 ${s} • BAIXO</span>`;
    }

    function renderizarBadgeCF1(row) {
      const qtd = row.cf1_qtd_autos || 0;
      if (qtd <= 0) return `<span style="color:var(--text-muted);">—</span>`;
      const jur = row.cf1_estado_juridico || "";
      const divCf1 = row.cf1_val_divida || 0;
      const corClasse = qtd >= 2 || divCf1 > 0 ? "badge-danger" : "badge-purple";
      const txtJur = jur === "Enviado ao MP" ? " • MP" : (jur === "A enviar ao MP" ? " • A Env.MP" : "");
      return `<span class="badge ${corClasse}" title="Estado Jurídico: ${jur} | Dívida CF1: ${fmtECV(divCf1)} | Evidência: ${row.cf1_evidencia_fotos || '—'}">⚖️ ${qtd}x CF1${txtJur}</span>`;
    }

    function renderizarBadgeCobranca(row) {
      const st = row.status_cobranca || "";
      const valCob = row.cob_valor_total || 0;
      const mat = row.cob_maturidade_predom ? ` (${row.cob_maturidade_predom})` : "";
      if (st === "Devedor Sem Pagamento 2026") {
        return `<span class="badge badge-danger" title="Cliente com dívida ativa e 0 ECV pago em 2026">🚨 S/ Pag. 2026</span>`;
      }
      if (valCob > 0) {
        const cls = st === "Devedor em Amortização" ? "badge-warn" : "badge-ok";
        return `<span class="badge ${cls}" title="${st} • ${row.cob_qtd_meses || 0} meses pagos (Últ: ${row.cob_ultimo_mes || '—'})${mat}">${fmtInt(valCob)} ECV${mat}</span>`;
      }
      return `<span style="color:var(--text-muted);">0 ECV</span>`;
    }

    
    // =========================================================================
    // SCORECARD DE PRIORIDADE DE VISTORIA DE CAMPO (ENGENHARIA PNT)
    // =========================================================================
    function calcularPrioridadeVistoria(row) {
      const score = Number(row.score_risco || 0);
      const desvio = row.faturacao_alerta_desvio === "Desv_Fat";
      const cf1Qtd = Number(row.cf1_qtd_autos || 0);
      const cf1Jur = row.cf1_estado_juridico || "";
      const medFat = Number(row.med_fat || 0);
      const t3 = Number(row.faturacao_t3 || 0);
      const estCtr = row.est_ctr || "";
      const matLeit = row.mat_leitura || "";
      const matCont = row.mat_contador || "";
      const anom = row.anomalia || "";

      // Cálculo de Perda Estimada em ECV/mês (Tarifa Média: 26 ECV/kWh)
      let kwhPerdido = 0;
      if (desvio && medFat > 0) {
        kwhPerdido = medFat; // Consumo mensal esperado que zerou no trimestre
      } else if (matCont === "> 20 ano" && medFat > 0) {
        kwhPerdido = Math.round(medFat * 0.20); // Submedição típica de 20%
      }
      const perdaEcvMes = Math.round(kwhPerdido * 26);

      // Classificação 1 a 5 Estrelas
      // P1: Emergencial 24h
      if ((cf1Qtd >= 2 || cf1Jur === "Enviado ao MP" || cf1Jur === "A enviar ao MP") || (desvio && medFat >= 150 && estCtr === "Contrato em Vigor")) {
        return {
          nivel: 1,
          badge: `<span class="badge badge-danger" style="font-weight:700; background:rgba(239,68,68,0.25); border-color:#EF4444;" title="Intervenção em 24h: Fraude Reincidente ou Bypass de Alto Consumo">🚨 P1 • 24h ⭐⭐⭐⭐⭐</span>`,
          perdaEcvMes: perdaEcvMes,
          rotulo: "Emergencial 24h",
          instrucao: "Vistoria prioritária com brigada especializada. Inspecionar ramal aéreo/subterrâneo antes do medidor, testar carga com pinça amperimétrica e verificar selos."
        };
      }

      // P2: Crítico 72h
      if (desvio && estCtr === "Contrato em Vigor") {
        return {
          nivel: 2,
          badge: `<span class="badge badge-danger" title="Intervenção em 72h: Queda Brusca de Consumo (Desv_Fat)">🔥 P2 • 72h ⭐⭐⭐⭐</span>`,
          perdaEcvMes: perdaEcvMes,
          rotulo: "Crítico 72h",
          instrucao: "Inspecionar medição direta. Confrontar leitura atual com histórico e verificar se houve desvio de fase ou religação à revelia."
        };
      }

      // P3: Alta Prioridade 7d
      if (cf1Qtd === 1 || (matLeit === "> 5 meses" && anom) || score >= 40) {
        return {
          nivel: 3,
          badge: `<span class="badge badge-warn" title="Intervenção em 7 dias: Histórico CF1 ou Cegueira de Leitura c/ Anomalia">⚠️ P3 • 7d ⭐⭐⭐</span>`,
          perdaEcvMes: perdaEcvMes,
          rotulo: "Alta Prioridade",
          instrucao: "Auditoria de rota de leitura. Realizar ensaio de rotação de disco/pulsos LED e registrar foto da fachada e padrão de entrada."
        };
      }

      // P4: Troca Programada de Medidor
      if (matCont === "> 20 ano" || matLeit === "> 5 meses") {
        return {
          nivel: 4,
          badge: `<span class="badge" style="background:#1E1B4B; color:#C7D2FE; border:1px solid #4338CA;" title="Plano de Troca de Medidor Obsoleto ou Visita de Leiturista">📟 P4 • Rota ⭐⭐</span>`,
          perdaEcvMes: perdaEcvMes,
          rotulo: "Troca Programada",
          instrucao: "Agendar substituição por medidor eletrônico moderno de telemedição ou inspeção de acessibilidade ao contador."
        };
      }

      // P5: Monitoramento Regular
      return {
        nivel: 5,
        badge: `<span class="badge badge-ok" style="opacity:0.8;" title="Parâmetros Regulares de Consumo">✅ P5 • Regular ⭐</span>`,
        perdaEcvMes: 0,
        rotulo: "Monitoramento Regular",
        instrucao: "Manter no ciclo regular de leitura e faturação comercial."
      };
    }

    function renderizarTabela(linhas) {
      const tbody = document.getElementById("tabela-corpo");
      if (!linhas.length) {
        tbody.innerHTML = `<tr><td colspan="20" style="text-align:center; padding:32px; color:var(--text-muted);">Nenhum contrato encontrado com os filtros selecionados.</td></tr>`;
        return;
      }

      tbody.innerHTML = linhas.map((row, idx) => {
        const estBadge = row.est_ctr === "Contrato em Vigor"
          ? `<span class="badge badge-ok">${row.est_ctr}</span>`
          : `<span class="badge badge-warn">${row.est_ctr || "—"}</span>`;

        const matLeitBadge = row.mat_leitura === "< 5 meses"
          ? `<span class="badge badge-ok" title="Última leitura: ${row.data_leitura || '—'}">&lt; 5m</span>`
          : (row.mat_leitura === "> 5 meses"
              ? `<span class="badge badge-warn" title="Última leitura: ${row.data_leitura || '—'}">&gt; 5m</span>`
              : `<span style="color:var(--text-muted);">—</span>`);

        const anomBadge = row.anomalia
          ? `<span class="badge badge-danger">${row.anomalia}</span>`
          : `<span style="color:var(--text-muted);">—</span>`;

        const desvBadge = row.faturacao_alerta_desvio === "Desv_Fat"
          ? `<span class="badge badge-danger">Desv_Fat</span>`
          : `<span style="color:var(--text-muted);">Normal</span>`;

        const valorFmt = row.valor > 0
          ? `<strong style="color:#FBBF24;">${Number(row.valor).toLocaleString("pt-PT", { maximumFractionDigits: 0 })}</strong>`
          : `<span style="color:var(--text-muted);">0</span>`;

        const prio = calcularPrioridadeVistoria(row);
        const perdaBadge = prio.perdaEcvMes > 0
          ? `<strong style="color:#F87171; font-family:var(--font-mono); font-size:11.5px;">+${fmtInt(prio.perdaEcvMes)} ECV</strong>`
          : `<span style="color:var(--text-muted); font-size:11px;">—</span>`;

        return `
          <tr onclick="abrirDossie(${idx})">
            <td style="white-space:nowrap;">${prio.badge}</td>
            <td class="num-right">${perdaBadge}</td>
            <td>${badgeRisco(row.score_risco, row.nivel_risco)}</td>
            <td class="mono-cell" style="color:var(--accent-cyan); font-weight:600;">${row.cil}</td>
            <td>${row.desc_uni || "—"}</td>
            <td>${row.localidade || "—"}</td>
            <td class="mono-cell" style="color:#E2E8F0;">${(row.pt || "—").trim()}</td>
            <td style="font-weight:500;">
              ${row.nome || "—"}
              ${Number(row.qtd_clientes_distintos || 1) > 1 ? `<span class="badge" style="margin-left:5px; font-size:10px; padding:1px 5px; background:rgba(56,189,248,0.14); color:#38BDF8; border:1px solid rgba(56,189,248,0.35);" title="Local de consumo com ${row.qtd_clientes_distintos} titulares distintos (${row.qtd_contratos_hist || 1} contratos no histórico). Dívida outros titulares: ${fmtECV(row.divida_outros_titulares || 0)}">👥 ${row.qtd_clientes_distintos} tit.</span>` : ""}
              ${Number(row.divida_outros_titulares || 0) > 0 ? `<span class="badge badge-warn" style="margin-left:3px; font-size:10px; padding:1px 5px;" title="Atenção: ${fmtECV(row.divida_outros_titulares)} da dívida deste CIL pertence a titular(es) anterior(es)">⚠️ Dív. Ant.</span>` : ""}
            </td>
            <td>${estBadge}</td>
            <td>${renderizarBadgeCF1(row)}</td>
            <td>${renderizarBadgeCobranca(row)}</td>
            <td class="mono-cell">${row.contador || "—"}</td>
            <td>${matLeitBadge}</td>
            <td>${anomBadge}</td>
            <td style="font-size:11.5px; color:var(--text-secondary);" title="${row.motivo_risco || ''}">${row.motivo_risco || "—"}</td>
            <td class="num-right">${row.faturacao_t3 !== null ? fmtInt(row.faturacao_t3) : "0"}</td>
            <td class="num-right" style="color:var(--accent-cyan); font-weight:600;">${fmtInt(row.med_fat)}</td>
            <td>${desvBadge}</td>
            <td class="num-right">${row.qtd || 0}</td>
            <td class="num-right">${valorFmt}</td>
          </tr>
        `;
      }).join("");
    }

    async function carregarMapaFiltrado(tokenAtual) {
      const badge = document.getElementById("map-count-badge");
      const maxMapPoints = parseInt(document.getElementById("map-limit")?.value || "2000", 10);
      badge.textContent = "⏳ Carregando georref...";

      try {
        const baseParams = construirQueryParams();
        baseParams.append("lat", "not.is.null");
        baseParams.append("long", "not.is.null");
        baseParams.append("select", "cil,nome,localidade,desc_uni,pt,lat,long,score_risco,nivel_risco,motivo_risco,valor,qtd,cf1_qtd_autos,cf1_estado_juridico,cob_valor_total,status_cobranca");

        // 1º lote de 1.000 + contagem exata de todos os pontos georreferenciados do filtro
        const p1 = new URLSearchParams(baseParams);
        p1.append("limit", "1000");
        p1.append("offset", "0");

        const r1 = await fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?${p1.toString()}`, {
          headers: { ...HEADERS, "Prefer": "count=exact" }
        });
        if (tokenAtual && tokenAtual !== ultimoTokenFiltro) return;

        const range = r1.headers.get("Content-Range") || "0-0/0";
        const totalGeo = parseInt((range.split("/")[1]) || "0", 10);
        let todosPontos = await r1.json();
        if (!Array.isArray(todosPontos)) todosPontos = [];

        const alvoTotal = Math.min(totalGeo, maxMapPoints);
        if (alvoTotal > 1000 && todosPontos.length === 1000) {
          const offsets = [];
          for (let off = 1000; off < alvoTotal; off += 1000) {
            offsets.push(off);
          }
          // Carregar lotes em paralelo (4 por vez)
          for (let i = 0; i < offsets.length; i += 4) {
            if (tokenAtual && tokenAtual !== ultimoTokenFiltro) return;
            const grupo = offsets.slice(i, i + 4);
            badge.textContent = `⏳ Mapa: ${fmtInt(todosPontos.length)} / ${fmtInt(alvoTotal)}...`;
            const lotes = await Promise.all(grupo.map(async (off) => {
              const p = new URLSearchParams(baseParams);
              p.append("limit", "1000");
              p.append("offset", String(off));
              const res = await fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?${p.toString()}`, { headers: HEADERS });
              return res.json();
            }));
            lotes.forEach(arr => {
              if (Array.isArray(arr)) todosPontos.push(...arr);
            });
          }
        }

        if (tokenAtual && tokenAtual !== ultimoTokenFiltro) return;
        atualizarMapa(todosPontos, totalGeo);
      } catch (e) {
        console.error("Erro ao carregar mapa filtrado:", e);
        badge.textContent = "Erro ao carregar mapa";
      }
    }

    function atualizarMapa(linhas, totalGeoFiltro = null) {
      markersLayer.clearLayers();
      const coords = [];

      linhas.forEach((row) => {
        if (!row.lat || !row.long) return;
        const lat = parseFloat(String(row.lat).replace(",", ".").trim());
        const lng = parseFloat(String(row.long).replace(",", ".").trim());
        if (isNaN(lat) || isNaN(lng) || lat < 14 || lat > 18 || lng < -26 || lng > -22) return;

        coords.push([lat, lng]);
        const n = row.nivel_risco || "BAIXO";
        const cor = n === "CRÍTICO" ? "#EF4444" : (n === "ALTO" ? "#F59E0B" : (n === "MÉDIO" ? "#06B6D4" : "#10B981"));

        const marker = L.circleMarker([lat, lng], {
          radius: n === "CRÍTICO" ? 7 : (n === "ALTO" ? 6 : 4.5),
          fillColor: cor,
          color: "#070A0F",
          weight: 1.2,
          opacity: 1,
          fillOpacity: 0.9
        });

        marker.bindPopup(`
          <div style="font-family:'IBM Plex Sans',sans-serif; min-width:240px; color:#0F172A;">
            <div style="font-weight:700; font-size:13px; margin-bottom:4px;">CIL ${row.cil} • ${row.nome || ""}</div>
            <div style="font-size:12px; margin-bottom:4px;"><strong>Score Risco:</strong> <span style="color:#DC2626; font-weight:700;">${row.score_risco || 0}/100 (${row.nivel_risco || "BAIXO"})</span></div>
            <div style="font-size:11.5px; color:#475569; margin-bottom:4px;">${row.motivo_risco || ""}</div>
            <div style="font-size:12px;"><strong>Localidade:</strong> ${row.localidade || "—"} (${row.desc_uni || ""})</div>
            <div style="font-size:12px;"><strong>PT:</strong> ${(row.pt || "—").trim()}</div>
            <div style="font-size:12px;"><strong>Dívida Geral:</strong> ${fmtECV(row.valor)} (${row.qtd || 0} fat.)</div>
            <div style="font-size:12px;"><strong>Autos CF1:</strong> ${row.cf1_qtd_autos || 0} (${row.cf1_estado_juridico || "Sem Auto"})</div>
            <div style="font-size:12px;"><strong>Cobrança 2026:</strong> ${fmtECV(row.cob_valor_total)} (${row.status_cobranca || "—"})</div>
            <button onclick="abrirDossiePorCIL(${row.cil})" style="margin-top:8px; width:100%; padding:6px; background:#0F172A; color:#fff; border:none; border-radius:4px; cursor:pointer; font-weight:600;">
              📋 Ver Dossiê Completo (CIL ${row.cil})
            </button>
          </div>
        `);

        markersLayer.addLayer(marker);
      });

      const sufixoTotal = (totalGeoFiltro !== null && totalGeoFiltro > coords.length)
        ? ` de ${fmtInt(totalGeoFiltro)} georref.`
        : ` georref. no filtro`;
      document.getElementById("map-count-badge").textContent = `${fmtInt(coords.length)}${sufixoTotal}`;
      if (coords.length > 0) {
        map.fitBounds(L.latLngBounds(coords), { padding: [28, 28], maxZoom: 16 });
      }
    }

    function atualizarPaginacao() {
      const totalPaginas = Math.max(1, Math.ceil(totalRegistosFiltrados / PAGE_SIZE));
      document.getElementById("pag-info").textContent =
        `Página ${paginaAtual} de ${fmtInt(totalPaginas)} • (${fmtInt(totalRegistosFiltrados)} contratos filtrados)`;
      document.getElementById("btn-prev").disabled = paginaAtual <= 1;
      document.getElementById("btn-next").disabled = paginaAtual >= totalPaginas;
    }

    function mudarPagina(delta) {
      const nova = paginaAtual + delta;
      if (nova < 1) return;
      aplicarFiltros(nova, true);
    }

    async function abrirDossiePorCIL(cil) {
      const local = registosPaginaAtual.find(x => Number(x.cil) === Number(cil)) || (typeof registosDividaPagina !== 'undefined' ? registosDividaPagina.find(x => Number(x.cil) === Number(cil)) : null);
      if (local) {
        renderizarDossieObjeto(local);
        return;
      }
      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?cil=eq.${cil}&limit=1`, { headers: HEADERS });
        const d = await r.json();
        if (Array.isArray(d) && d.length > 0) {
          renderizarDossieObjeto(d[0]);
        }
      } catch (e) {
        console.error("Erro ao abrir dossiê por CIL:", e);
      }
    }

    function abrirDossie(idx) {
      const r = registosPaginaAtual[idx];
      if (!r) return;
      renderizarDossieObjeto(r);
    }

    let ultimoDossieCliente = null;

    function fmtDataOitoDigitos(s) {
      if (!s) return "—";
      const limpo = String(s).trim();
      if (limpo.length === 8 && /^\d{8}$/.test(limpo) && limpo !== "00000000") {
        return `${limpo.slice(0, 4)}-${limpo.slice(4, 6)}-${limpo.slice(6, 8)}`;
      }
      return limpo;
    }

    function nomeEmpresaCodigo(cod) {
      const c = String(cod || "").trim().replace(/^0+/, "");
      if (c === "17") return "17 • EDEC SA";
      if (c === "21") return "21 • ELECTRA SA";
      if (c === "7")  return "07 • EDEC Sul";
      if (c === "70") return "70 • ELECTRA SARL";
      return c || "—";
    }

    function renderizarSecaoHistoricoContratos(r) {
      let hist = [];
      if (Array.isArray(r.historico_contratos)) {
        hist = r.historico_contratos;
      } else if (typeof r.historico_contratos === "string" && r.historico_contratos.trim().startsWith("[")) {
        try { hist = JSON.parse(r.historico_contratos); } catch (_) { hist = []; }
      }
      const qtdCtr = Number(r.qtd_contratos_hist || hist.length || 1);
      const qtdCli = Number(r.qtd_clientes_distintos || 1);
      const divTitAtual = Number(r.divida_titular_atual ?? r.valor ?? 0);
      const divOutros = Number(r.divida_outros_titulares || 0);
      const temOutros = divOutros > 0 || qtdCli > 1;

      const linhasHtml = hist.map((h) => {
        const ehAtual = Number(h.id) === Number(r.id_cliente);
        const divH = Number(h.divida || 0);
        const badgeTit = ehAtual
          ? `<span class="badge badge-ok" style="font-size:9.5px; padding:1px 5px; margin-left:4px;">TITULAR ATUAL</span>`
          : `<span class="badge badge-warn" style="font-size:9.5px; padding:1px 5px; margin-left:4px;">ANTERIOR</span>`;
        const vig = `${fmtDataOitoDigitos(h.dt_ini)} → ${h.dt_baixa ? fmtDataOitoDigitos(h.dt_baixa) : "Ativo"}`;
        return `
          <tr style="border-bottom:1px solid rgba(148,163,184,0.12); background:${ehAtual ? 'rgba(16,185,129,0.05)' : 'transparent'};">
            <td style="padding:6px 8px; font-family:var(--font-mono); font-size:11px; color:#93C5FD;">${nomeEmpresaCodigo(h.emp)}</td>
            <td style="padding:6px 8px; font-family:var(--font-mono); font-size:11px;">${h.id || "—"}${badgeTit}</td>
            <td style="padding:6px 8px; font-size:11.5px; font-weight:600; color:var(--text-primary);">${h.nome || "—"}</td>
            <td style="padding:6px 8px; font-family:var(--font-mono); font-size:11px;">${h.prod || "—"}</td>
            <td style="padding:6px 8px; font-size:11px; color:var(--text-secondary);">${h.est || "—"}</td>
            <td style="padding:6px 8px; font-family:var(--font-mono); font-size:10.5px; color:var(--text-muted);">${vig}</td>
            <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono); font-size:11.5px; font-weight:700; color:${divH > 0 ? (ehAtual ? '#FBBF24' : '#F87171') : 'var(--text-muted)'};">
              ${divH > 0 ? `${fmtECV(divH)} (${h.faturas || 0} fat.)` : "0 ECV"}
            </td>
          </tr>
        `;
      }).join("");

      return `
        <div class="dossier-section" style="border-color:${temOutros ? 'rgba(56,189,248,0.45)' : 'var(--border-dim)'}; background:${temOutros ? 'rgba(56,189,248,0.05)' : 'var(--bg-input)'};">
          <h4 style="color:#38BDF8;">📜 2.5. Histórico de Contratos &amp; Titulares no CIL (Empresas 17, 21, 07, 70)</h4>
          <div class="dossier-grid" style="margin-bottom:${hist.length ? '10px' : '0'};">
            <div class="kv-item"><div class="k">Contratos no CIL</div><div class="v" style="color:#38BDF8;">${qtdCtr} contrato(s)</div></div>
            <div class="kv-item"><div class="k">Titulares Distintos (ID)</div><div class="v" style="color:${qtdCli > 1 ? '#FBBF24' : '#34D399'};">${qtdCli} cliente(s)</div></div>
            <div class="kv-item"><div class="k">Dívida Titular Atual (ID ${r.id_cliente || "—"})</div><div class="v" style="color:#FBBF24;">${fmtECV(divTitAtual)}</div></div>
            <div class="kv-item"><div class="k">Dívida Outros Titulares (Anteriores)</div><div class="v" style="color:${divOutros > 0 ? '#F87171' : '#34D399'}; font-weight:700;">${fmtECV(divOutros)}</div></div>
          </div>
          ${hist.length ? `
            <div style="overflow-x:auto; border:1px solid var(--border-dim); border-radius:6px; background:rgba(7,10,15,0.55);">
              <table style="width:100%; border-collapse:collapse; text-align:left;">
                <thead>
                  <tr style="border-bottom:1px solid var(--border-dim); font-size:10.5px; color:var(--text-muted); text-transform:uppercase;">
                    <th style="padding:6px 8px;">Empresa</th>
                    <th style="padding:6px 8px;">ID Conta</th>
                    <th style="padding:6px 8px;">Titular / Cliente</th>
                    <th style="padding:6px 8px;">Prod.</th>
                    <th style="padding:6px 8px;">Estado</th>
                    <th style="padding:6px 8px;">Vigência</th>
                    <th style="padding:6px 8px; text-align:right;">Dívida Conta</th>
                  </tr>
                </thead>
                <tbody>${linhasHtml}</tbody>
              </table>
            </div>
          ` : ""}
        </div>
      `;
    }

    function renderizarDossieObjeto(r) {
      if (!r) return;
      ultimoDossieCliente = r;

      const ehAdS = (Number(r.cil) === 60220187 || Number(r.cil) === 60220188 || Number(r.id_cliente) === 60209538 || (r.nome && r.nome.toUpperCase().includes("AGUAS DE SANTIAGO")));
      const badgeAdS = ehAdS
        ? " • 💧 CONTA ESPECIAL AdS (ÁGUA)"
        : ((r.produto === "AG" || Number(r.divida_ag || 0) > 0) ? " • 🚰 CLIENTE DE ÁGUA (AG)" : "");
      document.getElementById("d-badge-uc").textContent = `${r.desc_uni || "SANTIAGO"} • ${r.grup_tp_cli || "—"}${badgeAdS}`;
      document.getElementById("d-nome").textContent = r.nome || "CLIENTE SEM NOME";
      document.getElementById("d-sub").textContent = `CIL: ${r.cil} | NIB: ${r.nib || "—"} | CIL_ID: ${r.cil_id || "—"}`;

      const lat = r.lat ? String(r.lat).trim() : null;
      const lng = r.long ? String(r.long).trim() : null;
      const gmapsUrl = (lat && lng) ? `https://www.google.com/maps?q=${lat},${lng}` : null;

      const temCf1 = (r.cf1_qtd_autos || 0) > 0;

      document.getElementById("drawer-content").innerHTML = `
        <div class="dossier-section" style="border-color:rgba(239,68,68,0.45); background:rgba(239,68,68,0.06);">
          <h4>🔥 Diagnóstico do Motor de Score de Risco de Fraude / Perdas</h4>
          <div class="dossier-grid">
            <div class="kv-item"><div class="k">Score de Risco (0 a 100)</div><div class="v" style="font-size:18px; color:#F87171;">${r.score_risco || 0} / 100</div></div>
            <div class="kv-item"><div class="k">Prioridade de Inspeção</div><div class="v">${badgeRisco(r.score_risco, r.nivel_risco)}</div></div>
          </div>
          <div class="kv-item" style="margin-top:10px;">
            <div class="k">Fatores de Risco Detetados</div>
            <div class="v" style="color:#FBBF24; font-size:12.5px;">${r.motivo_risco || "Normal / Sem Indícios"}</div>
          </div>
        </div>

        <!-- Bloco de Engenharia de Vistoria de Campo -->
        <div class="dossier-section" style="border-color:rgba(245,158,11,0.45); background:rgba(245,158,11,0.06);">
          <h4>🎯 Classificação de Prioridade de Vistoria &amp; Perda Estimada</h4>
          <div class="dossier-grid">
            <div class="kv-item">
              <div class="k">Nível de Prioridade de Campo</div>
              <div class="v">${calcularPrioridadeVistoria(r).badge}</div>
            </div>
            <div class="kv-item">
              <div class="k">Perda Financeira Mensal Estimada</div>
              <div class="v" style="color:#F87171; font-weight:700;">${calcularPrioridadeVistoria(r).perdaEcvMes > 0 ? '+' + fmtECV(calcularPrioridadeVistoria(r).perdaEcvMes) + '/mês' : 'Sem desvio relevante'}</div>
            </div>
          </div>
          <div class="kv-item" style="margin-top:10px;">
            <div class="k">Protocolo Técnico Recomendado para a Brigada</div>
            <div class="v" style="color:var(--text-primary); font-size:12px; line-height:1.5;">${calcularPrioridadeVistoria(r).instrucao}</div>
          </div>
        </div>

        <div class="dossier-section" style="border-color:${temCf1 ? 'rgba(168,85,247,0.5)' : 'var(--border-dim)'}; background:${temCf1 ? 'rgba(168,85,247,0.06)' : 'var(--bg-input)'};">
          <h4 style="color:#C084FC;">⚖️ 1. Histórico de Autos de Fraude (CF1) &amp; Processo Jurídico</h4>
          <div class="dossier-grid">
            <div class="kv-item"><div class="k">Qtd. Autos CF1 Registados</div><div class="v" style="color:${temCf1 ? '#C084FC' : 'var(--text-muted)'}; font-size:15px;">${r.cf1_qtd_autos || 0} auto(s) ${r.cf1_qtd_autos >= 2 ? '🔥 (REINCIDENTE)' : ''}</div></div>
            <div class="kv-item"><div class="k">Último Ano de Auto CF1</div><div class="v">${r.cf1_ultimo_ano || "—"}</div></div>
            <div class="kv-item"><div class="k">Energia Faturada CF1 (QTD)</div><div class="v">${r.cf1_kwh_total ? fmtInt(r.cf1_kwh_total) + " kWh" : "0 kWh"}</div></div>
            <div class="kv-item"><div class="k">Valor Total Faturado CF1</div><div class="v">${fmtECV(r.cf1_val_total || 0)}</div></div>
            <div class="kv-item"><div class="k">Dívida CF1 em Aberto (VAL_DIV)</div><div class="v" style="color:${(r.cf1_val_divida || 0) > 0 ? '#F87171' : '#34D399'};">${fmtECV(r.cf1_val_divida || 0)}</div></div>
            <div class="kv-item"><div class="k">Estado Comercial da Dívida CF1</div><div class="v">${r.cf1_estado_divida || "Sem Registo"}</div></div>
            <div class="kv-item"><div class="k">Estado Processo Jurídico (MP)</div><div class="v" style="color:#FBBF24;">${r.cf1_estado_juridico || "Sem Processo"}</div></div>
            <div class="kv-item"><div class="k">Evidência Fotográfica (Base)</div><div class="v">${r.cf1_evidencia_fotos || "—"}</div></div>
          </div>
        </div>

        <div class="dossier-section" style="border-color:rgba(16,185,129,0.35);">
          <h4 style="color:#34D399;">💳 2. Telemetria de Cobrança 2026 &amp; Maturidade (COB_J)</h4>
          <div class="dossier-grid">
            <div class="kv-item"><div class="k">Status de Cobrança 2026</div><div class="v" style="color:${r.status_cobranca === 'Devedor Sem Pagamento 2026' ? '#F87171' : '#34D399'};">${r.status_cobranca || "—"}</div></div>
            <div class="kv-item"><div class="k">Total Pago em 2026</div><div class="v" style="font-size:15px; color:#34D399;">${fmtECV(r.cob_valor_total || 0)}</div></div>
            <div class="kv-item"><div class="k">Regularidade (Meses Pagos)</div><div class="v">${r.cob_qtd_meses || 0} mês(es) em 2026</div></div>
            <div class="kv-item"><div class="k">Último Mês com Cobrança</div><div class="v">${r.cob_ultimo_mes || "Nenhum pagamento em 2026"}</div></div>
            <div class="kv-item"><div class="k">Maturidade Predominante</div><div class="v" style="color:var(--accent-cyan);">${r.cob_maturidade_predom || "—"}</div></div>
            <div class="kv-item"><div class="k">Pago de Dívida Antiga (≥ 3m)</div><div class="v">${fmtECV(r.cob_valor_atraso || 0)}</div></div>
          </div>
        </div>

        ${renderizarSecaoHistoricoContratos(r)}

        <div class="dossier-section">
          <h4>3. Identificação Contratual e Comercial</h4>
          <div class="dossier-grid">
            <div class="kv-item"><div class="k">CIL (Ponto Entrega)</div><div class="v" style="color:var(--accent-cyan);">${r.cil}</div></div>
            <div class="kv-item"><div class="k">NIB</div><div class="v">${r.nib || "—"}</div></div>
            <div class="kv-item"><div class="k">ID Cliente (Conta)</div><div class="v">${r.id_cliente || "—"}</div></div>
            <div class="kv-item"><div class="k">Chave CIL_ID</div><div class="v">${r.cil_id || "—"}</div></div>
            <div class="kv-item"><div class="k">Estado do Contrato</div><div class="v">${r.est_ctr || "—"}</div></div>
            <div class="kv-item"><div class="k">Grupo Tipo Cliente</div><div class="v">${r.grup_tp_cli || "—"}</div></div>
            <div class="kv-item"><div class="k">Produto / Tarifa</div><div class="v">${r.produto || "—"} / ${r.tarifa || "—"}</div></div>
            <div class="kv-item"><div class="k">Inspeção IMTT (TIP)</div><div class="v">${r.tip || "Não registado"}</div></div>
          </div>
        </div>

        <div class="dossier-section">
          <h4>4. Medição, Aparelho e Faturação Trimestral (T3)</h4>
          <div class="dossier-grid">
            <div class="kv-item"><div class="k">Nº Contador / Modelo</div><div class="v" style="color:#FBBF24;">${r.contador || "Sem Contador"} (${r.modelo || "—"})</div></div>
            <div class="kv-item"><div class="k">Data Instalação</div><div class="v">${r.da_inst || "—"} (${r.mat_contador || "—"})</div></div>
            <div class="kv-item"><div class="k">Data Última Leitura</div><div class="v" style="color:${r.mat_leitura === '> 5 meses' ? '#FBBF24' : '#34D399'};">${r.data_leitura || "—"} (${r.mat_leitura || "—"})</div></div>
            <div class="kv-item"><div class="k">Anomalia de Leitura</div><div class="v" style="color:${r.anomalia ? '#F87171' : '#34D399'};">${r.anomalia || "Nenhuma Anomalia"}</div></div>
            <div class="kv-item"><div class="k">Dívida Acumulada Geral (VALOR)</div><div class="v" style="color:#FBBF24; font-size:15px;">${fmtECV(r.valor)} (${r.qtd || 0} fat.)</div></div>
            <div class="kv-item"><div class="k">Consumo T3 / Média Mensal</div><div class="v">${r.faturacao_t3 !== null ? fmtInt(r.faturacao_t3) : "0"} kWh (${fmtInt(r.med_fat)} kWh/mês)</div></div>
          </div>
        </div>

        <div class="dossier-section">
          <h4>5. Localização Geográfica e Rede de Distribuição (PT)</h4>
          <div class="dossier-grid">
            <div class="kv-item"><div class="k">Unidade / Localidade</div><div class="v">${r.desc_uni || "—"} / ${r.localidade || "—"}</div></div>
            <div class="kv-item"><div class="k">Posto Transformação (PT)</div><div class="v" style="color:var(--accent-cyan);">${(r.pt || "Não associado").trim()}</div></div>
            <div class="kv-item"><div class="k">Latitude</div><div class="v">${lat || "—"}</div></div>
            <div class="kv-item"><div class="k">Longitude</div><div class="v">${lng || "—"}</div></div>
          </div>
          ${gmapsUrl ? `
            <div style="margin-top:12px;">
              <a href="${gmapsUrl}" target="_blank" class="btn btn-amber" style="width:100%; justify-content:center; text-decoration:none;">
                📍 Abrir Coordenadas Exatas no Google Maps (${lat}, ${lng})
              </a>
            </div>
          ` : ""}
        </div>
      `;

      document.getElementById("drawer-backdrop").classList.add("open");
    }

    function fecharDossie() {
      document.getElementById("drawer-backdrop").classList.remove("open");
    }

    async function exportarCSVFiltrado() {
      const btn = document.getElementById("btn-export");
      const txtOrig = btn.textContent;
      btn.disabled = true;

      try {
        const baseParams = construirQueryParams();
        btn.textContent = "⏳ A iniciar exportação...";

        // 1º lote de 1.000 + contagem total exata
        const p1 = new URLSearchParams(baseParams);
        p1.append("limit", "1000");
        p1.append("offset", "0");

        const r1 = await fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?${p1.toString()}`, {
          headers: { ...HEADERS, "Prefer": "count=exact" }
        });
        const range = r1.headers.get("Content-Range") || "0-0/0";
        const totalExportar = parseInt((range.split("/")[1]) || "0", 10);
        let dados = await r1.json();
        if (!Array.isArray(dados) || !dados.length) {
          alert("Nenhum registo para exportar com o filtro atual.");
          return;
        }

        // Paginar em lotes paralelos de 1.000 até obter 100% dos registos filtrados
        if (totalExportar > 1000 && dados.length === 1000) {
          const offsets = [];
          for (let off = 1000; off < totalExportar; off += 1000) {
            offsets.push(off);
          }
          for (let i = 0; i < offsets.length; i += 4) {
            const grupo = offsets.slice(i, i + 4);
            const pct = Math.min(99, Math.round((dados.length / totalExportar) * 100));
            btn.textContent = `⏳ Exportando ${fmtInt(dados.length)} / ${fmtInt(totalExportar)} (${pct}%)...`;
            const lotes = await Promise.all(grupo.map(async (off) => {
              const p = new URLSearchParams(baseParams);
              p.append("limit", "1000");
              p.append("offset", String(off));
              const res = await fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?${p.toString()}`, { headers: HEADERS });
              return res.json();
            }));
            lotes.forEach(arr => {
              if (Array.isArray(arr)) dados.push(...arr);
            });
          }
        }

        btn.textContent = `⏳ A gerar CSV (${fmtInt(dados.length)} linhas)...`;
        const cols = Object.keys(dados[0]);
        const csvLinhas = [
          cols.join(";"),
          ...dados.map(row => cols.map(c => `"${String(row[c] ?? "").replace(/"/g, '""')}"`).join(";"))
        ];
        const blob = new Blob(["\uFEFF" + csvLinhas.join("\n")], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `EDEC_Santiago_Export_${dados.length}_reg_${new Date().toISOString().slice(0,10)}.csv`;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        alert("Erro ao exportar CSV: " + e.message);
      } finally {
        btn.textContent = txtOrig;
        btn.disabled = false;
      }
    }

    
