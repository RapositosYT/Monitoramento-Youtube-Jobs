import datetime
import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import gemini, supa, yt  # noqa: E402
from lib.snapshot import registrar_snapshot  # noqa: E402


def main():
    cfg = supa.config_dict()
    janela_dias = int(cfg.get("janela_rastreamento_dias", 14))
    shorts_max_s = int(cfg.get("shorts_max_segundos", 180))
    amostra_minima = int(cfg.get("amostra_minima_videos", 5))
    janela_videos = int(cfg.get("desvio_janela_videos", 30))
    limiares = {
        "atencao": float(cfg.get("limiar_atencao", 1.5)),
        "candidato": float(cfg.get("limiar_candidato", 2.0)),
        "anomalia": float(cfg.get("limiar_anomalia", 3.0)),
    }
    agora = datetime.datetime.now(datetime.timezone.utc)
    agora_iso = agora.isoformat()

    canais = supa.get(
        "channels", "id,youtube_channel_id,uploads_playlist_id",
        filters=[("eq", "ativo", True)],
    )
    stats = yt.channels_info([c["youtube_channel_id"] for c in canais])

    snaps = []
    for c in canais:
        s = stats.get(c["youtube_channel_id"])
        if not s:
            continue
        snaps.append({
            "channel_id": c["id"],
            "coletado_em": agora_iso,
            "subs": s["subs"],
            "total_views_canal": s["total_views"],
            "qtd_videos": s["qtd_videos"],
        })
        supa.update("channels", [("eq", "id", c["id"])],
                    {"subs_atual": s["subs"], "thumbnail_url": s["thumbnail_url"]})
    supa.insert("channel_snapshots", snaps)

    candidatos = {}
    for c in canais:
        pl = c.get("uploads_playlist_id") or \
            stats.get(c["youtube_channel_id"], {}).get("uploads_playlist_id")
        if not pl:
            continue
        for vid in yt.playlist_recent(pl):
            candidatos[vid] = c["id"]

    novos_ids = filtrar_desconhecidos(list(candidatos))
    if not novos_ids:
        print(f"Canais: {len(canais)} | snapshots: {len(snaps)} | videos novos: 0")
        return

    info = yt.videos_info(novos_ids)
    limite = agora - datetime.timedelta(days=janela_dias)
    linhas = []
    ignorados_agendado_ou_live = 0
    for vid, v in info.items():
        pub = datetime.datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        if pub > agora or v["ao_vivo"]:
            # ainda agendado (published_at no futuro) ou e/foi live/estreia --
            # continua "desconhecido" e sera reavaliado na proxima descoberta.
            ignorados_agendado_ou_live += 1
            continue
        linhas.append({
            "channel_id": candidatos[vid],
            "youtube_video_id": vid,
            "titulo": v["titulo"],
            "thumbnail_url": v["thumbnail_url"],
            "published_at": v["published_at"],
            "descoberto_em": agora_iso,
            "tipo": "short" if 0 < v["duracao_s"] <= shorts_max_s else "longo",
            "duracao_s": v["duracao_s"],
            "rastreamento_ativo": pub > limite,
        })
    inseridos = supa.insert("videos", linhas)
    for video in inseridos:
        d = info.get(video["youtube_video_id"])
        if d:
            registrar_snapshot(video, d, agora, agora_iso, limiares, amostra_minima, janela_videos)
    classificados = classificar_novos(inseridos, info)
    print(f"Canais: {len(canais)} | snapshots: {len(snaps)} | videos novos: {len(linhas)} | "
          f"ignorados (agendado/live): {ignorados_agendado_ou_live} | classificados: {classificados}")


def classificar_novos(inseridos, info):
    if not inseridos:
        return 0
    formatos = supa.get("formatos", "id,nome,descricao")
    classificados = 0
    for video in inseridos:
        descricao = info.get(video["youtube_video_id"], {}).get("descricao", "")
        resultados = gemini.classificar_formatos(video["titulo"], descricao, formatos)
        if not resultados:
            continue

        linhas_junction = []
        for i, (nome, confianca) in enumerate(resultados):
            formato_id = garantir_formato(nome, formatos)
            if formato_id is None:
                continue
            linhas_junction.append({
                "video_id": video["id"], "formato_id": formato_id,
                "confianca": confianca, "principal": i == 0,
            })
        if not linhas_junction:
            continue

        principal = linhas_junction[0]
        supa.update(
            "videos", [("eq", "id", video["id"])],
            {"formato_id": principal["formato_id"], "confianca_classificacao": principal["confianca"]},
        )
        supa.upsert("video_formatos", linhas_junction, on_conflict="video_id,formato_id")
        classificados += 1
    return classificados


def garantir_formato(nome, formatos_conhecidos):
    for f in formatos_conhecidos:
        if f["nome"].strip().lower() == nome.strip().lower():
            return f["id"]
    existentes = supa.get("formatos", "id,nome", filters=[("ilike", "nome", nome)])
    if existentes:
        formatos_conhecidos.append(existentes[0])
        return existentes[0]["id"]
    criados = supa.insert("formatos", [{"nome": nome}])
    if criados:
        formatos_conhecidos.append(criados[0])
        return criados[0]["id"]
    return None


def filtrar_desconhecidos(ids):
    conhecidos = set()
    for i in range(0, len(ids), 100):
        lote = ids[i:i + 100]
        for r in supa.get(
            "videos", "youtube_video_id",
            filters=[("in_", "youtube_video_id", lote)],
        ):
            conhecidos.add(r["youtube_video_id"])
    return [v for v in ids if v not in conhecidos]


if __name__ == "__main__":
    main()
