from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_trial_target = parse_vtex_target

TrialStore = make_vtex_store(
    store_id="trial",
    title="Trial",
    site="www.trial.cl",
    base="https://www.trial.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
