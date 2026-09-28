from retail.platforms.magento import make_magento_store, parse_magento_target

parse_newbalance_target = parse_magento_target

NewbalanceStore = make_magento_store(
    store_id="newbalance",
    title="New Balance",
    site="www.newbalance.cl",
    base="https://www.newbalance.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
