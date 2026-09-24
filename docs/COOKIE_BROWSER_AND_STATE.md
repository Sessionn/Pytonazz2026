# Browser cookie e stato persistente

## Browser dedicato sulla VM

Eseguire `bash scripts/setup_cookie_browser.sh` dalla repository Linux. Richiede
Docker, systemd utente e il venv del bot. L'immagine ufficiale Chromium è fissata
a una versione e il profilo è conservato nel volume `pytonazz-cookie-profile`.

Dal PC aprire il tunnel:

```powershell
ssh -N -L 17900:127.0.0.1:17900 pytonazz
```

Visitare `http://127.0.0.1:17900/vnc.html`, password noVNC `secret`, e accedere
manualmente a YouTube. Non chiudere il browser e lasciare la scheda su YouTube.
Google può richiedere una nuova autenticazione o rifiutare un browser automatizzato:
il servizio non risolve CAPTCHA, non conserva password e non aggira queste richieste.

Le porte 17900 (interfaccia) e 14444 (WebDriver) sono legate esclusivamente a
127.0.0.1 sulla VM. Non pubblicarle attraverso firewall o reverse proxy.

`monitoring.cookie_browser` è eseguito dal servizio utente
`pytonazz-cookie-browser.service`. Attende il login senza interromperlo, poi ogni
15 minuti aggiorna la pagina, esporta soltanto i cookie YouTube e verifica
l'audio usando la sonda del bot. Solo un risultato positivo sostituisce
atomicamente `COOKIE_FILE`, con permessi 600 e backup `.last-good`. Un test
negativo conserva il file precedente. Il resolver legge i cookie a ogni nuova
estrazione e non riscrive il file alla chiusura, evitando di annullare il rinnovo.

Controllo: `journalctl --user -u pytonazz-cookie-browser -n 20`.
Arresto: `systemctl --user stop pytonazz-cookie-browser` e
`docker stop pytonazz-cookie-browser`.

Non è una garanzia di cookie perpetui o di accesso a ogni video. È rinnovo da una
sessione autorizzata, soggetto alle decisioni di Google e ai controlli YouTube.
Riferimenti: [yt-dlp, cookie YouTube](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)
e [immagini ufficiali Selenium](https://github.com/SeleniumHQ/docker-selenium).

## Ripristino dello stato

La presenza normale (attività e online/idle/dnd/invisible) viene salvata con le
impostazioni del bot dopo ogni applicazione. Al riavvio e alla riconnessione viene
ripristinata prima della rotazione; la prima rotazione attende l'intervallo
configurato. La manutenzione resta prioritaria e conserva la presenza normale
da ripristinare alla sua disattivazione. `/status set` mantiene la semantica
esistente: dura fino al successivo ciclo di rotazione.

La scrittura delle impostazioni usa file temporaneo, flush e sostituzione atomica;
snapshot e valori di default sono copie profonde. Non riguarda code musicali o
riconnessione automatica ai canali vocali. Gli stati persi prima di questa versione
non possono essere ricostruiti retroattivamente.

## Revisione sommaria

Controllati entry point, collegamenti dei nuovi moduli, chiusura dei resolver,
persistenza, login, fallback grafico e regressioni con la suite della repository.
I moduli wrapper compatibili sono mantenuti: essere brevi non li rende inutili.
Questo controllo non certifica ogni ramo possibile o ogni integrazione esterna;
nessuna cancellazione indiscriminata dei file non coperti dai test.
