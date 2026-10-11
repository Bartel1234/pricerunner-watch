# Validering · beta.3 · 11. oktober 2026

- 27 Python unittest-tests bestået.
- JavaScript-syntaks kontrolleret med Node --check.
- Python-moduler kompileret uden fejl.
- Installations- og opdateringsscript kontrolleret med bash -n.
- API-tests bruger dokumenterede Adtraction v3-felter og simulerede svar; ingen nøgle eller live-feed er tilgængeligt i udviklingsmiljøet.
- Feed-worker kontrolleret for succes, prisfald, fejlet feed uden tab af historik, og deaktivering af automatik ved fejl.
- GTIN-kontrolciffer, butiksspecifik fallback, deduplikering, ukendt lager, valuta/marked/godkendelse og credential-redaktion kontrolleret.
- HTTP-testen starter den rigtige lokale webserver. Databaseovergang bevarer eksisterende data og slår den tidligere crawler-automatik fra.
- Docker findes ikke i udviklingsmiljøet: image-build, sundhedstjek og opdateringsscriptets rollback er ikke kørt mod Docker. Live-test på DeathStar kræver brugerens nøgle, kanal-ID og godkendte feeds.
- PriceRunner-crawleren er tidligere observeret blokeret med HTTP 403 på DeathStar. Beta.3 løser datakildevalget; den ophæver ikke blokeringen.
