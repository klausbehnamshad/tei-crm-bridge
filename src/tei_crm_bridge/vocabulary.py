"""The project's small RDF vocabulary (prefix ``tcb:``), documented under docs/vocab/.

Everything that standard vocabularies (CIDOC CRM, W3C Web Annotation, PROV-O,
Dublin Core) already cover uses those; ``tcb:`` only names what they leave open.
"""

from __future__ import annotations

NAMESPACE = "https://klausbehnamshad.github.io/tei-crm-bridge/vocab/#"

#: (local name, kind, German label, English label, German definition)
TERMS: tuple[tuple[str, str, str, str, str], ...] = (
    ("Origin", "class", "Herkunft einer Nennung", "origin of a mention",
     "Klasse der zwei möglichen Herkünfte einer Nennung: redaktionell oder automatisch."),
    ("origin", "property", "Herkunft", "origin",
     "Verbindet eine oa:Annotation mit ihrer Herkunft (tcb:editorial oder tcb:automatic)."),
    ("editorial", "origin", "redaktionell", "editorial",
     "Die Nennung war bereits im TEI-Dokument ausgezeichnet. Nur solche Nennungen erzeugen crm:P67_refers_to."),
    ("automatic", "origin", "automatisch", "automatic",
     "Vorschlag der automatischen Erkennung. Ungeprüft; der Graph behauptet damit keine Bezugnahme des Dokuments."),
    ("Candidate", "class", "Kandidat", "candidate",
     "Entität, die eine automatische Erkennung vorschlägt. Sie ist bewusst keine Instanz einer CIDOC-CRM-Klasse; "
     "diese Aussage entsteht erst nach redaktioneller Bestätigung."),
    ("suggestedClass", "property", "vorgeschlagene Klasse", "suggested class",
     "CIDOC-CRM-Klasse, die das Erkennungsverfahren für einen Kandidaten vorschlägt (E21 Person, E53 Place, E74 Group)."),
    ("confidence", "property", "Modellscore", "model score",
     "Score des Erkennungsmodells (0–1) für eine automatische Nennung. Kein kalibriertes Maß für die Richtigkeit; Glossartreffer haben keinen."),
    ("unresolvedRef", "property", "nicht aufgelöste Referenz", "unresolved reference",
     "Wert aus @ref, der sich weder als URI, über prefixDef noch als xml:id im Dokument auflösen ließ. Wird unverändert erhalten."),
    ("sending", "type", "Versand", "sending",
     "crm:E55_Type für Ereignisse aus tei:correspAction[@type='sent']."),
    ("receiving", "type", "Empfang", "receiving",
     "crm:E55_Type für Ereignisse aus tei:correspAction[@type='received']."),
    ("engine", "property", "Erkennungsverfahren", "engine",
     "Verfahren eines Verarbeitungslaufs: glossary (deterministisch) oder hf (Transformers-Modell)."),
    ("model", "property", "Modell", "model", "Kennung des verwendeten Modells, z. B. ein Hugging-Face-Repository."),
    ("modelRevision", "property", "Modellrevision", "model revision", "Festgehaltener Commit der Modelldateien."),
    ("stride", "property", "Fensterüberlappung", "stride",
     "Überlappung der Modellfenster in Tokens; lange Absätze werden so vollständig gelesen."),
    ("aggregation", "property", "Aggregation", "aggregation",
     "Verfahren, mit dem Teilwort-Vorhersagen zu Namen zusammengefasst werden (first: wortgenau)."),
    ("glossary", "property", "Glossar", "glossary", "Dateiname des verwendeten Glossars."),
    ("glossarySha256", "property", "Glossar-Prüfsumme", "glossary checksum", "SHA-256 des Glossars."),
    ("threshold", "property", "Schwelle", "threshold", "Mindestscore für automatische Nennungen eines Modells."),
    ("reading", "property", "Lesart", "reading",
     "Welcher Zweig von tei:choice dem Erkennungsverfahren vorgelegt wurde: edited (corr/reg/expan) oder diplomatic (sic/orig/abbr)."),
    ("softwareVersion", "property", "Softwareversion", "software version", "Version von TEI CRM Bridge im Verarbeitungslauf."),
)
