"""Bounded delimiter detection shared by preview and background import."""

import csv
import itertools


def resolve_delimiter(path, parameters):
    if parameters.delimiter is not None:
        return parameters.delimiter
    start = parameters.skiprows + (parameters.header or 0)
    with open(path, encoding=parameters.encoding) as stream:
        for _ in range(start):
            if not stream.readline(65536):
                break
        lines = list(itertools.islice(stream, 21))
    if len(lines) <= 20 and parameters.skipfooter:
        lines = lines[: -parameters.skipfooter]
    sample = "".join(lines[:20])[:65536]
    if not sample.strip():
        return ","
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t| ").delimiter
    except csv.Error:
        return ","  # A one-column numeric file needs no delimiter at all.


def convert_import_columns(frame):
    """Preserve wholly textual columns for category/date axes, coerce mixed numeric columns."""
    import pandas as pd
    result=frame.apply(pd.to_numeric,errors='coerce')
    for name in frame.columns:
        source=frame[name]
        # Do not destroy categorical labels or ISO dates just because a column
        # has no numeric observations. Mixed numeric/bad-value columns retain
        # the established missing-value and warning policy.
        if source.notna().any() and not result[name].notna().any():
            result[name]=source.copy()
    return result
