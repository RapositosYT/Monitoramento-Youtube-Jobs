"""One-off: preenche duracao_s dos videos que ja estavam no banco antes da
coluna existir. Rodar manualmente uma vez (workflow_dispatch); nao faz parte
do ciclo normal (job1_descoberta.py ja grava duracao_s pros novos)."""
import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa, yt  # noqa: E402


def main():
    pendentes = supa.get(
        "videos", "id,youtube_video_id",
        filters=[("is_", "duracao_s", "null")],
    )
    if not pendentes:
        print("Nenhum video pendente de duracao_s.")
        return

    info = yt.videos_info([v["youtube_video_id"] for v in pendentes])
    atualizados = 0
    for v in pendentes:
        d = info.get(v["youtube_video_id"])
        if not d:
            continue
        supa.update("videos", [("eq", "id", v["id"])], {"duracao_s": d["duracao_s"]})
        atualizados += 1

    print(f"Pendentes: {len(pendentes)} | atualizados: {atualizados}")


if __name__ == "__main__":
    main()
