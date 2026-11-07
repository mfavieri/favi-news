"""
Servidor Local do FaviNews PWA ("Em 15 minutos tudo pode mudar !!").
Serve os arquivos estáticos do PWA e a pasta `base_conhecimento/`, além de
oferecer a rota POST `/api/atualizar-agora` para disparar um ciclo do Crawler
sob demanda pelo botão 🔄 da interface.
"""

import json
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from backend.crawler import executar_crawler

PORTA_PADRAO = 8090


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
                resumo = executar_crawler()
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
    servidor = HTTPServer(("0.0.0.0", porta), FaviNewsRequestHandler)
    print("=================================================================")
    print(f"🚀 FaviNews PWA no ar em: http://localhost:{porta}")
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

