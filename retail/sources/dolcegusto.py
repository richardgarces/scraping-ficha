from retail.platforms.magento import make_magento_store, parse_magento_target

parse_dolcegusto_target = parse_magento_target

DolcegustoStore = make_magento_store(
    store_id="dolcegusto",
    title="Nescafé Dolce Gusto",
    site="www.dolce-gusto.cl",
    base="https://www.dolce-gusto.cl",
    category_help="Slug Magento, por ejemplo capsulas",
)
