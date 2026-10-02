# Wiki22 1.10 — anteprima leggera

Questa versione di sviluppo avvia l’app senza Wikipedia. Il catalogo interno
permette di scaricare la biblioteca italiana già convertita (5,84 GB), con pausa,
ripresa e verifica SHA-256 di tutti i file prima della registrazione.

La Sonda delle fonti prepara un’anteprima di file/cartelle e URL pubblici scelti
dall’utente. Solo i documenti selezionati vengono convertiti in una nuova libreria
22CK, conservando la provenienza. Più librerie si consultano insieme attraverso
la selezione già presente nell’app. Nessun crawler autonomo, OCR o accesso con
credenziali è incluso. I siti possono rifiutare la raccolta.

Pacchetti portatili di anteprima: estrarre lo ZIP e aprire Avvia Wiki22.sh
(Linux) o Avvia Wiki22.cmd (Windows). Runtime incluso. Profilo separato,
nessuna migrazione automatica della versione installata.

Test: `python -m unittest discover -s tests`. Avvio dai sorgenti:
`python start.py --port 0`. Non è necessaria una biblioteca preinstallata.

Il catalogo usa intervalli dei file già pubblicati per trasferire solo Wikipedia,
senza duplicare l’archivio sullo storage. La verifica completa viene effettuata
prima di rendere la libreria disponibile. La preparazione richiede circa 7,1 GB.

La firma SignPath rimane in attesa di valutazione. Questa anteprima non è firmata
e non sostituisce gli installer pubblici 1.9.0. Windows su hardware reale resta
da collaudare.

## Base storica e licenze


Wiki22 è un'enciclopedia personale offline di 22 GmbH per consultare fonti,
conservare letture e comporre ricerche documentate. Non richiede chiamate a LLM.

Sito e download: https://www.twenty-two.ch/wiki22.html

## Stato della distribuzione

Questa pubblicazione dei sorgenti deriva dal prodotto Wiki22 1.9.0. Il pacchetto
Wikipedia italiana contiene 1.984.914 voci. Wikipedia, l'interprete Python e i
dati personali non sono conservati in questo repository.

Gli installer storici 1.9.0 disponibili sul sito sono **privi di firma**. La
candidatura a SignPath Foundation è stata inviata il 2 ottobre 2026: non è stata ancora
approvata e questo repository non rappresenta una distribuzione firmata.
Il prodotto storico Windows è stato collaudato in Wine, non su hardware
Windows reale. Le nuove compilazioni devono essere verificate separatamente.

Il lavoro iniziale di firma riguarda `Wiki22.exe`, l'avviatore dell'app.
L'installer storico da circa 5,9 GB supera il limite di firma degli eseguibili
Windows e richiede un successivo pacchetto più piccolo con archivio dati separato.

## Licenza e componenti

Il codice originale Wiki22 e gli strumenti di compilazione sono distribuiti
con **GPL-3.0-only**, Copyright (c) 2026 22 GmbH. Vedi [LICENSE](LICENSE).
Questa licenza permette anche l'uso commerciale.

I componenti e i contenuti di terze parti conservano le rispettive licenze:
vedi [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). La GPL non sostituisce
le licenze dei testi Wikipedia o degli altri contenuti importati dall'utente.

## Avvio dai sorgenti

Con Python 3.14, un browser e una copia autorizzata dell'archivio Wikipedia
1.9.0, collocare la cartella `Biblioteca` accanto a `start.py`, quindi eseguire:

```text
python -X utf8 -B start.py --port 0
```

Il registro iniziale contiene esclusivamente il riferimento relativo alla
biblioteca distribuita. I dati vengono conservati in `Dati-personali`.
`python -X utf8 -B start.py --stop` arresta il servizio locale.

## Compilazione Windows

Servono Visual Studio Build Tools (C/C++ x64), Windows SDK e Python 3.14.
Da un prompt **x64 Native Tools**:

```text
python packaging/build_windows.py
```

Il risultato `dist/windows-unsigned/Wiki22.exe` è un avviatore, non un installer
autonomo: richiede l'app e il runtime Python nella struttura prevista. Le
istruzioni di avvio non chiedono di disabilitare le protezioni Windows.

GitHub Actions compila lo stesso sorgente e conserva l'eseguibile come artifact.
La firma si abilita soltanto dopo l'ammissione a SignPath e la configurazione
del progetto. Non si firmano nuovamente i componenti di terze parti.

## Privacy, firma e rimozione

- [Privacy](PRIVACY.md)
- [Code signing policy](CODE_SIGNING_POLICY.md)
- [Rimozione e conservazione dei dati](UNINSTALL.md)
