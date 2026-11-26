"""Tests for the Markdown extraction report and the fixes shipped with it."""

import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tableau_export'))

from extraction_report import (  # noqa: E402
    build_extraction_report, generate_extraction_report,
    _esc, _table, _classify_calc, _datasource_captions, _friendly_ds,
)


def _write_extract(tmpdir, payloads):
    for name, payload in payloads.items():
        with io.open(os.path.join(tmpdir, f'{name}.json'), 'w',
                     encoding='utf-8') as handle:
            json.dump(payload, handle)


SAMPLE = {
    'datasources': [{
        'name': 'federated.abc123',
        'caption': 'Orders (Excel)',
        'connection': {'type': 'Excel',
                       'details': {'filename': 'C:/data/Orders.xlsx'}},
        'tables': [{'name': 'Orders', 'type': 'table'}],
        'relationships': [{'left_table': 'Orders', 'right_table': 'Returns',
                           'join_type': 'inner', 'condition': 'Order ID'}],
        'columns': [
            {'name': '[Sales]', 'caption': 'Sales', 'datatype': 'real',
             'role': 'measure', 'type': 'quantitative', 'hidden': False},
            {'name': '[Region]', 'caption': 'Region', 'datatype': 'string',
             'role': 'dimension', 'type': 'nominal', 'hidden': False},
        ],
    }],
    'worksheets': [{
        'name': 'Sales by Region',
        'title': 'Regional Sales',
        'chart_type': 'clusteredBarChart',
        'original_mark_class': 'Bar',
        'fields': [{'name': 'Region', 'shelf': 'columns',
                    'datasource': 'federated.abc123.Orders'}],
        'filters': [{'field': 'Region', 'type': 'categorical',
                     'exclude': False, 'values': ['East']}],
        'axes': {'dual_axis': False},
    }],
    'dashboards': [{
        'name': 'Overview', 'title': 'Sales Overview',
        'size': {'width': 1200, 'height': 800},
        'objects': [{'type': 'worksheet', 'worksheet': 'Sales by Region',
                     'x': 0, 'y': 0, 'width': 600, 'height': 400}],
    }],
    'calculations': [
        {'name': 'Calculation_1', 'caption': 'Profit Ratio',
         'datasource_name': 'Orders (Excel)', 'datatype': 'real',
         'role': 'measure', 'formula': 'SUM([Profit]) / SUM([Sales])'},
        {'name': 'Calculation_2', 'caption': 'Customer Sales',
         'datasource_name': 'Orders (Excel)', 'datatype': 'real',
         'role': 'measure', 'formula': '{FIXED [Customer ID] : SUM([Sales])}'},
    ],
    'parameters': [{'name': 'Top N', 'datatype': 'integer',
                    'current_value': 10}],
    'custom_sql': [{'name': 'Orders query', 'datasource': 'Orders (Excel)',
                    'query': 'SELECT * FROM orders WHERE region = ?'}],
    'filters': [], 'stories': [], 'actions': [], 'sets': [], 'groups': [],
    'bins': [], 'hierarchies': [], 'user_filters': [], 'sort_orders': [],
    'aliases': {}, 'hyper_files': [], 'published_datasources': [],
    'data_blending': [], 'datasource_filters': [], 'table_extensions': [],
    'custom_geocoding': [], 'linguistic_schema': {},
}


class TestMarkdownHelpers(unittest.TestCase):

    def test_pipe_is_escaped(self):
        self.assertEqual(_esc('a|b'), 'a\\|b')

    def test_backslashes_survive_unchanged(self):
        # A Windows path must stay readable; doubling backslashes mangles it.
        self.assertEqual(_esc(r'C:\Users\data.xlsx'), r'C:\Users\data.xlsx')

    def test_newlines_collapse_to_spaces(self):
        self.assertNotIn('\n', _esc('line one\nline two'))

    def test_empty_table_renders_placeholder(self):
        self.assertIn('_None found._', _table(['A'], []))

    def test_short_row_is_padded(self):
        rendered = '\n'.join(_table(['A', 'B', 'C'], [['only']]))
        self.assertIn('| only |  |  |', rendered)


class TestCalcClassification(unittest.TestCase):

    def test_fixed_lod(self):
        self.assertIn('LOD:FIXED', _classify_calc('{FIXED [A] : SUM([X])}'))

    def test_include_lod(self):
        self.assertIn('LOD:INCLUDE', _classify_calc('{INCLUDE [A] : AVG([X])}'))

    def test_table_calc(self):
        self.assertIn('table calc', _classify_calc('RUNNING_SUM(SUM([Sales]))'))

    def test_regex(self):
        self.assertIn('regex', _classify_calc('REGEXP_MATCH([A], "x")'))

    def test_plain_formula(self):
        self.assertEqual(_classify_calc('SUM([Sales])'), 'standard')

    def test_empty_formula(self):
        self.assertEqual(_classify_calc(''), '—')


class TestDatasourceCaptions(unittest.TestCase):

    def test_internal_id_resolves_to_caption(self):
        captions = _datasource_captions(SAMPLE['datasources'])
        self.assertEqual(_friendly_ds('federated.abc123', captions),
                         'Orders (Excel)')

    def test_qualified_reference_resolves(self):
        captions = _datasource_captions(SAMPLE['datasources'])
        self.assertEqual(_friendly_ds('federated.abc123.Orders', captions),
                         'Orders (Excel)')

    def test_unknown_reference_passes_through(self):
        self.assertEqual(_friendly_ds('something-else', {}), 'something-else')


class TestReportBuild(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _write_extract(self.tmp, SAMPLE)
        self.md = build_extraction_report(self.tmp, workbook_name='Demo')

    def test_every_object_type_has_a_section(self):
        for heading in ('## Data Sources', '## Worksheets (Visuals)',
                        '## Dashboards', '## Calculated Fields',
                        '## Parameters', '## Queries', '## Contents'):
            self.assertIn(heading, self.md)

    def test_columns_are_listed(self):
        self.assertIn('| Sales |', self.md)
        self.assertIn('| Region |', self.md)

    def test_worksheet_and_visual_mapping_shown(self):
        self.assertIn('Sales by Region', self.md)
        self.assertIn('clusteredBarChart', self.md)

    def test_formula_is_reproduced_verbatim(self):
        self.assertIn('SUM([Profit]) / SUM([Sales])', self.md)
        self.assertIn('{FIXED [Customer ID] : SUM([Sales])}', self.md)

    def test_custom_sql_is_included(self):
        self.assertIn('SELECT * FROM orders WHERE region = ?', self.md)

    def test_join_is_described(self):
        self.assertIn('Returns', self.md)
        self.assertIn('inner', self.md)

    def test_worksheet_datasource_shown_as_caption(self):
        self.assertNotIn('federated.abc123.Orders', self.md)

    def test_counts_appear_in_contents(self):
        self.assertIn('| Data Sources | 1 |', self.md)
        self.assertIn('| Calculated Fields | 2 |', self.md)

    def test_warnings_section_when_supplied(self):
        md = build_extraction_report(
            self.tmp, workbook_name='Demo',
            warnings=[{'code': 'W1', 'message': 'something odd',
                       'context': 'sheet 2'}])
        self.assertIn('## Extraction Warnings', md)
        self.assertIn('something odd', md)

    def test_no_warnings_section_when_none(self):
        self.assertNotIn('## Extraction Warnings', self.md)


class TestReportRobustness(unittest.TestCase):

    def test_empty_extract_dir_still_produces_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = build_extraction_report(tmp, workbook_name='Empty')
            self.assertIn('# Extraction Report — Empty', md)
            self.assertIn('not extracted', md)

    def test_malformed_json_is_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            with io.open(os.path.join(tmp, 'worksheets.json'), 'w',
                         encoding='utf-8') as handle:
                handle.write('{ not json')
            md = build_extraction_report(tmp, workbook_name='Broken')
            self.assertIn('# Extraction Report', md)

    def test_unexpected_shapes_do_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_extract(tmp, {'worksheets': ['a string, not a dict'],
                                 'datasources': [42],
                                 'calculations': [None]})
            md = build_extraction_report(tmp, workbook_name='Odd')
            self.assertIn('# Extraction Report', md)

    def test_pipe_in_field_name_does_not_break_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_extract(tmp, {'datasources': [{
                'name': 'ds', 'caption': 'DS',
                'columns': [{'name': '[A|B]', 'caption': 'A|B',
                             'datatype': 'string'}],
            }]})
            md = build_extraction_report(tmp, workbook_name='Pipes')
            self.assertIn('A\\|B', md)

    def test_file_is_written_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_extract(tmp, SAMPLE)
            out = os.path.join(tmp, 'nested', 'EXTRACTION_REPORT.md')
            returned = generate_extraction_report(tmp, out, workbook_name='Demo')
            self.assertEqual(returned, out)
            self.assertTrue(os.path.isfile(out))
            with io.open(out, encoding='utf-8') as handle:
                self.assertIn('# Extraction Report — Demo', handle.read())


if __name__ == '__main__':
    unittest.main()
