# Projektplan

## Ziel

Ein kleines öffentliches Demonstrationsprojekt, das wissenschaftlich saubere Modellierung und praktisch ausführbare Software für historische TEI-Texte zeigt.

## Phase 1: MVP (in diesem Repository)

- TEI P5 sicher parsen und gemischten Inhalt erhalten.
- Bestehende und neue Personen-, Orts- und Organisationsnamen erfassen.
- Optionales historisches deutsches NER als austauschbaren Adapter bereitstellen.
- CIDOC CRM Turtle mit Dokument-, Entitäts- und expliziten Versandereignissen ausgeben.
- Reproduzierbares fiktives Beispiel, Tests und klare Grenzen dokumentieren.

## Phase 2: Forschungsqualität

- Quellenkorpus und Goldstandard auswählen; Precision/Recall/F1 pro Entitätstyp messen.
- Modellvergleich, OCR-Fehleranalyse und Schwellenwertkalibrierung durchführen.
- Korrekturworkflow, Herkunft jeder Aussage und versionierte Modellparameter ergänzen.
- TEI-ODD/Schematron sowie RDF/SHACL für das konkrete Mappingprofil einsetzen.

## Phase 3: Portfolio-Demo

- Kleine Browseransicht mit synchronisiertem TEI-Text und Graph.
- Vorher/Nachher-Beispiele, bekannte Fehler und methodische Entscheidungen zeigen.
- Dauerhafte URIs, Release-Tag und Screenshots für die GitHub-Präsentation.
