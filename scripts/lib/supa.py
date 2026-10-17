import os
from supabase import create_client

PAGE = 1000
_client = None


def client():
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _client


def _apply(query, filters):
    for op, col, val in filters or []:
        if op == "not_is":
            query = query.not_.is_(col, val)
        else:
            query = getattr(query, op)(col, val)
    return query


def get(table, select="*", filters=None):
    rows, offset = [], 0
    while True:
        q = _apply(client().table(table).select(select), filters)
        r = q.range(offset, offset + PAGE - 1).execute()
        rows += r.data
        if len(r.data) < PAGE:
            return rows
        offset += PAGE


def ultimo(table, select, filters, order_col):
    """Linha mais recente por order_col, sem baixar o resto do historico."""
    q = _apply(client().table(table).select(select), filters)
    rows = q.order(order_col, desc=True).limit(1).execute().data
    return rows[0] if rows else None


def insert(table, rows):
    if not rows:
        return []
    return client().table(table).insert(rows).execute().data


def upsert(table, rows, on_conflict):
    if not rows:
        return []
    return client().table(table).upsert(rows, on_conflict=on_conflict).execute().data


def update(table, filters, data):
    _apply(client().table(table).update(data), filters).execute()


def delete(table, filters):
    _apply(client().table(table).delete(), filters).execute()


def config_dict():
    return {c["chave"]: c["valor"] for c in get("config")}
