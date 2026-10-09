# Evaluation

Wie gut findet das Werkzeug Personen, Orte und Organisationen in echten Briefen – und was bedeutet eine Zahl gegenüber einer Edition mit eigenen Richtlinien?

## Korpus

- **Quelle:** [schnitzler-briefe-data](https://github.com/arthur-schnitzler/schnitzler-briefe-data), Commit `76870800b474b0ab829c65ef1ad84c3ba5f81c4e` (4.546 Briefe).
- **Edition:** Arthur Schnitzler: Briefwechsel mit Autorinnen und Autoren, hg. v. Martin Anton Müller und Gerd-Hermann Susen, Austrian Centre for Digital Humanities (ACDH-CH), Wien.
- **Lizenz:** Jeder Brief nennt in `publicationStmt/availability/licence` [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de); das Repository-Label (MIT) gilt für die Software. Die 40 Dateien liegen **unverändert** in [`corpus/`](corpus/); Titel, Handle, Quell-URL, Git-Blob-SHA und SHA-256 stehen in [`manifest.tsv`](manifest.tsv). Bei neun Briefen ist der Handle in der Quelle nur `XXXX`; dort ist die gepinnte Quell-URL der konkrete Beleg. Die Demo-TEI auf der Projektseite ist dagegen maschinell bearbeitet (ergänzte Namen, Verarbeitungsvermerk, absolute Schemaverweise).
- **Auswahl** ([`select_corpus.py`](select_corpus.py), ohne Handauswahl): jeder 25. Brief in Dateinamenfolge (182), davon die mit mindestens einer Personen-, Orts- oder Organisationsreferenz und mindestens 150 Zeichen Lesetext (158); je zehn Briefe in gleichmäßigen Abständen aus vier Längenquartilen. Jede Datei wird gegen die Blob-SHA des festgehaltenen Commits geprüft. `<c>`, `<note>`, `<del>`/`<add>`, Adressen, Datumsintervalle und verschiedene `correspAction`-Typen kommen vor; `<choice>` wird in dieser Edition nicht verwendet und ist nur in den Tests abgedeckt.

```bash
python eval/select_corpus.py --commit 76870800b474b0ab829c65ef1ad84c3ba5f81c4e
```

Die Auswahl schließt Briefe ohne ausgezeichnete Namen aus; über sie sagt die Messung nichts.

## Referenz und Messregeln

Festgelegt vor der ersten Messung ([`goldlib.py`](goldlib.py), [`evaluate.py`](evaluate.py)):

- **Lesetext** wie im Werkzeug ([`projection.py`](../src/tei_crm_bridge/projection.py)): Kommentare und Streichungen zählen nicht, `<c>` bleibt im Wort.
- **Referenz:** redaktionelle `persName`/`placeName`/`orgName` (und Ortsteile wie `settlement`) sowie `rs`/`name` mit `@type` person, place oder org im Lesetext. Ausgeschlossen werden `@subtype="implied"` (implizite Verweise wie „er“ – kein Eigenname, 40 Fälle) und in einer anderen Referenz geschachtelte Namen (im Korpus 0 Fälle). Spannen werden an beiden Enden um Leerraum gekürzt.
- **Eingabe:** eine Kopie jedes Briefs ohne diese Referenzen im `<body>`; alles andere, auch Werkverweise `rs[@type='work']`, bleibt.
- **Vorhersagen:** neue `persName`/`placeName`/`orgName` in der Ausgabe plus Stand-off-Treffer aus der Mentions-Datei.
- **Strikt:** gleicher Brief, Block, Anfang, Ende, Typ. **Überlappend:** gleicher Typ, mindestens ein gemeinsames Zeichen, eins zu eins, größte Überlappung zuerst.
- **Umfang von v0.1:** v0.1 las `body//p`; für den fairen Vergleich zählen dort nur Spannen, deren Zeichen in einem `<p>` liegen (auch in `postscript`).
- **Fehlerklassen:** nicht erkannt, falscher Treffer (keine Überlappung), Grenze abweichend (Überlappung, gleicher Typ), Typ abweichend. Zehn Beispiele werden deterministisch über die Klassen verteilt gezogen.
- Werte werden ungerundet gespeichert und nur für die Anzeige einmal gerundet.

## Läufe

| Lauf | Werkzeug | Zweck |
| --- | --- | --- |
| `v0.1-hf` | Commit `e09fa38` | Ausgangsstand vor allen Änderungen |
| `v0.2-hf` | Version 0.2.0, Paketbaum im Ergebnis-JSON (noch ohne Commit) | Ergebnis |
| `ablation-simple` | wie `v0.2-hf`, `--aggregation simple` | Begründung der Aggregation |
| `v0.1-hf-original`, `v0.2-hf-original` | beide | Integrität auf den **unveränderten** Briefen |

Alle mit `impresso-project/ner-hipe2020-hist-base` @ `afd1b50`, Schwelle 0,85, auf der CPU. Acht zentrale Pakete sind in [`requirements.txt`](requirements.txt) auf die gemessenen Versionen festgelegt; darüber hinaus war die Kette für die v0.2-Läufe nicht gesperrt. Die Ergebnisse protokollieren Python und fünf Bibliotheken. Ergebnisse in [`results/`](results/): je Lauf eine Markdown-Übersicht und ein JSON mit allen Fehlern, dazu [`compare_v0.1-hf_v0.2-hf.md`](results/compare_v0.1-hf_v0.2-hf.md) und `integrity_*.json`. `score` und `integrity` enden mit Status 1, wenn sie ein Problem finden.

Für v0.2 ist bisher nur der Git-Baum-Hash von `src/tei_crm_bridge` gespeichert. Der signierte Commit, der den vollständigen Quellstand einschließlich Evaluation identifiziert, steht noch aus.

```bash
pip install -e . -r eval/requirements.txt
git worktree add ../tcb-v0.1 e09fa38
sh eval/reproduce.sh
```

Ein Wiederholungslauf aus demselben exportierten v0.2-Schnappschuss ergab identische Kennzahlen und byte-gleiche Ausgabedateien. Nach dem signierten Commit sollte die Messung aus einem sauberen Checkout erneut laufen.

## Messumgebung sperren

`torch` ist plattformabhängig: je nach Betriebssystem, Architektur und CPU-/CUDA-Build gehören andere Pakete und Binärkomponenten dazu. [`requirements.txt`](requirements.txt) legt nur die acht direkten Pakete fest; die darüber hinaus installierten Distributionsversionen hält [`requirements.lock`](requirements.lock) fest. Erzeugt wird sie mit `sh eval/make_lock.sh` (frische venv mit Python 3.13, `pip install -e . -r eval/requirements.txt`, danach `pip freeze --exclude-editable`); der Dateikopf nennt Python-Version, Betriebssystem, Architektur, Datum und Befehl.

Geltungsbereich: Das Lockfile belegt Anaconda Python 3.13.9 auf macOS arm64; das lokale Paket ist absichtlich ausgenommen (`pip freeze --exclude-editable`) und wird aus dem festgelegten Commit mit `pip install -e . --no-deps` dazu installiert. Es ist kein plattformübergreifendes Versprechen: Ein anderes Python 3.13, ein anderes Betriebssystem oder ein anderer Paketindex kann andere Binärpakete ergeben.

Die Neumessung für 0.4.0 soll in genau dieser gesperrten Umgebung aus einem sauberen Checkout laufen; die tatsächlich verwendete venv, Plattform und der Kandidaten-Commit werden nach dem Lauf benannt (R4).

## Befunde

Die Zahlen stehen in [`results/v0.1-hf.md`](results/v0.1-hf.md), [`results/v0.2-hf.md`](results/v0.2-hf.md) und auf der [Projektseite](https://klausbehnamshad.github.io/tei-crm-bridge/).

1. **Kontext wirkt.** Im Text, den v0.1 las (`<p>`), steigen strikte Präzision und F1, und die falschen Treffer in Absätzen sinken deutlich. Ursache war die Erkennung pro Textknoten: „Schwe`<c>`s`</c>`tern“ wurde in v0.1 zum Ort „Schwe“, „Ver`<c>`s`</c>`en“ zum Ort „Ver“; beides kommt in v0.2 nicht mehr vor.
2. **Mehr Text wird gelesen.** Adressen, Briefköpfe und Grußformeln verarbeitet erst v0.2; dort lagen die meisten Orte, die v0.1 übersah. Über alle Blöcke steigt der Recall deutlich.
3. **Die strikte Präzision über alle Blöcke sinkt.** Die meisten falschen Treffer von v0.2 liegen in Adressen, Grußformeln und Unterschriften – Text, den v0.1 nicht las. Ob es sich um Fehler oder um nicht annotierte Namen handelt, zeigt nur die Stichprobe (unten), und nur für zehn Briefe.
4. **Struktur bleibt intakt.** Auf den Originalbriefen setzte v0.1 307 seiner 336 neuen Namen an eine unzulässige Stelle: 274 in bereits ausgezeichnete Namen der Edition, 150 in Kommentare, davon 117 in beides. v0.2 setzt keinen. Der Lesetext bleibt gleich; nach Entfernen der Ergänzungen ist die ursprüngliche Textauszeichnung in allen 40 Briefen wiederherstellbar.
5. **Grenzen:** Das Modell zählt Titel und Funktionen zum Namen („Dr Hochsinger“, „Marcell Salzer, der herrliche Vorleser“), wie es die [Impresso-Annotationsrichtlinien v2.2.0](https://doi.org/10.5281/zenodo.3604227) vorsehen, und trennt Adressen in Einzelorte; die Edition zeichnet nur den Namen und die ganze Adresse aus. Deshalb stehen strikte und überlappende Werte nebeneinander.
6. **Aggregation:** `simple` und `first` liegen in F1 gleichauf; `simple` erzeugt aber Treffer, die mitten im Wort enden („Sternwartestra“), `first` keine. Für TEI-Markup ist nur Letzteres brauchbar.

## Stichprobe: nicht annotierte Namen

Zehn Briefe (jeder vierte des Manifests) wurden auf Personen-, Orts- und Organisationsnamen geprüft, die die Edition nicht auszeichnet. **Methode:** zwei unabhängige, KI-gestützte Lesedurchgänge je Brief mit denselben Regeln; übereinstimmende Funde gelten als bestätigt, abweichende entschied ein dritter Durchgang (1 Fall). **Status:** Der Autor hat die Stichprobe am 26. September 2026 gesichtet und ihre Plausibilität bestätigt. Dies bleibt eine KI-gestützte Stichprobe, keine unabhängige Blindannotation.

[`spotcheck.tsv`](spotcheck.tsv) nennt jeden Namen mit Brief, Block, Wortlaut und Vorkommen; `evaluate.py` sucht ihn bei jeder Messung im aktuellen Lesetext und bricht ab, wenn er fehlt. Ergebnis: 28 Namen, 25 Personen und 3 Orte, fast ausschließlich in Unterschriften („HermannBahr“, „A.“), Anreden („Lieber Arthur“), Adressen und Briefköpfen – die Edition verzeichnet Absender und Empfänger in `correspDesc`, nicht im Text.

Berichtet werden nur Zählungen: wie viele der nicht exakt passenden Vorhersagen in diesen zehn Briefen genau einem solchen Namen entsprechen und wie viele einen überlappen (`results/v0.2-hf.md`). Eine „bereinigte Präzision“ wird nicht gebildet, und die Hauptzahlen bleiben unbereinigt.

## Integritätsprüfung

`evaluate.py integrity` prüft einen Lauf auf den unveränderten Briefen: neue Namen in bestehenden Personen-, Orts- oder Organisationsreferenzen, in `<note>`, `<del>` oder direkt in `<c>`/`<g>` (Überschneidungen werden getrennt gezählt); gleicher Lesetext; und ob das Entfernen der neuen Elemente und des `application`-Eintrags exakt das Original ergibt (C14N 2.0; die C14N-1.0-Implementierung von libxml2 2.14 serialisiert Namensräume unter `xml:base` fehlerhaft). Dieselbe Prüfung läuft in der CI für den veröffentlichten Demo-Brief.

## Grenzen der Evaluation

- Eine Edition, ein Modell, 40 Briefe; Organisationen nur elfmal – keine Aussage über ORG.
- Briefe ohne ausgezeichnete Namen sind nicht im Korpus; eine menschlich annotierte Blindstichprobe solcher Briefe steht aus.
- Acht automatische Namen liegen innerhalb von Werkreferenzen (`rs[@type="work"]`): fünf entsprechen für die Messung entfernten redaktionellen Namen, drei sind ungeprüfte Vorschläge in Werktiteln („Rondoli“, „Phryne“, „Casanova“). Die Integritätszahl für vorhandene Personen-, Orts- und Organisationsreferenzen erfasst Werkreferenzen nicht.
- Die Stichprobe ist eine KI-gestützte, vom Autor gesichtete Vorprüfung (siehe oben).
- Kein Block des Korpus braucht mehr als ein Modellfenster; lange Texte sind nur durch die Modelltests abgedeckt.
- Das Modell steht unter CC BY-NC-SA 4.0; die Messung ist nicht-kommerziell.
