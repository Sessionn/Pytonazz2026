# 🐍 Pytonazz 2026

> Bot Discord multiuso scritto in Python — musica, AI, TTS, moderazione e molto altro.

---

## ✨ Funzionalità

- 🎵 **Musica** — YouTube, Spotify (track/playlist/album/artista), SoundCloud, filtri audio dedicati (`/nightcore`, `/vaporwave`, `/audio8d`, `/bassboost`, `/trebleboost`, `/vocalboost`, `/radio`, `/nightmode`, `/filteroff`), `/seek` relativo, loop, `/shuffle` casuale e `/smartshuffle` stile Spotify per artisti, `/autoplay` intelligente a fine coda, coda fino a 200 tracce, `/search` con menu select, `/versions` per alternative, `/artistshuffle` radio artista
- 🤖 **AI** — risponde alle @mention e ai DM con fallback a più provider (Gemini primary/fallback + Groq emergency), memoria conversazionale per canale e tono colloquiale diretto
- 🔊 **TTS** — text-to-speech con voci neurali Microsoft Edge in italiano e inglese
- 👋 **Welcome/Goodbye** — embed personalizzabili per server, con placeholder dinamici e AutoRole
- 🎂 **Compleanni** — tracciamento e notifiche automatiche giornaliere per server
- 🛡️ **Moderazione** — `/purge`, `/ruolo` con controlli gerarchia
- 🎲 **Fun** — roulette, sondaggi, 8ball, generatore card citazioni (immagine PNG)
- ❓ **Help** — sistema `/help` interattivo paginato con menu Discord per categoria
- 🔧 **Pannello Dev** — gestione comandi, status, backup config, manutenzione (solo owner)

---

## 🚀 Avvio Rapido

```bash
git clone https://github.com/Sessionn/Pytonazz2026
cd Pytonazz2026
pip install -r requirements.txt
```

Crea un file `.env` nella root:

```env
DISCORD_TOKEN=il_tuo_token

# Opzionale — OWNER_ID + DEV_IDS (CSV). DEV_ID resta alias legacy.
OWNER_ID=il_tuo_id_discord
DEV_IDS=il_tuo_id_discord,altro_id
DEV_ID=il_tuo_id_discord  # alias legacy/fallback

# Opzionale
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
GEMINI_API_KEY=...
GROQ_API_KEY=...
YTDLP_PROXY=socks5://127.0.0.1:40000  # solo per VM/VPS
FFMPEG_PROXY=http://127.0.0.1:3128   # opzionale (fallback su YTDLP_PROXY solo se HTTP/HTTPS)
```

```bash
python main.py
```

> Richiede **Python 3.10+** e **FFmpeg** installato nel sistema.

---

## 📚 Documentazione

Per la documentazione tecnica completa — architettura, meccanismi interni, guida ai comandi, configurazione dettagliata e istruzioni di manutenzione:

**[→ DOCS.md](./DOCS.md)**

> Convenzione: **README** resta una panoramica rapida, **DOCS.md** è la fonte tecnica completa.

### Merge su `main` (workflow consigliato)

1. Apri la PR del branch di lavoro (es. `copilot/fix-music-logical-errors`)
2. Fai review + CI green
3. Premi **Merge** su GitHub
4. In locale:

```bash
git checkout main
git pull origin main
```

---

## 📁 Struttura

```
Pytonazz2026/
├── main.py          ← Entrypoint
├── config.py        ← Configurazione e variabili d'ambiente
├── core/            ← Moduli interni (player, resolver, AI, queue...)
├── cogs/            ← Funzionalità del bot (auto-caricati)
├── embeds/          ← Embed Discord
├── views/           ← Bottoni e UI interattiva
├── assets/          ← Status, prompt AI, config runtime
├── data/            ← Dati runtime locali (welcome_config, immagini welcome, tmp)
└── DOCS.md          ← Documentazione tecnica completa
```

## 🧭 Convenzioni naming

- Repository: `Pytonazz2026` (nome progetto su GitHub)
- Nome bot mostrato agli utenti: `Pitonazz`
- Namespace logger Python: `pitonazz.*` (minuscolo)

## 🗂️ Script operativi

- `scripts/deploy_commands.py` → script **manuale/emergency** per forzare la sync slash commands.
- `scripts/update_ytdlp.sh` → script **maintenance** per aggiornamento rapido `yt-dlp`.
- `tools/audit_architecture.py` → audit rapido **periodico** su coupling cog→cog e duplicazioni logiche.

## 🧩 Strategia Refactor

- Niente refactor massivo preventivo.
- Refactor a settori solo quando ci sono segnali tecnici chiari (duplicazioni, coupling cog→cog, complessità eccessiva, fix/test con side-effect).
- Audit periodico consigliato:

```bash
python tools/audit_architecture.py
```

- Linea guida completa in `DOCS.md` (sezione **10.8**).

---

## 🛠️ Tecnologie

`discord.py 2.x` · `yt-dlp` · `spotipy` · `edge-tts` · `google-genai` · `groq` · `Pillow` · `FFmpeg` · `watchdog` · `davey`
