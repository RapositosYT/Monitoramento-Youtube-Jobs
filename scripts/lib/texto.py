import re
import unicodedata

STOPWORDS = {
    "a", "o", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "pra", "pro", "para", "com", "sem", "e", "ou",
    "que", "se", "ao", "aos", "foi", "ser", "sao", "mais", "muito",
    "tambem", "ja", "ainda", "so", "este", "esta", "isso", "esse", "essa", "meu", "minha",
    "seu", "sua", "nosso", "nossa", "eu", "ele", "ela", "voce", "voces", "nao", "sim",
    "como", "quando", "onde", "porque", "entao", "tudo", "nada", "todo", "toda", "todos",
    "todas", "vs", "the", "of", "in", "on",
}
# "mas" foi removido de proposito da lista acima: alem de conjuncao comum, e
# tambem o nome de um formato inteiro de video ("Minecraft Mas...", "Roblox
# Mas..." -- traducao do genero "X But Y" do YouTube), entao remove-lo como
# stopword apagava justamente a palavra que identifica esses temas


def _sem_acento(s):
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(titulo):
    if not titulo:
        return []
    s = _sem_acento(titulo.lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    palavras = [p for p in s.split() if len(p) > 2 and p not in STOPWORDS]
    return palavras


def palavras_chave(titulo):
    """Unigramas + bigramas do titulo, usados como assinatura pra medir
    similaridade entre videos (Jaccard). Bigramas capturam formatos que so
    fazem sentido como frase (ex: 'quem constroi', 'sobreviver dias')."""
    palavras = normalizar(titulo)
    bigramas = [f"{palavras[i]}_{palavras[i + 1]}" for i in range(len(palavras) - 1)]
    return set(palavras) | set(bigramas)


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)
