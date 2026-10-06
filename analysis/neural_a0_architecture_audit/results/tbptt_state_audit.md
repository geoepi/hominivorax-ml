# TBPTT state audit

- The audit training loop initializes `hidden = None` at each epoch and runs all 52 warm-up feature weeks under `torch.no_grad()` before response loss begins.
- Training uses contiguous 13-week chunks. Each chunk calls `optimizer.zero_grad(set_to_none=True)`, performs one optimizer step after the chunk, and detaches the resulting hidden state before the next chunk.
- Validation follows the final training hidden state when validation is temporally after training; the restored-best-checkpoint final evaluation instead resets hidden and replays the 52-week warm-up before validation.
- A new model and hidden state are created per fold/seed task, so hidden state is not retained across folds or unrelated tasks.
- No response loss is calculated during warm-up. Development validation uses only F1--F4 weeks; terminal/later responses are not loaded.

These references correspond to `scripts/run_neural_a0_architecture_audit.py` and the unchanged recurrent model interfaces in `python/task2b_models.py`.
