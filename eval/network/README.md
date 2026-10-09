# Korrespondenz- und Nennungsnetz

Zwei Netze aus der Edition (40 Originalbriefe) und ihren Briefgraphen.
Aufruf mit beiden Netzen:

```bash
tei-crm network eval/corpus/L*.xml --out-dir eval/work/network \
  --graphs eval/work/sparql/letters/*.ttl
```

Ohne `--graphs` entsteht nur das Korrespondenznetz. Ausgabe je Lauf:
`correspondence.graphml`, `correspondence_edges.csv`, mit `--graphs`
zusätzlich `mentions.graphml`, `mentions_edges.csv`, immer `metrics.json`
mit Methode, Version, Korpus (Dateinamen + SHA-256), Datum und Hinweis.
Kanten sind nach (Quelle, Ziel) sortiert, zwei Läufe byte-gleich.

## Beispielzahlen (40 Briefe)

| Netz | Knoten | Kanten | Komponenten |
| Korrespondenz | 26 | 37 | 1 |
| Nennungen | 80 | 237 | 9 |

Datenstand: `eval/corpus` (Stand aus `eval/manifest.tsv`), Briefgraphen
aus `eval/sparql/manifest.json`, Lauf vom 09.10.2026 mit Version 0.5.0.
Alle 40 Briefe tragen `sent` und `received`; Mehrfachkanten sind mit
`weight` und Brief-Liste vereint, Datumsangaben stehen parallel dazu.
Das Nennungsnetz verbindet alle P67-Personen mit PMB-URI (Q1-Menge);
die aus Q3 folgenden Paare sind darin enthalten.

## Was die Zahlen zeigen, was nicht

Das Korrespondenznetz zeigt, wer laut Edition an wen schreibt
(Schnitzler, Arthur versendet am häufigsten). Das Nennungsnetz zeigt,
welche Personen die Edition gemeinsam in denselben Briefen nennt.
Beides beschreibt nur die Auszeichnung im gegebenen Korpus und belegt
keine Bedeutung einer Person: „Kennzahlen beschreiben die Auszeichnung
der Edition im gegebenen Korpus.“
