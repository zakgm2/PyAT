"""
backend/errors.py
-----------------
What a failed request to the analysis engine looks like to the app: one exception, carrying the engine's own error record
({"code", "message", "hint", "type"}; see PyATCLI/ops/__init__.py), so a caller can tell "the file is not there" from "the engine
stopped" without reading the text, and the person is shown the text.
"""


class BackendError(Exception):
    """A request the engine (or a one-shot `python -m PyATCLI` run) could not do.

    code     what kind of failure: bad_parameter, invalid_input, not_found, io_error, analysis_failed, cannot_reproduce, unknown_operation,
             no_recording, confirmation_required, cancelled, internal_error — or, from this side of the pipe, engine_stopped,
             engine_unavailable, bad_reply
    message  what is wrong, for the person
    hint     what to do about it, or None
    type     the class name of the exception the engine raised
    """

    def __init__(self, message, code="internal_error", hint=None, type_name=None):
        super().__init__(message)
        self.message = str(message)
        self.code = code
        self.hint = hint
        self.type_name = type_name

    @classmethod
    def from_info(cls, info):
        info = info or {}
        return cls(info.get("message") or "the analysis engine failed", code=info.get("code") or "internal_error",
                   hint=info.get("hint"), type_name=info.get("type"))

    @property
    def cancelled(self):
        return self.code == "cancelled"

    def __str__(self):
        return f"{self.message}\n{self.hint}" if self.hint else self.message

    def info(self):
        return {"code": self.code, "message": self.message, "hint": self.hint, "type": self.type_name}
