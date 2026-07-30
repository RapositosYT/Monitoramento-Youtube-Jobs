import json
import os

from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
_client = None
_chaves = None
_indice_chave = 0


def _lista_chaves():
    global _chaves
    if _chaves is None:
        candidatas = [os.environ.get("GEMINI_API_KEY")] + [
            os.environ.get(f"GEMINI_API_KEY_{n}") for n in (2, 3)
        ]
        _chaves = [c for c in candidatas if c]
        if not _chaves:
            raise RuntimeError("nenhuma GEMINI_API_KEY configurada")
    return _chaves


def client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=_lista_chaves()[_indice_chave])
    return _client


def _e_erro_de_limite(e):
    texto = str(e).lower()
    return any(s in texto for s in ("resource_exhausted", "429", "quota", "rate limit"))


def _gerar(prompt, mime="application/json"):
    """Chama generate_content com a chave atual; se o erro indicar limite
    atingido, roda pra proxima GEMINI_API_KEY configurada e tenta de novo,
    ate esgotar as chaves disponiveis."""
    global _indice_chave, _client
    chaves = _lista_chaves()
    ultimo_erro = None
    for tentativa in range(len(chaves)):
        try:
            return client().models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type=mime),
            )
        except Exception as e:
            ultimo_erro = e
            if _e_erro_de_limite(e) and _indice_chave + 1 < len(chaves):
                _indice_chave += 1
                _client = None
                print(f"Aviso: chave Gemini {tentativa + 1} atingiu limite, trocando pra chave {_indice_chave + 1}")
                continue
            raise
    raise ultimo_erro


MAX_FORMATOS_PROMPT = 80
MAX_DESCRICAO_FORMATO = 80


def classificar_formato(titulo, descricao, formatos_existentes):
    """formatos_existentes: lista de dicts {"nome":..., "descricao":...}.
    Retorna (nome_formato, confianca) ou (None, 0.0) se a chamada falhar."""
    # cap no numero de formatos e no tamanho da descricao de cada um -- sem
    # isso o prompt cresce sem limite conforme o catalogo de formatos aumenta.
    lista = "\n".join(
        f"- {f['nome']}: {(f.get('descricao') or '')[:MAX_DESCRICAO_FORMATO]}"
        for f in formatos_existentes[:MAX_FORMATOS_PROMPT]
    ) or "(nenhum formato cadastrado ainda)"

    prompt = f"""Voce classifica videos de Minecraft/Roblox de um canal infantojuvenil brasileiro em um FORMATO de conteudo (ex: "100 dias survival", "tycoon", "roleplay", "desafio").

Formatos ja cadastrados:
{lista}

Video para classificar:
Titulo: {titulo}
Descricao: {(descricao or "")[:300]}

Escolha o formato ja cadastrado que melhor encaixa nesse video. So proponha um formato novo se genuinamente nenhum dos existentes encaixar bem. Responda apenas com JSON no formato:
{{"formato": "nome do formato", "confianca": numero de 0.0 a 1.0}}"""

    try:
        resp = _gerar(prompt)
        data = json.loads(resp.text)
        nome = (data.get("formato") or "").strip()
        confianca = float(data.get("confianca", 0))
        return (nome or None), confianca
    except Exception as e:
        print(f"Aviso: falha ao classificar formato via Gemini: {e}")
        return None, 0.0


def mesclar_temas_entre_idiomas(grupos):
    """grupos: lista de dicts {"id": int, "rotulo": str, "exemplos": [titulos]},
    ja agrupados por similaridade de texto (podem ter so 1 video, quando o
    titulo variou demais ao redor de um termo especifico em comum, tipo nome
    de mod/personagem). Usada 1x por execucao do job3_temas (nao por video),
    pra manter o uso da API baixo mesmo com o catalogo de videos crescendo.
    Retorna lista de listas de ids que devem ser fundidos, ou [] se a chamada
    falhar ou nenhuma fusao fizer sentido."""
    if len(grupos) < 2:
        return []

    lista = json.dumps(grupos, ensure_ascii=False)
    prompt = f"""Voce recebe uma lista de grupos de titulos de video de Minecraft/Roblox, ja agrupados por similaridade de texto. Cada grupo pode ter 1 ou varios videos. Alguns grupos podem representar o MESMO formato/tema/assunto especifico de video (ex: mesmo mod, personagem, jogo especifico, evento, ou a mesma serie de desafio), mesmo que:
- estejam em idiomas diferentes (portugues, espanhol, ingles) -- ex: "sobrevivendo 100 dias" e "surviving 100 days" sao o mesmo formato;
- o resto do titulo seja bem diferente, desde que o assunto especifico seja claramente o mesmo -- ex: "Origem do Verity", "Verity X Falsity" e "the verity mod updated" sao todos sobre o mesmo mod "Verity", mesmo com titulos bem distintos entre si;
- for uma serie de desafio com "regra variavel" -- o formato/piada e sempre o mesmo, so a regra especifica de cada episodio muda. Ex: "Minecraft mas os blocos sao aleatorios", "Minecraft mas cada bloco vira um item aleatorio", "Minecraft mas eu so posso usar 1 bloco" sao todos o MESMO formato "Minecraft But/Mas", mesmo cada um tendo uma regra diferente -- NAO separe por regra especifica, junte pela serie/formato.

Grupos (id, rotulo automatico, titulos de exemplo):
{lista}

Identifique quais grupos representam o mesmo formato/tema/assunto especifico (ou a mesma serie de desafio com regra variavel) e devem ser fundidos. Responda apenas com JSON no formato:
{{"fusoes": [[id1, id2], [id3, id4, id5]]}}
Grupos que nao devem ser fundidos com nenhum outro nao precisam aparecer. Se nenhuma fusao fizer sentido, responda {{"fusoes": []}}."""

    try:
        resp = _gerar(prompt)
        data = json.loads(resp.text)
        fusoes = data.get("fusoes") or []
        return [f for f in fusoes if isinstance(f, list) and len(f) >= 2]
    except Exception as e:
        print(f"Aviso: falha ao mesclar temas entre idiomas via Gemini: {e}")
        return []


def gerar_rotulos_pt(itens):
    """itens: lista de dicts {"id": int, "exemplos": [titulos]} -- titulos de
    exemplo de um tema ja fechado (podem estar em portugues, espanhol ou
    ingles). Roda 1x por execucao do job3_temas (nao por video), pra manter o
    uso da API baixo. Retorna dict {id: rotulo em portugues}, ou {} se a
    chamada falhar (quem chama mantem o rotulo por palavra-chave como
    fallback nesse caso)."""
    if not itens:
        return {}

    lista = json.dumps(itens, ensure_ascii=False)
    prompt = f"""Voce recebe uma lista de temas/formatos de video de Minecraft/Roblox, cada um com titulos de exemplo (podem estar em portugues, espanhol ou ingles). De um nome curto e claro EM PORTUGUES pra cada tema, descrevendo o formato/assunto do video (ex: "Sobrevivendo com Verity", "100 Dias Hardcore", "Quem Constroi Mais Rapido"). Maximo 5 palavras por nome.

Temas (id, titulos de exemplo):
{lista}

Responda apenas com JSON no formato:
{{"rotulos": [{{"id": id1, "rotulo": "Nome em Portugues"}}, ...]}}"""

    try:
        resp = _gerar(prompt)
        data = json.loads(resp.text)
        return {item["id"]: item.get("rotulo") for item in data.get("rotulos", []) if item.get("rotulo")}
    except Exception as e:
        print(f"Aviso: falha ao gerar rotulos em portugues via Gemini: {e}")
        return {}
