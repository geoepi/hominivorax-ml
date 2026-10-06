# Warm-up audit

The prepared A0 tensor has 120 weeks: 52 warm-up weeks followed by the 68 development weeks. Every task replays exactly the first 52 feature weeks before training and before final validation prediction. Warm-up weeks do not contribute response loss. Fold training and validation indices are restricted to the four specified development splits; no F5/F6 or terminal/later outcomes are loaded.

The input artifact is the persisted A0 tensor from the completed revised-domain experiment, verified at shape `[120, 10037, 30]`, with canonical node order and 77,614 directed edges.
