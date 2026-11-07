"""
Gerador de Arquivos HTML Autocontidos (_R_ Resenha e _N_ Notícia) para o Favi News.
Cada arquivo gerado segue rigorosamente o padrão de nomenclatura:
  - YYYYMMDD-HHMMSS_R_<Categoria>_<Subtopico>.html
  - YYYYMMDD-HHMMSS_N_<Categoria>_<Subtopico>.html
Todas as imagens são embutidas em bytecode (Base64) dentro do próprio arquivo HTML.
"""

import html
import re
from typing import Dict, List


def limpar_subtopico(texto: str) -> str:
    """
    Remove acentos e caracteres especiais para compor o sufixo do nome do arquivo.
    Ex: 'São Paulo' -> 'SaoPaulo', 'Brasil' -> 'Brasil'
    """
    mapa = str.maketrans(
        "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ",
        "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN",
    )
    limpo = texto.translate(mapa)
    limpo = re.sub(r"[^a-zA-Z0-9]", "", limpo)
    return limpo or "Brasil"


def montar_nomes_arquivos(carimbo_ts: str, categoria_id: str, subtopico: str) -> Dict[str, str]:
    """
    Retorna os nomes padronizados para o par Notícia (_N_) e Resenha (_R_).
    Exemplo:
      - 20261107-081500_N_Politica_Brasil.html
      - 20261107-081500_R_Politica_Brasil.html
    """
    cat_limpa = limpar_subtopico(categoria_id)
    sub_limpo = limpar_subtopico(subtopico)
    return {
        "arquivo_n": f"{carimbo_ts}_N_{cat_limpa}_{sub_limpo}.html",
        "arquivo_r": f"{carimbo_ts}_R_{cat_limpa}_{sub_limpo}.html",
    }


CSS_COMUM_EMBUTIDO = """
  :root {
    --bg: #0f172a;
    --card: #1e293b;
    --text: #f8fafc;
    --muted: #94a3b8;
    --border: #334155;
    --accent: #38bdf8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background-color: var(--bg);
    color: var(--text);
    line-height: 1.65;
    padding: 16px;
    max-width: 760px;
    margin: 0 auto;
  }
  .favi-article {
    background-color: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 10px 30px rgba(0,0,0,0.35);
  }
  .favi-hero-img {
    width: 100%;
    max-height: 380px;
    object-fit: cover;
    display: block;
    border-bottom: 1px solid var(--border);
  }
  .favi-content {
    padding: 20px;
  }
  .favi-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 12px;
    font-size: 0.82rem;
  }
  .badge-tipo {
    padding: 4px 10px;
    border-radius: 999px;
    font-weight: 700;
    letter-spacing: 0.4px;
    text-transform: uppercase;
  }
  .badge-r { background: rgba(56, 189, 248, 0.18); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); }
  .badge-n { background: rgba(34, 197, 94, 0.18); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4); }
  .badge-cat {
    padding: 4px 10px;
    border-radius: 999px;
    font-weight: 600;
    background: rgba(255,255,255,0.08);
    color: #e2e8f0;
  }
  .favi-meta {
    color: var(--muted);
    font-size: 0.85rem;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }
  h1 {
    font-size: 1.45rem;
    line-height: 1.3;
    margin-bottom: 12px;
    color: #ffffff;
  }
  .resenha-box {
    background: rgba(15, 23, 42, 0.65);
    border-left: 4px solid #38bdf8;
    padding: 16px;
    border-radius: 0 12px 12px 0;
    margin: 16px 0;
  }
  .resenha-box h2 {
    font-size: 0.95rem;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: #38bdf8;
    margin-bottom: 10px;
  }
  .resenha-lista {
    padding-left: 18px;
  }
  .resenha-lista li {
    margin-bottom: 8px;
    color: #e2e8f0;
  }
  .paragrafo-noticia {
    margin-bottom: 14px;
    font-size: 1.03rem;
    color: #e2e8f0;
  }
  .favi-footer {
    margin-top: 22px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: space-between;
    align-items: center;
  }
  .btn-link {
    display: inline-block;
    padding: 10px 16px;
    border-radius: 10px;
    text-decoration: none;
    font-weight: 600;
    font-size: 0.9rem;
    background: #2563eb;
    color: #ffffff;
  }
  .btn-link.secundario {
    background: rgba(255,255,255,0.08);
    color: #cbd5e1;
  }
"""


def gerar_html_resenha(dados: Dict) -> str:
    """
    Gera o arquivo HTML da Resenha (_R_) com imagem em bytecode (Base64),
    síntese executiva, fonte e data/hora do fato.
    """
    titulo = html.escape(dados["titulo"])
    fonte = html.escape(dados["fonte"])
    categoria_rotulo = html.escape(dados["categoria_rotulo"])
    icone = html.escape(dados.get("icone", "📰"))
    data_formatada = html.escape(dados["data_fato_formatada"])
    resenha_texto = html.escape(dados["resenha_texto"])
    pontos_chave: List[str] = dados.get("pontos_chave", [])
    img_b64 = dados["imagem_base64_miniatura"]
    arquivo_n = html.escape(dados["arquivo_n"])
    arquivo_r = html.escape(dados["arquivo_r"])
    url_original = html.escape(dados.get("url_original", "#"))

    itens_html = "\n".join(f"<li>{html.escape(p)}</li>" for p in pontos_chave)
    if not itens_html:
        itens_html = f"<li>{resenha_texto}</li>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="favi-tipo" content="R">
  <meta name="favi-timestamp" content="{html.escape(dados['carimbo_ts'])}">
  <meta name="favi-categoria" content="{html.escape(dados['categoria_id'])}">
  <meta name="favi-par-noticia" content="{arquivo_n}">
  <title>[RESENHA] {titulo}</title>
  <style>{CSS_COMUM_EMBUTIDO}</style>
</head>
<body>
  <article class="favi-article" data-arquivo="{arquivo_r}">
    <img class="favi-hero-img" src="{img_b64}" alt="{titulo}">
    <div class="favi-content">
      <div class="favi-badges">
        <span class="badge-tipo badge-r">⚡ Resenha (_R_)</span>
        <span class="badge-cat">{icone} {categoria_rotulo}</span>
      </div>
      <h1>{titulo}</h1>
      <div class="favi-meta">
        📍 <strong>Fonte:</strong> {fonte} &nbsp;|&nbsp; 🕒 <strong>Data do Fato:</strong> {data_formatada}
      </div>
      <div class="resenha-box">
        <h2>📋 Síntese Executiva</h2>
        <ul class="resenha-lista">
          {itens_html}
        </ul>
      </div>
      <p class="paragrafo-noticia">{resenha_texto}</p>
      <div class="favi-footer">
        <a class="btn-link" href="{arquivo_n}" data-abrir-par="{arquivo_n}">📰 Ler Notícia Completa (_N_)</a>
        <a class="btn-link secundario" href="{url_original}" target="_blank" rel="noopener noreferrer">🔗 Fonte Original</a>
      </div>
    </div>
  </article>
</body>
</html>"""


def gerar_html_noticia(dados: Dict) -> str:
    """
    Gera o arquivo HTML da Notícia Completa (_N_) com imagem de capa em bytecode (Base64),
    todos os parágrafos da matéria limpos e metadados completos.
    """
    titulo = html.escape(dados["titulo"])
    fonte = html.escape(dados["fonte"])
    categoria_rotulo = html.escape(dados["categoria_rotulo"])
    icone = html.escape(dados.get("icone", "📰"))
    data_formatada = html.escape(dados["data_fato_formatada"])
    paragrafos: List[str] = dados.get("paragrafos_noticia", [])
    img_b64 = dados["imagem_base64_completa"]
    arquivo_n = html.escape(dados["arquivo_n"])
    arquivo_r = html.escape(dados["arquivo_r"])
    url_original = html.escape(dados.get("url_original", "#"))

    corpo_html = "\n".join(
        f'<p class="paragrafo-noticia">{html.escape(p)}</p>' for p in paragrafos if p.strip()
    )
    if not corpo_html:
        corpo_html = f'<p class="paragrafo-noticia">{html.escape(dados["resenha_texto"])}</p>'

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="favi-tipo" content="N">
  <meta name="favi-timestamp" content="{html.escape(dados['carimbo_ts'])}">
  <meta name="favi-categoria" content="{html.escape(dados['categoria_id'])}">
  <meta name="favi-par-resenha" content="{arquivo_r}">
  <title>[NOTÍCIA] {titulo}</title>
  <style>{CSS_COMUM_EMBUTIDO}</style>
</head>
<body>
  <article class="favi-article" data-arquivo="{arquivo_n}">
    <img class="favi-hero-img" src="{img_b64}" alt="{titulo}">
    <div class="favi-content">
      <div class="favi-badges">
        <span class="badge-tipo badge-n">📰 Notícia Completa (_N_)</span>
        <span class="badge-cat">{icone} {categoria_rotulo}</span>
      </div>
      <h1>{titulo}</h1>
      <div class="favi-meta">
        📍 <strong>Fonte:</strong> {fonte} &nbsp;|&nbsp; 🕒 <strong>Data do Fato:</strong> {data_formatada}
      </div>
      <div class="noticia-corpo">
        {corpo_html}
      </div>
      <div class="favi-footer">
        <a class="btn-link" href="{arquivo_r}" data-abrir-par="{arquivo_r}">⚡ Voltar para Resenha (_R_)</a>
        <a class="btn-link secundario" href="{url_original}" target="_blank" rel="noopener noreferrer">🔗 Ver no site ({fonte})</a>
      </div>
    </div>
  </article>
</body>
</html>"""

