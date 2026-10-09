# Projektplan

## Ziel

Ein kleines öffentliches Demonstrationsprojekt, das wissenschaftlich saubere Modellierung und praktisch ausführbare Software für historische TEI-Texte zeigt.

## Phase 1: MVP (in diesem Repository)

- TEI P5 sicher parsen und gemischten Inhalt erhalten.
- Bestehende und neue Personen-, Orts- und Organisationsnamen erfassen.
- Optionales historisches deutsches NER als austauschbaren Adapter bereitstellen.
- CIDOC CRM Turtle mit Dokument-, Entitäts- und expliziten Versandereignissen ausgeben.
- Reproduzierbares fiktives Beispiel, Tests und klare Grenzen dokumentieren.

## Phase 2: Forschungsqualität

- [x] Quellenkorpus und Referenz auswählen; Precision/Recall/F1 pro Entitätstyp messen (v0.2, `eval/`).
- [x] Herkunft jeder Aussage und versionierte Modellparameter (v0.2, PROV und `appInfo`).
- [x] Stichprobe der nicht annotierten Namen vom Autor sichten lassen (26. September 2026; v0.2).
- [ ] Annotationsrichtlinien (Titel, Adressen) als Profil dokumentieren.
- [ ] Modellvergleich (z. B. SBB-NER), Schwellenwertkalibrierung auf einem getrennten Entwicklungsset.
- [ ] v0.3: kleine Oberfläche zum Annehmen, Ablehnen und Korrigieren von Kandidaten; bestätigte Kandidaten erhalten CRM-Klasse, `P67` und Normdaten.
- [ ] Menschlich annotierte Blindstichprobe, auch mit Briefen ohne ausgezeichnete Namen (die Korpusauswahl schließt sie bisher aus).
- [x] RDF/SHACL für das konkrete Mappingprofil (v0.5, `shapes/tcb-shapes.ttl` mit Profilen `source`/`reviewed`).
- [ ] TEI-ODD/Schematron für das konkrete Mappingprofil.

## Phase 3: Portfolio-Demo

- [x] Browseransicht mit Herkunft, URI und Score je Markierung; echter Brief mit Quellenangabe (v0.2).
- [x] Vorher/Nachher-Zahlen, belegte Fehlerfälle und methodische Entscheidungen (Projektseite).
- [ ] Dauerhafte URIs (z. B. w3id.org), Release-Tag mit DOI (Zenodo), Screenshots.

## Phase 4: Graph-Folgelaufträge (nach v0.5)

- [ ] SPARQL im Browser auf der Projektseite (WASM-Paket).
- [ ] Koreferenz von Kandidaten über Briefe hinweg.
- [ ] Verteilte Abfragen (`SERVICE`) gegen Wikidata oder GND.
