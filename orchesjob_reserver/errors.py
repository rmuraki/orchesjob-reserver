from __future__ import annotations


class ReserverError(Exception):
    pass


class CliError(ReserverError):
    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code
