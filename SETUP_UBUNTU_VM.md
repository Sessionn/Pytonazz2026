# Setup Ubuntu VM

Guida operativa per installare Pytonazz su una VM Ubuntu e pubblicare la dashboard in HTTPS dietro reverse proxy. La porta `5000` non deve essere esposta a Internet.

## 1. Architettura target

```text
Internet -> 80/443 -> Caddy -> 127.0.0.1:5000 -> dashboard Flask
Discord -> main.py -> bot + cogs + resolver + cache DB
yt-dlp/FFmpeg -> stream audio Discord
SQLite -> data/database/cache.db
```

Principi:

- il bot gira dentro `venv`;
- la dashboard ascolta solo su `127.0.0.1:5000`;
- il firewall pubblico espone solo `22`, `80`, `443`;
- Caddy gestisce TLS e reverse proxy;
- yt-dlp deve essere aggiornato spesso;
- FFmpeg deve supportare le opzioni passate dal bot.

## 1.1 Configurazione VM attuale

Stato operativo verificato sulla VM:

- OS: Ubuntu 22.04 LTS;
- repo produzione: `~/Pytonazz2026`;
- branch produzione: `main-2`;
- Python: `3.10`;
- FFmpeg: serie `4.4.x` Ubuntu;
- yt-dlp: installato nel venv;
- dashboard: `127.0.0.1:5000`;
- proxy pubblico: Caddy su `80/443`;
- WARP SOCKS locale: `127.0.0.1:40000`;
- processo bot: `screen` session `pytonazz`;
- script runtime: `~/.local/bin/pytonazz-bot`;
- cookie YouTube: `/home/sessionn/cookies.txt`;
- autostart: crontab utente.

Home policy:

```text
~/
|-- Pytonazz2026/              # repo produzione
|-- .local/bin/pytonazz-bot    # start/stop/restart
|-- .local/bin/rotate-warp     # utility manuale WARP
|-- cookies.txt                # cookie YouTube aggiornabile da PC
```

Non lasciare probe Python, screen log, backup `.env`, clone temporanei o altri artifact nella root della home. Finito il debug, rimuovili.

## 2. Prerequisiti

- Ubuntu 22.04 o 24.04;
- utente con `sudo`;
- dominio o DDNS puntato alla VM, per esempio `pytonazz.duckdns.org`;
- bot Discord gia creato;
- credenziali Discord, Spotify e Groq;
- branch Git corretto gia pushato dal PC locale.

## 3. Regole rete lato cloud

Nel pannello del provider abilita:

- `TCP 22` solo dagli IP da cui ti colleghi in SSH, se possibile;
- `TCP 80` da `0.0.0.0/0`;
- `TCP 443` da `0.0.0.0/0`.

Non esporre `TCP 5000`.

## 4. Pacchetti base

```bash
sudo apt update
sudo apt install -y git ffmpeg python3 python3-venv python3-pip curl ufw
```

Verifica runtime:

```bash
python3 --version
ffmpeg -version | head -n 1
```

Nota FFmpeg: Ubuntu 22.04 installa spesso FFmpeg `4.4.2`. Il bot evita opzioni non supportate da quella versione, ma se aggiorni FFmpeg e reintroduci opzioni avanzate devi testare prima con `tools/benchmark_resolve.py`.

## 5. Clonazione repo

Esempio sotto `/opt`:

```bash
sudo mkdir -p /opt/pytonazz
sudo chown -R "$USER":"$USER" /opt/pytonazz
cd /opt/pytonazz
git clone https://github.com/TUO-ACCOUNT/TUO-REPO.git .
```

Se sulla VM usi `~/Pytonazz2026`, mantieni quel path in tutti i comandi successivi.

## 6. Ambiente virtuale

```bash
cd /opt/pytonazz
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pip install --upgrade yt-dlp
```

Verifica librerie rilevanti:

```bash
python - <<'PY'
import yt_dlp
print("yt_dlp", yt_dlp.version.__version__)
try:
    import spotipy
    print("spotipy ok")
except Exception as exc:
    print("spotipy missing", exc)
PY
```

## 7. File `.env`

Parti dal template:

```bash
cp .env.example .env
```

Variabili minime:

```env
DISCORD_TOKEN=
OWNER_ID=
DEV_IDS=
DEV_ID=
GUILD_IDS=

GROQ_API_KEY=

SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_HINT_WAIT_SECONDS=0.25
SPOTIFY_AMBIGUOUS_WAIT_SECONDS=0.75

CACHE_ENABLED=true
DB_PATH=data/database/cache.db
CACHE_TTL_DAYS=30
CACHE_MAX_ENTRIES=500

DASHBOARD_SOCKET=127.0.0.1:5000
DASH_USER=admin
DASH_PASSWORD=cambiala-subito
DASH_SECRET_KEY=
DASH_TRUST_PROXY=true
DASH_SESSION_SECURE=true
DASH_SESSION_SAMESITE=Lax
DASH_LOGIN_WINDOW_SECONDS=900
DASH_LOGIN_MAX_ATTEMPTS=5
DASH_LOG_SCANNERS=false

LOG_LEVEL=INFO
SHOW_BANNER=true
```

Genera una session key:

```bash
python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
```

Inserisci l'output in `DASH_SECRET_KEY`.

Se usi cookie per YouTube, usa un path assoluto leggibile dal processo del bot. Evita file copiati in path temporanei o con permessi solo root.

Sulla VM attuale il path ordinato per i cookie archiviati e':

```env
COOKIE_FILE=/home/sessionn/cookies.txt
```

`COOKIES_ENABLED` deve essere valorizzato solo quando vuoi davvero usare quel file. Se e' vuoto, il bot non passa cookie a yt-dlp.

## 8. Cache DB

Schema corrente: SQLite normalizzato con tracce, sorgenti, alias query e viste dashboard. La documentazione tecnica e in `CACHE_DB.md`.

Per ricrearlo da zero:

```bash
source venv/bin/activate
python tools/rebuild_cache_db.py --backup
```

Non usare `source tools/rebuild_cache_db.py --backup`: quello tenta di eseguire Python come shell script e produce errori tipo `import: command not found`.

Per manutenzione:

```bash
python tools/dedupe_cache_db.py --db data/database/cache.db
python tools/renumber_cache_ids.py --db data/database/cache.db
```

## 9. Verifica locale del bot

```bash
source /opt/pytonazz/venv/bin/activate
cd /opt/pytonazz
python main.py
```

Controlli minimi:

```bash
curl -I http://127.0.0.1:5000
python tools/benchmark_resolve.py "titolo artista"
python tools/benchmark_ytdlp.py "titolo artista"
```

Risultato desiderato:

- dashboard locale HTTP `200` o redirect login;
- benchmark resolve sotto 5-6 secondi su miss fredda YouTube;
- cover Spotify quando Spotify riconosce bene il brano;
- stream avviabile da FFmpeg senza errori su opzioni non riconosciute.

## 10. Firewall locale

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 5000/tcp
sudo ufw --force enable
sudo ufw status verbose
```

## 11. Reverse proxy HTTPS con Caddy

Installa Caddy:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
sudo apt update
sudo apt install -y caddy
```

Configura `/etc/caddy/Caddyfile`:

```caddyfile
pytonazz.duckdns.org {
    encode gzip zstd
    reverse_proxy 127.0.0.1:5000
}
```

Poi:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
sudo systemctl status caddy --no-pager
```

## 12. Service systemd

La VM attuale usa `screen` e crontab, non systemd per il bot. Questa sezione resta valida se in futuro vuoi migrare a un servizio systemd.

Crea `/etc/systemd/system/pytonazz.service`:

```ini
[Unit]
Description=Pytonazz Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=TUO_UTENTE
WorkingDirectory=/opt/pytonazz
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/pytonazz/venv/bin/python /opt/pytonazz/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Attiva:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pytonazz
sudo systemctl restart pytonazz
sudo systemctl status pytonazz --no-pager
```

Se invece usi `screen`, assicurati che lo script di start entri nel repo, attivi `venv` e lanci `python main.py`.

Setup screen usato sulla VM attuale:

```bash
mkdir -p ~/.local/bin

# Script operativo atteso:
~/.local/bin/pytonazz-bot start
~/.local/bin/pytonazz-bot stop
~/.local/bin/pytonazz-bot restart

# Alias consigliati in ~/.bashrc:
alias gp='cd ~/Pytonazz2026 && git pull && cd ~'
alias sta='~/.local/bin/pytonazz-bot start'
alias sto='~/.local/bin/pytonazz-bot stop'
alias res='~/.local/bin/pytonazz-bot restart'
alias scr='screen -r pytonazz'
alias warp-rotate='~/.local/bin/rotate-warp'

# Autostart:
(crontab -l 2>/dev/null; echo '@reboot sleep 15 && /home/sessionn/.local/bin/pytonazz-bot start') | crontab -
```

Evita `screen -L` senza `-Logfile`: crea `screenlog.0` nella directory corrente, spesso la home.

## 13. Deploy aggiornamenti

Prima di pullare:

```bash
cd /opt/pytonazz
git status --short
```

Se ci sono modifiche locali a file di codice, non fare pull alla cieca. Decidi se salvarle, committarle, stasherle o scartarle. File runtime come `cache.db-wal`, `cache.db-shm`, backup DB e log non vanno committati.

Deploy standard:

```bash
cd /opt/pytonazz
git pull --rebase
source venv/bin/activate
pip install -r requirements.txt
python -m pip install --upgrade yt-dlp
sudo systemctl restart pytonazz
sudo systemctl restart caddy
```

Con `screen`, sostituisci il restart systemd con i tuoi alias di stop/start.

Deploy standard sulla VM attuale:

```bash
gp
res
```

Se cambi dipendenze Python:

```bash
cd ~/Pytonazz2026
source venv/bin/activate
pip install -r requirements.txt
res
```

## 14. Test rete e TLS

Sulla VM:

```bash
curl -I http://127.0.0.1:5000
sudo ss -tulpn | grep -E ':80|:443|:5000'
sudo journalctl -u caddy -n 100 --no-pager
```

Dal PC:

```powershell
Test-NetConnection pytonazz.duckdns.org -Port 80
Test-NetConnection pytonazz.duckdns.org -Port 443
curl.exe -4 -I http://pytonazz.duckdns.org --connect-timeout 10 -v
curl.exe -4 -I https://pytonazz.duckdns.org --connect-timeout 10 -vk
```

Atteso:

- `80` raggiungibile;
- `443` raggiungibile;
- HTTP redirige a HTTPS;
- HTTPS risponde dalla dashboard;
- `5000` non e raggiungibile da Internet.

## 15. Troubleshooting

### Dashboard locale OK, dominio no

```bash
sudo ss -tulpn | grep -E ':80|:443|:5000'
sudo journalctl -u caddy -n 100 --no-pager
sudo ufw status verbose
```

Controlla DNS/DDNS, security group cloud, Caddy e firewall.

### `80/443` in timeout da fuori

```bash
sudo iptables -L INPUT --line-numbers -n -v
sudo nft list ruleset
```

Se ci sono regole manuali prima di `ufw`, sistemale in modo esplicito. Non aprire `5000` come scorciatoia.

### `5000` esposta

Non va bene. Deve rispondere solo in locale:

```bash
curl -I http://127.0.0.1:5000
```

### Resolve lento

Misura separatamente Spotify, yt-dlp e FFmpeg:

```bash
python tools/benchmark_resolve.py "titolo artista"
python tools/benchmark_ytdlp.py "titolo artista"
ffmpeg -version | head -n 1
```

Se `ytsearch1` da solo impiega 4-5 secondi, il collo di bottiglia e YouTube/yt-dlp/rete VM: il bot non puo arrivare stabilmente a 2-3 secondi su miss fredda senza cambiare sorgente, prewarm, download/cache preventivo o provider alternativo.

### Audio assente e FFmpeg termina subito

Se vedi errori tipo `Unrecognized option 'reconnect_max_retries'`, la versione FFmpeg non supporta quell'opzione. Aggiorna il codice o FFmpeg e ritesta. Il bot deve passare a FFmpeg solo opzioni compatibili con la VM reale.

### Copertina YouTube invece di Spotify

Controlla:

```bash
python tools/benchmark_resolve.py "titolo artista"
```

Se `spotify_probe_ms` trova titolo/artista ma la cover resta YouTube, il match Spotify non ha superato la soglia o la query e troppo ambigua. Vedi `CACHE_DB.md` e `DOCS.md` per la logica di enrichment.

## 16. Hardening minimo

- ruota tutti i segreti prima del deploy reale;
- usa password dashboard lunga e unica;
- non riusare token del bot di sviluppo;
- non esporre mai `0.0.0.0:5000`;
- tieni `DASH_SESSION_SECURE=true`;
- usa solo HTTPS pubblico;
- non committare `.env`, database runtime, log o backup.

Segreti da ruotare se finiti in file o log:

- `DISCORD_TOKEN`;
- `SPOTIFY_CLIENT_SECRET`;
- `GROQ_API_KEY`;
- `DASH_PASSWORD`;
- `DASH_SECRET_KEY`.

## 17. Checklist finale

- [ ] VM raggiungibile in SSH
- [ ] branch corretto e working tree pulito
- [ ] `ffmpeg -version` verificato
- [ ] `venv` creato
- [ ] `pip install -r requirements.txt` completato
- [ ] `yt-dlp` aggiornato nel venv
- [ ] `.env` compilato
- [ ] cache DB ricreato o migrato consapevolmente
- [ ] dashboard bindata a `127.0.0.1:5000`
- [ ] `ufw` con `22`, `80`, `443` aperte e `5000` chiusa
- [ ] Caddy attivo
- [ ] HTTPS pubblico funzionante
- [ ] servizio systemd o screen attivo
- [ ] `python tools/benchmark_resolve.py "titolo artista"` eseguito
- [ ] `/play` reale provato in Discord
- [ ] home utente pulita: repo, dotfile/cartelle utente e `cookies.txt`
- [ ] artifact temporanei eliminati dopo debug
