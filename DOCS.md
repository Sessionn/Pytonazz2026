# 📖 Manuale Tecnico Esteso e Legenda dei Comandi

Questo documento costituisce il manuale operativo e la specifica tecnica dettagliata di tutti i moduli funzionali ed i comandi applicativi presenti all'interno di **Pitonazz**. Ciascun comando viene analizzato sotto il profilo sintattico, dei vincoli di runtime e dei requisiti autorizzativi.

---

## 📍 Indice
1. [Architettura dei Cogs (Moduli Applicativi)](#-architettura-dei-cogs-moduli-applicativi)
2. [Modello di Gestione dei Permessi](#-modello-di-gestione-dei-permessi)
3. [Manuale dei Comandi: Modulo Musica](#-manuale-des-comandi-modulo-musica)
4. [Manuale dei Comandi: Modulo Intelligenza Artificiale & TTS](#-manuale-dei-comandi-modulo-intelligenza-artificiale--tts)
5. [Manuale dei Comandi: Modulo Compleanni (`/bday`)](#-manuale-dei-comandi-modulo-compleanni-bday)
6. [Manuale dei Comandi: Modulo Developer & Gestione Interna](#-manuale-dei-comandi-modulo-developer--gestione-interna)
7. [Automazioni di Runtime e Ciclo di Vita](#-automazioni-di-runtime-e-ciclo-of-vita)

---

## 🧩 Architettura dei Cogs (Moduli Applicativi)

Il bot sposa un'architettura modulare guidata dalla classe `discord.ext.commands.Cog`. Ogni file presente nella cartella `cogs/` isola un dominio funzionale:


cogs/
├── ai.py # Gestione LLM, chat contestuale ed immagini
├── birthdays.py # Logica applicativa e scadenziario dei compleanni
├── dev.py # Utility di base dell'owner (riavvio, sync)
├── dev_audio.py # Debug avanzato dello stream FFmpeg e volumi tts
├── dev_cache.py # Strumenti di ispezione diretta sulla cache SQLite
├── filters.py # Manipolazione dei parametri audio di FFmpeg
├── fun.py # Comandi ricreativi e d'interazione della community
├── help.py # Generatore dinamico della guida ai comandi
├── moderation.py # Strumenti di controllo dei canali e dei membri
├── music.py # Core operativo del player, delle code e delle interfacce
├── tts.py # Interfaccia con i motori di sintesi vocale Edge-TTS
└── welcome.py # Trigger e generazione eventi d'ingresso nuovi membri

---

## 👑 Modello di Gestione dei Permessi

I comandi sono protetti da verifiche gerarchiche strutturate su tre livelli logici:

| Livello | Definizione | Criterio di Verifica |
| :--- | :--- | :--- |
| **L1: Utente Standard** | Qualsiasi membro della gilda. | Nessuna restrizione di ID o ruolo di gilda. |
| **L2: Amministratore** | Gestori della community locale. | Controllo del flag Discord `manage_guild` o `administrator` nel contesto del comando. |
| **L3: Bot Developer / Owner** | Sviluppatori dell'infrastruttura. | Controllo di corrispondenza binaria dell'ID utente con i campi `OWNER_ID` o `DEV_IDS` nel file `.env`. |

---

## 🎵 Manuale dei Comandi: Modulo Musica

I comandi musicali richiedono che l'utente sia connesso a un canale vocale all'interno della stessa gilda. La dimensione massima invalicabile della coda è impostata a **200 tracce**.

### `/play`
* **Livello Permessi:** L1
* **Argomenti:** `query` (Stringa, Obbligatorio)
* **Descrizione:** Accetta testo libero (esegue lookup su cache e poi ricerca su YouTube), URL di YouTube (singoli o playlist), URL di Spotify (singoli brani, album interi o playlist commerciali/pubbliche), e URL SoundCloud.
* **Eccezioni:** Restituisce un errore se l'URL appartiene a un profilo artista Spotify o a un canale YouTube privato.

### `/search`
* **Livello Permessi:** L1
* **Argomenti:** `query` (Stringa, Obbligatorio)
* **Descrizione:** Interroga la rete e propone un menu a tendina interattivo (`discord.ui.Select`) contenente i primi 7 risultati trovati. L'utente ha 60 secondi per selezionare la traccia, pena l'annullamento della richiesta.

### `/versions`
* **Livello Permessi:** L1
* **Argomenti:** Nessuno
* **Descrizione:** Analizza i metadati del brano attualmente in riproduzione e genera un menu di selezione proponendo 5 varianti acustiche sintetiche pre-elaborate (es: *Nightcore, Slowed, Speed Up, Bass Boosted*).

### `/artistshuffle`
* **Livello Permessi:** L1
* **Argomenti:** `artista` (Stringa, Obbligatorio), `quantita` (Intero, Opzionale - Default: 20, Max: 50)
* **Descrizione:** Sfrutta le API di Spotify per estrarre le Top Tracks dell'artista specificato e dei suoi artisti correlati, mixandole ed immettendole istantaneamente nella coda di riproduzione.

### `/skip`
* **Livello Permessi:** L1
* **Descrizione:** Interrompe immediatamente la traccia corrente e passa alla successiva. Se la coda è vuota, il player si ferma mantenendo la connessione vocale.

### `/skipto`
* **Livello Permessi:** L1
* **Argomenti:** `posizione` (Intero, Obbligatorio)
* **Descrizione:** Salta direttamente all'indice specificato all'interno della coda. Tutte le tracce intermedie vengono rimosse dalla memoria volatile del player.

### `/pause` / `/resume`
* **Livello Permessi:** L1
* **Descrizione:** Modificano lo stato di riproduzione del player audio asincrono. Lo stato di pausa inibisce temporaneamente il timer di disconnessione automatica del bot.

### `/stop`
* **Livello Permessi:** L1
* **Descrizione:** Resetta la coda, interrompe l'istanza FFmpeg corrente, pulisce lo stato del player e disconnette il bot dal canale vocale.

### `/disconnect`
* **Livello Permessi:** L1
* **Descrizione:** Disconnette il bot dal canale vocale lasciando intatta la coda dei brani per un utilizzo futuro all'interno della sessione di runtime attuale.

### `/clearqueue`
* **Livello Permessi:** L1
* **Descrizione:** Rimuove tutti i brani dalla coda ad eccezione di quello correntemente in riproduzione.

### `/queue`
* **Livello Permessi:** L1
* **Descrizione:** Mostra un Rich Embed paginato provvisto di bottoni di navigazione (`Prec / Succ`) per scorrere la coda dei brani a blocchi di 10 elementi per pagina.

### `/nowplaying`
* **Livello Permessi:** L1
* **Descrizione:** Invia un embed grafico dettagliato che mostra la barra di avanzamento della traccia in tempo reale, la thumbnail, la sorgente e l'utente che ha richiesto il brano. Include bottoni interattivi per Play/Pause, Skip e Stop.

### `/loop`
* **Livello Permessi:** L1
* **Argomenti:** `modalita` (Scelta fissa: `off`, `track`, `queue`, Obbligatorio)
* **Descrizione:** Modifica il comportamento del loop: `off` disattiva il riciclo, `track` ripete la traccia corrente all'infinito, `queue` rimette in coda i brani esauriti in fondo alla lista.

### `/shuffle`
* **Livello Permessi:** L1
* **Descrizione:** Attiva/disattiva la modalità di miscelazione casuale standard della coda utilizzando l'algoritmo nativo di sampling pseudo-casuale.

### `/smartshuffle`
* **Livello Permessi:** L1
* **Descrizione:** Algoritmo avanzato di shuffle: riordina la coda applicando un vincolo di isolamento acustico che impedisce la riproduzione consecutiva di brani dello stesso artista.

### `/remove`
* **Livello Permessi:** L1
* **Argomenti:** `posizione` (Intero, Obbligatorio)
* **Descrizione:** Elimina permanentemente dalla coda la singola traccia presente all'indice inserito.

### `/move`
* **Livello Permessi:** L1
* **Argomenti:** `da` (Intero, Obbligatorio), `a` (Intero, Obbligatorio)
* **Descrizione:** Sposta un brano internamente alla coda modificando la sua priorità di riproduzione.

### `/history`
* **Livello Permessi:** L1
* **Descrizione:** Restituisce un embed contenente lo storico degli ultimi 10 brani effettivamente riprodotti e completati all'interno della sessione corrente della gilda.

### `/join`
* **Livello Permessi:** L1
* **Argomenti:** `canale` (Canale Vocale, Opzionale)
* **Descrizione:** Sposta o connette il bot al canale vocale specificato o a quello in cui si trova l'utente che impartisce il comando.

### `/filter`
* **Livello Permessi:** L1
* **Argomenti:** `tipo` (Scelta fissa: `nightcore`, `vaporwave`, `8d`, `off`, Obbligatorio)
* **Descrizione:** Riavvia a caldo l'istanza di streaming FFmpeg modificando i parametri audio della pipeline (`-af`) per applicare l'effetto selezionato senza interrompere bruscamente l'ascolto.

---

## 🧠 Manuale dei Comandi: Modulo Intelligenza Artificiale & TTS

Il modulo AI risponde alle menzioni dirette nei canali abilitati e gestisce in parallelo la sintesi vocale multilingua.

### 💬 Chat Conversazionale Naturale (Trigger: `@Pitonazz` o Messaggio Diretto DM)
* **Funzionamento:** Il bot analizza il contesto del canale mantenendo in un oggetto `deque` gli ultimi **20 messaggi** scambiati per non perdere il filo del discorso.
* **Riconoscimento Vision:** Se al messaggio viene allegata un'immagine (formati supportati: `PNG, JPEG, WEBP, GIF, BMP`), il bot effettua una codifica asincrona in Base64 e interroga l'LLM attivando le funzionalità multimodali per descrivere o commentare il file multimediale.
* **Modalità Ricerca Live (`#web`):** Se il testo contiene i token `cerca web:`, `web:` o l'omonimo tag `#web`, il bot interrope la pipeline standard, interroga Wikipedia tramite le sue Search API, estrae i 3 snippet informativi più rilevanti e li inserisce all'interno del prompt di sistema prima di formulare la risposta finale dell'LLM.

### `/tts`
* **Livello Permessi:** L1
* **Argomenti:** `testo` (Stringa, Obbligatorio, Max 500 caratteri), `voce` (Scelta a tendina, Opzionale)
* **Descrizione:** Converte il testo in un flusso vocale e lo riproduce nel canale audio. Le voci disponibili emulano i profili neurali standard:
  * `Diego` (Italiano Maschile - Standard predefinito)
  * `Elsa` / `Isabella` (Italiano Femminile)
  * `Ryan` (Inglese UK Maschile)
  * `Aria` (Inglese US Femminile)

---

## 🎂 Manuale dei Comandi: Modulo Compleanni (`/bday`)

Il modulo organizza l'anagrafica interna memorizzando i dati all'interno del file locale `assets/data/birthdays.json`.

### `/bday set`
* **Livello Permessi:** L1
* **Argomenti:** `giorno` (Intero, Obbligatorio), `mese` (Intero, Obbligatorio), `anno` (Intero, Opzionale)
* **Descrizione:** Registra la data di nascita dell'utente. Se viene inserito l'anno, il bot calcolerà automaticamente l'età esatta della persona nel messaggio di auguri pubblico.

### `/bday remove`
* **Livello Permessi:** L1
* **Descrizione:** Cancella definitivamente l'utente dal database dei compleanni.

### `/bday check`
* **Livello Permessi:** L1
* **Argomenti:** `utente` (Membro Discord, Opzionale)
* **Descrizione:** Mostra un embed riepilogativo con i dati del compleanno dell'utente target o dell'esecutore, indicando i giorni mancanti alla ricorrenza.

### `/bday list`
* **Livello Permessi:** L1
* **Descrizione:** Genera la lista completa di tutti i compleanni della gilda ordinati cronologicamente a partire dal giorno corrente.

### `/bday adminset`
* **Livello Permessi:** L2
* **Argomenti:** `utente` (Membro, Obbligatorio), `giorno` (Intero, Obbligatorio), `mese` (Intero, Obbligatorio), `anno` (Intero, Opzionale)
* **Descrizione:** Permette ad un amministratore di inserire o correggere manualmente i dati di un utente del server.

### `/bday adminremove`
* **Livello Permessi:** L2
* **Argomenti:** `utente` (Membro, Obbligatorio)
* **Descrizione:** Forza la rimozione dei dati di un utente specifico dal database gilda.

### `/bday channel`
* **Livello Permessi:** L2
* **Argomenti:** `canale` (Canale Testuale, Opzionale)
* **Descrizione:** Configura il canale dove verranno inviati gli auguri automatici alle **00:00 UTC** di ogni giorno. Se non viene specificato alcun canale, la funzione di annuncio automatico viene disattivata.

### `/bday tags`
* **Livello Permessi:** L2
* **Descrizione:** Mostra la legenda dei tag di formattazione dinamica supportati dai messaggi di auguri:
  * `{mention}`: Menziona l'utente festeggiato con tag cliccabile.
  * `{name}`: Mostra il nome utente nativo di Discord.
  * `{display_name}`: Mostra il nickname del membro all'interno del server corrente.
  * `{age}`: Inserisce l'età calcolata (es: "18"). Se l'anno non è configurato nel DB, restituisce una stringa vuota.
  * `{guild}`: Inserisce il nome del server Discord corrente.

### `/bday messages_set`
* **Livello Permessi:** L2
* **Argomenti:** `messaggi` (Stringa, Obbligatorio)
* **Descrizione:** Sostituisce in blocco tutti i messaggi di auguri impostati per il server. Accetta testi multi-linea: ogni riga viene interpretata come un template di augurio singolo che verrà poi estratto casualmente dal bot a runtime.

### `/bday messages_add` / `/bday messages_remove`
* **Livello Permessi:** L2
* **Descrizione:** Aggiungono o rimuovono un singolo template di auguri dalla lista di rotazione del server. Rimozione guidata dall'indice numerico ricavabile da `/bday messages_list`.

### `/bday messages_list`
* **Livello Permessi:** L2
* **Descrizione:** Mostra l'elenco completo e numerato di tutti i template di auguri configurati nella gilda corrente.

### `/bday test`
* **Livello Permessi:** L2
* **Descrizione:** Genera un messaggio di test immediato in modalità effimera simulando l'annuncio dei compleanni per verificare l'effettivo rendering grafico dei tag dinamici.

---

## ⚙️ Manuale dei Comandi: Modulo Developer & Gestione Interna

I seguenti comandi sono rigorosamente accessibili solo dagli utenti inclusi nel livello di permessi **L3**.

### `/restart`
* **Descrizione:** Chiude in sicurezza i loop asincroni attivi, interrompe le connessioni di rete e lancia un sottoprocesso OS per rieseguire `main.py`, applicando a caldo gli aggiornamenti del codice sorgente.

### `/sync`
* **Argomenti:** `clear_global` (Booleano, Opzionale)
* **Descrizione:** Forza la sincronizzazione dell'albero dei comandi slash applicativi verso le API di Discord. Se `clear_global` è impostato su True, ripulisce la cache globale dei comandi di Discord prima di eseguire il push locale sulle gilde.

### `/maintenance`
* **Argomenti:** `attiva` (Booleano, Obbligatorio)
* **Descrizione:** Muta lo stato operativo del bot. Se attiva, il bot rifiuta qualsiasi interazione proveniente da utenti di livello L1 ed L2, rispondendo con un messaggio di alert temporaneo ed applicando uno status visivo dedicato ("*In Manutenzione*").

### `/backupconfig`
* **Descrizione:** Compila a caldo un archivio `.zip` binario contenente i database JSON, i file `.env`, `cache.db` e le impostazioni, inviandolo direttamente nel canale Discord sotto forma di allegato protetto.

### `/restoreconfig`
* **Argomenti:** `file_zip` (Allegato Discord, Obbligatorio)
* **Descrizione:** Accetta l'archivio generato da `/backupconfig`, estrae i file sovrascrivendo le configurazioni corrotte o obsolete sul disco ed esegue un reload a caldo di tutti i moduli software core.

### `/disable_command` / `/enable_command`
* **Argomenti:** `comando` (Stringa, Obbligatorio)
* **Descrizione:** Inibisce o riabilita globalmente l'utilizzo di uno specifico comando all'interno del bot a runtime. I comandi di sicurezza del modulo Dev (come `/enable_command` e `/restart`) sono protetti nativamente e non possono essere disabilitati.

### `/command_list`
* **Descrizione:** Mostra una tabella riepilogativa dello stato operativo di ciascun comando applicativo, distinguendo tra quelli *Abilitati*, *Disabilitati a runtime* o *Protetti di Sistema*.

### `/set_log_channel`
* **Argomenti:** `canale` (Canale Testuale, Opzionale)
* **Descrizione:** Configura un canale di log centralizzato all'interno di Discord. Tutte le eccezioni non gestite (Error 500, crash di moduli, timeout di rete) genereranno un dump completo dello stacktrace in questo canale per facilitare il debugging.

### `/say`
* **Argomenti:** `testo` (Stringa, Obbligatorio), `canale` (Canale Testuale, Opzionale)
* **Descrizione:** Permette allo sviluppatore di inviare stringhe o comunicazioni ufficiali parlando direttamente attraverso l'identità del bot all'interno del canale specificato.

### Gruppo `/status` (Gestione Presenza)
* `/status add`: Aggiunge una stringa di attività custom (es: "*Watching my code*") alla rotazione dinamica del bot memorizzandola nel file JSON.
* `/status remove`: Elimina una presenza custom tramite il suo indice identificativo.
* `/status list`: Mostra la coda complessiva delle presenze registrate e dei relativi stati di connessione (`online`, `idle`, `dnd`).
* `/status interval <secondi>`: Imposta il tempo di polling del loop asincrono che si occupa di cambiare l'attività visibile sul profilo Discord del bot.

---

## 📊 Automazioni di Runtime e Ciclo di Vita

Il bot implementa una serie di routine in background guidate dal modulo `discord.ext.tasks`:
1. **Loop di Inattività Vocale:** Ogni 60 secondi il bot analizza lo stato dei propri player attivi. Se rileva che il bot è l'unico membro rimasto nel canale vocale, o se lo stream è fermo da più di **10 minuti continui**, avvia autonomamente la procedura di disconnessione e pulizia della memoria per risparmiare risorse di rete sulla macchina ospitante.
2. **Ciclo degli Auguri (Task Giornaliero):** Un ciclo impostato ad intervalli regolari controlla il superamento della mezzanotte UTC. Al trigger temporale, interroga il database dei compleanni e formula i messaggi di auguri inviandoli nei rispettivi canali registrati nelle gilde.
3. **Auditing Dashboard Flask:** La web dashboard gira su un thread parallelo isolato dal loop principale di Discord. Monitora la saturazione della memoria RAM, la latenza delle API di Discord (espressa in millisecondi) e blocca gli IP anomali che tentano scansioni di rete non autorizzate sul socket della dashboard, registrandoli nei log con l'identificativo `[NET_SCAN]`.
