"""
Servidor Local do FaviNews PWA ("Em 15 minutos tudo pode mudar !!").
Serve os arquivos estáticos do PWA e a pasta `base_conhecimento/`, além de
oferecer a rota POST `/api/atualizar-agora` para disparar um ciclo do Crawler
sob demanda pelo botão 🔄 da interface.
"""

import json
import os
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


def sincronizar_ao_iniciar_pc():
    """
    Executa a sincronização única no momento em que a aplicação entra no ar no PC.
    Puxa do GitHub as últimas novidades e executa uma rodada inicial para garantir
    que a base local e o catálogo estejam 100% frescos.
    O PC NÃO fica em loop de 15 minutos em background (responsabilidade da nuvem).
    """
    try:
        print("\n🚀 [FaviNews PC] Aplicação entrando no ar! Sincronizando com o GitHub...")
        subprocess.run(["git", "pull", "--rebase", "-X", "theirs", "origin", "main"], cwd=str(RAIZ_PROJETO), timeout=25)
    except Exception as exc:
        print(f"[!] Aviso ao puxar do GitHub: {exc}")

    # Giro inicial único ao subir o servidor
    rodar_crawler_seguro("inicializacao-ao-entrar-no-ar")
    print("✅ [FaviNews PC] Sincronização inicial concluída! Servidor pronto (loop de 15 min desativado no PC).\n")


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
        elif self.path.startswith("/api/salvar-config"):
            try:
                tam = int(self.headers.get("Content-Length", "0"))
                bruto = self.rfile.read(tam).decode("utf-8")
                payload = json.loads(bruto)

                nova_cfg = payload.get("config")
                if not isinstance(nova_cfg, dict) or "categorias" not in nova_cfg:
                    raise ValueError("Estrutura de configuração inválida.")

                agora = agora_brasilia()
                nova_cfg["atualizado_iso"] = agora.isoformat()
                nova_cfg["atualizado_em"] = agora.strftime("%d/%m/%Y às %Hh%M")

                caminho_cfg = RAIZ_PROJETO / "config" / "fontes.config.json"
                with open(caminho_cfg, "w", encoding="utf-8") as f:
                    json.dump(nova_cfg, f, ensure_ascii=False, indent=2)

                def _push_cfg_e_rodar():
                    try:
                        subprocess.run(["git", "add", "config/fontes.config.json"], cwd=str(RAIZ_PROJETO), timeout=15)
                        subprocess.run(
                            ["git", "commit", "-m", "chore(config): atualiza regras pelo Configurador PC FaviNews"],
                            cwd=str(RAIZ_PROJETO),
                            timeout=15,
                        )
                        subprocess.run(
                            ["git", "push", "origin", "HEAD:main", "HEAD:frontend", "HEAD:backend", "--force"],
                            cwd=str(RAIZ_PROJETO),
                            timeout=45,
                        )
                    except Exception:
                        pass
                    if payload.get("rodar_crawler", True):
                        rodar_crawler_seguro("configurador-pc")

                threading.Thread(target=_push_cfg_e_rodar, daemon=True).start()

                resp_ok = json.dumps(
                    {"ok": True, "mensagem": "Configuração salva no JSON, enviada ao GitHub e giro iniciado!"},
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp_ok)))
                self.end_headers()
                self.wfile.write(resp_ok)
            except Exception as exc:
                erro = json.dumps({"ok": False, "erro": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(erro)))
                self.end_headers()
                self.wfile.write(erro)
        else:
            self.send_error(404, "Rota nao encontrada")


def liberar_porta_windows(porta: int):
    """Encerra eventual processo anterior do servidor que tenha ficado preso na mesma porta."""
    meu_pid = os.getpid()
    try:
        saida = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL)
        for linha in saida.splitlines():
            if f":{porta} " in linha and "LISTENING" in linha:
                partes = linha.split()
                pid_antigo = int(partes[-1])
                if pid_antigo != meu_pid and pid_antigo > 0:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid_antigo)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    time.sleep(0.4)
    except Exception:
        pass


def iniciar_servidor(porta: int = PORTA_PADRAO):
    liberar_porta_windows(porta)
    # Sincronização única no momento em que a aplicação entra no ar (não roda a cada 15 min no PC)
    t_inicio = threading.Thread(target=sincronizar_ao_iniciar_pc, daemon=True)
    t_inicio.start()

    servidor = HTTPServer(("0.0.0.0", porta), FaviNewsRequestHandler)
    print("=================================================================")
    print(f"🚀 FaviNews PWA no ar em: http://localhost:{porta}")
    print("⚡ Sincronização PC: ÚNICA AO ENTRAR NO AR (Loop de 15 min desativado no PC)")
    print("🎙️ Slogan: 'Em 15 minutos tudo pode mudar !!'")
    print("=================================================================")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor FaviNews...")
        servidor.server_close()


if __name__ == "__main__":
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else PORTA_PADRAO
    iniciar_servidor(porta)

