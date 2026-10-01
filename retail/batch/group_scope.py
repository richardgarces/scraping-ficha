"""Errores de arranque de las corridas por grupo."""


class GroupBatchBusy(RuntimeError):
    def __init__(self, group: str) -> None:
        super().__init__(f"Ya hay una corrida de {group} en curso.")


class GroupBatchPaused(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Reanuda las corridas antes de iniciar un grupo.")
