# TEI CRM Bridge

Ein kleiner, nachvollziehbarer Prototyp für Digital Humanities: TEI P5 einlesen, vorhandene Markierungen erhalten, Personennamen, Ortsnamen und Organisationen ergänzen und einen CIDOC-CRM-Graphen als Turtle exportieren.

**Status:** MVP für ein Bewerbungsportfolio, kein fertiges Editionssystem. Die Beispieldaten sind fiktiv. Automatisch erkannte Namen und gleichlautende Namen sind keine geprüften Identitäten. Der Graph behauptet keine historischen Ereignisse aus bloßen NER-Treffern.

## Schnellstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
tei-crm examples/letter.xml --glossary examples/glossary.json
```

Das erzeugt `build/letter.enriched.xml`, `build/letter.ttl` und eine im Browser öffnende `build/letter.html`. Der Glossar-Modus ist deterministisch und dient dem schnellen, vollständig lokalen Durchlauf; er ist **keine KI**.

Die versionierte [Browser-Demo](docs/letter.html) verwendet bewusst den Glossar-Modus, damit der Screenshot und die Ausgabe ohne großen Modelldownload reproduzierbar sind. Ein echter KI-Lauf kann abweichen; auf diesem Beispieldokument markierte das getestete Impresso-Modell drei neue Nennungen und ließ „Jena“ innerhalb von `<hi>` aus.

Für echtes historisches deutsches NER:

```bash
pip install -e '.[ner]'
tei-crm examples/letter.xml --engine hf --base-uri https://example.org/mein-projekt/
```

Der `hf`-Modus lädt bei der ersten Ausführung [`impresso-project/ner-hipe2020-hist-base`](https://huggingface.co/impresso-project/ner-hipe2020-hist-base) von Hugging Face. Der Modell-Commit ist im Code fixiert; für eigene lokale Modelle kann `--model /pfad/zum/modellordner` genutzt werden. `--local-files-only` verlangt bereits vorhandene Modelldateien. Für vertrauliche Texte ist zu prüfen, ob alle Abhängigkeiten und Modelldateien schon lokal vorliegen. Die Textinferenz läuft lokal; eine pauschale Aussage „100 % offline/GDPR-konform“ wäre ohne Prüfung der gesamten Betriebsumgebung nicht seriös. Das Impresso-Modell steht unter CC BY-NC-SA 4.0 und wird nicht mit dem MIT-lizenzierten Code verteilt.

## Warum dieses Mapping?

| TEI/Quelle | RDF-Aussage |
| --- | --- |
| TEI-Dokument | `E31_Document` |
| `persName` / `placeName` / `orgName` | `E21_Person` / `E53_Place` / `E74_Group` |
| Nennung im Dokument | `P67_refers_to` plus eigene `oa:Annotation` für Herkunft, TEI-XPath und Konfidenz |
| `correspAction type="sent"` | `E7_Activity` mit `P14_carried_out_by`, `P7_took_place_at`, `P4_has_time-span` und `P70_documents` |

Ein Name im Fließtext belegt nur eine Nennung, keine Teilnahme an einem Ereignis. Deshalb entsteht ein Versandereignis ausschließlich aus der expliziten TEI-Korrespondenzmetadaten-Struktur. Datum, Akteur und Ort werden nur gesetzt, wenn sie dort angegeben sind. `@ref` an bereits vorhandenen TEI-Namen bleibt erhalten; neue Namen erhalten eine dokumentlokale URI. Gleiche Oberflächenformen werden derzeit innerhalb eines Dokuments zusammengeführt und müssen für echte Forschungsdaten später durch Authority Linking und manuelle Prüfung disambiguiert werden.

## Grenzen des MVP

- Erkennung geschieht pro Textknoten eines `<p>` im `<body>`. Namen, die über mehrere Inline-Elemente reichen, werden nicht erkannt; die Inline-Struktur bleibt dadurch erhalten.
- Keine automatische Ereignisextraktion, Koreferenzauflösung, GND/Wikidata-Verlinkung oder Vollvalidierung gegen ein TEI-ODD.
- Der Hugging-Face-Adapter ist optional. Modellqualität auf konkretem Quellenmaterial muss mit annotierten Beispielen geprüft werden; ein hoher Modellscore ist kein wissenschaftlicher Beleg.
- Die URIs unter `example.org` sind Platzhalter. Für Veröffentlichung eine eigene dauerhafte HTTPS-Basis-URI über `--base-uri` angeben.

## Tests

```bash
pip install -e '.[test]'
pytest -q
```

## Nächste Ausbaustufe

1. 20–50 echte Beispielseiten mit Goldstandard-Annotationen und Fehleranalyse.
2. Vergleich mit dem [SBB NER-Modell](https://huggingface.co/SBB/sbb_ner), den [dbmdz-Flair-Modellen](https://github.com/dbmdz/historic-ner) und [impresso Stacked BERT](https://huggingface.co/impresso-project/ner-stacked-bert-multilingual) auf genau diesen Quellen. Das ältere dbmdz-Flair-Checkpoint ließ sich mit Flair 0.15.1 nicht laden; Impresso Stacked BERT benötigt **Custom Code**. Das hier verwendete Impresso HIPE-Modell nutzt Standard-Transformers und Safetensors.
3. Review-Oberfläche für Korrekturen und versionierte Provenienz; danach GND/Wikidata-Kandidaten mit manueller Bestätigung.
4. TEI-ODD/Schematron-Validierung und dokumentierte CRM-Mappingprofile für zusätzliche Ereignistypen.

## Quellen und Standards

- [TEI P5 Namensraum und Elementreferenz](https://www.tei-c.org/release/doc/tei-p5-doc/en/html/REF-ELEMENTS.html)
- [CIDOC CRM 7.1.3](https://cidoc-crm.org/html/cidoc_crm_v7.1.3.html)
- [dbmdz historic-ner](https://github.com/dbmdz/historic-ner)
- [Impresso HIPE-Modellkarte](https://huggingface.co/impresso-project/ner-hipe2020-hist-base)

## Lizenz

MIT für den Code dieses Repositories. Die externen Modelle und Datensätze haben eigene Lizenzen und werden hier nicht mitgeliefert.
