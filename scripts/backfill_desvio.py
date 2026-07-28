"""One-off: recalcula desvio/nivel_sinalizacao dos snapshots que ja tem
checkpoint gravado mas ficaram sem desvio -- a regua de comparacao antiga
exigia video 100% fechado (rastreamento_ativo=False), o que na pratica
deixava quase nenhuma referencia disponivel antes do marco de 14d (ver
lib/snapshot.py). Rodar manualmente uma vez (workflow_dispatch); nao faz
parte do ciclo normal."""
import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa  # noqa: E402
from lib.snapshot import calcular_desvio  # noqa: E402


def main():
    cfg = supa.config_dict()
    amostra_minima = int(cfg.get("amostra_minima_videos", 5))
    janela_videos = int(cfg.get("desvio_janela_videos", 30))
    limiares = {
        "atencao": float(cfg.get("limiar_atencao", 1.5)),
        "candidato": float(cfg.get("limiar_candidato", 2.0)),
        "anomalia": float(cfg.get("limiar_anomalia", 3.0)),
    }

    pendentes = [
        s for s in supa.get("video_snapshots", "id,video_id,views,checkpoint", filters=[("is_", "desvio", "null")])
        if s.get("checkpoint")
    ]
    if not pendentes:
        print("Nenhum snapshot pendente de desvio.")
        return

    videos_por_id = {v["id"]: v for v in supa.get("videos", "id,channel_id,tipo")}

    atualizados = 0
    for s in pendentes:
        v = videos_por_id.get(s["video_id"])
        if not v:
            continue
        desvio, nivel = calcular_desvio(v, s["views"], s["checkpoint"], amostra_minima, limiares, janela_videos)
        if desvio is None:
            continue
        supa.update("video_snapshots", [("eq", "id", s["id"])], {"desvio": desvio, "nivel_sinalizacao": nivel})
        atualizados += 1

    print(f"Pendentes: {len(pendentes)} | atualizados: {atualizados}")


if __name__ == "__main__":
    main()
