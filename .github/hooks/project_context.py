import json


def main() -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "Proyecto precios.meincart.cl (Python >=3.11). Antes de editar, "
                "lee el código y sus pruebas. Nunca inventes datos: separa precio "
                "sin tarjeta, tarjeta/cupón y despacho; marca como no verificado "
                "lo que no tenga evidencia. Los cambios de esquema requieren plan "
                "y aprobación. Un push a main puede desplegar a BMAX."
            ),
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
