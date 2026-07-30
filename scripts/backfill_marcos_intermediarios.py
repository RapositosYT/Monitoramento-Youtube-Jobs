"""One-off: atribui os marcos novos (72h/96h/120h/144h) a snapshots ja
coletados que nunca tinham marco (o job normal so roda daqui pra frente).
Duas fases: primeiro atribui TODOS os marcos, depois calcula o desvio -- se
calculasse na mesma passada, os primeiros videos processados comparariam
contra uma amostra ainda vazia desse marco novo."""
import datetime
import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa  # noqa: E402
from lib.snapshot import CHECKPOINTS_H, CHECKPOINT_TOLERANCIA_H, calcular_desvio  # noqa: E402

NOVOS_MARCOS = ["72h", "96h", "120h", "144h"]


def main():
    cfg = supa.config_dict()
    amostra_minima = int(cfg.get("amostra_minima_videos", 5))
    janela_videos = int(cfg.get("desvio_janela_videos", 30))
    limiares = {
        "atencao": float(cfg.get("limiar_atencao", 1.5)),
        "candidato": float(cfg.get("limiar_candidato", 2.0)),
        "anomalia": float(cfg.get("limiar_anomalia", 3.0)),
    }

    videos = supa.get(
        "videos", "id,channel_id,tipo,published_at",
        filters=[("eq", "removido", False)],
    )

    # Fase 1: atribui o marco ao snapshot mais proximo do horario alvo, pra
    # cada video/marco novo que ainda nao tem nenhum snapshot marcado assim.
    atribuidos = []
    for v in videos:
        publicado = datetime.datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        snaps = supa.get(
            "video_snapshots", "id,coletado_em,views,checkpoint",
            filters=[("eq", "video_id", v["id"])],
        )
        if not snaps:
            continue

        for marco in NOVOS_MARCOS:
            alvo_h = CHECKPOINTS_H[marco]
            tolerancia = CHECKPOINT_TOLERANCIA_H[marco]
            melhor, melhor_dist = None, None
            for s in snaps:
                coletado = datetime.datetime.fromisoformat(s["coletado_em"])
                horas = (coletado - publicado).total_seconds() / 3600
                dist = abs(horas - alvo_h)
                if dist <= tolerancia and (melhor is None or dist < melhor_dist):
                    melhor, melhor_dist = s, dist

            if not melhor or melhor["checkpoint"]:
                continue  # sem candidato dentro da tolerancia, ou snapshot ja usado por outro marco

            supa.update("video_snapshots", [("eq", "id", melhor["id"])], {"checkpoint": marco})
            atribuidos.append({"snapshot_id": melhor["id"], "video": v, "views": melhor["views"], "marco": marco})

    # Fase 2: agora que todo mundo ja tem o marco atribuido, calcula o desvio
    # de cada um com a amostra completa.
    atualizados = 0
    for item in atribuidos:
        desvio, nivel = calcular_desvio(
            item["video"], item["views"], item["marco"], amostra_minima, limiares, janela_videos,
        )
        supa.update(
            "video_snapshots", [("eq", "id", item["snapshot_id"])],
            {"desvio": desvio, "nivel_sinalizacao": nivel},
        )
        if desvio is not None:
            atualizados += 1

    print(f"Videos verificados: {len(videos)} | marcos atribuidos: {len(atribuidos)} | desvios calculados: {atualizados}")


if __name__ == "__main__":
    main()
