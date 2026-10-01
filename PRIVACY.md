# Privacy di Wiki22

Wiki22 1.9.0 conserva letture, ricerche, impostazioni e documenti importati
sul computer dell'utente. L'app funziona su un servizio locale legato a
`127.0.0.1`; non richiede un account e non usa servizi LLM remoti.

Il percorso ordinario dell'enciclopedia non invia le ricerche a un servizio
esterno. Il browser può connettersi a Wikipedia quando l'utente apre un link
alla fonte originale. Il download dell'app o degli archivi contatta il
servizio che ospita quei file, secondo le politiche di tale servizio.

I file del profilo non devono essere pubblicati nel repository. Le copie di
fabbrica contengono solo un registro iniziale, senza letture o documenti privati.
La disinstallazione manuale deve preservare i dati che si desidera conservare.

Questa descrizione riguarda l'app Wiki22. GitHub, SignPath e il sito di
distribuzione trattano separatamente i dati relativi ai rispettivi servizi.

## Optional downloads and source probe (1.10 preview)

No connection is made at startup or during local reading. When the user chooses
to download Wikipedia, Wiki22 contacts the public release storage using range
requests. The storage provider receives the connection IP and request metadata.
The bundled catalog pins file sizes and SHA-256 hashes; no personal library or
reading history is uploaded.

When the user supplies web URLs to the source probe and clicks Explore, Wiki22
requests those public pages and their robots.txt rules. Destination websites
receive normal request metadata, including the user's connection IP. The probe
does not send local document contents or browser cookies, does not log into sites,
and does not recursively follow links. Private-network addresses are blocked.
Web content is staged locally for preview and conversion. Imported content keeps
its original URL and SHA-256 in the library; site content retains its own rights.
