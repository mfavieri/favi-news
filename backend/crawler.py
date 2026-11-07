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
    converter_sazonalidade_timedelta,
    expurgar_alertas_ciclo,
    expurgar_arquivos_antigos,
    extrair_metadados_do_nome,
    salvar_catalogo,
    sincronizar_google_drive,
)
from backend.html_builder import (
    gerar_html_alerta,
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


def consultar_alertas_oficiais_rj() -> List[Dict]:
    """
    Consulta a API oficial de Avisos Meteorológicos Ativos do INMET (mesma fonte
    dos alertas de Tempestade/Chuva do MSN Clima no Brasil) filtrando Rio de Janeiro / Niterói.
    """
    url_inmet = "https://apiprevmet3.inmet.gov.br/avisos/ativos"
    alertas_rj: List[Dict] = []
    try:
        req = urllib.request.Request(url_inmet, headers=HEADERS_PADRAO)
        with urllib.request.urlopen(req, timeout=7) as resp:
            dados = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for a in dados.get("hoje", []):
            estados_str = str(a.get("estados", "")) + " " + str(a.get("municipios", ""))
            if "Rio de Janeiro" in estados_str or "Niterói" in estados_str or "RJ" in estados_str:
                alertas_rj.append({
                    "descricao": a.get("descricao", "Alerta Meteorológico"),
                    "severidade": a.get("severidade", "Perigo Potencial"),
                    "inicio": a.get("inicio", ""),
                    "fim": a.get("fim", ""),
                    "riscos": a.get("riscos", []),
                    "instrucoes": a.get("instrucoes", []),
                })
        # Prioriza Tempestade / Chuvas Intensas / Vendaval no topo da lista
        alertas_rj.sort(
            key=lambda x: 0 if any(p in x["descricao"].lower() for p in ("tempestade", "chuva", "vendaval", "granizo")) else 1
        )
    except Exception:
        pass
    return alertas_rj


def gerar_boletim_clima_niteroi(
    cat_cfg: Dict,
    carimbos_usados: Set[str],
    pasta_base: Path,
) -> Optional[Dict]:
    """
    Gera o Boletim Meteorológico em Tempo Real de Niterói - RJ combinando:
    1. Estação real de Niterói (Open-Meteo + wttr.in / METAR SBRJ) com fallback resiliente;
    2. Alertas Meteorológicos Oficiais Ativos (INMET / MSN Clima RJ & Niterói),
       cruzando com a precipitação e vento reais da estação para detectar quando a tempestade já passou.
    """
    url_api = (
        "https://api.open-meteo.com/v1/forecast?"
        "latitude=-22.8833&longitude=-43.1036"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=America%2FSao_Paulo&forecast_days=3"
    )
    try:
        dados = {}
        for tentativa in range(2):
            try:
                req = urllib.request.Request(url_api, headers=HEADERS_PADRAO)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    dados = json.loads(resp.read().decode("utf-8"))
                break
            except Exception:
                if tentativa == 1:
                    dados = {}

        atual = dados.get("current", {})
        diario = dados.get("daily", {})

        temp = float(atual.get("temperature_2m", 26.0))
        sensacao = float(atual.get("apparent_temperature", temp))
        umidade = int(atual.get("relative_humidity_2m", 80))
        precip_mm = float(atual.get("precipitation", 0.0))
        vento = float(atual.get("wind_speed_10m", 8.0))
        wcode = int(atual.get("weather_code", 3))
        icone_cond, texto_cond = MAPA_WMO_CLIMA.get(wcode, ("⛅", "Tempo Variável"))

        # Complementa com leitura da estação METAR de Niterói (wttr.in)
        try:
            req_wttr = urllib.request.Request("https://wttr.in/Niteroi?format=j1&lang=pt", headers=HEADERS_PADRAO)
            with urllib.request.urlopen(req_wttr, timeout=6) as r_w:
                dw = json.loads(r_w.read().decode("utf-8", errors="ignore"))
                cc = dw.get("current_condition", [{}])[0]
                if not atual and cc.get("temp_C"):
                    temp = float(cc["temp_C"])
                if not atual and cc.get("FeelsLikeC"):
                    sensacao = float(cc["FeelsLikeC"])
                if not atual and cc.get("humidity"):
                    umidade = int(cc["humidity"])
                wttr_precip = float(cc.get("precipMM", 0.0) or 0.0)
                # Só usa descrição de chuva/trovoada do wttr se houver precipitação real agora
                if cc.get("lang_pt") and cc["lang_pt"][0].get("value"):
                    desc_wttr = cc["lang_pt"][0]["value"].strip()
                    if precip_mm > 0.2 or wttr_precip > 0.2:
                        texto_cond = desc_wttr
        except Exception:
            pass

        # Verifica se ainda está chovendo/tempestade AGORA na estação de Niterói
        estacao_com_chuva_ou_vento_forte = (precip_mm >= 0.3) or (wcode >= 51) or (vento >= 35.0)
        if not estacao_com_chuva_ou_vento_forte and precip_mm == 0.0 and wcode <= 3:
            texto_cond = f"{texto_cond} • Sem Chuva (0 mm)"

        # Consulta alertas oficiais ativos para Niterói / RJ (INMET / Defesa Civil)
        alertas_ativos = consultar_alertas_oficiais_rj()

        t_min_lista = diario.get("temperature_2m_min", [22.0, 21.0, 21.0])
        t_max_lista = diario.get("temperature_2m_max", [31.0, 29.0, 28.0])
        prob_lista = diario.get("precipitation_probability_max", [40, 35, 30])
        wcode_lista = diario.get("weather_code", [wcode, wcode, wcode])
        datas_lista = diario.get("time", [])

        t_min_hoje = float(t_min_lista[0])
        t_max_hoje = float(t_max_lista[0])
        prob_hoje = int(prob_lista[0])

        alerta_principal_str = ""
        alerta_banner_svg = ""
        aviso_informativo_pos_chuva = ""
        if alertas_ativos:
            a0 = alertas_ativos[0]
            risco_txt = a0["riscos"][0] if a0.get("riscos") else ""
            if estacao_com_chuva_ou_vento_forte:
                # Tempestade/Chuva ativa em Niterói: aciona Banner Vermelho Global de Emergência
                alerta_banner_svg = f"ALERTA {a0['descricao'].upper()} ({a0['severidade']}) EM NITERÓI/RJ"
                alerta_principal_str = (
                    f"🚨 ALERTA OFICIAL ATIVO ({a0['descricao']} - {a0['severidade']}): "
                    f"Vigência de {a0['inicio']} até {a0['fim']}. {risco_txt}"
                )
                if "tempestade" in a0["descricao"].lower() or "chuva" in a0["descricao"].lower():
                    icone_cond = "⛈️"
                    texto_cond = f"Alerta de {a0['descricao']}"
                    prob_hoje = max(prob_hoje, 85)
            else:
                # A tempestade já passou na estação de Niterói (0 mm de chuva e vento calmo)
                aviso_informativo_pos_chuva = (
                    f"ℹ️ Tempestade passou em Niterói (estação registra 0 mm de chuva e vento de {vento:.0f} km/h). "
                    f"Aviso preventivo do INMET ({a0['descricao']}) segue em observação regional até {a0['fim']}."
                )

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
            alerta_banner=alerta_banner_svg,
        )

        prefixo_alerta = (
            f"⛈️ [ALERTA: {alertas_ativos[0]['descricao'].upper()}] "
            if (alertas_ativos and estacao_com_chuva_ou_vento_forte)
            else ""
        )
        titulo = (
            f"{prefixo_alerta}Niterói - RJ Agora: {temp:.0f}°C ({texto_cond}) • "
            f"Vento {vento:.0f} km/h | Máx {t_max_hoje:.0f}°C / Mín {t_min_hoje:.0f}°C"
        )
        resenha_texto = (
            f"{alerta_principal_str + ' | ' if alerta_principal_str else ''}"
            f"Estação Niterói registra agora {temp:.0f}°C ({texto_cond}), sensação de {sensacao:.0f}°C, "
            f"vento de {vento:.0f} km/h e umidade de {umidade}%."
            f"{' ' + aviso_informativo_pos_chuva if aviso_informativo_pos_chuva else ''}"
        )

        pontos_chave = [
            f"Agora na Estação Niterói: {icone_cond} {temp:.0f}°C ({texto_cond}) — Vento {vento:.0f} km/h, sensação {sensacao:.0f}°C e umidade {umidade}%.",
            f"Temperaturas Hoje em Niterói: Mínima de {t_min_hoje:.0f}°C e Máxima de {t_max_hoje:.0f}°C | Probabilidade residual de chuva: {prob_hoje}%.",
        ]
        if estacao_com_chuva_ou_vento_forte and alertas_ativos:
            for al in alertas_ativos[:2]:
                r_resumo = al["riscos"][0] if al.get("riscos") else ""
                pontos_chave.insert(
                    0,
                    f"🚨 Alerta {al['descricao']} ({al['severidade']}): {r_resumo} (até {al['fim']})",
                )
        elif aviso_informativo_pos_chuva:
            pontos_chave.append(aviso_informativo_pos_chuva)

        paragrafos = [resenha_texto]
        if estacao_com_chuva_ou_vento_forte:
            for al in alertas_ativos:
                riscos_juntos = " ".join(al.get("riscos", []))
                instr_juntas = " ".join(al.get("instrucoes", []))
                paragrafos.append(
                    f"⚠️ AVISO METEOROLÓGICO ATIVO — {al['descricao'].upper()} ({al['severidade']}): "
                    f"Início: {al['inicio']} | Fim: {al['fim']}. Riscos: {riscos_juntos} {instr_juntas}"
                )
        elif aviso_informativo_pos_chuva:
            paragrafos.append(aviso_informativo_pos_chuva)

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
            "arquivo_a": nomes["arquivo_a"],
            "url_original": url_climatempo_niteroi,
        }

        (pasta_base / nomes["arquivo_r"]).write_text(gerar_html_resenha(dados_artigo), encoding="utf-8")
        (pasta_base / nomes["arquivo_n"]).write_text(gerar_html_noticia(dados_artigo), encoding="utf-8")
        arquivo_alerta_gerado = ""
        if alerta_principal_str:
            (pasta_base / nomes["arquivo_a"]).write_text(gerar_html_alerta(dados_artigo), encoding="utf-8")
            arquivo_alerta_gerado = nomes["arquivo_a"]
            print(f"  [!] Alerta [A] Efêmero gerado: {nomes['arquivo_a']}")
        print(f"  [+] Boletim Clima Niterói gerado: {nomes['arquivo_r']}")

        return {
            "carimbo_ts": carimbo_ts,
            "titulo": titulo,
            "fonte": "Climatempo & Defesa Civil • Niterói - RJ",
            "categoria_id": cat_cfg["id"],
            "categoria_rotulo": cat_cfg["rotulo"],
            "icone": cat_cfg["icone"],
            "cor": cat_cfg["cor"],
            "subtopico": "Niteroi",
            "tipo_artefato": "A" if arquivo_alerta_gerado else "R",
            "data_fato_formatada": dt_alocado.strftime("%d/%m/%Y às %Hh%M"),
            "resenha_texto": resenha_texto,
            "pontos_chave": pontos_chave,
            "alerta_defesa_civil": alerta_principal_str,
            "arquivo_r": nomes["arquivo_r"],
            "arquivo_n": nomes["arquivo_n"],
            "arquivo_a": arquivo_alerta_gerado,
            "url_original": url_climatempo_niteroi,
            "thumbnail_base64": b64_painel,
        }
    except Exception as exc:
        print(f"  [!] Aviso ao gerar boletim ao vivo de Niterói: {exc}")
        return None


def descobrir_xml_ou_raspar_capa(url_alvo: str) -> Tuple[Optional[ET.Element], List[Dict]]:
    """
    Aceita tanto uma URL de feed RSS quanto a URL direta da home de um portal
    (ex: https://mittechreview.com.br/ ou https://enfoco.com.br/).
    1. Se a resposta já for XML RSS/Atom, retorna o elemento raiz XML.
    2. Se for HTML de um portal, tenta descobrir o link <link rel="alternate" type="application/rss+xml">
       ou testar `url/feed/`.
    3. Caso o site não possua RSS, extrai diretamente as manchetes da primeira página HTML.
    """
    try:
        req = urllib.request.Request(url_alvo, headers=HEADERS_PADRAO)
        with urllib.request.urlopen(req, timeout=8) as resp:
            bruto = resp.read(450_000)
    except Exception:
        bruto = b""

    if bruto:
        try:
            return ET.fromstring(bruto), []
        except Exception:
            pass

    html_capa = bruto.decode("utf-8", errors="ignore") if bruto else ""
    # Tenta encontrar link de feed no HTML ou sufixo /feed/
    candidatos_feed: List[str] = []
    if html_capa:
        m_rss = re.search(
            r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
            html_capa,
            flags=re.IGNORECASE,
        )
        if m_rss:
            href_rss = html.unescape(m_rss.group(1).strip())
            if href_rss.startswith("/"):
                base_dom = re.match(r"^(https?://[^/]+)", url_alvo)
                if base_dom:
                    href_rss = base_dom.group(1) + href_rss
            if href_rss.startswith("http"):
                candidatos_feed.append(href_rss)

    if not url_alvo.rstrip("/").endswith("/feed") and "news.google.com" not in url_alvo:
        candidatos_feed.append(url_alvo.rstrip("/") + "/feed/")

    for cand in candidatos_feed:
        try:
            req_f = urllib.request.Request(cand, headers=HEADERS_PADRAO)
            with urllib.request.urlopen(req_f, timeout=7) as resp_f:
                return ET.fromstring(resp_f.read(450_000)), []
        except Exception:
            pass

    # Fallback: raspa manchetes diretamente do HTML da Primeira Página
    manchetes_capa: List[Dict] = []
    if html_capa:
        base_dom_m = re.match(r"^(https?://[^/]+)", url_alvo)
        dominio = base_dom_m.group(1) if base_dom_m else ""
        vistos = set()
        for m_a in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_capa, flags=re.DOTALL | re.IGNORECASE):
            href = html.unescape(m_a.group(1).strip())
            txt = limpar_tags_html(m_a.group(2))
            if len(txt) < 35 or len(txt) > 220:
                continue
            if href.startswith("/") and dominio:
                href = dominio + href
            if not href.startswith("http") or href in vistos:
                continue
            vistos.add(href)
            manchetes_capa.append({"titulo": txt, "link": href})
            if len(manchetes_capa) >= 12:
                break

    return None, manchetes_capa


def processar_feed_rss(
    fonte_cfg: Dict,
    cat_cfg: Dict,
    max_itens: int,
    urls_ja_processadas: Set[str],
    carimbos_usados: Set[str],
    pasta_base: Path,
    limite_corte: datetime,
    regras_crawler: Optional[Dict] = None,
) -> List[Dict]:
    """
    Lê uma fonte configurada (URL de portal ou RSS), aplica a Sazonalidade e o Filtro
    definidos no Configurador e gera os artefatos _R_, _N_ ou _A_.
    """
    novos_itens_catalogo: List[Dict] = []
    rss_url = (fonte_cfg.get("rss_url") or fonte_cfg.get("site_url") or "").strip()
    if not rss_url:
        return novos_itens_catalogo

    nome_fonte = fonte_cfg.get("nome", cat_cfg.get("rotulo", "Portal"))
    subtopico = fonte_cfg.get("subtopico", cat_cfg.get("subtopico_padrao", "Brasil"))
    sazonalidade = fonte_cfg.get("sazonalidade") or cat_cfg.get("sazonalidade") or "3d"
    filtro_modo = (fonte_cfg.get("filtro") or cat_cfg.get("filtro_padrao") or "todo_conteudo").lower()
    regras_busca_str = (fonte_cfg.get("regras_busca") or "").strip().lower()

    regras = regras_crawler or {}
    tam_min_titulo = int(regras.get("tamanho_minimo_titulo", 30))
    termos_esporte_bloqueados = tuple(
        t.lower()
        for t in regras.get(
            "palavras_bloqueadas",
            [
                "copa do brasil", "brasileirão", "libertadores", "champions league", "futebol",
                "onde assistir", "escalação", "flamengo", "fluminense", "botafogo", "vasco",
                "palmeiras", "corinthians", "são paulo fc", "atlético-mg", "grêmio", "cruzeiro",
                "rodada do", "campeonato brasileiro", "gol de", "gols de", "eliminatórias",
            ],
        )
    )

    # Ajusta limite de itens e corte temporal conforme o Filtro e a Sazonalidade da Fonte
    if filtro_modo == "primeira_pagina":
        limite_itens_fonte = max(2, min(max_itens, 4))
    elif filtro_modo == "todo_conteudo":
        limite_itens_fonte = max(max_itens, 5)
    else:
        limite_itens_fonte = max_itens

    td_saz = converter_sazonalidade_timedelta(sazonalidade, padrao_dias=3)
    eh_fonte_alerta = (
        filtro_modo == "apenas_alertas"
        or sazonalidade in ("1c", "ultimo_boletim")
        or "alerta" in subtopico.lower()
    )
    if eh_fonte_alerta:
        corte_efetivo = agora_brasilia() - timedelta(hours=2)
    elif td_saz is not None:
        corte_efetivo = agora_brasilia() - td_saz
    else:
        corte_efetivo = limite_corte

    root, manchetes_html = descobrir_xml_ou_raspar_capa(rss_url)
    if root is None and not manchetes_html:
        print(f"  [!] Aviso ao ler fonte '{nome_fonte}' ({rss_url})")
        return novos_itens_catalogo

    entradas_brutas: List[Dict] = []
    if root is not None:
        items_xml = root.findall(".//item")
        if not items_xml:
            items_xml = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for item in items_xml:
            titulo_el = item.find("title")
            if titulo_el is None:
                titulo_el = item.find("{http://www.w3.org/2005/Atom}title")
            t_txt = limpar_tags_html(titulo_el.text if titulo_el is not None and titulo_el.text else "")

            link_el = item.find("link")
            u_orig = ""
            if link_el is not None:
                u_orig = (link_el.text or link_el.attrib.get("href", "")).strip()

            pub_el = item.find("pubDate")
            if pub_el is None:
                pub_el = item.find("{http://purl.org/dc/elements/1.1/}date")
            if pub_el is None:
                pub_el = item.find("{http://www.w3.org/2005/Atom}published")
            p_txt = pub_el.text if pub_el is not None and pub_el.text else ""

            desc_el = item.find("description")
            if desc_el is None:
                desc_el = item.find("{http://www.w3.org/2005/Atom}summary")
            d_bruta = desc_el.text if desc_el is not None and desc_el.text else ""

            u_img = extrair_primeira_imagem_html(d_bruta)
            if not u_img:
                for elem in item.iter():
                    tag_local = elem.tag.split("}")[-1].lower()
                    if tag_local in ("content", "thumbnail", "enclosure"):
                        cand_img = elem.attrib.get("url", "")
                        if cand_img.startswith("http"):
                            u_img = cand_img
                            break
            entradas_brutas.append({
                "titulo": t_txt,
                "url": u_orig,
                "pub_str": p_txt,
                "desc_bruta": d_bruta,
                "url_img": u_img,
            })
    else:
        for mh in manchetes_html:
            entradas_brutas.append({
                "titulo": mh["titulo"],
                "url": mh["link"],
                "pub_str": "",
                "desc_bruta": "",
                "url_img": None,
            })

    contador = 0
    for ent in entradas_brutas:
        if contador >= limite_itens_fonte:
            break

        titulo = ent["titulo"]
        t_low = titulo.lower()
        if (
            not titulo
            or len(titulo) < tam_min_titulo
            or "previsão do tempo para " in t_low
            or any(termo in t_low for termo in termos_esporte_bloqueados)
        ):
            continue

        # Se a fonte tiver regras específicas de palavras-chave no Configurador, valida
        if regras_busca_str:
            termos_req = [x.strip() for x in regras_busca_str.split(",") if x.strip()]
            if termos_req and not any(tr in t_low for tr in termos_req):
                continue

        url_original = ent["url"]
        if url_original and url_original in urls_ja_processadas:
            continue

        dt_fato = converter_data_rss(ent["pub_str"])
        if dt_fato < corte_efetivo:
            continue

        desc_bruta = ent["desc_bruta"]
        descricao_limpa = limpar_tags_html(desc_bruta)
        url_img = ent["url_img"]

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
            "arquivo_a": nomes["arquivo_a"],
            "url_original": url_original,
        }

        if eh_fonte_alerta:
            # Artefato [A] - Alerta: grava apenas o arquivo _A_ (que será deletado no próximo ciclo de 15 min)
            html_a = gerar_html_alerta(dados_artigo)
            (pasta_base / nomes["arquivo_a"]).write_text(html_a, encoding="utf-8")
            novos_itens_catalogo.append(
                {
                    "carimbo_ts": carimbo_ts,
                    "titulo": titulo,
                    "fonte": nome_fonte,
                    "categoria_id": cat_cfg["id"],
                    "categoria_rotulo": cat_cfg["rotulo"],
                    "icone": "🚨",
                    "cor": "#ef4444",
                    "subtopico": subtopico,
                    "tipo_artefato": "A",
                    "data_fato_formatada": dt_alocado.strftime("%d/%m/%Y às %Hh%M"),
                    "resenha_texto": resenha_texto,
                    "pontos_chave": pontos_chave,
                    "arquivo_a": nomes["arquivo_a"],
                    "arquivo_r": nomes["arquivo_a"],
                    "arquivo_n": nomes["arquivo_a"],
                    "url_original": url_original,
                    "thumbnail_base64": b64_miniatura,
                }
            )
            print(f"  [!] Gerado Alerta Efêmero [A]: {nomes['arquivo_a']}")
        else:
            # Artefatos [R] e [N]: grava os 2 arquivos HTML autocontidos na Base de Conhecimento (retenção 3 dias)
            html_r = gerar_html_resenha(dados_artigo)
            html_n = gerar_html_noticia(dados_artigo)

            (pasta_base / nomes["arquivo_r"]).write_text(html_r, encoding="utf-8")
            (pasta_base / nomes["arquivo_n"]).write_text(html_n, encoding="utf-8")

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
                    "tipo_artefato": "RN",
                    "data_fato_formatada": dt_alocado.strftime("%d/%m/%Y às %Hh%M"),
                    "resenha_texto": resenha_texto,
                    "pontos_chave": pontos_chave,
                    "arquivo_r": nomes["arquivo_r"],
                    "arquivo_n": nomes["arquivo_n"],
                    "url_original": url_original,
                    "thumbnail_base64": b64_miniatura,
                }
            )
            print(f"  [+] Gerado par: {nomes['arquivo_r']} | {nomes['arquivo_n']}")

        if url_original:
            urls_ja_processadas.add(url_original)
        contador += 1

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

    dias_retencao = int(cfg.get("janela_retencao_dias", 7))
    regras_crawler = cfg.get("regras_crawler", {})
    max_por_fonte = int(regras_crawler.get("max_noticias_por_fonte", cfg.get("max_noticias_por_fonte", 4)))
    limite_corte = agora_brasilia() - timedelta(days=dias_retencao)
    lista_categorias = cfg.get("categorias", [])

    print("=================================================================")
    print("🎙️  FAVI NEWS CRAWLER — 'Em 15 minutos tudo pode mudar !!'")
    print("=================================================================")

    # 1. Expurga arquivos por sazonalidade configurada e deleta TODOS os alertas (_A_) e efêmeros do ciclo anterior
    expurgados = expurgar_arquivos_antigos(
        pasta_base, dias_retencao=dias_retencao, categorias_cfg=lista_categorias
    )
    alertas_deletados = expurgar_alertas_ciclo(pasta_base, categorias_cfg=lista_categorias)
    if expurgados:
        print(f"🧹 Expurgo por Sazonalidade: {len(expurgados)} arquivo(s) vencido(s) removido(s).")
    if alertas_deletados:
        print(f"🚨 Expurgo de Ciclo [A / Efêmeros]: {len(alertas_deletados)} arquivo(s) anterior(es) deletado(s).")

    # 1.1 Expurga arquivos de categorias que foram removidas do fontes.config.json
    categorias_ativas = {c["id"] for c in lista_categorias}
    cats_ultimo_boletim = {
        c["id"] for c in lista_categorias if c.get("sazonalidade") in ("1c", "ultimo_boletim", "ciclo", "15m")
    }
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

    # 2. Carrega catálogo existente (filtrando apenas categorias ativas e descartando alertas [A] do ciclo anterior)
    cat_atual = carregar_catalogo(pasta_base)
    itens_existentes: List[Dict] = [
        it
        for it in cat_atual.get("itens", [])
        if it.get("categoria_id") in categorias_ativas
        and it.get("tipo_artefato") != "A"
        and "alerta" not in str(it.get("subtopico", "")).lower()
    ]
    urls_ja_processadas: Set[str] = {
        it.get("url_original", "") for it in itens_existentes if it.get("url_original")
    }
    carimbos_usados: Set[str] = {
        it.get("carimbo_ts", "") for it in itens_existentes if it.get("carimbo_ts")
    }

    todos_novos: List[Dict] = []
    fontes_verificadas = 0
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
            boletim_nit = gerar_boletim_clima_niteroi(cat_cfg, carimbos_usados, pasta_base)
            if boletim_nit:
                # Deleta TODOS os itens anteriores de Clima para manter exclusivamente o último boletim atual
                for ant in list(itens_existentes):
                    if ant.get("categoria_id") == "Clima" or ant.get("categoria_id") in cats_ultimo_boletim:
                        for chave_arq in ("arquivo_r", "arquivo_n", "arquivo_a"):
                            nome_ant = ant.get(chave_arq, "")
                            if nome_ant:
                                caminho_ant = pasta_base / nome_ant
                                if caminho_ant.exists() and caminho_ant.name not in (
                                    boletim_nit.get("arquivo_r"),
                                    boletim_nit.get("arquivo_n"),
                                    boletim_nit.get("arquivo_a"),
                                ):
                                    try:
                                        caminho_ant.unlink()
                                    except OSError:
                                        pass
                        itens_existentes.remove(ant)
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
                regras_crawler=regras_crawler,
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

