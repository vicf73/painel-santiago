    // =========================================================================
    // MOTOR 3D: TOPOGRAFIA INTERATIVA DE SANTIAGO & BALANÇO REAL DE PTs (SL7000)
    // =========================================================================
    let DADOS_PTS_3D = [];
    let BALANCO_TRIMS = {};
    let trimestreAtualPT = "2026-T3";
    let ptSelecionado3D = null;
    let scene3D, camera3D, renderer3D, controls3D, animId3D;
    let beacons3D = [];
    let autoRotacao3D = true;
    let iniciado3D = false;

    function geoParaTerreno3D(lat, lon) {
      // Mapeia coordenadas reais da Ilha de Santiago para o plano 3D (x: -24..24, z: -28..28)
      if (!lat || !lon || isNaN(lat) || isNaN(lon)) return { x: 0, z: 0 };
      const x = ((Number(lon) - (-23.60)) / 0.18) * 20;
      const z = ((15.10 - Number(lat)) / 0.22) * 26;
      return {
        x: Math.max(-22, Math.min(22, x)),
        z: Math.max(-26, Math.min(26, z)),
      };
    }

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
      if (!tri) {
        iniciarOuRedimensionar3D();
        return;
      }

      const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      setTxt("m2-kpi-pts", `${tri.pts_com_cobertura} / ${tri.pts_medidos}`);
      setTxt("m2-kpi-inj", `${Number(tri.injetada_mwh || 0).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MWh`);
      setTxt("m2-kpi-fat", `${Number(tri.faturada_mwh || 0).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MWh`);
      setTxt("m2-kpi-perda", `${Number(tri.perda_mwh || 0).toLocaleString("pt-PT", { maximumFractionDigits: 1 })} MWh (${tri.taxa_perda_pct}%)`);

      DADOS_PTS_3D = (tri.pts || [])
        .filter(p => p.status !== "sem_cobertura" && p.injetada_kwh > 0)
        .map(p => {
          const pos = geoParaTerreno3D(p.lat, p.lon);
          return {
            id: p.pt,
            nome: p.localidade || p.pt,
            concelho: p.localidade || "Santiago",
            contador: p.contador,
            x: pos.x,
            z: pos.z,
            injetada: Number(p.injetada_kwh) / 1000.0,
            faturada: Number(p.faturada_kwh) / 1000.0,
            perda: Number(p.perda_kwh) / 1000.0,
            taxa: Number(p.taxa_perda_pct),
            divida: Number(p.divida_ecv || 0),
            clientes: Number(p.qtd_clientes || 0),
            status: p.status,
          };
        });

      ptSelecionado3D = DADOS_PTS_3D[0] || null;
      iniciarOuRedimensionar3D();
      if (iniciado3D) criarBeaconsPTs();
      renderizarTabelaCompletaPTs(tri.pts || []);
    }

    function mudarTrimestreBalancoPT(trimCod) {
      carregarBalancoPTReal(trimCod);
    }

    function renderizarTabelaCompletaPTs(pts) {
      const tbody = document.getElementById("m2-tbody-pts");
      const tfoot = document.getElementById("m2-tfoot-pts");
      if (!tbody) return;

      let totCli = 0, totIpKwh = 0, totInj = 0, totFat = 0;
      tbody.innerHTML = pts.map(p => {
        const cor = p.status === "critico" ? "#F87171" : p.status === "alerta" ? "#FBBF24" : p.status === "normal" ? "#34D399" : "var(--text-muted)";
        const stLbl = p.status === "sem_cobertura" ? "S/ Cobertura CL_PT" : p.status.toUpperCase();
        const ipKwh = Number(p.fat_ip_kwh || 0);
        const ipTxt = p.contador_ip
          ? `<div style="font-family:var(--font-mono); font-size:10.5px; color:var(--text-secondary);">${p.contador_ip}</div><div style="font-family:var(--font-mono); font-weight:700; color:#FBBF24;">${Math.round(ipKwh).toLocaleString("pt-PT")} kWh</div>`
          : `<span style="color:var(--text-muted); opacity:0.45;">—</span>`;

        totCli += Number(p.qtd_clientes || 0);
        totIpKwh += ipKwh;
        if (p.status !== "sem_cobertura") {
          totInj += Number(p.injetada_kwh || 0);
          totFat += Number(p.faturada_kwh || 0);
        }

        return `
          <tr style="cursor:pointer;" onclick="selecionarPT3DPorId('${p.pt}')">
            <td style="font-family:var(--font-mono); font-weight:700; color:#60A5FA; white-space:nowrap;">${p.pt}</td>
            <td style="font-size:11px; color:var(--text-secondary);">${p.localidade || "--"}</td>
            <td style="text-align:right; font-family:var(--font-mono); font-weight:700;">${Number(p.qtd_clientes || 0).toLocaleString("pt-PT")}</td>
            <td style="text-align:right; white-space:nowrap;">${ipTxt}</td>
            <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap;">${(p.injetada_kwh / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right; font-family:var(--font-mono); white-space:nowrap;">${(p.faturada_kwh / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right; font-family:var(--font-mono); font-weight:800; color:${cor}; white-space:nowrap;">${p.taxa_perda_pct}%</td>
            <td style="text-align:center;"><span class="badge" style="color:${cor}; border:1px solid ${cor}; font-size:9.5px;">${stLbl}</span></td>
          </tr>
        `;
      }).join("");

      if (tfoot) {
        const taxaTot = totInj > 0 ? (((totInj - totFat) / totInj) * 100).toFixed(1) : "0.0";
        tfoot.innerHTML = `
          <tr style="border-top:2px solid var(--border-dim); background:var(--bg-panel-elevated); font-weight:800; font-family:var(--font-mono);">
            <td>TOTAL (${pts.length} PTs)</td>
            <td style="font-size:10.5px; color:var(--text-muted);">*Injetada/Faturada c/ cobertura</td>
            <td style="text-align:right;">${totCli.toLocaleString("pt-PT")}</td>
            <td style="text-align:right; color:#FBBF24;">${(totIpKwh / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right;">${(totInj / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right;">${(totFat / 1000).toFixed(1)} MWh</td>
            <td style="text-align:right; color:#F87171;">${taxaTot}%</td>
            <td></td>
          </tr>
        `;
      }
    }

    function iniciarOuRedimensionar3D() {
      const container = document.getElementById("canvas-3d-viewport");
      if (!container) return;

      if (!iniciado3D) {
        initThreeJS(container);
        iniciado3D = true;
      } else {
        if (renderer3D && camera3D) {
          const w = container.clientWidth;
          const h = container.clientHeight;
          camera3D.aspect = w / h;
          camera3D.updateProjectionMatrix();
          renderer3D.setSize(w, h);
        }
      }
      renderizarRankingPTs3D();
      atualizarCardPT(ptSelecionado3D);
    }

    function initThreeJS(container) {
      if (typeof THREE === 'undefined') {
        console.warn("Three.js ainda não carregado.");
        return;
      }

      const width = container.clientWidth || 800;
      const height = container.clientHeight || 540;

      scene3D = new THREE.Scene();
      scene3D.background = new THREE.Color(0x0a101d);
      scene3D.fog = new THREE.FogExp2(0x0a101d, 0.012);

      camera3D = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
      camera3D.position.set(0, 48, 65);

      renderer3D = new THREE.WebGLRenderer({ antialias: true });
      renderer3D.setSize(width, height);
      renderer3D.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer3D.shadowMap.enabled = true;
      container.appendChild(renderer3D.domElement);

      if (typeof THREE.OrbitControls !== 'undefined') {
        controls3D = new THREE.OrbitControls(camera3D, renderer3D.domElement);
        controls3D.enableDamping = true;
        controls3D.dampingFactor = 0.05;
        controls3D.maxPolarAngle = Math.PI / 2.1;
        controls3D.minDistance = 25;
        controls3D.maxDistance = 140;
      }

      // Iluminação
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
      scene3D.add(ambientLight);

      const dirLight = new THREE.DirectionalLight(0xffffff, 0.9);
      dirLight.position.set(30, 60, 40);
      dirLight.castShadow = true;
      scene3D.add(dirLight);

      const blueLight = new THREE.PointLight(0x4E79A7, 2.5, 120);
      blueLight.position.set(-20, 25, 10);
      scene3D.add(blueLight);

      // 1. Oceano Atlântico em torno de Santiago
      const oceanGeo = new THREE.PlaneGeometry(300, 300, 32, 32);
      const oceanMat = new THREE.MeshStandardMaterial({
        color: 0x061120,
        roughness: 0.3,
        metalness: 0.8,
        transparent: true,
        opacity: 0.92
      });
      const ocean = new THREE.Mesh(oceanGeo, oceanMat);
      ocean.rotation.x = -Math.PI / 2;
      ocean.position.y = -0.5;
      scene3D.add(ocean);

      // Grid sutil no oceano
      const grid = new THREE.GridHelper(200, 40, 0x1E293B, 0x131C2B);
      grid.position.y = -0.4;
      scene3D.add(grid);

      // 2. Malha Topográfica 3D da Ilha de Santiago
      criarTerrenoSantiago();

      // 3. Beacons 3D dos Postos de Transformação
      criarBeaconsPTs();

      // Raycaster para clique nos PTs
      const raycaster = new THREE.Raycaster();
      const mouse = new THREE.Vector2();

      renderer3D.domElement.addEventListener('click', (e) => {
        const rect = renderer3D.domElement.getBoundingClientRect();
        mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

        raycaster.setFromCamera(mouse, camera3D);
        const intersects = raycaster.intersectObjects(beacons3D, true);

        if (intersects.length > 0) {
          let obj = intersects[0].object;
          while (obj && !obj.userData.ptData && obj.parent) {
            obj = obj.parent;
          }
          if (obj && obj.userData.ptData) {
            selecionarPT3D(obj.userData.ptData);
          }
        }
      });

      // Loop de animação
      function animate() {
        animId3D = requestAnimationFrame(animate);
        if (controls3D) controls3D.update();

        if (autoRotacao3D && scene3D) {
          scene3D.rotation.y += 0.0018;
        }

        // Animação dos anéis pulsantes dos beacons
        const t = Date.now() * 0.003;
        beacons3D.forEach(b => {
          if (b.userData.ring) {
            const scale = 1 + Math.sin(t + b.userData.offset) * 0.22;
            b.userData.ring.scale.set(scale, scale, 1);
          }
        });

        renderer3D.render(scene3D, camera3D);
      }
      animate();

      window.addEventListener('resize', () => {
        if (!iniciado3D) return;
        const w = container.clientWidth;
        const h = container.clientHeight;
        camera3D.aspect = w / h;
        camera3D.updateProjectionMatrix();
        renderer3D.setSize(w, h);
      });
    }

    function criarTerrenoSantiago() {
      // Santiago: comprimento Norte-Sul (~55km), largura Leste-Oeste (~28km)
      const terrainGeo = new THREE.PlaneGeometry(36, 64, 48, 64);
      const pos = terrainGeo.attributes.position;

      for (let i = 0; i < pos.count; i++) {
        const x = pos.getX(i);
        const y = pos.getY(i); // no plano é Y, no 3D será Z

        // Forma de losango alongado de Santiago
        const ny = y / 32; // -1 (sul, praia) a +1 (norte, tarrafal)
        const nx = x / 18; // -1 a +1

        // Perímetro aproximado da costa de Santiago
        const maxLargura = (1 - Math.abs(ny * 0.85)) * (0.9 + 0.15 * Math.sin(ny * 4));
        const dentroIlha = Math.abs(nx) < maxLargura;

        if (dentroIlha) {
          // Relevo montanhoso: Pico d'Antónia (sul-centro) e Serra da Malagueta (norte-centro)
          const distAntonia = Math.hypot(x - 2, y - 5);
          const elevAntonia = Math.max(0, 8.5 - distAntonia * 0.9);

          const distMalagueta = Math.hypot(x - 1, y + 14);
          const elevMalagueta = Math.max(0, 7.2 - distMalagueta * 0.8);

          const planaltoGeral = Math.max(0, 2.5 - Math.hypot(x, y * 0.4) * 0.12);
          const rugosidade = (Math.sin(x * 0.8) * Math.cos(y * 0.8)) * 0.8;

          const zElev = Math.max(0.1, elevAntonia + elevMalagueta + planaltoGeral + rugosidade);
          pos.setZ(i, zElev);
        } else {
          pos.setZ(i, -1.5);
        }
      }
      terrainGeo.computeVertexNormals();

      const terrainMat = new THREE.MeshStandardMaterial({
        color: 0x1E293B,
        roughness: 0.85,
        metalness: 0.15,
        flatShading: true
      });

      const terrain = new THREE.Mesh(terrainGeo, terrainMat);
      terrain.rotation.x = -Math.PI / 2;
      terrain.position.y = 0;
      terrain.receiveShadow = true;
      scene3D.add(terrain);
    }

    function criarBeaconsPTs() {
      beacons3D = [];
      DADOS_PTS_3D.forEach((pt, idx) => {
        const group = new THREE.Group();
        group.userData = { ptData: pt, offset: idx * 1.5 };

        // Cor por status
        let corHex = 0x59A14F; // verde normal
        if (pt.status === "alerta") corHex = 0xF28E2B; // laranja
        if (pt.status === "critico") corHex = 0xE15759; // vermelho

        // Altura da coluna proporcional à perda (8 a 22 unidades)
        const alturaCol = 6 + (pt.taxa / 40) * 16;

        // Cilindro vertical
        const cylGeo = new THREE.CylinderGeometry(0.5, 0.7, alturaCol, 12);
        const cylMat = new THREE.MeshStandardMaterial({
          color: corHex,
          emissive: corHex,
          emissiveIntensity: 0.35,
          roughness: 0.3,
          metalness: 0.6
        });
        const cyl = new THREE.Mesh(cylGeo, cylMat);
        cyl.position.y = alturaCol / 2;
        group.add(cyl);

        // Esfera brilhante no topo
        const sphereGeo = new THREE.SphereGeometry(1.0, 16, 16);
        const sphereMat = new THREE.MeshBasicMaterial({ color: corHex });
        const sphere = new THREE.Mesh(sphereGeo, sphereMat);
        sphere.position.y = alturaCol + 0.8;
        group.add(sphere);

        // Anel na base
        const ringGeo = new THREE.RingGeometry(1.2, 2.0, 24);
        const ringMat = new THREE.MeshBasicMaterial({
          color: corHex,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.65
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.15;
        group.add(ring);
        group.userData.ring = ring;

        group.position.set(pt.x, 0, pt.z);
        scene3D.add(group);
        beacons3D.push(group);
      });
    }

    function selecionarPT3D(pt) {
      ptSelecionado3D = pt;
      atualizarCardPT(pt);

      // Destacar visualmente no 3D
      beacons3D.forEach(b => {
        if (b.userData.ptData.id === pt.id) {
          b.scale.set(1.25, 1.25, 1.25);
        } else {
          b.scale.set(1, 1, 1);
        }
      });
    }

    function atualizarCardPT(pt) {
      if (!pt) return;
      document.getElementById("pt-sel-codigo").textContent = `${pt.id} • ${pt.nome}`;
      document.getElementById("pt-sel-local").textContent = `Concelho de ${pt.concelho} • Cabo Verde`;
      document.getElementById("pt-sel-taxa").textContent = `${pt.taxa.toFixed(1)}%`;
      document.getElementById("pt-sel-injetada").textContent = `${pt.injetada.toFixed(1)} MWh`;
      document.getElementById("pt-sel-faturada").textContent = `${pt.faturada.toFixed(1)} MWh`;
      document.getElementById("pt-sel-perda").textContent = `${pt.perda.toFixed(1)} MWh`;

      const pctFat = (pt.faturada / pt.injetada) * 100;
      const pctPerda = (pt.perda / pt.injetada) * 100;
      document.getElementById("pt-bar-faturada").style.width = `${pctFat.toFixed(1)}%`;
      document.getElementById("pt-bar-perda").style.width = `${pctPerda.toFixed(1)}%`;

      const prejuizoEcv = Math.round(pt.perda * 35810); // PM Real 35,81 ECV/kWh
      document.getElementById("pt-sel-prejuizo").textContent = `~${prejuizoEcv.toLocaleString('pt-PT')} ECV/trim.`;
      document.getElementById("pt-sel-divida").textContent = `${pt.divida.toLocaleString('pt-PT')} ECV`;
      document.getElementById("pt-sel-clientes").textContent = `${pt.clientes} clientes ligados`;

      const badge = document.getElementById("pt-sel-badge");
      if (pt.status === "critico") {
        badge.className = "badge badge-danger";
        badge.textContent = "🚨 PERDA CRÍTICA CF1";
      } else if (pt.status === "alerta") {
        badge.className = "badge badge-warn";
        badge.textContent = "⚠️ ALERTA DE PERDA";
      } else {
        badge.className = "badge badge-ok";
        badge.textContent = "📗 BALANÇO NORMAL";
      }
    }

    function renderizarRankingPTs3D() {
      const container = document.getElementById("ranking-pts-3d-list");
      if (!container) return;

      const ordenados = [...DADOS_PTS_3D].sort((a, b) => b.taxa - a.taxa).slice(0, 5);
      container.innerHTML = ordenados.map((pt, i) => {
        const isAtivo = pt.id === ptSelecionado3D?.id ? "active" : "";
        const cor = pt.status === "critico" ? "#E15759" : (pt.status === "alerta" ? "#F28E2B" : "#59A14F");
        return `
          <div class="rank-item ${isAtivo}" onclick="selecionarPT3DPorId('${pt.id}')" style="border-left:3.5px solid ${cor};">
            <div class="rank-top">
              <span><b>#${i+1}</b> ${pt.id} — ${pt.nome}</span>
              <span style="color:${cor}; font-weight:700;">${pt.taxa.toFixed(1)}% perda</span>
            </div>
            <div class="rank-metrics">
              <span>${pt.concelho}</span>
              <span style="font-family:var(--font-mono);">${pt.divida.toLocaleString('pt-PT')} ECV</span>
            </div>
            <div class="rank-bar-track">
              <div class="rank-bar-fill" style="width:${pt.taxa}%; background:${cor};"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    function selecionarPT3DPorId(ptId) {
      const pt = DADOS_PTS_3D.find(p => p.id === ptId);
      if (pt) selecionarPT3D(pt);
    }

    function alternarAutoRotacao() {
      autoRotacao3D = !autoRotacao3D;
      const btn = document.getElementById("btn-auto-rot");
      if (btn) btn.textContent = autoRotacao3D ? "⏸ Pausar Giro" : "▶ Retomar Giro";
    }

    function resetarCamera3D() {
      if (camera3D) {
        camera3D.position.set(0, 48, 65);
        if (controls3D) {
          controls3D.target.set(0, 0, 0);
          controls3D.update();
        }
      }
      if (scene3D) {
        scene3D.rotation.y = 0;
      }
    }

    function filtrarPTNaTriagem() {
      if (!ptSelecionado3D) return;
      selecionarModulo('mod1');
      const inputBusca = document.getElementById("f-busca");
      const tipoBusca = document.getElementById("f-tipo-busca");
      if (inputBusca && tipoBusca) {
        tipoBusca.value = "pt";
        inputBusca.value = ptSelecionado3D.id;
        aplicarFiltros(1);
      }
    }

    // =========================================================================
    // MICROINTERAÇÃO 3D TILT NOS CARDS (EFEITO FÍSICO TÁTIL)
    // =========================================================================
    function ativarMicrointeracaoTilt3D() {
      const cards = document.querySelectorAll('.kpi-card, .pnt-pattern-card, .action-card, .pt-card-balance');
      cards.forEach(card => {
        card.addEventListener('mousemove', (e) => {
          const rect = card.getBoundingClientRect();
          const x = e.clientX - rect.left;
          const y = e.clientY - rect.top;
          const cx = rect.width / 2;
          const cy = rect.height / 2;
          const rotX = ((y - cy) / cy) * -5; // max 5 graus
          const rotY = ((x - cx) / cx) * 5;
          card.style.transform = `perspective(700px) rotateX(${rotX.toFixed(2)}deg) rotateY(${rotY.toFixed(2)}deg) translateY(-2px)`;
        });
        card.addEventListener('mouseleave', () => {
          card.style.transform = '';
        });
      });
    }

    // Chamar inicialização do Tilt quando a página carregar
    window.addEventListener("DOMContentLoaded", () => {
      setTimeout(ativarMicrointeracaoTilt3D, 500);
    });


