import collections
import datetime
import hashlib
import json
import os
import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib import gemini, supa, texto  # noqa: E402

# acima desse tamanho, um "balde" de videos que compartilham uma mesma palavra-
# chave deixa de ser comparado par-a-par (custo O(n^2) por balde) -- protege o
# job de travar se um termo generico escapar da lista de stopwords
BALDE_MAX = 400
# tamanho de lote enviado por chamada ao Gemini na fusao entre idiomas --
# a fusao roda 1x por execucao do job (nao por video), entao o uso da API
# nao cresce com o catalogo de videos, so com a quantidade de grupos/temas
LOTE_GEMINI = 60
ID_CORINGA = "00000000-0000-0000-0000-000000000000"
CACHE_DIAS_EXPIRACAO = 60
# quantos temas SECUNDARIOS (alem do principal) um video pode ganhar --
# limita pra nao virar uma lista de tags gigante por video
TEMA_SECUNDARIO_MAX = 2
TAMANHO_LOTE_INSERT = 500


def _inserir_em_lotes(tabela, linhas):
    for inicio in range(0, len(linhas), TAMANHO_LOTE_INSERT):
        supa.insert(tabela, linhas[inicio:inicio + TAMANHO_LOTE_INSERT])


def _hash_lote(rotulo_funcao, payload):
    bruto = json.dumps({"fn": rotulo_funcao, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def _cache_buscar(chave):
    linhas = supa.get("gemini_cache_temas", "resposta", [("eq", "chave", chave)])
    return linhas[0]["resposta"] if linhas else None


def _cache_salvar(chave, resposta):
    supa.upsert("gemini_cache_temas", [{"chave": chave, "resposta": resposta}], on_conflict="chave")


def _limpar_cache_antigo():
    limite = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=CACHE_DIAS_EXPIRACAO)
    supa.delete("gemini_cache_temas", [("lt", "criado_em", limite.isoformat())])


class UniaoBusca:
    def __init__(self, n):
        self.pai = list(range(n))

    def encontrar(self, x):
        while self.pai[x] != x:
            self.pai[x] = self.pai[self.pai[x]]
            x = self.pai[x]
        return x

    def unir(self, a, b):
        ra, rb = self.encontrar(a), self.encontrar(b)
        if ra != rb:
            self.pai[ra] = rb


def agrupar(videos, chaves_por_video, similaridade_minima):
    uf = UniaoBusca(len(videos))

    invertido = collections.defaultdict(list)
    for i, chaves in enumerate(chaves_por_video):
        for c in chaves:
            invertido[c].append(i)

    comparados = set()
    for indices in invertido.values():
        if len(indices) < 2 or len(indices) > BALDE_MAX:
            continue
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                i, j = indices[a], indices[b]
                par = (i, j) if i < j else (j, i)
                if par in comparados:
                    continue
                comparados.add(par)
                if texto.jaccard(chaves_por_video[i], chaves_por_video[j]) >= similaridade_minima:
                    uf.unir(i, j)

    grupos = collections.defaultdict(list)
    for i in range(len(videos)):
        grupos[uf.encontrar(i)].append(i)
    return list(grupos.values())


def candidatos_por_termo_raro(grupos, chaves_por_video, termo_raro_df_max):
    """Um titulo com um termo ou frase bem especifica em comum (ex: nome de
    mod/personagem tipo 'Verity', ou uma frase de serie tipo 'minecraft mas')
    pode variar tanto no resto do texto que a similaridade bruta com outro
    video do mesmo assunto fica baixa demais -- cada um vira um grupo de 1
    video so, e nunca chega a ser comparado. Considera unigramas E bigramas:
    uma frase (ex: 'minecraft_mas') costuma ser um sinal mais especifico que
    uma unica palavra generica. Aqui a gente acha esse tipo de grupo
    (inclusive os de 1 video) atraves de termos raros no catalogo inteiro,
    pra pelo menos colocar como candidato de fusao pro Gemini decidir."""
    df = collections.Counter()
    for chaves in chaves_por_video:
        df.update(chaves)

    por_termo = collections.defaultdict(set)
    for gi, idx in enumerate(grupos):
        termos_do_grupo = {w for i in idx for w in chaves_por_video[i]}
        for w in termos_do_grupo:
            # bigramas (frase de 2 palavras) sao especificos o bastante pra
            # servir de sinal de fusao mesmo quando aparecem em MUITOS videos
            # -- e exatamente o caso de series com "regra variavel" tipo
            # "Minecraft Mas/But", que e recorrente (df alto) mas nao deixa
            # de ser o mesmo formato. So unigramas ficam presos ao limite de
            # raridade, que existe pra evitar palavra generica demais.
            eh_bigrama = "_" in w
            if eh_bigrama or df[w] <= termo_raro_df_max:
                por_termo[w].add(gi)

    candidatos = set()
    for gids in por_termo.values():
        if len(gids) >= 2:
            candidatos |= gids
    return candidatos


def mesclar_entre_idiomas(grupos, chaves_por_video, videos, termo_raro_df_max):
    """Grupos foram formados por similaridade de texto dentro do MESMO idioma
    (Jaccard nao enxerga 'sobrevivendo 100 dias' == 'surviving 100 days', nem
    titulos variados demais ao redor de um termo especifico em comum). Aqui o
    Gemini olha so os resumos dos grupos (nao video a video) 1x por execucao,
    e sugere quais grupos sao o mesmo formato/assunto especifico, mesmo em
    idiomas diferentes ou com o resto do titulo bem diferente."""
    if not os.environ.get("GEMINI_API_KEY"):
        return grupos

    candidatos_ids = {gi for gi, idx in enumerate(grupos) if len(idx) >= 2}
    candidatos_ids |= candidatos_por_termo_raro(grupos, chaves_por_video, termo_raro_df_max)
    if len(candidatos_ids) < 2:
        return grupos

    candidatos_ids = sorted(candidatos_ids)
    fusoes = []
    for inicio in range(0, len(candidatos_ids), LOTE_GEMINI):
        lote_ids = candidatos_ids[inicio:inicio + LOTE_GEMINI]
        # assinatura por video (nao pelo indice de grupo, que muda a cada
        # execucao) -- se o mesmo conjunto de grupos/titulos ja foi decidido
        # antes, reaproveita a resposta em vez de chamar o Gemini de novo
        resumos = [{
            "id": gi,
            "rotulo": rotular(chaves_por_video, grupos[gi]),
            "exemplos": [videos[i]["titulo"] for i in grupos[gi][:3]],
        } for gi in lote_ids]
        payload_cache = [{"rotulo": r["rotulo"], "exemplos": r["exemplos"]} for r in resumos]
        chave = _hash_lote("mesclar_entre_idiomas", payload_cache)
        cache = _cache_buscar(chave)
        if cache is not None:
            fusoes += [[lote_ids[i] for i in fusao if 0 <= i < len(lote_ids)] for fusao in cache]
            continue
        resultado = gemini.mesclar_temas_entre_idiomas(resumos)
        # resultado vem com os ids reais de lote_ids (gemini recebe "id": gi
        # original) -- guarda no cache como posicao dentro do lote (0..N-1)
        # pra ficar independente dos indices de grupo, que sao efemeros
        posicoes = {gi: i for i, gi in enumerate(lote_ids)}
        resultado_cache = [[posicoes[gi] for gi in fusao if gi in posicoes] for fusao in resultado]
        _cache_salvar(chave, resultado_cache)
        fusoes += resultado

    if not fusoes:
        return grupos

    uf = UniaoBusca(len(grupos))
    for fusao in fusoes:
        validos = [gi for gi in fusao if 0 <= gi < len(grupos)]
        for a, b in zip(validos, validos[1:]):
            uf.unir(a, b)

    finais = collections.defaultdict(list)
    for gi, idx in enumerate(grupos):
        finais[uf.encontrar(gi)].extend(idx)
    return list(finais.values())


def rotular(chaves_por_video, indices):
    freq = collections.Counter()
    for i in indices:
        freq.update(w for w in chaves_por_video[i] if "_" not in w)
    principais = [p for p, _ in freq.most_common(3)]
    return " ".join(w.capitalize() for w in principais) if principais else "Tema sem rótulo"


def gerar_rotulos_pt(grupos_finais, chaves_por_video, videos):
    """grupos_finais: lista de indices que ja passaram no filtro min_videos/
    min_canais (so eles vao virar tema de verdade). O rotulo por palavra-chave
    (rotular()) pode sair em ingles/espanhol se o grupo for dominado por
    titulos nesses idiomas -- aqui o Gemini da 1 nome curto em portugues por
    tema, 1x por execucao (nao por video). Se a API falhar ou nao tiver
    chave configurada, mantem o rotulo por palavra-chave como fallback."""
    rotulos = {i: rotular(chaves_por_video, idx) for i, idx in enumerate(grupos_finais)}
    if not os.environ.get("GEMINI_API_KEY") or not grupos_finais:
        return rotulos

    for inicio in range(0, len(grupos_finais), LOTE_GEMINI):
        lote = list(enumerate(grupos_finais))[inicio:inicio + LOTE_GEMINI]
        itens = [{"id": i, "exemplos": [videos[v]["titulo"] for v in idx[:4]]} for i, idx in lote]
        payload_cache = [{"exemplos": item["exemplos"]} for item in itens]
        chave = _hash_lote("gerar_rotulos_pt", payload_cache)
        cache = _cache_buscar(chave)
        if cache is not None:
            for posicao, nome in cache.items():
                gi = lote[int(posicao)][0]
                if nome:
                    rotulos[gi] = nome
            continue
        traduzidos = gemini.gerar_rotulos_pt(itens)
        posicoes = {i: posicao for posicao, (i, _) in enumerate(lote)}
        resultado_cache = {str(posicoes[gi]): nome for gi, nome in traduzidos.items() if gi in posicoes}
        _cache_salvar(chave, resultado_cache)
        for gi, nome in traduzidos.items():
            if nome:
                rotulos[gi] = nome
    return rotulos


def classificar(total_videos, videos_recentes, dias_totais, cfg):
    quente_proporcao = float(cfg.get("tema_quente_proporcao", 0.5))
    evergreen_dias_minimo = int(cfg.get("tema_evergreen_dias_minimo", 120))

    if dias_totais >= evergreen_dias_minimo and videos_recentes > 0:
        return "evergreen"
    if total_videos and (videos_recentes / total_videos) >= quente_proporcao:
        return "quente"
    return "esporadico"


def main():
    _limpar_cache_antigo()

    cfg = supa.config_dict()
    min_videos = int(cfg.get("tema_min_videos", 3))
    min_canais = int(cfg.get("tema_min_canais", 2))
    similaridade_minima = float(cfg.get("tema_similaridade_minima", 0.34))
    termo_raro_df_max = int(cfg.get("tema_termo_raro_df_max", 8))
    janela_quente_dias = int(cfg.get("tema_janela_quente_dias", 30))
    # limiar bem mais frouxo que similaridade_minima -- aqui o objetivo nao e
    # decidir o tema principal do video, e so notar que ele TAMBEM toca em
    # outro tema (ex: video de "100 dias" que tambem usa o mod Verity)
    similaridade_secundaria_minima = float(cfg.get("tema_secundario_similaridade_minima", 0.15))

    todos = supa.get("videos", "id,channel_id,titulo,published_at")
    videos = [v for v in todos if v["titulo"] and v["published_at"]]
    if not videos:
        print("Nenhum video com titulo pra agrupar.")
        return

    canais_regiao = {c["id"]: c.get("regiao") for c in supa.get("channels", "id,regiao")}

    chaves_por_video = [texto.palavras_chave(v["titulo"]) for v in videos]
    grupos = agrupar(videos, chaves_por_video, similaridade_minima)
    grupos = mesclar_entre_idiomas(grupos, chaves_por_video, videos, termo_raro_df_max)

    qualificados = [
        idx for idx in grupos
        if len(idx) >= min_videos and len({videos[i]["channel_id"] for i in idx}) >= min_canais
    ]
    rotulos = gerar_rotulos_pt(qualificados, chaves_por_video, videos)

    # assinatura de cada tema = uniao das palavras-chave dos seus videos --
    # usada so pra achar afinidade SECUNDARIA (video que tambem toca em outro
    # tema alem do principal), sem custo de API: e so um jaccard local.
    membro_de = {i: gi for gi, idx in enumerate(qualificados) for i in idx}
    assinaturas_tema = [set().union(*(chaves_por_video[i] for i in idx)) if idx else set() for idx in qualificados]
    secundarios_por_video = collections.defaultdict(list)
    for vi in range(len(videos)):
        pontuacoes = []
        for gi, assinatura in enumerate(assinaturas_tema):
            if membro_de.get(vi) == gi:
                continue
            pontuacao = texto.jaccard(chaves_por_video[vi], assinatura)
            if pontuacao >= similaridade_secundaria_minima:
                pontuacoes.append((pontuacao, gi))
        pontuacoes.sort(reverse=True)
        secundarios_por_video[vi] = [gi for _, gi in pontuacoes[:TEMA_SECUNDARIO_MAX]]

    agora = datetime.datetime.now(datetime.timezone.utc)
    limite_quente = agora - datetime.timedelta(days=janela_quente_dias)

    supa.update("videos", [("neq", "id", ID_CORINGA)], {"tema_id": None})
    supa.delete("temas", [("neq", "id", ID_CORINGA)])

    criados = 0
    tema_id_por_gi = {}
    linhas_video_temas = []
    for gi, indices in enumerate(qualificados):
        vids = [videos[i] for i in indices]
        canais_distintos = len({v["channel_id"] for v in vids})

        publicados = sorted(datetime.datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")) for v in vids)
        primeiro, ultimo = publicados[0], publicados[-1]
        dias_totais = (ultimo - primeiro).days
        videos_recentes = sum(1 for p in publicados if p >= limite_quente)

        palavras_chave_grupo = sorted({w for i in indices for w in chaves_por_video[i] if "_" not in w})[:20]
        alcancou_br = any(canais_regiao.get(v["channel_id"]) == "BR" for v in vids)

        tema = supa.insert("temas", [{
            "rotulo": rotulos.get(gi) or rotular(chaves_por_video, indices),
            "palavras_chave": palavras_chave_grupo,
            "total_videos": len(vids),
            "canais_distintos": canais_distintos,
            "primeiro_video_em": primeiro.isoformat(),
            "ultimo_video_em": ultimo.isoformat(),
            "videos_ultimos_30_dias": videos_recentes,
            "classificacao": classificar(len(vids), videos_recentes, dias_totais, cfg),
            "alcancou_br": alcancou_br,
        }])[0]

        supa.update("videos", [("in_", "id", [v["id"] for v in vids])], {"tema_id": tema["id"]})
        tema_id_por_gi[gi] = tema["id"]
        linhas_video_temas += [
            {"video_id": v["id"], "tema_id": tema["id"], "principal": True} for v in vids
        ]
        criados += 1

    for vi, gis_secundarios in secundarios_por_video.items():
        for gi in gis_secundarios:
            tema_id = tema_id_por_gi.get(gi)
            if tema_id:
                linhas_video_temas.append({"video_id": videos[vi]["id"], "tema_id": tema_id, "principal": False})

    _inserir_em_lotes("video_temas", linhas_video_temas)

    print(f"Videos analisados: {len(videos)} | temas criados: {criados} | "
          f"associacoes secundarias: {sum(1 for l in linhas_video_temas if not l['principal'])}")


if __name__ == "__main__":
    main()
