import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa, yt  # noqa: E402


def main():
    canais = supa.get("meu_canal", "id,youtube_channel_id")
    canal = canais[0] if canais else None
    if not canal or not canal.get("youtube_channel_id"):
        print("Nenhum canal proprio configurado ainda (tela de Missoes) -- nada a coletar.")
        return

    info = yt.channels_info([canal["youtube_channel_id"]])
    dados = info.get(canal["youtube_channel_id"])
    if not dados:
        print(f"Canal {canal['youtube_channel_id']} nao encontrado na API do YouTube.")
        return

    supa.update("meu_canal", [("eq", "id", canal["id"])], {
        "nome": dados["nome"],
        "thumbnail_url": dados["thumbnail_url"],
    })
    supa.insert("meu_canal_snapshots", [{
        "subs": dados["subs"],
        "total_views": dados["total_views"],
        "qtd_videos": dados["qtd_videos"],
    }])
    print(f"Snapshot registrado: {dados['subs']} subs, {dados['total_views']} views, {dados['qtd_videos']} videos.")


if __name__ == "__main__":
    main()
