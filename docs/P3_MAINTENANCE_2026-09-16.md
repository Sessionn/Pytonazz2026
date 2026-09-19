> Documento storico. Per lo stato attuale vedere [audit del 20 settembre](AUDIT_2026-09-20.md).

# Interventi P3 — 16 settembre 2026

Branch: `codex/p3-maintainability-performance`, derivato da `codex/web-redesign-audit` (`5d82d76`).

## Modifiche

- Musica e moderazione diventano pacchetti con moduli dedicati a code, raccolte, comandi standard, voce e isolamento. Restano invariati i nomi delle estensioni e dei comandi Discord.
- Resolver: parsing, policy di selezione, shuffle, estrazione e cache in memoria sono separati dall'orchestrazione. Gli import pubblici precedenti rimangono disponibili; commenti corrotti ripuliti.
- Cache SQLite: schema/manutenzione identificatori e query di lettura in `core/cache/`. Connessione, lock e notifiche restano nel proprietario originale. Nessuna migrazione del database.
- Conteggi del catalogo tramite aggregazioni separate: evitata la moltiplicazione sorgenti × query durante il join.
- Dashboard: paginazione SQL uniforme per brani, alias, tracce, sorgenti e query; 50 righe per pagina, massimo API 200. Ricerca e ordinamento sul server, ordinamento stabile per ID, risposte obsolete ignorate. Le richieste senza parametri di paginazione mantengono il formato precedente.
- CSS DJ: eliminate 392 dichiarazioni superate, mantenendo la precedenza degli stili e il tema condiviso.
- Strumenti: audit include i file `__init__.py` e distingue dipendenze interne da dipendenze tra cog; lettura UTF-8 con BOM; runner include nuovi moduli non ancora in staging, timeout configurabile e durata dei test; preview con `main`, porta configurabile e database temporaneo.

## Continuità operativa

Il watcher riconosce modifiche, aggiunte e rimozioni nei pacchetti, ricarica una volta la relativa estensione e ritenta dopo un errore. Musica conserva player, code e primitive di sincronizzazione nel bot durante il reload; i callback vengono ricollegati al nuovo cog. Moderazione conserva lo stato di sessione e sostituisce il watchdog precedente.

La suddivisione è in moduli Python: non introduce shard delle connessioni Discord.
Le modifiche ai moduli condivisi `core/` richiedono un riavvio completo. La prima installazione di questo refactor va effettuata con un riavvio, non facendo affidamento sul vecchio watcher.
Un riavvio completo continua a caricare i dati persistenti previsti dal progetto; non viene introdotta la persistenza della coda musicale tra processi.

## Verifiche

- 74/74 script Python superati; sintassi di 207 file verificata in una copia temporanea senza `.env` o database locali.
- Caricamento offline di tutte le 14 estensioni; confronto dei comandi e relativi parametri dopo due reload consecutivi di musica e moderazione.
- Conservazione dello stato musicale/moderazione e verifica dei callback e dell'arresto del vecchio watchdog.
- Test del watcher su aggiunte/rimozioni, proprietario dell'estensione, errori e retry.
- API: compatibilità precedente, limiti delle pagine, ricerca/filtri, risultati vuoti, input non valido e ordinamenti non autorizzati.
- Browser Chromium: pagine distinte, ricerca dopo cambio pagina, desktop/mobile, login, temi, modale, notifiche e risposte di ricerca fuori ordine.
- CSS: stessi valori calcolati per gli elementi presenti e relativi pseudo-elementi su 1440×1000, 1920×1080, 768×900 e 390×844, nei due temi. Questa verifica non copre ogni possibile stato dinamico della console.

## Limiti e messa in servizio

Verifiche locali e offline: nessun test audio su Discord reale e nessun deploy di questo branch sulla VM. Nessun aggiornamento indiscriminato delle dipendenze esterne. Le API legacy senza paginazione possono ancora restituire tutti i dati; la dashboard usa quelle paginate. Le ricerche testuali continuano a richiedere scansioni SQL, mentre trasferimento e rendering sono limitati alla pagina.

Gli interventi P1/P2 del report precedente restano fuori da questo branch. I file locali preesistenti non tracciati sono esclusi dal commit.
