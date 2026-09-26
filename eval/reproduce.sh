#!/bin/sh
# Reproduce every number in eval/results from the pinned corpus.
#   pip install -e . -r eval/requirements.txt
#   git worktree add ../tcb-v0.1 e09fa38        # baseline for the comparison
#   git worktree add ../tcb-v0.2 <commit>       # optional: measure a committed, clean state
# V01_SRC and SRC point to the src/ folders of the two checkouts.
set -eu
V01_SRC=${V01_SRC:-../tcb-v0.1/src}
SRC=${SRC:-src}
E="python eval/evaluate.py"
HF="--engine hf --local-files-only"
$E prepare
$E run --label v0.1-hf --src "$V01_SRC" -- $HF
$E run --label v0.2-hf --src "$SRC" -- $HF
$E run --label ablation-simple --src "$SRC" -- $HF --aggregation simple
$E run --label v0.1-hf-original --input original --src "$V01_SRC" -- $HF
$E run --label v0.2-hf-original --input original --src "$SRC" -- $HF
for label in v0.1-hf v0.2-hf ablation-simple; do $E score --label "$label" > /dev/null; done
$E compare v0.1-hf v0.2-hf > /dev/null
$E integrity --label v0.1-hf-original > /dev/null || echo "v0.1: integrity findings recorded (expected for the baseline)"
$E integrity --label v0.2-hf-original > /dev/null
echo "results written to eval/results"
