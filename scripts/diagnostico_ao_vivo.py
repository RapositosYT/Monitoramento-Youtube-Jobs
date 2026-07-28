"""One-off: verifica na API de verdade (liveStreamingDetails) quais videos ja
no banco sao/foram live ou premiere, pra decidir com seguranca o que limpar.
So LE e imprime -- nao apaga nada. Rodar manualmente (workflow_dispatch)."""
import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa, yt  # noqa: E402


def main():
    videos = supa.get(
        "videos", "id,youtube_video_id,titulo,channel_id,published_at,duracao_s",
        filters=[("eq", "removido", False)],
    )
    canais = {c["id"]: c["nome"] for c in supa.get("channels", "id,nome")}

    encontrados = 0
    for i in range(0, len(videos), 50):
        lote = videos[i:i + 50]
        info = yt.videos_info([v["youtube_video_id"] for v in lote])
        for v in lote:
            d = info.get(v["youtube_video_id"])
            if not d or not d["ao_vivo"]:
                continue
            encontrados += 1
            snaps = supa.get(
                "video_snapshots", "views",
                filters=[("eq", "video_id", v["id"])],
            )
            views_max = max((s["views"] for s in snaps), default=0)
            print(
                f"AO_VIVO | id={v['id']} | canal={canais.get(v['channel_id'])} | "
                f"titulo={v['titulo']!r} | duracao_s={v['duracao_s']} | "
                f"published_at={v['published_at']} | snapshots={len(snaps)} | views_max={views_max}"
            )

    print(f"Total verificado: {len(videos)} | marcados como live/premiere: {encontrados}")


if __name__ == "__main__":
    main()
