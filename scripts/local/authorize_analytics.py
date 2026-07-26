"""Gera o refresh_token da YouTube Analytics API. Rode ISSO UMA VEZ, na sua
maquina (nunca no GitHub Actions -- precisa abrir o navegador pra voce logar
e autorizar). Depois de rodar, salve o refresh_token impresso no final como
secret YT_OAUTH_REFRESH_TOKEN no repositorio do GitHub.

Requer client_id/client_secret de um OAuth Client ID tipo "Desktop app",
criado no Google Cloud Console (mesmo projeto onde a API key ja existe).

Uso:
    pip install google-auth-oauthlib
    python authorize_analytics.py <client_id> <client_secret>
"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]


def main():
    if len(sys.argv) != 3:
        print("Uso: python authorize_analytics.py <client_id> <client_secret>")
        sys.exit(1)
    client_id, client_secret = sys.argv[1], sys.argv[2]

    flow = InstalledAppFlow.from_client_config(
        {"installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }},
        scopes=SCOPES,
    )
    creds = flow.run_local_server(port=0)
    print("\nRefresh token (salve como secret YT_OAUTH_REFRESH_TOKEN):\n")
    print(creds.refresh_token)


if __name__ == "__main__":
    main()
