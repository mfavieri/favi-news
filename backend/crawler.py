"""
Motor Crawler Principal do Favi News ("Em 15 minutos tudo pode mudar !!").
Varre os portais configurados em `config/fontes.config.json`, extrai manchetes,
resenhas, textos das notícias e imagens (convertendo-as para bytecode Base64),
salva os pares `_R_` (Resenha) e `_N_` (Notícia Completa) padronizados por
timestamp `YYYYMMDD-HHMMSS` e executa o expurgo automático da janela de 3 dias.
"""

import email.utils
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Garante que o diretório raiz do projeto esteja no sys.path
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from backend.drive_service import (
    FUSO_BRASILIA,
    agora_brasilia,
    carregar_catalogo,
    expurgar_arquivos_antigos,
    extrair_metadados_do_nome,
    salvar_catalogo,
    sincronizar_google_drive,
)
from backend.html_builder import (
    gerar_html_noticia,
    gerar_html_resenha,
    montar_nomes_arquivos,
)
from backend.image_utils import (
    HEADERS_PADRAO,
    baixar_imagem_para_base64,
    gerar_svg_painel_clima_niteroi_base64,
    gerar_svg_placeholder_base64,
)


def limpar_tags_html(texto_html: str) -> str:
    """Remove tags HTML, scripts e normaliza espaços em branco."""
    if not texto_html:
        return ""
    sem_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", texto_html, flags=re.DOTALL | re.IGNORECASE)
    sem_tags = re.sub(r"<[^>]+>", " ", sem_script)
    decodificado = html.unescape(sem_tags)
    return re.sub(r"\s+", " ", decodificado).strip()


def extrair_primeira_imagem_html(trecho_html: str) -> Optional[str]:
    """Busca a primeira URL de imagem dentro de um trecho HTML do RSS."""
    if not trecho_html:
        return None
    m = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', trecho_html, flags=re.IGNORECASE)
    return m.group(1) if m else None


def converter_data_rss(pub_date_str: str) -> datetime:
    """Converte datas RFC-2822 ou ISO-8601 do RSS para o fuso horário do Rio/Brasília (UTC-3)."""
    agora_br = agora_brasilia()
    if not pub_date_str:
        return agora_br
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str.strip())
        if dt.tzinfo is not None:
            dt = dt.astimezone(FUSO_BRASILIA).replace(tzinfo=None)
        if dt > agora_br + timedelta(minutes=5):
            return agora_br
        return dt
    except Exception:
        pass
    try:
        dt_iso = datetime.fromisoformat(pub_date_str.strip().replace("Z", "+00:00"))
        if dt_iso.tzinfo is not None:
            dt_iso = dt_iso.astimezone(FUSO_BRASILIA).replace(tzinfo=None)
        return dt_iso
    except Exception:
        return agora_br


def alocar_carimbo_unico(dt_base: datetime, carimbos_usados: Set[str]) -> Tuple[str, datetime]:
    """
    Gera o carimbo `YYYYMMDD-HHMMSS` cravado até o segundo.
    Se já houver outra notícia no exato mesmo segundo, incrementa +1 segundo
    para manter a chave primária 100% única sem colisões.
    """
    dt_atual = dt_base
    while True:
        carimbo = dt_atual.strftime("%Y%m%d-%H%M%S")
        if carimbo not in carimbos_usados:
            carimbos_usados.add(carimbo)
            return carimbo, dt_atual
        dt_atual += timedelta(seconds=1)


def raspar_artigo_completo(url: str, timeout: int = 6) -> Tuple[List[str], Optional[str]]:
    """
    Visita a página da notícia para extrair os parágrafos do corpo e a imagem OpenGraph (`og:image`),
    caso o feed RSS traga apenas o resumo curto.
    """
    if not url or "news.google.com" in url:
        return [], None

    try:
        req = urllib.request.Request(url, headers=HEADERS_PADRAO)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            conteudo_bytes = resp.read(350_000)
            html_bruto = conteudo_bytes.decode("utf-8", errors="ignore")

        # Tenta extrair og:image
        og_img = None
        m_og = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
            html_bruto,
            flags=re.IGNORECASE,
        )
        if not m_og:
            m_og = re.search(
                r'<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']',
                html_bruto,
                flags=re.IGNORECASE,
            )
        if m_og:
            og_img = html.unescape(m_og.group(1))

        # Extrai parágrafos significativos (<p>...</p>)
        blocos_p = re.findall(r"<p[^>]*>(.*?)</p>", html_bruto, flags=re.DOTALL | re.IGNORECASE)
        paragrafos: List[str] = []
        for b in blocos_p:
            texto_p = limpar_tags_html(b)
            if len(texto_p) >= 65 and not any(
                ruido in texto_p.lower()
                for ruido in ["cookies", "assine já", "todos os direitos reservados", "newsletter", "publicidade"]
            ):
                if texto_p not in paragrafos:
                    paragrafos.append(texto_p)
            if len(paragrafos) >= 10:
                break

        return paragrafos, og_img
    except Exception:
        return [], None


def construir_resenha_inteligente(titulo: str, descricao_rss: str, paragrafos: List[str], fonte: str) -> Tuple[str, List[str]]:
    """
    Constrói a Resenha (_R_) e os bullet points executivos a partir do Lead
    jornalístico da notícia, garantindo leitura rápida em 15 segundos.
    """
    base_texto = descricao_rss if len(descricao_rss) >= 50 else (paragrafos[0] if paragrafos else titulo)
    if len(base_texto) > 360:
        base_texto = base_texto[:357].rsplit(" ", 1)[0] + "..."

    pontos: List[str] = []
    # Ponto 1: Fato central (Manchete/Lead)
    pontos.append(f"Fato Central: {titulo}")

    # Ponto 2: Contexto imediato
    if descricao_rss and descricao_rss.lower() != titulo.lower():
        resumo_curto = descricao_rss[:220] + ("..." if len(descricao_rss) > 220 else "")
        pontos.append(f"Contexto: {resumo_curto}")
    elif len(paragrafos) > 0:
        p0 = paragrafos[0][:220] + ("..." if len(paragrafos[0]) > 220 else "")
        pontos.append(f"Contexto: {p0}")

    # Ponto 3: Desdobramento adicional se houver mais parágrafos
    if len(paragrafos) > 1:
        p1 = paragrafos[1][:220] + ("..." if len(paragrafos[1]) > 220 else "")
        pontos.append(f"Detalhes: {p1}")
    else:
        pontos.append(f"Apuração publicada por {fonte}.")

    return base_texto, pontos


MAPA_WMO_CLIMA = {
    0: ("☀️", "Sol e Céu Limpo"),
    1: ("🌤️", "Sol com Poucas Nuvens"),
    2: ("⛅", "Sol entre Nuvens"),
    3: ("☁️", "Céu Encoberto"),
    45: ("🌫️", "Nevoeiro"),
    48: ("🌫️", "Nevoeiro Úmido"),
    51: ("🌦️", "Garoa Leve"),
    53: ("🌦️", "Chuvisco Moderado"),
    55: ("🌧️", "Chuvisco Intenso"),
    61: ("🌧️", "Chuva Fraca"),
    63: ("🌧️", "Chuva Moderada"),
    65: ("⛈️", "Chuva Forte"),
    80: ("🌦️", "Pancadas de Chuva Isoladas"),
    81: ("🌧️", "Pancadas de Chuva"),
    82: ("⛈️", "Temporal / Chuva Intensa"),
    95: ("⛈️", "Tempestade com Raios"),
}


def gerar_boletim_clima_niteroi(
    cat_cfg: Dict,
    carimbos_usados: Set[str],
    pasta_base: Path,
) -> Optional[Dict]:
    """
    Gera o Boletim Meteorológico em Tempo Real de Niterói - RJ (com previsão de 3 dias
    e referência direta ao Climatempo Niterói) em par _R_ e _N_ autocontido.
    """
    url_api = (
        "https://api.open-meteo.com/v1/forecast?"
        "latitude=-22.8833&longitude=-43.1036"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=America%2FSao_Paulo&forecast_days=3"
    )
    try:
        req = urllib.request.Request(url_api, headers=HEADERS_PADRAO)
        with urllib.request.urlopen(req, timeout=8) as resp:
            dados = json.loads(resp.read().decode("utf-8"))

        atual = dados.get("current", {})
        diario = dados.get("daily", {})

        temp = float(atual.get("temperature_2m", 28.0))
        sensacao = float(atual.get("apparent_temperature", temp))
        umidade = int(atual.get("relative_humidity_2m", 65))
        vento = float(atual.get("wind_speed_10m", 10.0))
        wcode = int(atual.get("weather_code", 1))
        icone_cond, texto_cond = MAPA_WMO_CLIMA.get(wcode, ("⛅", "Tempo Variável"))

        t_min_lista = diario.get("temperature_2m_min", [22.0, 21.0, 21.0])
        t_max_lista = diario.get("temperature_2m_max", [31.0, 29.0, 28.0])
        prob_lista = diario.get("precipitation_probability_max", [10, 20, 30])
        wcode_lista = diario.get("weather_code", [wcode, wcode, wcode])
        datas_lista = diario.get("time", [])

        t_min_hoje = float(t_min_lista[0])
        t_max_hoje = float(t_max_lista[0])
        prob_hoje = int(prob_lista[0])

        agora_br = agora_brasilia()
        carimbo_ts, dt_alocado = alocar_carimbo_unico(agora_br, carimbos_usados)
        nomes = montar_nomes_arquivos(carimbo_ts, cat_cfg["id"], "Niteroi")

        b64_painel = gerar_svg_painel_clima_niteroi_base64(
            temp_atual=temp,
            sensacao=sensacao,
            temp_min=t_min_hoje,
            temp_max=t_max_hoje,
            chuva_prob=prob_hoje,
            umidade=umidade,
            condicao_icone=icone_cond,
            condicao_texto=texto_cond,
        )

        # Detecta alertas severos de clima em Niterói (estilo MSN Clima)
        alerta_msn = ""
        if sensacao >= 36.0:
            alerta_msn = f"⚠️ ALERTA DE CALOR: Sensação térmica de {sensacao:.0f}°C em Niterói! Hidrate-se e evite sol forte."
        elif prob_hoje >= 60 or wcode in (65, 81, 82, 95):
            alerta_msn = f"⚠️ ALERTA DE CHUVA/TEMPO SEVERO: {prob_hoje}% de probabilidade de chuva em Niterói hoje."
        elif len(prob_lista) > 1 and int(prob_lista[1]) >= 65:
            alerta_msn = f"⚠️ ALERTA DE VIRADA NO TEMPO: Previsão de {prob_lista[1]}% de chuva amanhã em Niterói."

        prefixo_alerta = "⚠️ [ALERTA CLIMA] " if alerta_msn else ""
        titulo = (
            f"{prefixo_alerta}Niterói - RJ Agora: {temp:.0f}°C ({texto_cond}) • "
            f"Sensação de {sensacao:.0f}°C | Máx {t_max_hoje:.0f}°C / Mín {t_min_hoje:.0f}°C"
        )
        resenha_texto = (
            f"{alerta_msn + ' ' if alerta_msn else ''}"
            f"Boletim atualizado de Niterói (Icaraí / Centro / Região Oceânica): faz {temp:.1f}°C "
            f"neste momento com sensação térmica de {sensacao:.1f}°C, umidade em {umidade}% e "
            f"probabilidade de chuva de {prob_hoje}% hoje."
        )

        pontos_chave = []
        if alerta_msn:
            pontos_chave.append(alerta_msn)
        pontos_chave.extend([
            f"Agora em Niterói: {icone_cond} {temp:.1f}°C ({texto_cond}) — Sensação térmica de {sensacao:.1f}°C.",
            f"Hoje em Niterói: Mínima de {t_min_hoje:.0f}°C e Máxima de {t_max_hoje:.0f}°C | Chance de chuva: {prob_hoje}%.",
        ])

        paragrafos = [
            resenha_texto,
            f"Condições atuais registradas na estação Niterói - RJ: ventos de {vento:.1f} km/h, umidade relativa do ar em {umidade}% e condição de {texto_cond.lower()}.",
        ]

        # Adiciona previsão detalhada dos 3 dias
        nomes_dias = ["Hoje", "Amanhã", "Próximo Dia"]
        for idx in range(min(3, len(t_max_lista))):
            ic_d, txt_d = MAPA_WMO_CLIMA.get(int(wcode_lista[idx]), ("⛅", "Variável"))
            dt_str = datas_lista[idx] if idx < len(datas_lista) else nomes_dias[idx]
            linha_prev = (
                f"📅 Previsão {nomes_dias[idx]} ({dt_str}) em Niterói: {ic_d} {txt_d} — "
                f"Mínima {t_min_lista[idx]:.0f}°C / Máxima {t_max_lista[idx]:.0f}°C "
                f"(Chance de chuva: {prob_lista[idx]}%)."
            )
            paragrafos.append(linha_prev)
            if idx == 1:
                pontos_chave.append(linha_prev)

        paragrafos.append(
            "Fonte de Referência: Climatempo Niterói - RJ & Alertas MSN Clima (msn.com/pt-br/clima)."
        )

        url_climatempo_niteroi = "https://www.climatempo.com.br/previsao-do-tempo/cidade/315/niteroi-rj"

        dados_artigo = {
            "carimbo_ts": carimbo_ts,
            "titulo": titulo,
            "fonte": "Climatempo • Niterói - RJ",
            "categoria_id": cat_cfg["id"],
            "categoria_rotulo": cat_cfg["rotulo"],
            "icone": cat_cfg["icone"],
            "cor": cat_cfg["cor"],
            "subtopico": "Niteroi",
            "data_fato_formatada": dt_alocado.strftime("%d/%m/%Y às %Hh%M"),
            "data_iso": dt_alocado.isoformat(),
            "resenha_texto": resenha_texto,
            "pontos_chave": pontos_chave,
            "paragrafos_noticia": paragrafos,
            "imagem_base64_miniatura": b64_painel,
            "imagem_base64_completa": b64_painel,
            "arquivo_r": nomes["arquivo_r"],
            "arquivo_n": nomes["arquivo_n"],
            "url_original": url_climatempo_niteroi,
        }

        (pasta_base / nomes["arquivo_r"]).write_text(gerar_html_resenha(dados_artigo), encoding="utf-8")
        (pasta_base / nomes["arquivo_n"]).write_text(gerar_html_noticia(dados_artigo), encoding="utf-8")
        print(f"  [+] Boletim Clima Niterói gerado: {nomes['arquivo_r']}")

        return {
            "carimbo_ts": carimbo_ts,
            "titulo": titulo,
            "fonte": "Climatempo • Niterói - RJ",
            "categoria_id": cat_cfg["id"],
            "categoria_rotulo": cat_cfg["rotulo"],
            "icone": cat_cfg["icone"],
            "cor": cat_cfg["cor"],
            "subtopico": "Niteroi",
            "data_fato_formatada": dt_alocado.strftime("%d/%m/%Y às %Hh%M"),
            "resenha_texto": resenha_texto,
            "pontos_chave": pontos_chave,
            "arquivo_r": nomes["arquivo_r"],
            "arquivo_n": nomes["arquivo_n"],
            "url_original": url_climatempo_niteroi,
            "thumbnail_base64": b64_painel,
        }
    except Exception as exc:
        print(f"  [!] Aviso ao gerar boletim ao vivo de Niterói: {exc}")
        return None


def processar_feed_rss(
    fonte_cfg: Dict,
    cat_cfg: Dict,
    max_itens: int,
    urls_ja_processadas: Set[str],
    carimbos_usados: Set[str],
    pasta_base: Path,
    limite_corte: datetime,
) -> List[Dict]:
    """Lê um feed RSS, processa as notícias inéditas dos últimos 3 dias e gera os pares _R_ e _N_."""
    novos_itens_catalogo: List[Dict] = []
    rss_url = fonte_cfg["rss_url"]
    nome_fonte = fonte_cfg["nome"]
    subtopico = fonte_cfg.get("subtopico", cat_cfg.get("subtopico_padrao", "Brasil"))

    try:
        req = urllib.request.Request(rss_url, headers=HEADERS_PADRAO)
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        print(f"  [!] Aviso ao ler RSS de '{nome_fonte}': {exc}")
        return novos_itens_catalogo

    items_xml = root.findall(".//item")
    if not items_xml:
        items_xml = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    contador = 0
    for item in items_xml:
        if contador >= max_itens:
            break

        titulo_el = item.find("title")
        if titulo_el is None:
            titulo_el = item.find("{http://www.w3.org/2005/Atom}title")
        titulo = limpar_tags_html(titulo_el.text if titulo_el is not None and titulo_el.text else "")
        # Filtra títulos vazios, muito curtos (ex: apenas nome de portal no MSN) ou páginas de coordenadas
        if not titulo or len(titulo) < 32 or "previsão do tempo para " in titulo.lower():
            continue

        link_el = item.find("link")
        url_original = ""
        if link_el is not None:
            url_original = (link_el.text or link_el.attrib.get("href", "")).strip()

        if url_original and url_original in urls_ja_processadas:
            continue

        pub_el = item.find("pubDate")
        if pub_el is None:
            pub_el = item.find("{http://purl.org/dc/elements/1.1/}date")
        if pub_el is None:
            pub_el = item.find("{http://www.w3.org/2005/Atom}published")
        dt_fato = converter_data_rss(pub_el.text if pub_el is not None and pub_el.text else "")

        # Ignora notícias com mais de 3 dias (72 horas)
        if dt_fato < limite_corte:
            continue

        desc_el = item.find("description")
        if desc_el is None:
            desc_el = item.find("{http://www.w3.org/2005/Atom}summary")
        desc_bruta = desc_el.text if desc_el is not None and desc_el.text else ""
        descricao_limpa = limpar_tags_html(desc_bruta)

        # Tenta localizar URL de imagem no próprio XML (media:content, enclosure ou <img> na descrição)
        url_img = extrair_primeira_imagem_html(desc_bruta)
        if not url_img:
            for elem in item.iter():
                tag_local = elem.tag.split("}")[-1].lower()
                if tag_local in ("content", "thumbnail", "enclosure"):
                    candidato = elem.attrib.get("url", "")
                    if candidato.startswith("http"):
                        url_img = candidato
                        break

        # Raspa parágrafos completos e og:image da página original
        paragrafos, og_img = raspar_artigo_completo(url_original)
        if not url_img and og_img:
            url_img = og_img

        if not paragrafos and descricao_limpa:
            paragrafos = [descricao_limpa]

        resenha_texto, pontos_chave = construir_resenha_inteligente(
            titulo, descricao_limpa, paragrafos, nome_fonte
        )

        # Converte imagem para bytecode Base64 (ou gera placeholder SVG em Base64 se não houver foto)
        b64_completa = baixar_imagem_para_base64(url_img, largura_max=760, qualidade_jpeg=74)
        b64_miniatura = baixar_imagem_para_base64(url_img, largura_max=420, qualidade_jpeg=66)

        if not b64_completa:
            b64_completa = gerar_svg_placeholder_base64(
                cat_cfg["rotulo"], cat_cfg["icone"], cat_cfg["cor"], eh_miniatura=False
            )
        if not b64_miniatura:
            b64_miniatura = gerar_svg_placeholder_base64(
                cat_cfg["rotulo"], cat_cfg["icone"], cat_cfg["cor"], eh_miniatura=True
            )

        # Aloca o timestamp único YYYYMMDD-HHMMSS
        carimbo_ts, dt_alocado = alocar_carimbo_unico(dt_fato, carimbos_usados)
        nomes = montar_nomes_arquivos(carimbo_ts, cat_cfg["id"], subtopico)

        dados_artigo = {
            "carimbo_ts": carimbo_ts,
            "titulo": titulo,
            "fonte": nome_fonte,
            "categoria_id": cat_cfg["id"],
            "categoria_rotulo": cat_cfg["rotulo"],
            "icone": cat_cfg["icone"],
            "cor": cat_cfg["cor"],
            "subtopico": subtopico,
            "data_fato_formatada": dt_alocado.strftime("%d/%m/%Y às %Hh%M"),
            "data_iso": dt_alocado.isoformat(),
            "resenha_texto": resenha_texto,
            "pontos_chave": pontos_chave,
            "paragrafos_noticia": paragrafos,
            "imagem_base64_miniatura": b64_miniatura,
            "imagem_base64_completa": b64_completa,
            "arquivo_r": nomes["arquivo_r"],
            "arquivo_n": nomes["arquivo_n"],
            "url_original": url_original,
        }

        # Grava os 2 arquivos HTML autocontidos na Base de Conhecimento
        html_r = gerar_html_resenha(dados_artigo)
        html_n = gerar_html_noticia(dados_artigo)

        (pasta_base / nomes["arquivo_r"]).write_text(html_r, encoding="utf-8")
        (pasta_base / nomes["arquivo_n"]).write_text(html_n, encoding="utf-8")

        # Registra metadado enxuto no catálogo para a Home do PWA abrir em milissegundos
        novos_itens_catalogo.append(
            {
                "carimbo_ts": carimbo_ts,
                "titulo": titulo,
                "fonte": nome_fonte,
                "categoria_id": cat_cfg["id"],
                "categoria_rotulo": cat_cfg["rotulo"],
                "icone": cat_cfg["icone"],
                "cor": cat_cfg["cor"],
                "subtopico": subtopico,
                "data_fato_formatada": dt_alocado.strftime("%d/%m/%Y às %Hh%M"),
                "resenha_texto": resenha_texto,
                "pontos_chave": pontos_chave,
                "arquivo_r": nomes["arquivo_r"],
                "arquivo_n": nomes["arquivo_n"],
                "url_original": url_original,
                "thumbnail_base64": b64_miniatura,
            }
        )

        if url_original:
            urls_ja_processadas.add(url_original)
        contador += 1
        print(f"  [+] Gerado par: {nomes['arquivo_r']} | {nomes['arquivo_n']}")

    return novos_itens_catalogo


def atualizar_andamento_json(pasta_base: Path, estado_txt: str, mensagem: str, progresso_pct: int, extras: Optional[Dict] = None):
    """
    Atualiza imediatamente o `status_ciclo` dentro do `catalogo_3dias.json`
    para que o Frontend mostre o andamento ao vivo passo a passo.
    """
    caminho_cat = pasta_base / "catalogo_3dias.json"
    agora = agora_brasilia()
    proximo = agora + timedelta(minutes=15)
    try:
        if caminho_cat.exists():
            with open(caminho_cat, "r", encoding="utf-8") as f:
                cat = json.load(f)
        else:
            cat = {"itens": [], "total_itens": 0, "janela_dias": 3}

        sc = cat.get("status_ciclo", {})
        sc.update({
            "estado": estado_txt,
            "verificado_em": agora.strftime("%d/%m/%Y %H:%M:%S"),
            "hora_curta": agora.strftime("%H:%M"),
            "proximo_giro": proximo.strftime("%H:%M"),
            "progresso_pct": progresso_pct,
            "mensagem": mensagem,
        })
        if extras:
            sc.update(extras)
        cat["status_ciclo"] = sc
        with open(caminho_cat, "w", encoding="utf-8") as f:
            json.dump(cat, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def executar_crawler() -> Dict:
    """Executa um ciclo completo de coleta, geração de HTMLs, expurgo de 3 dias e catálogo."""
    caminho_cfg = RAIZ_PROJETO / "config" / "fontes.config.json"
    pasta_base = RAIZ_PROJETO / "base_conhecimento"
    pasta_base.mkdir(parents=True, exist_ok=True)

    with open(caminho_cfg, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    dias_retencao = int(cfg.get("janela_retencao_dias", 3))
    max_por_fonte = int(cfg.get("max_noticias_por_fonte", 3))
    limite_corte = agora_brasilia() - timedelta(days=dias_retencao)

    print("=================================================================")
    print("🎙️  FAVI NEWS CRAWLER — 'Em 15 minutos tudo pode mudar !!'")
    print("=================================================================")

    # 1. Expurga arquivos com mais de 3 dias (> 72h)
    expurgados = expurgar_arquivos_antigos(pasta_base, dias_retencao=dias_retencao)
    if expurgados:
        print(f"🧹 Expurgo de {dias_retencao} dias: {len(expurgados)} arquivo(s) antigo(s) removido(s).")

    # 1.1 Expurga arquivos de categorias que foram removidas do fontes.config.json
    categorias_ativas = {c["id"] for c in cfg.get("categorias", [])}
    removidos_cat = 0
    for arq_html in pasta_base.glob("*.html"):
        meta = extrair_metadados_do_nome(arq_html.name)
        if meta and meta["categoria"] not in categorias_ativas:
            try:
                arq_html.unlink()
                removidos_cat += 1
            except OSError:
                pass
    if removidos_cat:
        print(f"🗑️ Limpeza de categorias desativadas: {removidos_cat} arquivo(s) removido(s).")

    # 2. Carrega catálogo existente (filtrando apenas categorias ativas)
    cat_atual = carregar_catalogo(pasta_base)
    itens_existentes: List[Dict] = [
        it for it in cat_atual.get("itens", []) if it.get("categoria_id") in categorias_ativas
    ]
    urls_ja_processadas: Set[str] = {
        it.get("url_original", "") for it in itens_existentes if it.get("url_original")
    }
    carimbos_usados: Set[str] = {
        it.get("carimbo_ts", "") for it in itens_existentes if it.get("carimbo_ts")
    }

    todos_novos: List[Dict] = []
    fontes_verificadas = 0
    lista_categorias = cfg.get("categorias", [])
    total_cats = max(1, len(lista_categorias))

    atualizar_andamento_json(
        pasta_base,
        estado_txt="em_andamento",
        mensagem=f"⏳ Iniciando giro das {agora_brasilia().strftime('%H:%M')} • preparando leitura de {total_cats} editorias...",
        progresso_pct=5,
    )

    for idx_cat, cat_cfg in enumerate(lista_categorias, start=1):
        pct = int((idx_cat - 0.5) / total_cats * 90)
        atualizar_andamento_json(
            pasta_base,
            estado_txt="em_andamento",
            mensagem=f"📡 [{idx_cat}/{total_cats}] Varrendo {cat_cfg['icone']} {cat_cfg['rotulo']} ({len(todos_novos)} novidade(s) até agora)...",
            progresso_pct=pct,
        )
        print(f"\n📡 Varrendo editoria: {cat_cfg['icone']} {cat_cfg['rotulo']}...")
        if cat_cfg.get("id") == "Clima":
            fontes_verificadas += 1
            # Remove boletins automáticos anteriores de Niterói para manter sempre o mais fresco no topo
            for ant in list(itens_existentes):
                if ant.get("fonte") == "Climatempo • Niterói - RJ":
                    for chave_arq in ("arquivo_r", "arquivo_n"):
                        caminho_ant = pasta_base / ant.get(chave_arq, "")
                        if caminho_ant.exists():
                            try:
                                caminho_ant.unlink()
                            except OSError:
                                pass
                    itens_existentes.remove(ant)
            boletim_nit = gerar_boletim_clima_niteroi(cat_cfg, carimbos_usados, pasta_base)
            if boletim_nit:
                todos_novos.append(boletim_nit)
        for fonte_cfg in cat_cfg.get("fontes", []):
            fontes_verificadas += 1
            atualizar_andamento_json(
                pasta_base,
                estado_txt="em_andamento",
                mensagem=f"📡 [{idx_cat}/{total_cats}] Lendo fonte: {fonte_cfg['nome']} ({cat_cfg['rotulo']})...",
                progresso_pct=pct,
            )
            novos = processar_feed_rss(
                fonte_cfg=fonte_cfg,
                cat_cfg=cat_cfg,
                max_itens=max_por_fonte,
                urls_ja_processadas=urls_ja_processadas,
                carimbos_usados=carimbos_usados,
                pasta_base=pasta_base,
                limite_corte=limite_corte,
            )
            todos_novos.extend(novos)

    # Desconta 1 do boletim de clima para contar apenas matérias inéditas reais como "novas_paginas"
    novas_materias_reais = max(0, len(todos_novos) - 1)

    # 3. Salva o catálogo atualizado de 3 dias com status completo do giro
    catalogo_final = salvar_catalogo(
        pasta_base,
        itens_existentes + todos_novos,
        dias_retencao=dias_retencao,
        info_ciclo={
            "novas_paginas": novas_materias_reais,
            "fontes_verificadas": fontes_verificadas,
            "expurgados": len(expurgados) + removidos_cat,
        },
    )

    # 4. Sincroniza com o Google Drive se habilitado/configurado
    status_drive = sincronizar_google_drive(
        pasta_base=pasta_base,
        folder_id=cfg.get("google_drive", {}).get("folder_id", ""),
        dias_retencao=dias_retencao,
    )

    resumo = {
        "novos_pares_gerados": len(todos_novos),
        "total_ativos_3dias": catalogo_final["total_itens"],
        "expurgados_local": len(expurgados),
        "atualizado_em": catalogo_final["atualizado_em"],
        "drive": status_drive,
    }
    print("\n✅ Ciclo concluído com sucesso:", json.dumps(resumo, ensure_ascii=False))
    return resumo


if __name__ == "__main__":
    executar_crawler()

