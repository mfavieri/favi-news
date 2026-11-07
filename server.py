"""
Servidor Local do FaviNews PWA ("Em 15 minutos tudo pode mudar !!").
Serve os arquivos estáticos do PWA e a pasta `base_conhecimento/`, além de
oferecer a rota POST `/api/atualizar-agora` para disparar um ciclo do Crawler
sob demanda pelo botão 🔄 da interface.
"""

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from backend.crawler import executar_crawler
from backend.drive_service import agora_brasilia, carregar_catalogo

PORTA_PADRAO = 8090
INTERVALO_SEGUNDOS = 15 * 60  # 15 minutos ("Em 15 minutos tudo pode mudar !!")
_lock_crawler = threading.Lock()


def sincronizar_git_background():
    """Envia o catalogo_3dias.json e novos HTMLs para o GitHub automaticamente após cada giro."""
    try:
        subprocess.run(["git", "add", "base_conhecimento/"], cwd=str(RAIZ_PROJETO), timeout=15)
        diff = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=str(RAIZ_PROJETO), timeout=10)
        if diff.returncode != 0:
            hora = agora_brasilia().strftime("%H:%M")
            subprocess.run(
                ["git", "commit", "-m", f"chore(noticias): giro automatico 15min ({hora})"],
                cwd=str(RAIZ_PROJETO),
                timeout=20,
            )
            subprocess.run(
                ["git", "push", "origin", "HEAD:main", "HEAD:frontend", "HEAD:backend"],
                cwd=str(RAIZ_PROJETO),
                timeout=45,
            )
            print(f"☁️ [Git Sync] Base sincronizada com GitHub Pages às {hora}!")
    except Exception as exc:
        print(f"[!] Aviso ao sincronizar Git: {exc}")


def rodar_crawler_seguro(origem: str = "agendador-15min") -> dict:
    """Executa o crawler com lock para evitar dois giros simultâneos."""
    if not _lock_crawler.acquire(blocking=False):
        return {"status": "ja_em_execucao"}
    try:
        print(f"\n⏱️ [{origem}] Disparando atualização FaviNews...")
        res = executar_crawler()
        threading.Thread(target=sincronizar_git_background, daemon=True).start()
        return res
    finally:
        _lock_crawler.release()


def loop_agendador_15min():
    """
    Thread em background que verifica se o catálogo tem mais de 15 minutos
    ao iniciar e depois executa o Crawler automaticamente a cada 15 minutos.
    """
    pasta_base = RAIZ_PROJETO / "base_conhecimento"
    while True:
        try:
            cat = carregar_catalogo(pasta_base)
            iso_str = cat.get("atualizado_iso", "")
            precisa_rodar = True
            if iso_str:
                dt_ult = datetime.fromisoformat(iso_str)
                segundos_passados = (agora_brasilia() - dt_ult).total_seconds()
                if segundos_passados < INTERVALO_SEGUNDOS:
                    precisa_rodar = False
                    espera = max(10, int(INTERVALO_SEGUNDOS - segundos_passados))
                    time.sleep(espera)
                    continue

            if precisa_rodar:
                rodar_crawler_seguro("auto-15min")
        except Exception as exc:
            print(f"[!] Aviso no agendador de 15 min: {exc}")

        time.sleep(30)


class FaviNewsRequestHandler(SimpleHTTPRequestHandler):
    """Handler HTTP que serve o PWA e permite disparar o Crawler via /api/atualizar-agora."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(RAIZ_PROJETO), **kwargs)

    def end_headers(self):
        # Evita cache agressivo do navegador durante o desenvolvimento/atualizações de 15 min
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def do_POST(self):
        if self.path.startswith("/api/atualizar-agora"):
            try:
                resumo = rodar_crawler_seguro("botao-manual")
                corpo = json.dumps({"ok": True, "resumo": resumo}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            except Exception as exc:
                erro = json.dumps({"ok": False, "erro": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(erro)))
                self.end_headers()
                self.wfile.write(erro)
        else:
            self.send_error(404, "Rota nao encontrada")


def iniciar_servidor(porta: int = PORTA_PADRAO):
    # Inicia a thread autônoma de 15 em 15 minutos em background
    t_cron = threading.Thread(target=loop_agendador_15min, daemon=True)
    t_cron.start()

    servidor = HTTPServer(("0.0.0.0", porta), FaviNewsRequestHandler)
    print("=================================================================")
    print(f"🚀 FaviNews PWA no ar em: http://localhost:{porta}")
    print("⏱️  Relógio Interno de 15 minutos: ATIVO")
    print("🎙️  Slogan: 'Em 15 minutos tudo pode mudar !!'")
    print("=================================================================")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor FaviNews...")
        servidor.server_close()


if __name__ == "__main__":
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else PORTA_PADRAO
    iniciar_servidor(porta)

