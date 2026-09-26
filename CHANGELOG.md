# Changelog

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
