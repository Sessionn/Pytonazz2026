# 📖 Documentazione Tecnica & Manuale dei Comandi

Benvenuto nella documentazione tecnica interna di **Pitonazz**. Questo documento descrive l'elenco esaustivo dei comandi slash applicativi (Application Commands) suddivisi per modulo operativo e la gestione avanzata dei permessi di runtime.

---

## 👑 Gerarchia dei Permessi

Il bot prevede tre livelli di autorizzazione per l'esecuzione dei comandi:
1. **Utente Standard:** Accesso ai moduli Musica, TTS e Fun.
2. **Server Admin (Permesso "Gestisci Server"):** Accesso alle configurazioni di gilda dei compleanni e dei messaggi di Benvenuto/Arrivederci.
3. **Bot Developer / Owner:** Contrassegnati dal prefisso `⚙️ 👑`. Richiedono la corrispondenza degli ID all'interno delle configurazioni `.env` ed eludono le restrizioni standard.

---

## 🎵 Modulo Musica (`/play`, `/search`, ecc.)

Il modulo gestisce flussi audio asincroni interfacciandosi con `yt-dlp` e integrando un algoritmo predittivo di enrichment dei metadati per i link Spotify.

* `/play <testo o link>`: Riproduce musica nel canale vocale corrente. Supporta ricerche testuali libere, URL singoli o playlist di YouTube, traccie/playlist/album di Spotify e flussi SoundCloud. *Nota: Non accetta profili artista Spotify o canali YouTube.*
* `/search <testo>`: Esegue una ricerca approfondita e restituisce un menu interattivo con i primi 7 risultati rilevati.
* `/versions`: Analizza la traccia in riproduzione e propone un menu con 5 versioni alternative (es: Speed up, Slowed, Nightcore, Cover).
* `/artistshuffle <nome_artista> [n]`: Genera una stazione radio dedicata a un artista caricando le sue Top Tracks e combinandole con brani di artisti simili (Default: 20 tracce, max 50).
* `/skip`: Salta immediatamente il brano corrente.
* `/skipto <posizione>`: Salta direttamente alla traccia *N* della coda, rimuovendo istantaneamente tutte le tracce intermedie.
* `/pause` / `/resume`: Mette in pausa o riprende la riproduzione musicale.
* `/stop`: Interrompe definitivamente lo streaming, svuota completamente la coda d'attesa e disconnette il bot.
* `/disconnect`: Disconnette il bot dal canale vocale preservando intatta la coda corrente.
* `/queue`: Mostra lo stato della coda d'attesa tramite un sistema di pagine interattive navigabili con bottoni.
* `/nowplaying`: Genera un Rich Embed grafico della traccia in riproduzione provvisto di controlli multimediali interattivi.
* `/loop <off|track|queue>`: Imposta il ciclo di ripetizione (Disattivato, Traccia Singola, Intera Coda).
* `/shuffle`: Attiva o disattiva la miscelazione casuale standard della coda.
* `/smartshuffle`: Algoritmo di riordinamento intelligente basato sull'isolamento degli artisti: garantisce che non vengano mai riprodotti due brani consecutivi dello stesso autore.
* `/remove <posizione>`: Rimuove la traccia posizionata all'indice *N* della coda.
* `/move <da> <a>`: Cambia la priorità di una traccia spostandola all'interno della coda d'attesa.
* `/history`: Mostra la cronologia degli ultimi 10 brani riprodotti nel server.
* `/join [utente]`: Forza l'ingresso del bot nel canale vocale dell'utente specificato o di chi lancia il comando.
* `/filter <filtro>`: Applica filtri di equalizzazione in tempo reale al flusso FFmpeg (`nightcore`, `vaporwave`, `8d`, `off`).

> **Regole di Inattività Vocale:** Il bot esegue un auto-disconnessione di sicurezza dopo **10 minuti continui** di inattività o qualora il canale vocale rimanga vuoto. Non si disconnette se il player è esplicitamente in stato di pausa.

---

## 🧠 Modulo Intelligenza Artificiale & TTS

Questo modulo espone l'integrazione con i modelli linguistici di ultima generazione gestendo lo stato conversazionale (`core/ai_runtime.py`) tramite deque isolati per canale.

* **Interazione Naturale (@Pitonazz / DM):** Menzionando il bot nei canali testuali abilitati o scrivendogli direttamente in DM, si attiva la chat conversazionale. Possiede memoria storica degli ultimi 20 messaggi del canale e supporta la comprensione di allegati di tipo immagine (PNG, JPEG, WEBP, GIF, BMP).
* **Funzionalità `#web`:** Digitando all'inizio o all'interno del messaggio i marker `cerca web:`, `web:` o il tag `#web`, l'AI interroga in tempo reale le Wikipedia Search API estraendo fino a 3 snippet informativi accurati per aggiornare il proprio contesto operativo.
* `/tts <testo> [voce]`: Sintetizza il testo inserito (max 500 caratteri) all'interno del canale vocale. Le voci selezionabili sono:
  * `Diego` (Italiano Maschile - Default)
  * `Elsa` / `Isabella` (Italiano Femminile)
  * `Ryan` (Inglese UK Maschile)
  * `Aria` (Inglese US Femminile)

---

## 🎂 Modulo Compleanni (`/bday`)

* `/bday set <giorno> <mese> [anno]`: Registra la propria data di nascita. L'anno è opzionale: se fornito, abilita il calcolo automatico dell'età durante l'annuncio.
* `/bday check [@utente]`: Mostra la data di compleanno registrata per l'utente selezionato o per se stessi.
* `/bday list`: Mostra la timeline ordinata cronologicamente di tutti i compleanni della community.
* `/bday remove`: Consente all'utente di cancellare definitivamente la propria entry dal database.

### 🛡️ Comandi Amministrativi Compleanni (Richiede Gestisci Server):
* `/bday adminset <@utente> <giorno> <mese> [anno]`: Forza la registrazione del compleanno di un utente.
* `/bday adminremove <@utente>`: Rimuove l'entry di un utente specifico.
* `/bday channel [#canale]`: Imposta o disabilita il canale testuale dedicato alla pubblicazione automatica dei messaggi di auguri giornalieri.
* `/bday messages_set <messaggi>`: Sovrascrive l'intera lista dei messaggi di auguri del server (una stringa per riga). Accetta placeholder dinamici come `{mention}`, `{age}`, `{display_name}`, `{guild}`.
* `/bday messages_add <messaggio>`: Aggiunge un nuovo template di auguri plain-text alla rotazione casuale.
* `/bday messages_remove <indice>`: Rimuove un template in base al suo indice identificativo.
* `/bday messages_list`: Mostra l'elenco numerato di tutti i messaggi inseriti.
* `/bday test`: Esegue una simulazione istantanea in modalità effimera (visibile solo all'admin) per verificare la formattazione dei placeholder.

---

## ⚙️ 👑 Modulo Developer (`/status`, `/cache`, ecc.)

Comandi esclusivi ad altissimo privilegio per la manutenzione a caldo del backend del bot.

* `/restart`: Chiude in sicurezza le connessioni attive di `discord.py` e riavvia il processo software rigenerando l'istanza tramite l'esecutibile di sistema di Python.
* `/sync [clear_global]`: Sincronizza l'albero applicativo dei comandi slash con l'API di Discord. Può ripulire le entry globali corrotte o forzare il push sulle gilde indicate in `GUILD_IDS`.
* `/maintenance <attiva>`: Attiva lo stato di manutenzione. Il bot rifiuterà l'interazione con gli utenti standard e applicherà un flag grafico allo status di Discord.
* `/backupconfig`: Genera istantaneamente un archivio compresso `.zip` contenente tutti i file critici di configurazione di runtime, database JSON e immagini di benvenuto memorizzate, restituendolo in chat.
* `/restoreconfig <allegato_zip>`: Legge un file di backup valido generato dal bot, sovrascrive a caldo i file di configurazione corrotti ed esegue il reload automatico delle classi.
* `/disable_command <comando>` / `/enable_command <comando>`: Abilita o disabilita a runtime l'utilizzo di uno specifico comando slash in tutto il bot (I comandi critici di amministrazione sono protetti e non disabilitabili).
* `/command_list`: Mostra un pannello di controllo diagnostico con lo stato di runtime di tutti i comandi (Abilitati, Disabilitati, Protetti).
* `/set_log_channel [canale]`: Configura un canale di log centralizzato dove il bot inoltrerà in tempo reale gli stacktrace degli errori eccezione non gestiti.
* `/tts_volume <valore>`: Modifica l'ampiezza persistente (moltiplicatore da 0.1 a 3.0) del modulo TTS.
* `/say <testo> [canale]`: Consente allo sviluppatore di inviare messaggi testuali o Embed impersonando direttamente l'identità del bot all'interno di qualsiasi gilda condivisa.

### Gruppo `/status` (Rotazione Attività):
* `/status add <tipo> <nome> <stato>`: Aggiunge uno stato personalizzato alla rotazione ciclica del bot (Giocando, Guardando, Ascoltando, Gareggiando, Custom) associandolo a un marker di presenza (`online`, `idle`, `dnd`, `invisible`).
* `/status remove <indice>`: Rimuove uno stato custom dalla coda di rotazione.
* `/status edit <indice> [nome] [tipo] [stato]`: Modifica i parametri di un'attività inserita.
* `/status list`: Mostra l'intera pipeline di rotazione dividendo gli stati nativi (statici) da quelli custom introdotti a runtime.
* `/status set <tipo> <nome> <stato>`: Forza l'applicazione immediata di uno status ignorando temporaneamente il ciclo di rotazione.
* `/status interval <secondi>`: Modifica la frequenza di aggiornamento del ciclo delle attività (Minimo 10 secondi, persistente ai riavvii).
