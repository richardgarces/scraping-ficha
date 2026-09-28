from retail.platforms.magento import make_magento_store, parse_magento_target

parse_prune_target = parse_magento_target

PruneStore = make_magento_store(
    store_id="prune",
    title="Prüne",
    site="pruneshop.cl",
    base="https://pruneshop.cl",
    category_help="Slug Magento, por ejemplo carteras",
)
