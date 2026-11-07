# TEI CRM Bridge

[![tests](https://github.com/klausbehnamshad/tei-crm-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/klausbehnamshad/tei-crm-bridge/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22979658.svg)](https://doi.org/10.5281/zenodo.22979658)

Ein Werkzeug für Digital Humanities: Es ergänzt TEI-P5-Briefe um Personen, Orte und Organisationen, bewahrt dabei den Lesetext und die vorhandene Textauszeichnung, legt Aussagen und Vorschläge mit ihrer Herkunft als CIDOC CRM und W3C Web Annotation ab und misst sich an der redaktionellen Auszeichnung einer echten Edition.

**[Projektseite mit Messung](https://klausbehnamshad.github.io/tei-crm-bridge/)** · [echter Brief (Schnitzler-Edition)](https://klausbehnamshad.github.io/tei-crm-bridge/schnitzler/L02051.html) · [fiktives Beispiel](https://klausbehnamshad.github.io/tei-crm-bridge/example/letter.html) · [Evaluation](eval/README.md)

**Status:** Forschungsprototyp, kein fertiges Editionssystem. Automatisch erkannte Namen sind im Ausgangsgraphen Vorschläge; eine redaktionelle Entscheidung kann einen getrennten geprüften Graphen erzeugen.

*English summary: TEI CRM Bridge adds person, place and organisation names to TEI letters while preserving the reading text and existing text markup, records statements and suggestions with provenance (CIDOC CRM, W3C Web Annotation, PROV-O), and is evaluated against the editorial annotation of 40 letters from the Arthur Schnitzler correspondence edition.*

## Ergebnis von Version 0.2

<!-- results:start -->
Gemessen an 40 Briefen der Schnitzler-Edition (295 redaktionelle Referenzen), gleiche Eingaben und gleiches Modell für beide Versionen:

| | v0.1 | v0.2 |
| --- | ---: | ---: |
| nur Text in `<p>`, strikt: F1 (P / R) | 0,619 (0,688 / 0,563) | 0,668 (0,770 / 0,591) |
| nur Text in `<p>`, überlappend: F1 (P / R) | 0,706 (0,784 / 0,642) | 0,747 (0,861 / 0,660) |
| alle Blöcke, strikt: F1 (P / R) | 0,514 (0,688 / 0,410) | 0,535 (0,528 / 0,542) |
| alle Blöcke, überlappend: F1 (P / R) | 0,586 (0,784 / 0,468) | 0,702 (0,693 / 0,712) |
| neue Namen an unzulässiger Stelle (Originalbriefe) | 307 von 336 | 0 von 55 |
| Briefe mit verändertem Lesetext / Markup | 0 / 0 | 0 / 0 |

Im Text, den v0.1 las (`<p>`), steigen Präzision und F1. Über alle Blöcke steigt der Recall, die strikte Präzision sinkt: v0.2 liest auch Adressen, Briefköpfe und Grußformeln, und 67 seiner 78 falschen Treffer liegen dort. Wie viele davon nicht annotierte Namen sind, zeigt eine Stichprobe von zehn Briefen ([eval/README.md](eval/README.md)).
<!-- results:end -->

## Schnellstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
tei-crm examples/letter.xml --glossary examples/glossary.json
```

Das erzeugt in `build/` die angereicherte TEI-Datei, einen Turtle-Graphen, eine Mentions-Datei (JSON) und eine HTML-Vorschau. Der Glossar-Modus ist deterministisch und dient dem schnellen lokalen Durchlauf; er ist **keine KI** und vergibt keine Konfidenz.

## Redaktionelle Prüfung (Version 0.3)

Die HTML-Vorschau öffnet sich direkt im Browser, auch ohne Server. Ein Klick auf eine automatisch erkannte Inline-Markierung oder einen Stand-off-Treffer zeigt Text, Typ, Position, Quelle und Kandidaten-URI. Die prüfende Person vergibt **Annehmen**, **Ablehnen** oder **Offen lassen** und kann eine Begründung ergänzen. Die Übersicht zählt die drei Zustände. Entscheidungen werden lokal im Browser gehalten; **Review-Datei exportieren** sichert sie als JSON, **Review-Datei importieren** lädt sie wieder. Für den Export ist ein Name oder Kürzel erforderlich.

Die Review-Datei bindet jede Entscheidung an Fundstellen-ID, Textspanne, Zeitstempel sowie SHA-256-Prüfsummen der Eingabe, Mentions-Datei und des ursprünglichen RDF-Graphen. Danach lokal einen **separaten** Graphen erzeugen:

```bash
tei-crm-review build/letter.mentions.json build/letter.ttl \
  build/letter-001.review.json build/letter.reviewed.ttl
```

Die Dateinamen hängen vom Eingabedokument ab. Das Kommando prüft die Bindung und lehnt veraltete, doppelte oder auf redaktionelle Namen bezogene Entscheidungen ab. Es fügt `oa:assessing`-Annotationen mit Entscheidung, Zeitpunkt und prüfender Person hinzu. Nur für angenommene Nennungen erhält der Kandidat eine CIDOC-CRM-Klasse und das Dokument `crm:P67_refers_to`. Die ursprüngliche TEI und der ursprüngliche RDF-Graph bleiben unverändert. Gleichlautende Nennungen können denselben Kandidaten teilen: Eine Ablehnung betrifft die einzelne Fundstelle; eine Annahme bestätigt die gemeinsame Entität im geprüften Graphen. Die Review-Oberfläche bietet noch keine Normdaten-Verknüpfung und keinen Mehrpersonen-Workflow.

Für historisches deutsches NER:

```bash
pip install -e '.[ner]'
tei-crm brief.xml --engine hf --base-uri https://example.org/mein-projekt/
```

Der `hf`-Modus lädt [`impresso-project/ner-hipe2020-hist-base`](https://huggingface.co/impresso-project/ner-hipe2020-hist-base) in einer festgehaltenen Revision. `--local-files-only` verlangt bereits vorhandene Modelldateien; `--model` (mit `--revision`) erlaubt ein anderes Modell, dessen Labels auf Personen, Orte und Organisationen abgebildet werden – ohne passende Labels bricht der Lauf ab. Mit `--tei-base-url` zeigen die Annotationen auf die veröffentlichte TEI-Datei, `--source-url` verknüpft die Eingabe als Herkunft. Die Textinferenz läuft lokal; eine pauschale Aussage „100 % offline/DSGVO-konform“ wäre ohne Prüfung der Betriebsumgebung nicht seriös. Das Modell steht unter CC BY-NC-SA 4.0 und wird nicht mit dem MIT-lizenzierten Code verteilt.

## So arbeitet das Werkzeug

**1. Lesetext bilden** ([`projection.py`](src/tei_crm_bridge/projection.py)). Jeder Textblock (`p`, `opener`, `closer`, `address`, `salute`, `signed`, `dateline`, …) wird zu einem zusammenhängenden Text; jedes Zeichen bleibt auf seinen XML-Textknoten rückführbar.

| TEI | Regel |
| --- | --- |
| `<c>`, `<hi>`, `<g>`, `<add>`, andere Inline-Elemente | Text ohne Trenner: „Ro`<c>`s`</c>`a“ bleibt „Rosa“ |
| `<lb/>`, `<pb/>`, `<space/>` | ein Leerzeichen; bei `@break="no"` geht das Wort weiter, Leerraum daneben entfällt |
| Zeilen in Brief­kopf, Adresse, Grußformel | Zeilenumbruch; ein Name endet an einer Zeilengrenze, eine Anrede allein ist kein Name |
| `<note>`, `<del>`, `<fw>`, `<index>`, `<interp>`, `<certainty>`, Beschreibungen in `<gap>` | nicht Teil des Lesetexts |
| `<choice>` | genau ein Zweig: `corr`/`reg`/`expan` (`--reading edited`, Standard) oder `sic`/`orig`/`abbr` (`diplomatic`) |
| `<app>` | das `lem` (auch in `rdgGrp`), sonst die erste `rdg` |
| vorhandene `persName`/`placeName`/`orgName`, Ortsteile wie `settlement`, `rs[@type=person\|place\|org]` | Annotation der Edition; darin entstehen keine neuen Namen |

**2. Namen erkennen** ([`ner.py`](src/tei_crm_bridge/ner.py)). Das Modell sieht den ganzen Block statt einzelner Textknoten; im Beispielbrief erhält „Jena“ allein das Label Person (0,478), im Satz Ort (0,999). Lange Blöcke werden in überlappenden Fenstern gelesen (`--stride 128`, nur mit Fast-Tokenizer); ist ein Text nicht vollständig abgedeckt, bricht der Lauf ab, statt still zu kürzen. Am Fensterrand abgeschnittene Teilnamen weichen dem ganzen Namen aus dem Nachbarfenster. Die Aggregation `first` erzeugt wortgenaue Grenzen.

**3. Behutsam zurückschreiben** ([`writeback.py`](src/tei_crm_bridge/writeback.py)). Ein neues `persName`/`placeName`/`orgName` entsteht nur, wenn Anfang und Ende im selben Textknoten liegen und das Elternelement Namen erlaubt; es trägt `xml:id`, `@ref`, `@resp` und bei Modelltreffern `@cert`. Treffer über Elementgrenzen bleiben Stand-off-Annotationen. Nach dem Schreiben prüft das Werkzeug, dass der Lesetext identisch ist und das Entfernen der neuen Elemente exakt das Original ergibt; sonst bricht es ab. Der Verarbeitungslauf wird in `encodingDesc/appInfo/application` dokumentiert.

**4. Nachvollziehbar modellieren** ([`rdf.py`](src/tei_crm_bridge/rdf.py)).

| TEI/Quelle | RDF |
| --- | --- |
| TEI-Dokument | `crm:E31_Document`; die TEI-Datei als `dcterms:isFormatOf` |
| redaktioneller Name | `oa:Annotation` (`tcb:editorial`), Entität mit CIDOC-CRM-Klasse, `crm:P67_refers_to` |
| automatischer Name | `oa:Annotation` (`tcb:automatic`) mit `prov:wasGeneratedBy` und Modellscore; Körper ist ein `tcb:Candidate` mit `tcb:suggestedClass` – **keine** CRM-Instanz, **kein** `P67` |
| Textstelle | `oa:SpecificResource` in der veröffentlichten TEI-Datei; `oa:XPathSelector` ohne Präfixbindung, verfeinert durch `oa:TextPositionSelector` und `oa:TextQuoteSelector` auf dem Stringwert der Datei |
| `@ref` | URI direkt; `gnd:…` über `prefixDef`; `#id` zeigt auf das `xml:id` der TEI-Datei, relative Verweise nutzen `xml:base`; mehrere Registereinträge sind mehrere Entitäten; eigene `idno` des Registereintrags (GND, Wikidata, GeoNames) als `rdfs:seeAlso`; Unauflösbares bleibt als `tcb:unresolvedRef` erhalten |
| `correspAction[@type=sent\|received]` | je ein `crm:E7_Activity` mit `crm:P2_has_type tcb:sending\|tcb:receiving`, `P14_carried_out_by`, `P7_took_place_at` |
| `date/@when` (Jahr, Monat, Tag, Uhrzeit), `@notBefore`/`@notAfter` | `crm:E52_Time-Span` mit `P82a_begin_of_the_begin`/`P82b_end_of_the_end`; keine erfundene Genauigkeit; mehrere Daten einer Handlung werden geschnitten, Widersprüche gemeldet |
| Verarbeitungslauf | `prov:Activity` mit Verfahren, Modell, Revision, Schwelle, Stride, Lesart, Softwareversion |

`owl:sameAs` wird nicht gesetzt: Gleichlautende automatische Namen teilen sich pro Dokument einen Kandidaten, der erst nach redaktioneller Prüfung eine CRM-Klasse und Normdaten erhalten sollte. Die wenigen eigenen Terme stehen im [Vokabular](https://klausbehnamshad.github.io/tei-crm-bridge/vocab/).

## Evaluation

Das Korpus sind 40 Briefe der Edition [Arthur Schnitzler: Briefwechsel mit Autorinnen und Autoren](https://schnitzler-briefe.acdh.oeaw.ac.at/) (CC BY 4.0), nach fester Regel aus einem festgehaltenen Commit ausgewählt. Die redaktionellen Namen dienen als Referenz, die Auszeichnungen werden vor dem Lauf entfernt. Methode, Stichprobe, Fehleranalyse und alle Zahlen: [eval/README.md](eval/README.md).

```bash
pip install -e . -r eval/requirements.txt   # zentrale Pakete in gemessenen Versionen; kein vollständiges Lockfile
git worktree add ../tcb-v0.1 e09fa38         # Ausgangsstand für den Vergleich
sh eval/reproduce.sh                          # alle Kennzahlen
python scripts/build_docs.py --with-model     # Projektseite, Demo und diese Ergebnistabelle
```

## Tests

```bash
pip install -e '.[test]'
pytest -q                                  # schnell, ohne Modell (CI)
TCB_MODEL_TESTS=1 pytest -m integration    # mit dem Modell: Kontext, 5.640-Zeichen-Text, Fenstergrenze
```

## CMIF-Export für correspSearch

```bash
tei-crm cmif eval/corpus/L*.xml --out build/cmif.xml \
  --url-pattern 'https://edition.example.org/{id}.html' \
  --cmif-url 'https://example.org/cmif.xml'
```

Der Unterbefehl sammelt die `correspDesc`/`correspAction`-Metadaten vieler Originalbriefe
(kein NER nötig) in einer CMIF-Datei des [TEI Correspondence SIG](https://github.com/TEI-Correspondence-SIG/CMIF).
Die Brief-URL in `correspDesc/@ref` entsteht aus `--url-pattern`, indem `{id}` durch die
`xml:id` des Briefs ersetzt wird; ohne Muster steht stattdessen `key=<xml:id>`.
Personen erhalten die GND-URI (aus `@ref`, sonst aus der Register-`idno` der Subtypes
`gnd`/`d-nb`), Orte die GeoNames-URI (Register-`idno` des Subtypes `geonames`); ohne
Normdaten steht der Name ohne `@ref` und es gibt eine Warnung. Nur `sent`/`received`
werden übernommen, Datumsangaben werden über `dates.py` geprüft. Titel, Verlag und Lizenz
kommen aus dem `teiHeader` der Briefe (`--title`, `--publisher`, `--licence` setzen sie).
Hinweis: Die briefbegleitenden Register tragen keine GND-/GeoNames-IDs. Dafür gibt es
die Reconciliation:

```bash
tei-crm reconcile eval/corpus/L*.xml --cache build/reconciliation.json
tei-crm cmif eval/corpus/L*.xml --out build/cmif.xml --reconciliation build/reconciliation.json \
  --url-pattern 'https://edition.example.org/{id}.html' --cmif-url 'https://example.org/cmif.xml'
```

`reconcile` löst die lokalen Register-IDs (`pmb<N>`) über die PMB-API gegen GND
(Personen/Organisationen), GeoNames (Orte) und Wikidata auf und legt sie mit Quelle,
PMB-URI und Abrufdatum in einer committbaren JSON-Cache-Datei ab (eine höfliche Anfrage
je unbekannter Entity). Der zweite Lauf mit `--offline` nutzt nur den Cache und macht
keinen Netzaufruf. `cmif` (und `enrich`, dort als `rdfs:seeAlso`) konsumieren nur diese
Datei: erst vorhandene Register-`idno`, dann Cache, dann direktes GND-`@ref`.
Für TLS lädt das Paket `certifi` zusätzlich zum System-Store; `SSL_CERT_FILE` gilt weiter.
Zwischen zwei Anfragen liegen mindestens `--delay` Sekunden, auch bei Wiederholungen;
auf HTTP 429/502/503/504 wartet `reconcile` (bis zu drei Versuche, `Retry-After` wird
beachtet, höchstens 60 s). Netz-, Zertifikats- und Überlastungsfehler gelten als
systematisch: Drei davon vor dem ersten Erfolg oder fünf in Folge danach brechen den Lauf
ab (Exit 1, Geholtes bleibt gespeichert), ebenso ein Lauf ohne jeden Erfolg. Ein einzelner
HTTP-Fehler betrifft nur seine Entität: Exit 0 mit Hinweis auf stderr, ein späterer Lauf
versucht sie erneut. IDs ohne `pmb<N>`-Form werden übersprungen. Antwortet die API
außerhalb ihrer bekannten Form, bricht der Lauf mit Exit 1 ab. Strg-C sichert und meldet
Exit 130. Der JSON-Bericht nennt das Ergebnis in `status`
(`ok`, `partial`, `no_progress`, `aborted`, `drift`, `interrupted`) und listet `failures`.

## Triplestore und SPARQL

```bash
pip install -e '.[store]'
tei-crm store eval/work/sparql/letters/*.ttl --db build/store
tei-crm query eval/sparql/q3_shared_persons.rq --db build/store
tei-crm query eval/sparql/q1_persons_places.rq --graph eval/work/sparql/union.ttl \
  --bind doc=https://example.org/tei-crm-demo/document/L03501 --format csv
```

`store` lädt Turtle-Dateien in einen persistenten pyoxigraph-Store unter
`--db`. `query` fragt einen Store oder Turtle-Dateien (`--graph`) ab;
`--bind name=WERT` belegt Variablen (gültige IRI wird IRI, sonst Literal),
`--format csv|json|table` wählt die Ausgabe. Unterstützt werden SELECT-Abfragen;
jede gebundene Variable muss im SELECT stehen (Grenze von pyoxigraph
`substitutions`). Werte werden nicht in den Abfragetext eingesetzt. Auch leere
CSV-Ergebnisse enthalten ihre Spaltenüberschrift. Lade-, Parse- und Abfragefehler
enden mit Exit 1 und einer Meldung. Q2 läuft in rdflib je
Briefdatei, mit dem Store auf dem Vereinigungsgraphen (FILTER-Form).

Laufzeiten vom 10.10.2026, macOS 26.6.2 arm64, Python 3.13.9, 40 Briefe
(Datenstand `eval/sparql/manifest.json`). Median von drei Wiederholungen ohne
Warmup, inklusive Ergebnis-Materialisierung, ohne Laden/Parsen/Zählen.
Einzelwerte, Spannweiten, Versionen, Graph- und Quellhashes stehen in
[`benchmark-2026-10-10.json`](eval/sparql/benchmark-2026-10-10.json).
Reproduktion (benötigt das Extra `store`, keinen Modelllauf):

```bash
python eval/sparql/build_graph.py --out-dir eval/work/sparql
python eval/sparql/benchmark.py --graph-dir eval/work/sparql \
  --out eval/work/sparql/benchmark.json --repeats 3
```

rdflib 7.6.0:

| Abfrage | Bindung | Zeilen | Zeit |
| --- | --- | --- | --- |
| Q1 Union | keine | 264 | 0,013 s |
| Q3 Union | keine | 41 | 0,027 s |
| Q2 je Brief, summiert | keine | 340 | 1,533 s |
| Q2 je Brief, summiert | Kainz | 2 | 0,607 s |

pyoxigraph 0.5.11, gleiche Daten:

| Abfrage | Bindung | Zeilen | Zeit |
| --- | --- | --- | --- |
| Laden 40 (ohne Zählen) | keine | 10.434 Tripel | 0,015 s |
| Q1 Union | keine | 264 | 0,002 s |
| Q3 Union | keine | 41 | 0,001 s |
| Q2 Union | keine | 340 | 0,598 s |
| Q2 Union | Kainz | 2 | 0,226 s |

Beide Engines liefern dieselben Zeilen (Multimengenvergleich in
`tests/test_store.py`).

## Validierung mit SHACL

```bash
pip install -e '.[validate]'
tei-crm validate docs/example/letter.ttl
tei-crm validate docs/schnitzler/L02051.ttl
```

Das Profil `source` gilt dem Ausgangsgraphen, `reviewed` dem Graphen mit
Prüfvermerken (`--profile source|reviewed`, Standard `source`). `reviewed`
erlaubt `P67` auf Kandidaten mit CRM-Klasse; ein Annahmevermerk für diese
Entität wird dabei nicht verlangt. Der Profilname bestätigt keine Prüfung. Exit 0
heißt formkonform, Exit 1 nennt Verstöße mit Fokusknoten, Shape und
Meldung. Formkonform heißt nur Form; fachliche Richtigkeit prüft das
Profil nie.

| Regel | Shape |
| --- | --- |
| Kandidat ohne CRM-Klasse: `tcb:Candidate` ohne E21/E53/E74 (nur `source`) | CandidateShape |
| P67-Kandidatenbedingungen: jedes P67-Ziel; in `source` kein Candidate, in `reviewed` Candidate nur mit E21/E53/E74; keine Annahmeprüfung | P67SourceShape, P67ReviewedShape |
| Provenienz automatischer Nennungen: `oa:Annotation` mit `origin automatic` braucht mindestens ein `wasGeneratedBy` **oder** `wasAttributedTo` | AutomaticProvenanceShape |
| Konfidenz höchstens eine von 0 bis 1: nur automatische `oa:Annotation`, Wert darf fehlen | ConfidenceShape |
| Belegstelle und Prüfvermerk-Target: jede `oa:Annotation` sowie jedes Subjekt mit `tcb:origin` braucht genau ein Target; gewöhnliche Annotation: genau eine `hasSource` und mindestens ein `hasSelector` im Target; Prüfvermerk mit `motivatedBy assessing`: Target vom Typ `oa:Annotation` | MentionTargetShape |
| Ereignis mit Typ und Ausführendem: jedes E7 braucht genau ein P2 aus `sending`/`receiving` und mindestens ein P14 | EventShape |
| Zeitspanne aufsteigend: bei E52 mit beiden Grenzen P82a ≤ P82b; Grenzen müssen nicht vorhanden sein | TimeSpanShape |
| Lauf mit Engine und Version: jede `prov:Activity` braucht mindestens einen Engine- und SoftwareVersion-Wert; deren Richtigkeit wird nicht geprüft | RunShape |
| Prüfvermerk mit Urheber, Zeit und Urteil: `oa:Annotation` mit `motivatedBy assessing` braucht je genau einen Creator, Created und Body; Body aus `accepted`/`rejected` (nur `reviewed`) | AssessingShape |

## Netzwerk

```bash
pip install -e '.[network]'
tei-crm network eval/corpus/L*.xml --out-dir build/network \
  --graphs eval/work/sparql/letters/*.ttl
```

Der Lauf schreibt `correspondence.graphml`, `correspondence_edges.csv`,
`mentions.graphml`, `mentions_edges.csv`, `mentions_bipartite.graphml`,
`mentions_bipartite_edges.csv` und `metrics.json` (Methode,
Software- und networkx-Version, Korpus mit SHA-256, Datum). Beispielzahlen vom 10.10.2026,
40 Briefe (Datenstand `eval/sparql/manifest.json`), Version 0.5.0:
Korrespondenz 26 Personen und 37 Kanten, Nennungen 80 Personen und
237 Kanten; bipartit 40 Briefe und 185 Entitäten, 273 Kanten.

Das bipartite Netz verbindet Brief-URIs über P67 mit externen URIs der Klassen
E21/E53/E74. Die Personenprojektion enthält alle solchen E21-Personen, auch
außerhalb des PMB-Namensraums, und alle gemeinsam genannten Paare. Q3 bildet
eine Teilmenge davon; die Projektion ist kein Filter auf Q3. `weight` zählt
verschiedene vollständige Brief-URIs; `letters` zeigt kurze IDs und die
zusätzliche Spalte `letter_uris` bewahrt die vollständige Identität.

Korrespondenzkanten tragen parallele Listen `letters`, `date_begin`, `date_end`
und `date_source` (`sent`, ersatzweise `received`, sonst `none`); `date_fallbacks`
nennt Briefe mit Empfangsdatum als Ersatz. Ungültige oder widersprüchliche
Datumsangaben werden unter `correspondence.date_errors` in `metrics.json`
und als `date_errors` in der CLI-Ausgabe gesammelt, mit Datei, Brief, Handlung
und Meldung. Betroffene Briefe behalten ihre Kanten mit leeren Datumsgrenzen
und `date_source none`; der Netzlauf läuft weiter. Mehrere Daten derselben
Handlungsart werden geschnitten. Grade sind ungewichtete Gesamtgrade (bei
gerichteten Netzen Eingang plus Ausgang), Betweenness ist normalisiert und
ungewichtet; Komponenten sind bei gerichteten Netzen schwach zusammenhängend.
Ehrlichkeitsregel aus `metrics.json`: „Kennzahlen
beschreiben die Auszeichnung der Edition im gegebenen Korpus.“

## Grenzen

- Q2 bleibt in rdflib auf dem Vereinigungsgraphen langsam (Minuten); empfohlen sind je Briefdatei oder der Store.
- Netzwerkkennzahlen beschreiben die Auszeichnung der Edition, keine Bedeutung von Personen.
- SHACL prüft Form, keine fachliche Richtigkeit.
- Die Referenz ist eine Edition mit eigenen Richtlinien: Korrespondenzpartner in Adressen und Unterschriften sind dort nicht ausgezeichnet, Titel gehören nicht zum Namen. Die Zahlen messen daher Übereinstimmung mit dieser Edition, nicht absolute Richtigkeit.
- Organisationen kommen im Korpus nur elfmal vor; dafür gibt es keine belastbare Aussage.
- Keine Koreferenz, keine automatische Verlinkung mit GND oder Wikidata für neue Namen, keine Ereignisse aus dem Fließtext.
- `<choice>` ist getestet, kommt im Evaluationskorpus aber nicht vor.
- Die URIs unter `example.org` sind Platzhalter; für eine Veröffentlichung eine eigene dauerhafte Basis-URI über `--base-uri` angeben.
- `prefixDef`-Muster werden als reguläre Ausdrücke von Python ausgewertet; nur vertrauenswürdige TEI verarbeiten. Nicht deklarierte Entitäten (etwa aus einer externen DTD) werden nicht geladen; solche Dateien werden mit einer Fehlermeldung abgelehnt.

## Quellen und Standards

- [TEI P5 Guidelines](https://www.tei-c.org/release/doc/tei-p5-doc/en/html/) – insbesondere [`correspAction`](https://www.tei-c.org/release/doc/tei-p5-doc/en/html/ref-correspAction.html), [Datumsattribute](https://www.tei-c.org/release/doc/tei-p5-doc/en/html/ref-att.datable.w3c.html), [`choice`](https://www.tei-c.org/release/doc/tei-p5-doc/en/html/ref-choice.html)
- [CIDOC CRM 7.1.3](https://cidoc-crm.org/html/cidoc_crm_v7.1.3.html) und die [RDF-Umsetzung von P82a/P82b](https://cidoc-crm.org/Issue/ID-288-issue-about-p82-and-p81-usage)
- [W3C Web Annotation Vocabulary](https://www.w3.org/TR/annotation-vocab/), [PROV-O](https://www.w3.org/TR/prov-o/)
- [CMIF-Dokumentation und Schema](https://github.com/TEI-Correspondence-SIG/CMIF) (TEI Correspondence SIG, für correspSearch)
- [Impresso HIPE-Modellkarte](https://huggingface.co/impresso-project/ner-hipe2020-hist-base), [HIPE-2020](https://impresso.github.io/CLEF-HIPE-2020/)

## Lizenz

MIT für den Code. Die Briefe in `eval/corpus/` stammen unverändert aus [schnitzler-briefe-data](https://github.com/arthur-schnitzler/schnitzler-briefe-data) und stehen unter CC BY 4.0 (Namensnennung siehe [eval/README.md](eval/README.md)). Das NER-Modell hat eine eigene Lizenz und wird nicht mitgeliefert.
