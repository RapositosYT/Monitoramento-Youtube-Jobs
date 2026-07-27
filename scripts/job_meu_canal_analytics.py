import datetime
import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa  # noqa: E402
from lib.oauth import analytics_client  # noqa: E402


def main():
    canais = supa.get("meu_canal", "id,youtube_channel_id")
    canal = canais[0] if canais else None
    if not canal or not canal.get("youtube_channel_id"):
        print("Nenhum canal proprio configurado ainda (tela de Missoes) -- nada a coletar.")
        return

    # A YouTube Analytics API so consolida dados ate ~2 dias atras; reprocessa
    # uma janela pequena pra cobrir atrasos de consolidacao entre execucoes.
    fim = datetime.date.today() - datetime.timedelta(days=2)
    inicio = fim - datetime.timedelta(days=3)

    yta = analytics_client()

    linhas = {}

    def somar(dia, campos):
        linha = linhas.setdefault(dia, {"dia": dia})
        linha.update(campos)

    principal = yta.reports().query(
        ids="channel==MINE",
        startDate=inicio.isoformat(),
        endDate=fim.isoformat(),
        metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
        dimensions="day",
    ).execute()
    for dia, views, minutos, duracao_media, ganhos, perdidos in principal.get("rows", []):
        somar(dia, {
            "views": views,
            "tempo_exibicao_min": minutos,
            "duracao_media_visualizacao_s": duracao_media,
            "subs_ganhos": ganhos,
            "subs_perdidos": perdidos,
        })

    # impressoes/CTR nao existem na API publica do YouTube Analytics -- so
    # ficam disponiveis dentro do YouTube Studio (mesma limitacao do Test &
    # Compare de titulo/thumbnail).
    if linhas:
        supa.upsert("meu_canal_analytics_diario", list(linhas.values()), on_conflict="dia")

    trafego = yta.reports().query(
        ids="channel==MINE",
        startDate=inicio.isoformat(),
        endDate=fim.isoformat(),
        metrics="views",
        dimensions="day,insightTrafficSourceType",
    ).execute()
    trafego_linhas = [
        {"dia": dia, "origem": origem, "views": views}
        for dia, origem, views in trafego.get("rows", [])
    ]
    if trafego_linhas:
        supa.upsert("meu_canal_trafego", trafego_linhas, on_conflict="dia,origem")

    videos_retencao = coletar_retencao(yta)

    print(f"Analytics atualizado: {inicio} a {fim} | {len(linhas)} dias | {len(trafego_linhas)} linhas de trafego "
          f"| retencao coletada de {videos_retencao} videos.")


def coletar_retencao(yta):
    """So processa videos publicados nos ultimos 30 dias -- cada um custa 1
    chamada de API separada (filtro video==ID nao aceita lote)."""
    trinta_dias_atras = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    recentes = supa.get(
        "meu_canal_videos", "youtube_video_id",
        filters=[("gte", "published_at", trinta_dias_atras)],
    )

    processados = 0
    for v in recentes:
        vid = v["youtube_video_id"]
        try:
            resp = yta.reports().query(
                ids="channel==MINE",
                startDate="2020-01-01",
                endDate=datetime.date.today().isoformat(),
                dimensions="elapsedVideoTimeRatio",
                metrics="audienceWatchRatio,relativeRetentionPerformance",
                filters=f"video=={vid}",
            ).execute()
        except Exception as e:
            print(f"Retencao falhou pra {vid}: {e}")
            continue

        linhas = [
            {"youtube_video_id": vid, "elapsed_ratio": elapsed, "audience_watch_ratio": watch, "retencao_relativa": relativa}
            for elapsed, watch, relativa in resp.get("rows", [])
        ]
        if linhas:
            supa.upsert("meu_canal_retencao", linhas, on_conflict="youtube_video_id,elapsed_ratio")
            processados += 1
    return processados


if __name__ == "__main__":
    main()
