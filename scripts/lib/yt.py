import os
import re

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

_client = None


def client():
    global _client
    if _client is None:
        _client = build(
            "youtube", "v3",
            developerKey=os.environ["YOUTUBE_API_KEY"],
            cache_discovery=False,
        )
    return _client


def channels_info(channel_ids):
    out = {}
    for i in range(0, len(channel_ids), 50):
        data = client().channels().list(
            part="snippet,contentDetails,statistics",
            id=",".join(channel_ids[i:i + 50]),
            maxResults=50,
        ).execute()
        for it in data.get("items", []):
            st = it.get("statistics", {})
            sn = it.get("snippet", {})
            th = sn.get("thumbnails", {})
            thumb = (th.get("high") or th.get("medium") or th.get("default") or {}).get("url")
            out[it["id"]] = {
                "nome": sn.get("title"),
                "uploads_playlist_id": it["contentDetails"]["relatedPlaylists"]["uploads"],
                "thumbnail_url": thumb,
                "subs": int(st.get("subscriberCount", 0)),
                "total_views": int(st.get("viewCount", 0)),
                "qtd_videos": int(st.get("videoCount", 0)),
            }
    return out


def playlist_recent(playlist_id, max_results=10):
    try:
        data = client().playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=max_results,
        ).execute()
    except HttpError as e:
        if e.resp.status == 404:
            return []
        raise
    return [it["contentDetails"]["videoId"] for it in data.get("items", [])]


def playlist_all(playlist_id):
    """Pagina a playlist inteira (usado pro canal proprio, onde queremos o
    catalogo completo -- diferente de playlist_recent, usado pra descoberta
    continua de concorrentes)."""
    ids, token = [], None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
        if token:
            params["pageToken"] = token
        try:
            data = client().playlistItems().list(**params).execute()
        except HttpError as e:
            if e.resp.status == 404:
                return ids
            raise
        ids += [it["contentDetails"]["videoId"] for it in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token:
            return ids


def videos_info(video_ids):
    out = {}
    for i in range(0, len(video_ids), 50):
        data = client().videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(video_ids[i:i + 50]),
        ).execute()
        for it in data.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            th = sn.get("thumbnails", {})
            thumb = (th.get("maxres") or th.get("high") or th.get("medium")
                     or th.get("default") or {}).get("url")
            out[it["id"]] = {
                "titulo": sn["title"],
                "descricao": sn.get("description", ""),
                "published_at": sn["publishedAt"],
                "thumbnail_url": thumb,
                "duracao_s": _iso_duration_s(it["contentDetails"].get("duration")),
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comentarios": int(st.get("commentCount", 0)),
            }
    return out


def _iso_duration_s(d):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return dd * 86400 + h * 3600 + mi * 60 + s
