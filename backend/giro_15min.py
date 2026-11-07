"""
Executor Autônomo de 15 Minutos do FaviNews.
Roda um giro completo do Crawler (atualizando o `status_ciclo` no `catalogo_3dias.json`
mesmo quando não há novas páginas) e publica automaticamente no GitHub Pages.
"""

import subprocess
import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from backend.crawler import executar_crawler
from backend.drive_service import agora_brasilia


def executar_giro_e_publicar():
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
            subprocess.run(
                ["git", "push", "origin", "HEAD:main", "HEAD:frontend", "HEAD:backend"],
                cwd=str(RAIZ_PROJETO),
                timeout=60,
            )
            print(f"☁️ Publicado no GitHub Pages com sucesso às {hora}!")
    except Exception as exc:
        print(f"[!] Aviso ao publicar no Git: {exc}")
    return resumo


if __name__ == "__main__":
    executar_giro_e_publicar()

