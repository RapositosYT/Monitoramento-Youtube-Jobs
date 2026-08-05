import datetime
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa  # noqa: E402

# alguns CDNs (ex: minecraft.net, atras de Cloudflare) bloqueiam por
# header -- um user-agent de navegador de verdade passa, um UA "bot"
# generico trava a coleta com timeout silencioso
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT_S = 20
TIMEOUT_OG_IMAGE_S = 10
# quantos bytes da pagina de destino ler procurando <meta og:image> -- a tag
# fica no <head>, nao precisa baixar a pagina inteira
LEITURA_OG_IMAGE_BYTES = 200_000
# noticia mais antiga que isso nao entra no banco -- alguns feeds devolvem o
# historico inteiro no 1o request; sem esse corte a 1a rodada importaria
# anos de posts de uma vez
DIAS_MAX_NOTICIA = 20
# limpa noticias mais velhas que isso pra tabela nao crescer sem limite
DIAS_RETENCAO = 60
# respiro entre fontes + retry com backoff pra 429 -- nenhuma fonte atual
# rate-limita normalmente, mas nao custa manter a defesa (Cloudflare/
# Discourse podem reagir mal a rajada de requests)
PAUSA_ENTRE_FONTES_S = 4
RETRY_429_TENTATIVAS = 3
RETRY_429_ESPERA_BASE_S = 8

# Reddit foi removido -- na pratica o top do dia trazia muito mais fofoca/
# papo de usuario do que noticia de verdade sobre o nicho, dificil de filtrar
# automaticamente. Roblox ganha o Developer Forum oficial (release notes de
# verdade) no lugar do r/roblox.
FONTES = [
    {"fonte": "YouTube (blog oficial)", "categoria": "youtube",
     "url": "https://blog.youtube/rss/"},
    {"fonte": "Minecraft (oficial)", "categoria": "minecraft",
     "url": "https://www.minecraft.net/en-us/feeds/community-content/rss"},
    {"fonte": "Roblox Developer Forum", "categoria": "roblox",
     "url": "https://devforum.roblox.com/c/updates/announcements/62.rss"},
]

NS_ATOM = "{http://www.w3.org/2005/Atom}"

RE_OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE
)
RE_OG_IMAGE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.IGNORECASE
)
# imagem embutida no HTML da propria descricao do item (ex: Developer Forum
# da Roblox, que usa Discourse e cita a imagem de preview do link no corpo)
RE_IMG_TAG = re.compile(r'<img[^>]+src=["\']([^"\']+)', re.IGNORECASE)


def _normalizar_url_imagem(url):
    if not url:
        return None
    # algumas fontes devolvem URL relativa a protocolo ("//dominio/img.jpg")
    return f"https:{url}" if url.startswith("//") else url


def _buscar_xml(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for tentativa in range(1, RETRY_429_TENTATIVAS + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                corpo = resp.read()
            return ET.fromstring(corpo)
        except urllib.error.HTTPError as e:
            if e.code != 429 or tentativa == RETRY_429_TENTATIVAS:
                raise
            espera = RETRY_429_ESPERA_BASE_S * tentativa
            print(f"  429 recebido, tentativa {tentativa}/{RETRY_429_TENTATIVAS} -- esperando {espera}s")
            time.sleep(espera)


# YouTube/Minecraft nao trazem imagem no proprio feed -- busca o <meta
# og:image> direto na pagina de destino (so' os primeiros bytes, a tag fica
# no <head>). Falha aqui nunca derruba o job, so' fica sem imagem.
def _buscar_og_image(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT_OG_IMAGE_S) as resp:
            html = resp.read(LEITURA_OG_IMAGE_BYTES).decode("utf-8", errors="ignore")
        m = RE_OG_IMAGE.search(html) or RE_OG_IMAGE_ALT.search(html)
        return _normalizar_url_imagem(m.group(1)) if m else None
    except Exception:
        return None


def _parsear_data(texto):
    if not texto:
        return None
    formatos = (
        "%a, %d %b %Y %H:%M:%S %z",     # RSS2 (RFC 822): "Mon, 02 Jan 2006 15:04:05 -0700"
        "%Y-%m-%dT%H:%M:%S%z",           # Atom (ISO 8601)
        "%Y-%m-%dT%H:%M:%S.%f%z",        # Atom com fracao de segundo (feeds do Blogger)
    )
    texto_norm = texto.strip().replace("Z", "+00:00")
    for fmt in formatos:
        try:
            return datetime.datetime.strptime(texto_norm, fmt)
        except ValueError:
            continue
    return None


def _itens_rss2(raiz):
    itens = []
    for item in raiz.findall(".//item"):
        titulo = (item.findtext("title") or "").strip()
        # RSS2 "puro" usa <link>texto</link>; alguns feeds (ex: minecraft.net)
        # so tem um <a10:link href="..."/> no estilo Atom dentro do item
        link = (item.findtext("link") or "").strip()
        if not link:
            link_el = item.find(f"{NS_ATOM}link")
            if link_el is not None:
                link = (link_el.get("href") or "").strip()
        publicado = _parsear_data(item.findtext("pubDate"))
        descricao = item.findtext("description") or ""
        m = RE_IMG_TAG.search(descricao)
        imagem = _normalizar_url_imagem(m.group(1)) if m else None
        if titulo and link:
            itens.append((titulo, link, publicado, imagem))
    return itens


def _itens_atom(raiz):
    itens = []
    for entry in raiz.findall(f".//{NS_ATOM}entry"):
        titulo = (entry.findtext(f"{NS_ATOM}title") or "").strip()
        link_el = entry.find(f"{NS_ATOM}link[@rel='alternate']") or entry.find(f"{NS_ATOM}link")
        link = link_el.get("href", "").strip() if link_el is not None else ""
        publicado = _parsear_data(entry.findtext(f"{NS_ATOM}published") or entry.findtext(f"{NS_ATOM}updated"))
        if titulo and link:
            itens.append((titulo, link, publicado, None))
    return itens


def _coletar_fonte(fonte, imagens_conhecidas):
    try:
        raiz = _buscar_xml(fonte["url"])
    except Exception as e:
        print(f"[{fonte['fonte']}] falha ao buscar/parsear feed: {e}")
        return []

    itens = _itens_rss2(raiz) if raiz.tag == "rss" else _itens_atom(raiz)
    limite = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DIAS_MAX_NOTICIA)

    linhas = []
    for titulo, link, publicado, imagem_descricao in itens:
        if publicado is not None and publicado < limite:
            continue
        # ja tem imagem salva de uma coleta anterior? nao busca de novo
        imagem = imagens_conhecidas.get(link)
        if not imagem:
            # og:image da pagina de destino tende a ser a imagem de capa de
            # verdade (screenshot/thumbnail); a imagem embutida na descricao
            # do item as vezes eh so um icone pequeno sem relacao com o post
            # (ex: emoji/logo citado no corpo do texto do Developer Forum)
            imagem = _buscar_og_image(link) or imagem_descricao
        linhas.append({
            "fonte": fonte["fonte"],
            "categoria": fonte["categoria"],
            "titulo": titulo,
            "link": link,
            "imagem_url": imagem,
            "publicado_em": publicado.isoformat() if publicado else None,
        })
    return linhas


def main():
    imagens_conhecidas = {
        n["link"]: n["imagem_url"]
        for n in supa.get("noticias", "link,imagem_url")
        if n.get("imagem_url")
    }

    todas = []
    for i, fonte in enumerate(FONTES):
        if i > 0:
            time.sleep(PAUSA_ENTRE_FONTES_S)
        linhas = _coletar_fonte(fonte, imagens_conhecidas)
        com_imagem = sum(1 for l in linhas if l["imagem_url"])
        print(f"[{fonte['fonte']}] {len(linhas)} noticias dentro da janela de {DIAS_MAX_NOTICIA} dias "
              f"({com_imagem} com imagem).")
        todas.extend(linhas)

    if todas:
        supa.upsert("noticias", todas, on_conflict="link")

    limite_retencao = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DIAS_RETENCAO)
    supa.delete("noticias", [("lt", "criado_em", limite_retencao.isoformat())])

    print(f"Total coletado: {len(todas)} noticias de {len(FONTES)} fontes.")


if __name__ == "__main__":
    main()
