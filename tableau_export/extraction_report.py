"""Markdown inventory of everything extracted from a Tableau workbook.

The migration pipeline already writes 23 JSON files describing the source
workbook, but they are machine-shaped: to answer "what was in this dashboard?"
you have to open a dozen of them. This module folds them into one readable
``.md`` file written next to the generated project, listing every worksheet,
data source, column, calculated field, filter, parameter, action and query the
extractor found — including the items the converter could not map, so the gaps
are visible rather than implied.

It reads only the extracted JSON, never the workbook, so it costs nothing to
produce and cannot change the migration result.

Entry point::

    from extraction_report import generate_extraction_report
    generate_extraction_report(extract_dir, output_path, workbook_name="Sales")
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime

__all__ = ["generate_extraction_report", "build_extraction_report"]


# ── loading ─────────────────────────────────────────────────────────

#: Extracted file -> human heading. Order drives the report's section order.
OBJECT_FILES = [
    ("datasources", "Data Sources"),
    ("worksheets", "Worksheets (Visuals)"),
    ("dashboards", "Dashboards"),
    ("stories", "Stories"),
    ("calculations", "Calculated Fields"),
    ("parameters", "Parameters"),
    ("filters", "Filters"),
    ("datasource_filters", "Data Source Filters"),
    ("sets", "Sets"),
    ("groups", "Groups"),
    ("bins", "Bins"),
    ("hierarchies", "Hierarchies"),
    ("actions", "Actions"),
    ("custom_sql", "Custom SQL"),
    ("hyper_files", "Hyper Extracts"),
    ("published_datasources", "Published Data Sources"),
    ("data_blending", "Data Blending"),
    ("table_extensions", "Table Extensions"),
    ("custom_geocoding", "Custom Geocoding"),
    ("user_filters", "User Filters (RLS)"),
    ("sort_orders", "Sort Orders"),
    ("aliases", "Aliases"),
    ("linguistic_schema", "Linguistic Schema (Q&A synonyms)"),
]


def _load(extract_dir, name):
    """Load one extracted JSON file, returning ``None`` when absent."""
    path = os.path.join(extract_dir, f"{name}.json")
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _count(value):
    if value is None:
        return 0
    if isinstance(value, (list, dict)):
        return len(value)
    return 1


# ── markdown helpers ────────────────────────────────────────────────

def _esc(value):
    """Render *value* safely inside a Markdown table cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(_esc(v) for v in value if v not in (None, ""))
    if isinstance(value, dict):
        return ", ".join(f"{k}={_esc(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    # Only the pipe needs escaping inside a table cell. Doubling backslashes
    # would mangle every Windows path in the report.
    text = str(value).replace("|", "\\|")
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return text.strip()


def _table(headers, rows):
    """Build a Markdown table, or a placeholder when there are no rows."""
    if not rows:
        return ["_None found._", ""]
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        cells = [_esc(c) for c in row]
        cells += [""] * (len(headers) - len(cells))
        out.append("| " + " | ".join(cells[:len(headers)]) + " |")
    out.append("")
    return out


def _code_block(text, lang=""):
    body = "" if text is None else str(text).rstrip()
    if not body:
        return []
    fence = "```"
    while fence in body:
        fence += "`"
    return [f"{fence}{lang}", body, fence, ""]


def _heading(level, text):
    return [f"{'#' * level} {text}", ""]


# ── sections ────────────────────────────────────────────────────────

def _section_summary(data):
    lines = _heading(2, "Contents")
    rows = []
    for key, label in OBJECT_FILES:
        value = data.get(key)
        if value is None:
            rows.append([label, "—", "not extracted"])
        else:
            count = _count(value)
            rows.append([label, count, "" if count else "none in workbook"])
    lines += _table(["Object type", "Count", "Notes"], rows)
    return lines


def _section_datasources(datasources):
    lines = _heading(2, "Data Sources")
    if not datasources:
        return lines + ["_None found._", ""]

    for ds in datasources:
        if not isinstance(ds, dict):
            continue
        caption = ds.get("caption") or ds.get("name") or "(unnamed)"
        lines += _heading(3, f"{caption}")

        conn = ds.get("connection") or {}
        details = conn.get("details") if isinstance(conn, dict) else {}
        meta = [
            ["Internal name", ds.get("name")],
            ["Caption", ds.get("caption")],
            ["Connection type", (conn or {}).get("type")],
        ]
        for key in ("server", "port", "dbname", "database", "schema", "filename",
                    "directory", "warehouse", "project", "authentication", "class"):
            if isinstance(details, dict) and details.get(key):
                meta.append([key.title(), details[key]])
        lines += _table(["Property", "Value"], meta)

        tables = ds.get("tables") or []
        if tables:
            lines += _heading(4, "Tables")
            rows = []
            for tbl in tables:
                if isinstance(tbl, dict):
                    rows.append([tbl.get("name") or tbl.get("table"),
                                 tbl.get("type"), tbl.get("alias")])
                else:
                    rows.append([tbl, "", ""])
            lines += _table(["Table", "Type", "Alias"], rows)

        rels = ds.get("relationships") or []
        if rels:
            lines += _heading(4, "Joins / Relationships")
            rows = []
            for rel in rels:
                if not isinstance(rel, dict):
                    rows.append([rel, "", "", ""])
                    continue
                rows.append([
                    rel.get("left_table") or rel.get("left") or rel.get("from"),
                    rel.get("right_table") or rel.get("right") or rel.get("to"),
                    rel.get("join_type") or rel.get("type") or rel.get("operator"),
                    rel.get("condition") or rel.get("expression")
                    or rel.get("on") or rel.get("clause"),
                ])
            lines += _table(["Left", "Right", "Join", "Condition"], rows)

        columns = ds.get("columns") or []
        lines += _heading(4, f"Columns ({len(columns)})")
        rows = []
        for col in columns:
            if not isinstance(col, dict):
                rows.append([col]); continue
            calc = col.get("calculation") or {}
            rows.append([
                col.get("caption") or col.get("name"),
                col.get("name"),
                col.get("datatype"),
                col.get("role"),
                col.get("type"),
                col.get("default_aggregation"),
                col.get("semantic_role"),
                col.get("hidden"),
                "yes" if (isinstance(calc, dict) and calc.get("formula")) else "",
                col.get("description"),
            ])
        lines += _table(
            ["Field", "Internal name", "Data type", "Role", "Measure type",
             "Default agg", "Semantic role", "Hidden", "Calculated", "Description"],
            rows,
        )
    return lines


def _classify_calc(formula):
    """Label a Tableau formula by the feature that drives its DAX conversion."""
    if not formula:
        return "—"
    upper = str(formula).upper()
    tags = []
    if "{FIXED" in upper:
        tags.append("LOD:FIXED")
    if "{INCLUDE" in upper:
        tags.append("LOD:INCLUDE")
    if "{EXCLUDE" in upper:
        tags.append("LOD:EXCLUDE")
    for fn in ("WINDOW_SUM", "WINDOW_AVG", "WINDOW_MIN", "WINDOW_MAX",
               "RUNNING_SUM", "RUNNING_AVG", "RUNNING_COUNT", "RUNNING_MIN",
               "RUNNING_MAX", "INDEX()", "RANK", "LOOKUP", "PREVIOUS_VALUE",
               "TOTAL(", "SIZE()", "FIRST()", "LAST()"):
        if fn in upper:
            tags.append("table calc")
            break
    if "REGEXP_" in upper:
        tags.append("regex")
    if "[PARAMETERS]." in upper or "[PARAMETER." in upper:
        tags.append("parameter")
    return ", ".join(tags) if tags else "standard"


def _section_calculations(calculations):
    lines = _heading(2, "Calculated Fields")
    if not calculations:
        return lines + ["_None found._", ""]

    rows = []
    for calc in calculations:
        if not isinstance(calc, dict):
            continue
        rows.append([
            calc.get("caption") or calc.get("name"),
            calc.get("datasource_name"),
            calc.get("datatype"),
            calc.get("role"),
            _classify_calc(calc.get("formula")),
        ])
    lines += _table(
        ["Field", "Data source", "Data type", "Role", "Features"], rows)

    lines += _heading(3, "Formulas")
    for calc in calculations:
        if not isinstance(calc, dict):
            continue
        name = calc.get("caption") or calc.get("name") or "(unnamed)"
        internal = calc.get("name")
        header = f"**{name}**"
        if internal and internal != name:
            header += f"  \n`{internal}`"
        lines += [header, ""]
        if calc.get("description"):
            lines += [f"> {calc['description']}", ""]
        lines += _code_block(calc.get("formula"))
    return lines


def _section_parameters(parameters):
    lines = _heading(2, "Parameters")
    rows = []
    for param in parameters or []:
        if not isinstance(param, dict):
            continue
        rows.append([
            param.get("caption") or param.get("name"),
            param.get("datatype"),
            param.get("current_value", param.get("value")),
            param.get("allowable_values") or param.get("allowable"),
            param.get("range_min"), param.get("range_max"), param.get("range_step"),
        ])
    lines += _table(
        ["Parameter", "Data type", "Current value", "Allowable", "Min", "Max", "Step"],
        rows)
    return lines


def _datasource_captions(datasources):
    """Map a data source's internal id to its caption.

    Worksheets reference data sources by ids like
    ``federated.14vgqpy1xbzasr1g68vql17hz4ef``; the caption is what the
    workbook author actually sees.
    """
    captions = {}
    for ds in datasources or []:
        if not isinstance(ds, dict):
            continue
        caption = ds.get("caption") or ds.get("name")
        for key in (ds.get("name"), ds.get("caption")):
            if key:
                captions[key] = caption
        conn = ds.get("connection") or {}
        if isinstance(conn, dict) and conn.get("name"):
            captions[conn["name"]] = caption
    return captions


def _friendly_ds(value, captions):
    """Resolve a data source reference to its caption where one is known."""
    if not value:
        return value
    text = str(value)
    if text in captions:
        return captions[text]
    # Worksheet fields use "<datasource>.<table>" form.
    head = text.split(".")[0]
    if head in captions:
        return captions[head]
    for key, caption in captions.items():
        if text.startswith(key):
            return caption
    return text


def _section_worksheets(worksheets, datasources=None):
    lines = _heading(2, "Worksheets (Visuals)")
    if not worksheets:
        return lines + ["_None found._", ""]
    captions = _datasource_captions(datasources)

    overview = []
    for ws in worksheets:
        if not isinstance(ws, dict):
            continue
        axes = ws.get("axes") or {}
        overview.append([
            ws.get("name"),
            ws.get("title") or "",
            ws.get("original_mark_class"),
            ws.get("chart_type"),
            len(ws.get("fields") or []),
            len(ws.get("filters") or []),
            "yes" if axes.get("dual_axis") else "",
        ])
    lines += _table(
        ["Worksheet", "Title", "Tableau mark", "Power BI visual",
         "Fields", "Filters", "Dual axis"],
        overview)

    for ws in worksheets:
        if not isinstance(ws, dict):
            continue
        lines += _heading(3, ws.get("name") or "(unnamed)")

        meta = [
            ["Tableau mark type", ws.get("original_mark_class")],
            ["Mapped Power BI visual", ws.get("chart_type")],
            ["Title", ws.get("title")],
            ["Description", ws.get("description")],
        ]
        axes = ws.get("axes") or {}
        if axes.get("dual_axis"):
            meta.append(["Dual axis", "yes (synchronised)" if axes.get("dual_axis_sync") else "yes"])
        lines += _table(["Property", "Value"], [m for m in meta if m[1]])

        fields = ws.get("fields") or []
        if fields:
            lines += _heading(4, f"Fields on shelves ({len(fields)})")
            lines += _table(
                ["Field", "Shelf", "Data source", "Aggregation"],
                [[f.get("name"), f.get("shelf"),
                  _friendly_ds(f.get("datasource"), captions),
                  f.get("aggregation")] for f in fields if isinstance(f, dict)])

        encoding = ws.get("mark_encoding") or {}
        if encoding:
            lines += _heading(4, "Mark encoding")
            lines += _table(["Channel", "Field"],
                            [[k, v] for k, v in encoding.items() if v])

        filters = ws.get("filters") or []
        if filters:
            lines += _heading(4, f"Filters ({len(filters)})")
            lines += _table(
                ["Field", "Type", "Mode", "Exclude", "Values"],
                [[f.get("field"), f.get("type"), f.get("filter_mode"),
                  f.get("exclude"), f.get("values")]
                 for f in filters if isinstance(f, dict)])

        for key, label, headers, getter in (
            ("sort_orders", "Sort orders", ["Field", "Direction", "By"],
             lambda s: [s.get("field"), s.get("direction"), s.get("sort_by")]),
            ("reference_lines", "Reference lines", ["Scope", "Value", "Label"],
             lambda s: [s.get("scope"), s.get("value"), s.get("label")]),
            ("trend_lines", "Trend lines", ["Model", "Field"],
             lambda s: [s.get("model"), s.get("field")]),
            ("table_calcs", "Table calculations", ["Field", "Type", "Compute using"],
             lambda s: [s.get("field"), s.get("type"), s.get("compute_using")]),
            ("tooltips", "Tooltips", ["Content"], lambda s: [s]),
            ("annotations", "Annotations", ["Text"], lambda s: [s]),
        ):
            items = ws.get(key) or []
            if not items:
                continue
            lines += _heading(4, label)
            rows = []
            for item in items:
                rows.append(getter(item) if isinstance(item, dict) else [item])
            lines += _table(headers, rows)

        totals = ws.get("totals") or {}
        if totals.get("grand_totals") or totals.get("subtotals"):
            lines += _heading(4, "Totals")
            lines += _table(["Kind", "Detail"],
                            [["Grand totals", totals.get("grand_totals")],
                             ["Subtotals", totals.get("subtotals")]])
    return lines


def _section_dashboards(dashboards):
    lines = _heading(2, "Dashboards")
    if not dashboards:
        return lines + ["_None found._", ""]

    for dash in dashboards:
        if not isinstance(dash, dict):
            continue
        lines += _heading(3, dash.get("name") or "(unnamed)")
        size = dash.get("size") or {}
        lines += _table(["Property", "Value"], [
            ["Title", dash.get("title")],
            ["Size", f"{size.get('width', '?')} x {size.get('height', '?')}"
                     if size else ""],
            ["Layout", "floating" if dash.get("floating_tiled") else "tiled"],
            ["Theme", dash.get("theme")],
            ["Dynamic zone visibility",
             "yes" if dash.get("dynamic_zone_visibility") else ""],
        ])

        objects = dash.get("objects") or []
        if objects:
            lines += _heading(4, f"Zones ({len(objects)})")
            rows = []
            for obj in objects:
                if not isinstance(obj, dict):
                    rows.append([obj]); continue
                rows.append([
                    obj.get("type"),
                    obj.get("worksheet") or obj.get("name"),
                    obj.get("x"), obj.get("y"),
                    obj.get("width"), obj.get("height"),
                ])
            lines += _table(
                ["Zone type", "Worksheet / name", "X", "Y", "Width", "Height"], rows)

        for key, label in (("filters", "Dashboard filters"),
                           ("parameters", "Dashboard parameters")):
            items = dash.get(key) or []
            if not items:
                continue
            lines += _heading(4, label)
            rows = [[i.get("field") or i.get("name"), i.get("type"), i.get("values")]
                    if isinstance(i, dict) else [i, "", ""] for i in items]
            lines += _table(["Field", "Type", "Values"], rows)
    return lines


def _section_queries(custom_sql, datasources, table_extensions):
    """Every query the workbook issues: custom SQL, native SQL, table extensions."""
    lines = _heading(2, "Queries")
    found = False

    if custom_sql:
        found = True
        lines += _heading(3, "Custom SQL")
        for item in custom_sql:
            if isinstance(item, dict):
                title = item.get("name") or item.get("datasource") or "(query)"
                lines += [f"**{_esc(title)}**", ""]
                if item.get("datasource"):
                    lines += [f"Data source: `{_esc(item['datasource'])}`", ""]
                lines += _code_block(item.get("query") or item.get("sql"), "sql")
            else:
                lines += _code_block(item, "sql")

    for ds in datasources or []:
        if not isinstance(ds, dict):
            continue
        conn = ds.get("connection") or {}
        details = conn.get("details") if isinstance(conn, dict) else {}
        sql = None
        if isinstance(details, dict):
            sql = details.get("query") or details.get("custom_sql") or details.get("sql")
        if sql:
            found = True
            lines += _heading(3, f"Native query — {ds.get('caption') or ds.get('name')}")
            lines += _code_block(sql, "sql")

    if table_extensions:
        found = True
        lines += _heading(3, "Table Extensions (script-backed tables)")
        for ext in table_extensions:
            if isinstance(ext, dict):
                lines += [f"**{_esc(ext.get('name') or '(extension)')}**", ""]
                lines += _code_block(ext.get("script") or ext.get("code"))
            else:
                lines += _code_block(ext)

    if not found:
        lines += ["_No custom SQL, native queries or table extensions found. "
                  "All tables are read through the connector directly._", ""]
    return lines


def _section_generic(label, payload, columns=None):
    """Render a list-of-dicts object type without bespoke knowledge of it."""
    lines = _heading(2, label)
    if payload is None:
        return lines + ["_Not extracted._", ""]
    if isinstance(payload, dict):
        rows = [[k, v] for k, v in payload.items()]
        return lines + _table(["Key", "Value"], rows)
    if not payload:
        return lines + ["_None found._", ""]

    keys = columns
    if not keys:
        seen = []
        for item in payload:
            if isinstance(item, dict):
                for k in item:
                    if k not in seen:
                        seen.append(k)
        keys = seen[:8]
    if not keys:
        return lines + _table(["Value"], [[i] for i in payload])

    rows = [[item.get(k) if isinstance(item, dict) else item for k in keys]
            for item in payload]
    return lines + _table([k.replace("_", " ").title() for k in keys], rows)


# ── assembly ────────────────────────────────────────────────────────

def build_extraction_report(extract_dir, workbook_name=None, source_file=None,
                            warnings=None):
    """Return the full Markdown report as a string."""
    data = {key: _load(extract_dir, key) for key, _ in OBJECT_FILES}

    title = workbook_name or "Tableau workbook"
    lines = [f"# Extraction Report — {title}", ""]

    meta = [["Workbook", workbook_name]]
    if source_file:
        meta.append(["Source file", os.path.basename(source_file)])
        meta.append(["Source path", f"`{source_file}`"])
    meta.append(["Extracted", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    meta.append(["Extract directory", f"`{extract_dir}`"])
    lines += _table(["", ""], [m for m in meta if m[1]])

    lines += [
        "This is an inventory of what the extractor found in the Tableau "
        "workbook, written before any Power BI artifact is generated. Use it "
        "to confirm nothing was missed, and to see what will need manual "
        "attention after migration.",
        "",
        "---",
        "",
    ]

    lines += _section_summary(data)
    lines += ["---", ""]
    lines += _section_datasources(data.get("datasources"))
    lines += _section_worksheets(data.get("worksheets"), data.get("datasources"))
    lines += _section_dashboards(data.get("dashboards"))
    lines += _section_calculations(data.get("calculations"))
    lines += _section_parameters(data.get("parameters"))
    lines += _section_queries(data.get("custom_sql"), data.get("datasources"),
                              data.get("table_extensions"))

    lines += _section_generic("Filters (workbook level)", data.get("filters"),
                              ["field", "type", "filter_mode", "exclude", "values"])
    lines += _section_generic("Data Source Filters", data.get("datasource_filters"))
    lines += _section_generic("Sets", data.get("sets"))
    lines += _section_generic("Groups", data.get("groups"))
    lines += _section_generic("Bins", data.get("bins"))
    lines += _section_generic("Hierarchies", data.get("hierarchies"))
    lines += _section_generic("Actions", data.get("actions"),
                              ["name", "type", "command", "source_worksheets",
                               "target_worksheets", "field_mappings"])
    lines += _section_generic("Stories", data.get("stories"))
    lines += _section_generic("Hyper Extracts", data.get("hyper_files"))
    lines += _section_generic("Published Data Sources",
                              data.get("published_datasources"))
    lines += _section_generic("Data Blending", data.get("data_blending"))
    lines += _section_generic("User Filters (RLS)", data.get("user_filters"))
    lines += _section_generic("Custom Geocoding", data.get("custom_geocoding"))
    lines += _section_generic("Sort Orders", data.get("sort_orders"))
    lines += _section_generic("Aliases", data.get("aliases"))
    lines += _section_generic("Linguistic Schema (Q&A synonyms)",
                              data.get("linguistic_schema"))

    if warnings:
        lines += _heading(2, "Extraction Warnings")
        rows = []
        for warn in warnings:
            if isinstance(warn, dict):
                rows.append([warn.get("code"), warn.get("message"),
                             warn.get("context")])
            else:
                rows.append(["", warn, ""])
        lines += _table(["Code", "Message", "Context"], rows)

    lines += ["---", "",
              "_Generated by the Tableau → Power BI migration tool._", ""]
    return "\n".join(lines)


def generate_extraction_report(extract_dir, output_path, workbook_name=None,
                               source_file=None, warnings=None):
    """Write the Markdown extraction report and return its path."""
    markdown = build_extraction_report(
        extract_dir, workbook_name=workbook_name,
        source_file=source_file, warnings=warnings)
    directory = os.path.dirname(os.path.abspath(output_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with io.open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)
    return output_path
