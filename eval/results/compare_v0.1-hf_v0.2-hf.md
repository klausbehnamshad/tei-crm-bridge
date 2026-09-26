# Vergleich `v0.1-hf` → `v0.2-hf`

| Maß | Typ | vorher | nachher | Differenz |
| --- | --- | ---: | ---: | ---: |
| strict precision | PER | 0.583 | 0.392 | -0.191 |
| strict recall | PER | 0.583 | 0.563 | -0.020 |
| strict f1 | PER | 0.583 | 0.462 | -0.121 |
| strict precision | LOC | 0.870 | 0.669 | -0.201 |
| strict recall | LOC | 0.331 | 0.558 | +0.227 |
| strict f1 | LOC | 0.480 | 0.608 | +0.128 |
| strict precision | ORG | 0.250 | 0.250 | +0.000 |
| strict recall | ORG | 0.091 | 0.091 | +0.000 |
| strict f1 | ORG | 0.133 | 0.133 | +0.000 |
| strict precision | all | 0.688 | 0.528 | -0.160 |
| strict recall | all | 0.410 | 0.542 | +0.132 |
| strict f1 | all | 0.514 | 0.535 | +0.021 |
| overlap precision | PER | 0.718 | 0.486 | -0.232 |
| overlap recall | PER | 0.718 | 0.699 | -0.019 |
| overlap f1 | PER | 0.718 | 0.574 | -0.144 |
| overlap precision | LOC | 0.913 | 0.907 | -0.006 |
| overlap recall | LOC | 0.348 | 0.757 | +0.409 |
| overlap f1 | LOC | 0.504 | 0.825 | +0.321 |
| overlap precision | ORG | 0.250 | 0.250 | +0.000 |
| overlap recall | ORG | 0.091 | 0.091 | +0.000 |
| overlap f1 | ORG | 0.133 | 0.133 | +0.000 |
| overlap precision | all | 0.784 | 0.693 | -0.091 |
| overlap recall | all | 0.468 | 0.712 | +0.244 |
| overlap f1 | all | 0.586 | 0.702 | +0.116 |
| strict precision (nur `<p>`) | PER | 0.583 | 0.655 | +0.072 |
| strict recall (nur `<p>`) | PER | 0.600 | 0.570 | -0.030 |
| strict f1 (nur `<p>`) | PER | 0.591 | 0.610 | +0.019 |
| strict precision (nur `<p>`) | LOC | 0.870 | 0.909 | +0.039 |
| strict recall (nur `<p>`) | LOC | 0.556 | 0.648 | +0.092 |
| strict f1 (nur `<p>`) | LOC | 0.678 | 0.757 | +0.079 |
| strict precision (nur `<p>`) | ORG | 0.250 | 0.000 | -0.250 |
| strict recall (nur `<p>`) | ORG | 0.143 | 0.000 | -0.143 |
| strict f1 (nur `<p>`) | ORG | 0.182 | 0.000 | -0.182 |
| strict precision (nur `<p>`) | all | 0.688 | 0.770 | +0.082 |
| strict recall (nur `<p>`) | all | 0.563 | 0.591 | +0.028 |
| strict f1 (nur `<p>`) | all | 0.619 | 0.668 | +0.049 |
| overlap precision (nur `<p>`) | PER | 0.718 | 0.805 | +0.087 |
| overlap recall (nur `<p>`) | PER | 0.740 | 0.700 | -0.040 |
| overlap f1 (nur `<p>`) | PER | 0.729 | 0.749 | +0.020 |
| overlap precision (nur `<p>`) | LOC | 0.913 | 0.935 | +0.022 |
| overlap recall (nur `<p>`) | LOC | 0.583 | 0.667 | +0.084 |
| overlap f1 (nur `<p>`) | LOC | 0.712 | 0.778 | +0.066 |
| overlap precision (nur `<p>`) | ORG | 0.250 | 0.000 | -0.250 |
| overlap recall (nur `<p>`) | ORG | 0.143 | 0.000 | -0.143 |
| overlap f1 (nur `<p>`) | ORG | 0.182 | 0.000 | -0.182 |
| overlap precision (nur `<p>`) | all | 0.784 | 0.861 | +0.077 |
| overlap recall (nur `<p>`) | all | 0.642 | 0.660 | +0.018 |
| overlap f1 (nur `<p>`) | all | 0.706 | 0.747 | +0.041 |

| Befund | vorher | nachher |
| --- | ---: | ---: |
| nicht erkannt | 151 | 78 |
| falscher Treffer | 28 | 78 |
| Grenze abweichend | 21 | 58 |
| Typ abweichend | 6 | 7 |
| Struktur: inline | 176 | 262 |
| Struktur: standoff | 0 | 41 |
| Struktur: in_note | 138 | 0 |
| Struktur: in_del | 0 | 0 |
| Struktur: in_other_reference | 33 | 8 |
| Struktur: in_c_or_g | 0 | 0 |
