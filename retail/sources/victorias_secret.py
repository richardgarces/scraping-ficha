from retail.platforms.magento import make_magento_store, parse_magento_target

parse_victorias_secret_target = parse_magento_target

VictoriasSecretStore = make_magento_store(
    store_id="victorias_secret",
    title="Victoria’s Secret",
    site="www.victoriassecret.cl",
    base="https://www.victoriassecret.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
