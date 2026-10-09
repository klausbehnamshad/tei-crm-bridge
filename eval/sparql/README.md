# SPARQL über den eingefrorenen Graphen

Drei Abfragen über die Auszeichnung der Edition in 40 Originalbriefen, ohne
Modell. Der Graph wird nie committet, nur sein Hash in
[`manifest.json`](manifest.json) (SHA-256 über die verketteten
Brief-Turtle-Dateien in Buchstabenfolge).

```bash
python eval/sparql/build_graph.py --out-dir eval/work/sparql
```

Das Skript prüft jede Eingabe gegen `eval/manifest.tsv`, baut je Brief einen
Graphen nur aus der Edition (Glossarmodus mit leerem Glossar, Befehl aus R0)
und bricht ab, wenn der Hash vom Manifest abweicht. Abfragen und
Zwischendateien siehe unten; der Test `tests/test_sparql.py` baut den Graphen
frisch, prüft den Hash und vergleicht jede Antwort mit einem Weg direkt aus
der TEI: Q1 und Q3 bilden ihre Erwartung aus den Fundstellen des Werkzeugs
(find_blocks/project); ein gesonderter XPath-Vergleich prüft nur die Menge
(Brief, @ref-Token) und erkennt keine fehlende zweite Fundstelle mit
demselben Token.

## Regel: explizit und implizit

Alle drei Abfragen zählen **alle redaktionellen Namen einschließlich
impliziter Verweise** (`@subtype="implied"`, z. B. „er" mit `@ref` auf eine
Person). Der Graph verzeichnet sie wie explizite Namen (P67, Annotation mit
Belegstelle); ein `subtype`-Tripel gibt es nicht (`src/tei_crm_bridge/rdf.py`,
`add_mention`), und am Wortlaut sind sie nicht erkennbar. Deshalb kann keine
Abfrage über den eingefrorenen Graphen implizite Verweise ausschließen oder
markieren — das ginge nur mit einer Modelländerung (eigener Triple-Typ für die
Auszeichnungsart), die außerhalb dieses Releases liegt.

Abgrenzung zur Evaluation: Dort zählen 295 Referenzen, weil implizite
Verweise kein Eigenname und kein NER-Ziel sind (`eval/README.md`,
`eval/goldlib.py`). Hier stehen 335 Nennungen; je Brief gilt
Graph = Referenzen + implied (`tests/test_sparql.py` prüft das). Wer mit der
Evaluationszahl vergleicht, zieht je Brief die implied aus `manifest.tsv`
(`implied_excluded`) ab. Markieren lassen sich implizite Treffer nur über die
TEI: Der Element-XPath der Annotation zeigt auf das Ausgangselement, dessen
`@subtype` entscheidet.

Beispiel: In L03501 steht „Den Kindern ist hier bis jetzt … sehr wol" mit
`<rs type="person" ref="#pmb2922 #pmb23915" subtype="implied">Kinder</rs>`:
ein Verweis mit zwei Referenten (Paul Salten, Anna Katharina Rehmann), die im
Brief nirgends namentlich vorkommen. Q1 enthält beide URIs, Q2 belegt beide
an derselben Textstelle.

## Q1: Personen und Orte eines Briefs

Frage: Welche Personen und Orte nennt ein bestimmter Brief laut Edition?
Aufruf (`?doc` bindet den Brief, ungebunden alle Briefe):

```python
from rdflib import Graph, URIRef
union = Graph()
union.parse("eval/work/sparql/union.ttl", format="turtle")
brief = URIRef("https://example.org/tei-crm-demo/document/L03501")
query = open("eval/sparql/q1_persons_places.rq").read()
rows = list(union.query(query, initBindings={"doc": brief}))
```

Beispiel: Brief L03501 liefert 10 Zeilen, darunter Josef Kainz, Olga
Schnitzler und Margarethe Kainz als `E21_Person` sowie Lido als `E53_Place`.
Fachlich zeigt die Antwort, wen und was die Edition diesem Brief zuordnet:
Die Namen stammen aus der redaktionellen Auszeichnung, nicht aus einem
Modell. Dass darunter neben ausgeschriebenen Namen auch implizite Verweise
stehen können, gehört zur Regel oben, nicht zu einem Fehler der Abfrage.

## Zähleinheiten

Q1 und Q3 zählen eindeutige Paare aus **Brief-URI und aufgelöster
Entitäts-URI**. Mehrere Nennungen desselben Referenten in einem Brief zählen
einmal. Q3 gruppiert diese Paare nach derselben PMB-URI und zählt verschiedene
Brief-URIs. Für Q2 ist die Einheit **Brief, Entität und belegte Textspanne**
(Block-XPath plus Anfang/Ende): Eine Nennung mit mehreren Referenten in einem
`@ref` ergibt je Referent einen Beleg. Labels sind Anzeige, nicht Identität:
Zwei verschiedene Schreibweisen können dieselbe URI tragen, und
`correspDesc`-Personen erscheinen nur als `P14`/`P7` an Ereignissen, nie als
Q1/Q2-Nennung.

## Q2: Belegstelle zu einer Nennung

Frage: Welche Textstelle belegt, dass ein Brief eine bestimmte Person, einen
Ort oder eine Organisation nennt?
Aufruf (`?entity` bindet die Entität):

```python
from rdflib import Graph, URIRef
brief = Graph()
brief.parse("eval/work/sparql/letters/L03501.ttl", format="turtle")
kainz = URIRef("https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb11851")
query = open("eval/sparql/q2_evidence.rq").read()
rows = list(brief.query(query, initBindings={"entity": kainz}))
```

Auf dem Vereinigungsgraphen braucht diese Abfrage in rdflib Minuten; je
Briefdatei läuft dieselbe Datei in Millisekunden und liefert dieselben
Zeilen. Wer alle Briefe braucht, hängt die 40 Ergebnisse aneinander
(`tests/test_sparql.py` macht genau das). Die Gleichheit gilt unter zwei
Strukturbedingungen: Die Annotation-URIs sind je Brief verschieden
(`rdf.py` erzeugt sie briefbezogen), und Blank Nodes werden je Datei
getrennt geparst (`build_union` liest jede Turtle-Datei einzeln ein) —
sonst entstünden Kreuzkombinationen über Briefgrenzen. Ein Zwei-Brief-Test
mit gemeinsamer Entität vergleicht die Q2-Zeilen auf der Vereinigung und je
Brief als Multimenge (ohne Reihenfolge).

Beispiel: Für Josef Kainz in L03501 liefert die Abfrage unter anderem
`exact "Kainz"` im ersten Absatz (`div[1]/p[1]`, Stelle „…f vom 22. Das
letzte, was mir Kainz …"). Fachlich zeigt die Antwort den editionseigenen
Beleg: An welcher Stelle des Lesetexts steht die Nennung, und welcher
Ausschnitt sichert sie gegen Verwechslung. Geprüft wird an Position und
Stringwert, nicht an einem bloßen Wortvorkommen.

## Q3: Personen über mehrere Briefe

Frage: Welche Personen nennen mehrere Briefe, und welche Briefe sind es?
Aufruf ohne Parameter (12 Personen in 41 Zeilen):

```python
query = open("eval/sparql/q3_shared_persons.rq").read()
rows = list(union.query(query))
```

Beispiel: Hermann Bahr steht in L00201, L02676 und L04326. Fachlich zeigt die
Antwort gemeinsame Bezugspersonen über Briefgrenzen hinweg, zusammengeführt
über die identische PMB-URI der Edition. Dass drei Briefe dieselbe Person
nennen, ist eine Aussage der Auszeichnung, kein Netzwerkmaß.

## Grenzen

- Q1 liefert redaktionelle Verweise, keine Namensliste im engeren Sinn:
  40 der 335 Nennungen sind implizit (`@subtype="implied"`); die Evaluation
  schließt sie für die NER-Messung aus (`eval/goldlib.py`).
- Gezählt wird nur der Lesetext der `<body>`-Blöcke; Streichungen, nicht
  gelesene Lesarten und Register im `<back>` zählen nicht. Q1 zählt
  redaktionell ausgezeichnete Referenzen darin, auch implizite (Beispiel
  „Kinder" oben). Nicht dazu gehören: Namen in editorischen Anmerkungen
  (`<note>`), Namen in den Korrespondenzangaben (`correspDesc`, im Graphen
  als `P14`/`P7` an `E7_Activity`) und nicht ausgezeichnete Namen im
  Brieftext. Beispiel L03501: Wien, Arthur Schnitzler und Felix Salten stehen
  in der Anmerkung und in `correspDesc`, und „Ihr Salten" in der Unterschrift
  ist nicht ausgezeichnet. Auf der Editionsseite sind all diese Namen
  sichtbar.
- `@ref` wird an Leerraum in Tokens geteilt; eine lokale Register-ID plus
  externe URI ergibt `seeAlso`, keine zweite Entität; `#pmb…` folgt dem
  `xml:base` der Quelle.
- Zahlen hier gelten für 40 Briefe aus schnitzler-briefe-data
  (`76870800…`, Stand 29.09.2026), Software 0.5.0, Glossarmodus mit leerem
  Glossar. Keine Triple-Zahl belegt Qualität.

## Handabgleich

"Am 29.09.2026 von Klaus an der Online-Edition abgeglichen: In L03501 vier
der zehn Q1-Funde im Brief gefunden (Josef Kainz, Olga Schnitzler, Heinrich
Schnitzler, Lido); Q2-Belegstelle Kainz in L03501; Q2-Belegstelle Kopenhagen
in L02051 im ersten `<p>` des eigentlichen Briefs nach Adresse und Anrede."
Geprüft ist: die Menge (Brief, @ref-Token) je Brief per XPath — eine
fehlende zweite Fundstelle mit demselben Token erkennt das nicht;
Fundstellen über die Leseregel des Werkzeugs, wie in der Evaluation; bei Q2
zusätzlich Wortlaut, Position und die Entität an genau dieser Fundstelle
(umgebogene Bodies fliegen auf). Der
Handabgleich ist ein zweiter, stichprobenhafter Prüfweg. Nichts darüber
hinaus ist als geprüft zu bezeichnen.
