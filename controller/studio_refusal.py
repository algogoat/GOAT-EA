"""The controller's structured refusal (goatai#2272 self-heal), shared by both CLIs.

Moved unchanged from demo_agent.py so studio_agent_setup can raise it without importing the demo
agent; demo_agent re-exports it under its old name. The goat_studio and demo_agent CLIs both put
``refusal_code`` and every field beside the unchanged ``error`` sentence.
"""


class Refusal(ValueError):
    """A refusal with a stable machine code next to its sentence (goatai#2272 self-heal).

    Still a ValueError everywhere, so the CLI's top-level ``code`` stays ``REFUSED`` (the desktop
    keys on it); the CLI adds ``refusal_code`` and any ``fields`` beside the unchanged ``error``.
    Fields are structured data for an agent (never parsed out of the sentence) and must be JSON.
    """
    def __init__(self, message, code, **fields):
        super().__init__(message)
        self.code, self.fields = code, fields


def refusal_fields(exc, error):
    """The JSON a CLI adds for a Refusal: its fields (never overwriting ``error``'s own keys) and ``refusal_code``."""
    if not isinstance(exc, Refusal):
        return {}
    return {key: value for key, value in exc.fields.items() if key not in error} | dict(refusal_code=exc.code)
