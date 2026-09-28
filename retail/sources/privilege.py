from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_privilege_target = parse_vtex_target

PrivilegeStore = make_vtex_store(
    store_id="privilege",
    title="Privilege",
    site="www.privilege.cl",
    base="https://www.privilege.cl",
    default_brand="Privilege",
    category_help="Slug VTEX, por ejemplo mujer/vestidos",
    group="moda",
)
