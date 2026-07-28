import datetime

from . import supa

# Espelha METAS em dashboard/components/ConquistasInscritos.jsx -- mantido em
# sincronia manualmente (os dois lados so leem, o desbloqueio de verdade e
# gravado aqui uma vez e fica permanente em conquistas_desbloqueadas).
METAS_INSCRITOS = [
    ("slime", 500), ("galinha", 1000), ("zumbi", 5000), ("esqueleto", 7500),
    ("aranha", 10000), ("creeper", 15000), ("enderman", 20000), ("villager", 35000),
    ("iron-golem", 50000), ("pillager", 75000), ("warden", 100000), ("piglin", 150000),
    ("wither-skeleton", 200000), ("blaze", 250000), ("golem-de-neve", 300000), ("wither", 500000),
]

# Os 10 canais de destaque do nicho BR escolhidos manualmente -- desbloqueia
# quando a media de views (videos longos, ultimos 7 dias) do canal proprio
# supera a do respectivo canal numa mesma semana (nao precisa sustentar).
CANAIS_DESTAQUE = [
    ("cadres", "Cadres"), ("athos", "Athos"), ("probiems", "ProbIems"),
    ("marcelodrv", "Marcelodrv"), ("welix", "WELIX"), ("xmarcelo", "xMarcelo"),
    ("naru", "Naru"), ("geleia", "Geleia"), ("tex-hs", "Tex HS"), ("jeffblox", "JeffBlox"),
]


def _ja_desbloqueada(slug):
    return bool(supa.get("conquistas_desbloqueadas", "slug", filters=[("eq", "slug", slug)]))


def _desbloquear_se_novo(slug):
    if _ja_desbloqueada(slug):
        return False
    supa.insert("conquistas_desbloqueadas", [{"slug": slug}])
    return True


def verificar_conquistas_inscritos(subs_atual):
    novas = []
    for slug, meta in METAS_INSCRITOS:
        if subs_atual >= meta and _desbloquear_se_novo(slug):
            novas.append(slug)
    return novas


def media_views_7d_longo_canal(channel_id):
    sete_dias = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
    videos = supa.get(
        "videos", "id",
        filters=[
            ("eq", "channel_id", channel_id), ("eq", "tipo", "longo"),
            ("eq", "removido", False), ("gte", "published_at", sete_dias),
        ],
    )
    if not videos:
        return None
    ids = [v["id"] for v in videos]
    snaps = supa.get(
        "video_snapshots", "video_id,views,coletado_em",
        filters=[("in_", "video_id", ids)],
    )
    ultimo_por_video = {}
    for s in snaps:
        atual = ultimo_por_video.get(s["video_id"])
        if not atual or s["coletado_em"] > atual["coletado_em"]:
            ultimo_por_video[s["video_id"]] = s
    if not ultimo_por_video:
        return None
    return sum(s["views"] for s in ultimo_por_video.values()) / len(ultimo_por_video)


def media_views_7d_longo_meu_canal():
    sete_dias = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
    videos = supa.get(
        "meu_canal_videos", "views",
        filters=[("eq", "tipo", "longo"), ("gte", "published_at", sete_dias)],
    )
    views = [v["views"] for v in videos if v["views"] is not None]
    if not views:
        return None
    return sum(views) / len(views)


def verificar_conquistas_canais(media_minha):
    if media_minha is None:
        return []
    canais = {c["nome"]: c["id"] for c in supa.get("channels", "id,nome")}
    novas = []
    for slug, nome_canal in CANAIS_DESTAQUE:
        if _ja_desbloqueada(slug):
            continue
        channel_id = canais.get(nome_canal)
        if not channel_id:
            continue
        media_canal = media_views_7d_longo_canal(channel_id)
        if media_canal and media_minha > media_canal and _desbloquear_se_novo(slug):
            novas.append(slug)
    return novas
