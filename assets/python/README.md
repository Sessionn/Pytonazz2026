# Python — asset Blender originale

Modello originale realizzato per Pytonazz, ispirato al pitone reale. Nessun modello o texture di terzi è incorporato.

- `python.blend`: progetto Blender 4.5, con collezioni distinte per superficie di produzione, dettaglio ad alta risoluzione e posa da ritratto. Le immagini sono incorporate nel file.
- `python.glb`: modello di produzione in posa neutra, con materiali e immagini incorporati. Può essere importato in Blender o in altri strumenti glTF.
- `skin.png`, `normal.png`: atlante originale 2048×2048; l'alpha dell'atlante pelle contiene la rugosità del materiale Blender.
- `python-portrait.png`: render Cycles del modello, senza sfondo.

Il master ad alta risoluzione include rilievi geometrici delle squame e anatomia craniale. La versione web usa 30.468 vertici e 58.624 triangoli, mappe precalcolate e filtraggio mipmap. La geometria non viene generata nel browser. Il runtime trasferisce circa 3 MB al primo caricamento, poi riutilizza gli asset dalla cache HTTP; il GLB e il progetto Blender non vengono richiesti dalla pagina.

## Ricostruzione

Dalla radice del repository:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' --background --factory-startup --python tools/blender/build_python.py
python tools/blender/package_python.py
```

Il secondo comando richiede Pillow nell'interprete usato per la build; non è una nuova dipendenza del bot. I comandi rigenerano i file di questa cartella e quelli in `data/database/dashboard/static/models/python/`. Le modifiche manuali al `.blend` vanno salvate separatamente prima di rigenerare: lo script ricostruisce il progetto da zero.

Il formato web `PYT1` contiene un'intestazione di 12 byte (firma, numero vertici, numero indici), vertici little-endian da 10 float32 (posizione locale, normale, parametro longitudinale, UV, materiale) e indici uint16. Il renderer deforma la mesh tramite la curva del corpo già usata dalle interazioni del login. La mappa colore web è WebP di qualità 92; la mappa delle normali è WebP lossless. La rugosità web è uniforme per ridurre il trasferimento, mentre il file Blender conserva la mappa completa.

Il toolkit è stato consultato e il suo CLI verificato. Poiché l'addon risultava non attivo, il progetto è stato costruito con Blender in modalità batch, senza modificare scene aperte o installare addon globali.
