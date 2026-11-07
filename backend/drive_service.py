"""
Serviço de Base de Conhecimento e Sincronização com Google Drive (Favi News).
Responsável por:
1. Gravar os arquivos padronizados (_R_ e _N_) na pasta `base_conhecimento`.
2. Executar o Garbage Collector (expurgo automático de arquivos > 3 dias / 72h)
   usando o próprio prefixo `YYYYMMDD-HHMMSS` do nome do arquivo.
3. Atualizar o índice `catalogo_3dias.json` para leitura instantânea Sem Login no PWA.
4. Sincronizar com a pasta do Google Drive (quando credenciais estiverem configuradas).
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Fuso horário oficial de Brasília / Rio de Janeiro (UTC-3)
FUSO_BRASILIA = timezone(timedelta(hours=-3))


def agora_brasilia() -> datetime:
    """Retorna o datetime atual sempre no fuso horário do Rio/Brasília (UTC-3), sem tzinfo."""
    return datetime.now(FUSO_BRASILIA).replace(tzinfo=None)


PADRAO_NOME_ARQUIVO = re.compile(
    r"^(\d{8}-\d{6})_([NRA])_([A-Za-z0-9]+)_([A-Za-z0-9]+)\.html$"
)


def extrair_metadados_do_nome(nome_arquivo: str) -> Optional[Dict[str, str]]:
    """
    Analisa um nome de arquivo no padrão do Favi:
      Ex: 20261107-081500_N_Politica_Brasil.html (Notícia - 3 dias)
          20261107-081500_R_Politica_Brasil.html (Resenha - 3 dias)
          20261107-081500_A_Clima_Niteroi.html   (Alerta  - 1 ciclo de 15 min)
    Retorna dicionário com timestamp, data_hora, tipo ('N', 'R' ou 'A'), categoria e subtopico.
    """
    m = PADRAO_NOME_ARQUIVO.match(nome_arquivo)
    if not m:
        return None
    carimbo_ts, tipo, categoria, subtopico = m.groups()
    try:
        dt = datetime.strptime(carimbo_ts, "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return {
        "nome_arquivo": nome_arquivo,
        "carimbo_ts": carimbo_ts,
        "datetime": dt,
        "tipo": tipo,
        "categoria": categoria,
        "subtopico": subtopico,
    }


def converter_sazonalidade_timedelta(sazonalidade_str: str, padrao_dias: int = 3) -> Optional[timedelta]:
    """
    Converte o código de sazonalidade do Configurador em timedelta:
      - 'ultimo_boletim' / 'ciclo' / '15m': None (efêmero de 1 ciclo — mantém apenas o último boletim)
      - '6h': 6 horas
      - '1d': 1 dia (24h)
      - '3d': 3 dias (72h)
      - '7d': 7 dias (168h)
    """
    s = (sazonalidade_str or "").strip().lower()
    if s in ("ultimo_boletim", "ciclo", "15m", "alerta"):
        return None
    if s == "6h":
        return timedelta(hours=6)
    if s in ("1d", "24h"):
        return timedelta(days=1)
    if s in ("3d", "72h"):
        return timedelta(days=3)
    if s in ("7d", "semana"):
        return timedelta(days=7)
    if s.endswith("d") and s[:-1].isdigit():
        return timedelta(days=int(s[:-1]))
    return timedelta(days=padrao_dias)


def expurgar_alertas_ciclo(pasta_base: Path, categorias_cfg: Optional[List[Dict]] = None) -> List[str]:
    """
    Deleta TODOS os arquivos de Alerta (`_A_`) do ciclo anterior e todos os arquivos de
    categorias com sazonalidade `ultimo_boletim` (como `Clima`, exceto o par de boletim reserva
    que é substituído pelo novo boletim).
    """
    removidos: List[str] = []
    if not pasta_base.exists():
        return removidos

    cats_efemeras = {"Clima"}
    if categorias_cfg:
        for c in categorias_cfg:
            if c.get("sazonalidade") in ("ultimo_boletim", "ciclo", "15m"):
                cats_efemeras.add(c.get("id", ""))

    for arq in pasta_base.glob("*.html"):
        info = extrair_metadados_do_nome(arq.name)
        if not info:
            continue
        # Deleta todo arquivo _A_, todo AlertaRJ, ou arquivos de Clima que não sejam o último boletim Niteroi
        if (
            info["tipo"] == "A"
            or info["subtopico"] == "AlertaRJ"
            or (info["categoria"] in cats_efemeras and info["subtopico"] != "Niteroi")
        ):
            try:
                arq.unlink()
                removidos.append(arq.name)
            except OSError:
                pass

    return removidos


def expurgar_arquivos_antigos(
    pasta_base: Path,
    dias_retencao: int = 3,
    agora: Optional[datetime] = None,
    categorias_cfg: Optional[List[Dict]] = None,
) -> List[str]:
    """
    Remove da Base de Conhecimento qualquer arquivo HTML cujo timestamp no nome
    (`YYYYMMDD-HHMMSS`) tenha ultrapassado a Sazonalidade configurada da sua Aba/Fonte
    (ex: 7 dias para Ciências, 1 dia para Niterói/Trânsito, 3 dias para Geral).
    """
    if agora is None:
        agora = agora_brasilia()
    removidos: List[str] = []

    if not pasta_base.exists():
        return removidos

    mapa_sazonalidade_cat: Dict[str, Optional[timedelta]] = {}
    if categorias_cfg:
        for c in categorias_cfg:
            cid = c.get("id", "")
            mapa_sazonalidade_cat[cid] = converter_sazonalidade_timedelta(
                c.get("sazonalidade", f"{dias_retencao}d"), padrao_dias=dias_retencao
            )

    for arq in pasta_base.glob("*.html"):
        info = extrair_metadados_do_nome(arq.name)
        if not info:
            continue
        td_cat = mapa_sazonalidade_cat.get(info["categoria"], timedelta(days=dias_retencao))
        if td_cat is None:
            # Categoria efêmera (ultimo_boletim): se tiver mais de 1 hora e não foi substituído, expurga
            limite_corte = agora - timedelta(hours=2)
        else:
            limite_corte = agora - td_cat

        if info["datetime"] < limite_corte:
            try:
                arq.unlink()
                removidos.append(arq.name)
            except OSError:
                pass

    return removidos


def carregar_catalogo(pasta_base: Path) -> Dict:
    """Carrega o catálogo atual de 3 dias ou retorna estrutura vazia."""
    caminho_cat = pasta_base / "catalogo_3dias.json"
    if caminho_cat.exists():
        try:
            with open(caminho_cat, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "atualizado_em": "",
        "janela_dias": 3,
        "total_itens": 0,
        "itens": [],
    }


def salvar_catalogo(
    pasta_base: Path,
    itens_novos_ou_atuais: List[Dict],
    dias_retencao: int = 3,
    info_ciclo: Optional[Dict] = None,
) -> Dict:
    """
    Filtra apenas os itens dentro da janela de 3 dias cujo arquivo _R_ exista na pasta,
    ordena do mais recente para o mais antigo e salva o `catalogo_3dias.json`
    incluindo o status detalhado do giro de 15 minutos (mesmo quando há 0 novas páginas).
    """
    pasta_base.mkdir(parents=True, exist_ok=True)
    agora = agora_brasilia()
    proximo = agora + timedelta(minutes=15)
    limite_corte = agora - timedelta(days=dias_retencao)

    por_carimbo: Dict[str, Dict] = {}
    for item in itens_novos_ou_atuais:
        ts = item.get("carimbo_ts", "")
        arq_principal = item.get("arquivo_a") or item.get("arquivo_r", "")
        if not ts or not arq_principal:
            continue
        try:
            dt = datetime.strptime(ts, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        if dt < limite_corte:
            continue
        if (pasta_base / arq_principal).exists():
            por_carimbo[ts] = item

    itens_ordenados = sorted(
        por_carimbo.values(),
        key=lambda x: x.get("carimbo_ts", ""),
        reverse=True,
    )

    novas_qtd = int((info_ciclo or {}).get("novas_paginas", 0))
    fontes_lidas = int((info_ciclo or {}).get("fontes_verificadas", 0))
    expurgados_qtd = int((info_ciclo or {}).get("expurgados", 0))
    hora_curta = agora.strftime("%H:%M")
    prox_curta = proximo.strftime("%H:%M")

    if novas_qtd > 0:
        detalhe_novas = f"+{novas_qtd} nova(s) página(s) coletada(s)"
    else:
        detalhe_novas = f"sem novas páginas ({fontes_lidas} fontes varridas)"

    msg_status = f"Giro {hora_curta} OK • {detalhe_novas} • Próximo às {prox_curta}"

    catalogo = {
        "atualizado_em": agora.strftime("%d/%m/%Y %H:%M:%S"),
        "atualizado_iso": agora.isoformat(),
        "proximo_giro_em": proximo.strftime("%d/%m/%Y %H:%M:%S"),
        "proximo_giro_iso": proximo.isoformat(),
        "janela_dias": dias_retencao,
        "total_itens": len(itens_ordenados),
        "status_ciclo": {
            "estado": "concluido",
            "verificado_em": agora.strftime("%d/%m/%Y %H:%M:%S"),
            "hora_curta": hora_curta,
            "proximo_giro": prox_curta,
            "novas_paginas": novas_qtd,
            "fontes_verificadas": fontes_lidas,
            "expurgados_ciclo": expurgados_qtd,
            "total_ativas_3dias": len(itens_ordenados),
            "mensagem": msg_status,
        },
        "itens": itens_ordenados,
    }

    caminho_cat = pasta_base / "catalogo_3dias.json"
    with open(caminho_cat, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)

    return catalogo


def sincronizar_google_drive(pasta_base: Path, folder_id: str, dias_retencao: int = 3) -> Dict[str, int]:
    """
    Sincroniza a pasta local `base_conhecimento` com a pasta do Google Drive
    usando credencial de Service Account (`GOOGLE_SERVICE_ACCOUNT_JSON`) no GitHub Actions.
    Se a variável não estiver definida, opera em modo Local / GitHub Pages transparente.
    """
    cred_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    folder_id_env = os.environ.get("GDRIVE_FOLDER_ID", folder_id).strip()

    resultado = {"enviados": 0, "expurgados_drive": 0, "modo": "local_e_static"}
    if not cred_json or not folder_id_env or folder_id_env.startswith("COLE_AQUI"):
        return resultado

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        info_cred = json.loads(cred_json)
        creds = service_account.Credentials.from_service_account_info(
            info_cred, scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build("drive", "v3", credentials=creds)

        # Lista arquivos existentes na pasta do Drive
        resp = (
            service.files()
            .list(
                q=f"'{folder_id_env}' in parents and trashed = false",
                fields="files(id, name)",
                pageSize=1000,
            )
            .execute()
        )
        arquivos_drive = {f["name"]: f["id"] for f in resp.get("files", [])}

        # 1. Expurga do Drive arquivos HTML com mais de 3 dias OU alertas (_A_) já removidos localmente
        limite_corte = agora_brasilia() - timedelta(days=dias_retencao)
        for nome_arq, file_id in list(arquivos_drive.items()):
            meta = extrair_metadados_do_nome(nome_arq)
            if meta and (meta["datetime"] < limite_corte or (meta["tipo"] == "A" and not (pasta_base / nome_arq).exists())):
                service.files().delete(fileId=file_id).execute()
                del arquivos_drive[nome_arq]
                resultado["expurgados_drive"] += 1

        # 2. Envia arquivos HTML novos que ainda não estão no Drive
        for arq_local in pasta_base.glob("*.html"):
            if arq_local.name not in arquivos_drive:
                media = MediaFileUpload(str(arq_local), mimetype="text/html", resumable=False)
                service.files().create(
                    body={"name": arq_local.name, "parents": [folder_id_env]},
                    media_body=media,
                    fields="id",
                ).execute()
                resultado["enviados"] += 1

        # 3. Atualiza o catalogo_3dias.json no Drive
        cat_path = pasta_base / "catalogo_3dias.json"
        if cat_path.exists():
            media_cat = MediaFileUpload(str(cat_path), mimetype="application/json", resumable=False)
            if "catalogo_3dias.json" in arquivos_drive:
                service.files().update(
                    fileId=arquivos_drive["catalogo_3dias.json"],
                    media_body=media_cat,
                ).execute()
            else:
                service.files().create(
                    body={"name": "catalogo_3dias.json", "parents": [folder_id_env]},
                    media_body=media_cat,
                    fields="id",
                ).execute()

        resultado["modo"] = "google_drive_ativo"
    except Exception as exc:
        resultado["modo"] = f"aviso_drive: {exc}"

    return resultado

