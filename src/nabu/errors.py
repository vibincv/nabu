"""Named errors (FRD Section 14). Every failure maps to one of these and a one-line message.

Messages must never contain document text or values. They may contain file names.
"""


class NabuError(Exception):
    """Base class. `message` is shown to the user as-is."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigError(NabuError):
    pass


class EgressBlocked(NabuError):
    """Raised by the egress guard when code tries to reach a non-allowed address (AR-3)."""


class ValueWriteRefused(NabuError):
    """Raised by the store when a write would put a document value on disk (AR-7, FR-11.6)."""


class UnsupportedFormat(NabuError):
    pass


class UnreadableInput(NabuError):
    pass


class TooLarge(NabuError):
    pass


class ModelUnavailable(NabuError):
    pass


class ModelOutputInvalid(NabuError):
    pass


class OcrLanguageMissing(NabuError):
    pass
