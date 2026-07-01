from __future__ import annotations

import io
import json

from rich.console import Console
from rich.table import Table


def render(data, *, as_json: bool, columns: list[str] | None = None) -> str:
    if as_json:
        return json.dumps(data, indent=2, default=str)

    rows = data if isinstance(data, list) else [data]
    cols = columns or (list(rows[0].keys()) if rows else [])

    table = Table(show_header=True, header_style="bold")
    for c in cols:
        table.add_column(c)
    for row in rows:
        table.add_row(*(str(row.get(c, "")) for c in cols))

    buf = io.StringIO()
    Console(file=buf, width=120).print(table)
    return buf.getvalue()
