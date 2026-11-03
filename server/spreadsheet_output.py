"""Bounded table outputs for Complex Excel; no model-generated code is executed."""
import json
import math
import re
from . import meta_ai

CELL_SCHEMA = {'anyOf': [{'type': 'string', 'maxLength': 2000}, {'type': 'number'},
                       {'type': 'boolean'}, {'type': 'null'}]}
SCHEMA = {'type': 'object', 'properties': {
    'summary': {'type': 'string', 'maxLength': 4000},
    'columns': {'type': 'array', 'minItems': 1, 'maxItems': 96,
                'items': {'type': 'string', 'minLength': 1, 'maxLength': 200}},
    'rows': {'type': 'array', 'maxItems': 512,
             'items': {'type': 'array', 'minItems': 1, 'maxItems': 96, 'items': CELL_SCHEMA}}},
    'required': ['summary', 'columns', 'rows'], 'additionalProperties': False}

PROMPT = '''Your final answer is a spreadsheet result, not a prose report or Markdown table.
Return one JSON object with exactly these keys:
{"summary":"short explanation of the changes and limitations","columns":["column name",...],"rows":[["value",123,null,...],...]}
The application converts columns/rows into a downloadable CSV and displays the summary separately.
Produce the actual resulting table, including requested calculations and transformations.
Preserve original identifiers, columns and detail rows unless the user explicitly requests their
removal, filtering, replacement or only an aggregate. Add calculated columns to the input rows.
For multiple report sections, use section and row_type columns, with detail/subtotal/grand_total/
exception/recommendation rows as appropriate and blank cells where a field does not apply.
Put every requested subtotal, total and data-supported recommendation IN the table, not only
in summary. Never sum identifiers, unit prices, dates, rates or percentages as if additive;
recalculate ratios from the appropriate totals. Respect the user's rounding and date rules.
Use calculated values, not Excel formulas, scripts, Markdown syntax, code fences or download links.
Do not invent source rows or missing values, claim file creation outside this response, or claim
independent arithmetic verification. If information is missing, explain it in summary and include
an explicit status/issue row instead of invented results. Do not repeat the table in summary.
Maximum 96 unique nonempty columns, 0–512 rows, 2000 characters per cell, 150000 characters overall.
Each row must have exactly as many cells as columns. Cells may be strings, finite numbers,
booleans or null, never nested arrays/objects. Keep JSON compact to fit the output budget.
If an optimization tool is used, the final answer must still follow this JSON contract.'''


class TableOutputError(meta_ai.AIError):
    def __init__(self, reason, **details):
        super().__init__('csv_solution_invalid')
        # Shape diagnostics only, never source values or a fabricated provider call.
        self.validation_detail = {'status': 'invalid', 'reason': reason, **details}


def parse_answer(text):
    if not isinstance(text, str) or len(text) > 150000:
        raise TableOutputError('response_size')
    normalized = []
    fenced = re.fullmatch(r'\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*', text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
        normalized.append('outer_json_fence_removed')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TableOutputError('duplicate_json_key')
            result[key] = value
        return result

    def nonfinite(_):
        raise TableOutputError('nonfinite_number')

    try:
        obj = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    except TableOutputError:
        raise
    except (ValueError, TypeError, RecursionError):
        raise TableOutputError('invalid_json') from None
    if not isinstance(obj, dict) or set(obj) != {'summary', 'columns', 'rows'}:
        raise TableOutputError('result_fields')
    summary, columns, rows = obj['summary'], obj['columns'], obj['rows']
    if not isinstance(summary, str) or len(summary) > 4000:
        raise TableOutputError('summary_size')
    if not isinstance(columns, list) or not 1 <= len(columns) <= 96:
        raise TableOutputError('column_count')
    if any(not isinstance(c, str) or not c.strip() or len(c) > 200 or any(ord(ch) < 32 for ch in c) for c in columns):
        raise TableOutputError('column_name')
    if len(set(c.strip().casefold() for c in columns)) != len(columns):
        raise TableOutputError('duplicate_column')
    if not isinstance(rows, list) or len(rows) > 512:
        raise TableOutputError('row_count')
    for i, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(columns):
            raise TableOutputError('row_width', row=i, expected_cells=len(columns),
                                   actual_cells=len(row) if isinstance(row, list) else None)
        for j, cell in enumerate(row, 1):
            if cell is not None and not isinstance(cell, (str, bool, int, float)):
                raise TableOutputError('cell_type', row=i, column=j)
            if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                try:
                    finite = math.isfinite(cell)
                except OverflowError:
                    finite = False
                if not finite:
                    raise TableOutputError('nonfinite_number', row=i, column=j)
            if isinstance(cell, str) and (len(cell) > 2000 or any(ord(ch) < 32 and ch not in '\t\r\n' for ch in cell)):
                raise TableOutputError('cell_text', row=i, column=j)
    return summary, {'columns': columns, 'rows': rows, 'structure_validated': True,
                     'normalizations': normalized, 'content_verified': False, 'source': 'model_generated'}


def numerical_table(dataset, plan):
    """Append verified decisions without dropping or changing any uploaded cell."""
    columns = list(dataset['headers'])
    for title in ('solution_decision', 'solution_metric', 'solution_value', 'constraints_satisfied'):
        name = title
        while name in columns:
            name = '_' + name
        columns.append(name)
    decisions = {r['id']: r['decision'] for r in plan['rows']}
    rows = [[row[h] for h in dataset['headers']] + [decisions[row['id']], plan['metric'],
             plan['display_value'], plan['feasible']] for row in dataset['rows']]
    return {'columns': columns, 'rows': rows, 'structure_validated': True,
            'content_verified': True, 'verification_scope': 'Original input cells and checked solver decisions; interpretation is not independently verified.',
            'source': 'verified_solver_decisions'}
