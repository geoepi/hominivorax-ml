# GPBoost 1.8.0 VIF API preflight

Pre-execution API checks were performed in the installed Atlas environment
`gpboost_env_1.8.0` through the authorized WSL `atlas-ssh` wrapper. The exact
requested `GPModel` constructor arguments were accepted for
`likelihood="bernoulli_logit"`, `cov_function="matern_space_time"`,
`gp_approx="full_scale_vecchia"`, 200 inducing points with `kmeans++`, eight
neighbors, `vecchia_ordering="time"`, iterative inversion, 16 parallel
threads, and seed 31415. `set_prediction_data` also accepted
`order_obs_first_cond_obs_only` with 40 neighbors. These checks constructed a
GP model only; they did not call `fit` or `gpb.train`.

The installed 1.8.0 constructor documentation explicitly lists Bernoulli-logit
likelihoods, `matern_space_time`, VIF for non-Gaussian likelihoods,
`ind_points_selection`, and the 200-point VIF default. The installed Python
signatures expose the requested constructor and prediction arguments,
`train_gp_model_cov_pars`, and training callbacks. The run-time API audit stores
the full signatures and documentation excerpts.

The no-fit constructor checks emitted GPBoost warnings that 130 and 30
inducing points were removed on two small synthetic coordinate sets because
they coincided with data points. The production gate will keep the prescribed
200-point `kmeans++` request, capture any corresponding native warning, and
report it as a limitation. It will not silently substitute a different
inducing-point method or a different requested count.
