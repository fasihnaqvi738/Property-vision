"""Validation helpers and CLI for the shared capture result contract."""

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "property_capture_result.schema.json"


def validate_result(result: dict, schema_path: Path = SCHEMA_PATH) -> None:
    """Raise ValueError with all schema issues when a result is not contract compliant."""
    with Path(schema_path).open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    Draft202012Validator.check_schema(schema)
    issues = sorted(
        Draft202012Validator(schema).iter_errors(result),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    if issues:
        details = []
        for issue in issues:
            location = "$"
            for part in issue.absolute_path:
                location += f"[{part}]" if isinstance(part, int) else f".{part}"
            details.append(f"{location}: {issue.message}")
        raise ValueError("Result does not match the shared schema:\n- " + "\n- ".join(details))


def validate_result_file(path: Path) -> None:
    with Path(path).open(encoding="utf-8") as result_file:
        result = json.load(result_file)
    validate_result(result)


def _collect_result_files(inputs: list[Path]) -> list[Path]:
    files = []
    for input_path in inputs:
        if input_path.is_dir():
            files.extend(input_path.rglob("result.json"))
        elif input_path.is_file():
            files.append(input_path)
        else:
            raise FileNotFoundError(f"Input does not exist: {input_path}")
    return sorted(set(path.resolve() for path in files))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Property Vision result.json files against the shared JSON schema.")
    parser.add_argument("paths", nargs="+", type=Path, help="Result JSON file(s) or directories to scan recursively.")
    args = parser.parse_args()
    try:
        result_files = _collect_result_files(args.paths)
        if not result_files:
            raise FileNotFoundError("No result.json files found in the supplied paths.")
        failures = 0
        for path in result_files:
            try:
                validate_result_file(path)
                print(f"VALID {path}")
            except (ValueError, json.JSONDecodeError) as error:
                failures += 1
                print(f"INVALID {path}\n{error}", file=sys.stderr)
        print(f"Validated {len(result_files)} result(s); {failures} invalid.")
        return 1 if failures else 0
    except (OSError, FileNotFoundError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
