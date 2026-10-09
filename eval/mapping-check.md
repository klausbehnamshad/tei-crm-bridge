# Mapping-Prüfblatt — TEI → CRM (manuell, Release 0.4)

Stand: 2026-09-29. Modell-Software 0.4.0. Fälle 1–4, 6, 7 aus echten Läufen
mit leerem Glossar (gesichert unter `eval/work/mapping-check/runs/`); Fall 5
aus der im Arbeitsbaum erneuerten, getrackten Demo (Version 0.4.0, wird mit
dem Kandidaten-Commit committet) ohne neuen Lauf; Fall 8 aus Glossarlauf mit
gesichertem Reconcile-Cache (s. Befehle). Review-Spalten füllt Klaus; Spalte
„fachlich geprüft" bleibt bis dahin leer.

Jede Zeile: TEI-Stelle (Datei + Zeile im Korpus) → erwartete CRM-Abbildung →
tatsächliche Tripel aus dem Lauf → Befund. Direkt-Link Muster:
`https://schnitzler-briefe.acdh.oeaw.ac.at/<ID>.html`.

## Befehle (echte Läufe ohne Modell: Glossarmodus mit leerem Glossar, Projekt-.venv; Fall 5 aus im Arbeitsbaum erneuerter, getrackter Modell-Demo)

Leeres Glossar (Inhalt `{"PER": [], "LOC": [], "ORG": []}`, vgl. R2-README):

- `eval/work/sparql/empty-glossary.json` — `{"PER": [], "LOC": [], "ORG": []}`

Fallbriefe (Fälle 1–4, 6, 7), exakt ausgeführt:

- `.venv/bin/tei-crm eval/corpus/L03501.xml eval/corpus/L01351.xml --out-dir eval/work/mapping-check/runs --engine glossary --glossary eval/work/sparql/empty-glossary.json`

Fall 5 (kein neuer Lauf — im Arbeitsbaum erneuerte, getrackte Modell-Demo
(Version 0.4.0, wird mit dem Kandidaten-Commit committet):
`docs/schnitzler/L02051.ttl` und `docs/schnitzler/L02051.mentions.json`,
HF-Modell, Software 0.4.0):

Fall 8 (KEIN neuer Reconcile-Lauf gegen die PMB-API; Cache vom echten Lauf
mit Abrufdatum 2026-09-29 einmalig gesichert — 2 Einträge — pmb50, pmb29442 —
mit Timeout ohne Eintrag, s. Warnungen des Originallaufs):

- `cp /tmp/mc-rec-cache.json eval/work/mapping-check/reconcile-cache.json`
- `.venv/bin/tei-crm eval/corpus/L00001.xml --out-dir eval/work/mapping-check/runs --engine glossary --glossary eval/work/sparql/empty-glossary.json --reconciliation eval/work/mapping-check/reconcile-cache.json`

## Übersicht

| #   | Fall | Brief | TEI | CRM | Befund |
| --- | ---- | ----- | --- | --- | ------ |
| 1 | Person mit P67 | L03501 | `rs type=person ref=#pmb11851` | P67 + E21 | ok |
| 2 | Versand und Empfang | L03501 | 2× `correspAction` | 2× E7, P2, P14, P7 | ok |
| 3 | genaues Datum | L03501 | `date when` (sent) | E52, P82a/P82b | ok |
| 4 | Intervall | L03501 | `date notBefore/notAfter` (received) | E52, P82a/P82b; evidence nur in P3-Note | Klaus beurteilt |
| 5 | NER-Kandidat ohne P67 | L02051 (Modell-Demo) | Fließtext-`persName` ohne `#` | tcb:Candidate, kein P67 | ok |
| 6 | Ref ohne Registerauflösung | L01351 | `placeName ref=#pmb207274` | dokumentspezifische E53, mit P67 | Klaus beurteilt, schwierig |
| 7 | „Kinder" mit zwei Referenten | L03501 | `@ref` mit 2 URIs | P67 ×2 | ok, schwierig |
| 8 | seeAlso aus Reconcile-Lauf | L00001 | Register ohne idno + PMB-API | seeAlso ×3 | ok |

Pflichtfälle nach Auftrag: P67 (Fall 1), Versand/Empfang (Fall 2), genaues
Datum (Fall 3), Intervall (Fall 4), Kandidat (Fall 5). Implizite Verweise
(`@subtype="implied"`) deckt Fall 7 zusammen mit dem SPARQL-README ab.

## Fall 1 — Person mit P67 (Kainz, L03501)

- TEI: `eval/corpus/L03501.xml`, Fließtext-`rs type="person" ref="#pmb11851"`
  („Kainz", Link: `https://schnitzler-briefe.acdh.oeaw.ac.at/L03501.html`).
- CRM (erwartet): Dokument P67 → `#pmb11851`, `#pmb11851` a E21_Person.
- CRM (Lauf `eval/work/mapping-check/runs/L03501.ttl`, per rdflib gezählt):
  `#pmb11851` unter den 10 P67-Referenten; `#pmb11851 a crm:E21_Person`,
  Label „Josef Kainz".
- Element-XPath (erstes `Kainz`-Vorkommen, Z. 145):
  `/tei:TEI/tei:text[1]/tei:body[1]/tei:div[1]/tei:p[1]/tei:rs[2]`
- TEI, wörtlich aus `eval/corpus/L03501.xml`:
```xml
<rs type="person" ref="#pmb11851">Kainz</rs>
```
- Tripel, wörtlich aus `eval/work/mapping-check/runs/L03501.ttl`:
```turtle
<https://example.org/tei-crm-demo/mention/L03501/4> a oa:Annotation ;
    oa:hasBody <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb11851> ;
```
```turtle
    crm:P67_refers_to <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb11851>,
```
```turtle
<https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb11851> a crm:E21_Person ;
    rdfs:label "Josef Kainz" .
```
- Regel (`README.md`, Abschnitt „So arbeitet das Werkzeug", Schritt 4, Z. 86):
  „redaktioneller Name | `oa:Annotation` (`tcb:editorial`), Entität mit
  CIDOC-CRM-Klasse, `crm:P67_refers_to`"
- Befund: ok.

| fachlich geprüft (Klaus) | Datum | Anmerkung |
| ------------------------ | ----- | --------- |
|                          |       |           |

## Fall 2 — Versand und Empfang (L03501)

- TEI: `eval/corpus/L03501.xml`, Z. 113–123 (`correspDesc`, Link:
  `https://schnitzler-briefe.acdh.oeaw.ac.at/L03501.html`).
- CRM (erwartet): je `correspAction` eine E7_Activity mit P2-Typ
  (sending/receiving), P14 (handelnde Person), P7 (Ort).
- CRM (Lauf `eval/work/mapping-check/runs/L03501.ttl`):
  `event/L03501/sent-1 a crm:E7_Activity`, `P2 tcb:sending`,
  `P14 …#pmb2167` (Felix Salten), `P7 …#pmb53379` (Grado);
  `event/L03501/received-1 a crm:E7_Activity`, `P2 tcb:receiving`,
  `P14 …#pmb2121` (Arthur Schnitzler), `P7 …#pmb50` (Wien).
- Element-XPaths:
  `/tei:TEI/tei:teiHeader[1]/tei:profileDesc[1]/tei:correspDesc[1]/tei:correspAction[1]`
  (`sent`), `/tei:TEI/tei:teiHeader[1]/tei:profileDesc[1]/tei:correspDesc[1]/tei:correspAction[2]`
  (`received`)
- TEI, wörtlich aus `eval/corpus/L03501.xml` (Z. 113–123):
```xml
            <correspAction type="sent">
               <persName ref="#pmb2167">Salten, Felix</persName>
               <date when="1909-06-29" n="01">29. 6. 1909</date>
               <placeName ref="#pmb53379">Grado</placeName>
            </correspAction>
            <correspAction type="received">
               <persName ref="#pmb2121">Schnitzler, Arthur</persName>
               <date evidence="conjecture" notBefore="1909-06-30" notAfter="1909-07-04">[30. 6. 1909
                  – 4. 7. 1909?]</date>
               <placeName ref="#pmb50" evidence="conjecture">Wien</placeName>
            </correspAction>
```
- Tripel, wörtlich aus `eval/work/mapping-check/runs/L03501.ttl`:
```turtle
<https://example.org/tei-crm-demo/event/L03501/sent-1> a crm:E7_Activity ;
    rdfs:label "Versand: Felix Salten an Arthur Schnitzler, 29. 6. 1909" ;
    crm:P14_carried_out_by <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb2167> ;
    crm:P2_has_type tcb:sending ;
    crm:P4_has_time-span <https://example.org/tei-crm-demo/event/L03501/sent-1/time> ;
    crm:P7_took_place_at <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb53379> .
```
```turtle
<https://example.org/tei-crm-demo/event/L03501/received-1> a crm:E7_Activity ;
    rdfs:label "Empfang: Felix Salten an Arthur Schnitzler, 29. 6. 1909" ;
    crm:P14_carried_out_by <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb2121> ;
    crm:P2_has_type tcb:receiving ;
    crm:P4_has_time-span <https://example.org/tei-crm-demo/event/L03501/received-1/time> ;
    crm:P7_took_place_at <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb50> .
```
- Regel (`README.md`, Abschnitt „So arbeitet das Werkzeug", Schritt 4, Z. 90):
  „`correspAction[@type=sent\|received]` | je ein `crm:E7_Activity` mit
  `crm:P2_has_type tcb:sending\|tcb:receiving`, `P14_carried_out_by`,
  `P7_took_place_at`"
- Befund: ok — beide Aktionen mit Typ, Person und Ort vorhanden.

| fachlich geprüft (Klaus) | Datum | Anmerkung |
| ------------------------ | ----- | --------- |
|                          |       |           |

## Fall 3 — genaues Datum (L03501, sent)

- TEI: `eval/corpus/L03501.xml`, Z. 115:
  `<date when="1909-06-29" n="01">29. 6. 1909</date>` (im `sent`-Block).
- CRM (erwartet): E52_Time-Span mit P82a/P82b als Tagesgrenzen.
- CRM (Lauf `eval/work/mapping-check/runs/L03501.ttl`):
  `event/L03501/sent-1/time a crm:E52_Time-Span`, Label „29. 6. 1909",
  `P3_has_note "TEI when=\"1909-06-29\""`,
  `P82a_begin_of_the_begin "1909-06-29T00:00:00"^^xsd:dateTime`,
  `P82b_end_of_the_end "1909-06-29T23:59:59"^^xsd:dateTime`.
- Element-XPath:
  `/tei:TEI/tei:teiHeader[1]/tei:profileDesc[1]/tei:correspDesc[1]/tei:correspAction[1]/tei:date[1]`
- TEI, wörtlich aus `eval/corpus/L03501.xml` (Z. 115):
```xml
               <date when="1909-06-29" n="01">29. 6. 1909</date>
```
- Tripel, wörtlich aus `eval/work/mapping-check/runs/L03501.ttl`:
```turtle
<https://example.org/tei-crm-demo/event/L03501/sent-1/time> a crm:E52_Time-Span ;
    rdfs:label "29. 6. 1909" ;
    crm:P3_has_note "TEI when=\"1909-06-29\"" ;
    crm:P82a_begin_of_the_begin "1909-06-29T00:00:00"^^xsd:dateTime ;
    crm:P82b_end_of_the_end "1909-06-29T23:59:59"^^xsd:dateTime .
```
- Regel (`README.md`, Abschnitt „So arbeitet das Werkzeug", Schritt 4, Z. 91):
  „`date/@when` (Jahr, Monat, Tag, Uhrzeit), `@notBefore`/`@notAfter` |
  `crm:E52_Time-Span` mit `P82a_begin_of_the_begin`/`P82b_end_of_the_end`;
  keine erfundene Genauigkeit; mehrere Daten einer Handlung werden
  geschnitten, Widersprüche gemeldet"
- Befund: ok — `when` wird Tagesanfang bis Tagesende.

| fachlich geprüft (Klaus) | Datum | Anmerkung |
| ------------------------ | ----- | --------- |
|                          |       |           |

## Fall 4 — Intervall (L03501, received)

- TEI: `eval/corpus/L03501.xml`, Z. 120–121:
  `<date evidence="conjecture" notBefore="1909-06-30" notAfter="1909-07-04">`
  `[30. 6. 1909 – 4. 7. 1909?]</date>` (im `received`-Block).
- CRM (erwartet): E52_Time-Span mit P82a = notBefore, P82b = notAfter.
- CRM (Lauf `eval/work/mapping-check/runs/L03501.ttl`):
  `event/L03501/received-1/time a crm:E52_Time-Span`,
  Label „[30. 6. 1909 – 4. 7. 1909?]",
  `P3_has_note "TEI notBefore=\"1909-06-30\" notAfter=\"1909-07-04\"; evidence=conjecture"`,
  `P82a_begin_of_the_begin "1909-06-30T00:00:00"^^xsd:dateTime`,
  `P82b_end_of_the_end "1909-07-04T23:59:59"^^xsd:dateTime`.
- Element-XPath:
  `/tei:TEI/tei:teiHeader[1]/tei:profileDesc[1]/tei:correspDesc[1]/tei:correspAction[2]/tei:date[1]`
- TEI, wörtlich aus `eval/corpus/L03501.xml` (Z. 120–121):
```xml
               <date evidence="conjecture" notBefore="1909-06-30" notAfter="1909-07-04">[30. 6. 1909
                  – 4. 7. 1909?]</date>
```
- Tripel, wörtlich aus `eval/work/mapping-check/runs/L03501.ttl`:
```turtle
<https://example.org/tei-crm-demo/event/L03501/received-1/time> a crm:E52_Time-Span ;
    rdfs:label "[30. 6. 1909 – 4. 7. 1909?]" ;
    crm:P3_has_note "TEI notBefore=\"1909-06-30\" notAfter=\"1909-07-04\"; evidence=conjecture" ;
    crm:P82a_begin_of_the_begin "1909-06-30T00:00:00"^^xsd:dateTime ;
    crm:P82b_end_of_the_end "1909-07-04T23:59:59"^^xsd:dateTime .
```
- Regel (`README.md`, Abschnitt „So arbeitet das Werkzeug", Schritt 4, Z. 91):
  „`date/@when` (Jahr, Monat, Tag, Uhrzeit), `@notBefore`/`@notAfter` |
  `crm:E52_Time-Span` mit `P82a_begin_of_the_begin`/`P82b_end_of_the_end`;
  keine erfundene Genauigkeit; mehrere Daten einer Handlung werden
  geschnitten, Widersprüche gemeldet" — für die Ablage von
  `evidence="conjecture"` als P3-Freitext: keine Regel im README.
- Verlust/Erhalt: `evidence="conjecture"` bleibt **nicht** als eigene
  CRM-Eigenschaft erhalten — es steht nur als Text in der P3-Note (nicht
  maschinenlesbar). Das „?" der Datumsangabe bleibt nur im rdfs-Label
  („[…?]") erhalten. Ebenso geht `evidence="conjecture"` am
  `placeName` (Wien, Z. 122) verloren: `received-1 P7 …#pmb50` trägt keine
  Notiz. **Klaus beurteilt fachlich, ob das ausreicht.**
- Befund: Intervallgrenzen ok; conjecture-Status nur als Freitext — offen.

| fachlich geprüft (Klaus) | Datum | Anmerkung |
| ------------------------ | ----- | --------- |
|                          |       |           |

## Fall 5 — NER-Kandidat ohne P67 (Modell-Demo L02051, ohne neuen Lauf)

- TEI: `docs/schnitzler/L02051.*` (im Arbeitsbaum erneuerte, getrackte Demo
  (Version 0.4.0, wird mit dem Kandidaten-Commit committet)),
  Fließtext-`persName` „Georg Brandes" ohne `#` (Mention #14 in
  `L02051.mentions.json`: `kind: PER`, `origin: automatic`,
  `source: impresso-project/ner-hipe2020-hist-base`, `score: 0.9977`,
  XPath `/tei:TEI/tei:text[1]/tei:body[1]/tei:div[2]/tei:closer[1]/tei:signed[1]/tei:persName[1]`).
- CRM (erwartet): Kandidat ohne CRM-Klasse und ohne P67.
- CRM (`docs/schnitzler/L02051.ttl`, im Arbeitsbaum erneuerte, getrackte Demo
  (Version 0.4.0, wird mit dem Kandidaten-Commit committet)):
  `…/candidate/per/georg-brandes-17d9260253 a tcb:Candidate`,
  Label „Georg Brandes", `tcb:suggestedClass crm:E21_Person`;
  die Annotation trägt `tcb:confidence 0.9977` und
  `prov:wasGeneratedBy …/run/L02051/20322ffc80d6` mit
  `tcb:model "impresso-project/ner-hipe2020-hist-base"`,
  `tcb:modelRevision "afd1b509233560298ae39360ad3186253c5800d3"`,
  `tcb:engine "hf"`, `tcb:softwareVersion "0.4.0"`.
  Per rdflib: 7 `tcb:Candidate`, 0 davon mit P67-Tripel.
- Element-XPath der Fundstelle im Korpusbrief (`eval/corpus/L02051.xml`,
  Z. 175; dort steht der Name ohne Auszeichnung, das Modell ergänzt das
  `persName` in der angereicherten TEI):
  `/tei:TEI/tei:text[1]/tei:body[1]/tei:div[2]/tei:closer[1]/tei:signed[1]`
  (angereichert: `…/tei:signed[1]/tei:persName[1]`, `xml:id="tcb-n4"`)
- TEI, wörtlich aus `eval/corpus/L02051.xml`:
```xml
<closer>Ihr ergebenster <signed>Georg Brandes</signed></closer>
```
- Tripel, wörtlich aus `docs/schnitzler/L02051.ttl`:
```turtle
<https://klausbehnamshad.github.io/tei-crm-bridge/schnitzler/L02051.html#/document/L02051/candidate/per/georg-brandes-17d9260253> a tcb:Candidate ;
    rdfs:label "Georg Brandes" ;
    tcb:suggestedClass crm:E21_Person .
```
```turtle
<https://klausbehnamshad.github.io/tei-crm-bridge/schnitzler/L02051.html#/mention/L02051/14> a oa:Annotation ;
    oa:hasBody <https://klausbehnamshad.github.io/tei-crm-bridge/schnitzler/L02051.html#/document/L02051/candidate/per/georg-brandes-17d9260253> ;
```
```turtle
<https://klausbehnamshad.github.io/tei-crm-bridge/schnitzler/L02051.html#/run/L02051/20322ffc80d6> a prov:Activity ;
    prov:used <https://huggingface.co/impresso-project/ner-hipe2020-hist-base> ;
    prov:wasAssociatedWith <https://github.com/klausbehnamshad/tei-crm-bridge> ;
    tcb:aggregation "first" ;
    tcb:engine "hf" ;
    tcb:model "impresso-project/ner-hipe2020-hist-base" ;
    tcb:modelRevision "afd1b509233560298ae39360ad3186253c5800d3" ;
    tcb:reading "edited" ;
    tcb:softwareVersion "0.4.0" ;
    tcb:stride 128 ;
    tcb:threshold 0.85 .
```
- Regel (`README.md`, Abschnitt „So arbeitet das Werkzeug", Schritt 4, Z. 87):
  „automatischer Name | `oa:Annotation` (`tcb:automatic`) mit
  `prov:wasGeneratedBy` und Modellscore; Körper ist ein `tcb:Candidate` mit
  `tcb:suggestedClass` – **keine** CRM-Instanz, **kein** `P67`"
- Befund: ok.

| fachlich geprüft (Klaus) | Datum | Anmerkung |
| ------------------------ | ----- | --------- |
|                          |       |           |

## Fall 6 — Ref ohne Registerauflösung (L01351, schwierig)

- TEI: `eval/corpus/L01351.xml`, Z. 184
  (`<placeName ref="#pmb207274">Haus Bahr</placeName>` im
  `received`-correspAction) und Z. 210 (gleiches `@ref` im Body); Link:
  `https://schnitzler-briefe.acdh.oeaw.ac.at/L01351.html`.
- CRM (erwartet): P67 auf den Referenten; offene Frage, welche URI er bekommt.
- CRM (Lauf `eval/work/mapping-check/runs/L01351.ttl`, per rdflib gezählt):
  5 P67-Referenten, darunter die **dokumentspezifische**
  `…/document/L01351/entity/loc/ref-pmb207274-c72b844c0e a crm:E53_Place`,
  Label „Haus Bahr" — also **nicht** die editions-URI `#pmb207274`,
  aber **mit** P67 und als P7-Ort des received-Events.
- Zusätzlich hält die Annotation zum Body-Beleg (`oa:exact "Veitlissengasse"`)
  das Tripel `tcb:unresolvedRef "#pmb207274"` fest.
- Element-XPaths (`eval/corpus/L01351.xml`):
  `/tei:TEI/tei:teiHeader[1]/tei:profileDesc[1]/tei:correspDesc[1]/tei:correspAction[3]/tei:placeName[1]`
  (Z. 184, `received`-correspAction),
  `/tei:TEI/tei:text[1]/tei:body[1]/tei:div[1]/tei:address[1]/tei:addrLine[3]/tei:rs[1]`
  (Z. 210, Body)
- TEI, wörtlich aus `eval/corpus/L01351.xml`:
```xml
               <placeName ref="#pmb207274">Haus Bahr</placeName>
```
```xml
<rs ref="#pmb207274" type="place">Veitli<c rendition="#langesS">s</c><c rendition="#langesS">s</c>enga<c rendition="#langesS">s</c><c rendition="#langesS">s</c>e</rs>
```
- Tripel, wörtlich aus `eval/work/mapping-check/runs/L01351.ttl`:
```turtle
<https://example.org/tei-crm-demo/document/L01351/entity/loc/ref-pmb207274-c72b844c0e> a crm:E53_Place ;
    rdfs:label "Haus Bahr" .
```
```turtle
    crm:P67_refers_to <https://example.org/tei-crm-demo/document/L01351/entity/loc/ref-pmb207274-c72b844c0e>,
```
```turtle
    crm:P7_took_place_at <https://example.org/tei-crm-demo/document/L01351/entity/loc/ref-pmb207274-c72b844c0e> .
```
```turtle
    tcb:unresolvedRef "#pmb207274" .
```
- Regel (`README.md`, Abschnitt „So arbeitet das Werkzeug", Schritt 4, Z. 89):
  „`@ref` | URI direkt; `gnd:…` über `prefixDef`; `#id` zeigt auf das
  `xml:id` der TEI-Datei, relative Verweise nutzen `xml:base`; mehrere
  Registereinträge sind mehrere Entitäten; eigene `idno` des
  Registereintrags (GND, Wikidata, GeoNames) als `rdfs:seeAlso`;
  Unauflösbares bleibt als `tcb:unresolvedRef` erhalten" — das deckt das
  `tcb:unresolvedRef`-Tripel; für die dokumentspezifische Entity-URI
  (`…/entity/loc/ref-…`) selbst: keine Regel im README.
- Regel: Im Register von L01351 gibt es kein `xml:id="pmb207274"`
  (per grep über `eval/corpus/L01351.xml` geprüft: 0 Treffer). Dokumentiert
  ist nur, dass Unauflösbares als `tcb:unresolvedRef` erhalten bleibt
  (`README.md`, Z. 89); die brieflokale Entity-URI ist nicht im README
  beschrieben.
- Folge: keine Koreferenz mit `editions#pmb207274`, und in Q3
  (`q3_shared_persons.rq`, nur echte PMB-URIs) zählt diese Entität nicht.
- Befund: P67 vorhanden, aber Koreferenz-Frage: Die Entity ist brief-lokal
  statt register-identisch. **Klaus beurteilt fachlich, ob das korrekt ist.**
  Schwierig, weil dasselbe `@ref` zweimal vorkommt (Kopf + Body) und dennoch
  keine Register-URI entsteht.

| fachlich geprüft (Klaus) | Datum | Anmerkung |
| ------------------------ | ----- | --------- |
|                          |       |           |

## Fall 7 — „Kinder" mit zwei Referenten (L03501, schwierig)

- TEI: `eval/corpus/L03501.xml`, Z. 167:
  `<rs type="person" ref="#pmb2922 #pmb23915" subtype="implied">Kinder</rs>`
  (2 Referenten, implied; Link:
  `https://schnitzler-briefe.acdh.oeaw.ac.at/L03501.html`).
- CRM (erwartet): P67 je Referent (mengenwertig, inkl. implied).
- CRM (Lauf `eval/work/mapping-check/runs/L03501.ttl`, per rdflib gezählt):
  beide Referenten — `#pmb2922` (Paul Salten) und `#pmb23915`
  (Anna Katharina Rehmann) — unter den 10 P67-Referenten.
- Element-XPath (Z. 167):
  `/tei:TEI/tei:text[1]/tei:body[1]/tei:div[1]/tei:p[1]/tei:rs[11]`
- TEI, wörtlich aus `eval/corpus/L03501.xml`:
```xml
<rs type="person" ref="#pmb2922 #pmb23915" subtype="implied">Kinder</rs>
```
- Tripel, wörtlich aus `eval/work/mapping-check/runs/L03501.ttl`:
```turtle
<https://example.org/tei-crm-demo/mention/L03501/12> a oa:Annotation ;
    oa:hasBody <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb23915>,
        <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb2922> ;
```
```turtle
        <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb23915>,
```
```turtle
        <https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb2922>,
```
```turtle
<https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb23915> a crm:E21_Person ;
    rdfs:label "Anna Katharina Rehmann" .
```
```turtle
<https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb2922> a crm:E21_Person ;
    rdfs:label "Paul Salten" .
```
- Regel (`README.md`, Abschnitt „So arbeitet das Werkzeug", Schritt 4, Z. 89):
  „mehrere Registereinträge sind mehrere Entitäten"
- Befund: ok. Schwierig, weil Mehrfach-`@ref` und implied zusammenfallen.

| fachlich geprüft (Klaus) | Datum | Anmerkung |
| ------------------------ | ----- | --------- |
|                          |       |           |

## Fall 8 — seeAlso aus Reconcile-Lauf (L00001)

- TEI: `eval/corpus/L00001.xml` — der Registereintrag `#pmb146`
  („Frankfurt am Main") hat **keine** idno im Register; Normdaten stammen
  aus einem echten Reconcile-Lauf gegen die PMB-API (Abrufdatum 2026-09-29):
  `.venv/bin/tei-crm reconcile eval/corpus/L00001.xml --cache /tmp/mc-rec-cache.json`
  (Warnungen: pmb50 und pmb29442 mit Timeout, kein Eintrag gespeichert).
- Cache-Auszug (`eval/work/mapping-check/reconcile-cache.json`,
  `source: pmb-apis`, `retrieved: 2026-09-29`; bytegleich mit
  `/tmp/mc-rec-cache.json` vom Originallauf): pmb146 → GND
  `https://d-nb.info/gnd/4018118-2`,
  GeoNames `https://sws.geonames.org/2925533/`,
  Wikidata `http://www.wikidata.org/entity/Q1794`.
- CRM (Lauf `eval/work/mapping-check/runs/L00001.ttl`, 111 Tripel, mit genau
  diesem Cache): `#pmb146 a crm:E53_Place`, Label „Frankfurt am Main",
  `rdfs:seeAlso` → Wikidata Q1794, GND 4018118-2, GeoNames 2925533.
  (Daneben seeAlso aus demselben Lauf: pmb2121 → Q44331 + GND, pmb4986 →
  Q1400771 + GND.)
- Element-XPath des Registereintrags (`eval/corpus/L00001.xml`, Z. 221):
  `/tei:TEI/tei:text[1]/tei:back[1]/tei:listPlace[1]/tei:place[1]`
- TEI, wörtlich aus `eval/corpus/L00001.xml` (Z. 221–224):
```xml
            <place xml:id="pmb146">
               <placeName>Frankfurt am Main</placeName>
               <placeName type="ort_namensvariante">Frankfurt a. Main</placeName>
               <placeName type="ort_namensvariante">Frankfurt/Main</placeName>
```
- Tripel, wörtlich aus `eval/work/mapping-check/runs/L00001.ttl`:
```turtle
<https://id.acdh.oeaw.ac.at/schnitzler/schnitzler-briefe/editions#pmb146> a crm:E53_Place ;
    rdfs:label "Frankfurt am Main" ;
    rdfs:seeAlso <http://www.wikidata.org/entity/Q1794>,
        <https://d-nb.info/gnd/4018118-2>,
        <https://sws.geonames.org/2925533/> .
```
- Regel (`README.md`, Abschnitt „So arbeitet das Werkzeug", Schritt 4, Z. 89):
  „eigene `idno` des Registereintrags (GND, Wikidata, GeoNames) als
  `rdfs:seeAlso`"; dazu Abschnitt „CMIF-Export für correspSearch", Z. 145–146:
  „`cmif` (und `enrich`, dort als `rdfs:seeAlso`) konsumieren nur diese
  Datei: erst vorhandene Register-`idno`, dann Cache, dann direktes
  GND-`@ref`."
- Befund: ok — alle Normdaten aus dem dokumentierten API-Lauf, keine
  handgetragenen Werte.

| fachlich geprüft (Klaus) | Datum | Anmerkung |
| ------------------------ | ----- | --------- |
|                          |       |           |
