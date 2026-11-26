"""Tests for the Windows MAX_PATH guard and the INCLUDE LOD conversion."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tableau_export'))

from powerbi_import import longpath  # noqa: E402
from dax_converter import convert_tableau_formula_to_dax  # noqa: E402

IS_WINDOWS = sys.platform == 'win32'


class TestLpNormalisation(unittest.TestCase):

    def test_short_path_is_untouched(self):
        self.assertEqual(longpath.lp(r'C:\pbi\out'), r'C:\pbi\out')

    def test_empty_and_none_pass_through(self):
        self.assertEqual(longpath.lp(''), '')
        self.assertIsNone(longpath.lp(None))

    @unittest.skipUnless(IS_WINDOWS, 'extended-length prefix is Windows-only')
    def test_long_path_gets_prefix(self):
        long = 'C:\\' + '\\'.join('segment%02d' % i for i in range(30))
        self.assertTrue(longpath.lp(long).startswith('\\\\?\\'))

    @unittest.skipUnless(IS_WINDOWS, 'extended-length prefix is Windows-only')
    def test_prefix_is_not_applied_twice(self):
        long = 'C:\\' + '\\'.join('segment%02d' % i for i in range(30))
        once = longpath.lp(long)
        self.assertEqual(longpath.lp(once), once)

    @unittest.skipUnless(IS_WINDOWS, 'extended-length prefix is Windows-only')
    def test_strip_reverses_prefix(self):
        long = 'C:\\' + '\\'.join('segment%02d' % i for i in range(30))
        self.assertEqual(longpath.strip_lp(longpath.lp(long)),
                         os.path.abspath(long))

    def test_strip_leaves_plain_paths_alone(self):
        self.assertEqual(longpath.strip_lp(r'C:\pbi'), r'C:\pbi')


class TestAtRisk(unittest.TestCase):

    def test_short_path_is_not_at_risk(self):
        self.assertFalse(longpath.at_risk(r'C:\pbi'))

    @unittest.skipUnless(IS_WINDOWS, 'MAX_PATH is a Windows limit')
    def test_deep_path_is_at_risk(self):
        deep = 'C:\\' + '\\'.join('segment%02d' % i for i in range(30))
        self.assertTrue(longpath.at_risk(deep))

    def test_none_is_not_at_risk(self):
        self.assertFalse(longpath.at_risk(None))


class TestDeepRoundTrip(unittest.TestCase):
    """Create, write, list and read back a file past MAX_PATH."""

    @unittest.skipUnless(IS_WINDOWS, 'MAX_PATH is a Windows limit')
    def test_write_and_read_beyond_max_path(self):
        tmp = tempfile.mkdtemp()
        # Tear down with the long-path rmtree: stdlib shutil.rmtree cannot
        # delete this tree, which is the limitation under test.
        self.addCleanup(longpath.rmtree, tmp, True)

        deep = os.path.join(tmp, *['a_fairly_long_directory_name'] * 9)
        self.assertGreater(len(deep), longpath.MAX_PATH)

        longpath.makedirs(deep, exist_ok=True)
        self.assertTrue(longpath.isdir(deep))

        target = os.path.join(deep, 'visual.json')
        with longpath.lp_open(target, 'w', encoding='utf-8') as handle:
            handle.write('{"ok": true}')

        self.assertTrue(longpath.isfile(target))
        self.assertIn('visual.json', longpath.listdir(deep))
        with longpath.lp_open(target, encoding='utf-8') as handle:
            self.assertEqual(handle.read(), '{"ok": true}')

        hits = longpath.lp_glob(os.path.join(deep, '*.json'))
        self.assertEqual(len(hits), 1)
        self.assertFalse(hits[0].startswith('\\\\?\\'),
                         'glob results should come back unprefixed')

        roots = [root for root, _, files in longpath.walk(deep) if files]
        self.assertTrue(roots)
        self.assertFalse(roots[0].startswith('\\\\?\\'),
                         'walk roots should come back unprefixed')


class TestIncludeLod(unittest.TestCase):
    """INCLUDE must preserve the extra grain, not silently drop it."""

    def _convert(self, formula):
        return convert_tableau_formula_to_dax(
            formula, column_name='M', table_name='Sales')

    def test_include_sum_materialises_the_grain(self):
        dax = self._convert('{INCLUDE [City] : SUM([Sales])}')
        self.assertIn('SUMX', dax)
        self.assertIn("SUMMARIZE('Sales', 'Sales'[City])", dax)

    def test_include_average_uses_averagex(self):
        # The case that was wrong before: averaging rows, not group averages.
        dax = self._convert('{INCLUDE [Product ID] : AVG([Sales])}')
        self.assertIn('AVERAGEX', dax)
        self.assertIn("SUMMARIZE('Sales', 'Sales'[Product ID])", dax)

    def test_include_min_uses_minx(self):
        self.assertIn('MINX', self._convert('{INCLUDE [City] : MIN([Sales])}'))

    def test_include_countd_is_additive(self):
        dax = self._convert('{INCLUDE [Order Date] : COUNTD([Customer ID])}')
        self.assertIn('SUMX', dax)
        self.assertIn('DISTINCTCOUNT', dax)

    def test_fixed_is_unchanged(self):
        dax = self._convert('{FIXED [Customer ID] : SUM([Sales])}')
        self.assertIn('ALLEXCEPT', dax)
        self.assertNotIn('SUMMARIZE', dax)

    def test_exclude_is_unchanged(self):
        dax = self._convert('{EXCLUDE [State] : SUM([Sales])}')
        self.assertIn('REMOVEFILTERS', dax)
        self.assertNotIn('SUMMARIZE', dax)

    def test_grand_total_is_unchanged(self):
        self.assertIn('ALL(', self._convert('{FIXED : SUM([Sales])}'))

    def test_nested_include_inside_fixed(self):
        dax = self._convert('{FIXED [A] : {INCLUDE [B] : SUM([Sales])}}')
        self.assertIn('ALLEXCEPT', dax)
        self.assertIn('SUMMARIZE', dax)


if __name__ == '__main__':
    unittest.main()
