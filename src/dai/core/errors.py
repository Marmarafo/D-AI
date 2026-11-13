class DaiError(Exception):
    """Base class for D-AI errors."""


class ConfigError(DaiError):
    pass


class FetchError(DaiError):
    pass


class UnsafeURL(FetchError):
    pass
