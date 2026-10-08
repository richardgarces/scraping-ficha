from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_elite_professional_target = parse_vtex_target

EliteProfessionalStore = make_vtex_store(
    store_id="elite_professional",
    title="Elite Professional",
    site="www.eliteprofessional.cl",
    base="https://www.eliteprofessional.cl",
    default_brand='Elite Professional',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="retail",
)
