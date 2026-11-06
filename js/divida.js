        // =========================================================================
    // MÓDULO 3: GESTÃO DEDICADA DE DÍVIDA & INADIMPLÊNCIA (ESTRATÉGICO & OPERACIONAL)
    // =========================================================================
    
    // =========================================================================
    // SIMULADOR FINANCEIRO DE RECUPERAÇÃO DE RECEITA (CASH-IN SIMULATOR)
    // =========================================================================
    const BASE_SIMULACAO = {
      grandes: 2599339517, // ~2.60 Bilhões em contas privadas > 250k ECV
      gov: 2595538988,     // ~2.60 Bilhões em Autarquias, Estado e Empresas Públicas
      massa: 1841940392,   // ~1.84 Bilhão em Domésticos e PMEs (< 250k ECV)
      cf1: 108580309       // ~108.6 Milhões em autos de fraude CF1 com dívida
    };

    function formatarBaseSim(val) {
      if (val >= 1e9) return `${(val / 1e9).toFixed(2)} Bilhões ECV`;
      if (val >= 1e6) return `${(val / 1e6).toFixed(1)} Milhões ECV`;
      return fmtECV(val);
    }

    function formatarCurtoSim(val) {
      if (val >= 1e9) return `${(val / 1e9).toFixed(2)} B ECV`;
      if (val >= 1e6) return `${(val / 1e6).toFixed(1)} M ECV`;
      return fmtECV(val);
    }

    function atualizarSimulador() {
      if (dadosResumoDivida) {
        if (dadosResumoDivida.divida_grandes_priv > 0) BASE_SIMULACAO.grandes = Number(dadosResumoDivida.divida_grandes_priv);
        if (dadosResumoDivida.divida_setor_publico > 0) BASE_SIMULACAO.gov = Number(dadosResumoDivida.divida_setor_publico);
        if (dadosResumoDivida.divida_massa > 0) BASE_SIMULACAO.massa = Number(dadosResumoDivida.divida_massa);
        if (dadosResumoDivida.cf1_divida_total > 0) BASE_SIMULACAO.cf1 = Number(dadosResumoDivida.cf1_divida_total);
      }

      const bLblGrandes = document.getElementById("base-lbl-grandes");
      const mLblGrandes = document.getElementById("max-lbl-grandes");
      const bLblGov = document.getElementById("base-lbl-gov");
      const mLblGov = document.getElementById("max-lbl-gov");
      const bLblMassa = document.getElementById("base-lbl-massa");
      const mLblMassa = document.getElementById("max-lbl-massa");
      const bLblCf1 = document.getElementById("base-lbl-cf1");
      const mLblCf1 = document.getElementById("max-lbl-cf1");

      if (bLblGrandes) bLblGrandes.textContent = `Base: ${formatarBaseSim(BASE_SIMULACAO.grandes)}`;
      if (mLblGrandes) mLblGrandes.textContent = `50% (${formatarCurtoSim(BASE_SIMULACAO.grandes * 0.5)})`;
      if (bLblGov) bLblGov.textContent = `Base: ${formatarBaseSim(BASE_SIMULACAO.gov)}`;
      if (mLblGov) mLblGov.textContent = `50% (${formatarCurtoSim(BASE_SIMULACAO.gov * 0.5)})`;
      if (bLblMassa) bLblMassa.textContent = `Base: ${formatarBaseSim(BASE_SIMULACAO.massa)}`;
      if (mLblMassa) mLblMassa.textContent = `30% (${formatarCurtoSim(BASE_SIMULACAO.massa * 0.3)})`;
      if (bLblCf1) bLblCf1.textContent = `Base: ${formatarBaseSim(BASE_SIMULACAO.cf1)}`;
      if (mLblCf1) mLblCf1.textContent = `100% (${formatarCurtoSim(BASE_SIMULACAO.cf1)})`;

      const pGrandes = Number(document.getElementById("slider-sim-grandes")?.value || 15);
      const pGov = Number(document.getElementById("slider-sim-gov")?.value || 25);
      const pMassa = Number(document.getElementById("slider-sim-massa")?.value || 7);
      const pCf1 = Number(document.getElementById("slider-sim-cf1")?.value || 30);

      const valGrandes = BASE_SIMULACAO.grandes * (pGrandes / 100);
      const valGov = BASE_SIMULACAO.gov * (pGov / 100);
      const valMassa = BASE_SIMULACAO.massa * (pMassa / 100);
      const valCf1 = BASE_SIMULACAO.cf1 * (pCf1 / 100);
      const totalRecuperado = Math.round(valGrandes + valGov + valMassa + valCf1);

      // Atualizar labels dos sliders
      const elLGrandes = document.getElementById("lbl-sim-grandes");
      const elLGov = document.getElementById("lbl-sim-gov");
      const elLMassa = document.getElementById("lbl-sim-massa");
      const elLCf1 = document.getElementById("lbl-sim-cf1");

      if (elLGrandes) elLGrandes.textContent = `${pGrandes}% (${(valGrandes/1e6).toFixed(1)} M ECV)`;
      if (elLGov) elLGov.textContent = `${pGov}% (${(valGov/1e6).toFixed(1)} M ECV)`;
      if (elLMassa) elLMassa.textContent = `${pMassa}% (${(valMassa/1e6).toFixed(1)} M ECV)`;
      if (elLCf1) elLCf1.textContent = `${pCf1}% (${(valCf1/1e6).toFixed(1)} M ECV)`;

      // Atualizar KPIs de Impacto no Caixa
      const elTot = document.getElementById("sim-res-total");
      const elTaxa = document.getElementById("sim-res-taxa");
      const elTaxaAtual = document.getElementById("sim-res-taxa-atual");
      const elMensal = document.getElementById("sim-res-mensal");

      if (elTot) elTot.textContent = `+${fmtECV(totalRecuperado)}`;

      const arrecadadoBase = dadosResumoDivida?.cob_total_2026 || 2541070380;
      const totalDivida = dadosResumoDivida?.total_divida || 8595747001;
      const taxaAtual = (arrecadadoBase / (arrecadadoBase + totalDivida)) * 100;
      const novaTaxa = ((arrecadadoBase + totalRecuperado) / (arrecadadoBase + totalDivida)) * 100;

      if (elTaxa) elTaxa.textContent = `${novaTaxa.toFixed(1)}%`;
      if (elTaxaAtual) elTaxaAtual.textContent = `Atual: ${taxaAtual.toFixed(1)}%`;
      if (elMensal) elMensal.textContent = `${(totalRecuperado / 12 / 1e6).toFixed(1)}M ECV/mês`;
    }

    function aplicarCenarioSimulacao(cenario) {
      const sGrandes = document.getElementById("slider-sim-grandes");
      const sGov = document.getElementById("slider-sim-gov");
      const sMassa = document.getElementById("slider-sim-massa");
      const sCf1 = document.getElementById("slider-sim-cf1");

      if (cenario === "conservador") {
        if (sGrandes) sGrandes.value = 5;
        if (sGov) sGov.value = 10;
        if (sMassa) sMassa.value = 3;
        if (sCf1) sCf1.value = 15;
      } else if (cenario === "moderado") {
        if (sGrandes) sGrandes.value = 15;
        if (sGov) sGov.value = 25;
        if (sMassa) sMassa.value = 7;
        if (sCf1) sCf1.value = 30;
      } else if (cenario === "agressivo") {
        if (sGrandes) sGrandes.value = 25;
        if (sGov) sGov.value = 40;
        if (sMassa) sMassa.value = 12;
        if (sCf1) sCf1.value = 50;
      }
      atualizarSimulador();
    }

    function exportarRelatorioSimulacao() {
      const pGrandes = document.getElementById("slider-sim-grandes")?.value || 15;
      const pGov = document.getElementById("slider-sim-gov")?.value || 25;
      const pMassa = document.getElementById("slider-sim-massa")?.value || 7;
      const pCf1 = document.getElementById("slider-sim-cf1")?.value || 30;

      const vGrandes = BASE_SIMULACAO.grandes * (pGrandes / 100);
      const vGov = BASE_SIMULACAO.gov * (pGov / 100);
      const vMassa = BASE_SIMULACAO.massa * (pMassa / 100);
      const vCf1 = BASE_SIMULACAO.cf1 * (pCf1 / 100);
      const total = vGrandes + vGov + vMassa + vCf1;

      const linhas = [
        "Segmento;Base Dívida (ECV);Meta Recuperação (%);Impacto Financeiro Projetado (ECV);Meta Mensal 12M (ECV)",
        `Grandes Devedores Privados;${BASE_SIMULACAO.grandes};${pGrandes}%;${vGrandes};${Math.round(vGrandes/12)}`,
        `Protocolo Estado e Autarquias;${BASE_SIMULACAO.gov};${pGov}%;${vGov};${Math.round(vGov/12)}`,
        `Carteira Doméstica e PME;${BASE_SIMULACAO.massa};${pMassa}%;${vMassa};${Math.round(vMassa/12)}`,
        `Regularização Fraudes CF1;${BASE_SIMULACAO.cf1};${pCf1}%;${vCf1};${Math.round(vCf1/12)}`,
        `TOTAL PROJETADO EM CAIXA;${BASE_SIMULACAO.grandes + BASE_SIMULACAO.gov + BASE_SIMULACAO.massa + BASE_SIMULACAO.cf1};-;${total};${Math.round(total/12)}`
      ];

      const blob = new Blob(["\uFEFF" + linhas.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `EDEC_Simulacao_Recuperacao_${new Date().toISOString().slice(0,10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    }

    // =========================================================================
    // ROTEIRIZADOR DE PIQUETES POR POSTO DE TRANSFORMAÇÃO (PT)
    // =========================================================================
    let clientesRoteiroPT = [];
    let ptAtivoRoteiro = "Tirachapeu";

    async function carregarRoteiroPT(ptNome) {
      if (!ptNome) return;
      ptAtivoRoteiro = ptNome;

      const selPt = document.getElementById("sel-roteiro-pt");
      if (selPt && selPt.value !== ptNome) {
        const existe = Array.from(selPt.options).some(o => o.value === ptNome);
        if (!existe) {
          const opt = document.createElement("option");
          opt.value = ptNome;
          opt.textContent = `⚡ PT ${ptNome}`;
          selPt.appendChild(opt);
        }
        selPt.value = ptNome;
      }

      // Atualizar métricas resumidas do PT a partir dos dados em memória ou consultar resumo exato
      const listaPtsMem = [...(dadosResumoDivida?.top_pts_maior_divida || []), ...(dadosResumoDivida?.top_pts_divida || [])];
      const ptInfo = listaPtsMem.find(p => p.pt === ptNome);
      if (ptInfo) {
        document.getElementById("pt-card-divida").textContent = fmtECV(ptInfo.soma_divida || 0);
        document.getElementById("pt-card-contratos").textContent = `${fmtInt(ptInfo.qtd_contratos || 0)} clientes`;
        document.getElementById("pt-card-cf1").textContent = `${fmtInt(ptInfo.qtd_cf1 || 0)} autos`;
        document.getElementById("pt-card-cobrado").textContent = fmtECV(ptInfo.soma_cob_2026 || 0);
      }

      const tbody = document.getElementById("corpo-preview-roteiro-pt");
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:16px; color:var(--text-secondary);">A consultar alvos prioritários do PT ${ptNome}...</td></tr>`;
      }

      try {
        const promLista = fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?pt=eq.${encodeURIComponent(ptNome)}&valor=gt.0&order=valor.desc&limit=25&select=cil,id_cliente,nome,localidade,contador,valor,qtd,cf1_qtd_autos,cf1_estado_juridico,status_cobranca,pt,desc_uni`, {
          headers: HEADERS
        }).then(r => r.json());

        const promResumoPT = !ptInfo
          ? fetch(`${SUPABASE_URL}/rest/v1/rpc/get_resumo_santiago`, {
              method: "POST",
              headers: HEADERS,
              body: JSON.stringify({ p_pt: ptNome, p_divida: "gt0" })
            }).then(r => r.json())
          : Promise.resolve(null);

        const [listaAlvos, resumoPT] = await Promise.all([promLista, promResumoPT]);
        clientesRoteiroPT = Array.isArray(listaAlvos) ? listaAlvos : [];

        if (resumoPT) {
          document.getElementById("pt-card-divida").textContent = fmtECV(resumoPT.total_divida || 0);
          document.getElementById("pt-card-contratos").textContent = `${fmtInt(resumoPT.com_divida || resumoPT.total_contratos || 0)} clientes`;
          document.getElementById("pt-card-cf1").textContent = `${fmtInt(resumoPT.total_autos_cf1 || resumoPT.com_cf1 || 0)} autos`;
          document.getElementById("pt-card-cobrado").textContent = fmtECV(resumoPT.cob_total_2026 || 0);
        }

        renderizarPreviewRoteiroPT(clientesRoteiroPT);
      } catch (e) {
        console.error("Erro ao carregar roteiro do PT:", e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:#F87171; padding:16px;">Erro: ${e.message}</td></tr>`;
      }
    }

    function renderizarPreviewRoteiroPT(lista) {
      const tbody = document.getElementById("corpo-preview-roteiro-pt");
      if (!tbody) return;

      if (!lista || !lista.length) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:16px; color:var(--text-muted);">Nenhum cliente devedor encontrado para este transformador.</td></tr>`;
        return;
      }

      tbody.innerHTML = lista.slice(0, 6).map(c => {
        const cf1 = Number(c.cf1_qtd_autos || 0);
        const stCob = c.status_cobranca === "Devedor Sem Pagamento 2026"
          ? `<span class="badge badge-danger">🚨 Sem Pag. 2026</span>`
          : `<span class="badge badge-ok">🟡 Amortizando</span>`;

        const badgeCf1 = cf1 > 0 ? `<span class="badge badge-danger">⚡ ${cf1} Auto(s)</span>` : `<span style="color:var(--text-muted);">-</span>`;

        return `
          <tr>
            <td style="font-family:var(--font-mono); font-weight:700; color:var(--accent-cyan);">${c.cil}</td>
            <td style="font-family:var(--font-mono); color:var(--text-secondary);">${c.contador || 'Sem Contador'}</td>
            <td style="font-weight:600; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${c.nome}">${c.nome}</td>
            <td style="color:var(--text-secondary); max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${c.localidade || '-'}</td>
            <td style="text-align:right; font-family:var(--font-mono); font-weight:700; color:#FBBF24;">${fmtECV(c.valor)}</td>
            <td style="text-align:right; font-family:var(--font-mono);">${c.qtd}</td>
            <td>${stCob}</td>
            <td>${badgeCf1}</td>
            <td style="text-align:center;">
              <button class="btn btn-sm" onclick="abrirDossiePorCIL(${c.cil})" title="Ver Ficha Completa">Ficha</button>
            </td>
          </tr>
        `;
      }).join("");
    }

    function filtrarTabelaPorPTAtual() {
      resetarFiltrosDividaInputs();
      const el = document.getElementById("div-localidade");
      if (el) el.value = ptAtivoRoteiro;
      aplicarFiltrosDivida(1);
    }

    function abrirModalOrdemPiquete() {
      const modal = document.getElementById("modal-ordem-piquete");
      if (!modal) return;

      const meta = document.getElementById("print-os-meta");
      if (meta) {
        meta.innerHTML = `ILHA DE SANTIAGO • POSTO DE TRANSFORMAÇÃO: <strong>${ptAtivoRoteiro}</strong> • ALVOS PRIORITÁRIOS: <strong>${clientesRoteiroPT.length}</strong> • EMISSÃO: ${new Date().toLocaleDateString('pt-PT')}`;
      }

      const tbody = document.getElementById("corpo-tabela-ordem-piquete");
      if (tbody) {
        if (!clientesRoteiroPT.length) {
          tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:20px;">Nenhum devedor carregado para este PT.</td></tr>`;
        } else {
          tbody.innerHTML = clientesRoteiroPT.map((c, idx) => `
            <tr style="border-bottom:1px solid #334155;">
              <td style="padding:6px; font-weight:700;">${c.cil}</td>
              <td style="padding:6px;">${c.contador || 'S/N'}</td>
              <td style="padding:6px; font-weight:600; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${c.nome}</td>
              <td style="padding:6px; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${c.localidade || '-'}</td>
              <td style="padding:6px; text-align:right; font-weight:700;">${fmtInt(c.valor)} ECV</td>
              <td style="padding:6px; text-align:center;">${c.qtd}</td>
              <td style="padding:6px; text-align:center;">
                [ &nbsp; ] Cortado &nbsp; [ &nbsp; ] Negociou &nbsp; [ &nbsp; ] Ausente
              </td>
              <td style="padding:6px; border-bottom:1px dashed #64748B;"></td>
            </tr>
          `).join("");
        }
      }

      modal.style.display = "flex";
    }

    function fecharModalOrdemPiquete() {
      const modal = document.getElementById("modal-ordem-piquete");
      if (modal) modal.style.display = "none";
    }

    function exportarRoteiroPTCSV() {
      if (!clientesRoteiroPT.length) {
        alert("Nenhum cliente disponível no roteiro atual para exportar.");
        return;
      }

      const linhas = [
        "PT;CIL;Contador;Nome;Localidade;Divida_Total_ECV;Faturas_Qtd;Status_Cobranca;Autos_CF1;Acao_Campo_Sugerida",
        ...clientesRoteiroPT.map(c => `"${c.pt}";"${c.cil}";"${c.contador || ''}";"${(c.nome || '').replace(/"/g, '""')}";"${(c.localidade || '').replace(/"/g, '""')}";${c.valor};${c.qtd};"${c.status_cobranca || ''}";${c.cf1_qtd_autos || 0};"Corte / Vistoria Piquete"`)
      ];

      const blob = new Blob(["\uFEFF" + linhas.join("\n")], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `EDEC_Roteiro_Piquete_PT_${ptAtivoRoteiro}_${new Date().toISOString().slice(0,10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    }


    let paginaDividaAtual = 1;
    let totalDevedoresFiltrados = 0;
    let tokenFiltroDivida = 0;
    let registosDividaPagina = [];
    let dadosResumoDivida = null;

    const abrirDossieTecnico = abrirDossiePorCIL;

    function selecionarEmpresaDivida(cod) {
      const sel = document.getElementById("div-empresa");
      if (sel) sel.value = cod || "";
      atualizarBotoesEmpresaDivida(cod || "");
      aplicarFiltrosDivida(1);
    }

    function atualizarBotoesEmpresaDivida(cod) {
      ["", "17", "21", "7", "70"].forEach(c => {
        const id = c ? `btn-emp-${c}` : "btn-emp-todas";
        const btn = document.getElementById(id);
        if (btn) {
          if (c === (cod || "")) btn.classList.add("active");
          else btn.classList.remove("active");
        }
      });
    }

    function resetarFiltrosDividaInputs() {
      const elBusca = document.getElementById("div-busca");
      const elUni = document.getElementById("div-uni");
      const elLoc = document.getElementById("div-localidade");
      const elGrupo = document.getElementById("div-grupo");
      const elProd = document.getElementById("div-produto");
      const elFaixa = document.getElementById("div-faixa");
      const elCob = document.getElementById("div-cobranca");
      const elCf1 = document.getElementById("div-cf1");
      const elQtd = document.getElementById("div-qtd-fat");
      const elOrdem = document.getElementById("div-ordem");

      if (elBusca) elBusca.value = "";
      const elDivIlha = document.getElementById("div-ilha");
      if (elDivIlha) elDivIlha.value = "";
      if (elUni) elUni.value = "";
      const badgeConcelho = document.getElementById("badge-concelhos-total");
      if (badgeConcelho) badgeConcelho.textContent = "Região Sul (4 Ilhas)";
      const elDivSub = document.getElementById("lbl-kpi-div-subtipo");
      if (elDivSub) elDivSub.textContent = "REGIÃO SUL (ECV)";
      if (elLoc) elLoc.value = "";
      if (elGrupo) elGrupo.value = "";
      if (elProd) elProd.value = "";
      const elEmp = document.getElementById("div-empresa");
      if (elEmp) elEmp.value = "";
      atualizarBotoesEmpresaDivida("");
      if (elFaixa) elFaixa.value = "todas";
      if (elCob) elCob.value = "";
      if (elCf1) elCf1.value = "";
      if (elQtd) elQtd.value = "";
      if (elOrdem) elOrdem.value = "valor.desc";

      document.querySelectorAll(".action-card").forEach(c => c.classList.remove("active"));
      if (typeof atualizarBotoesProdutoDivida === "function") atualizarBotoesProdutoDivida("");
    }

    function resetarFiltrosDivida() {
      resetarFiltrosDividaInputs();
      aplicarFiltrosDivida(1);
    }

    function ativarAcaoGestao(tipo) {
      resetarFiltrosDividaInputs();
      document.querySelectorAll(".action-card").forEach(c => c.classList.remove("active"));

      if (tipo === "corte_urgente") {
        document.getElementById("card-act-corte")?.classList.add("active");
        const f = document.getElementById("div-faixa");
        const c = document.getElementById("div-cobranca");
        if (f) f.value = "250k";
        if (c) c.value = "Devedor Sem Pagamento 2026";
      } else if (tipo === "fraude_cf1") {
        document.getElementById("card-act-fraude")?.classList.add("active");
        const cf1 = document.getElementById("div-cf1");
        if (cf1) cf1.value = "com_cf1";
      } else if (tipo === "governo_autarquia") {
        document.getElementById("card-act-gov")?.classList.add("active");
        const g = document.getElementById("div-grupo");
        if (g) g.value = "__SETOR_PUBLICO__";
      } else if (tipo === "acordo_amortizacao") {
        document.getElementById("card-act-deal")?.classList.add("active");
        const c = document.getElementById("div-cobranca");
        const q = document.getElementById("div-qtd-fat");
        if (c) c.value = "Devedor em Amortização";
        if (q) q.value = "4a12";
      } else if (tipo === "ads_especial") {
        document.getElementById("card-act-ads")?.classList.add("active");
        const p = document.getElementById("div-produto");
        if (p) p.value = "AG_ADS";
        atualizarBotoesProdutoDivida("AG_ADS");
      }

      aplicarFiltrosDivida(1);
    }

    function selecionarProdutoDivida(prod) {
      const el = document.getElementById("div-produto");
      if (el) el.value = prod;
      atualizarBotoesProdutoDivida(prod);
      aplicarFiltrosDivida(1);
    }

    function atualizarBotoesProdutoDivida(prod) {
      const bTodos = document.getElementById("btn-prod-todos");
      const bElet = document.getElementById("btn-prod-elet");
      const bAguaAds = document.getElementById("btn-prod-agua-ads");
      const bAguaOutros = document.getElementById("btn-prod-agua-outros");
      const bAgua = document.getElementById("btn-prod-agua");

      if (bTodos) bTodos.className = "btn-prod-pill" + (prod === "" ? " active" : "");
      if (bElet) bElet.className = "btn-prod-pill" + (prod === "__ELETRICIDADE__" ? " active" : "");
      if (bAguaAds) bAguaAds.className = "btn-prod-pill" + (prod === "AG_ADS" ? " active-water" : "");
      if (bAguaOutros) bAguaOutros.className = "btn-prod-pill" + (prod === "AG_OUTROS" ? " active-water" : "");
      if (bAgua) bAgua.className = "btn-prod-pill" + (prod === "AG" ? " active-water" : "");
    }

    function filtrarConcelhoDivida(concelho) {
      resetarFiltrosDividaInputs();
      const el = document.getElementById("div-uni");
      if (el) el.value = concelho;
      aplicarFiltrosDivida(1);
    }

    function filtrarPTDivida(pt) {
      resetarFiltrosDividaInputs();
      const el = document.getElementById("div-localidade");
      if (el) el.value = pt;
      carregarRoteiroPT(pt);
      aplicarFiltrosDivida(1);
    }

    function construirParamsDivida() {
      const p = new URLSearchParams();
      // REGRA DE OURO: Apenas registos com Dívida > 0
      p.append("valor", "gt.0");

      const buscaRaw = (document.getElementById("div-busca")?.value || "").trim();
      const ilha = document.getElementById("div-ilha")?.value || "";
      const uni = document.getElementById("div-uni")?.value || "";
      const loc = (document.getElementById("div-localidade")?.value || "").trim();
      const grupo = document.getElementById("div-grupo")?.value || "";
      const prod = document.getElementById("div-produto")?.value || "";
      const faixa = document.getElementById("div-faixa")?.value || "todas";
      const cob = document.getElementById("div-cobranca")?.value || "";
      const cf1 = document.getElementById("div-cf1")?.value || "";
      const qtdFat = document.getElementById("div-qtd-fat")?.value || "";
      const ordem = document.getElementById("div-ordem")?.value || "valor.desc";

      if (ilha) p.append("ilha", `eq.${ilha}`);
      if (uni) p.append("desc_uni", `eq.${uni}`);
      if (loc) {
        p.append("or", `(localidade.ilike.*${loc}*,pt.ilike.*${loc}*)`);
      }
      if (grupo === "__SETOR_PUBLICO__") {
        p.append("grup_tp_cli", "in.(Autarquia,Estado,Empresa Publica,Empresa Pública)");
      } else if (grupo) {
        p.append("grup_tp_cli", `eq.${grupo}`);
      }
      if (prod === "__ELETRICIDADE__") {
        p.append("produto", "in.(EB,EE,EM)");
      } else if (prod === "AG_ADS") {
        p.append("or", "(cil.in.(60220187,60220188),id_cliente.eq.60209538)");
      } else if (prod === "AG_OUTROS") {
        p.append("cil", "not.in.(60220187,60220188)");
        p.append("id_cliente", "neq.60209538");
        p.append("or", "(produto.eq.AG,divida_ag.gt.0)");
      } else if (prod === "AG") {
        p.append("or", "(produto.eq.AG,divida_ag.gt.0)");
      } else if (prod) {
        p.append("produto", `eq.${prod}`);
      }

      const emp = document.getElementById("div-empresa")?.value || "";
      if (emp === "17") {
        p.append("divida_edec", "gt.0");
      } else if (emp === "21") {
        p.append("divida_electra", "gt.0");
      } else if (emp === "7") {
        p.append("divida_sul", "gt.0");
      } else if (emp === "70") {
        p.append("divida_sarl", "gt.0");
      }
      if (cob) p.append("status_cobranca", `eq.${cob}`);

      // Faixas de Dívida e Titularidade
      if (faixa === "grandes") p.append("valor", "gte.1000000");
      else if (faixa === "250k") p.append("valor", "gte.250000");
      else if (faixa === "50k") p.append("valor", "gte.50000");
      else if (faixa === "10k") p.append("valor", "gte.10000");
      else if (faixa === "ate10k") p.append("valor", "lte.10000");
      else if (faixa === "outros_tit") p.append("divida_outros_titulares", "gt.0");

      // Fraude CF1
      if (cf1 === "com_cf1") {
        p.append("cf1_qtd_autos", "gt.0");
      } else if (cf1 === "cf1_mp") {
        p.append("cf1_estado_juridico", "eq.Enviado ao MP");
      } else if (cf1 === "sem_cf1") {
        p.append("cf1_qtd_autos", "eq.0");
      }

      // Qtd de faturas
      if (qtdFat === "1a3") {
        p.append("qtd", "gte.1");
        p.append("qtd", "lte.3");
      } else if (qtdFat === "4a12") {
        p.append("qtd", "gte.4");
        p.append("qtd", "lte.12");
      } else if (qtdFat === "gt12") {
        p.append("qtd", "gt.12");
      }

      // Busca por CIL, ID, NIB ou Nome
      if (buscaRaw) {
        const info = interpretarBusca(buscaRaw, "auto");
        if (info.ehNumero) {
          if (info.cilNorm && info.cilNorm !== info.numExato) {
            p.append("or", `(cil.eq.${info.cilNorm},cil.eq.${info.numExato},id_cliente.eq.${info.numExato},nib.eq.${info.numExato})`);
          } else {
            p.append("or", `(cil.eq.${info.numExato},id_cliente.eq.${info.numExato},nib.eq.${info.numExato})`);
          }
        } else {
          p.append("nome", `ilike.*${info.texto}*`);
        }
      }

      p.append("order", `${ordem}.nullslast`);
      return p;
    }

    async function aplicarFiltrosDivida(pagina = 1) {
      const token = ++tokenFiltroDivida;
      paginaDividaAtual = pagina;
      const offset = (paginaDividaAtual - 1) * PAGE_SIZE;

      const tbody = document.getElementById("tabela-divida-corpo");
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="14" style="text-align:center; padding:32px; color:var(--text-secondary);">Consultando devedores no Supabase...</td></tr>`;
      }

      const params = construirParamsDivida();
      params.append("limit", PAGE_SIZE);
      params.append("offset", offset);

      atualizarKPIsDivida(token);

      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?${params.toString()}`, {
          headers: { ...HEADERS, "Prefer": "count=exact" }
        });
        if (token !== tokenFiltroDivida) return;

        const cr = r.headers.get("content-range");
        if (cr) {
          const m = cr.match(/\/(\d+|\*)/);
          if (m && m[1] !== "*") totalDevedoresFiltrados = parseInt(m[1], 10);
        }

        const elContTot = document.getElementById("div-contagem-total");
        if (elContTot) elContTot.textContent = `${fmtInt(totalDevedoresFiltrados)} contratos encontrados`;

        registosDividaPagina = await r.json();
        renderizarTabelaDivida(registosDividaPagina);
        atualizarPaginacaoDivida();
      } catch (e) {
        console.error("Erro ao carregar tabela de dívida:", e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="14" style="text-align:center; color:#F87171; padding:24px;">Erro ao consultar dívidas: ${e.message}</td></tr>`;
      }
    }

    async function atualizarKPIsDivida(token) {
      const ilha = document.getElementById("div-ilha")?.value || null;
      const uni = document.getElementById("div-uni")?.value || null;
      const prod = document.getElementById("div-produto")?.value || null;
      const grupo = document.getElementById("div-grupo")?.value || null;
      const cob = document.getElementById("div-cobranca")?.value || null;
      const cf1 = document.getElementById("div-cf1")?.value || "";
      const qtdFat = document.getElementById("div-qtd-fat")?.value || "";
      const loc = (document.getElementById("div-localidade")?.value || "").trim();
      const busca = (document.getElementById("div-busca")?.value || "").trim();
      const infoBusca = busca ? interpretarBusca(busca, "tudo") : {};

      let cf1FiltroRpc = null;
      if (cf1 === "com_cf1") cf1FiltroRpc = "__COM_CF1__";
      else if (cf1 === "cf1_mp") cf1FiltroRpc = "Enviado ao MP";
      else if (cf1 === "sem_cf1") cf1FiltroRpc = "__SEM_CF1__";

      try {
        const faixa = document.getElementById("div-faixa")?.value || "todas";
        let faixaRpc = "gt0";
        if (faixa === "grandes") faixaRpc = "gte1000000";
        else if (faixa === "250k") faixaRpc = "gte250000";
        else if (faixa === "50k") faixaRpc = "gte50000";
        else if (faixa === "10k") faixaRpc = "gte10000";
        else if (faixa === "ate10k") faixaRpc = "ate10k";
        else if (faixa === "outros_tit") faixaRpc = "outros_tit";

        const pDividaRpc = qtdFat ? `${faixaRpc}|${qtdFat}` : faixaRpc;

        const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/get_resumo_santiago`, {
          method: "POST",
          headers: HEADERS,
          body: JSON.stringify({
            p_desc_uni: uni,
            p_est_ctr: null,
            p_grup_tp_cli: grupo,
            p_anomalia: null,
            p_alerta_desvio: null,
            p_mat_contador: null,
            p_mat_leitura: null,
            p_nivel_risco: null,
            p_pt: loc || null,
            p_cf1_filtro: cf1FiltroRpc,
            p_status_cobranca: cob,
            p_divida: pDividaRpc,
            p_busca: infoBusca.texto || null,
            p_tipo_busca: infoBusca.modo || "tudo",
            p_ilha: ilha,
            p_produto: prod || null,
            p_empresa: document.getElementById("div-empresa")?.value || null
          })
        });
        if (token !== tokenFiltroDivida) return;
        const d = await r.json();
        dadosResumoDivida = d;

        const totDiv = d.total_divida || 0;
        const totCont = d.com_divida || d.total_contratos || 0;
        const qtdDevedores = totCont;
        const semPagDiv = d.divida_sem_pagamento || 0;
        const qtdSemPag = d.devedor_sem_pagamento || 0;
        const qtdAmort = d.com_cobranca_2026 || 0;
        const totFat = d.total_faturas_divida || 0;
        const cobTotal2026 = d.cob_total_2026 || 0;
        const comCf1 = d.com_cf1 || 0;
        const cf1Div = d.cf1_divida_total || 0;
        const crit = d.risco_critico || 0;
        const alto = d.risco_alto || 0;

        // KPI 1: Dívida Total Carteira
        document.getElementById("kpi-div-total").textContent = fmtECV(totDiv);
        const elDivSubtipo = document.getElementById("lbl-kpi-div-subtipo");
        if (elDivSubtipo) {
          elDivSubtipo.textContent = uni ? `${uni.toUpperCase()} (ECV)` : (ilha ? `${ilha.toUpperCase()} (ECV)` : "REGIÃO SUL (ECV)");
        }
        const totTitAtual = Number(d.tot_divida_titular_atual || 0);
        const totOutrosTit = Number(d.tot_divida_outros_titulares || 0);
        const infoTitularesSub = totOutrosTit > 0
          ? ` • Tit. Atual: ${formatarCurtoSim(totTitAtual)} | Antigos: ${formatarCurtoSim(totOutrosTit)}`
          : "";
        document.getElementById("kpi-div-total-sub").textContent = `${fmtInt(qtdDevedores)} devedores (${fmtInt(totFat)} fat.)${infoTitularesSub}`;

        // KPI 2: Inadimplência Crítica (Sem Amortização)
        document.getElementById("kpi-div-critica").textContent = fmtECV(semPagDiv);
        const pctCritica = totDiv > 0 ? ((semPagDiv / totDiv) * 100).toFixed(1) : "0.0";
        document.getElementById("kpi-div-critica-sub").textContent = `${fmtInt(qtdSemPag)} clientes (${pctCritica}% estagnada)`;

        // KPI 3: Cobrança Realizada 2026 (Harmonizado com a Aba de Contratos)
        document.getElementById("kpi-div-arrecadado").textContent = fmtECV(cobTotal2026);
        document.getElementById("kpi-div-arrecadado-sub").textContent = `${fmtInt(qtdAmort)} pagadores (2026)`;

        // Atualizar Faixa Dinâmica de Produto & Destaque AdS vs. Restantes Clientes Água + Titularidade CIL
        const porProd = d.por_produto || [];
        const itemAg = porProd.find(p => p.produto === "AG");
        const divAg = d.tot_divida_ag !== undefined ? Number(d.tot_divida_ag) : (itemAg ? Number(itemAg.soma_divida || 0) : 0);
        const cntAg = d.devedores_ag !== undefined ? Number(d.devedores_ag) : (itemAg ? Number(itemAg.qtd_devedores || itemAg.qtd_contratos || 0) : 0);
        const fatAg = d.tot_faturas_ag !== undefined ? Number(d.tot_faturas_ag) : (itemAg ? Number(itemAg.soma_faturas || 0) : 0);

        const divAgAds = d.divida_ag_ads !== undefined ? Number(d.divida_ag_ads) : 0;
        const cntAgAds = d.devedores_ag_ads !== undefined ? Number(d.devedores_ag_ads) : 0;
        const fatAgAds = d.faturas_ag_ads !== undefined ? Number(d.faturas_ag_ads) : 0;

        const divAgOutros = d.divida_ag_outros !== undefined ? Number(d.divida_ag_outros) : Math.max(0, divAg - divAgAds);
        const cntAgOutros = d.devedores_ag_outros !== undefined ? Number(d.devedores_ag_outros) : Math.max(0, cntAg - cntAgAds);
        const fatAgOutros = d.faturas_ag_outros !== undefined ? Number(d.faturas_ag_outros) : Math.max(0, fatAg - fatAgAds);

        const itensElet = porProd.filter(p => p.produto !== "AG");
        const divElet = d.tot_divida_en !== undefined ? Number(d.tot_divida_en) : itensElet.reduce((s, p) => s + Number(p.soma_divida || 0), 0);
        const cntElet = itensElet.reduce((s, p) => s + Number(p.qtd_devedores || p.qtd_contratos || 0), 0);
        const fatElet = d.tot_faturas_en !== undefined ? Number(d.tot_faturas_en) : itensElet.reduce((s, p) => s + Number(p.soma_faturas || 0), 0);
        const cobElet = itensElet.reduce((s, p) => s + Number(p.soma_cob_2026 || 0), 0);

        const elValElet = document.getElementById("prod-val-elet");
        const elDetElet = document.getElementById("prod-det-elet");
        const elPctElet = document.getElementById("prod-pct-elet");

        const elValAgua = document.getElementById("prod-val-agua");
        const elDetAgua = document.getElementById("prod-det-agua");
        const elPctAgua = document.getElementById("prod-pct-agua");

        const elValAguaOutros = document.getElementById("prod-val-agua-outros");
        const elDetAguaOutros = document.getElementById("prod-det-agua-outros");
        const elPctAguaOutros = document.getElementById("prod-pct-agua-outros");

        const elValOutrosTit = document.getElementById("prod-val-outros-tit");
        const elDetOutrosTit = document.getElementById("prod-det-outros-tit");
        const elPctOutrosTit = document.getElementById("prod-pct-outros-tit");

        const elPillTot = document.getElementById("pill-tot-div");
        const elPillElet = document.getElementById("pill-elet-div");
        const elPillAguaAds = document.getElementById("pill-agua-ads-div");
        const elPillAguaOutros = document.getElementById("pill-agua-outros-div");
        const elPillAgua = document.getElementById("pill-agua-div");

        if (elValElet) elValElet.textContent = fmtECV(divElet);
        if (elDetElet) elDetElet.textContent = `${fmtInt(cntElet)} devedores (${fmtInt(fatElet)} fat.) • ${fmtECV(cobElet)} cobrado em 2026`;
        if (elPctElet) elPctElet.textContent = totDiv > 0 ? `${((divElet / totDiv) * 100).toFixed(1)}% da Dívida` : "0%";

        if (elValAgua) elValAgua.textContent = fmtECV(divAgAds);
        if (elDetAgua) elDetAgua.textContent = `${fmtInt(cntAgAds)} CILs AdS (${fmtInt(fatAgAds)} fat.) • Emp. 21 + Emp. 07`;
        if (elPctAgua) elPctAgua.textContent = totDiv > 0 ? `${((divAgAds / totDiv) * 100).toFixed(1)}% da Dívida` : "0%";

        if (elValAguaOutros) elValAguaOutros.textContent = fmtECV(divAgOutros);
        if (elDetAguaOutros) elDetAguaOutros.textContent = `${fmtInt(cntAgOutros)} clientes finais AG (${fmtInt(fatAgOutros)} fat.) • Domésticos, Autarquias e Empresas`;
        if (elPctAguaOutros) elPctAguaOutros.textContent = totDiv > 0 ? `${((divAgOutros / totDiv) * 100).toFixed(1)}% da Dívida` : "0%";

        const cilsDivOutros = Number(d.cils_divida_outros_titulares || 0);
        const cilsMultiCli = Number(d.cils_multi_cliente || 0);
        if (elValOutrosTit) elValOutrosTit.textContent = fmtECV(totOutrosTit);
        if (elDetOutrosTit) elDetOutrosTit.textContent = `${fmtInt(cilsDivOutros)} CILs c/ dívida anterior (${fmtInt(cilsMultiCli)} CILs multi-titular) • Tit. Atual: ${fmtECV(totTitAtual)}`;
        if (elPctOutrosTit) elPctOutrosTit.textContent = totDiv > 0 ? `${((totOutrosTit / totDiv) * 100).toFixed(1)}% da Dívida` : "0%";

        if (elPillTot) elPillTot.textContent = fmtECV(totDiv);
        if (elPillElet) elPillElet.textContent = fmtECV(divElet);
        if (elPillAguaAds) elPillAguaAds.textContent = fmtECV(divAgAds);
        if (elPillAguaOutros) elPillAguaOutros.textContent = fmtECV(divAgOutros);
        if (elPillAgua) elPillAgua.textContent = fmtECV(divAg);
        if (typeof atualizarBotoesProdutoDivida === "function") atualizarBotoesProdutoDivida(prod || "");

        // Atualizar Indicadores de Composição por Empresa Credora
        const divEdec = Number(d.tot_divida_edec || 0);
        const fatEdec = Number(d.tot_faturas_edec || 0);
        const cntEdec = Number(d.devedores_edec || 0);

        const divElectra = Number(d.tot_divida_electra || 0);
        const fatElectra = Number(d.tot_faturas_electra || 0);
        const cntElectra = Number(d.devedores_electra || 0);

        const divSul = Number(d.tot_divida_sul || 0);
        const fatSul = Number(d.tot_faturas_sul || 0);
        const cntSul = Number(d.devedores_sul || 0);

        const divSarl = Number(d.tot_divida_sarl || 0);
        const fatSarl = Number(d.tot_faturas_sarl || 0);
        const cntSarl = Number(d.devedores_sarl || 0);

        const elVal17 = document.getElementById("emp-val-17");
        const elDet17 = document.getElementById("emp-det-17");
        const elPct17 = document.getElementById("emp-pct-17");
        if (elVal17) elVal17.textContent = fmtECV(divEdec);
        if (elDet17) elDet17.textContent = `${fmtInt(cntEdec)} devedores (${fmtInt(fatEdec)} fat.) • Faturação Atual`;
        if (elPct17) elPct17.textContent = totDiv > 0 ? `${((divEdec / totDiv) * 100).toFixed(1)}%` : "0%";

        const elVal21 = document.getElementById("emp-val-21");
        const elDet21 = document.getElementById("emp-det-21");
        const elPct21 = document.getElementById("emp-pct-21");
        if (elVal21) elVal21.textContent = fmtECV(divElectra);
        if (elDet21) elDet21.textContent = `${fmtInt(cntElectra)} devedores (${fmtInt(fatElectra)} fat.) • Contrato Especial AdS`;
        if (elPct21) elPct21.textContent = totDiv > 0 ? `${((divElectra / totDiv) * 100).toFixed(1)}%` : "0%";

        const elVal7 = document.getElementById("emp-val-7");
        const elDet7 = document.getElementById("emp-det-7");
        const elPct7 = document.getElementById("emp-pct-7");
        if (elVal7) elVal7.textContent = fmtECV(divSul);
        if (elDet7) elDet7.textContent = `${fmtInt(cntSul)} devedores (${fmtInt(fatSul)} fat.) • Dívida Sul Histórica`;
        if (elPct7) elPct7.textContent = totDiv > 0 ? `${((divSul / totDiv) * 100).toFixed(1)}%` : "0%";

        const elVal70 = document.getElementById("emp-val-70");
        const elDet70 = document.getElementById("emp-det-70");
        const elPct70 = document.getElementById("emp-pct-70");
        if (elVal70) elVal70.textContent = fmtECV(divSarl);
        if (elDet70) elDet70.textContent = `${fmtInt(cntSarl)} devedores (${fmtInt(fatSarl)} fat.) • Dívida Antiga Legada`;
        if (elPct70) elPct70.textContent = totDiv > 0 ? `${((divSarl / totDiv) * 100).toFixed(1)}%` : "0%";

        const elPillTotEmp = document.getElementById("pill-tot-emp");
        const elPill17 = document.getElementById("pill-emp-17");
        const elPill21 = document.getElementById("pill-emp-21");
        const elPill7 = document.getElementById("pill-emp-7");
        const elPill70 = document.getElementById("pill-emp-70");
        if (elPillTotEmp) elPillTotEmp.textContent = fmtECV(totDiv);
        if (elPill17) elPill17.textContent = fmtECV(divEdec);
        if (elPill21) elPill21.textContent = fmtECV(divElectra);
        if (elPill7) elPill7.textContent = fmtECV(divSul);
        if (elPill70) elPill70.textContent = fmtECV(divSarl);
        if (typeof atualizarBotoesEmpresaDivida === "function") atualizarBotoesEmpresaDivida(document.getElementById("div-empresa")?.value || "");
        carregarEvolucaoMensalDivida(document.getElementById("div-ilha")?.value || "");

        // KPI 4: Taxa de Recuperação 2026
        const baseRecup = cobTotal2026 + totDiv;
        const taxaRecup = baseRecup > 0 ? ((cobTotal2026 / baseRecup) * 100).toFixed(1) : "0.0";
        document.getElementById("kpi-div-taxa-recup").textContent = `${taxaRecup}%`;
        document.getElementById("kpi-div-taxa-recup-sub").textContent = `Cobrança 2026 vs Carteira Total`;

        // KPI 5: Ticket Médio Devedor
        const ticketMedio = totCont > 0 ? Math.round(totDiv / totCont) : 0;
        const medFat = totCont > 0 ? (totFat / totCont).toFixed(1) : "0";
        document.getElementById("kpi-div-ticket-medio").textContent = fmtECV(ticketMedio);
        document.getElementById("kpi-div-ticket-medio-sub").textContent = `Média: ${medFat} fat./cliente`;

        // KPI 6: Concentração Top Devedores (Pareto Real > 250k ECV e > 1M ECV)
        const divGrandes250k = d.divida_grandes_250k !== undefined ? Number(d.divida_grandes_250k) : Math.round(totDiv * 0.776);
        const qtdGrandes250k = d.qtd_grandes_250k !== undefined ? Number(d.qtd_grandes_250k) : 0;
        const qtdMilionarios = d.qtd_milionarios_1m !== undefined ? Number(d.qtd_milionarios_1m) : 0;
        const pctPareto = totDiv > 0 ? ((divGrandes250k / totDiv) * 100).toFixed(1) : "0.0";
        document.getElementById("kpi-div-grandes").textContent = fmtECV(divGrandes250k);
        document.getElementById("kpi-div-grandes-sub").textContent = `${fmtInt(qtdGrandes250k)} contas >250k (${pctPareto}% da dívida) • ${fmtInt(qtdMilionarios)} >1M`;

        // KPI 7: Devedores com Auto CF1
        document.getElementById("kpi-div-cf1").textContent = `${fmtInt(comCf1)} clientes`;
        document.getElementById("kpi-div-cf1-sub").textContent = `Dív. CF1: ${fmtECV(cf1Div)} • MP: ${fmtInt(d.cf1_enviado_mp || 0)}`;

        // KPI 8: Carteira em Risco
        document.getElementById("kpi-div-risco").textContent = `${fmtInt(crit + alto)} clientes`;
        document.getElementById("kpi-div-risco-sub").textContent = `${fmtInt(crit)} Crít. / ${fmtInt(alto)} Alto • Sc: ${d.score_medio || 0}/100`;

        document.getElementById("div-contagem-total").textContent = `${fmtInt(totCont)} contratos encontrados`;

        // Renderizar Painéis de Distribuição (Concelhos & PTs com Maior Dívida)
        renderizarDistribuicaoConcelhos(d.por_unidade || []);
        renderizarTopPTsDivida(d.top_pts_maior_divida || d.top_pts_divida || []);
        atualizarSimulador();
        if (clientesRoteiroPT.length === 0) {
          carregarRoteiroPT(ptAtivoRoteiro);
        }
      } catch (e) {
        console.error("Erro ao atualizar KPIs de dívida:", e);
      }
    }

    function renderizarDistribuicaoConcelhos(unidades) {
      const container = document.getElementById("lista-unidades-divida");
      if (!container) return;

      if (!unidades || !unidades.length) {
        container.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);">Sem dados de unidades para os filtros atuais.</div>`;
        return;
      }

      const totalSomaDivida = unidades.reduce((acc, u) => acc + (u.soma_divida || 0), 0) || 1;

      container.innerHTML = unidades.map(u => {
        const divVal = u.soma_divida || 0;
        const cobVal = u.soma_cob_2026 || 0;
        const pctShare = ((divVal / totalSomaDivida) * 100).toFixed(1);
        const taxaRecup = (cobVal + divVal) > 0 ? ((cobVal / (cobVal + divVal)) * 100).toFixed(1) : "0.0";

        return `
          <div class="rank-item" onclick="filtrarConcelhoDivida('${u.desc_uni}')" title="Clique para filtrar apenas o concelho ${u.desc_uni}">
            <div class="rank-top">
              <span style="color:var(--text-primary); font-weight:700;">📍 ${u.desc_uni}</span>
              <span style="font-family:var(--font-mono); color:#FBBF24;">${fmtECV(divVal)}</span>
            </div>
            <div class="rank-metrics">
              <span>${fmtInt(u.qtd_contratos || 0)} devedores (${pctShare}% share)</span>
              <span>Arrecadado: <strong style="color:#34D399;">${fmtECV(cobVal)}</strong> (Recup: ${taxaRecup}%)</span>
            </div>
            <div class="rank-bar-track">
              <div class="rank-bar-fill" style="width: ${Math.min(100, Math.max(5, pctShare))}%;"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    function renderizarTopPTsDivida(pts) {
      const container = document.getElementById("lista-pts-divida");
      if (!container) return;

      if (!pts || !pts.length) {
        container.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);">Sem postos de transformação críticos.</div>`;
        return;
      }

      const maxDiv = Math.max(...pts.map(p => p.soma_divida || 0), 1);

      container.innerHTML = pts.slice(0, 8).map(pt => {
        const divVal = pt.soma_divida || 0;
        const cobVal = pt.soma_cob_2026 || 0;
        const pctBar = ((divVal / maxDiv) * 100).toFixed(0);

        return `
          <div class="rank-item" onclick="filtrarPTDivida('${pt.pt}')" title="Clique para filtrar clientes do PT ${pt.pt}">
            <div class="rank-top">
              <span style="color:var(--accent-amber); font-weight:700;">⚡ PT ${pt.pt || 'Não Identificado'}</span>
              <span style="font-family:var(--font-mono); color:#F87171;">${fmtECV(divVal)}</span>
            </div>
            <div class="rank-metrics">
              <span>${fmtInt(pt.qtd_contratos || 0)} contratos • ${pt.qtd_cf1 || 0} autos CF1</span>
              <span>Cobrado: <strong style="color:#34D399;">${fmtECV(cobVal)}</strong></span>
            </div>
            <div class="rank-bar-track">
              <div class="rank-bar-fill" style="width: ${pctBar}%; background: linear-gradient(90deg, #F59E0B, #EF4444);"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    function calcularAcaoRecomendada(r) {
      const val = Number(r.valor || 0);
      const qtdFat = Number(r.qtd || 0);
      const pago2026 = Number(r.cob_valor_total || 0);
      const stCob = r.status_cobranca || "";
      const grupo = (r.grup_tp_cli || "").toLowerCase();
      const cf1Qtd = Number(r.cf1_qtd_autos || 0);
      const cf1Jur = r.cf1_estado_juridico || "";

      // 0. Caso Estratégico Especial AdS (Águas de Santiago S.A. - CILs 60220187 e 60220188)
      const isAdS = (Number(r.cil) === 60220187 || Number(r.cil) === 60220188 || Number(r.id_cliente) === 60209538 || (r.nome && r.nome.toUpperCase().includes("AGUAS DE SANTIAGO")));
      if (isAdS) {
        return `<span class="badge" style="background:#083344; color:#38BDF8; border:1px solid #0284C7; font-weight:700;" title="Protocolo Governamental de Encontro de Contas AdS">💧 Protocolo Especial AdS</span>`;
      }

      // 1. Fraude CF1 com MP ou reincidência
      if (cf1Qtd > 0) {
        if (cf1Jur === "Enviado ao MP" || cf1Jur === "A enviar ao MP") {
          return `<span class="badge" style="background:#450A0A; color:#FCA5A5; border:1px solid #B91C1C;" title="Processo de Fraude CF1 no Ministério Público">⚖️ Jurídico MP + Fraude</span>`;
        }
        return `<span class="badge" style="background:#451A03; color:#FCD34D; border:1px solid #D97706;" title="Auto de fiscalização CF1 registado">⚡ Brigada CF1</span>`;
      }

      // 2. Setor Público (Autarquias / Estado / Empresa Pública)
      if (grupo.includes("autarquia") || grupo.includes("estado") || grupo.includes("publica") || grupo.includes("pública")) {
        return `<span class="badge" style="background:#1E1B4B; color:#C7D2FE; border:1px solid #4338CA;" title="Cliente de Estado / Câmara Municipal">🏛️ Protocolo Estado</span>`;
      }

      // 3. Corte Imediato (Dívida alta sem amortização recente)
      if (val >= 100000 && (pago2026 <= 0 || stCob === "Devedor Sem Pagamento 2026")) {
        return `<span class="badge badge-danger" title="Grande devedor sem qualquer pagamento em 2026">🚨 Corte Imediato</span>`;
      }

      // 4. Acordo / Parcelamento (Pagando regularmente ou amortizando)
      if (pago2026 > 0 || stCob.includes("Amortiza")) {
        return `<span class="badge badge-ok" title="Cliente ativo em pagamento com saldo residual">🤝 Acordo / Parcelar</span>`;
      }

      // 5. Cobrança Rápida / Notificação de Corte
      if (qtdFat >= 4) {
        return `<span class="badge badge-warn" title="Mais de 3 faturas acumuladas">⚠️ Notificar Pré-Corte</span>`;
      }

      // 6. Monitoramento de Baixo Valor
      return `<span class="badge" style="background:#1E293B; color:#94A3B8; border:1px solid #475569;" title="Dívida recente ou de baixa complexidade">✉️ Cobrança Normal</span>`;
    }

    function renderizarTabelaDivida(linhas) {
      const tbody = document.getElementById("tabela-divida-corpo");
      if (!tbody) return;

      if (!linhas || !linhas.length) {
        tbody.innerHTML = `<tr><td colspan="14" style="text-align:center; padding:32px; color:var(--text-muted);">Nenhum contrato devedor encontrado com os filtros selecionados.</td></tr>`;
        return;
      }

      tbody.innerHTML = linhas.map(r => {
        const valDiv = r.valor || 0;
        const qtdFat = r.qtd || 0;
        const pago2026 = r.cob_valor_total || 0;
        const stCob = r.status_cobranca || "";
        const isGrande = valDiv >= 1000000;
        const isMedioGrande = valDiv >= 250000;

        const compEmp = [];
        if (Number(r.divida_edec || 0) > 0) compEmp.push(`<span style="color:#60A5FA; background:rgba(96,165,250,0.12); padding:1px 4px; border-radius:3px;" title="17 - EDEC SA: ${fmtInt(r.divida_edec)} ECV (${r.faturas_edec || 0} fat.)">EDEC: ${fmtInt(r.divida_edec)}</span>`);
        if (Number(r.divida_electra || 0) > 0) compEmp.push(`<span style="color:#FBBF24; background:rgba(251,191,36,0.12); padding:1px 4px; border-radius:3px;" title="21 - ELECTRA SA: ${fmtInt(r.divida_electra)} ECV (${r.faturas_electra || 0} fat.)">ELECTRA: ${fmtInt(r.divida_electra)}</span>`);
        if (Number(r.divida_sul || 0) > 0) compEmp.push(`<span style="color:#A78BFA; background:rgba(167,139,250,0.12); padding:1px 4px; border-radius:3px;" title="07 - EDEC Sul: ${fmtInt(r.divida_sul)} ECV (${r.faturas_sul || 0} fat.)">Sul: ${fmtInt(r.divida_sul)}</span>`);
        if (Number(r.divida_sarl || 0) > 0) compEmp.push(`<span style="color:#F472B6; background:rgba(244,114,182,0.12); padding:1px 4px; border-radius:3px;" title="70 - ELECTRA SARL: ${fmtInt(r.divida_sarl)} ECV (${r.faturas_sarl || 0} fat.)">SARL: ${fmtInt(r.divida_sarl)}</span>`);
        if (Number(r.divida_ag || 0) > 0 && Number(r.divida_en || 0) > 0) compEmp.push(`<span style="color:#38BDF8; background:rgba(14,165,233,0.15); padding:1px 4px; border-radius:3px;" title="Parcela Água AG: ${fmtInt(r.divida_ag)} ECV (${r.faturas_ag || 0} fat.)">🚰 AG: ${fmtInt(r.divida_ag)}</span>`);
        const subEmpHtml = compEmp.length ? `<div style="font-family:var(--font-mono); font-size:9.5px; margin-top:3px; display:flex; gap:3px; justify-content:flex-end; flex-wrap:wrap;">${compEmp.join("")}</div>` : "";

        const badgeDiv = (isGrande
          ? `<span class="badge badge-danger" title="Grande Devedor (> 1M ECV)">🔥 ${fmtInt(valDiv)} ECV</span>`
          : (isMedioGrande
              ? `<span class="badge badge-warn" title="Devedor Elevado (> 250k ECV)">⚡ ${fmtInt(valDiv)} ECV</span>`
              : `<span style="font-family:var(--font-mono); font-weight:600; color:#FBBF24;">${fmtInt(valDiv)} ECV</span>`)) + subEmpHtml;

        const badgeSt = stCob === "Devedor Sem Pagamento 2026"
          ? `<span class="badge badge-danger">🚨 Sem Pag. 2026</span>`
          : (pago2026 > 0 ? `<span class="badge badge-warn">🟡 Em Amortização</span>` : `<span style="color:var(--text-muted);">${stCob || '—'}</span>`);

        const cf1Qtd = Number(r.cf1_qtd_autos || 0);
        const cf1Jur = r.cf1_estado_juridico || "";
        const badgeCf1 = cf1Qtd > 0
          ? (cf1Jur === "Enviado ao MP" ? `<span class="badge badge-danger" title="${cf1Qtd} auto(s) no MP">⚡ ${cf1Qtd} (MP)</span>` : `<span class="badge badge-purple" title="${cf1Qtd} auto(s) CF1">⚡ ${cf1Qtd} Auto(s)</span>`)
          : `<span style="color:var(--text-muted); font-size:11px;">—</span>`;

        const badgeAcao = calcularAcaoRecomendada(r);
        const isAdS = (Number(r.cil) === 60220187 || Number(r.cil) === 60220188 || Number(r.id_cliente) === 60209538 || (r.nome && r.nome.toUpperCase().includes("AGUAS DE SANTIAGO")));
        const isAguaOutro = !isAdS && (r.produto === "AG" || Number(r.divida_ag || 0) > 0);
        const rowStyle = isAdS ? `style="background:rgba(6,182,212,0.08); border-left:4px solid #06B6D4;"` : "";
        const badgesMulti = `${Number(r.qtd_clientes_distintos || 1) > 1 ? `<span class="badge" style="margin-left:4px; font-size:9.5px; padding:1px 4px; background:rgba(56,189,248,0.14); color:#38BDF8; border:1px solid rgba(56,189,248,0.35);" title="${r.qtd_clientes_distintos} titulares distintos neste CIL (${r.qtd_contratos_hist || 1} contratos). Dívida titular atual: ${fmtECV(r.divida_titular_atual ?? r.valor)} | Outros titulares: ${fmtECV(r.divida_outros_titulares || 0)}">👥 ${r.qtd_clientes_distintos} tit.</span>` : ""}${Number(r.divida_outros_titulares || 0) > 0 ? `<span class="badge badge-warn" style="margin-left:3px; font-size:9.5px; padding:1px 4px;" title="Dívida de outros titulares anteriores neste CIL: ${fmtECV(r.divida_outros_titulares)}">⚠️ Ant: ${fmtInt(r.divida_outros_titulares)}</span>` : ""}`;
        const nomeHtml = isAdS 
          ? `<div style="font-weight:700; color:#E0F2FE;">${r.nome}${badgesMulti}</div><span class="badge" style="background:rgba(6,182,212,0.25); color:#22D3EE; border:1px solid #06B6D4; font-size:9.5px; font-weight:700; margin-top:2px; display:inline-block;">💧 CONTA ESPECIAL AdS (ÁGUA)</span>`
          : `<span style="font-weight:500;">${r.nome || '—'}</span>${badgesMulti}`;

        return `
          <tr ${rowStyle}>
            <td style="font-family:var(--font-mono); font-weight:600; color:var(--accent-cyan);">${r.cil}</td>
            <td style="font-family:var(--font-mono); color:var(--text-muted);">${r.id_cliente || r.id || '—'}</td>
            <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${r.nome || ''}">${nomeHtml}</td>
            <td><span class="badge" style="background:#131C2B; border:1px solid var(--border-bright);">${r.desc_uni || '—'}</span></td>
            <td style="color:var(--text-secondary); max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${r.localidade || ''} • PT: ${r.pt || '-'}">${r.localidade || '—'}${r.pt ? ' <span style="color:var(--accent-cyan); font-family:var(--font-mono); font-size:10px;">(' + r.pt + ')</span>' : ''}</td>
            <td>${r.grup_tp_cli || '—'}</td>
            <td>${isAdS ? '<span class="badge" style="background:rgba(6,182,212,0.25); color:#22D3EE; border:1px solid #06B6D4; font-weight:700; padding:2px 8px;">💧 AdS (Água)</span>' : (isAguaOutro ? '<span class="badge" style="background:rgba(14,165,233,0.18); color:#38BDF8; border:1px solid #0EA5E9; font-weight:600; padding:2px 8px;">🚰 AG (Água)</span>' : `<span class="badge" style="font-family:var(--font-mono);">${r.produto || '—'}</span>`)}</td>
            <td style="text-align:right; font-family:var(--font-mono); ${qtdFat > 12 ? 'color:#F87171; font-weight:700;' : ''}">${fmtInt(qtdFat)}</td>
            <td style="text-align:right;">${badgeDiv}</td>
            <td style="text-align:right; font-family:var(--font-mono); color:#34D399;">${pago2026 > 0 ? fmtInt(pago2026) + ' ECV' : '<span style="color:var(--text-muted);">0</span>'}</td>
            <td>${badgeSt}</td>
            <td style="text-align:center;">${badgeCf1}</td>
            <td>${badgeAcao}</td>
            <td style="text-align:center;">
              <button class="btn btn-sm" onclick="abrirDossieTecnico(${r.cil})" title="Ver Ficha Técnica Completa">Ver Ficha</button>
            </td>
          </tr>
        `;
      }).join("");
    }


    async function carregarEvolucaoMensalDivida(ilhaFiltro = "") {
      const escopo = ilhaFiltro ? ilhaFiltro : "TODAS";
      const badgeEl = document.getElementById("snap-scope-badge");
      if (badgeEl) badgeEl.textContent = ilhaFiltro ? `Ilha de ${ilhaFiltro}` : "Região Sul (4 Ilhas)";

      try {
        const r = await fetch(
          `${SUPABASE_URL}/rest/v1/santiago_snapshot_mensal?ilha=eq.${encodeURIComponent(escopo)}&select=*&order=ano_mes.asc`,
          { headers: HEADERS }
        );
        if (!r.ok) return;
        const serie = await r.json();
        if (!Array.isArray(serie) || serie.length === 0) return;

        const first = serie[0];
        const last = serie[serie.length - 1];
        const maxTotal = Math.max(...serie.map(s => Number(s.divida_total) || 1));

        const fmtCurto = (v) => {
          const n = Number(v) || 0;
          if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2).replace(".", ",") + " B";
          if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " M";
          return fmtInt(Math.round(n));
        };

        const deltaTot = (Number(last.divida_total) || 0) - (Number(first.divida_total) || 0);
        const deltaPct = first.divida_total > 0 ? ((deltaTot / first.divida_total) * 100).toFixed(1) : "0.0";
        const sumEl = document.getElementById("snap-delta-summary");
        if (sumEl) {
          const corD = deltaTot > 0 ? "#F87171" : "#34D399";
          const sinal = deltaTot > 0 ? "+" : "";
          sumEl.innerHTML = `Variação ${first.label_periodo} ➔ ${last.label_periodo}: <strong style="color:${corD};">${sinal}${fmtCurto(deltaTot)} ECV (${sinal}${deltaPct}%)</strong>`;
        }

        const barsBox = document.getElementById("snap-bars-container");
        if (barsBox) {
          barsBox.innerHTML = serie.map(s => {
            const tot = Number(s.divida_total) || 1;
            const wTot = Math.max(15, (tot / maxTotal) * 100);
            const p17 = (Number(s.divida_edec_17) / tot) * 100;
            const p21 = (Number(s.divida_electra_21) / tot) * 100;
            const p07 = (Number(s.divida_sul_07) / tot) * 100;
            const p70 = (Number(s.divida_sarl_70) / tot) * 100;
            return `
              <div style="margin-bottom:8px;">
                <div style="display:flex; justify-content:space-between; font-family:var(--font-mono); font-size:11px; margin-bottom:3px;">
                  <span style="font-weight:700; color:var(--text-primary);">${s.label_periodo} <span style="color:var(--text-muted); font-weight:400;">(${fmtInt(s.total_devedores)} dev.)</span></span>
                  <span style="font-weight:800; color:var(--text-primary);">${fmtCurto(s.divida_total)} ECV</span>
                </div>
                <div style="width:${wTot.toFixed(1)}%; height:13px; border-radius:4px; overflow:hidden; display:flex; background:#1E293B; border:1px solid var(--border-dim);">
                  <div style="width:${p17.toFixed(1)}%; background:#60A5FA;" title="17 - EDEC SA: ${fmtECV(s.divida_edec_17)}"></div>
                  <div style="width:${p21.toFixed(1)}%; background:#FBBF24;" title="21 - ELECTRA SA: ${fmtECV(s.divida_electra_21)}"></div>
                  <div style="width:${p07.toFixed(1)}%; background:#A78BFA;" title="07 - EDEC Sul: ${fmtECV(s.divida_sul_07)}"></div>
                  <div style="width:${p70.toFixed(1)}%; background:#F472B6;" title="70 - ELECTRA SARL: ${fmtECV(s.divida_sarl_70)}"></div>
                </div>
                <div style="display:flex; justify-content:space-between; font-family:var(--font-mono); font-size:9.8px; color:var(--text-secondary); margin-top:2px;">
                  <span style="color:#60A5FA;">17: ${fmtCurto(s.divida_edec_17)}</span>
                  <span style="color:#FBBF24;">21: ${fmtCurto(s.divida_electra_21)}</span>
                  <span style="color:#A78BFA;">07: ${fmtCurto(s.divida_sul_07)}</span>
                  <span style="color:#F472B6;">70: ${fmtCurto(s.divida_sarl_70)}</span>
                </div>
              </div>
            `;
          }).join("");
        }

        const deltasBox = document.getElementById("snap-deltas-container");
        if (deltasBox) {
          const empresas = [
            { cod: "17 - EDEC SA", cor: "#60A5FA", v0: Number(first.divida_edec_17), v1: Number(last.divida_edec_17), nota: "Faturação Corrente" },
            { cod: "21 - ELECTRA SA", cor: "#FBBF24", v0: Number(first.divida_electra_21), v1: Number(last.divida_electra_21), nota: "Contrato Especial AdS" },
            { cod: "07 - EDEC Sul", cor: "#A78BFA", v0: Number(first.divida_sul_07), v1: Number(last.divida_sul_07), nota: "Histórico Regional Sul" },
            { cod: "70 - ELECTRA SARL", cor: "#F472B6", v0: Number(first.divida_sarl_70), v1: Number(last.divida_sarl_70), nota: "Dívida Antiga Legada" }
          ];
          deltasBox.innerHTML = `
            <div style="font-size:11px; font-weight:700; color:var(--text-secondary); text-transform:uppercase; margin-bottom:8px; font-family:var(--font-mono);">
              Variação Acumulada (${first.label_periodo} ➔ ${last.label_periodo})
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
              ${empresas.map(e => {
                const dif = e.v1 - e.v0;
                const pct = e.v0 > 0 ? ((dif / e.v0) * 100).toFixed(1) : "0.0";
                const reduziu = dif <= 0;
                const corBadge = reduziu ? "#34D399" : "#F87171";
                const sinal = dif > 0 ? "+" : "";
                return `
                  <div style="padding:8px 10px; border-radius:6px; background:var(--bg-input); border-left:3px solid ${e.cor}; border-top:1px solid var(--border-dim); border-right:1px solid var(--border-dim); border-bottom:1px solid var(--border-dim);">
                    <div style="font-family:var(--font-mono); font-size:10.5px; font-weight:700; color:${e.cor};">${e.cod}</div>
                    <div style="font-family:var(--font-display); font-size:13.5px; font-weight:800; color:${corBadge}; margin:2px 0;">
                      ${sinal}${fmtCurto(dif)} ECV (${sinal}${pct}%)
                    </div>
                    <div style="font-family:var(--font-mono); font-size:9.5px; color:var(--text-muted);">
                      ${fmtCurto(e.v0)} ➔ ${fmtCurto(e.v1)} • ${reduziu ? "Amortização ✔" : "Crescimento ▲"}
                    </div>
                  </div>
                `;
              }).join("")}
            </div>
          `;
        }
      } catch (e) {}
    }

    function atualizarPaginacaoDivida() {
      const totalPags = Math.max(1, Math.ceil(totalDevedoresFiltrados / PAGE_SIZE));
      const info = document.getElementById("div-paginacao-info");
      if (info) {
        info.textContent = `Página ${paginaDividaAtual} de ${totalPags} (${fmtInt(totalDevedoresFiltrados)} devedores)`;
      }

      const gerarBotoes = () => `
        <button class="btn btn-sm" ${paginaDividaAtual <= 1 ? "disabled" : ""} onclick="aplicarFiltrosDivida(1)">« Primeira</button>
        <button class="btn btn-sm" ${paginaDividaAtual <= 1 ? "disabled" : ""} onclick="aplicarFiltrosDivida(${paginaDividaAtual - 1})">‹ Anterior</button>
        <span style="font-family:var(--font-mono); font-size:12px; padding:0 8px;">Pág. ${paginaDividaAtual}</span>
        <button class="btn btn-sm" ${paginaDividaAtual >= totalPags ? "disabled" : ""} onclick="aplicarFiltrosDivida(${paginaDividaAtual + 1})">Próxima ›</button>
        <button class="btn btn-sm" ${paginaDividaAtual >= totalPags ? "disabled" : ""} onclick="aplicarFiltrosDivida(${totalPags})">Última »</button>
      `;

      const top = document.getElementById("div-paginacao-topo");
      const bot = document.getElementById("div-paginacao-baixo");
      if (top) top.innerHTML = gerarBotoes();
      if (bot) bot.innerHTML = gerarBotoes();
    }

    async function exportarCSVDivida() {
      const params = construirParamsDivida();
      params.append("limit", "5000"); // Exporta até 5.000 clientes prioritários
      params.append("select", "cil,id_cliente,nome,desc_uni,localidade,pt,grup_tp_cli,produto,tarifa,valor,qtd,divida_edec,faturas_edec,divida_electra,faturas_electra,divida_sul,faturas_sul,divida_sarl,faturas_sarl,empresa_predom,cob_valor_total,status_cobranca,cf1_qtd_autos,cf1_estado_juridico,score_risco,nivel_risco");

      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/contratos_santiago?${params.toString()}`, { headers: HEADERS });
        const dados = await r.json();
        if (!dados.length) {
          alert("Nenhum devedor encontrado para exportar.");
          return;
        }

        const cols = Object.keys(dados[0]);
        const csvLinhas = [
          cols.join(";"),
          ...dados.map(row => cols.map(c => `"${String(row[c] ?? "").replace(/"/g, '""')}"`).join(";"))
        ];
        const blob = new Blob(["\uFEFF" + csvLinhas.join("\n")], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `EDEC_Divida_Santiago_${dados.length}_devedores_${new Date().toISOString().slice(0,10)}.csv`;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        alert("Erro ao exportar CSV de dívida: " + e.message);
      }
    }

