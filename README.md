# PriceRunner Watch · 0.1.0-beta.2

En første, lokal PriceRunner-monitor til Unraid. Én container, Chromium, dansk webinterface og SQLite. Ingen ekstern AI-tjeneste eller API-nøgle er nødvendig.

## Rettelse i beta.2

Ved adgangsblokering gemmes PriceRunners sidetekst, URL og HTTP-status, før browseren lukker. Beta.1 forsøgte først at læse teksten efter lukningen og skjulte fejlen. Rapporten ligger under `diagnostics/<run-id>/blocked.txt` i datamappen. Denne rettelse ændrer ikke PriceRunners adgangskontrol.

## Status — læs dette først

PriceRunner-adgangen blev testet fra ChatGPT-browseren 11. oktober 2026: katalogets første to batches (96 RAM-produkter) samt to produktsider kunne læses; én produktside viste seks butikker. Denne kode bygger på de observerede links og tilbudsetiketter.

Containeren er **ikke live-testet på DeathStar**. En anden browser/IP kan blive blokeret. Den medfølgende testpakke kontrollerer prisfortolkning, dubletter, historik, kandidatlogik, adgangskontrol og jobfejl lokalt. Første installation er derfor en afgrænset driftstest, ikke et løfte om stabil fuld crawling.

## Hent fra GitHub og installér på Unraid

Kør i Unraids terminal (kræver Git):

```bash
git clone https://github.com/Bartel1234/pricerunner-watch.git /mnt/user/appdata/pricerunner-watch-src
cd /mnt/user/appdata/pricerunner-watch-src
bash install-unraid.sh
```

Hvis mappen allerede findes fra ZIP-installationen, skal du beholde den eller vælge en ny tom kildemappe. `git clone` overskriver den ikke. Installationsscriptet stopper også, hvis containeren allerede findes.

Repositoryet indeholder kildekoden. Imaget bygges lokalt på Unraid; et færdigbygget GHCR-image er endnu ikke udgivet.

## Installation fra ZIP (Docker Compose er ikke nødvendigt)

1. Pak ZIP-filen ud, og kopiér mappen `pricerunner-watch` til f.eks. `/mnt/user/appdata/pricerunner-watch-src` via dit SMB-share.
2. Åbn Unraid-terminalen, og kør:

```bash
cd /mnt/user/appdata/pricerunner-watch-src
bash install-unraid.sh
```

3. Første build henter Microsofts Playwright-image og kan tage flere minutter. Data placeres i `/mnt/user/appdata/pricerunner-watch`.
4. Åbn `http://DIN-UNRAID-IP:8788`. Brugernavn: `admin`. Adgangskoden står i `.env` i kildemappen (filen genereres af installationen).
5. Klik **Start scanning**. Standard: RAM, højst 2 katalogbatches og 24 produktsider med 8 sekunders pause. Regn med flere minutter.
6. Se status, fejl og de første butikstilbud. Tilføj derefter Grafikkort og Harddiske/SSD under Indstillinger. Du kan også indsætte specifikke `/pl/…` produktlinks eller filtrerede `/cl/…` kategorilinks fra din browser.

Alternativ port: `WEB_PORT=8790 bash install-unraid.sh`. Alternativ datamappe: `DATA_PATH=/mnt/user/appdata/pricerunner-test bash install-unraid.sh`.

Brug webinterfacet på dit betroede hjemmenet eller gennem din eksisterende VPN. Login anvender HTTP Basic; brug HTTPS via en adgangsbeskyttet reverse proxy ved fjernadgang. Udstil ikke HTTP-porten direkte på internettet. Containeren får ikke adgang til Docker-socket, host-netværk eller andre shares.

## Hvad versionen gør

- Følger katalogets **Vis flere**-knap og læser synlige produktlinks.
- Besøger produktsider og udlæser butikkens navn og samlede varepris fra `Åbn tilbud fra … Pris: …` — aldrig månedsydelsen.
- Gemmer tilbuddenes synlige leveringstekst, bestillingsvare/udsolgt-markering og UTC-tidspunkt.
- Gemmer hver succesfuld observation som historik. Fejl overskriver ikke en gammel pris med nul.
- Fjerner identiske butikstilbud og reklamedubletter. Sammenligner samme PriceRunner-produkt-ID på tværs af forskellige butikker.
- Marker kandidat ved mindst 35% forskel til næstbilligste butik, når mindst tre butikker har et læsbart tilbud, eller ved 35% fald fra produktets forrige måling. Grænsen kan ændres.
- Priser er **eksklusive fragt**. Bestillingsvarer kan være kandidater, men markeres i tilbudsvisningen. Ukendt lagerstatus er ikke et løfte om lager.
- Måler de ældst besøgte eller endnu ikke besøgte produkter først inden for det indlæste katalog. Større batchgrænse er nødvendig for at nå længere ind i kategorien; systemet roterer ikke automatisk gennem hele kataloget.
- Én scanning ad gangen, stopknap, delresultater og status efter genstart.
- Valgfrit interval (mindst 6 timer). Fra som standard. Ved adgangsbegrænsning stoppes jobbet, og intervallet sættes til 0. Der bruges ingen proxyrotation, stealth eller CAPTCHA-omgåelse.
- Eksport af aktuelle målinger til JSON. Fuld historik ligger i SQLite-databasen.

## Hvad en kandidat betyder

Det er et spor, ikke en bekræftet prisfejl. PriceRunner kan have forsinkede priser, fejlkategoriseringer og forkerte produktmatches. Åbn produktet på PriceRunner og kontrollér modelnummer, pris, lager og samlet beløb hos butikken før et køb.

En status **delvis** betyder, at en grænse blev nået, eller at enkelte sider fejlede. Det er aldrig en bekræftelse på, at hele kategorien blev gennemgået. Katalogets annoncer/relaterede produkter kan give flere fundne links end det viste batchantal.

Denne beta sender ingen Pushbullet-beskeder og foretager ingen køb. Advarsler vises i webinterfacet. Beskeder bør først kobles på, når datakvaliteten er testet fra DeathStar.

## Fejlfinding

- **Blokeret:** intervallet er automatisk slået fra. Se loggen. Adgangen fra serveren er begrænset; gentagne genstarter er ikke en løsning.
- **Ingen butikstilbud:** PriceRunner kan have ændret layout, siden kan mangle tilbud eller indlæsningen kan være fejlet. Tidligere målinger forbliver daterede.
- **Browserstarter fejl:** se `docker logs pricerunner-watch`. Image og Python-pakke er begge låst til Playwright 1.63.0.
- **Permission denied /data:** tjek ejeren af den dedikerede datamappe. Installationsscriptet sætter kun ejeren på mappen selv, ikke rekursivt.
- **Stop:** en igangværende navigation kan bruge op til ca. 45 sekunder, før jobbet reagerer.
- **Container genstartet:** et aktivt job får status afbrudt. Det genoptages ikke midt i en side.

Fejltekster fra sider gemmes under `data/diagnostics/<run-id>/`. Disse og historikken slettes ikke automatisk i betaen. Der gemmes ikke PriceRunner-login, cookies eller browserprofiler mellem jobs.

## Backup, opdatering og fjernelse

Stop containeren før du kopierer hele datamappen; SQLite bruger WAL, så kopier ikke kun `.sqlite3`-filen under drift. Tag også en kopi af kildemappens `.env`.

Opdatering: behold datamappen og `.env`, stop og fjern kun containeren via Unraid, udskift kildefilerne, og kør installationsscriptet igen. Databasen bliver bevaret. Der er intet publiceret registry-image i denne pakke, så Unraids almindelige image-opdatering henter ikke nye kildefiler.

Fjernelse: stop og fjern containeren i Unraid. Behold datamappen, hvis du vil kunne vende tilbage. Installationsscriptet nægter at overskrive en eksisterende container.

Compose er også inkluderet: opret `.env` med `APP_PASSWORD=<mindst 16 tegn>` og evt. `DATA_PATH=…`, klargør datamappens ejer som image-brugeren `pwuser`, og kør `docker compose up -d --build`.

## Udvikling og tests

Python 3.12+ anbefales. Testene kræver kun standardbiblioteket:

```bash
python3 -m unittest discover -s tests -v
```

Lokal kørsel kræver `pip install -r requirements.txt`, `python -m playwright install chromium` og systembiblioteker til Chromium. Sæt `APP_PASSWORD`, og start `python app.py`.

Teknisk kilde til image/version: https://playwright.dev/python/docs/docker
