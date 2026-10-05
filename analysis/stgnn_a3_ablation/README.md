# Revised-domain paired neural A0 versus A3 experiment

This analysis compares the frozen 30-feature V2-A neural predictor tensor with
the same tensor plus the four frozen A3 additions on the revised 10,037-node
domain. The GConvGRU hurdle-NB architecture and training protocol are held
constant; only input width changes from 30 to 34.

The runner is `scripts/run_stgnn_a3_ablation.py`:

```bash
python scripts/run_stgnn_a3_ablation.py --mode prepare \
  --output-root /project/disease_ecology/STGNN-output \
  --repo /project/disease_ecology/STGNN

sbatch hpc/run_stgnn_a3_ablation.sbatch

python scripts/run_stgnn_a3_ablation.py --mode finalize \
  --output-root /project/disease_ecology/STGNN-output \
  --repo /project/disease_ecology/STGNN
```

Prepared tensors, task JSON files, predictions, and checkpoints remain under
`/project/disease_ecology/STGNN-output/stgnn_a3_ablation/`; only compact QA,
metrics, manifests, figures, and the report are written to `results/`.

The experiment uses F1--F4 only, five paired seeds per fold, a 52-week
warm-up, 13-week TBPTT, hidden width 64, GConvGRU K=3, dropout 0.1, Adam at
0.0003, zero neural weight decay, gradient clipping at 1.0, and fixed theta
`0.7018903965556372`. The structured-model penalty 0.01 is not applied as a
new neural penalty.
