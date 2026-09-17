"""Declarative test contracts shared by generation and the container runner."""
import json

TEMPLATES = {"python-files", "python-http"}


def validate_suite(suite):
    if not isinstance(suite, dict) or suite.get("version") != 1:
        raise ValueError("tests/suite.json must use version 1.")
    if suite.get("template") not in TEMPLATES:
        raise ValueError("Test template must be python-files or python-http.")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 12:
        raise ValueError("Test suite must contain 1–12 cases.")
    names = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("name"), str) or not case["name"].strip() or case["name"] in names:
            raise ValueError("Each test needs a unique, nonempty name.")
        names.add(case["name"])
        if not isinstance(case.get("args"), list) or not all(isinstance(arg, str) for arg in case["args"]):
            raise ValueError("Test args must be a list of strings.")
        if type(case.get("exit_code")) is not int:
            raise ValueError("Each test must specify an integer exit_code.")
        timeout = case.get("timeout_seconds", 10)
        if type(timeout) is not int or not 1 <= timeout <= 20:
            raise ValueError("Test timeout_seconds must be between 1 and 20.")
        assertions = 0
        for key in ("stdout_contains", "stderr_contains"):
            if key in case:
                values = case[key]
                if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
                    raise ValueError(f"{key} must contain nonempty strings.")
                assertions += 1
        if "stdout_json" in case:
            assertions += 1
        if not assertions:
            raise ValueError("Each test needs an output assertion, not only an exit code.")
    routes = suite.get("http_routes", {})
    if not isinstance(routes, dict) or len(routes) > 30:
        raise ValueError("http_routes must be an object with at most 30 routes.")
    for path, route in routes.items():
        if not path.startswith("/") or not isinstance(route, dict) or not isinstance(route.get("body", ""), str):
            raise ValueError("Each HTTP route needs a path and a text body.")
        if type(route.get("status", 200)) is not int or not 100 <= route.get("status", 200) <= 599:
            raise ValueError("Invalid HTTP route status.")
    if suite["template"] == "python-http" and not routes:
        raise ValueError("python-http requires http_routes.")
    return suite


def load_suite(path):
    with open(path, encoding="utf-8") as handle:
        return validate_suite(json.load(handle))
