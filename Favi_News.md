# 🎯 Nome do Projeto: Favi News

> **Status Oficial:** `5 : [Projeto Finalizado]` (Aceito com louvor! 🎉)  
> **Slogan:** *"Em 15 minutos tudo pode mudar !!"*  
> **Data:** 07/11/2026  
> **Autor:** Favi & Gimmy

---

## 1. 💡 A Ideia (Resumo em 1 parágrafo)
Um agregador e curador pessoal de notícias das primeiras páginas da internet e de sites confiáveis, focado em leitura rápida, limpa e sem ruído. O sistema coleta matérias a cada 15 minutos, gera versões de **Resenha (`_R_`)** e **Notícia Completa (`_N_`)** em arquivos HTML autocontidos (com imagens em bytecode/Base64) armazenados no Google Drive, permitindo leitura instantânea no celular via **PWA (sem necessidade de login)**.

---

## 2. 🎯 Objetivos Principais
- [x] Reunir notícias confiáveis num só lugar para leitura limpa e rápida
- [x] Reunir **Resenha (`_R_`)** / **Notícia (`_N_`)** / **Fonte** / **Data e Hora exata do Fato**
- [x] Classificar por editorias configuráveis: **Clima (Niterói - Climatempo), Variedades (MSN, Gastronomia, Festas, Fofocas, Curiosidades, Viagens, Moda e Entretenimento), Política, Economia, Ciências, Saúde e Trânsito (Rio de Janeiro)**
- [x] Aplicativo **Mobile (PWA)** instalável no celular, leve e 100% passivo (zero processamento pesado no aparelho)

---

## 3. 👤 Como vai funcionar na prática? (Fluxo do Usuário)
1. **Splash Screen Oficial:** No momento da carga do Frontend, exibe a tela de abertura **FaviNews** com o slogan: **"Em 15 minutos tudo pode mudar !!"**.
2. Com o **App (PWA)** instalado no celular, o usuário entra **sem login** e já visualiza as manchetes/resenhas do dia na tela inicial.
3. O App mantém uma janela móvel enxuta de apenas **3 dias de notícias** (as mais antigas são expurgadas automaticamente pelo backend).
4. O usuário pode **filtrar por assuntos (editorias)**, **buscar por palavras-chave** e, ao tocar em uma Resenha (`_R_`), abrir a Notícia Completa (`_N_`) correspondente.

---

## 4. ⚙️ Requisitos, Padrões e Arquitetura Preliminar

### 📁 Base de Conhecimento (Google Drive)
- Pasta específica contendo apenas os arquivos HTML padronizados e o catálogo de índice, configurada para leitura direta pelo PWA (sem exigir login no celular).
- **Padrão de Nomenclatura (Chave Primária por Timestamp `YYYYMMDD-HHMMSS` + Tipo `[N | R | A]`):**
  - `20261107-081500_N_Politica_Brasil.html`
    > **`[N]` — Notícia Completa (`_N_`):** Matéria sobre Política no Brasil relatada/ocorrida em `07/11/2026` às `08h15m00s` — imagens convertidas e embutidas em **bytecode (Base64)** dentro do próprio arquivo HTML. **Retenção: 3 dias (72h).**
  - `20261107-081500_R_Politica_Brasil.html`
    > **`[R]` — Resenha (`_R_`):** Resumo executivo da mesma notícia (`07/11/2026` às `08h15m00s`) — contendo manchete, fonte, data/hora, síntese e miniatura em bytecode (Base64). **Retenção: 3 dias (72h).**
  - `20261107-160710_A_Clima_Niteroi.html`
    > **`[A]` — Alerta Efêmero (`_A_`):** Avisos de baixa sazonalidade (ex: Tempestade / Defesa Civil / INMET). **Retenção: 1 ciclo (15 minutos).** Todo arquivo `_A_` é **deletado automaticamente no início de cada ciclo** e só é recriado se o alerta continuar válido e com severidade ativa no ciclo atual (eliminando alertas de tempestades que já passaram).
  - **Amarração `_R_` ↔ `_N_` ↔ `_A_`:** O carimbo `YYYYMMDD-HHMMSS` garante unicidade e relacionamento direto entre os artefatos.

### 🏗️ Divisão do Sistema em 2 Módulos Desacoplados
1. **Frontend (Leitor Mobile / PWA):**
   - Interface mobile-first instalável no smartphone.
   - Lê apenas o índice de 3 dias e os arquivos pré-formatados (`_R_` na listagem/resumo e `_N_` ao abrir a matéria completa).
   - Zero login, zero scraping no celular, carregamento instantâneo.
2. **Backend (Motor Crawler Serverless — GitHub Actions & Local) + Configurador PC (`⚙️`):**
   - Script Python executado automaticamente na nuvem via **GitHub Actions (`cron` a cada 15 minutos: `3,18,33,48 * * * *`)**, sem depender de computador ligado.
   - **Configurador Exclusivo na Versão PC (`usr: FaviNews` / `psw: NewsFavi`):**
     - Permite **ordenar as abas (`⬆️` / `⬇️`)**, **incluir novas abas e fontes** informando diretamente a URL do site/portal, definir a **Sazonalidade** individual (`Último boletim / 1 ciclo`, `6 horas`, `1 dia`, `3 dias`, `7 dias`) e calibrar o **Filtro de Busca na Página** (`Notícias de primeira página`, `Todo conteúdo`, `Apenas Alertas [A]`, palavras-chave e blacklist).
   - Varre os portais configurados em `fontes.config.json`:
     - **Clima (Niterói & RJ):** Sazonalidade `Último boletim (1 ciclo)` — deleta os anteriores e mantém apenas o boletim atual de Niterói + Alertas `[A]` vigentes
     - **Niterói:** `https://enfoco.com.br/` — Sazonalidade `1 dia` | Filtro `Notícias de primeira página`
     - **Variedades (MSN & Lazer):** MSN Brasil Estilo & Entretenimento, Gastronomia, Festas, Fofocas/Famosos, Curiosidades, Viagens e Moda — Sazonalidade `3 dias`
     - **Política / Geral:** MSN Brasil Notícias, BBC Brasil, Agência Brasil — Sazonalidade `3 dias`
     - **Economia:** MSN Dinheiro, InfoMoney, Agência Brasil — Sazonalidade `3 dias`
     - **Ciências:** `https://mittechreview.com.br/` (MIT Technology Review Brasil) + BBC Ciência — Sazonalidade `7 dias` | Filtro `Todo conteúdo`
     - **Saúde:** Agência Brasil Saúde, CNN Saúde — Sazonalidade `3 dias`
     - **Trânsito (Rio de Janeiro):** COR-Rio, Ponte Rio-Niterói e Vias Expressas — Sazonalidade `1 dia` | Filtro `Notícias de primeira página`
   - Gera os artefatos `.html` (`_R_`, `_N_` e `_A_`) com imagens comprimidas em Base64 e executa o expurgo automático respeitando a sazonalidade de cada aba/fonte.

---

## 5. 🔓 O "Pulo do Gato": Acesso Mobile Sem Login (Zero OAuth no Celular)
Para garantir que o usuário abra o App no celular e veja as manchetes na hora **sem nunca precisar digitar senha ou renovar login do Google**:
1. **Escrita Restrita ao Backend:** Apenas o motor do **GitHub Actions** possui a credencial de escrita (guardada em cofre seguro nos *GitHub Secrets*) para criar os arquivos `_R_` e `_N_` e expurgar os antigos (> 3 dias) na pasta do Google Drive.
2. **Leitura Pública por Link / Estática:**
   - A pasta `Favi_News_Base` no Google Drive fica configurada como **"Qualquer pessoa com o link pode ver" (Somente Leitura)**; e
   - O Crawler atualiza a cada 15 min o arquivo índice `catalogo_3dias.json` (com a lista dos pares `_R_` e `_N_` ativos e seus respectivos IDs/links), podendo também espelhar a janela de 3 dias no GitHub Pages do próprio projeto para entrega ultra-rápida sem bloqueio de CORS.
3. **Cache Offline no PWA:** O Service Worker do celular guarda no aparelho as resenhas já lidas para abrir até sem sinal (metrô/avião).

