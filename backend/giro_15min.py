"""
Executor Autônomo de 15 Minutos do FaviNews.
Roda um giro completo do Crawler (atualizando o `status_ciclo` no `catalogo_3dias.json`
mesmo quando não há novas páginas) e publica automaticamente no GitHub Pages.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from backend.crawler import executar_crawler
from backend.drive_service import agora_brasilia


def registrar_falha_sync_no_catalogo(msg_erro: str):
    """Registra eventual falha de sincronização no catalogo_3dias.json para exibir o ícone 🆘 no app."""
    arq_cat = RAIZ_PROJETO / "base_conhecimento" / "catalogo_3dias.json"
    if not arq_cat.exists():
        return
    try:
        dados = json.loads(arq_cat.read_text(encoding="utf-8"))
        sc = dados.setdefault("status_ciclo", {})
        sc["falha_sync"] = msg_erro
        sc["falha_sync_hora"] = agora_brasilia().strftime("%d/%m %H:%M:%S")
        arq_cat.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def limpar_rebase_travado():
    """Remove eventual estado de rebase travado e garante que estamos na branch main sincronizada."""
    git_dir = RAIZ_PROJETO / ".git"
    for pasta_trava in ("rebase-merge", "rebase-apply"):
        alvo = git_dir / pasta_trava
        if alvo.exists():
            shutil.rmtree(alvo, ignore_errors=True)
    subprocess.run(["git", "checkout", "-B", "main"], cwd=str(RAIZ_PROJETO), timeout=15)
    subprocess.run(["git", "fetch", "origin", "main"], cwd=str(RAIZ_PROJETO), timeout=25)


def executar_giro_e_publicar():
    try:
        limpar_rebase_travado()
    except Exception:
        pass

    resumo = executar_crawler()
    hora = agora_brasilia().strftime("%H:%M:%S")
    try:
        subprocess.run(["git", "add", "base_conhecimento/"], cwd=str(RAIZ_PROJETO), timeout=20)
        diff = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=str(RAIZ_PROJETO), timeout=10)
        if diff.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", f"chore(noticias): giro automatico 15min ({hora})"],
                cwd=str(RAIZ_PROJETO),
                timeout=20,
            )
            res_push = subprocess.run(
                ["git", "push", "origin", "HEAD:main", "HEAD:frontend", "HEAD:backend", "--force"],
                cwd=str(RAIZ_PROJETO),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res_push.returncode != 0:
                erro_git = (res_push.stderr or res_push.stdout or "Erro ao fazer git push").strip()[:180]
                registrar_falha_sync_no_catalogo(f"Falha no Git Push ({hora}): {erro_git}")
            else:
                print(f"☁️ Publicado no GitHub Pages com sucesso às {hora}!")
    except Exception as exc:
        print(f"[!] Aviso ao publicar no Git: {exc}")
        registrar_falha_sync_no_catalogo(f"Exceção no Sync ({hora}): {exc}")
    return resumo


if __name__ == "__main__":
    executar_giro_e_publicar()

