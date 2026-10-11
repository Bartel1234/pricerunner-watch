# Validering 11. oktober 2026

- 17 tests bestået via Python unittest.
- JavaScript-syntaks kontrolleret med Node --check.
- Python-moduler kompileret uden fejl.
- Installationsscript kontrolleret med bash -n.
- Worker-testene bruger en simuleret browser; HTTP-testen starter den rigtige lokale webserver.
- Live PriceRunner-adgang blev tidligere bekræftet i ChatGPT-browseren; den leverede container er ikke live-testet.
- Docker er ikke tilgængelig i byggemiljøet. Image-build, Chromium-opstart og adgang fra DeathStar afventer første installation.

Beta.2: regresstest bekræfter, at blokeringens sidetekst overlever browserlukning, og at en skrivefejl rapporteres. Docker-build af beta.2 afventer Unraid. Brugerens beta.1-container startede, men scanningen registrerede adgangsblokering.
