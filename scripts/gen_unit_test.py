"""Tests for gen_unit.py: python3 scripts/gen_unit_test.py (or make test in the ZMW root)"""
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from gen_unit import generate  # noqa: E402 pylint: disable=wrong-import-position


class TestGenUnit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self._tmp.name)
        self.nvr = os.path.join(root, 'nvr')
        self.args = types.SimpleNamespace(name='zmw_svc', src=os.path.join(root, 'zmw', 'zmw_svc'),
                                          run=os.path.join(root, 'run', 'zmw_svc'), user='batman',
                                          exec_start='python3 svc.py', svc_tmp=os.path.join(root, 'run', 'tmp'))
        for d in (self.args.src, os.path.join(root, 'zmw', 'zzmw_lib'), self.nvr):
            os.makedirs(d)
        self._write('Pipfile', 'zzmw-lib = {path = "../zzmw_lib", editable = true}\n')

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, text):
        with open(os.path.join(self.args.src, name), 'w', encoding='utf-8') as fp:
            fp.write(text)

    def _gen(self, cfg, conf):
        self._write('systemd.conf', conf)
        return generate(self.args, cfg)

    def test_template_and_source_libs(self):
        unit = generate(self.args, {})
        self.assertIn(f"BindReadOnlyPaths={self.args.src} {os.path.dirname(self.args.src)}/zzmw_lib\n", unit)
        self.assertNotRegex(unit, r'@[A-Z_]+@')

    def test_binds_cfg_paths_and_skips_visible_ones(self):
        cfg = {'rec': self.nvr, 'allowed': [self.args.svc_tmp, './models']}
        unit = self._gen(cfg, '[Service]\nBindPaths=@CFG:rec@\nBindReadOnlyPaths=@CFG:allowed@\n')
        self.assertIn(f"\nBindPaths={self.nvr}\n", unit)
        self.assertIn("# BindReadOnlyPaths=@CFG:allowed@ (nothing to bind)", unit)

    def test_missing_key(self):
        with self.assertRaisesRegex(SystemExit, "'rec', which isn't set"):
            self._gen({}, '[Service]\nBindPaths=@CFG:rec@\n')

    def test_missing_path(self):
        with self.assertRaisesRegex(SystemExit, "doesn't exist"):
            self._gen({'rec': '/nonexistent'}, '[Service]\nBindPaths=@CFG:rec@\n')

    def test_null_value_binds_nothing(self):
        unit = self._gen({'rec': None}, '[Service]\nBindPaths=@CFG:rec@\n')
        self.assertIn('(nothing to bind)', unit)


if __name__ == '__main__':
    unittest.main()
