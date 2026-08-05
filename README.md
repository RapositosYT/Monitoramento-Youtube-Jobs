# Monitoramento-Youtube-Jobs

Jobs de coleta (YouTube Data API → Supabase) do sistema de inteligência RapoIQ.
Este repositório é público só pra ter minutos de GitHub Actions ilimitados —
o dashboard, o schema do banco e a lista de canais monitorados continuam no
repositório privado principal.

## Estrutura

- `scripts/job1_descoberta.py` — descobre vídeos novos (playlistItems) + snapshot de canal em `channel_snapshots`; classifica o formato de cada vídeo novo via Gemini.
- `scripts/job2_stats.py` — snapshot de stats em `video_snapshots` (views/likes/comentários), velocidade de views/h, checkpoint mais próximo, desvio vs média histórica do canal, detecção de mudança de título/thumbnail, downsampling, recálculo de `tier_efetivo`/`corredor_estagio`.
- `scripts/job3_temas.py` — agrupamento de vídeos por tema/formato.
- `scripts/backfill_duracao.py` — preenche duração de vídeos antigos.
- `scripts/lib/` — clientes Supabase, YouTube e Gemini (cópia do repositório privado).

## Rodar localmente

Crie um `.env` com as chaves usadas pelos jobs (`YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY`).

```
pip install -r requirements.txt
python scripts/job1_descoberta.py
```

## Workflows (Actions)

Todos disparados via `workflow_dispatch`, agendados externamente pelo cron-job.org (agendamento nativo do GitHub Actions não era confiável no minuto 0/horário cheio).

| Workflow | Secrets usados | Frequência (cron-job.org) |
|---|---|---|
| Job 1 - Descoberta | `YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY` | a cada 30min |
| Job 2 - Stats | `YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` | de hora em hora |
| Job 3 - Temas | `SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY` | 1x/dia, 14h |
| Job Meu Canal | `YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` | 4x/dia (0h/6h/12h/18h) |
| Job Meu Canal Analytics | `YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` | 2x/dia (0h/12h) |
| Job Noticias | `SUPABASE_URL`, `SUPABASE_KEY` | 1x/dia, 8h |
| Job Roblox | `SUPABASE_URL`, `SUPABASE_KEY` | 4x/dia (1h/7h/13h/19h) |
| Backfill Duracao | `YOUTUBE_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` | manual |

Configure essas secrets em Settings → Secrets and variables → Actions deste repositório.
