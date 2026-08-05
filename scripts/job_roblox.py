import datetime
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid
from json import loads

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa  # noqa: E402

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}
TIMEOUT_S = 20
PAUSA_ENTRE_SORTS_S = 3
# 14 dias da pra sobra pra qualquer analise de tendencia por enquanto (hoje so'
# comparamos com a rodada anterior); sem isso a tabela cresce pra sempre, ja
# que roda varias vezes ao dia.
DIAS_RETENCAO = 14

# as 3 prateleiras genericas do Discover (nao dependem de historico/amigos do
# usuario, sao as mesmas pra qualquer visitante) -- as outras 2 que a API
# retorna (fun-with-friends, top-revisited) sao pessoais e ficam de fora
SORT_IDS = ["top-trending", "up-and-coming", "top-playing-now"]

LOTE_THUMBS = 100


def _get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return loads(resp.read())


def _coletar_sort(session_id, sort_id):
    url = (f"https://apis.roblox.com/explore-api/v1/get-sort-content"
           f"?sessionId={session_id}&sortId={sort_id}&device=computer&country=us")
    try:
        dados = _get_json(url)
    except Exception as e:
        print(f"[{sort_id}] falha ao buscar: {e}")
        return []
    jogos = dados.get("games", [])
    print(f"[{sort_id}] {len(jogos)} jogos.")
    return jogos


def _buscar_icones(universe_ids):
    icones = {}
    for i in range(0, len(universe_ids), LOTE_THUMBS):
        lote = universe_ids[i:i + LOTE_THUMBS]
        ids_str = ",".join(str(u) for u in lote)
        url = (f"https://thumbnails.roblox.com/v1/games/icons?universeIds={ids_str}"
               f"&size=150x150&format=Png")
        try:
            dados = _get_json(url)
        except Exception as e:
            print(f"falha ao buscar icones: {e}")
            continue
        for item in dados.get("data", []):
            if item.get("state") == "Completed" and item.get("imageUrl"):
                icones[item["targetId"]] = item["imageUrl"]
    return icones


def main():
    session_id = str(uuid.uuid4())

    por_sort = {}
    for i, sort_id in enumerate(SORT_IDS):
        if i > 0:
            time.sleep(PAUSA_ENTRE_SORTS_S)
        por_sort[sort_id] = _coletar_sort(session_id, sort_id)

    todos_jogos = {}
    for jogos in por_sort.values():
        for g in jogos:
            todos_jogos[g["universeId"]] = g

    if not todos_jogos:
        print("Nenhum jogo coletado, encerrando.")
        return

    icones = _buscar_icones(list(todos_jogos.keys()))
    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()

    catalogo = [{
        "universe_id": g["universeId"],
        "root_place_id": g.get("rootPlaceId"),
        "nome": g.get("name"),
        "genero": g.get("genreL1"),
        "icone_url": icones.get(g["universeId"]),
        "atualizado_em": agora,
    } for g in todos_jogos.values()]
    supa.upsert("roblox_jogos", catalogo, on_conflict="universe_id")

    snapshots = []
    for sort_id, jogos in por_sort.items():
        for posicao, g in enumerate(jogos):
            snapshots.append({
                "universe_id": g["universeId"],
                "sort_id": sort_id,
                "posicao": posicao,
                "jogadores": g.get("playerCount"),
                "upvotes": g.get("totalUpVotes"),
                "downvotes": g.get("totalDownVotes"),
            })
    supa.insert("roblox_snapshots", snapshots)

    limite_retencao = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DIAS_RETENCAO)
    supa.delete("roblox_snapshots", [("lt", "coletado_em", limite_retencao.isoformat())])

    # jogo que sumiu de todas as prateleiras ha mais de DIAS_RETENCAO dias:
    # atualizado_em so' e' tocado quando o jogo aparece de novo num upsert,
    # entao ficar parado por tanto tempo significa que ja nao sobrou nenhum
    # snapshot dele (foram todos apagados acima). Sem isso o catalogo cresce
    # pra sempre com jogo que nunca mais volta.
    supa.delete("roblox_jogos", [("lt", "atualizado_em", limite_retencao.isoformat())])

    print(f"Total: {len(todos_jogos)} jogos unicos, {len(snapshots)} linhas de snapshot.")


if __name__ == "__main__":
    main()
