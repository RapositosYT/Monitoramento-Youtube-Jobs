import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]


def analytics_client():
    """Cliente da YouTube Analytics API autenticado via OAuth (canal proprio).
    Diferente do lib/yt.py (API key), que so le dados publicos de qualquer
    canal -- esta API exige o dono do canal ter autorizado o app (ver
    scripts/local/authorize_analytics.py, rodado uma vez fora do CI)."""
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_OAUTH_REFRESH_TOKEN"],
        client_id=os.environ["YT_OAUTH_CLIENT_ID"],
        client_secret=os.environ["YT_OAUTH_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
