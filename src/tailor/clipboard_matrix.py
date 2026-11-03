"""Numeric spreadsheet clipboard parsing, independent of Qt."""


def parse_matrix(text: str, formats=()) -> list[list]:
    """Parse a ragged TSV rectangle without dropping empty cells."""
    if not text.strip():
        return []
    rows = text.rstrip("\r\n").splitlines()
    width = max(len(row.split("\t")) for row in rows)
    result = []
    for row_number, row in enumerate(rows, 1):
        values = []
        for column, cell in enumerate(row.split("\t"), 1):
            try:
                kind = formats[column - 1] if column <= len(formats) else "numeric"
                values.append(
                    cell
                    if kind != "numeric"
                    else float(cell.strip())
                    if cell.strip()
                    else float("nan")
                )
            except ValueError as exc:
                raise ValueError(
                    f"第 {row_number} 行、第 {column} 列不是有效数值"
                ) from exc
        values.extend([float("nan")] * (width - len(values)))
        result.append(values)
    return result
