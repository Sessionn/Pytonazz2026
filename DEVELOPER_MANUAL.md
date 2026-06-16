# Pytonazz2026 Developer Manual

Manuale tecnico unico per sviluppare, modificare e verificare Pytonazz2026.
Il README resta la panoramica rapida; questo documento descrive come funziona il
bot e quali punti toccare quando si aggiungono comandi, flussi o integrazioni.

## 1. Stack e responsabilita

- Python 3.10+.
- `discord.py` gestisce bot, slash command, voice, UI e interaction lifecycle.
- `yt-dlp` risolve YouTube, SoundCloud e stream audio temporanei.
- `spotipy` recupera metadata Spotify; Spotify non fornisce audio riproducibile.
- FFmpeg riproduce gli stream su Discord voice.
- SQLite in `core/cache_db.py` conserva tracce, sorgenti, alias e stream URL.
- Flask/Waitress espone dashboard cache e console DJ.
- Groq, Edge TTS e Pillow servono per AI, TTS e quote card.

## 2. Avvio runtime

Sequenza principale:

1. `main.py` carica `.env`.
2. `config.py` costruisce `Config` e normalizza path, proxy, cookie, cache e dashboard.
3. `setup_logging()` in `core/log_colors.py` prepara log colorati e compatibili UTF-8.
4. `ensure_runtime_dirs()` crea cartelle runtime.
5. `init_db(enabled=Config.CACHE_ENABLED)` inizializza SQLite.
6. `start_dashboard_thread()` avvia Waitress se cache/dashboard sono abilitate.
7. `load_extensions()` carica i cogs da `core/runtime.py`.
8. `on_ready()` avvia hot reload, cookie watchdog, status rotation e sync comandi.

## 3. Struttura file

- `main.py`: entrypoint, bot object, eventi globali, status rotation.
- `config.py`: unica fonte per env var e opzioni yt-dlp/FFmpeg.
- `cogs/`: slash command e listener Discord per dominio.
- `core/`: logica condivisa e testabile.
- `core/source_resolver/`: resolver musica, Spotify, yt-dlp e scoring.
- `core/music/`: player voice, queue, filtri live, input parser.
- `ui/`: embed e view Discord.
- `data/database/dashboard/`: dashboard Flask e console DJ web.
- `tools/`: audit, benchmark e manutenzione cache.
- `tests/`: test script-style eseguibili direttamente con Python.

## 4. Aggiungere un comando custom

1. Scegli il cog giusto. Se il comando e' musicale usa `cogs/music.py`; se e'
   owner/dev usa `cogs/dev.py` o un cog dedicato.
2. Metti la logica riusabile in `core/`, non dentro un altro cog.
3. Usa `@app_commands.command` o un `Group` esistente.
4. Applica permessi con `core.permissions` o `core.cmd_perm.perm()`.
5. Rispondi alle interaction con `defer()` se l'operazione puo' superare pochi secondi.
6. Logga con `log.info(tag("LABEL", "..."))`, mai con messaggi grezzi.
7. Aggiungi test statico o unitario in `tests/`.
8. Se il comando deve apparire in help, aggiorna `embeds/help_embeds.py` o `ui/help`.

Pattern minimo:

```python
from discord import app_commands
from discord.ext import commands

from core.cmd_perm import perm
from core.log_colors import tag, b


class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="my_command", description="Descrizione breve")
    @perm("admin")
    async def my_command(self, inter, valore: str):
        await inter.response.defer(ephemeral=True)
        log.info(tag("CMD", f"my_command valore={b(valore)} by={inter.user}"))
        await inter.followup.send("Fatto.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(MyCog(bot))
```

Se crei un nuovo cog, aggiungilo a `DEFAULT_COGS` in `core/runtime.py`.

## 5. Flusso `/play`

Percorso direct play:

1. `cogs/music.py` normalizza input e assicura connessione voice.
2. `SourceResolver.resolve_choices(query, requester, requester_id, n=1)` parte cache-first.
3. Se SQLite ha uno stream URL valido, ritorna immediatamente.
4. Se serve un refresh, `_fetch_stream_url(webpage_url)` aggiorna stream temporaneo.
5. Se cache miss, il resolver avvia Spotify hint quando configurato.
6. yt-dlp esegue `ytsearch1` per minimizzare latenza cold miss.
7. Lo scoring decide se applicare metadata Spotify: `full`, `cover_only`, `cover_link`,
   `link_only` o `skip`.
8. Il risultato viene salvato in cache se `n == 1`.
9. `MusicPlayer.play_next()` usa `track.stream_url` o `resolve_fresh_url()`.
10. FFmpeg riproduce lo stream e il player prefetch-a la prossima traccia.

## 6. Resolver e confronto con altri bot musicali

Bot basati su Lavalink/LavaSrc usano spesso il modello "mirror": metadata da
Spotify/Apple/Deezer e playback da una sorgente diretta. Pytonazz segue lo stesso
principio, ma lo implementa localmente con `spotipy` + `yt-dlp`.

Scelte da mantenere:

- Cache-first per query singole.
- `ytsearch1` sul direct play per ridurre cold start.
- `ytsearch3` solo per fallback o selezione candidato.
- Spotify come hint, non come sorgente audio.
- Guardrail contro versioni non richieste, video musicali e query non musicali.
- Prefetch della prossima traccia nel player.

Scelte da evitare senza refactor maggiore:

- Passare a Lavalink solo per "ottimizzare": richiede nodo esterno, client,
  configurazione e nuova superficie operativa.
- Aumentare sempre `ytsearchN`: migliora scelta candidato ma peggiora latenza.
- Aspettare sempre Spotify prima di YouTube: migliora metadata ma peggiora direct play.

## 7. Cache e concorrenza

`core/cache_db.py` salva:

- `cache_tracks`: identita logica.
- `cache_sources`: URL riproducibili, stream temporanei, metadata.
- `cache_queries`: query osservate e alias.

Il resolver ha anche cache in memoria:

- `_ytdlp_query_cache`: risultati yt-dlp per query breve.
- `_stream_url_cache`: stream URL da webpage URL.
- `_ytdlp_query_inflight`: coalescing di richieste yt-dlp simultanee uguali.
- `_stream_url_inflight`: coalescing di refresh stream simultanei uguali.

Il coalescing evita che due richieste identiche lancino due estrazioni yt-dlp
mentre la prima e' ancora in corso. Il primo thread lavora; gli altri aspettano
un `threading.Event` e poi leggono dalla cache.

## 8. Player, queue e filtri

`core/music/player.py` gestisce:

- stato corrente (`current`, posizione, pausa, volume);
- `MusicQueue` con loop, shuffle, history;
- stream URL reuse e refresh;
- FFmpeg source wrapping con `LivePCMTransform`;
- filtri live, EQ e tone filters;
- prefetch della prossima traccia;
- retry su errore FFmpeg con invalidazione cache.

Regole pratiche:

- Non bloccare il loop asyncio con I/O diretto; usa executor.
- Non chiamare Discord API dal thread FFmpeg: usa `run_coroutine_threadsafe`.
- Se cambi seek/filter/replay, aggiorna posizione e stato pubblico.
- Se invalidi uno stream, invalida anche cache memoria e DB.

## 9. Dashboard e console DJ

`data/database/dashboard/app.py` espone:

- login/logout dashboard;
- API stats, songs, aliases, tracks, sources, queries e schema;
- associazione manuale Spotify;
- console DJ con OAuth Discord;
- Server-Sent Events per aggiornamenti player.

La console DJ passa da `core/dj_access.py`, che:

- risolve il cog Music;
- trova il player per guild;
- verifica ruolo DJ da `core/dj_role_store.py`;
- pubblica snapshot e azioni player.

## 10. Logging

Usa sempre:

```python
log = logging.getLogger("pitonazz.nome_modulo")
log.info(tag("LABEL", f"messaggio compatto valore={valore}"))
```

Regole:

- niente `log.info("x %s", value)` nei moduli del bot;
- niente log grezzi senza `tag()`;
- includi ID e stato, ma evita payload enormi;
- tronca titoli/testi lunghi con helper locali se necessario;
- per tool CLI preferisci intestazioni ASCII;
- verifica con `python tools/check_logs.py --strict`.

## 11. Test e audit locali

Su Windows usa l'interprete richiesto:

```powershell
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' -m compileall -q .
Get-ChildItem tests -Filter *.py | ForEach-Object {
  & 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' $_.FullName
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Audit:

```powershell
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' tools\check_logs.py --strict
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' tools\audit_architecture.py
```

Test mirati dopo resolver/player:

```powershell
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' tests\test_resolver_ytdlp_cache_shared_requesters.py
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' tests\test_resolver_spotify_fast_path.py
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' tests\test_stream_expiry.py
```

Benchmark resolver e primo frame:

```powershell
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' tools\benchmark_resolve.py "Espresso Sabrina Carpenter"
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' tools\benchmark_cache_roundtrip.py "Espresso Sabrina Carpenter"
$env:DB_PATH = 'C:\tmp\pytonazz_e2e_bench.db'
$env:CACHE_ENABLED = 'true'
& 'C:\Users\Sergio\AppData\Local\Programs\Python\Python310\python.exe' tools\benchmark_end_to_end.py "Espresso Sabrina Carpenter"
```

`benchmark_resolve.py` disabilita la cache e misura il cold path. `benchmark_cache_roundtrip.py`
usa un DB temporaneo, misura prima resolve cold e poi resolve warm/cache immediato.
`benchmark_end_to_end.py` misura resolve, eventuale refresh stream, bootstrap FFmpeg e primo
frame PCM. Il cold path verso YouTube non puo' essere garantito sotto una soglia fissa se
yt-dlp viene rallentato da rete, rate limit, cookie scaduti o challenge anti-bot.

## 12. Test su VM

Non sporcare `~/Pytonazz2026` in produzione per prove non ancora mergeate.
Usa un clone temporaneo:

```bash
tmp=$(mktemp -d /tmp/pytonazz-codex.XXXXXX)
git clone ~/Pytonazz2026 "$tmp/repo"
cd "$tmp/repo"
~/Pytonazz2026/venv/bin/python -m py_compile core/source_resolver/__init__.py
~/Pytonazz2026/venv/bin/python tests/test_resolver_ytdlp_cache_shared_requesters.py
~/Pytonazz2026/venv/bin/python tools/check_logs.py --strict
DB_PATH=/tmp/pytonazz_e2e_bench_vm.db CACHE_ENABLED=true ~/Pytonazz2026/venv/bin/python tools/benchmark_end_to_end.py "Espresso Sabrina Carpenter"
rm -rf "$tmp"
```

Se la VM restituisce errori yt-dlp come `Sign in to confirm you're not a bot`, aggiorna prima
cookie/proxy o usa un provider audio esterno. Sharding e thread aiutano la concorrenza tra
richieste, ma non eliminano una challenge remota su una singola risoluzione cold.

Per deploy reale:

```bash
cd ~/Pytonazz2026
git pull
source venv/bin/activate
pip install -r requirements.txt
python -m py_compile config.py main.py
res
```

## 13. Refactor e omologazione

Stato architetturale attuale:

- `cogs/` non importa altri `cogs/`.
- Wrapper legacy come `core/player.py`, `core/queue.py`, `core/music_input.py`,
  `core/welcome_*.py` e `core/moderation_*.py` restano compatibili e delegano ai
  moduli nuovi.
- La logica nuova deve preferire i package `core/music/`, `core/welcome/` e
  `core/moderation/`.

Prima di spostare file:

1. Cerca import esistenti con `rg`.
2. Aggiungi wrapper compatibile solo se serve davvero.
3. Aggiorna test e docs nello stesso cambio.
4. Esegui `tools/audit_architecture.py`.

## 14. Checklist prima di merge

- `git status --short` non contiene artifact runtime.
- `python -m compileall -q .` passa.
- Tutti i test in `tests/` passano.
- `tools/check_logs.py --strict` passa.
- `tools/audit_architecture.py` non segnala accoppiamenti o duplicazioni.
- Se tocchi resolver/player, hai testato almeno un caso cache, uno Spotify e uno stream.
- Se tocchi dashboard, hai eseguito `test_dashboard_api.py` e `test_dashboard_security.py`.
- Se tocchi VM/deploy, hai rimosso clone temporanei e log/probe da `/tmp` o home.
