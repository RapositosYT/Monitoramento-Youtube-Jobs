import datetime
import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import supa, yt  # noqa: E402
from lib.snapshot import registrar_snapshot  # noqa: E402


def main():
    cfg = supa.config_dict()
    janela_dias = int(cfg.get("janela_rastreamento_dias", 14))
    amostra_minima = int(cfg.get("amostra_minima_videos", 5))
    janela_videos = int(cfg.get("desvio_janela_videos", 30))
    limiares = {
        "atencao": float(cfg.get("limiar_atencao", 1.5)),
        "candidato": float(cfg.get("limiar_candidato", 2.0)),
        "anomalia": float(cfg.get("limiar_anomalia", 3.0)),
    }
    agora = datetime.datetime.now(datetime.timezone.utc)
    agora_iso = agora.isoformat()
    limite = agora - datetime.timedelta(days=janela_dias)

    ativos = supa.get(
        "videos", "id,youtube_video_id,channel_id,tipo,published_at",
        filters=[("eq", "rastreamento_ativo", True)],
    )
    if not ativos:
        print("Nenhum video em rastreamento.")
        return

    info = yt.videos_info([v["youtube_video_id"] for v in ativos])
    processados = 0
    removidos = 0
    for v in ativos:
        d = info.get(v["youtube_video_id"])
        if not d:
            # video sumiu da API -- foi apagado ou ficou privado. Fecha o
            # rastreamento na hora em vez de deixar "zumbi" parado esperando
            # os 14 dias (sem receber snapshot novo nenhum nesse meio tempo).
            supa.update(
                "videos", [("eq", "id", v["id"])],
                {"rastreamento_ativo": False, "removido": True, "removido_em": agora_iso},
            )
            removidos += 1
            continue
        processados += 1
        registrar_snapshot(v, d, agora, agora_iso, limiares, amostra_minima, janela_videos)

    fechando = supa.get(
        "videos", "id",
        filters=[("eq", "rastreamento_ativo", True), ("lt", "published_at", limite.isoformat())],
    )
    for v in fechando:
        supa.delete("video_snapshots", [("eq", "video_id", v["id"]), ("is_", "checkpoint", "null")])
    if fechando:
        supa.update(
            "videos",
            [("eq", "rastreamento_ativo", True), ("lt", "published_at", limite.isoformat())],
            {"rastreamento_ativo": False},
        )

    atualizados_tier = atualizar_tier_efetivo(amostra_minima, cfg)
    atualizados_corredor = atualizar_corredor_estagio(cfg)

    print(f"Videos processados: {processados} | removidos (apagados/privados): {removidos} "
          f"| janelas fechadas (downsampling): {len(fechando)} "
          f"| tier_efetivo atualizados: {atualizados_tier} | corredor_estagio atualizados: {atualizados_corredor}")


def atualizar_tier_efetivo(amostra_minima, cfg):
    limite_pequeno = float(cfg.get("tier_efetivo_limite_pequeno", 20000))
    limite_medio = float(cfg.get("tier_efetivo_limite_medio", 200000))

    canais = supa.get("channels", "id", filters=[("eq", "ativo", True)])
    atualizados = 0
    for c in canais:
        tier = calcular_tier_efetivo(c["id"], amostra_minima, limite_pequeno, limite_medio)
        if tier:
            supa.update("channels", [("eq", "id", c["id"])], {"tier_efetivo": tier})
            atualizados += 1
    return atualizados


def calcular_tier_efetivo(channel_id, amostra_minima, limite_pequeno, limite_medio):
    videos = supa.get("videos", "id,tipo,published_at", filters=[("eq", "channel_id", channel_id)])
    if not videos:
        return None

    contagem = {}
    for v in videos:
        contagem[v["tipo"]] = contagem.get(v["tipo"], 0) + 1
    tipo_dominante = max(contagem, key=contagem.get)

    recentes = sorted(
        (v for v in videos if v["tipo"] == tipo_dominante),
        key=lambda v: v["published_at"], reverse=True,
    )[:15]
    if len(recentes) < amostra_minima:
        return None

    snaps = supa.get(
        "video_snapshots", "video_id,views,coletado_em",
        filters=[("in_", "video_id", [v["id"] for v in recentes])],
    )
    por_video = {}
    for s in snaps:
        atual = por_video.get(s["video_id"])
        if atual is None or s["coletado_em"] > atual["coletado_em"]:
            por_video[s["video_id"]] = s
    if len(por_video) < amostra_minima:
        return None

    media = sum(s["views"] for s in por_video.values()) / len(por_video)
    if media <= limite_pequeno:
        return "pequeno"
    elif media <= limite_medio:
        return "medio"
    return "grande"


def atualizar_corredor_estagio(cfg):
    """"X dias" do Sinal nao foi definido no plano original -- reusa
    janela_rastreamento_dias (14) como janela de recencia do sinal."""
    janela_validacao = int(cfg.get("janela_validacao_dias", 10))
    janela_sinal = int(cfg.get("janela_rastreamento_dias", 14))
    agora = datetime.datetime.now(datetime.timezone.utc)
    limite_sinal = (agora - datetime.timedelta(days=janela_sinal)).isoformat()

    canais = {c["id"]: c for c in supa.get(
        "channels", "id,tier_efetivo,regiao,jogo", filters=[("eq", "ativo", True)])}
    videos = [v for v in supa.get("videos", "id,channel_id,formato_id,published_at")
              if v["channel_id"] in canais and v["formato_id"]]

    marcados = supa.get(
        "video_snapshots", "video_id",
        filters=[("in_", "nivel_sinalizacao", ["candidato", "anomalia"])],
    )
    ids_com_sinal = {m["video_id"] for m in marcados}

    sinais = []
    for v in videos:
        if v["id"] not in ids_com_sinal or v["published_at"] < limite_sinal:
            continue
        c = canais[v["channel_id"]]
        if c["tier_efetivo"] == "pequeno" and c["regiao"] in ("gringo", "latino"):
            sinais.append({**v, "jogo": c["jogo"]})

    novo_estagio = {s["channel_id"]: "sinal" for s in sinais}

    validacoes = []
    for v in videos:
        c = canais[v["channel_id"]]
        if c["tier_efetivo"] != "medio" or c["regiao"] not in ("latino", "BR"):
            continue
        for s in sinais:
            if s["jogo"] != c["jogo"] or s["formato_id"] != v["formato_id"] or s["channel_id"] == c["id"]:
                continue
            dias = (datetime.datetime.fromisoformat(v["published_at"]) -
                    datetime.datetime.fromisoformat(s["published_at"])).days
            if 0 <= dias <= janela_validacao:
                novo_estagio[c["id"]] = "validacao"
                validacoes.append(v)
                break

    formatos_validados = {v["formato_id"] for v in validacoes}
    for v in videos:
        c = canais[v["channel_id"]]
        if c["tier_efetivo"] == "grande" and c["regiao"] == "BR" and v["formato_id"] in formatos_validados:
            novo_estagio[c["id"]] = "saturacao"

    for channel_id, estagio in novo_estagio.items():
        supa.update("channels", [("eq", "id", channel_id)], {"corredor_estagio": estagio})
    return len(novo_estagio)


if __name__ == "__main__":
    main()
