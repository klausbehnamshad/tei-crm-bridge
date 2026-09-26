# Evaluation `ablation-simple`

Korpus: 40 Briefe aus schnitzler-briefe-data @ `76870800b474`, 295 Referenzannotationen (ausgeschlossen: 40 implied, 0 nested).
Werkzeug: Version 0.2.0, Paketbaum `83c4a654604b`, Optionen `--engine hf --local-files-only --aggregation simple`.

Alle Textblöcke:

| Typ | Gold | Vorhergesagt | strikt P | strikt R | strikt F1 | Überlappung P | Überlappung R | Überlappung F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PER | 103 | 149 | 0.389 | 0.563 | 0.460 | 0.483 | 0.699 | 0.571 |
| LOC | 181 | 151 | 0.669 | 0.558 | 0.608 | 0.907 | 0.757 | 0.825 |
| ORG | 11 | 4 | 0.250 | 0.091 | 0.133 | 0.250 | 0.091 | 0.133 |
| gesamt | 295 | 304 | 0.526 | 0.542 | 0.534 | 0.691 | 0.712 | 0.701 |

Nur Text in `<p>` (der Umfang, den v0.1 las):

| Typ | Gold | Vorhergesagt | strikt P | strikt R | strikt F1 | Überlappung P | Überlappung R | Überlappung F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PER | 100 | 86 | 0.663 | 0.570 | 0.613 | 0.814 | 0.700 | 0.753 |
| LOC | 108 | 76 | 0.921 | 0.648 | 0.761 | 0.947 | 0.667 | 0.783 |
| ORG | 7 | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| gesamt | 215 | 163 | 0.779 | 0.591 | 0.672 | 0.871 | 0.660 | 0.751 |

Fehler: 79 nicht erkannt, 78 falscher Treffer, 59 Grenze abweichend, 7 Typ abweichend.
Nach Blocktyp: nicht erkannt: address 2, closer 1, opener 7, p 68, postscript 1; falscher Treffer: address 27, closer 29, opener 8, p 9, postscript 5; Grenze abweichend: address 25, opener 15, p 18, postscript 1; Typ abweichend: address 1, opener 1, p 4, postscript 1.
Struktur: 262 Treffer inline, 42 stand-off; neue Namen in `<note>`: 0, in `<del>`: 0, in anderer Referenz (Werk o. Ä.): 7, direkt in `<c>`/`<g>`: 0.

Stichprobe (Vorprüfung, 10 Briefe, 28 dort nicht annotierte Namen): von 62 Vorhersagen stimmen 23 exakt mit der Referenz überein; von den 39 übrigen sind 11 genau ein nicht annotierter Name und 8 überlappen einen.

## Fehlerbeispiele

| Kategorie | Brief | Vorhersage | Referenz | Kontext |
| --- | --- | --- | --- | --- |
| nicht erkannt | L00001 | – | ORG „Frankfurter Zeitung und Handelsblatt.“ | … [Frankfurter Zeitung und Handelsblatt.] Redaction. Frankfurt a. M., 2. Aug. 1889 Tel… |
| nicht erkannt | L02576 | – | PER „Rolland“ | …Ich schicke Ihnen zugleich den versprochenen [Rolland] ; Sie hätten ihn längst bekommen, aber ich wu… |
| nicht erkannt | L04526 | – | LOC „Enge“ | …Reichenau (N.-Ö.) mit der [Enge] .… |
| falscher Treffer | L00001 | PER „Dr FMamroth“ | – | …Ihr ergebener [Dr FMamroth] … |
| falscher Treffer | L02051 | PER „Arthur S.“ | – | …Glücklicherweise für [Arthur S.] halten wir noch immer dieselbe Distanz von… |
| falscher Treffer | L04526 | PER „Arthur“ | – | …Auf baldiges Wiedersehen! Ihr [Arthur] … |
| Grenze abweichend | L00026 | PER „Dr Hoffmann“ | PER „Hoffmann“ | …qui parfois se réveille wie Ste. Beuve sagt. [Dr Hoffmann] hat mir auf einen 4 Seiten langen Brief nach… |
| Grenze abweichend | L04526 | LOC „N.-Ö.“ | LOC „Reichenau (N.-Ö.)“ | …Reichenau ( [N.-Ö.] ) mit der Enge.… |
| Typ abweichend | L03151 | LOC „Specht“ | PER „Specht“ | …Lieber Freund, ich bin zum Souper bei [Specht] , wo Sie mich, falls es nötig wäre, anrufen k… |
| Typ abweichend | L04276 | ORG „Hotel“ | LOC „Hotel Passerhof“ | …Meran [Hotel] Passerhof 25/9… |
