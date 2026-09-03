# Model Evaluation

No model results exist yet. This file deliberately contains no fabricated metrics.

Phase 1 will use reproducible personal held-out splits, time-aware where dates are sufficiently complete and seeded repeated splits otherwise. It will compare popularity, content, collaborative, and hybrid models using MAE, RMSE, Precision@K, Recall@K, NDCG@K, hit rate, rank correlation, coverage, diversity, and novelty.

Every result must record data fingerprints, split strategy, seed, configuration, timestamp, artifact path, code/dependency version where practical, coverage, and missing mappings. Hybrid success requires improvement beyond simple baselines. Failures and poorly predicted films will be reported honestly.

Implemented but not yet measured:

- Bayesian popularity baseline with configurable count shrinkage toward the global mean.
- Personal content Ridge baseline using MovieLens genres and release-decade features.
- Bias-adjusted truncated-SVD collaborative model with regularized personal factor fitting.
- Fixed-weight prototype hybrid of collaborative, content, and popularity predictions.

Their artifacts and predictions are functional, but no performance claim will be made until a real Letterboxd import has sufficient MovieLens linkage and the held-out evaluator is run on it.

The seeded evaluator is now implemented for MAE and RMSE and writes every held-out actual/predicted value for audit. It requires at least ten linked ratings, but a much larger history is needed for trustworthy comparisons. Precision@K, Recall@K, NDCG, novelty, diversity, repeated splits, and time-aware evaluation remain incomplete; Phase 1 cannot be declared successful from a single MAE/RMSE split.
