# Rimuovere Wiki22 conservando i dati

1. Chiudere Wiki22 e arrestare il servizio locale con il comando di arresto
   fornito con la versione portatile, oppure con `python start.py --stop`
   usando il runtime della propria installazione.
2. Fare una copia della cartella `Dati-personali` e delle biblioteche importate
   che si desidera conservare.
3. Se nella cartella dell'app esiste `PROFILE.json`, controllare il percorso
   indicato: il profilo può appartenere a una precedente installazione.
   Non rimuoverlo se altre versioni lo usano.
4. Rimuovere la cartella della versione che non serve più e i suoi collegamenti
   dal Desktop o dal menu Start. Non rimuovere archivi o profili condivisi.

L'avviatore Windows di questo repository non crea servizi di sistema, non
richiede elevazione amministrativa e non modifica il registro di Windows.
