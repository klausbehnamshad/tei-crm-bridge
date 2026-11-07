# Changelog

## Unveröffentlicht (nach 0.5.0)

- Graph-Review: GND je `@ref`-Token, gesammelte Datumsfehler mit Datei, Brief und Handlung,
  sichtbarer Empfangsdatum-Fallback und vollständige Brief-URI als Gewichtungsidentität.
  Briefe mit Datumsfehlern bleiben als undatierte Kanten im Netz erhalten;
  `date_errors` steht in CLI-Ausgabe und `correspondence.date_errors` in `metrics.json`.
- Zusätzliche bipartite Nennungsausgabe mit E21/E53/E74; Personenprojektion
  auch für externe URIs außerhalb der PMB-Edition. Bisherige Korpuszahlen bleiben gleich.
  Mengenprüfung der Dokument-URI-Präfixe ersetzt den Vergleich mit jedem Brief.
- SHACL erfasst Annotationen ohne `origin`; Prüfvermerke adressieren weiterhin
  Annotationen. README nennt alle Bedingungen und bezeichnet Formkonformität
  nicht als fachliche Bestätigung.
- SELECT-Bindungsgrenze von pyoxigraph dokumentiert; klare Lade- und
  Abfragefehler, CSV-Kopf auch bei leerem Ergebnis, Store-Zählung ohne Python-Iteration.
- Reproduzierbarer Benchmark mit Einzelwerten, Quell- und Graphhashes.
  Historische Laufzeiten vom 09.10.2026 sind ohne Laufdatei unbelegt; neue
  Messung vom 10.10.2026 siehe `eval/sparql/benchmark-2026-10-10.json`.

## 0.5.0

Graph abfragbar, prüfbar, über Briefgrenzen nutzbar. Datenstand: 40 Briefe der Schnitzler-Edition, eingefrorener Graph in `eval/sparql/manifest.json`, alle Zahlen gemessen am 09.10.2026 auf macOS arm64.

### Triplestore und SPARQL
- Optionales Extra `store` (pyoxigraph): `tei-crm store` lädt Turtle-Dateien in einen persistenten Store, `tei-crm query` führt `.rq`-Dateien mit Variablenbindung aus (CSV, JSON, Tabelle).
- Q2 in FILTER-Form: gleiche 340 Zeilen wie bisher; im Store auf dem Vereinigungsgraphen unter einer Sekunde, in rdflib je Briefdatei empfohlen.

### Validierung mit SHACL
- Optionales Extra `validate` (pyshacl): Shapes in `src/tei_crm_bridge/shapes/tcb-shapes.ttl` mit Profilen `source` (Ausgangsgraph) und `reviewed` (geprüfter Graph); `tei-crm validate` meldet Exit 0 bei Formkonformität, Exit 1 bei Verstößen.
- Beide Demo-Graphen sind formkonform; vier Negativfälle scheitern je mit der erwarteten Shape; die CI validiert beide Demos.

### Netzwerk
- Optionales Extra `network` (networkx): `tei-crm network` baut aus `correspDesc` das Korrespondenznetz (26 Personen, 37 Kanten) und aus `P67` das Nennungsnetz (80 Personen, 237 Kanten), dazu `metrics.json` mit Methode, Version, Korpus und Ehrlichkeitshinweis.

### Vokabular
- Ontologie-Kopf mit `owl:Ontology` und `owl:versionInfo` in `build_vocabulary()`.

## Unveröffentlicht

### Reconciliation
- Neuer Unterbefehl `tei-crm reconcile` (`reconcile.py`): löst lokale Register-IDs über die PMB-API (Person/Ort/Institution) gegen GND, GeoNames und Wikidata auf und speichert sie mit Quelle, PMB-URI und Abrufdatum in einer committbaren JSON-Cache-Datei; `--offline` bleibt netzfrei, ein `Resolver`-Protokoll mit `PmbResolver` erlaubt andere Editionen.
- `tei-crm cmif ... --reconciliation FILE` füllt `@ref` aus dem Cache (nach Register-`idno`, vor direktem GND-`@ref`); `enrich ... --reconciliation FILE` ergänzt `rdfs:seeAlso` (kein `owl:sameAs`, keine CRM-Klasse).
- Live-PMB-Tests in `tests/test_reconcile_integration.py`, per `TCB_PMB_TESTS` wie die Modelltests gegated.
- `certifi` als Abhängigkeit: Das CA-Bundle wird additiv zum Plattform-Store geladen, sodass `SSL_CERT_FILE` weiter gilt (python.org-Python auf macOS hat sonst keinen CA-Store). Zertifikatsfehler ohne Retry, früher Abbruch nach drei gescheiterten Abrufen ohne Erfolg, Totalausfall endet mit Exit 1 ohne Cache-Schreiben.
- Verbindungsabbrüche (`RemoteDisconnected`, `IncompleteRead`, Resets) zählen als Netzfehler mit einem Retry. Der `--cache`-Pfad wird vor dem Netzlauf geprüft (Verzeichnis → Exit 2); fehlende Elternordner legt `save_cache` an.
- Fehler nach Ursache: Netz-, Zertifikats-, Überlastungs- (HTTP 429/502/503/504) und Driftfehler sind systematisch und zählen für den Abbruch (3 vor dem ersten Erfolg, 5 in Folge danach); ein einzelner HTTP-Fehler betrifft nur seine Entität und endet mit Exit 0 plus Hinweis. Mindestabstand `--delay` vor jeder Anfrage, auch bei Wiederholungen; 429/5xx mit Backoff und `Retry-After` (höchstens 60 s). Meldungen nennen Ursache und Anzahl in korrekter Einzahl/Mehrzahl, Netz- und Zertifikatsrat nur bei solchen Fehlern. Der Bericht enthält `status` und `failures`. TLS wird erst bei der ersten Anfrage aufgebaut, ein defektes certifi-Bundle fällt auf den System-Store zurück.
- Cache-Integrität: IDs ohne `pmb<N>`-Form werden übersprungen (Warnung, kein Eintrag); API-Antworten außerhalb der bekannten Form brechen den Lauf sofort ab (Exit 1, bisher Geholtes bleibt gespeichert); `save_cache` schreibt atomar mit Checkpoints alle 25 Einträge; Strg-C sichert und meldet Exit 130; korrupter Cache endet mit Exit 2 statt Traceback.

### CMIF
- Neuer Unterbefehl `tei-crm cmif` (`cmif.py`): sammelt `correspDesc`/`correspAction` vieler Originalbriefe in einer CMIF-Datei für correspSearch; Brief-URL aus `--url-pattern` (`{id}` = `xml:id`), stabile Dateiadresse aus `--cmif-url`, Titel/Verlag/Lizenz aus dem `teiHeader` oder aus Optionen.
- GND für Personen (`@ref` oder Register-`idno` `gnd`/`d-nb`), GeoNames für Orte (Register-`idno` `geonames`); ohne Normdaten Name ohne `@ref` plus Warnung; nur `sent`/`received`, Daten über `dates.py` geprüft.
- Gegen das offizielle CMIF-Schema (RNG) validiert; neue Tests in `tests/test_cmif.py`.
- Nur eigene Register-`idno` zählen (direkte Kinder und `location` ohne `type="located_in_place"`); `--out` legt fehlende Ordner an.

## 0.2.0

Gemessen an 40 Briefen der Schnitzler-Edition; Zahlen und Methode in [eval/README.md](eval/README.md).

### Erkennung
- Das Modell liest ganze Textblöcke statt einzelner Textknoten (`projection.py`); `<c>` bleibt im Wort, `<lb>`/`<space>` werden zu Leerzeichen, bei `@break="no"` entfällt auch der Leerraum daneben; `<note>`, `<del>`, `<index>`, `<interp>`, `<certainty>` und Beschreibungen in `<gap>` sind ausgeschlossen; `<choice>` liefert genau einen Zweig (`--reading`), `<app>` das `lem` (auch in `rdgGrp`); verschachtelte `floatingText` werden einmal gelesen.
- Außer `<p>` werden `opener`, `closer`, `address`, `salute`, `signed`, `dateline` und `postscript` gelesen.
- Lange Blöcke in überlappenden Fenstern (`--stride`, Standard 128) mit Abdeckungsprüfung; bisher wurde alles nach etwa 512 Tokens still abgeschnitten. Am Fensterrand abgeschnittene Teilnamen weichen dem ganzen Namen.
- Wortgenaue Aggregation (`--aggregation first`); Namen werden an TEI-Zeilengrenzen getrennt, reine Anredeformen verworfen.
- Andere Modelle: Labels werden auf PER/LOC/ORG abgebildet oder der Lauf bricht ab; `--revision`, die geladene Revision wird protokolliert.
- Glossartreffer tragen keinen Konfidenzwert mehr.

### TEI
- Inline-Elemente nur innerhalb eines Textknotens und nie in `c`/`g`/`w`/`pc`/`m`/`idno` oder fremden Namensräumen; sonst Stand-off.
- Keine neuen Namen in vorhandenen `persName`/`placeName`/`orgName`, Ortsteilen wie `settlement` oder `rs[@type=person|place|org]`.
- Neue Namen tragen `xml:id`, `@ref`, `@resp` und bei Modelltreffern `@cert`; der Lauf steht in `encodingDesc/appInfo/application`. Beim erneuten Verarbeiten bleiben frühere Vorschläge `tcb:Candidate` und verweisen auf die frühere Anwendung im TEI-Header.
- Integritätsprüfung nach jedem Lauf: gleicher Lesetext; die ursprüngliche Textauszeichnung ist nach Entfernen der Ergänzungen wiederherstellbar.
- Interne DTD-Entitäten werden aufgelöst, nicht deklarierte führen zu einer Fehlermeldung statt zu stillem Textverlust.

### RDF
- `correspAction` `sent` und `received` als getrennte `E7_Activity` mit `P2_has_type`.
- Datumsangaben von Jahr bis Sekundenbruchteil (höchstens sechs Stellen) und `notBefore`/`notAfter` als `P82a`/`P82b`-Intervalle; Zeitzonen werden validiert, mehrere Daten einer Handlung geschnitten und Widersprüche gemeldet.
- `@ref` bleibt erhalten: URI, `prefixDef` (einmal expandiert, fehlerhafte Muster gemeldet), `#id` auf die veröffentlichte TEI-Datei und relative Verweise mit `xml:base`; mehrere Registereinträge sind mehrere Entitäten; nur eigene `idno` eines Registereintrags als `rdfs:seeAlso`; Ungültiges oder Unauflösbares als `tcb:unresolvedRef` und Warnung.
- Automatische Treffer sind Annotationen mit einem `tcb:Candidate` (vorgeschlagene Klasse) als Körper; CRM-Klasse und `P67_refers_to` nur für redaktionelle Namen.
- W3C-Selektoren statt `ex:teiXPath`: präfixfreies XPath, Textposition und Zitat auf dem Stringwert der veröffentlichten TEI-Datei (`--tei-base-url`), Herkunft der Eingabe (`--source-url`).
- Provenienz (`prov:Activity`) mit Modell, Revision, Schwelle, Stride, Lesart und Version; deterministische Turtle-Ausgabe; Ausgaben werden erst geschrieben, wenn alles serialisierbar ist.

### Vorschau
- Herkunft, Quelle, URI und Score je Markierung; Stand-off-Liste; Änderungsvermerk für lizenzierte Quellen.
- Content-Security-Policy, nur http(s)-Links aus TEI-Daten, Detailansicht per DOM statt HTML-Strings.

### Projekt
- Evaluation (`eval/`) mit festgehaltenem Korpus (Blob-SHA geprüft), Referenzregeln, Stichprobe, Integritätsprüfung, festgehaltenen Paketversionen und Reproduktionsskript; `score` und `integrity` enden bei Befunden mit Fehlercode.
- Projektseite, echter Brief und Vokabular werden per `scripts/build_docs.py` erzeugt; die CI prüft Quellhash, gespeicherte Modellmetadaten, Rückbaubarkeit und Selektoren der Modell-Demo. Einen neuen Modelllauf führt die CI nicht aus.
- CLI: Schutz vor gleichen Dateinamen in einem Lauf, klare Meldung bei fehlendem Glossar.

## 0.1.0

Erster Prototyp: Glossar- und Hugging-Face-Erkennung pro Textknoten in `<p>`, CIDOC-CRM-Export mit Versandereignis, HTML-Vorschau.
