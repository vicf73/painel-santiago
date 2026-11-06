    // =========================================================================
    // MOTOR 3D: TOPOGRAFIA INTERATIVA DE SANTIAGO & POSTOS DE TRANSFORMAÇÃO (PTs)
    // =========================================================================
    const DADOS_PTS_3D = [
      { id: "PT-015", nome: "Fazenda / Sucupira", concelho: "Praia", x: 12, z: 22, injetada: 142.5, faturada: 88.1, perda: 54.4, taxa: 38.2, divida: 34218450, clientes: 418, status: "critico" },
      { id: "PT-042", nome: "Palmarejo Universitário", concelho: "Praia", x: 10, z: 24, injetada: 168.0, faturada: 120.1, perda: 47.9, taxa: 28.5, divida: 28410200, clientes: 520, status: "alerta" },
      { id: "PT-088", nome: "Achada Santo António Sul", concelho: "Praia", x: 13, z: 25, injetada: 195.4, faturada: 154.3, perda: 41.1, taxa: 21.0, divida: 22140800, clientes: 630, status: "alerta" },
      { id: "PT-112", nome: "Platô Histórico / Centro", concelho: "Praia", x: 14, z: 23, injetada: 110.2, faturada: 97.6, perda: 12.6, taxa: 11.4, divida: 14820100, clientes: 310, status: "normal" },
      { id: "PT-204", nome: "Assomada Centro Comercial", concelho: "Santa Catarina", x: 1, z: 2, injetada: 124.0, faturada: 84.7, perda: 39.3, taxa: 31.7, divida: 19640000, clientes: 380, status: "critico" },
      { id: "PT-215", nome: "Rincão Costeiro", concelho: "Santa Catarina", x: -10, z: 4, injetada: 48.0, faturada: 36.4, perda: 11.6, taxa: 24.1, divida: 8920000, clientes: 140, status: "alerta" },
      { id: "PT-310", nome: "Pedra Badejo Orla", concelho: "Santa Cruz", x: 14, z: 5, injetada: 86.5, faturada: 62.4, perda: 24.1, taxa: 27.8, divida: 16540300, clientes: 260, status: "alerta" },
      { id: "PT-401", nome: "Tarrafal Baía / Ponta", concelho: "Tarrafal", x: -8, z: -26, injetada: 72.0, faturada: 61.8, perda: 10.2, taxa: 14.2, divida: 11210000, clientes: 210, status: "normal" },
      { id: "PT-502", nome: "São Domingos Vale", concelho: "São Domingos", x: 8, z: 14, injetada: 65.0, faturada: 45.9, perda: 19.1, taxa: 29.3, divida: 13740000, clientes: 190, status: "alerta" },
      { id: "PT-601", nome: "Calheta São Miguel", concelho: "São Miguel", x: 6, z: -12, injetada: 54.0, faturada: 43.5, perda: 10.5, taxa: 19.5, divida: 7850000, clientes: 165, status: "alerta" }
    ];

    let ptSelecionado3D = DADOS_PTS_3D[0];
    let scene3D, camera3D, renderer3D, controls3D, animId3D;
    let beacons3D = [];
    let autoRotacao3D = true;
    let iniciado3D = false;

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

      const prejuizoEcv = Math.round(pt.perda * 26000); // ~26 ECV/kWh
      document.getElementById("pt-sel-prejuizo").textContent = `~${prejuizoEcv.toLocaleString('pt-PT')} ECV/mês`;
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


