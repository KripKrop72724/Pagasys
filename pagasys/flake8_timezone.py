import ast

FORBIDDEN_CALLS = {
    ("datetime", "now"): (
        "TZ001",
        "datetime.now() is not allowed. Use django.utils.timezone.now().",
    ),
    ("datetime", "today"): (
        "TZ002",
        "datetime.today() is not allowed. Use django.utils.timezone.localdate().",
    ),
    ("date", "today"): (
        "TZ003",
        "date.today() is not allowed. Use django.utils.timezone.localdate().",
    ),
}


class TimezoneLinter:
    """Flake8 plugin enforcing Django timezone helpers."""

    name = "flake8-django-timezone"
    version = "0.1.0"

    def __init__(self, tree):
        self.tree = tree

    def run(self):
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func
            if not isinstance(func, ast.Attribute):
                continue

            # unwind attribute chain to find the root name
            value = func.value
            while isinstance(value, ast.Attribute):
                value = value.value

            if isinstance(value, ast.Name):
                key = (value.id, func.attr)
                if key in FORBIDDEN_CALLS:
                    code, msg = FORBIDDEN_CALLS[key]
                    yield node.lineno, node.col_offset, f"{code} {msg}", type(self)
