from retail.platforms.magento import make_magento_store, parse_magento_target

parse_ripcurl_target = parse_magento_target

RipcurlStore = make_magento_store(
    store_id="ripcurl",
    title="Rip Curl",
    site="www.ripcurl.cl",
    base="https://www.ripcurl.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
