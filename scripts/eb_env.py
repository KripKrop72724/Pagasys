import argparse
import json
import os
import re
from typing import Iterable, List, Dict

NAMESPACE = "aws:elasticbeanstalk:application:environment"
VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def generate_option_settings(names: Iterable[str]) -> List[Dict[str, str]]:
    """Return option settings for the given environment variable names.

    Parameters
    ----------
    names:
        Iterable of environment variable names to include.

    Returns
    -------
    List[Dict[str, str]]
        Option settings suitable for aws elasticbeanstalk update-environment.

    Raises
    ------
    KeyError
        If a requested variable is missing from the environment.
    ValueError
        If a name is empty or contains invalid characters.
    """
    options: List[Dict[str, str]] = []
    seen = set()
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            raise ValueError("Empty environment variable name")
        if not VALID_NAME.fullmatch(name):
            raise ValueError(f"Invalid environment variable name: {name}")
        if name in seen:
            continue
        seen.add(name)
        if name not in os.environ:
            raise KeyError(f"Missing environment variable: {name}")
        options.append(
            {
                "Namespace": NAMESPACE,
                "OptionName": name,
                "Value": os.environ[name],
            }
        )
    return options


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Elastic Beanstalk option settings from env vars",
    )
    parser.add_argument(
        "--names",
        required=True,
        help="Comma-separated list of environment variable names",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write JSON file containing option settings",
    )
    args = parser.parse_args(argv)

    names = [n for n in (n.strip() for n in args.names.split(",")) if n]
    try:
        options = generate_option_settings(names)
    except Exception as exc:  # pragma: no cover - handled in tests
        print(str(exc), file=os.sys.stderr)
        return 1
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(options, fh)
    print(f"Wrote {len(options)} environment variables to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
