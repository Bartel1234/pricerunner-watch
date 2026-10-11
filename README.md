# PriceRunner Watch · 0.1.0-beta.3

Lokal prisovervågning på Unraid/DeathStar: dansk webinterface, SQLite-historik og import af **godkendte Adtraction v3-produktfeeds**. RAM, grafikkort, harddiske og SSD filtreres ud fra feedets produktnavn og kategori.

## Status

PriceRunner-crawleren blev blokeret med HTTP 403 på DeathStar. Beta.3 bruger derfor Adtraction som standard. Den tidligere crawler er bevaret som valgfri kilde, men er ikke en fungerende løsning på den observerede blokering. Opdateringen slår gammel automatik fra og bevarer historikken.

Feedintegrationen er testet med simulerede API-svar og en rigtig lokal HTTP-server. **Din Adtraction-nøgle, kanal og godkendte feeds mangler til live-test.** Docker-build og opdateringsscript er ikke kørt i udviklingsmiljøet, hvor Docker ikke findes.

CompuMail har et Adtraction-program. Det bekræfter ikke, at din kanal er godkendt, eller at programmet tilbyder et feed til dig. Elgigantens feedadgang er ikke verificeret. Systemet viser de danske DKK-programmer med feeds, din valgte kanal faktisk har godkendelse til. Der indsendes ingen programansøgninger automatisk.

## Opdater din eksisterende installation

I Unraids terminal:

```bash
cd /mnt/user/appdata/pricerunner-watch-src
git pull --ff-only
bash update-unraid.sh
```

Scriptet kræver den oprindelige `.env` i kildemappen. Det finder den eksisterende port og datamappe, bygger det nye image før driften stoppes, tager en backup af datamappen og bevarer den gamle container stoppet under et navn med tidsstempel. Hvis installationen eller sundhedstjekket fejler, forsøger det at starte den tidligere container igen. Databasen slettes ikke. Databackups kan indeholde API-nøglen og skal opbevares privat.

Det er ikke nok at bruge Unraids almindelige image-opdatering: kildekoden skal hentes og imaget bygges lokalt. Der er intet publiceret GHCR-image.

## Første installation

```bash
git clone https://github.com/Bartel1234/pricerunner-watch.git /mnt/user/appdata/pricerunner-watch-src
cd /mnt/user/appdata/pricerunner-watch-src
bash install-unraid.sh
```

Åbn `http://DIN-UNRAID-IP:8788`. Brugernavn: `admin`. Adgangskoden står i `.env` i kildemappen. Første build kan tage flere minutter. Standarddatamappe: `/mnt/user/appdata/pricerunner-watch`. Alternativ port: `WEB_PORT=8790 bash install-unraid.sh`. Alternativ datamappe: `DATA_PATH=/mnt/user/appdata/pricerunner-test bash install-unraid.sh`.

## Tilslut Adtraction

1. Log ind i Adtraction. Find/generér din API-nøgle under **Account → Settings → API**.
2. Find kanal-ID'et til den kanal, som dine butiksgodkendelser tilhører. Kanal-ID er ikke konto-ID eller program-ID.
3. Åbn **Indstillinger** i PriceRunner Watch. Vælg **Adtraction**, indtast nøgle og kanal-ID, og klik **Gem adgang**. Nøglen skal ikke sendes i chat eller lægges på GitHub.
4. Klik **Hent godkendte feeds**. Vælg butikkernes feeds, og klik **Gem indstillinger**.
5. Klik **Start scanning**. Kontrollér priser og lager hos butikkerne før du slår automatisk interval til. 24 timer er et rimeligt udgangspunkt til dagligt opdaterede feeds; den faktiske hyppighed varierer.

Ingen feeds i listen? Kontrollér den valgte kanal og dine programgodkendelser i Adtraction. Adtractions egen oversigt findes under **Products → Feeds**. Du skal være godkendt til et program for at få adgang til dets feed. Et tomt resultat er ikke bevis for, at butikken ikke har et feed på andre platforme.

API-nøglen gemmes i `adtraction-secrets.json` i datamappen med filrettigheder 0600. Den sendes kun som `X-Token` til `https://api.adtraction.net/v3/` og returneres ikke i webinterfacets state eller JSON-eksport. API-omdirigeringer afvises. Brug hjemmenettet/VPN eller HTTPS ved fjernadgang; HTTP Basic og lokal nøgleindtastning via HTTP er ikke krypteret. Containeren har ikke adgang til Docker-socket eller host-netværk.

## Import og kandidatlogik

- Henter hele de valgte feeds, maksimalt 20 feedvalg og 64 MiB pr. API-svar. Browserens batchgrænser gælder kun den tidligere PriceRunner-crawler.
- Accepterer kun godkendte danske produktrækker med DKK og en gyldig positiv pris. Prisformatet er API'ets decimalformat, ikke dansk tekstformat.
- Hardwarefilteret er et nøgleordsfilter på produktnavn/kategori. Feedets kategorier varierer; det garanterer ikke fuldstændig eller perfekt kategorisering. Fx kan en hel computer med RAM i titlen også matche. Kontrollér de første resultater.
- Sammenligner mellem butikker via en EAN/GTIN med gyldigt kontrolciffer; UPC/EAN med foranstillede nuller normaliseres. Uden gyldig EAN bevares butiksspecifik SKU/URL-identitet; ens produktnavne bliver ikke automatisk slået sammen.
- Overlappende feeds giver højst ét tilbud pr. butik og produkt. Markedspladsvarianter/sælgeridentitet er ikke særskilt verificeret.
- Feedets lagerstatus skal være boolean `true`, før tilbuddet bruges til kandidatberegning. Ukendt lager/udsolgt vises i historikken, men tæller ikke som tilgængeligt tilbud. Feedet giver ikke sikker information om bestillingsvarer.
- Kandidat: mindst 35% billigere end næstbilligste butik, når mindst tre butikker har tilgængelige tilbud, eller 35% fald fra seneste måling med samme sæt tilgængelige butikker. Grænsen kan ændres.
- Priser sammenlignes **ekskl. fragt**. Feedets egen opdateringsdato vises, når API'et oplyser den. Importtidspunktet er ikke det samme som butikkens prisopdatering.
- Hvis ét feed fejler, gemmes ingen nye observationer fra denne import. Historikken bevares, og automatik slås fra. Stop under den efterfølgende databasegemning kan efterlade daterede delresultater.
- Produkter, der forsvinder fra feedet, beholder den gamle, daterede måling. De skal ikke fortolkes som aktuelle tilbud. Et feed kan være forsinket eller indeholde forkerte produktmatches.
- Én import ad gangen. Valgfri automatik mindst 6 timer; første scanning skal startes manuelt. Stop kan vente på et API-kald op til timeout på 60 sekunder.

Systemet sender ingen beskeder og foretager ingen køb. En kandidat er et muligt fund, som skal kontrolleres hos butikken.

## PriceRunner-API

Klarna dokumenterer en Agentic Product API med dansk marked og europæisk endpoint på `api.pricerunner.com`. Adgang er for godkendte partnere/udviklere og skal aftales med Klarna via `agenticproductprotocol@klarna.com`. Denne integration er ikke implementeret uden godkendelse/API-adgang. Der er ikke sendt en ansøgning på dine vegne.

## Backup og fejlfinding

Stop containeren før du kopierer datamappen manuelt; SQLite bruger WAL. Gem også `.env` privat. `update-unraid.sh` gør dette med stoppet container, men er kun syntakskontrolleret i udviklingsmiljøet.

- **API HTTP 401/403:** kontrollér nøgle, kanal og godkendelser. Hent feedlisten igen.
- **Ingen hardware:** se feedets rækkeantal i loggen. Filteret kan mangle butikkens kategoribetegnelser, eller feedet kan mangle relevante produkter/priser.
- **Tidligere container gendannet:** se `docker logs pricerunner-watch` og opdateringsscriptets fejl. Backup ligger i kildemappens `backups/`.
- **PriceRunner blokeret:** brug feedtilstanden. Ved blokering bliver den tidligere crawler slået fra og gemmer diagnosticering under `diagnostics/<run-id>/blocked.txt`.
- **Permission denied /data:** kontrollér ejer af datamappen. Installationsscriptet ændrer ejeren af selve mappen; ikke rekursivt af alle filer.
- **Genstart:** aktive job får status afbrudt. De genoptages ikke midt i importen.

Compose er inkluderet: opret `.env` med `APP_PASSWORD=<mindst 16 tegn>`, klargør dataejeren som `pwuser`, og kør `docker compose up -d --build`.

## Tests og kilder

```bash
python3 -m unittest discover -s tests -v
```

27 tests, herunder API-requestformat, nøglebeskyttelse, GTIN-match, lagerstatus, historik, fejlede feeds, databaseovergang og HTTP-adgangskontrol. Se `TESTRESULTAT.md` for begrænsninger. Lokal feeddrift kræver Python-standardbiblioteket; den bevarede crawler kræver Playwright.

- https://apidocs.adtraction.net/v3/
- https://help.adtraction.com/en/articles/13398866-product-feeds-via-adtraction
- https://help.adtraction.com/en/articles/1563159-get-started-with-the-adtraction-api
- https://adtraction.com/dk/annoncorer/1743405744
- https://docs.klarna.com/acquirer/klarna/other-products/klarna-search/klarna-agentic-product-protocol/
- https://playwright.dev/python/docs/docker
