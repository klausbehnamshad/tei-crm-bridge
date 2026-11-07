# Korrespondenz- und Nennungsnetz

Zwei Netze aus der Edition (40 Originalbriefe) und ihren Briefgraphen.
Aufruf mit beiden Netzen:

```bash
tei-crm network eval/corpus/L*.xml --out-dir eval/work/network \
  --graphs eval/work/sparql/letters/*.ttl
```

Ohne `--graphs` entsteht nur das Korrespondenznetz. Ausgabe je Lauf:
`correspondence.graphml`, `correspondence_edges.csv`, mit `--graphs`
zusätzlich `mentions.graphml`, `mentions_edges.csv`,
`mentions_bipartite.graphml`, `mentions_bipartite_edges.csv`, immer `metrics.json`
mit Methode, Version, Korpus (Dateinamen + SHA-256), Datum und Hinweis.
Kanten sind nach (Quelle, Ziel) sortiert; bei gleichen Eingaben, Paketversionen
und gleichem Laufdatum sind die Dateien byte-gleich. Das Datum in `metrics.json`
ändert sich über Tagesgrenzen.

## Beispielzahlen (40 Briefe)

| Netz | Knoten | Kanten | Komponenten |
| --- | --- | --- | --- |
| Korrespondenz | 26 | 37 | 1 |
| Personenprojektion | 80 | 237 | 9 |
| Bipartit Brief → Entität | 225 | 273 | 2 |

Datenstand: `eval/corpus` (Stand aus `eval/manifest.tsv`), Briefgraphen
aus `eval/sparql/manifest.json`, eigener Lauf vom 10.10.2026 mit Version 0.5.0
und networkx 3.4.2; Graph-Hash `ce66bf1562f0ab7d6764e1adc74b5b44f0f713280e74ce5e15073f73541f953a`.
Alle 40 Briefe tragen `sent` und `received`; Mehrfachkanten sind mit
`weight` und Brief-Liste vereint, Datumsangaben stehen parallel dazu.
Das bipartite Netz umfasst 40 Dokumente und 185 externe E21/E53/E74-Entitäten.
Die Personenprojektion verbindet alle externen P67-Personen mit E21-Klasse;
die aus Q3 folgenden 25 Paare sind darin enthalten. Q3 beschränkt sich auf
mehrfach genannte PMB-Personen und ist keine Definition der ganzen Projektion.

`weight` zählt unterschiedliche vollständige Brief-URIs, auch bei gleichen
kurzen IDs in verschiedenen Editionen. Die Spalten `letters` und `letter_uris`
halten kurze IDs bzw. vollständige Identitäten parallel. Korrespondenz-CSV und
GraphML enthalten `date_source` parallel zu Brief-IDs und Grenzen: `sent`,
ersatzweise `received`, sonst `none`; `date_fallbacks` nennt den Rückgriff auf
Empfangsdaten. Ungültige Werte, widersprüchliche Datumsangaben und gemischte
Zeitzonen werden in `correspondence.date_errors` in `metrics.json` gesammelt:
Datei, Brief-ID, Handlung (`sent`/`received`) und Meldung. Betroffene Briefe
behalten ihre Kanten mit leeren Datumsgrenzen und `date_source none`;
der Lauf verarbeitet die übrigen Briefe weiter. Die CLI-Ausgabe enthält
dieselbe Fehlerliste als `date_errors`. GND wird je Registerperson und je
`@ref`-Token aufgelöst.

Kennzahlen verwenden ungewichteten Gesamtgrad (gerichtet: Eingang plus Ausgang),
normalisierte ungewichtete Betweenness und bei gerichteten Graphen schwache
Komponenten. Kanten-`weight` zählt gemeinsame Briefe. Die Zentralitätsberechnung
verwendet ungewichtete Kanten.

## Was die Zahlen zeigen, was nicht

Das Korrespondenznetz zeigt, wer laut Edition an wen schreibt
(Schnitzler, Arthur versendet am häufigsten). Das Nennungsnetz zeigt,
welche Personen die Edition gemeinsam in denselben Briefen nennt.
Beides beschreibt nur die Auszeichnung im gegebenen Korpus und belegt
keine Bedeutung einer Person: „Kennzahlen beschreiben die Auszeichnung
der Edition im gegebenen Korpus.“
