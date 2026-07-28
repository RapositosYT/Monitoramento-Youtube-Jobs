import datetime

from . import supa

CHECKPOINTS_H = {"1h": 1, "6h": 6, "24h": 24, "48h": 48, "7d": 168, "14d": 336}
# distancia maxima (em horas) entre a coleta e o horario alvo pra aceitar o
# checkpoint; alem disso o video foi descoberto tarde demais pra ter dado
# confiavel naquele marco e o checkpoint fica em branco (sem sinal, nao 0)
CHECKPOINT_TOLERANCIA_H = {"1h": 2, "6h": 3, "24h": 6, "48h": 8, "7d": 24, "14d": 24}


def checkpoint_para(horas_desde_pub):
    alvo = min(CHECKPOINTS_H, key=lambda k: abs(CHECKPOINTS_H[k] - horas_desde_pub))
    if abs(CHECKPOINTS_H[alvo] - horas_desde_pub) <= CHECKPOINT_TOLERANCIA_H[alvo]:
        return alvo
    return None


def registrar_snapshot(v, d, agora, agora_iso, limiares, amostra_minima, janela_videos):
    publicado = datetime.datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))

    anteriores = supa.get(
        "video_snapshots", "id,coletado_em,views,titulo,thumbnail_url,checkpoint",
        filters=[("eq", "video_id", v["id"])],
    )
    anteriores.sort(key=lambda s: s["coletado_em"])
    anterior = anteriores[-1] if anteriores else None

    limpar_checkpoints_invalidos(anteriores, publicado)

    velocidade = None
    if anterior:
        dt_ant = datetime.datetime.fromisoformat(anterior["coletado_em"])
        horas = (agora - dt_ant).total_seconds() / 3600
        if horas > 0:
            velocidade = (d["views"] - anterior["views"]) / horas
        registrar_alteracoes(v["id"], anterior, d, agora_iso)

    horas_desde_pub = (agora - publicado).total_seconds() / 3600
    checkpoint = checkpoint_para(horas_desde_pub)
    if checkpoint:
        checkpoint = checkpoint_se_mais_proximo(v["id"], checkpoint, publicado, horas_desde_pub)

    desvio, nivel = (None, None)
    if checkpoint:
        desvio, nivel = calcular_desvio(v, d["views"], checkpoint, amostra_minima, limiares, janela_videos)

    supa.insert("video_snapshots", [{
        "video_id": v["id"],
        "coletado_em": agora_iso,
        "views": d["views"],
        "likes": d["likes"],
        "comentarios": d["comentarios"],
        "titulo": d["titulo"],
        "thumbnail_url": d["thumbnail_url"],
        "velocidade_views_h": velocidade,
        "checkpoint": checkpoint,
        "desvio": desvio,
        "nivel_sinalizacao": nivel,
    }])

    if checkpoint:
        # so um snapshot pode "segurar" cada checkpoint do video -- checkpoint_se_mais_proximo
        # ja garantiu que o novo e o mais perto do horario alvo, entao qualquer outro que
        # ainda segure esse checkpoint perdeu a disputa e deve ser liberado
        supa.update(
            "video_snapshots",
            [("eq", "video_id", v["id"]), ("eq", "checkpoint", checkpoint), ("neq", "coletado_em", agora_iso)],
            {"checkpoint": None, "desvio": None, "nivel_sinalizacao": None},
        )


def checkpoint_se_mais_proximo(video_id, checkpoint, publicado, horas_desde_pub):
    """So o snapshot mais PROXIMO do horario alvo do checkpoint deve segura-lo --
    nao simplesmente o mais recente. Sem isso, uma coleta mais tardia (mas ainda
    dentro da tolerancia) rouba o checkpoint de uma coleta que estava mais perto
    do horario ideal (ex: 6h caindo perto da meia-noite, mas uma coleta de 2h
    depois "vence" so por ter sido feita depois)."""
    distancia_novo = abs(horas_desde_pub - CHECKPOINTS_H[checkpoint])
    atuais = supa.get(
        "video_snapshots", "coletado_em",
        filters=[("eq", "video_id", video_id), ("eq", "checkpoint", checkpoint)],
    )
    for s in atuais:
        dt_s = datetime.datetime.fromisoformat(s["coletado_em"])
        horas_s = (dt_s - publicado).total_seconds() / 3600
        distancia_atual = abs(horas_s - CHECKPOINTS_H[checkpoint])
        if distancia_atual <= distancia_novo:
            return None
    return checkpoint


def limpar_checkpoints_invalidos(snapshots, publicado):
    """Corrige snapshots antigos cujo checkpoint foi assumido sem tolerancia
    (ex: dado de execucoes antes desta checagem existir, ou video descoberto
    tarde demais). So roda update quando ha algo pra corrigir."""
    for s in snapshots:
        if not s.get("checkpoint"):
            continue
        dt = datetime.datetime.fromisoformat(s["coletado_em"])
        horas = (dt - publicado).total_seconds() / 3600
        if checkpoint_para(horas) != s["checkpoint"]:
            supa.update(
                "video_snapshots", [("eq", "id", s["id"])],
                {"checkpoint": None, "desvio": None, "nivel_sinalizacao": None},
            )


def registrar_alteracoes(video_id, anterior, atual, agora_iso):
    if anterior["titulo"] != atual["titulo"]:
        supa.insert("video_alteracoes", [{
            "video_id": video_id, "campo": "titulo",
            "valor_anterior": anterior["titulo"], "valor_novo": atual["titulo"],
            "detectado_em": agora_iso,
        }])
    if anterior["thumbnail_url"] != atual["thumbnail_url"]:
        supa.insert("video_alteracoes", [{
            "video_id": video_id, "campo": "thumbnail",
            "valor_anterior": anterior["thumbnail_url"], "valor_novo": atual["thumbnail_url"],
            "detectado_em": agora_iso,
        }])


def calcular_desvio(v, views_atuais, checkpoint, amostra_minima, limiares, janela_videos):
    # Nao exige mais rastreamento_ativo=False: a maioria dos videos "fechados"
    # so tem 1 snapshot (pego tarde demais, perto do proprio 14d, geralmente
    # do backfill inicial), entao exigir isso deixava o desvio praticamente
    # sem regua de comparacao nos marcos antes de 14d. Um video ainda ativo
    # que ja passou por esse checkpoint e uma referencia igualmente valida.
    outros_videos = supa.get(
        "videos", "id,published_at",
        filters=[
            ("eq", "channel_id", v["channel_id"]),
            ("eq", "tipo", v["tipo"]),
        ],
    )
    recentes = sorted(
        (x for x in outros_videos if x["id"] != v["id"]),
        key=lambda x: x["published_at"], reverse=True,
    )[:janela_videos]
    ids = [x["id"] for x in recentes]
    if not ids:
        return None, None

    snaps = supa.get(
        "video_snapshots", "views",
        filters=[("in_", "video_id", ids), ("eq", "checkpoint", checkpoint)],
    )
    if len(snaps) < amostra_minima:
        return None, None

    media = sum(s["views"] for s in snaps) / len(snaps)
    if media <= 0:
        return None, None

    desvio = views_atuais / media
    nivel = None
    if desvio >= limiares["anomalia"]:
        nivel = "anomalia"
    elif desvio >= limiares["candidato"]:
        nivel = "candidato"
    elif desvio >= limiares["atencao"]:
        nivel = "atencao"
    return desvio, nivel
