    // =========================================================================
    // CONFIGURAÇÃO SUPABASE (PROJETO ATIVO: edec-app)
    // =========================================================================
    const SUPABASE_URL = window.SANTIAGO_CONFIG?.SUPABASE_URL || "https://esbbohmkgbcrpegqvagk.supabase.co";
    const SUPABASE_KEY = window.SANTIAGO_CONFIG?.SUPABASE_ANON_KEY || "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzYmJvaG1rZ2JjcnBlZ3F2YWdrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM1MDQ3OTUsImV4cCI6MjA5OTA4MDc5NX0.85Ypz7LghhQ37Ur5YE2eLM4PFkMw2o3S8QtbhRSzBuU";
    const HEADERS = {
      "apikey": SUPABASE_KEY,
      "Authorization": `Bearer ${SUPABASE_KEY}`,
      "Content-Type": "application/json"
    };

    const PAGE_SIZE = 100;
    let paginaAtual = 1;
    let totalRegistosFiltrados = 0;
    let registosPaginaAtual = [];

    // Mapa Leaflet
    let map, markersLayer, tileDark, tileSat;
    let usandoSatelite = false;

    const fmtInt = (n) => (n === null || n === undefined || isNaN(n)) ? "0" : Number(n).toLocaleString("pt-PT");
    const fmtECV = (n) => (n === null || n === undefined || isNaN(n)) ? "0 ECV" : Number(n).toLocaleString("pt-PT", { maximumFractionDigits: 0 }) + " ECV";

    const INFO_MODULOS = {
      mod2: {
        icone: "🗺️",
        titulo: "2. Mapa GIS & Balanço Energético de PTs — Em Atualização",
        desc: "Em atualização: Integração dos Polígonos Geográficos das zonas de cada PT, cadastro técnico dos Transformadores e cálculo de Perda Energética por PT (kWh medido no PT vs soma da faturação T3 dos clientes)."
      },
      mod5: {
        icone: "⚖️",
        titulo: "5. Auditoria Jurídica CF1 & Recuperação COB_J — Em Atualização",
        desc: "Em atualização: Painel dedicado ao acompanhamento de processos de fraude enviados ao Ministério Público, reincidências CF1 e planos de amortização de dívida 2026."
      }
    };

    let dividaIniciada = false;

    // SUPORTE MULTI-ILHAS (SANTIAGO • FOGO • MAIO • BRAVA)
    let todasUnidadesLista = [];
    const ILHA_COORDS = {
      "Santiago": { center: [15.08, -23.62], zoom: 11 },
      "Fogo":     { center: [14.95, -24.38], zoom: 11 },
      "Maio":     { center: [15.20, -23.18], zoom: 11 },
      "Brava":    { center: [14.86, -24.71], zoom: 12 },
      "":         { center: [15.05, -23.85], zoom: 9 }
    };

    const ILHA_UNIDADES = {
      "Santiago": ["Praia", "Santa Catarina", "Santa Cruz", "Tarrafal", "Calheta S. Miguel", "São Domingos"],
      "Fogo": ["São Filipe", "Mosteiros"],
      "Maio": ["Maio"],
      "Brava": ["Brava"]
    };

    function aoMudarIlha(ilha) {
      const selUni = document.getElementById("f-uni");
      if (selUni && todasUnidadesLista.length) {
        const filtradas = ilha && ILHA_UNIDADES[ilha]
          ? todasUnidadesLista.filter(u => ILHA_UNIDADES[ilha].includes(u))
          : todasUnidadesLista;
        popularSelect("f-uni", filtradas);
      }
      if (map && ILHA_COORDS[ilha]) {
        const cfg = ILHA_COORDS[ilha];
        map.setView(cfg.center, cfg.zoom);
      }
      aplicarFiltros(1);
    }

    function aoMudarIlhaDivida(ilha) {
      const selUni = document.getElementById("div-uni");
      if (selUni) {
        Array.from(selUni.options).forEach(opt => {
          if (!opt.value) { opt.hidden = false; return; }
          if (!ilha) {
            opt.hidden = false;
          } else {
            opt.hidden = !(ILHA_UNIDADES[ilha] && ILHA_UNIDADES[ilha].includes(opt.value));
          }
        });
        if (selUni.selectedOptions[0] && selUni.selectedOptions[0].hidden) {
          selUni.value = "";
        }
      }
      const badge = document.getElementById("badge-concelhos-total");
      if (badge) {
        badge.textContent = ilha ? `Ilha de ${ilha}` : "Região Sul (4 Ilhas)";
      }
      aplicarFiltrosDivida(1);
    }

    function selecionarModulo(modId) {
      document.querySelectorAll(".mod-tab-btn").forEach(btn => btn.classList.remove("active"));
      const btnAtivo = document.getElementById(`tab-btn-${modId}`);
      if (btnAtivo) btnAtivo.classList.add("active");

      const paneMod1 = document.getElementById("modulo-mod1");
      const paneMod3 = document.getElementById("modulo-mod3");
      const paneUpd = document.getElementById("modulo-em-atualizacao");

      // Esconder todos inicialmente
      paneMod1.classList.add("hidden");
      if (paneMod3) paneMod3.classList.add("hidden");
      paneUpd.classList.add("hidden");

      const paneMod2 = document.getElementById("modulo-mod2");
      if (paneMod2) paneMod2.classList.add("hidden");

      if (modId === "mod1") {
        paneMod1.classList.remove("hidden");
        if (map) {
          setTimeout(() => map.invalidateSize(), 60);
        }
      } else if (modId === "mod2") {
        if (paneMod2) paneMod2.classList.remove("hidden");
        iniciarOuRedimensionar3D();
      } else if (modId === "mod3") {
        if (paneMod3) paneMod3.classList.remove("hidden");
        dividaIniciada = true;
        aplicarFiltrosDivida(1);
      } else {
        const info = INFO_MODULOS[modId] || {
          icone: "🚧",
          titulo: "Módulo em Atualização",
          desc: "Este módulo está em atualização."
        };
        document.getElementById("mod-upd-icon").textContent = info.icone;
        document.getElementById("mod-upd-titulo").textContent = info.titulo;
        document.getElementById("mod-upd-desc").textContent = info.desc;
        paneUpd.classList.remove("hidden");
      }
    }

    function iniciarMapa() {
      map = L.map("santiago-map", { preferCanvas: true }).setView([15.05, -23.60], 10);
      tileDark = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
        attribution: "&copy; OpenStreetMap &copy; CARTO",
        maxZoom: 20
      });

      tileLight = L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
        attribution: "&copy; OpenStreetMap &copy; CARTO",
        maxZoom: 20
      });

      tileSat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        attribution: "&copy; Esri World Imagery",
        maxZoom: 19
      });

      const initT = document.documentElement.getAttribute('data-theme') || 'dark';
      if (initT === 'light') {
        tileLight.addTo(map);
      } else {
        tileDark.addTo(map);
      }

      markersLayer = L.layerGroup().addTo(map);
    }

    
    function alternarTelaCheia() {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    }

    function setTema(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      try { localStorage.setItem('santiago_theme', theme); } catch(e) {}

      const btnDark = document.getElementById('theme-btn-dark');
      const btnLight = document.getElementById('theme-btn-light');
      if (btnDark && btnLight) {
        if (theme === 'light') {
          btnLight.classList.add('active');
          btnDark.classList.remove('active');
        } else {
          btnDark.classList.add('active');
          btnLight.classList.remove('active');
        }
      }

      // Sincronizar camada base do Mapa Leaflet
      if (typeof map !== 'undefined' && map && !usandoSatelite && typeof tileDark !== 'undefined' && typeof tileLight !== 'undefined') {
        if (theme === 'light') {
          if (map.hasLayer(tileDark)) map.removeLayer(tileDark);
          if (!map.hasLayer(tileLight)) tileLight.addTo(map);
        } else {
          if (map.hasLayer(tileLight)) map.removeLayer(tileLight);
          if (!map.hasLayer(tileDark)) tileDark.addTo(map);
        }
      }
    }

    function alternarCamadaMapa() {
      const isLight = document.documentElement.getAttribute('data-theme') === 'light';
      const defaultTile = isLight ? tileLight : tileDark;
      if (usandoSatelite) {
        map.removeLayer(tileSat);
        defaultTile.addTo(map);
      } else {
        if (map.hasLayer(tileDark)) map.removeLayer(tileDark);
        if (map.hasLayer(tileLight)) map.removeLayer(tileLight);
        tileSat.addTo(map);
      }
      usandoSatelite = !usandoSatelite;
    }

    async function carregarListasFiltros() {
      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/get_filtros_santiago`, {
          method: "POST",
          headers: HEADERS,
          body: "{}"
        });
        const d = await r.json();
        todasUnidadesLista = d.unidades || [];
        popularSelect("f-uni", todasUnidadesLista);
        popularSelect("f-estado", d.estados || []);
        popularSelect("f-grupo", d.grupos || []);
        popularSelect("f-anomalia", d.anomalias || [], true);
        popularSelect("f-mat-cont", d.mat_contador || []);
        const dlPts = document.getElementById("lista-pts-opcoes");
        if (dlPts && Array.isArray(d.pts)) {
          dlPts.innerHTML = d.pts.map(pt => `<option value="${pt}"></option>`).join("");
        }
      } catch (e) {
        console.error("Erro ao carregar filtros:", e);
      }
    }

    function popularSelect(id, lista, manterExistentes = false) {
      const sel = document.getElementById(id);
      const baseCount = manterExistentes ? 2 : 1;
      while (sel.options.length > baseCount) sel.remove(baseCount);
      lista.forEach(item => {
        const opt = document.createElement("option");
        opt.value = item;
        opt.textContent = item;
        sel.appendChild(opt);
      });
    }

    function interpretarBusca(rawBusca, tipoSelecionado) {
      let texto = (rawBusca || "").trim();
      let modo = tipoSelecionado || "auto";

      // Detetar se o utilizador escreveu explícito "CIL:60042095", "NIB:...", "CONT:..."
      const matchPrefixo = texto.match(/^(cil|nib|cont|contador|id)\s*[:=-]?\s*(.+)$/i);
      if (matchPrefixo) {
        const pref = matchPrefixo[1].toLowerCase();
        texto = matchPrefixo[2].trim();
        if (pref === "cil") modo = "cil";
        else if (pref === "nib") modo = "nib";
        else if (pref === "cont" || pref === "contador") modo = "contador";
        else if (pref === "id") modo = "id_cliente";
      }

      const ehNumero = /^\d+$/.test(texto);
      let numExato = ehNumero ? parseInt(texto, 10) : null;
      let cilNorm = numExato;
      if (ehNumero && texto.length <= 6 && numExato < 1000000) {
        cilNorm = 60000000 + numExato;
      }

      return { texto, modo, ehNumero, numExato, cilNorm };
    }

    function construirQueryParams() {
      const params = new URLSearchParams();
      const rawBusca = document.getElementById("f-busca").value;
      const tipoBuscaSel = document.getElementById("f-tipo-busca").value;
      const infoBusca = interpretarBusca(rawBusca, tipoBuscaSel);

      const elIlha = document.getElementById("f-ilha");
      const ilha = elIlha ? elIlha.value : "";
      if (ilha) params.append("ilha", `eq.${ilha}`);

      const risco = document.getElementById("f-risco").value;
      const uni = document.getElementById("f-uni").value;
      const cf1 = document.getElementById("f-cf1").value;
      const cobranca = document.getElementById("f-cobranca").value;
      const prod = document.getElementById("f-produto") ? document.getElementById("f-produto").value : "";
      if (prod === "__ELETRICIDADE__") {
        params.append("produto", "in.(EB,EE,EM)");
      } else if (prod) {
        params.append("produto", `eq.${prod}`);
      }

      const estado = document.getElementById("f-estado").value;
      const grupo = document.getElementById("f-grupo").value;
      const anom = document.getElementById("f-anomalia").value;
      const matCont = document.getElementById("f-mat-cont").value;
      const matLeit = document.getElementById("f-mat-leit").value;
      const pt = document.getElementById("f-pt").value.trim();
      const divida = document.getElementById("f-divida").value;
      const desvio = document.getElementById("f-desvio").value;
      const ordem = document.getElementById("f-ordem").value;

      const prioridade = document.getElementById("f-prioridade")?.value || "";
      if (prioridade === "P1") {
        params.append("or", "(cf1_qtd_autos.gte.2,and(score_risco.gte.60,faturacao_alerta_desvio.eq.Desv_Fat))");
      } else if (prioridade === "P2") {
        params.append("faturacao_alerta_desvio", "eq.Desv_Fat");
      } else if (prioridade === "P3") {
        params.append("or", "(cf1_qtd_autos.eq.1,and(mat_leitura.eq.> 5 meses,anomalia.not.is.null))");
      } else if (prioridade === "P4") {
        params.append("mat_contador", "eq.> 20 ano");
      }

      if (risco === "CRITICO_ALTO") {
        params.append("nivel_risco", "in.(CRÍTICO,ALTO)");
      } else if (risco) {
        params.append("nivel_risco", `eq.${risco}`);
      }
      if (uni) params.append("desc_uni", `eq.${uni}`);
      if (estado) params.append("est_ctr", `eq.${estado}`);
      if (grupo) params.append("grup_tp_cli", `eq.${grupo}`);
      if (matCont) params.append("mat_contador", `eq.${matCont}`);
      if (matLeit) params.append("mat_leitura", `eq.${matLeit}`);
      if (desvio) params.append("faturacao_alerta_desvio", `eq.${desvio}`);
      if (pt) params.append("pt", `ilike.*${pt}*`);

      // Filtros de Autos de Fraude CF1
      if (cf1 === "__COM_CF1__") {
        params.append("cf1_qtd_autos", "gt.0");
      } else if (cf1 === "__REINCIDENTE__") {
        params.append("cf1_qtd_autos", "gte.2");
      } else if (cf1 === "__DIVIDA_CF1__") {
        params.append("cf1_val_divida", "gt.0");
      } else if (cf1 === "__COM_FOTOS__") {
        params.append("cf1_evidencia_fotos", "eq.Com Fotos");
      } else if (cf1 === "__SEM_CF1__") {
        params.append("cf1_qtd_autos", "eq.0");
      } else if (cf1) {
        params.append("cf1_estado_juridico", `eq.${cf1}`);
      }

      // Filtros de Cobrança 2026 (COB_J)
      if (cobranca === "__MAT_LONGA__") {
        params.append("cob_maturidade_predom", "in.(6 mes,1 ano,> 1 ano)");
      } else if (cobranca) {
        params.append("status_cobranca", `eq.${cobranca}`);
      }

      if (anom === "__COM_ANOMALIA__") {
        params.append("anomalia", "not.is.null");
      } else if (anom) {
        params.append("anomalia", `eq.${anom}`);
      }

      if (divida === "gt0") params.append("valor", "gt.0");
      else if (divida === "gt10000") params.append("valor", "gt.10000");
      else if (divida === "gt50000") params.append("valor", "gt.50000");
      else if (divida === "gt100000") params.append("valor", "gt.100000");
      else if (divida === "sem") params.append("or", "(valor.is.null,valor.lte.0)");

      // Pesquisa Estruturada e Sem Falsos Positivos entre CIL e NIB
      if (infoBusca.texto) {
        const { texto, modo, ehNumero, numExato, cilNorm } = infoBusca;
        if (modo === "cil") {
          if (ehNumero) {
            params.append("cil", numExato !== cilNorm ? `in.(${numExato},${cilNorm})` : `eq.${numExato}`);
          } else {
            params.append("cil", "eq.-1");
          }
        } else if (modo === "nib") {
          if (ehNumero) {
            params.append("nib", numExato !== cilNorm ? `in.(${numExato},${cilNorm})` : `eq.${numExato}`);
          } else {
            params.append("nib", "eq.-1");
          }
        } else if (modo === "contador") {
          if (ehNumero) {
            params.append("contador", `eq.${numExato}`);
          } else {
            params.append("contador", "eq.-1");
          }
        } else if (modo === "id_cliente") {
          if (ehNumero) {
            params.append("id_cliente", numExato !== cilNorm ? `in.(${numExato},${cilNorm})` : `eq.${numExato}`);
          } else {
            params.append("id_cliente", "eq.-1");
          }
        } else if (modo === "nome") {
          params.append("or", `(nome.ilike.*${texto}*,localidade.ilike.*${texto}*,pt.ilike.*${texto}*)`);
        } else if (modo === "tudo") {
          if (ehNumero) {
            params.append("or", `(cil.eq.${numExato},cil.eq.${cilNorm},nib.eq.${numExato},contador.eq.${numExato},id_cliente.eq.${numExato})`);
          } else {
            params.append("or", `(nome.ilike.*${texto}*,localidade.ilike.*${texto}*,pt.ilike.*${texto}*)`);
          }
        } else {
          // Modo 'auto': se for número, pesquisa ESTRITAMENTE na coluna CIL (sem misturar com NIB!)
          if (ehNumero) {
            params.append("cil", numExato !== cilNorm ? `in.(${numExato},${cilNorm})` : `eq.${numExato}`);
          } else {
            params.append("or", `(nome.ilike.*${texto}*,localidade.ilike.*${texto}*,pt.ilike.*${texto}*)`);
          }
        }
      }

      params.append("order", ordem);
      return params;
    }

    async function atualizarKPIsERankings(tokenAtual) {
      const rawBusca = document.getElementById("f-busca").value;
      const tipoBuscaSel = document.getElementById("f-tipo-busca").value;
      const infoBusca = interpretarBusca(rawBusca, tipoBuscaSel);

      const risco = document.getElementById("f-risco").value || null;
      const uni = document.getElementById("f-uni").value || null;
      const cf1 = document.getElementById("f-cf1").value || null;
      const cobranca = document.getElementById("f-cobranca").value || null;
      const estado = document.getElementById("f-estado").value || null;
      const grupo = document.getElementById("f-grupo").value || null;
      const anom = document.getElementById("f-anomalia").value || null;
      const desvio = document.getElementById("f-desvio").value || null;
      const matCont = document.getElementById("f-mat-cont").value || null;
      const matLeit = document.getElementById("f-mat-leit").value || null;
      const pt = document.getElementById("f-pt").value.trim() || null;
      const divida = document.getElementById("f-divida").value || null;

      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/get_resumo_santiago`, {
          method: "POST",
          headers: HEADERS,
          body: JSON.stringify({
            p_desc_uni: uni,
            p_est_ctr: estado,
            p_grup_tp_cli: grupo,
            p_anomalia: anom,
            p_alerta_desvio: desvio,
            p_mat_contador: matCont,
            p_mat_leitura: matLeit,
            p_nivel_risco: risco,
            p_pt: pt,
            p_cf1_filtro: cf1,
            p_status_cobranca: cobranca,
            p_divida: divida,
            p_busca: infoBusca.texto || null,
            p_tipo_busca: infoBusca.modo || "auto",
            p_ilha: (document.getElementById("f-ilha") ? document.getElementById("f-ilha").value : null) || null,
            p_produto: (document.getElementById("f-produto") ? document.getElementById("f-produto").value : null) || null,
            p_empresa: null
          })
        });
        if (tokenAtual && tokenAtual !== ultimoTokenFiltro) return;
        const d = await r.json();
        const total = d.total_contratos || 0;

        document.getElementById("kpi-contratos").textContent = fmtInt(total);

        // Atualizar título do card e subtipo de acordo com o filtro de ilha/unidade
        const selIlha = document.getElementById("f-ilha") ? document.getElementById("f-ilha").value : "";
        const elTituloCard = document.getElementById("lbl-kpi-contratos-titulo");
        const elSubtipoCard = document.getElementById("lbl-kpi-contratos-subtipo");
        const elTituloMapa = document.getElementById("lbl-titulo-mapa");
        const elTituloUni = document.getElementById("lbl-titulo-unidades");

        if (elTituloCard) {
          elTituloCard.textContent = selIlha ? `CONTRATOS ${selIlha.toUpperCase()}` : "CONTRATOS SUL";
        }
        if (elSubtipoCard) {
          elSubtipoCard.textContent = uni ? uni.toUpperCase() : (selIlha ? `ILHA ${selIlha.toUpperCase()}` : "REGIÃO SUL");
        }
        if (elTituloMapa) {
          elTituloMapa.textContent = `🌍 Mapa Georreferenciado de Risco de Perdas (${selIlha ? selIlha : "Região Sul"})`;
        }
        if (elTituloUni) {
          elTituloUni.textContent = `🏢 Unidades Comerciais (${selIlha ? selIlha : "Região Sul"})`;
        }
        document.getElementById("kpi-contratos-sub").textContent =
          (() => {
          const selIlha = document.getElementById("f-ilha") ? document.getElementById("f-ilha").value : "";
          const txtIlha = selIlha ? `Ilha de ${selIlha}` : "Região Sul (4 Ilhas)";
          return uni ? `Unidade: ${uni} (${txtIlha})` : `${txtIlha} • ${d.por_unidade ? d.por_unidade.length : 0} Unidades`;
        })();

        const crit = d.risco_critico || 0;
        const alto = d.risco_alto || 0;
        document.getElementById("kpi-risco").textContent = `${fmtInt(crit)} Crít. / ${fmtInt(alto)} Alto`;
        document.getElementById("kpi-risco-sub").textContent =
          `Score médio: ${d.score_medio || 0}/100 • Médio: ${fmtInt(d.risco_medio || 0)}`;

        document.getElementById("kpi-divida").textContent = fmtECV(d.total_divida);
        document.getElementById("kpi-divida-sub").textContent =
          `${fmtInt(d.com_divida)} devedores (${fmtInt(d.total_faturas_divida)} fat.)`;

        // KPI Autos de Fraude CF1
        document.getElementById("kpi-cf1").textContent =
          `${fmtInt(d.com_cf1 || 0)} CILs (${fmtInt(d.total_autos_cf1 || 0)} autos)`;
        document.getElementById("kpi-cf1-sub").textContent =
          `Dív. CF1: ${fmtECV(d.cf1_divida_total || 0)} • MP: ${fmtInt(d.cf1_enviado_mp || 0)}`;

        // KPI Cobrança 2026 (COB_J)
        document.getElementById("kpi-cobranca").textContent = fmtECV(d.cob_total_2026 || 0);
        document.getElementById("kpi-cobranca-sub").textContent =
          `${fmtInt(d.com_cobranca_2026 || 0)} pagam • 🚨 ${fmtInt(d.devedor_sem_pagamento || 0)} s/ pag.`;

        document.getElementById("kpi-anomalias").textContent = fmtInt(d.com_anomalia);
        const pctAnom = total > 0 ? ((d.com_anomalia / total) * 100).toFixed(1) : "0.0";
        document.getElementById("kpi-anomalias-sub").textContent =
          `${pctAnom}% c/ anom. • ${fmtInt(d.leitura_antiga || 0)} s/ leit. >5m`;

        document.getElementById("kpi-desvio").textContent = fmtInt(d.com_desvio_fat);
        document.getElementById("kpi-medfat-sub").textContent = `Consumo médio: ${d.media_med_fat || 0} kWh/mês`;

        document.getElementById("kpi-geo").textContent = fmtInt(d.com_geo);
        const pctGeo = total > 0 ? ((d.com_geo / total) * 100).toFixed(1) : "0.0";
        document.getElementById("kpi-geo-sub").textContent = `${pctGeo}% georreferenciado em PTs`;

        // Atualizar Estimador de Perdas Não Técnicas (MWh & ECV)
        const qtdDesvio = d.com_desvio_fat || 0;
        const medFatGeral = d.media_med_fat || 145; // kWh médio mensal
        const mwhMes = Math.round((qtdDesvio * medFatGeral) / 1000);
        const tarifaMediaECV = 26; // ~26 ECV/kWh tarifa média de Santiago
        const ecvMes = (qtdDesvio * medFatGeral) * tarifaMediaECV;
        const ecvAno = ecvMes * 12;

        const elMwh = document.getElementById("diag-mwh-estimado");
        const elEcv = document.getElementById("diag-ecv-estimado");
        const elAno = document.getElementById("diag-ano-estimado");
        if (elMwh) elMwh.textContent = `~${fmtInt(mwhMes)} MWh/mês`;
        if (elEcv) elEcv.textContent = `~${fmtECV(ecvMes)}/mês`;
        if (elAno) elAno.textContent = `~${fmtECV(ecvAno)}/ano`;

        const bBypass = document.getElementById("badge-count-bypass");
        const bMeter = document.getElementById("badge-count-meter");
        const bBlind = document.getElementById("badge-count-blind");
        const bCf1 = document.getElementById("badge-count-cf1");
        if (bBypass) bBypass.textContent = `${fmtInt(qtdDesvio)} CILs`;
        if (bMeter) bMeter.textContent = `${fmtInt(d.contador_antigo || 12672)} CILs`;
        if (bBlind) bBlind.textContent = `${fmtInt(d.leitura_antiga || 14668)} CILs`;
        if (bCf1) bCf1.textContent = `${fmtInt(d.cf1_reincidentes || 916)} CILs`;

        renderizarRankingUnidades(d.por_unidade || [], total);
        renderizarRankingPTs(d.top_pts_divida || []);
      } catch (e) {
        console.error("Erro KPIs:", e);
      }
    }

    function renderizarRankingUnidades(lista, totalGeral) {
      const container = document.getElementById("lista-unidades");
      const uniAtual = document.getElementById("f-uni").value;
      if (!lista.length) {
        container.innerHTML = `<div style="padding:16px; color:var(--text-muted);">Sem dados para este filtro.</div>`;
        return;
      }
      const maxContratos = Math.max(...lista.map(x => x.qtd_contratos), 1);
      container.innerHTML = lista.map(u => {
        const pct = Math.round((u.qtd_contratos / maxContratos) * 100);
        const ativo = uniAtual === u.desc_uni ? "active" : "";
        return `
          <div class="rank-item ${ativo}" onclick="selecionarUnidade('${u.desc_uni.replace(/'/g, "\\'")}')">
            <div class="rank-top">
              <span>${u.desc_uni}</span>
              <span style="font-family:var(--font-mono); color:var(--accent-cyan);">${fmtInt(u.qtd_contratos)} CILs</span>
            </div>
            <div class="rank-metrics">
              <span>Dívida: <strong style="color:#FBBF24;">${fmtECV(u.soma_divida)}</strong></span>
              <span>CF1: <strong style="color:#C084FC;">${fmtInt(u.qtd_cf1 || 0)}</strong> | S/ Pag: <strong style="color:#F87171;">${fmtInt(u.qtd_sem_pag || 0)}</strong></span>
            </div>
            <div class="rank-bar-track">
              <div class="rank-bar-fill" style="width:${pct}%"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    function renderizarRankingPTs(lista) {
      const container = document.getElementById("lista-pts");
      const ptAtual = document.getElementById("f-pt").value.trim();
      if (!lista.length) {
        container.innerHTML = `<div style="padding:16px; color:var(--text-muted);">Sem PTs para este filtro.</div>`;
        return;
      }
      const maxRisco = Math.max(...lista.map(x => x.qtd_risco_elevado || 1), 1);
      container.innerHTML = lista.map(p => {
        const pct = Math.round(((p.qtd_risco_elevado || 0) / maxRisco) * 100);
        const nomePT = (p.pt || "").trim();
        const ativo = ptAtual && ptAtual.toLowerCase() === nomePT.toLowerCase() ? "active" : "";
        return `
          <div class="rank-item ${ativo}" onclick="selecionarPT('${nomePT.replace(/'/g, "\\'")}')">
            <div class="rank-top">
              <span style="font-family:var(--font-mono);">⚡ ${nomePT}</span>
              <span style="font-family:var(--font-mono); color:#F87171;">🔥 ${fmtInt(p.qtd_risco_elevado || 0)} Alvos</span>
            </div>
            <div class="rank-metrics">
              <span>Dívida: <strong style="color:#FBBF24;">${fmtECV(p.soma_divida)}</strong></span>
              <span>CF1: <strong style="color:#C084FC;">${fmtInt(p.qtd_cf1 || 0)}</strong> | Anom: <strong>${fmtInt(p.qtd_anomalias)}</strong></span>
            </div>
            <div class="rank-bar-track">
              <div class="rank-bar-fill" style="width:${pct}%"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    function selecionarUnidade(uni) {
      const sel = document.getElementById("f-uni");
      sel.value = (sel.value === uni) ? "" : uni;
      aplicarFiltros(1);
    }

    function selecionarPT(pt) {
      const inp = document.getElementById("f-pt");
      inp.value = (inp.value.trim() === pt) ? "" : pt;
      aplicarFiltros(1);
    }

    
