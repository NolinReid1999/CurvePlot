"""Compact check descriptions for the upcoming PhysicsPlot review panel."""


def summarize_checks(checks: list[dict], limit: int = 3) -> str:
    """Format validated check results without mutating them."""
    if type(limit) is not int or not (1 <= limit <= 3):
        raise ValueError("limit must be an integer between 1 and 3")

    if not isinstance(checks, list):
        raise ValueError("checks must be a list")

    for check in checks:
        if not isinstance(check, dict) or "name" not in check or "passed" not in check:
            raise ValueError(
                "Each check must be a dictionary with 'name' and 'passed' keys"
            )
        if not isinstance(check["name"], str) or not check["name"].strip():
            raise ValueError("'name' must be a nonempty string")
        if not isinstance(check["passed"], bool):
            raise ValueError("'passed' must be a boolean")

    formatted_checks = []
    for check in checks:
        name = " ".join(check["name"].split()).strip()
        if len(name) > 40:
            name = name[:37] + "..."
        status = "PASS" if check["passed"] else "FAIL"
        formatted_checks.append(f"{status} {name}")

    if len(formatted_checks) > limit:
        return (
            "; ".join(formatted_checks[:limit])
            + f"; +{len(formatted_checks) - limit} more"
        )
    else:
        return "; ".join(formatted_checks) if formatted_checks else "No checks."
