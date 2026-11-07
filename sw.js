/**
 * Service Worker do FaviNews PWA.
 * Garante funcionamento rápido e leitura offline dos arquivos HTML (_R_ e _N_)
 * e do catálogo de 3 dias no celular.
 */

const CACHE_NAME = "favinews-cache-v5";
const ARQUIVOS_ESSENCIAIS = [
  "./",
  "./index.html",
  "./css/styles.css",
  "./js/app.js",
  "./manifest.json",
  "./favicon.ico",
  "./icons/FaviNews.png",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ARQUIVOS_ESSENCIAIS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((chaves) =>
      Promise.all(
        chaves.map((chave) => {
          if (chave !== CACHE_NAME) {
            return caches.delete(chave);
          }
        })
      )
    )
  );
  self.clients.claim();
});

// Estratégia Network-First com fallback para Cache (ideal para notícias de 15 em 15 min)
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  // Nunca usa cache antigo para o JSON de status/catálogo de 15 min
  if (event.request.url.includes("catalogo_3dias.json") || event.request.url.includes("fontes.config.json")) {
    event.respondWith(
      fetch(event.request, { cache: "no-store" }).catch(() => caches.match(event.request))
    );
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((respostaRede) => {
        const copia = respostaRede.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copia));
        return respostaRede;
      })
      .catch(() => caches.match(event.request))
  );
});

