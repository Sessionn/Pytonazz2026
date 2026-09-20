# Dashboard: animazione e fluidità — 20 settembre 2026

Questo documento aggiorna la parte web dell'audit del 20 settembre. Il modello e il motore descritti qui sostituiscono la prima implementazione del serpente.

## Correzioni

- Il renderer precedente creava array e triangoli a ogni frame e limitava il disegno a circa 30 fps. La nuova superficie indicizzata viene caricata una sola volta sulla GPU; durante l'animazione cambiano soltanto 64 punti di controllo. Il rendering segue `requestAnimationFrame`, senza limite fisso a 30 fps.
- Tabelle: le risposte non svuotano più i risultati durante il caricamento. Righe invariate, immagini e pulsanti mantengono identità e focus. Le celle cambiate vengono aggiornate; riordini e paginazione rispettano l'ordine restituito dal server. Rimane la protezione contro risposte fuori ordine.
- Eliminati ritardi progressivi sulle righe e riavvii forzati delle animazioni dei contatori. Ogni contatore cancella la propria animazione precedente. Le sezioni hanno una breve transizione di opacità/posizione e spazio minimo per i risultati.
- Login: il puntatore guida il muso, con velocità limitata e seguito articolato del corpo. Il focus sul nickname porta il serpente attorno al campo. Il focus sulla password lo raccoglie sul bordo destro, con la coda sollevata davanti agli occhi. Nessuna lettura dei valori dei campi da parte del renderer.
- Dopo il login il serpente raggiunge la propria area e non segue più il mouse. Quando questa area è fuori schermo, oppure la scheda è nascosta, il ciclo di rendering si ferma. Pausa e movimento ridotto sono rispettati.

## Modello e limiti visivi

Il modello iniziale generato nel browser è stato sostituito con un asset realizzato in Blender 4.5: progetto modificabile, superficie ad alta risoluzione, export GLB, mesh di produzione e atlanti della pelle a 2K. Testa, mandibola, occhi, narici e fossette labiali sono componenti della geometria; i dettagli delle squame sono precalcolati nelle mappe della pelle e delle normali.

La versione web ha 30.468 vertici e 58.624 triangoli, usa mipmap e filtraggio anisotropico quando disponibile e trasferisce circa 3 MB al primo caricamento. Il canvas arriva a DPR 2. L'asset viene caricato in modo asincrono: un errore o un timeout attiva la decorazione statica senza impedire il login. La build completa e i limiti di ricostruzione sono descritti in [assets/python/README.md](../assets/python/README.md).

Il modello è originale, non una scansione di un animale. Le misure di fluidità locali non garantiscono lo stesso frame rate su ogni GPU.

## File e responsabilità

- `static/js/snake-mesh.js`: caricamento della mesh esportata, texture, shader, buffer e rendering WebGL.
- `static/js/snake.js`: pose, puntatore, focus, interpolazione, ridimensionamento, visibilità e preferenze di movimento.
- `static/js/login-transition.js`: POST autenticato, gestione degli errori e passaggio della pagina mantenendo canvas e contesto WebGL.
- `static/js/dashboard.js`: aggiornamento incrementale delle tabelle e animazioni della libreria.

I percorsi sono relativi a `data/database/dashboard/`. Nessuna libreria, texture o modello viene scaricato da CDN a runtime.

## Passaggio autenticato

Il form conserva il POST nativo. Con JavaScript disponibile, il client invia il medesimo POST al server e accetta la dashboard soltanto dopo una risposta riuscita con redirect della stessa origine e pagina attesa. Autenticazione, sessione e limiti ai tentativi rimangono sul server. Gli script ricevuti nell'HTML non vengono eseguiti; si caricano soltanto i due entry point locali noti della dashboard.

Il canvas rimane lo stesso nodo: la pagina appare gradualmente mentre la posa raggiunge l'area di destinazione in 1,25 secondi. Se il login fallisce si mostra il messaggio sul form; se gli script della dashboard non si caricano dopo l'autenticazione si usa la navigazione normale. Senza JavaScript rimane il POST tradizionale; senza WebGL l'accesso continua con una decorazione statica. Le credenziali non vengono memorizzate dal codice di animazione o transizione.

## Verifica

- `tests/test_dashboard_browser.cjs`: funzionalità desktop/mobile, filtri, ricerca, dettaglio, sicurezza del rendering e temi.
- `tests/test_snake_browser.cjs`: compilazione effettiva degli shader, buffer GPU stabili tra frame, pose, login errato, stesso canvas dopo il login, righe/focus stabili durante refresh, pausa, fallback WebGL e POST senza JavaScript.
- `tools/run_repository_checks.py --pattern 'test_dashboard_*.py'`: API, autenticazione e asset in copia isolata.
- Ispezione visiva delle schermate desktop e mobile della preview con database temporaneo.
- Campione locale di 120 intervalli `requestAnimationFrame` su Chromium, 1440×1000, DPR 1: mediana circa 6,1 ms, percentile 95 circa 6,2 ms, nessun intervallo oltre 32 ms. È una misura del ciclo browser su questa macchina, non una certificazione della latenza end-to-end né delle GPU mobili.
