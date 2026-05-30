# Setup completo Ubuntu VM

Guida operativa per installare Pitonazz da zero su una VM Ubuntu, con dashboard pubblicata correttamente in HTTPS dietro reverse proxy e porta `5000` non esposta.

## 1. Obiettivo finale

Architettura consigliata:

```text
Internet -> 80/443 -> Caddy -> 127.0.0.1:5000 -> dashboard
Discord bot -> processo Python separato sulla stessa VM
```

Principi:

- il bot gira dentro `venv`
- la dashboard ascolta solo su `127.0.0.1:5000`
- la porta pubblica `5000` resta chiusa
- il certificato TLS viene gestito da `Caddy`
- `ufw` consente solo `22`, `80`, `443`

## 2. Prerequisiti

- VM Ubuntu 22.04 o 24.04
- utente con `sudo`
- dominio o DDNS puntato alla VM, ad esempio `pytonazz.duckdns.org`
- bot Discord già creato
- credenziali Discord, Spotify, Groq

## 3. Regole rete lato cloud

Prima di entrare nella VM, il security layer del provider deve permettere:

- `TCP 22` da dove ti colleghi in SSH
- `TCP 80` da `0.0.0.0/0`
- `TCP 443` da `0.0.0.0/0`

Non esporre `TCP 5000`.

## 4. Accesso e pacchetti base

```bash
sudo apt update
sudo apt install -y git ffmpeg python3 python3-venv python3-pip curl ufw
```

## 5. Clonazione repo

Esempio sotto `/opt`:

```bash
sudo mkdir -p /opt/pytonazz
sudo chown -R "$USER":"$USER" /opt/pytonazz
cd /opt/pytonazz
git clone https://github.com/TUO-ACCOUNT/TUO-REPO.git .
```

Se usi una copia privata o un remote diverso, sostituisci l'URL.

## 6. Ambiente virtuale e dipendenze

```bash
cd /opt/pytonazz
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 7. File `.env`

Parti dal template:

```bash
cp .env.example .env
```

Variabili minime da configurare:

```env
DISCORD_TOKEN=
OWNER_ID=
DEV_IDS=
DEV_ID=
GUILD_IDS=

GROQ_API_KEY=

SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=

CACHE_ENABLED=true
DB_PATH=data/database/cache.db

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

Genera una chiave sessione robusta:

```bash
python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
```

Inserisci l'output in `DASH_SECRET_KEY`.

Nota: la dashboard ora rifiuta di avviarsi correttamente senza entrambe le variabili `DASH_USER` e `DASH_PASSWORD`.

## 8. Verifica locale del bot

```bash
source /opt/pytonazz/venv/bin/activate
cd /opt/pytonazz
python main.py
```

Controlli minimi:

- il bot va online su Discord
- la dashboard risponde in locale:

```bash
curl -I http://127.0.0.1:5000
```

Se questo non risponde, non passare oltre.

## 9. Firewall locale Ubuntu

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 5000/tcp
sudo ufw --force enable
sudo ufw status verbose
```

Il risultato corretto deve mostrare `80`, `443`, `22` aperte e `5000` negata.

## 10. Reverse proxy HTTPS con Caddy

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

## 11. Test rete e TLS

Sulla VM:

```bash
curl -I http://127.0.0.1:5000
sudo ss -tulpn | grep -E ':80|:443|:5000'
sudo journalctl -u caddy -n 100 --no-pager
```

Dal tuo PC:

```powershell
Test-NetConnection pytonazz.duckdns.org -Port 80
Test-NetConnection pytonazz.duckdns.org -Port 443
curl.exe -4 -I http://pytonazz.duckdns.org --connect-timeout 10 -v
curl.exe -4 -I https://pytonazz.duckdns.org --connect-timeout 10 -vk
```

Risultato atteso:

- `80` raggiungibile
- `443` raggiungibile
- `http://...` risponde con `308`
- `https://...` risponde con `200`

## 12. Service systemd del bot

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

Attiva il servizio:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pytonazz
sudo systemctl restart pytonazz
sudo systemctl status pytonazz --no-pager
```

## 13. Aggiornamento deploy

```bash
cd /opt/pytonazz
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart pytonazz
sudo systemctl restart caddy
```

## 14. Troubleshooting rapido

### Dashboard locale OK, dominio no

Controlla:

```bash
sudo ss -tulpn | grep -E ':80|:443|:5000'
sudo journalctl -u caddy -n 100 --no-pager
sudo ufw status verbose
```

### `80/443` in timeout da fuori

Controlla:

- regole cloud in ingresso su `80/443`
- `ufw`
- eventuali regole legacy `iptables`

Verifica:

```bash
sudo iptables -L INPUT --line-numbers -n -v
sudo nft list ruleset
```

Se trovi regole manuali prima di `ufw`, rimuovile e correggi il file persistente.

### `5000` esposta o raggiungibile da Internet

Non è corretto. Deve rispondere solo su loopback:

```bash
curl -I http://127.0.0.1:5000
```

e non deve essere aperta nel firewall pubblico.

## 15. Hardening minimo consigliato

- ruota tutti i segreti prima del deploy reale
- usa password dashboard lunga e unica
- non riusare token o chiavi del bot di sviluppo
- non esporre mai `0.0.0.0:5000`
- tieni `DASH_SESSION_SECURE=true`
- usa solo HTTPS pubblico

Segreti da ruotare se mai finiti in file o log:

- `DISCORD_TOKEN`
- `SPOTIFY_CLIENT_SECRET`
- `GROQ_API_KEY`
- `DASH_PASSWORD`
- `DASH_SECRET_KEY`

## 16. Checklist finale

- [ ] VM raggiungibile in SSH
- [ ] `ffmpeg` installato
- [ ] `venv` creato
- [ ] `pip install -r requirements.txt` completato
- [ ] `.env` compilato
- [ ] dashboard bindata a `127.0.0.1:5000`
- [ ] `ufw` con `22`, `80`, `443` aperte e `5000` chiusa
- [ ] `Caddy` attivo
- [ ] `https://dominio` risponde
- [ ] servizio `systemd` attivo
