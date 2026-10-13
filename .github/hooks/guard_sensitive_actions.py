import json
import re
import sys
from collections.abc import Iterator
from typing import Any


COMMAND_FIELDS = {
    "command",
    "cmd",
    "shellcommand",
    "shell_command",
    "script",
    "args",
    "argv",
}


def command_values(value: Any, field_name: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from command_values(nested, str(key).lower())
    elif isinstance(value, list):
        if field_name in {"args", "argv"} and all(
            isinstance(argument, str) for argument in value
        ):
            yield " ".join(value)
            return
        for nested in value:
            yield from command_values(nested, field_name)
    elif isinstance(value, str) and field_name in COMMAND_FIELDS:
        yield value


def approval_reason(event: dict[str, Any]) -> str | None:
    for command in command_values(event.get("tool_input", {})):
        if re.search(r"(?<![\w.-])git(?:\s+-C\s+\S+)?\s+push\b", command):
            return "Un push puede publicar cambios y desplegar a BMAX; confirma antes de continuar."
        normalized = command.casefold()
        if (
            "migrate_product_identity.py" in normalized
            and re.search(r"(?<!\S)--apply(?:\s|$)", normalized)
        ):
            return "La migración escribe datos persistentes; revisa el preview y confirma --apply."
    return None


def emit_approval(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        emit_approval("No se pudo validar la acción por una entrada de hook inválida.")
        return 0

    if not isinstance(event, dict):
        emit_approval("No se pudo validar la acción: el evento del hook no es un objeto.")
        return 0

    reason = approval_reason(event)
    if reason:
        emit_approval(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
