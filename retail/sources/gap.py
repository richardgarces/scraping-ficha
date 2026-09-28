from retail.platforms.magento import make_magento_store, parse_magento_target

parse_gap_target = parse_magento_target

GapStore = make_magento_store(
    store_id="gap",
    title="GAP",
    site="www.gap.cl",
    base="https://www.gap.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
