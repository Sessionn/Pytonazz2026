# Pytonazz Alert Monitor

Sistema isolato per avvisi realtime su telefono tramite ntfy self-hosted.

Non modifica `main.py`, `core/`, `cogs/` o la logica del bot. Legge un file log e invia una notifica HTTPS quando trova warning, errori, traceback, problemi FFmpeg o problemi YouTube/cookie.

## Cosa installare sulla VM

Installa ntfy sulla VM e pubblicalo dietro Caddy. Esempio Caddy, sullo stesso dominio della dashboard:

```caddyfile
tuo-dominio.example.com {
    encode gzip zstd

    handle_path /ntfy/* {
        reverse_proxy 127.0.0.1:2586
    }

    reverse_proxy 127.0.0.1:5000
}
```

Con questa configurazione l'endpoint alert diventa:

```text
https://tuo-dominio.example.com/ntfy/<topic-segreto>
```

Sul telefono installa l'app ntfy e iscriviti allo stesso topic segreto.

## Configurazione monitor

Copia `monitoring/config.example.env` in `monitoring/.env` sulla VM e cambia:

```env
PYTONAZZ_ALERT_BASE_URL=https://tuo-dominio.example.com/ntfy
PYTONAZZ_ALERT_TOPIC=topic-lungo-random-non-indovinabile
PYTONAZZ_MONITOR_LOG=/home/sessionn/Pytonazz2026/monitoring/bot.log
PYTONAZZ_ALERT_PROFILES=/home/sessionn/Pytonazz2026/monitoring/alert_profiles.json
```

`PYTONAZZ_ALERT_TOKEN` resta vuoto se proteggi il topic solo con nome lungo e HTTPS. Se abiliti auth ntfy, metti qui il token bearer.

## Personalizzazione messaggi

Copia l'esempio:

```bash
cp monitoring/alert_profiles.example.json monitoring/alert_profiles.json
```

Poi modifica `monitoring/alert_profiles.json`. Per ogni tipo problema puoi cambiare:

- `label`: titolo breve;
- `emoji`: simbolo visibile nel titolo e nel corpo;
- `tags`: tag ntfy, spesso renderizzati come icone;
- `summary`: spiegazione umana;
- `checks`: puntatori operativi da seguire.

Il file reale `monitoring/alert_profiles.json` e' ignorato da Git, quindi puoi tenerci testi privati o note specifiche della VM.

## Prova senza inviare notifiche

```bash
cd ~/Pytonazz2026
python -m monitoring.simulate_alerts --log monitoring/sample-bot.log
python -m monitoring.log_monitor --log monitoring/sample-bot.log --state monitoring/sample-state.json --profiles monitoring/alert_profiles.example.json --once --dry-run --cooldown 0
```

## Prova con notifica vera

```bash
cd ~/Pytonazz2026
set -a
source monitoring/.env
set +a
python -m monitoring.simulate_alerts --log monitoring/sample-bot.log
python -m monitoring.log_monitor --log monitoring/sample-bot.log --state monitoring/sample-state.json --profiles monitoring/alert_profiles.example.json --once --cooldown 0
```

## Avvio continuo

Usa `monitoring/pytonazz-alert-monitor.service.example` come base per un servizio systemd.

Il monitor salva solo offset e cooldown in `monitoring/.alert-monitor-state.json`, cosi non rimanda le stesse righe dopo un restart.

## Log del bot senza toccare main.py

Se il processo attuale non produce un file log, puoi avviare il bot con:

```bash
cd ~/Pytonazz2026
bash monitoring/run_bot_with_log.sh
```

Di default scrive in:

```text
monitoring/logs/bot.log
```

In quel caso imposta:

```env
PYTONAZZ_MONITOR_LOG=/home/sessionn/Pytonazz2026/monitoring/logs/bot.log
PYTONAZZ_ALERT_PROFILES=/home/sessionn/Pytonazz2026/monitoring/alert_profiles.json
```
