import datetime
import pathlib
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
# noticia mais antiga que isso nao entra no banco -- feeds tipo reddit
# trazem "top do dia", mas alguns blogs devolvem o historico inteiro no 1o
# request; sem esse corte a 1a rodada importaria anos de posts de uma vez
DIAS_MAX_NOTICIA = 20
# limpa noticias mais velhas que isso pra tabela nao crescer sem limite
DIAS_RETENCAO = 60
# reddit rate-limita requests em sequencia rapida (429), inclusive de IPs de
# datacenter tipo GitHub Actions -- respiro entre fontes + retry com backoff
# especifico pra 429 (as outras fontes raramente precisam, mas nao custa)
PAUSA_ENTRE_FONTES_S = 4
RETRY_429_TENTATIVAS = 3
RETRY_429_ESPERA_BASE_S = 8

FONTES = [
    {"fonte": "YouTube (blog oficial)", "categoria": "youtube",
     "url": "https://blog.youtube/rss/"},
    {"fonte": "Minecraft (oficial)", "categoria": "minecraft",
     "url": "https://www.minecraft.net/en-us/feeds/community-content/rss"},
    {"fonte": "Reddit r/Minecraft", "categoria": "minecraft",
     "url": "https://www.reddit.com/r/Minecraft/top/.rss?t=day"},
    {"fonte": "Reddit r/roblox", "categoria": "roblox",
     "url": "https://www.reddit.com/r/roblox/top/.rss?t=day"},
]

NS_ATOM = "{http://www.w3.org/2005/Atom}"


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
        if titulo and link:
            itens.append((titulo, link, publicado))
    return itens


def _itens_atom(raiz):
    itens = []
    for entry in raiz.findall(f".//{NS_ATOM}entry"):
        titulo = (entry.findtext(f"{NS_ATOM}title") or "").strip()
        link_el = entry.find(f"{NS_ATOM}link[@rel='alternate']") or entry.find(f"{NS_ATOM}link")
        link = link_el.get("href", "").strip() if link_el is not None else ""
        publicado = _parsear_data(entry.findtext(f"{NS_ATOM}published") or entry.findtext(f"{NS_ATOM}updated"))
        if titulo and link:
            itens.append((titulo, link, publicado))
    return itens


def _coletar_fonte(fonte):
    try:
        raiz = _buscar_xml(fonte["url"])
    except Exception as e:
        print(f"[{fonte['fonte']}] falha ao buscar/parsear feed: {e}")
        return []

    itens = _itens_rss2(raiz) if raiz.tag == "rss" else _itens_atom(raiz)
    limite = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DIAS_MAX_NOTICIA)

    linhas = []
    for titulo, link, publicado in itens:
        if publicado is not None and publicado < limite:
            continue
        linhas.append({
            "fonte": fonte["fonte"],
            "categoria": fonte["categoria"],
            "titulo": titulo,
            "link": link,
            "publicado_em": publicado.isoformat() if publicado else None,
        })
    return linhas


def main():
    todas = []
    for i, fonte in enumerate(FONTES):
        if i > 0:
            time.sleep(PAUSA_ENTRE_FONTES_S)
        linhas = _coletar_fonte(fonte)
        print(f"[{fonte['fonte']}] {len(linhas)} noticias dentro da janela de {DIAS_MAX_NOTICIA} dias.")
        todas.extend(linhas)

    if todas:
        supa.upsert("noticias", todas, on_conflict="link")

    limite_retencao = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DIAS_RETENCAO)
    supa.delete("noticias", [("lt", "criado_em", limite_retencao.isoformat())])

    print(f"Total coletado: {len(todas)} noticias de {len(FONTES)} fontes.")


if __name__ == "__main__":
    main()
