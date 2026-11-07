/**
 * Lógica do Frontend Mobile/PWA FaviNews ("Em 15 minutos tudo pode mudar !!").
 * 100% passivo e Sem Login: consome o `catalogo_3dias.json` e renderiza os
 * arquivos pré-formatados `_R_` (Resenha) e `_N_` (Notícia Completa).
 */

const estado = {
  categoriasConfig: [],
  itensCatalogo: [],
  atualizadoEm: "",
  ultimoHashItens: "",
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
const elTextoStatusCiclo = document.getElementById("texto-status-ciclo");
const elBannerDefesaCivil = document.getElementById("banner-alerta-defesa-civil");
const elTextoDefesaCivil = document.getElementById("texto-alerta-defesa-civil");
const elCategoriasNav = document.getElementById("categorias-nav");
const elListaNoticias = document.getElementById("lista-noticias");
const elContador = document.getElementById("contador-resultados");
const elInputBusca = document.getElementById("input-busca");
const elBtnLimparBusca = document.getElementById("btn-limpar-busca");
const elSelectDia = document.getElementById("select-janela-dia");
const elBtnCrawler = document.getElementById("btn-forcar-crawler");
const elBtnShareApp = document.getElementById("btn-compartilhar-app");
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
async function buscarJsonMaisRecente(caminhoRelativo) {
  const ts = Date.now();
  const ehGithubPages = window.location.hostname.includes("github.io");
  const promessaLocal = fetch(`${caminhoRelativo}?t=${ts}`, { cache: "no-store" }).then((r) =>
    r.ok ? r.json() : null
  ).catch(() => null);

  if (!ehGithubPages) {
    return promessaLocal;
  }

  // No GitHub Pages, consulta também o arquivo direto na branch main para eliminar o delay de build do Pages
  const urlRaw = `https://raw.githubusercontent.com/mfavieri/favi-news/main/${caminhoRelativo}?t=${ts}`;
  const promessaRaw = fetch(urlRaw, { cache: "no-store" }).then((r) =>
    r.ok ? r.json() : null
  ).catch(() => null);

  const [dadosPages, dadosRaw] = await Promise.all([promessaLocal, promessaRaw]);
  if (dadosRaw && dadosPages) {
    const isoRaw = dadosRaw.atualizado_iso || "";
    const isoPages = dadosPages.atualizado_iso || "";
    return isoRaw >= isoPages ? dadosRaw : dadosPages;
  }
  return dadosRaw || dadosPages;
}

async function carregarDadosBase(apenasStatus = false) {
  try {
    const promessas = [buscarJsonMaisRecente("base_conhecimento/catalogo_3dias.json")];
    if (!apenasStatus || estado.categoriasConfig.length === 0) {
      promessas.push(buscarJsonMaisRecente("config/fontes.config.json"));
    }

    const [cat, cfg] = await Promise.all(promessas);

    if (cfg && cfg.categorias) {
      estado.categoriasConfig = cfg.categorias || [];
    }

    if (cat && cat.itens) {
      const sc = cat.status_ciclo || {};

      // Atualiza o relógio do topo e o banner de andamento vindo do JSON
      if (sc.estado === "em_andamento") {
        elLabelAtualizado.textContent = `⏳ Varrendo (${sc.progresso_pct || 0}%)`;
        elBtnCrawler.classList.add("girando");
      } else if (sc.hora_curta && sc.proximo_giro) {
        elLabelAtualizado.textContent = `Giro: ${sc.hora_curta} (Próx: ${sc.proximo_giro})`;
        elBtnCrawler.classList.remove("girando");
      } else {
        elLabelAtualizado.textContent = `Atualizado: ${cat.atualizado_em || "Agora"}`;
        elBtnCrawler.classList.remove("girando");
      }

      if (elTextoStatusCiclo) {
        elTextoStatusCiclo.textContent =
          sc.mensagem ||
          `Última verificação em ${cat.atualizado_em} • ${(cat.itens || []).length} páginas ativas na base`;
      }

      // Verifica se já passou o horário do próximo giro de 15 min (quando no servidor local)
      if (cat.proximo_giro_iso && sc.estado !== "em_andamento") {
        const dtProx = new Date(cat.proximo_giro_iso).getTime();
        if (!isNaN(dtProx) && Date.now() > dtProx + 15000) {
          fetch("/api/atualizar-agora", { method: "POST" }).catch(() => null);
        }
      }

      const novoHash = `${cat.atualizado_em}_${(cat.itens || []).length}`;
      if (!apenasStatus || novoHash !== estado.ultimoHashItens) {
        estado.itensCatalogo = cat.itens || [];
        estado.atualizadoEm = cat.atualizado_em || "Agora";
        estado.ultimoHashItens = novoHash;

        // Exibe Banner Vermelho de Alerta da Defesa Civil / INMET se houver alerta ativo [A] em Niterói
        const itemAlerta = estado.itensCatalogo.find((it) => it.alerta_defesa_civil);
        if (elBannerDefesaCivil && elTextoDefesaCivil) {
          if (itemAlerta && itemAlerta.alerta_defesa_civil) {
            elTextoDefesaCivil.textContent = itemAlerta.alerta_defesa_civil;
            elBannerDefesaCivil.classList.remove("hidden");
            elBannerDefesaCivil.onclick = () =>
              abrirLeitorModal(itemAlerta, itemAlerta.arquivo_a ? "A" : "R");
          } else {
            elBannerDefesaCivil.classList.add("hidden");
          }
        }

        renderizarAbasCategorias();
        renderizarListaNoticias();
        // Atualiza em tempo real o Clima de Niterói e o Banner da Defesa Civil direto no navegador/celular
        atualizarClimaEDefesaCivilAoVivoNoCelular();
      }
      return;
    } else {
      elLabelAtualizado.textContent = "Base aguardando 1º giro";
    }
  } catch (erro) {
    console.warn("Aviso ao carregar dados da base:", erro);
    elLabelAtualizado.textContent = "Modo Offline Ativo";
  }

  if (!apenasStatus) {
    renderizarAbasCategorias();
    renderizarListaNoticias();
  }
}

const MAPA_WMO_MOBILE = {
  0: ["☀️", "Sol e Céu Limpo"],
  1: ["🌤️", "Sol com Poucas Nuvens"],
  2: ["⛅", "Sol entre Nuvens"],
  3: ["☁️", "Céu Encoberto"],
  45: ["🌫️", "Nevoeiro"],
  48: ["🌫️", "Nevoeiro Úmido"],
  51: ["🌦️", "Garoa Leve"],
  53: ["🌦️", "Chuvisco Moderado"],
  55: ["🌧️", "Chuvisco Intenso"],
  61: ["🌧️", "Chuva Fraca"],
  63: ["🌧️", "Chuva Moderada"],
  65: ["⛈️", "Chuva Forte"],
  80: ["🌦️", "Pancadas de Chuva Isoladas"],
  81: ["🌧️", "Pancadas de Chuva"],
  82: ["⛈️", "Temporal / Chuva Intensa"],
  95: ["⛈️", "Tempestade com Raios"]
};

/**
 * Consulta direto do celular a estação de Niterói (Open-Meteo) e os avisos do INMET
 * para atualizar temperatura, precipitação (mm) e Banner da Defesa Civil em tempo real,
 * mesmo quando o PC estiver desligado.
 */
async function atualizarClimaEDefesaCivilAoVivoNoCelular() {
  try {
    const urlOm =
      "https://api.open-meteo.com/v1/forecast?latitude=-22.8833&longitude=-43.1036&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=America%2FSao_Paulo&forecast_days=1";
    const respOm = await fetch(urlOm, { cache: "no-store" });
    if (!respOm.ok) return;
    const dadosOm = await respOm.json();
    const atual = dadosOm.current || {};
    const diario = dadosOm.daily || {};

    const temp = Number(atual.temperature_2m ?? 26);
    const sens = Number(atual.apparent_temperature ?? temp);
    const umid = Number(atual.relative_humidity_2m ?? 80);
    const precip = Number(atual.precipitation ?? 0);
    const vento = Number(atual.wind_speed_10m ?? 6);
    const wcode = Number(atual.weather_code ?? 3);
    const [icone, txtBase] = MAPA_WMO_MOBILE[wcode] || ["⛅", "Tempo Variável"];

    const estacaoComChuvaOuVentoForte = precip >= 0.3 || wcode >= 51 || vento >= 35;
    const condTexto = !estacaoComChuvaOuVentoForte && precip === 0 && wcode <= 3 ? `${txtBase} • Sem Chuva (0 mm)` : txtBase;
    const tMin = Number((diario.temperature_2m_min || [22])[0]);
    const tMax = Number((diario.temperature_2m_max || [32])[0]);

    // Atualiza o item de Clima Niterói na memória do celular
    const itemNit = estado.itensCatalogo.find(
      (it) => it.categoria_id === "Clima" && it.subtopico === "Niteroi"
    );
    if (itemNit) {
      const agora = new Date();
      const hhmm = `${String(agora.getHours()).padStart(2, "0")}h${String(agora.getMinutes()).padStart(2, "0")}`;
      const ddmm = `${String(agora.getDate()).padStart(2, "0")}/${String(agora.getMonth() + 1).padStart(2, "0")}/${agora.getFullYear()}`;
      itemNit.data_fato_formatada = `${ddmm} às ${hhmm}`;

      if (!estacaoComChuvaOuVentoForte) {
        itemNit.alerta_defesa_civil = "";
        itemNit.titulo = `Niterói - RJ Agora: ${Math.round(temp)}°C (${condTexto}) • Vento ${Math.round(vento)} km/h | Máx ${Math.round(tMax)}°C / Mín ${Math.round(tMin)}°C`;
        if (elBannerDefesaCivil) {
          elBannerDefesaCivil.classList.add("hidden");
        }
      }
      renderizarListaNoticias();
    }
  } catch (_) {
    // Em modo offline mantém os dados do JSON local
  }
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
    .map((item) => {
      const ehAlertaPuro = item.tipo_artefato === "A" && item.arquivo_a === item.arquivo_r;
      const temAlertaAssociado = Boolean(item.arquivo_a);
      const arqExibido = item.arquivo_a || item.arquivo_r;
      const botoesHtml = ehAlertaPuro
        ? `
            <button class="btn-card btn-card-a" style="grid-column: 1 / -1; background: rgba(239,68,68,0.22); border-color: rgba(239,68,68,0.6); color: #fca5a5;" data-acao="abrir-a" data-ts="${item.carimbo_ts}">
              🚨 Alerta Ativo (_A_) • Válido neste Ciclo
            </button>
          `
        : `
            <button class="btn-card btn-card-r" data-acao="abrir-r" data-ts="${item.carimbo_ts}">
              ⚡ Resenha (_R_)
            </button>
            <button class="btn-card btn-card-n" data-acao="abrir-n" data-ts="${item.carimbo_ts}">
              📰 Notícia (_N_)
            </button>
            ${
              temAlertaAssociado
                ? `<button class="btn-card btn-card-a" style="grid-column: 1 / -1; margin-top: 6px; background: rgba(239,68,68,0.22); border-color: rgba(239,68,68,0.6); color: #fca5a5;" data-acao="abrir-a" data-ts="${item.carimbo_ts}">
                    🚨 Alerta (_A_)
                   </button>`
                : ""
            }
          `;

      return `
      <article class="news-card" data-ts="${item.carimbo_ts}">
        <div class="card-thumb-wrap" data-acao="${ehAlertaPuro ? "abrir-a" : "abrir-r"}" data-ts="${item.carimbo_ts}">
          <img class="card-thumb" src="${item.thumbnail_base64}" alt="${escaparHtml(item.titulo)}" loading="lazy">
          <span class="card-cat-badge">${item.icone || "📰"} ${escaparHtml(item.categoria_rotulo)}</span>
          <span class="card-time-badge">🕒 ${escaparHtml(item.data_fato_formatada)}</span>
        </div>

        <div class="card-body">
          <div class="card-source">📍 ${escaparHtml(item.fonte)}</div>
          <h2 class="card-title" data-acao="${ehAlertaPuro ? "abrir-a" : "abrir-r"}" data-ts="${item.carimbo_ts}">
            ${escaparHtml(item.titulo)}
          </h2>
          <p class="card-resenha">${escaparHtml(item.resenha_texto)}</p>

          <div class="card-file-id" title="Artefato HTML na Base de Conhecimento ([R] Resenha, [N] Notícia, [A] Alerta)">
            📁 ${escaparHtml(arqExibido)}
          </div>

          <div class="card-actions">
            ${botoesHtml}
          </div>
        </div>
      </article>
    `;
    })
    .join("");

  // Eventos de abertura rápida dos arquivos _R_, _N_ e _A_
  elListaNoticias.querySelectorAll("[data-acao]").forEach((el) => {
    el.addEventListener("click", () => {
      const ts = el.getAttribute("data-ts");
      const acao = el.getAttribute("data-acao");
      const item = estado.itensCatalogo.find((i) => i.carimbo_ts === ts);
      if (item) {
        const modo = acao === "abrir-n" ? "N" : acao === "abrir-a" ? "A" : "R";
        abrirLeitorModal(item, modo);
      }
    });
  });
}

/**
 * Abre o Modal Leitor carregando o arquivo HTML autocontido (_R_, _N_ ou _A_)
 */
function abrirLeitorModal(item, modo = "R") {
  estado.itemAberto = item;
  estado.modoLeitor = modo;

  const nomeArq =
    modo === "A" && item.arquivo_a
      ? item.arquivo_a
      : modo === "N"
        ? item.arquivo_n
        : item.arquivo_r;
  elNomeArquivo.textContent = nomeArq;

  elTabResenha.classList.toggle("active", modo === "R" || modo === "A");
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

function mostrarToast(mensagem) {
  const toast = document.createElement("div");
  toast.className = "toast-share";
  toast.textContent = mensagem;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 350);
  }, 2600);
}

if (elBtnShareApp) {
  elBtnShareApp.addEventListener("click", async () => {
    const urlOficial = "https://mfavieri.github.io/favi-news/";
    const dadosShare = {
      title: "FaviNews — Em 15 minutos tudo pode mudar !!",
      text: "🎙️ Instale o FaviNews ('Em 15 minutos tudo pode mudar !!') — manchetes e resenhas em tempo real, direto no celular e sem login:",
      url: urlOficial
    };

    if (navigator.share) {
      try {
        await navigator.share(dadosShare);
        return;
      } catch (err) {
        if (err && err.name === "AbortError") return;
      }
    }

    // Fallback para PC/Desktop: copia link e abre opção de WhatsApp
    try {
      await navigator.clipboard.writeText(`${dadosShare.text} ${urlOficial}`);
      mostrarToast("🔗 Link do FaviNews copiado para a área de transferência!");
    } catch (_) {
      window.open(
        `https://wa.me/?text=${encodeURIComponent(dadosShare.text + " " + urlOficial)}`,
        "_blank"
      );
    }
  });
}

elBtnCrawler.addEventListener("click", async () => {
  elBtnCrawler.classList.add("girando");
  elLabelAtualizado.textContent = "Varrendo fontes...";
  if (elTextoStatusCiclo) {
    elTextoStatusCiclo.textContent = "⏳ Giro em andamento: consultando portais e atualizando catalogo_3dias.json...";
  }
  try {
    const resp = await fetch("/api/atualizar-agora", { method: "POST" }).catch(() => null);
    await carregarDadosBase();
  } finally {
    elBtnCrawler.classList.remove("girando");
  }
});

// Registra e força atualização imediata do Service Worker para não reter versão antiga
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("./sw.js")
      .then((reg) => reg.update())
      .catch(() => {});
  });
}

// Inicialização com Splash Screen "Em 15 minutos tudo pode mudar !!"
window.addEventListener("DOMContentLoaded", () => {
  exibirSplashScreen(1650);
  carregarDadosBase(false);

  // Consulta o status_ciclo no JSON a cada 5 segundos para mostrar o andamento ao vivo
  setInterval(() => {
    carregarDadosBase(true);
  }, 5 * 1000);
});

