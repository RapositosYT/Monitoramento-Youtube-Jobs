import pathlib
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(pathlib.Path(__file__).parent))
load_dotenv()
from lib.oauth import analytics_client  # noqa: E402

VIDEO_ID = "Zo18q1KgSI4"

yta = analytics_client()
resp = yta.reports().query(
    ids="channel==MINE",
    startDate="2020-01-01",
    endDate="2026-07-27",
    dimensions="elapsedVideoTimeRatio",
    metrics="audienceWatchRatio,relativeRetentionPerformance",
    filters=f"video=={VIDEO_ID}",
).execute()
linhas = resp.get("rows", [])
print(f"Linhas retornadas: {len(linhas)}")
print("Primeiras 3:", linhas[:3])
