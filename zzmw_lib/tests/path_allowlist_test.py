import os
import tempfile
import unittest
from zzmw_lib.path_allowlist import PathAllowlist


class TestPathAllowlist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.allowed = os.path.join(self.root, 'allowed')
        self.other = os.path.join(self.root, 'other')
        os.makedirs(self.allowed)
        os.makedirs(self.other)

    def tearDown(self):
        self._tmp.cleanup()

    def test_accepts_path_inside(self):
        al = PathAllowlist({'allowed_paths': [self.allowed]}, 'test')
        p = os.path.join(self.allowed, 'sub', 'f.jpg')
        self.assertEqual(al.check(p), p)

    def test_rejects_path_outside_and_logs_error(self):
        al = PathAllowlist({'allowed_paths': [self.allowed]}, 'test')
        with self.assertLogs('PathAllowlist', level='ERROR'):
            self.assertIsNone(al.check(os.path.join(self.other, 'f.jpg')))

    def test_rejects_traversal(self):
        al = PathAllowlist({'allowed_paths': [self.allowed]}, 'test')
        with self.assertLogs('PathAllowlist', level='ERROR'):
            self.assertIsNone(al.check(os.path.join(self.allowed, '..', 'other', 'f.jpg')))

    def test_rejects_sibling_with_same_prefix(self):
        os.makedirs(self.allowed + '_not')
        al = PathAllowlist({'allowed_paths': [self.allowed]}, 'test')
        with self.assertLogs('PathAllowlist', level='ERROR'):
            self.assertIsNone(al.check(os.path.join(self.allowed + '_not', 'f.jpg')))

    def test_rejects_symlink_pointing_out(self):
        target = os.path.join(self.other, 'secret')
        with open(target, 'w') as fp:
            fp.write('x')
        link = os.path.join(self.allowed, 'innocent.jpg')
        os.symlink(target, link)
        al = PathAllowlist({'allowed_paths': [self.allowed]}, 'test')
        with self.assertLogs('PathAllowlist', level='ERROR'):
            self.assertIsNone(al.check(link))

    def test_no_allowed_paths_rejects_everything_and_warns(self):
        with self.assertLogs('PathAllowlist', level='WARNING') as logs:
            al = PathAllowlist({}, 'test')
        self.assertTrue(any('WARNING' in l for l in logs.output))
        with self.assertLogs('PathAllowlist', level='ERROR'):
            self.assertIsNone(al.check(os.path.join(self.allowed, 'f.jpg')))

    def test_rejects_non_string(self):
        al = PathAllowlist({'allowed_paths': [self.allowed]}, 'test')
        for bad in (None, '', 42, ['x']):
            with self.assertLogs('PathAllowlist', level='ERROR'):
                self.assertIsNone(al.check(bad))

    def test_inaccessible_dir_logs_error_at_startup(self):
        missing = os.path.join(self.root, 'not_bound')
        with self.assertLogs('PathAllowlist', level='ERROR') as logs:
            PathAllowlist({'allowed_paths': [self.allowed, missing]}, 'test')
        self.assertEqual(len(logs.output), 1)
        self.assertIn('not_bound', logs.output[0])

    def test_accessible_dirs_log_nothing(self):
        with self.assertNoLogs('PathAllowlist', level='ERROR'):
            PathAllowlist({'allowed_paths': [self.allowed, self.other]}, 'test')

    def test_multiple_dirs(self):
        al = PathAllowlist({'allowed_paths': [self.allowed, self.other]}, 'test')
        p = os.path.join(self.other, 'f.jpg')
        self.assertEqual(al.check(p), p)
