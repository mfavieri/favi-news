/**
 * Lógica do Frontend Mobile/PWA FaviNews ("Em 15 minutos tudo pode mudar !!").
 * 100% passivo e Sem Login: consome o `catalogo_3dias.json` e renderiza os
 * arquivos pré-formatados `_R_` (Resenha) e `_N_` (Notícia Completa).
 */

const estado = {
  categoriasConfig: [],
  itensCatalogo: [],
  atualizadoEm: "",
  categoriaAtiva: "Todas",
  termoBusca: "",
  janelaDia: "todos", // 'todos' | 'hoje' | 'ontem'
  itemAberto: null,
  modoLeitor: "R" // 'R' (Resenha) | 'N' (Notícia Completa)
};

// Elementos da DOM
const elSplash = document.getElementById("splash-screen");
const elSplashProgress = document.getElementById("splash-progress");
const elSplashStatus = document.getElementById("splash-status");
const elLabelAtualizado = document.getElementById("label-atualizado");
const elCategoriasNav = document.getElementById("categorias-nav");
const elListaNoticias = document.getElementById("lista-noticias");
const elContador = document.getElementById("contador-resultados");
const elInputBusca = document.getElementById("input-busca");
const elBtnLimparBusca = document.getElementById("btn-limpar-busca");
const elSelectDia = document.getElementById("select-janela-dia");
const elBtnCrawler = document.getElementById("btn-forcar-crawler");
const elBtnReplaySplash = document.getElementById("btn-replay-splash");

// Modal Leitor
const elModalLeitor = document.getElementById("modal-leitor");
const elBackdrop = document.getElementById("leitor-backdrop");
const elBtnFecharLeitor = document.getElementById("btn-fechar-leitor");
const elTabResenha = document.getElementById("tab-resenha");
const elTabNoticia = document.getElementById("tab-noticia");
const elNomeArquivo = document.getElementById("leitor-nome-arquivo");
const elIframeLeitor = document.getElementById("iframe-leitor");

/**
 * Controla a exibição da Splash Screen ("Em 15 minutos tudo pode mudar !!")
 */
function exibirSplashScreen(duracaoMinimaMs = 1550) {
  elSplash.classList.remove("fade-out");
  elSplashProgress.style.width = "20%";
  elSplashStatus.textContent = "Sintonizando manchetes dos últimos 3 dias...";

  setTimeout(() => {
    elSplashProgress.style.width = "65%";
    elSplashStatus.textContent = "Carregando resenhas (_R_) e notícias (_N_)...";
  }, Math.floor(duracaoMinimaMs * 0.4));

  setTimeout(() => {
    elSplashProgress.style.width = "100%";
    elSplashStatus.textContent = "Pronto! Em 15 minutos tudo pode mudar !!";
  }, Math.floor(duracaoMinimaMs * 0.8));

  return new Promise((resolve) => {
    setTimeout(() => {
      elSplash.classList.add("fade-out");
      resolve();
    }, duracaoMinimaMs);
  });
}

/**
 * Carrega as categorias configuráveis e o catálogo de 3 dias
 */
async function carregarDadosBase() {
  try {
    const [respCfg, respCat] = await Promise.all([
      fetch(`config/fontes.config.json?t=${Date.now()}`),
      fetch(`base_conhecimento/catalogo_3dias.json?t=${Date.now()}`)
    ]);

    if (respCfg.ok) {
      const cfg = await respCfg.json();
      estado.categoriasConfig = cfg.categorias || [];
    }

    if (respCat.ok) {
      const cat = await respCat.json();
      estado.itensCatalogo = cat.itens || [];
      estado.atualizadoEm = cat.atualizado_em || "Agora";
      elLabelAtualizado.textContent = `Atualizado: ${estado.atualizadoEm}`;
    } else {
      elLabelAtualizado.textContent = "Base aguardando 1º giro";
    }
  } catch (erro) {
    console.warn("Aviso ao carregar dados da base:", erro);
    elLabelAtualizado.textContent = "Modo Offline Ativo";
  }

  renderizarAbasCategorias();
  renderizarListaNoticias();
}

/**
 * Renderiza as abas horizontais de categorias configuráveis
 */
function renderizarAbasCategorias() {
  const contagens = { Todas: estado.itensCatalogo.length };
  for (const item of estado.itensCatalogo) {
    const c = item.categoria_id;
    contagens[c] = (contagens[c] || 0) + 1;
  }

  const abas = [
    { id: "Todas", rotulo: "Todas", icone: "🔥" },
    ...estado.categoriasConfig.map((c) => ({
      id: c.id,
      rotulo: c.rotulo,
      icone: c.icone || "📰"
    }))
  ];

  elCategoriasNav.innerHTML = abas
    .map((aba) => {
      const qtd = contagens[aba.id] || 0;
      const classeAtiva = estado.categoriaAtiva === aba.id ? "active" : "";
      return `
        <button class="cat-chip ${classeAtiva}" data-cat="${aba.id}">
          <span>${aba.icone}</span>
          <span>${aba.rotulo}</span>
          <small style="opacity:0.75">(${qtd})</small>
        </button>
      `;
    })
    .join("");

  elCategoriasNav.querySelectorAll(".cat-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      estado.categoriaAtiva = btn.getAttribute("data-cat");
      renderizarAbasCategorias();
      renderizarListaNoticias();
    });
  });
}

/**
 * Verifica se o carimbo YYYYMMDD-HHMMSS pertence ao filtro de dia selecionado
 */
function passaFiltroDia(carimboTs) {
  if (estado.janelaDia === "todos" || !carimboTs) return true;
  const prefixoData = carimboTs.slice(0, 8); // YYYYMMDD
  const hoje = new Date();
  const fmtData = (d) =>
    `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;

  if (estado.janelaDia === "hoje") {
    return prefixoData === fmtData(hoje);
  }
  if (estado.janelaDia === "ontem") {
    const ontem = new Date(hoje);
    ontem.setDate(hoje.getDate() - 1);
    return prefixoData === fmtData(ontem);
  }
  return true;
}

/**
 * Filtra e renderiza os cards de notícias na tela inicial
 */
function renderizarListaNoticias() {
  const termo = estado.termoBusca.trim().toLowerCase();

  const filtradas = estado.itensCatalogo.filter((item) => {
    if (estado.categoriaAtiva !== "Todas" && item.categoria_id !== estado.categoriaAtiva) {
      return false;
    }
    if (!passaFiltroDia(item.carimbo_ts)) {
      return false;
    }
    if (termo) {
      const alvo = [
        item.titulo,
        item.resenha_texto,
        item.fonte,
        item.categoria_rotulo,
        item.subtopico,
        ...(item.pontos_chave || [])
      ]
        .join(" ")
        .toLowerCase();
      return alvo.includes(termo);
    }
    return true;
  });

  elContador.textContent = `${filtradas.length} manchete(s) na janela de 3 dias`;

  if (filtradas.length === 0) {
    elListaNoticias.innerHTML = `
      <div class="empty-state">
        <p style="font-size:2rem;margin-bottom:8px;">📡</p>
        <h3>Nenhuma notícia encontrada para este filtro</h3>
        <p style="margin-top:6px;">Tente mudar a categoria, limpar a busca ou clique no botão 🔄 no topo para atualizar.</p>
      </div>
    `;
    return;
  }

  elListaNoticias.innerHTML = filtradas
    .map(
      (item) => `
      <article class="news-card" data-ts="${item.carimbo_ts}">
        <div class="card-thumb-wrap" data-acao="abrir-r" data-ts="${item.carimbo_ts}">
          <img class="card-thumb" src="${item.thumbnail_base64}" alt="${escaparHtml(item.titulo)}" loading="lazy">
          <span class="card-cat-badge">${item.icone || "📰"} ${escaparHtml(item.categoria_rotulo)}</span>
          <span class="card-time-badge">🕒 ${escaparHtml(item.data_fato_formatada)}</span>
        </div>

        <div class="card-body">
          <div class="card-source">📍 ${escaparHtml(item.fonte)}</div>
          <h2 class="card-title" data-acao="abrir-r" data-ts="${item.carimbo_ts}">
            ${escaparHtml(item.titulo)}
          </h2>
          <p class="card-resenha">${escaparHtml(item.resenha_texto)}</p>

          <div class="card-file-id" title="Par de arquivos HTML na Base de Conhecimento">
            📁 ${escaparHtml(item.arquivo_r)}
          </div>

          <div class="card-actions">
            <button class="btn-card btn-card-r" data-acao="abrir-r" data-ts="${item.carimbo_ts}">
              ⚡ Resenha (_R_)
            </button>
            <button class="btn-card btn-card-n" data-acao="abrir-n" data-ts="${item.carimbo_ts}">
              📰 Notícia (_N_)
            </button>
          </div>
        </div>
      </article>
    `
    )
    .join("");

  // Eventos de abertura rápida dos arquivos _R_ e _N_
  elListaNoticias.querySelectorAll("[data-acao]").forEach((el) => {
    el.addEventListener("click", () => {
      const ts = el.getAttribute("data-ts");
      const acao = el.getAttribute("data-acao");
      const item = estado.itensCatalogo.find((i) => i.carimbo_ts === ts);
      if (item) {
        abrirLeitorModal(item, acao === "abrir-n" ? "N" : "R");
      }
    });
  });
}

/**
 * Abre o Modal Leitor carregando o arquivo HTML autocontido (_R_ ou _N_)
 */
function abrirLeitorModal(item, modo = "R") {
  estado.itemAberto = item;
  estado.modoLeitor = modo;

  const nomeArq = modo === "N" ? item.arquivo_n : item.arquivo_r;
  elNomeArquivo.textContent = nomeArq;

  elTabResenha.classList.toggle("active", modo === "R");
  elTabNoticia.classList.toggle("active", modo === "N");

  elIframeLeitor.src = `base_conhecimento/${nomeArq}`;
  elModalLeitor.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function fecharLeitorModal() {
  elModalLeitor.classList.add("hidden");
  elIframeLeitor.src = "about:blank";
  document.body.style.overflow = "";
}

// Intercepta clique nos botões internos do HTML (_R_ <-> _N_) dentro do iframe
elIframeLeitor.addEventListener("load", () => {
  try {
    const doc = elIframeLeitor.contentDocument || elIframeLeitor.contentWindow.document;
    if (!doc) return;
    doc.querySelectorAll("[data-abrir-par]").forEach((link) => {
      link.addEventListener("click", (ev) => {
        ev.preventDefault();
        if (!estado.itemAberto) return;
        const novoModo = estado.modoLeitor === "R" ? "N" : "R";
        abrirLeitorModal(estado.itemAberto, novoModo);
      });
    });
  } catch (_) {
    // Ignora se cross-origin
  }
});

function escaparHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// =========================================================================
// EVENTOS GLOBAIS E INICIALIZAÇÃO
// =========================================================================
elTabResenha.addEventListener("click", () => {
  if (estado.itemAberto) abrirLeitorModal(estado.itemAberto, "R");
});

elTabNoticia.addEventListener("click", () => {
  if (estado.itemAberto) abrirLeitorModal(estado.itemAberto, "N");
});

elBtnFecharLeitor.addEventListener("click", fecharLeitorModal);
elBackdrop.addEventListener("click", fecharLeitorModal);

elInputBusca.addEventListener("input", () => {
  estado.termoBusca = elInputBusca.value;
  elBtnLimparBusca.classList.toggle("hidden", !estado.termoBusca);
  renderizarListaNoticias();
});

elBtnLimparBusca.addEventListener("click", () => {
  elInputBusca.value = "";
  estado.termoBusca = "";
  elBtnLimparBusca.classList.add("hidden");
  renderizarListaNoticias();
});

elSelectDia.addEventListener("change", () => {
  estado.janelaDia = elSelectDia.value;
  renderizarListaNoticias();
});

elBtnReplaySplash.addEventListener("click", () => {
  exibirSplashScreen(1800);
});

elBtnCrawler.addEventListener("click", async () => {
  elBtnCrawler.classList.add("girando");
  elLabelAtualizado.textContent = "Coletando notícias...";
  try {
    // Se estiver rodando com server.py local, dispara o crawler ao vivo; se estático, recarrega o catálogo
    const resp = await fetch("/api/atualizar-agora", { method: "POST" }).catch(() => null);
    if (resp && resp.ok) {
      await carregarDadosBase();
    } else {
      await carregarDadosBase();
    }
  } finally {
    elBtnCrawler.classList.remove("girando");
  }
});

// Registra Service Worker para PWA instalável no celular
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  });
}

// Inicialização com Splash Screen "Em 15 minutos tudo pode mudar !!"
window.addEventListener("DOMContentLoaded", () => {
  exibirSplashScreen(1650);
  carregarDadosBase();

  // Atualiza automaticamente a tela a cada 60 segundos buscando novo catálogo
  setInterval(() => {
    carregarDadosBase();
  }, 60 * 1000);
});

