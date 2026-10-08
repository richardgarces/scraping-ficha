from retail.platforms.magento import make_magento_store, parse_magento_target

parse_bath_and_body_works_target = parse_magento_target

BathAndBodyWorksStore = make_magento_store(
    store_id="bath_and_body_works",
    title="Bath & Body Works",
    site="www.bathandbodyworks.cl",
    base="https://www.bathandbodyworks.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
