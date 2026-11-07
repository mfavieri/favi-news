"""
Utilitário de Imagens em Bytecode (Base64) para o Favi News.
Responsável por baixar imagens das notícias, redimensioná-las/comprimi-las
para manter os arquivos HTML leves e retornar o Data URI (bytecode embutido).
Caso a matéria não possua imagem ou o download falhe, gera um banner SVG
em Base64 personalizado para a editoria.
"""

import base64
import io
import urllib.request
from typing import Optional

# Tenta importar Pillow para compressão e redimensionamento inteligente
try:
    from PIL import Image
    PILLOW_DISPONIVEL = True
except ImportError:
    PILLOW_DISPONIVEL = False


HEADERS_PADRAO = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def gerar_svg_placeholder_base64(categoria_rotulo: str, icone: str, cor_hex: str, eh_miniatura: bool = False) -> str:
    """
    Gera uma imagem vetorial SVG convertida em bytecode Base64 para notícias
    que não possuam foto na origem, mantendo 100% dos HTMLs ilustrados e offline.
    """
    largura = 400 if eh_miniatura else 800
    altura = 225 if eh_miniatura else 420
    tam_icone = 54 if eh_miniatura else 90
    tam_texto = 22 if eh_miniatura else 34

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" viewBox="0 0 {largura} {altura}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{cor_hex}" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#0f172a" stop-opacity="0.98"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#bg)" rx="12"/>
  <text x="50%" y="44%" dominant-baseline="middle" text-anchor="middle" font-size="{tam_icone}">{icone}</text>
  <text x="50%" y="72%" dominant-baseline="middle" text-anchor="middle" fill="#ffffff" font-family="system-ui, -apple-system, sans-serif" font-weight="700" font-size="{tam_texto}" letter-spacing="1">FAVI NEWS • {categoria_rotulo.upper()}</text>
</svg>"""
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def baixar_imagem_para_base64(
    url_imagem: Optional[str],
    largura_max: int = 720,
    qualidade_jpeg: int = 72,
    timeout: int = 6,
) -> Optional[str]:
    """
    Baixa uma imagem da internet, redimensiona (se Pillow estiver disponível)
    e retorna a string Data URI (data:image/jpeg;base64,...) pronta para
    ser embutida diretamente no atributo src="" do HTML.
    """
    if not url_imagem or not url_imagem.startswith(("http://", "https://")):
        return None

    try:
        req = urllib.request.Request(url_imagem, headers=HEADERS_PADRAO)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dados_brutos = resp.read()
            content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()

        if not dados_brutos or len(dados_brutos) < 256:
            return None

        # Se Pillow estiver instalado, comprime e redimensiona para economizar espaço no Drive
        if PILLOW_DISPONIVEL:
            try:
                with Image.open(io.BytesIO(dados_brutos)) as img:
                    if img.mode in ("RGBA", "P", "LA"):
                        fundo = Image.new("RGB", img.size, (15, 23, 42))
                        if img.mode == "P":
                            img = img.convert("RGBA")
                        fundo.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
                        img = fundo
                    elif img.mode != "RGB":
                        img = img.convert("RGB")

                    if img.width > largura_max:
                        proporcao = largura_max / float(img.width)
                        nova_altura = max(1, int(float(img.height) * proporcao))
                        img = img.resize((largura_max, nova_altura), Image.Resampling.LANCZOS)

                    buffer_saida = io.BytesIO()
                    img.save(buffer_saida, format="JPEG", quality=qualidade_jpeg, optimize=True)
                    b64 = base64.b64encode(buffer_saida.getvalue()).decode("ascii")
                    return f"data:image/jpeg;base64,{b64}"
            except Exception:
                # Fallback caso o formato não seja suportado pelo Pillow (ex: SVG/AVIF específico)
                pass

        # Fallback sem Pillow: codifica os bytes originais se não forem excessivamente grandes (< 600 KB)
        if len(dados_brutos) <= 600 * 1024:
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"
            b64 = base64.b64encode(dados_brutos).decode("ascii")
            return f"data:{content_type};base64,{b64}"

        return None
    except Exception:
        return None

