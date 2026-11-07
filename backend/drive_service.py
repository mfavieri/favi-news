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
    r"^(\d{8}-\d{6})_([NR])_([A-Za-z0-9]+)_([A-Za-z0-9]+)\.html$"
)


def extrair_metadados_do_nome(nome_arquivo: str) -> Optional[Dict[str, str]]:
    """
    Analisa um nome de arquivo no padrão do Favi:
      Ex: 20261107-081500_N_Politica_Brasil.html
    Retorna dicionário com timestamp, data_hora, tipo ('N' ou 'R'), categoria e subtopico.
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


def expurgar_arquivos_antigos(pasta_base: Path, dias_retencao: int = 3, agora: Optional[datetime] = None) -> List[str]:
    """
    Remove da Base de Conhecimento qualquer arquivo HTML cujo timestamp no nome
    (`YYYYMMDD-HHMMSS`) seja anterior à janela de retenção (padrão: 3 dias / 72 horas).
    """
    if agora is None:
        agora = agora_brasilia()
    limite_corte = agora - timedelta(days=dias_retencao)
    removidos: List[str] = []

    if not pasta_base.exists():
        return removidos

    for arq in pasta_base.glob("*.html"):
        info = extrair_metadados_do_nome(arq.name)
        if not info:
            continue
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


def salvar_catalogo(pasta_base: Path, itens_novos_ou_atuais: List[Dict], dias_retencao: int = 3) -> Dict:
    """
    Filtra apenas os itens dentro da janela de 3 dias cujo arquivo _R_ exista na pasta,
    ordena do mais recente para o mais antigo e salva o `catalogo_3dias.json`.
    """
    pasta_base.mkdir(parents=True, exist_ok=True)
    agora = agora_brasilia()
    limite_corte = agora - timedelta(days=dias_retencao)

    por_carimbo: Dict[str, Dict] = {}
    for item in itens_novos_ou_atuais:
        ts = item.get("carimbo_ts", "")
        arq_r = item.get("arquivo_r", "")
        if not ts or not arq_r:
            continue
        try:
            dt = datetime.strptime(ts, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        if dt < limite_corte:
            continue
        if (pasta_base / arq_r).exists():
            por_carimbo[ts] = item

    itens_ordenados = sorted(
        por_carimbo.values(),
        key=lambda x: x.get("carimbo_ts", ""),
        reverse=True,
    )

    catalogo = {
        "atualizado_em": agora.strftime("%d/%m/%Y %H:%M:%S"),
        "atualizado_iso": agora.isoformat(),
        "janela_dias": dias_retencao,
        "total_itens": len(itens_ordenados),
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

        # 1. Expurga do Drive arquivos HTML com mais de 3 dias
        limite_corte = agora_brasilia() - timedelta(days=dias_retencao)
        for nome_arq, file_id in list(arquivos_drive.items()):
            meta = extrair_metadados_do_nome(nome_arq)
            if meta and meta["datetime"] < limite_corte:
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

