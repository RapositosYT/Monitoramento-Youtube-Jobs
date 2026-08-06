import datetime

from . import supa

# Espelha METAS em dashboard/components/ConquistasInscritos.jsx -- mantido em
# sincronia manualmente (os dois lados so leem, o desbloqueio de verdade e
# gravado aqui uma vez e fica permanente em conquistas_desbloqueadas).
METAS_INSCRITOS = [
    ("slime", 500), ("galinha", 1000), ("zumbi", 5000), ("esqueleto", 7500),
    ("aranha", 10000), ("creeper", 15000), ("enderman", 20000), ("villager", 35000),
    ("iron-golem", 50000), ("pillager", 75000), ("warden", 100000), ("piglin", 150000),
    ("wither-skeleton", 200000), ("blaze", 250000), ("golem-de-neve", 300000),
    ("vaca-cogumelo", 350000), ("allay", 400000), ("sapo", 450000), ("wither", 500000),
    ("axolote", 600000), ("baiacu", 700000), ("comerciante", 800000),
    ("golem-de-cobre", 900000), ("ender-dragon", 1000000),
]

# Views em UM UNICO short (o maior short do canal, nao soma) -- espelha
# METAS_SHORTS em dashboard/components/ConquistasShorts.jsx.
METAS_SHORTS = [
    ("shorts", 10000), ("carvao", 20000), ("terra", 25000), ("madeira", 50000),
    ("pedra", 100000), ("ferro", 300000), ("mel", 400000), ("ouro", 500000),
    ("esmeralda", 1000000), ("diamante", 2500000), ("netherite", 5000000),
    ("netherite-encantado", 10000000),
]

# Soma de views de TODO o canal desde sempre (total_views da API do YouTube,
# nao e soma calculada aqui) -- espelha METAS em
# dashboard/components/ConquistasViewsTotais.jsx. Slugs prefixados com
# "vt-" de proposito pra nao colidir com METAS_SHORTS (mesmos nomes de
# material, thresholds bem diferentes -- "madeira" ali e' 50 mil views num
# unico short, aqui e' 5 milhoes de views somadas do canal inteiro).
METAS_VIEWS_TOTAIS = [
    ("vt-youtube", 1000000), ("vt-terra", 2500000), ("vt-madeira", 5000000),
    ("vt-pedra", 10000000), ("vt-carvao", 25000000), ("vt-ferro", 50000000),
    ("vt-mel", 100000000), ("vt-ouro", 150000000), ("vt-esmeralda", 200000000),
    ("vt-diamante", 250000000), ("vt-netherite", 500000000),
    ("vt-netherite-encantado", 1000000000),
]

# Os 10 canais de destaque do nicho BR escolhidos manualmente -- desbloqueia
# quando a SOMA de views (videos longos, ultimos 7 dias) do canal proprio
# supera a do respectivo canal numa mesma semana (nao precisa sustentar).
# Soma em vez de media pra nao recompensar um unico video de sorte contra um
# canal que manteve resultado consistente em varios videos na semana.
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


def maior_views_short_meu_canal():
    shorts = supa.get("meu_canal_videos", "views", filters=[("eq", "tipo", "short")])
    views = [v["views"] for v in shorts if v["views"] is not None]
    return max(views) if views else 0


def verificar_conquistas_shorts(maior_views):
    novas = []
    for slug, meta in METAS_SHORTS:
        if maior_views >= meta and _desbloquear_se_novo(slug):
            novas.append(slug)
    return novas


def verificar_conquistas_views_totais(total_views):
    novas = []
    for slug, meta in METAS_VIEWS_TOTAIS:
        if total_views >= meta and _desbloquear_se_novo(slug):
            novas.append(slug)
    return novas


def soma_views_7d_longo_canal(channel_id):
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
    return sum(s["views"] for s in ultimo_por_video.values())


def soma_views_7d_longo_meu_canal():
    sete_dias = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
    videos = supa.get(
        "meu_canal_videos", "views",
        filters=[("eq", "tipo", "longo"), ("gte", "published_at", sete_dias)],
    )
    views = [v["views"] for v in videos if v["views"] is not None]
    if not views:
        return None
    return sum(views)


def verificar_conquistas_canais(minha_soma):
    if minha_soma is None:
        return []
    canais = {c["nome"]: c["id"] for c in supa.get("channels", "id,nome")}
    novas = []
    for slug, nome_canal in CANAIS_DESTAQUE:
        if _ja_desbloqueada(slug):
            continue
        channel_id = canais.get(nome_canal)
        if not channel_id:
            continue
        soma_canal = soma_views_7d_longo_canal(channel_id)
        if soma_canal and minha_soma > soma_canal and _desbloquear_se_novo(slug):
            novas.append(slug)
    return novas
