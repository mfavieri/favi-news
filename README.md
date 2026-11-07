# 🎙️ FaviNews — *"Em 15 minutos tudo pode mudar !!"*

Agregador e curador pessoal de notícias das primeiras páginas e portais confiáveis, projetado com arquitetura desacoplada: **Backend Crawler (GitHub Actions a cada 15 min)** + **Base de Conhecimento em Arquivos HTML Autocontidos (Imagens em Bytecode/Base64)** + **Frontend Leitor Mobile/PWA Sem Login**.

---

## 🏗️ Arquitetura do Projeto

- **`config/fontes.config.json`** — Lista configurável de editorias (*Política, Economia, Esporte, Ciências, Saúde, Trânsito RJ*) e seus respectivos feeds RSS.
- **`backend/crawler.py`** — Motor coletor que:
  1. Varre os portais configurados;
  2. Extrai o texto limpo da notícia, monta a síntese executiva (Resenha) e converte as imagens para **bytecode Base64** comprimido;
  3. Salva os pares de arquivos HTML padronizados pelo timestamp até o segundo (`YYYYMMDD-HHMMSS`):
     - `YYYYMMDD-HHMMSS_R_<Categoria>_<Subtopico>.html` (**Resenha `_R_`**)
     - `YYYYMMDD-HHMMSS_N_<Categoria>_<Subtopico>.html` (**Notícia Completa `_N_`**)
  4. Executa o **Expurgo Automático de 3 Dias (72h)** diretamente pelo carimbo `YYYYMMDD-HHMMSS` do nome do arquivo;
  5. Atualiza o índice leve `base_conhecimento/catalogo_3dias.json` e sincroniza com o Google Drive.
- **`.github/workflows/crawler_15min.yml`** — Cron job gratuito no GitHub Actions que executa o Crawler a cada 15 minutos (`*/15 * * * *`) sem depender de computador ligado.
- **`index.html` / `css/styles.css` / `js/app.js`** — Aplicativo Mobile/PWA com Splash Screen oficial (*"Em 15 minutos tudo pode mudar !!"*), acesso direto **Sem Login**, filtro por editoria e busca instantânea por palavra-chave.

---

## 🚀 Como Executar Localmente

1. **Rodar um giro manual do Crawler:**
   ```powershell
   python backend/crawler.py
   ```
2. **Subir o Servidor do App PWA (`http://localhost:8090`):**
   ```powershell
   python server.py
   ```

