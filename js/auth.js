    // =========================================================================
    // ETAPA 1: MOTOR DE AUTENTICAÇÃO SUPABASE AUTH & CONTROLO DE ACESSO (RBAC)
    // =========================================================================
    const AUTH_STORAGE_KEY = "santiago_auth_session";
    let sessaoAuthAtual = null;
    let perfilUtilizadorAtual = null;
    let cacheUtilizadoresAdmin = [];

    function alternarVisibilidadeSenha(inputId, btn) {
      const inp = document.getElementById(inputId);
      if (!inp) return;
      if (inp.type === "password") {
        inp.type = "text";
        btn.textContent = "🙈";
      } else {
        inp.type = "password";
        btn.textContent = "👁️";
      }
    }

    function lerSessaoGuardada() {
      try {
        const raw = localStorage.getItem(AUTH_STORAGE_KEY);
        if (!raw) return null;
        return JSON.parse(raw);
      } catch (e) {
        return null;
      }
    }

    function guardarSessao(sessao) {
      sessaoAuthAtual = sessao;
      try {
        if (sessao) {
          localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(sessao));
          HEADERS["Authorization"] = `Bearer ${sessao.access_token}`;
        } else {
          localStorage.removeItem(AUTH_STORAGE_KEY);
          HEADERS["Authorization"] = `Bearer ${SUPABASE_KEY}`;
        }
      } catch (e) {}
    }

    async function renovarTokenSeNecessario(sessao) {
      if (!sessao || !sessao.access_token) return null;
      const agoraSeg = Math.floor(Date.now() / 1000);
      if (sessao.expires_at && sessao.expires_at - agoraSeg > 120) {
        HEADERS["Authorization"] = `Bearer ${sessao.access_token}`;
        return sessao;
      }
      if (!sessao.refresh_token) return null;
      try {
        const r = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=refresh_token`, {
          method: "POST",
          headers: { "apikey": SUPABASE_KEY, "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: sessao.refresh_token })
        });
        if (!r.ok) return null;
        const novo = await r.json();
        guardarSessao(novo);
        return novo;
      } catch (e) {
        return null;
      }
    }

    async function carregarPerfilUtilizador(email) {
      const r = await fetch(
        `${SUPABASE_URL}/rest/v1/santiago_utilizadores?email=eq.${encodeURIComponent(email.toLowerCase().trim())}&select=*&limit=1`,
        { headers: HEADERS }
      );
      if (!r.ok) return null;
      const lista = await r.json();
      return (Array.isArray(lista) && lista.length > 0) ? lista[0] : null;
    }

    function aplicarPermissoesInterface(perfil) {
      perfilUtilizadorAtual = perfil;
      const pill = document.getElementById("auth-user-pill");
      const lbl = document.getElementById("auth-user-label");
      const btnUsers = document.getElementById("btn-gestao-users");
      const btnSenha = document.getElementById("btn-minha-senha");
      const btnLogout = document.getElementById("btn-logout-santiago");
      const btnExport = document.getElementById("btn-export");
      const btnStory = document.getElementById("btn-story-executivo");
      const tabMod2 = document.getElementById("tab-btn-mod2");
      const tabMod3 = document.getElementById("tab-btn-mod3");
      const tabMod5 = document.getElementById("tab-btn-mod5");

      const mapIcones = {
        admin: "👑 ADMIN",
        direcao: "🏛️ DIREÇÃO",
        gestor: "📊 GESTOR",
        operador: "🛠️ OPERADOR",
        visualizador: "👁️ LEITURA"
      };
      const tagNivel = mapIcones[perfil.nivel_acesso] || perfil.nivel_acesso.toUpperCase();

      if (pill && lbl) {
        lbl.textContent = `${perfil.nome} • ${tagNivel}`;
        pill.style.display = "inline-flex";
      }
      if (btnSenha) btnSenha.style.display = "inline-flex";
      if (btnLogout) btnLogout.style.display = "inline-flex";

      // Botão Gestão de Utilizadores: exclusivo para Administrador
      const ehAdmin = perfil.nivel_acesso === "admin";
      if (btnUsers) btnUsers.style.display = ehAdmin ? "inline-flex" : "none";

      // Controlo de permissões granulares
      if (btnExport) btnExport.style.display = (ehAdmin || perfil.pode_exportar) ? "inline-flex" : "none";
      if (btnStory) btnStory.style.display = (ehAdmin || perfil.pode_ver_story) ? "inline-flex" : "none";
      if (tabMod3) tabMod3.style.display = (ehAdmin || perfil.pode_ver_divida) ? "inline-flex" : "none";
      if (tabMod2) tabMod2.style.display = (ehAdmin || perfil.pode_ver_cf1) ? "inline-flex" : "none";
      if (tabMod5) tabMod5.style.display = (ehAdmin || perfil.pode_ver_cf1) ? "inline-flex" : "none";

      // Restrição geográfica por Ilha (se configurada pelo Administrador)
      const selIlha1 = document.getElementById("f-ilha");
      const selIlha3 = document.getElementById("div-ilha");
      if (perfil.ilha_restrita) {
        [selIlha1, selIlha3].forEach(sel => {
          if (sel) {
            sel.value = perfil.ilha_restrita;
            sel.disabled = true;
            sel.title = `Acesso restrito à Ilha de ${perfil.ilha_restrita}`;
          }
        });
      } else {
        [selIlha1, selIlha3].forEach(sel => {
          if (sel) {
            sel.disabled = false;
            sel.title = "";
          }
        });
      }
    }

    function mostrarEcraLogin(msgErro = "") {
      document.body.classList.add("auth-locked");
      const gate = document.getElementById("santiago-auth-gate");
      if (gate) gate.classList.remove("hidden");
      const errBox = document.getElementById("login-error-msg");
      if (errBox) {
        if (msgErro) {
          errBox.textContent = msgErro;
          errBox.style.display = "block";
        } else {
          errBox.style.display = "none";
        }
      }
    }

    async function carregarSeloAuditoriaETL() {
      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/santiago_etl_execucoes?select=*&order=executado_em.desc&limit=1`, {
          headers: HEADERS
        });
        if (!r.ok) return;
        const arr = await r.json();
        const u = arr && arr[0];
        if (!u) return;
        const dt = new Date(u.executado_em).toLocaleString("pt-PT", {
          day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"
        });
        const txt = document.getElementById("etl-audit-text");
        const pill = document.getElementById("etl-audit-pill");
        if (txt) {
          txt.innerHTML = `Dados: <strong style="color:var(--text-primary);">${dt}</strong> ${u.reconciliacao_ok ? '<span style="color:#34D399;">✔</span>' : '<span style="color:#F87171;">⚠️</span>'}`;
        }
        if (pill) {
          pill.title = `Última Carga ETL: ${dt} | Contratos: ${fmtInt(u.total_contratos)} | Dívida Conciliada: ${fmtECV(u.divida_total)} (Dif: ${u.diferenca_reconciliacao_pct}%)`;
        }
      } catch (e) {}
    }

    function desbloquearPainelPosLogin() {
      document.body.classList.remove("auth-locked");
      const gate = document.getElementById("santiago-auth-gate");
      if (gate) gate.classList.add("hidden");
      if (!map) {
        iniciarMapa();
      } else {
        setTimeout(() => map.invalidateSize(), 100);
      }
      carregarSeloAuditoriaETL();
      carregarListasFiltros();
      aplicarFiltros(1);
    }

    async function submeterLoginSantiago(ev) {
      ev.preventDefault();
      const email = (document.getElementById("login-email")?.value || "").trim().toLowerCase();
      const password = document.getElementById("login-password")?.value || "";
      const btn = document.getElementById("btn-login-submit");
      const errBox = document.getElementById("login-error-msg");

      if (errBox) errBox.style.display = "none";
      if (btn) {
        btn.disabled = true;
        btn.textContent = "A autenticar no Supabase...";
      }

      try {
        const r = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
          method: "POST",
          headers: { "apikey": SUPABASE_KEY, "Content-Type": "application/json" },
          body: JSON.stringify({ email, password })
        });
        const dados = await r.json();
        if (!r.ok || !dados.access_token) {
          throw new Error(dados.error_description || dados.msg || "Email ou palavra-passe incorretos.");
        }

        guardarSessao(dados);
        const perfil = await carregarPerfilUtilizador(email);
        if (!perfil) {
          guardarSessao(null);
          throw new Error("A sua conta não está autorizada na lista de utilizadores do Sistema Santiago.");
        }
        if (!perfil.ativo) {
          guardarSessao(null);
          throw new Error("A sua conta encontra-se suspensa. Contacte o Administrador (vitfonseca73@gmail.com).");
        }

        aplicarPermissoesInterface(perfil);
        desbloquearPainelPosLogin();
      } catch (err) {
        mostrarEcraLogin(err.message || "Falha na autenticação.");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Entrar no Sistema ➔";
        }
      }
    }

    async function terminarSessaoSantiago() {
      try {
        if (sessaoAuthAtual?.access_token) {
          await fetch(`${SUPABASE_URL}/auth/v1/logout`, {
            method: "POST",
            headers: HEADERS
          });
        }
      } catch (e) {}
      guardarSessao(null);
      perfilUtilizadorAtual = null;
      mostrarEcraLogin();
    }

    async function iniciarFluxoAutenticacao() {
      document.body.classList.add("auth-locked");
      const sessao = await renovarTokenSeNecessario(lerSessaoGuardada());
      if (!sessao || !sessao.user?.email) {
        guardarSessao(null);
        mostrarEcraLogin();
        return;
      }
      const perfil = await carregarPerfilUtilizador(sessao.user.email);
      if (!perfil || !perfil.ativo) {
        guardarSessao(null);
        mostrarEcraLogin("Sessão expirada ou conta sem permissão ativa.");
        return;
      }
      aplicarPermissoesInterface(perfil);
      desbloquearPainelPosLogin();
    }

    // =========================================================================
    // GESTÃO DE UTILIZADORES E ACESSOS (EXCLUSIVO ADMIN)
    // =========================================================================
    function aoMudarNivelAcessoForm(nivel) {
      const cDiv = document.getElementById("rbac-perm-divida");
      const cCf1 = document.getElementById("rbac-perm-cf1");
      const cSto = document.getElementById("rbac-perm-story");
      const cExp = document.getElementById("rbac-perm-export");
      if (!cDiv || !cCf1 || !cSto || !cExp) return;

      if (nivel === "admin" || nivel === "direcao" || nivel === "gestor") {
        cDiv.checked = true;
        cCf1.checked = true;
        cSto.checked = true;
        cExp.checked = true;
      } else if (nivel === "operador") {
        cDiv.checked = true;
        cCf1.checked = true;
        cSto.checked = false;
        cExp.checked = false;
      } else {
        cDiv.checked = true;
        cCf1.checked = false;
        cSto.checked = false;
        cExp.checked = false;
      }
    }

    function limparFormularioUtilizador() {
      document.getElementById("rbac-user-id").value = "";
      document.getElementById("rbac-nome").value = "";
      const inpEmail = document.getElementById("rbac-email");
      inpEmail.value = "";
      inpEmail.disabled = false;
      document.getElementById("rbac-cargo").value = "";
      document.getElementById("rbac-senha").value = "";
      document.getElementById("lbl-rbac-senha").textContent = "Palavra-passe Inicial *";
      document.getElementById("rbac-nivel").value = "gestor";
      document.getElementById("rbac-ilha").value = "";
      aoMudarNivelAcessoForm("gestor");
      document.getElementById("rbac-ativo").checked = true;
      document.getElementById("rbac-form-title").textContent = "➕ Novo Utilizador";
      document.getElementById("rbac-form-msg").textContent = "";
    }

    function abrirModalGestaoUtilizadores() {
      if (!perfilUtilizadorAtual || perfilUtilizadorAtual.nivel_acesso !== "admin") {
        alert("Acesso restrito ao Administrador Geral do Sistema.");
        return;
      }
      document.getElementById("modal-gestao-utilizadores").classList.remove("hidden");
      limparFormularioUtilizador();
      carregarListaUtilizadoresAdmin();
    }

    function fecharModalGestaoUtilizadores() {
      document.getElementById("modal-gestao-utilizadores").classList.add("hidden");
    }

    async function carregarListaUtilizadoresAdmin() {
      const tbody = document.getElementById("tbody-rbac-users");
      const countEl = document.getElementById("rbac-count-users");
      if (!tbody) return;
      tbody.innerHTML = `<tr><td colspan="6" style="padding:18px; text-align:center; color:var(--text-muted);">A sincronizar utilizadores...</td></tr>`;

      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/santiago_utilizadores?select=*&order=criado_em.asc`, {
          headers: HEADERS
        });
        if (!r.ok) throw new Error("Não foi possível carregar a lista de utilizadores.");
        const lista = await r.json();
        cacheUtilizadoresAdmin = lista;
        if (countEl) countEl.textContent = lista.length;

        const badgeNivel = (n) => {
          const map = {
            admin: `<span class="rbac-role-badge rbac-role-admin">👑 Administrador</span>`,
            direcao: `<span class="rbac-role-badge rbac-role-direcao">🏛️ Direção</span>`,
            gestor: `<span class="rbac-role-badge rbac-role-gestor">📊 Gestor</span>`,
            operador: `<span class="rbac-role-badge rbac-role-operador">🛠️ Operador</span>`,
            visualizador: `<span class="rbac-role-badge rbac-role-visualizador">👁️ Visualizador</span>`
          };
          return map[n] || n;
        };

        tbody.innerHTML = lista.map(u => {
          const dtLogin = u.ultimo_acesso ? new Date(u.ultimo_acesso).toLocaleString("pt-PT") : "Ainda sem login";
          const perms = [
            u.pode_ver_divida ? "💰 Dívida" : null,
            u.pode_ver_cf1 ? "⚖️ CF1/GIS" : null,
            u.pode_ver_story ? "📑 Story" : null,
            u.pode_exportar ? "⬇ CSV" : null
          ].filter(Boolean).join(" • ") || "Básico";

          const ehRoot = (u.email || "").toLowerCase() === "vitfonseca73@gmail.com";
          return `
            <tr style="border-bottom:1px solid var(--border-dim);">
              <td style="padding:9px 10px;">
                <div style="font-weight:700; color:var(--text-primary);">${u.nome}</div>
                <div style="font-family:var(--font-mono); font-size:11px; color:var(--accent-cyan);">${u.email}</div>
                <div style="font-size:10.5px; color:var(--text-muted);">${u.cargo || ""}</div>
              </td>
              <td style="padding:9px 10px;">${badgeNivel(u.nivel_acesso)}</td>
              <td style="padding:9px 10px; font-family:var(--font-mono); font-size:11.5px;">
                ${u.ilha_restrita ? `🏝️ ${u.ilha_restrita}` : `<span style="color:var(--text-secondary);">🌍 4 Ilhas</span>`}
              </td>
              <td style="padding:9px 10px; font-size:11px; color:var(--text-secondary);">${perms}</td>
              <td style="padding:9px 10px;">
                <div>${u.ativo ? `<span style="color:#34D399; font-weight:700;">● Ativo</span>` : `<span style="color:#F87171; font-weight:700;">● Suspenso</span>`}</div>
                <div style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono); margin-top:2px;">${dtLogin}</div>
              </td>
              <td style="padding:9px 10px; text-align:right; white-space:nowrap;">
                <button class="btn btn-sm" onclick="preencherEdicaoUtilizador('${u.id}')" title="Editar permissões ou redefinir senha">✏️ Editar</button>
                ${!ehRoot ? `
                  <button class="btn btn-sm" onclick="alternarEstadoUtilizador('${u.id}', ${!u.ativo})" title="${u.ativo ? 'Suspender acesso' : 'Reativar acesso'}">
                    ${u.ativo ? "⏸️" : "▶️"}
                  </button>
                  <button class="btn btn-sm" style="color:#F87171;" onclick="removerUtilizadorAdmin('${u.id}', '${u.email}')" title="Eliminar utilizador">🗑️</button>
                ` : `<span style="font-size:10px; color:var(--text-muted); font-family:var(--font-mono); padding:0 4px;">Admin Principal</span>`}
              </td>
            </tr>
          `;
        }).join("");
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" style="padding:18px; text-align:center; color:#F87171;">${e.message}</td></tr>`;
      }
    }

    function preencherEdicaoUtilizador(uid) {
      const u = cacheUtilizadoresAdmin.find(x => x.id === uid);
      if (!u) return;
      document.getElementById("rbac-user-id").value = u.id;
      document.getElementById("rbac-nome").value = u.nome || "";
      document.getElementById("rbac-email").value = u.email || "";
      document.getElementById("rbac-cargo").value = u.cargo || "";
      document.getElementById("rbac-senha").value = "";
      document.getElementById("lbl-rbac-senha").textContent = "Nova Palavra-passe (deixe vazio para manter)";
      document.getElementById("rbac-nivel").value = u.nivel_acesso || "operador";
      document.getElementById("rbac-ilha").value = u.ilha_restrita || "";
      document.getElementById("rbac-perm-divida").checked = !!u.pode_ver_divida;
      document.getElementById("rbac-perm-cf1").checked = !!u.pode_ver_cf1;
      document.getElementById("rbac-perm-story").checked = !!u.pode_ver_story;
      document.getElementById("rbac-perm-export").checked = !!u.pode_exportar;
      document.getElementById("rbac-ativo").checked = !!u.ativo;
      document.getElementById("rbac-form-title").textContent = `✏️ Editar: ${u.nome}`;
      document.getElementById("rbac-form-msg").textContent = "";
    }

    async function salvarUtilizadorAdmin(ev) {
      ev.preventDefault();
      const id = document.getElementById("rbac-user-id").value;
      const nome = document.getElementById("rbac-nome").value.trim();
      const email = document.getElementById("rbac-email").value.trim().toLowerCase();
      const cargo = document.getElementById("rbac-cargo").value.trim();
      const senha = document.getElementById("rbac-senha").value.trim();
      const nivel_acesso = document.getElementById("rbac-nivel").value;
      const ilha_restrita = document.getElementById("rbac-ilha").value || null;
      const pode_ver_divida = document.getElementById("rbac-perm-divida").checked;
      const pode_ver_cf1 = document.getElementById("rbac-perm-cf1").checked;
      const pode_ver_story = document.getElementById("rbac-perm-story").checked;
      const pode_exportar = document.getElementById("rbac-perm-export").checked;
      const ativo = document.getElementById("rbac-ativo").checked;
      const msgEl = document.getElementById("rbac-form-msg");
      const btn = document.getElementById("btn-rbac-save");

      if (!id && senha.length < 6) {
        msgEl.style.color = "#F87171";
        msgEl.textContent = "Defina uma palavra-passe inicial com pelo menos 6 caracteres.";
        return;
      }

      const payload = {
        nome,
        email,
        cargo,
        nivel_acesso,
        ilha_restrita,
        pode_ver_divida,
        pode_ver_cf1,
        pode_ver_story,
        pode_exportar,
        ativo,
        criado_por: perfilUtilizadorAtual?.email || "admin"
      };
      if (senha) payload.senha_definir = senha;

      btn.disabled = true;
      msgEl.style.color = "var(--accent-cyan)";
      msgEl.textContent = "A sincronizar com Supabase Auth...";

      try {
        const url = id
          ? `${SUPABASE_URL}/rest/v1/santiago_utilizadores?id=eq.${id}`
          : `${SUPABASE_URL}/rest/v1/santiago_utilizadores`;
        const method = id ? "PATCH" : "POST";

        const r = await fetch(url, {
          method,
          headers: { ...HEADERS, "Prefer": "return=representation" },
          body: JSON.stringify(payload)
        });
        if (!r.ok) {
          const errTxt = await r.text();
          throw new Error(errTxt || "Erro ao guardar utilizador.");
        }
        msgEl.style.color = "#34D399";
        msgEl.textContent = id ? "✔ Utilizador atualizado com sucesso!" : "✔ Novo utilizador criado e ativo!";
        await carregarListaUtilizadoresAdmin();
        if (!id) limparFormularioUtilizador();
      } catch (e) {
        msgEl.style.color = "#F87171";
        msgEl.textContent = "Erro: " + e.message;
      } finally {
        btn.disabled = false;
      }
    }

    async function alternarEstadoUtilizador(uid, novoAtivo) {
      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/santiago_utilizadores?id=eq.${uid}`, {
          method: "PATCH",
          headers: HEADERS,
          body: JSON.stringify({ ativo: novoAtivo })
        });
        if (!r.ok) throw new Error("Falha ao alterar estado.");
        carregarListaUtilizadoresAdmin();
      } catch (e) {
        alert(e.message);
      }
    }

    async function removerUtilizadorAdmin(uid, email) {
      if (email.toLowerCase() === "vitfonseca73@gmail.com") {
        alert("O Administrador Geral principal não pode ser removido.");
        return;
      }
      if (!confirm(`Tem a certeza que deseja eliminar o acesso de ${email}?`)) return;
      try {
        const r = await fetch(`${SUPABASE_URL}/rest/v1/santiago_utilizadores?id=eq.${uid}`, {
          method: "DELETE",
          headers: HEADERS
        });
        if (!r.ok) throw new Error("Não foi possível eliminar o utilizador.");
        carregarListaUtilizadoresAdmin();
      } catch (e) {
        alert(e.message);
      }
    }

    // Alteração da própria palavra-passe pelo utilizador autenticado
    function abrirModalMinhaSenha() {
      document.getElementById("minha-nova-senha").value = "";
      document.getElementById("minha-conf-senha").value = "";
      document.getElementById("msg-minha-senha").textContent = "";
      document.getElementById("modal-minha-senha").classList.remove("hidden");
    }

    function fecharModalMinhaSenha() {
      document.getElementById("modal-minha-senha").classList.add("hidden");
    }

    async function salvarMinhaNovaSenha(ev) {
      ev.preventDefault();
      const s1 = document.getElementById("minha-nova-senha").value;
      const s2 = document.getElementById("minha-conf-senha").value;
      const msg = document.getElementById("msg-minha-senha");
      const btn = document.getElementById("btn-save-minha-senha");

      if (s1 !== s2) {
        msg.style.color = "#F87171";
        msg.textContent = "As palavras-passe não coincidem.";
        return;
      }
      btn.disabled = true;
      msg.style.color = "var(--accent-cyan)";
      msg.textContent = "A atualizar palavra-passe...";
      try {
        const r = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
          method: "PUT",
          headers: HEADERS,
          body: JSON.stringify({ password: s1 })
        });
        if (!r.ok) throw new Error("Não foi possível atualizar a palavra-passe.");
        msg.style.color = "#34D399";
        msg.textContent = "✔ Palavra-passe alterada com sucesso!";
        setTimeout(() => fecharModalMinhaSenha(), 1200);
      } catch (e) {
        msg.style.color = "#F87171";
        msg.textContent = e.message;
      } finally {
        btn.disabled = false;
      }
    }

    window.addEventListener("DOMContentLoaded", () => {
      const savedTheme = localStorage.getItem('santiago_theme') || 'light';
      setTema(savedTheme);
      iniciarFluxoAutenticacao();
    });
  
