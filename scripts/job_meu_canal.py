import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa, yt  # noqa: E402
from lib.conquistas import (  # noqa: E402
    media_views_7d_longo_meu_canal, verificar_conquistas_canais, verificar_conquistas_inscritos,
)


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
        "uploads_playlist_id": dados["uploads_playlist_id"],
    })
    supa.insert("meu_canal_snapshots", [{
        "subs": dados["subs"],
        "total_views": dados["total_views"],
        "qtd_videos": dados["qtd_videos"],
    }])

    shorts_max_s = int(supa.config_dict().get("shorts_max_segundos", 180))
    video_ids = yt.playlist_all(dados["uploads_playlist_id"]) if dados.get("uploads_playlist_id") else []
    linhas = []
    if video_ids:
        detalhes = yt.videos_info(video_ids)
        for vid, v in detalhes.items():
            linhas.append({
                "youtube_video_id": vid,
                "titulo": v["titulo"],
                "thumbnail_url": v["thumbnail_url"],
                "tipo": "short" if 0 < v["duracao_s"] <= shorts_max_s else "longo",
                "duracao_s": v["duracao_s"],
                "published_at": v["published_at"],
                "views": v["views"],
                "likes": v["likes"],
                "comentarios": v["comentarios"],
            })
        supa.upsert("meu_canal_videos", linhas, on_conflict="youtube_video_id")

    novas_inscritos = verificar_conquistas_inscritos(dados["subs"])
    media_minha = media_views_7d_longo_meu_canal()
    novas_canais = verificar_conquistas_canais(media_minha)

    print(f"Snapshot registrado: {dados['subs']} subs, {dados['total_views']} views, {dados['qtd_videos']} videos "
          f"| {len(linhas)} videos do catalogo atualizados "
          f"| conquistas novas: {novas_inscritos + novas_canais}")


if __name__ == "__main__":
    main()
