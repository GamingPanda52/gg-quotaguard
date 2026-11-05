"""Isolated safety tests. Linux-only integration cases explicitly skip elsewhere."""
import concurrent.futures
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gg_quotaguard', ROOT / 'gg_quotaguard.py')
qg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qg)
LINUX_ACCOUNTING = os.name == 'posix' and hasattr(os, 'statvfs')


def quota_row(device='/dev/test', used=10, soft=100, hard=200,
              files=1, fsoft=0, fhard=0):
    return f'{device} {used} {soft} {hard} 0 {files} {fsoft} {fhard} 0\n'


def snapshot(available=1000):
    return dict(method='quota', used_bytes=0, limit_bytes=available,
                account_free_bytes=available, filesystem_free_bytes=available,
                available_bytes=available, entries=None)


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-quotaguard-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / 'downloads'
        self.target.mkdir()
        self.cfgfile = self.root / 'config.json'
        self.config = dict(mode='quota', target=str(self.target),
                           quota_device='/dev/test', reserve_bytes=100,
                           scope_confirmed=True, startup_pending_confirmed=True,
                           state_dir=str(self.root / 'state'),
                           scan_timeout_seconds=10, max_entries=1000)

    def save(self, config=None):
        self.cfgfile.write_text(json.dumps(self.config if config is None else config), encoding='utf-8')
        return str(self.cfgfile)

    def initialize(self):
        with qg.ledger(self.config, initialize=True):
            pass

    def invoke(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = qg.main(list(args))
        return code, json.loads(out.getvalue())


class IntegerTests(unittest.TestCase):
    def test_positive_bytes(self):
        self.assertEqual(qg.integer('123456789', 'size', 1), 123456789)

    def test_maximum_supported_bytes(self):
        self.assertEqual(qg.integer(str(qg.MAX_BYTES), 'size', 1), qg.MAX_BYTES)

    def test_unknown_negative_decimal_or_overflow_rejected(self):
        for bad in ['', '0', '-1', '1.5', '1 GB', 'NaN', 'None', True,
                    str(qg.MAX_BYTES + 1), '1e6', ' 10', '10\n']:
            with self.subTest(bad=bad), self.assertRaises(qg.Block):
                qg.integer(bad, 'size', 1)

    def test_request_ids_are_hashed_and_control_characters_rejected(self):
        self.assertEqual(len(qg.request_hash('private-release-name')), 64)
        self.assertNotIn('private', qg.request_hash('private-release-name'))
        for bad in ['', 'x' * 257, 'secret\nname', 'secret\x00name', None]:
            with self.subTest(bad=bad), self.assertRaises(qg.Block):
                qg.request_hash(bad)


class ConfigTests(Workspace):
    def test_valid_config(self):
        self.assertEqual(qg.load_config(self.save())['reserve_bytes'], 100)

    def test_unknown_keys_and_filesystem_only_mode_rejected(self):
        for change in [{'fail_closed': False}, {'mode': 'df'}, {'mode': 'auto'}]:
            c = dict(self.config, **change)
            with self.subTest(change=change), self.assertRaises(qg.Block):
                qg.load_config(self.save(c))

    def test_explicit_scope_and_pending_confirmation_required(self):
        for key in ['scope_confirmed', 'startup_pending_confirmed']:
            for value in [False, 'true', 1, None]:
                with self.subTest(key=key, value=value), self.assertRaises(qg.Block):
                    qg.load_config(self.save(dict(self.config, **{key: value})))

    def test_invalid_quotas_paths_and_limits(self):
        changes = [{'target': 'relative'}, {'state_dir': 'relative'},
                   {'reserve_bytes': 0}, {'reserve_bytes': -1},
                   {'quota_device': 'tmpfs'}, {'quota_device': '/dev/test;true'},
                   {'scan_timeout_seconds': 61}, {'max_entries': 0}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(qg.Block):
                qg.load_config(self.save(dict(self.config, **change)))

    def test_manual_directory_quota_requires_paths_and_positive_limit(self):
        c = dict(self.config, mode='directory', directories=[str(self.target)], quota_bytes=1000)
        self.assertEqual(qg.load_config(self.save(c))['quota_bytes'], 1000)
        for change in [{'quota_bytes': 0}, {'quota_bytes': '1 TB'},
                       {'directories': []}, {'directories': ['relative']}]:
            with self.subTest(change=change), self.assertRaises(qg.Block):
                qg.load_config(self.save(dict(c, **change)))

    def test_missing_or_malformed_json_rejected(self):
        with self.assertRaises(qg.Block):
            qg.load_config(self.cfgfile)
        for text in ['{', '[]', 'null', '"private data"']:
            self.cfgfile.write_text(text, encoding='utf-8')
            with self.subTest(text=text), self.assertRaises(qg.Block):
                qg.load_config(self.cfgfile)

    def test_duplicate_json_keys_rejected(self):
        # json.loads silently keeps the last duplicate; an ambiguous file must not change meaning.
        base = json.dumps(self.config)
        self.cfgfile.write_text(base[:-1] + ', "reserve_bytes": 1000000}', encoding='utf-8')
        with self.assertRaises(qg.Block):
            qg.load_config(self.cfgfile)


class QuotaTests(unittest.TestCase):
    def test_unscaled_kib_and_stricter_soft_limit(self):
        self.assertEqual(qg.parse_quota(quota_row(), '/dev/test'), (10240, 102400))

    def test_hard_limit_used_when_soft_unlimited(self):
        self.assertEqual(qg.parse_quota(quota_row(soft=0), '/dev/test'), (10240, 204800))

    def test_soft_limit_used_when_hard_unlimited(self):
        self.assertEqual(qg.parse_quota(quota_row(hard=0), '/dev/test'), (10240, 102400))

    def test_exact_device_chosen_in_multiple_filesystem_report(self):
        text = 'Disk quotas for user REDACTED\n' + quota_row('/dev/other', used=1) + quota_row(used=55)
        self.assertEqual(qg.parse_quota(text, '/dev/test'), (55 * 1024, 100 * 1024))

    def test_overquota_markers_supported(self):
        self.assertEqual(qg.parse_quota(quota_row(used='101*'), '/dev/test'), (101 * 1024, 100 * 1024))

    def test_ambiguous_missing_human_units_wrapped_and_bad_rows_rejected(self):
        texts = ['', quota_row('/dev/other'), quota_row() * 2,
                 '/dev/test 1.5T 2T 2T 0 1 0 0 0\n',
                 '/dev/test\n 10 100 100 0 1 0 0 0\n',
                 '/dev/test 10 100 100 1 0 0\n',
                 quota_row(soft=0, hard=0), quota_row(used='-1')]
        for text in texts:
            with self.subTest(text=text), self.assertRaises(qg.Block):
                qg.parse_quota(text, '/dev/test')

    def test_exhausted_inode_quota_rejected(self):
        for kw in [dict(files=20, fsoft=20), dict(files=20, fhard=19)]:
            with self.subTest(kw=kw), self.assertRaises(qg.Block):
                qg.parse_quota(quota_row(**kw), '/dev/test')

    def test_quota_multiplication_overflow_rejected(self):
        with self.assertRaises(qg.Block):
            qg.parse_quota(quota_row(hard=qg.MAX_BYTES, soft=0), '/dev/test')

    def test_markers_in_limit_columns_or_repeated_markers_rejected(self):
        for text in [quota_row(used='10**'), quota_row(soft='100*'),
                     quota_row(hard='200*'), quota_row(fsoft='20*')]:
            with self.subTest(text=text), self.assertRaises(qg.Block):
                qg.parse_quota(text, '/dev/test')


class CommandTests(unittest.TestCase):
    def test_failed_stderr_missing_and_timedout_command_rejected(self):
        bad_results = [types.SimpleNamespace(returncode=1, stdout='huge free space', stderr=''),
                       types.SimpleNamespace(returncode=0, stdout='partial', stderr='permission denied')]
        for result in bad_results:
            with self.subTest(result=result), mock.patch.object(qg.subprocess, 'run', return_value=result), self.assertRaises(qg.Block):
                qg.run(['quota'])
        for exc in [FileNotFoundError(), subprocess.TimeoutExpired('quota', 1)]:
            with self.subTest(exc=exc), mock.patch.object(qg.subprocess, 'run', side_effect=exc), self.assertRaises(qg.Block):
                qg.run(['quota'])

    def test_stable_locale_requested(self):
        with mock.patch.object(qg.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout='ok', stderr='')) as runner:
            self.assertEqual(qg.run(['quota']), 'ok')
        self.assertEqual(runner.call_args.kwargs['env']['LC_ALL'], 'C')


class MeasurementTests(Workspace):
    def fs(self, free=1000000, readonly=False, inodes=100):
        return types.SimpleNamespace(f_flag=1 if readonly else 0, f_bavail=free,
                                     f_frsize=1, f_files=100, f_favail=inodes)

    def measurement(self, fs=None, outputs=None):
        with mock.patch.object(qg.os, 'statvfs', return_value=fs or self.fs(), create=True), \
             mock.patch.object(qg.os, 'getuid', return_value=1000, create=True), \
             mock.patch.object(qg, 'run', side_effect=outputs or ['/dev/test[/account]\n', quota_row()]):
            return qg.measure(self.config)

    def test_capacity_is_minimum_of_account_quota_and_filesystem(self):
        self.assertEqual(self.measurement()['available_bytes'], 90 * 1024)
        self.assertEqual(self.measurement(fs=self.fs(free=1000))['available_bytes'], 1000)

    def test_overquota_has_zero_available(self):
        self.assertEqual(self.measurement(outputs=['/dev/test', quota_row(used=300)])['available_bytes'], 0)

    def test_readonly_or_inode_exhausted_fs_rejected(self):
        for fs in [self.fs(readonly=True), self.fs(inodes=0)]:
            with self.subTest(fs=fs), self.assertRaises(qg.Block):
                self.measurement(fs=fs)

    def test_wrong_device_or_quota_failure_never_falls_back_to_df(self):
        for outputs in [['/dev/wrong', quota_row()], ['/dev/test', qg.Block('quota denied')]]:
            with self.subTest(outputs=outputs), self.assertRaises(qg.Block):
                self.measurement(outputs=outputs)

    def test_missing_target_or_denied_target_rejected(self):
        self.config['target'] = str(self.root / 'missing')
        with self.assertRaises(qg.Block):
            qg.verified_target(self.config)
        self.config['target'] = str(self.target)
        with mock.patch.object(qg.os, 'access', return_value=False), self.assertRaises(qg.Block):
            qg.verified_target(self.config)


class LedgerTests(Workspace):
    def check(self, size='500', request_id='one', available=1000):
        with mock.patch.object(qg, 'measure', side_effect=lambda _: snapshot(available)):
            return qg.check(self.config, size, request_id)

    def pending(self):
        with qg.ledger(self.config) as db:
            return db.execute('SELECT COALESCE(SUM(bytes),0) FROM reservations').fetchone()[0]

    def test_initialization_creates_private_state_and_refuses_overwrite(self):
        self.initialize()
        self.assertEqual(self.pending(), 0)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(Path(self.config['state_dir']).stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((Path(self.config['state_dir']) / 'reservations.sqlite3').stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            self.initialize()

    def test_missing_ledger_does_not_reinitialize_on_check(self):
        code, result = self.invoke('check', '--config', self.save(), '--size', '100', '--request-id', 'x')
        self.assertEqual(code, 2)
        self.assertEqual(result['decision'], 'reject')
        self.assertFalse(Path(self.config['state_dir']).exists())

    def test_accept_reserves_and_second_request_cannot_spend_same_bytes(self):
        self.initialize()
        self.assertEqual(self.check()[1], 0)
        result, code = self.check(request_id='two')
        self.assertEqual(code, 1)
        self.assertEqual(result['pending_bytes'], 500)
        self.assertEqual(self.pending(), 500)

    def test_safety_reserve_exact_boundary(self):
        self.initialize()
        self.assertEqual(self.check(size='900')[1], 0)
        self.assertEqual(self.pending(), 900)

    def test_nearly_full_and_large_incoming_reject_without_reservation(self):
        self.initialize()
        for size, free in [('901', 1000), ('1', 100), (str(qg.MAX_BYTES), 1000000)]:
            with self.subTest(size=size, free=free):
                self.assertEqual(self.check(size=size, available=free)[1], 1)
                self.assertEqual(self.pending(), 0)

    def test_invalid_or_unknown_sizes_cannot_approve(self):
        self.initialize()
        for size in ['0', '-1', '', '{{ .Size }}', '10.5', str(qg.MAX_BYTES + 1)]:
            with self.subTest(size=size), self.assertRaises(qg.Block):
                self.check(size=size)
        self.assertEqual(self.pending(), 0)

    def test_duplicate_request_is_rejected_without_second_approval(self):
        self.initialize()
        self.check()
        with self.assertRaises(qg.Block):
            self.check()
        self.assertEqual(self.pending(), 500)

    def test_missing_request_id_generates_distinct_durable_reservations(self):
        self.initialize()
        args = ['check', '--config', self.save(), '--size', '100']
        with mock.patch.object(qg, 'measure', side_effect=lambda _: snapshot()):
            first_code, first = self.invoke(*args)
            second_code, second = self.invoke(*args)
        self.assertEqual(first_code, 0, first)
        self.assertEqual(second_code, 0, second)
        self.assertNotEqual(first['reservation'], second['reservation'])
        self.assertEqual(len(first['reservation']), 64)
        self.assertEqual(self.pending(), 200)

    def test_zero_size_via_cli_rejected_before_measurement(self):
        self.initialize()
        with mock.patch.object(qg, 'measure', return_value=snapshot()) as measurement:
            code, result = self.invoke('check', '--config', self.save(), '--size', '0')
            self.assertEqual(code, 2, result)
            self.assertEqual(result['decision'], 'reject')
            measurement.assert_not_called()
        self.assertEqual(self.pending(), 0)

    def test_explicit_empty_request_id_rejected_instead_of_replaced(self):
        self.initialize()
        with mock.patch.object(qg, 'measure', return_value=snapshot()) as measurement:
            code, result = self.invoke('check', '--config', self.save(), '--size', '1', '--request-id', '')
            self.assertEqual(code, 2, result)
            measurement.assert_not_called()
        self.assertEqual(self.pending(), 0)

    def test_duplicate_cli_options_rejected_before_config_or_state_access(self):
        bases = {
            '--config': ['check', '--size', '1'],
            '--size': ['check', '--config', str(self.cfgfile)],
            '--request-id': ['check', '--config', str(self.cfgfile), '--size', '1'],
            '--reservation': ['release', '--config', str(self.cfgfile), '--confirmed-accounted-or-cancelled'],
            '--target': ['diagnose'],
        }
        for option, base in bases.items():
            forms = [[option, 'first', option, 'second'],
                     [option + '=first', option + '=second'],
                     [option, 'first', option + '=second']]
            for form in forms:
                with self.subTest(option=option, form=form), \
                     mock.patch.object(qg, 'load_config') as config_loader, \
                     mock.patch.object(qg, 'measure') as measurement, \
                     mock.patch.object(qg, 'diagnose') as diagnostic:
                    code, result = self.invoke(*(base + form))
                    self.assertEqual(code, 2, result)
                    self.assertEqual(result['decision'], 'reject')
                    config_loader.assert_not_called()
                    measurement.assert_not_called()
                    diagnostic.assert_not_called()
        self.assertFalse(Path(self.config['state_dir']).exists())

    def test_abbreviated_cli_options_cannot_bypass_duplicate_checks(self):
        config = self.save()
        cases = [
            ['check', '--config', config, '--size', '999', '--siz', '1'],
            ['check', '--conf', config, '--size', '1'],
            ['check', '--config', config, '--size', '1', '--request-i', 'attempt'],
            ['release', '--config', config, '--reserv', 'a' * 64, '--confirmed-accounted-or-cancelled'],
            ['diagnose', '--targ', str(self.target)],
        ]
        for argv in cases:
            with self.subTest(argv=argv), \
                 mock.patch.object(qg, 'load_config') as config_loader, \
                 mock.patch.object(qg, 'measure') as measurement, \
                 mock.patch.object(qg, 'diagnose') as diagnostic, \
                 contextlib.redirect_stderr(io.StringIO()) as errors, \
                 self.assertRaises(SystemExit) as stopped:
                qg.main(argv)
            self.assertEqual(stopped.exception.code, 2)
            self.assertTrue(errors.getvalue())
            config_loader.assert_not_called()
            measurement.assert_not_called()
            diagnostic.assert_not_called()
        self.assertFalse(Path(self.config['state_dir']).exists())

    def test_unexpected_exception_is_reported_as_reject_without_traceback(self):
        self.initialize()
        with mock.patch.object(qg.secrets, 'token_hex', side_effect=NotImplementedError('no entropy source')), \
             mock.patch.object(qg, 'measure', return_value=snapshot()):
            code, result = self.invoke('check', '--config', self.save(), '--size', '1')
        self.assertEqual(code, 2)
        self.assertEqual(result['decision'], 'reject')
        self.assertEqual(self.pending(), 0)

    def test_storage_failure_rolls_back_reservation(self):
        self.initialize()
        with mock.patch.object(qg, 'measure', side_effect=qg.Block('unreadable quota')), self.assertRaises(qg.Block):
            qg.check(self.config, '500', 'one')
        self.assertEqual(self.pending(), 0)

    def test_changed_config_and_corrupt_ledger_fail_closed(self):
        self.initialize()
        self.config['reserve_bytes'] += 1
        with self.assertRaises(qg.Block):
            self.check()
        self.config['reserve_bytes'] -= 1
        (Path(self.config['state_dir']) / 'reservations.sqlite3').write_bytes(b'not a database')
        code, result = self.invoke('check', '--config', self.save(), '--size', '100', '--request-id', 'x')
        self.assertEqual(code, 2)
        self.assertEqual(result['decision'], 'reject')

    def test_reservations_do_not_expire_with_wall_clock(self):
        self.initialize()
        with mock.patch.object(qg.time, 'time', return_value=1):
            self.check()
        with mock.patch.object(qg.time, 'time', return_value=100000000000):
            self.assertEqual(self.pending(), 500)
            self.assertEqual(self.check(request_id='two')[1], 1)

    def test_release_requires_known_hash_and_healthy_measurement(self):
        self.initialize()
        reservation = self.check()[0]['reservation']
        config = self.save()
        args = ['release', '--config', config, '--reservation', reservation,
                '--confirmed-accounted-or-cancelled']
        with mock.patch.object(qg, 'measure', side_effect=qg.Block('unreadable quota')):
            self.assertEqual(self.invoke(*args)[0], 2)
        self.assertEqual(self.pending(), 500)
        with mock.patch.object(qg, 'measure', return_value=snapshot()):
            self.assertEqual(self.invoke(*args)[0], 0)
            self.assertEqual(self.invoke(*args)[0], 2)
        self.assertEqual(self.pending(), 0)

    def test_generic_errors_do_not_leak_private_paths(self):
        with mock.patch.object(qg, 'measure', side_effect=OSError('/private/SECRET/private-user')):
            code, result = self.invoke('inspect', '--config', self.save())
        self.assertEqual(code, 2)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn(str(self.target), json.dumps(result))

    def test_corrupt_reservation_types_identifiers_and_timestamps_fail_closed(self):
        self.initialize()
        path = Path(self.config['state_dir']) / 'reservations.sqlite3'
        invalid = [('a' * 64, 'not-a-number', 0), ('a' * 64, 1.5, 0),
                   ('a' * 64, -1, 0), ('bad-id', 10, 0),
                   ('a' * 64, 10, -1), ('a' * 64, 10, 'not-a-time'),
                   ('a' * 64, 10, 1.5)]
        for key, amount, created in invalid:
            with self.subTest(key=key, amount=amount, created=created):
                with contextlib.closing(sqlite3.connect(path)) as raw, raw:
                    raw.execute('PRAGMA ignore_check_constraints=ON')
                    raw.execute('DELETE FROM reservations')
                    raw.execute('INSERT INTO reservations VALUES (?,?,?)', (key, amount, created))
                with mock.patch.object(qg, 'measure', return_value=snapshot()) as measurement:
                    code, result = self.invoke('check', '--config', self.save(), '--size', '1', '--request-id', 'new')
                    self.assertEqual(code, 2, result)
                    self.assertEqual(result['decision'], 'reject')
                    measurement.assert_not_called()

    def test_corrupt_reservation_sum_overflow_fails_before_sql_sum(self):
        self.initialize()
        path = Path(self.config['state_dir']) / 'reservations.sqlite3'
        with contextlib.closing(sqlite3.connect(path)) as raw, raw:
            raw.executemany('INSERT INTO reservations VALUES (?,?,?)',
                            [('a' * 64, qg.MAX_BYTES, 0), ('b' * 64, qg.MAX_BYTES, 0)])
        with mock.patch.object(qg, 'measure', return_value=snapshot()) as measurement:
            code, result = self.invoke('check', '--config', self.save(), '--size', '1', '--request-id', 'new')
            self.assertEqual(code, 2, result)
            measurement.assert_not_called()

    def test_locked_ledger_fails_closed_without_approval(self):
        self.initialize()
        path = Path(self.config['state_dir']) / 'reservations.sqlite3'
        raw = sqlite3.connect(path, isolation_level=None)
        try:
            raw.execute('BEGIN IMMEDIATE')
            with mock.patch.object(qg, 'measure', return_value=snapshot()) as measurement:
                code, result = self.invoke('check', '--config', self.save(), '--size', '1', '--request-id', 'new')
                self.assertEqual(code, 2, result)
                measurement.assert_not_called()
        finally:
            raw.rollback()
            raw.close()
        self.assertEqual(self.pending(), 0)

    @unittest.skipUnless(os.name == 'posix', 'POSIX ownership/permissions required')
    def test_world_readable_state_or_hardlinked_ledger_rejected(self):
        self.initialize()
        directory = Path(self.config['state_dir'])
        path = directory / 'reservations.sqlite3'
        directory.chmod(0o755)
        try:
            with self.assertRaises(qg.Block):
                self.check()
        finally:
            directory.chmod(0o700)
        path.chmod(0o644)
        try:
            with self.assertRaises(qg.Block):
                self.check()
        finally:
            path.chmod(0o600)
        os.link(path, directory / 'other-link')
        with self.assertRaises(qg.Block):
            self.check()

    def test_independent_processes_serialize_competing_approvals(self):
        self.initialize()
        configfile = self.save()
        worker = """import importlib.util,json,sys,time
s=importlib.util.spec_from_file_location('qg',sys.argv[1]); q=importlib.util.module_from_spec(s);s.loader.exec_module(q)
c=q.load_config(sys.argv[2]);q.measure=lambda _:dict(available_bytes=1000)
try:
 r,code=q.check(c,'500',sys.argv[3]);print(json.dumps({'code':code,**r}))
except (q.Block,q.sqlite3.Error):print(json.dumps({'code':2}))
"""
        def attempt(i):
            r = subprocess.run([sys.executable, '-c', worker, str(ROOT / 'gg_quotaguard.py'), configfile, str(i)],
                               capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(r['code'] == 0 for r in results), 1, results)
        self.assertEqual(self.pending(), 500)


@unittest.skipUnless(LINUX_ACCOUNTING, 'real POSIX st_blocks/statvfs accounting requires Linux/POSIX')
class DirectoryIntegrationTests(Workspace):
    def scan(self, roots=None, **kwargs):
        return qg.scan_usage(roots or [str(self.target)], str(self.target), **kwargs)

    def test_empty_directory_still_counts_directory_allocation(self):
        used, count = self.scan()
        self.assertGreaterEqual(used, self.target.stat().st_blocks * 512)
        self.assertEqual(count, 1)

    def test_hidden_files_hardlinks_and_overlapping_roots(self):
        nested = self.target / 'nested'
        nested.mkdir()
        hidden = nested / '.hidden'
        hidden.write_bytes(b'x' * 8192)
        os.link(hidden, self.target / 'hardlink')
        used, count = self.scan()
        overlap_used, overlap_count = self.scan([str(self.target), str(nested)])
        self.assertGreaterEqual(used, 8192)
        self.assertEqual(count, 3)
        self.assertEqual((used, count), (overlap_used, overlap_count))

    def test_sparse_files_count_logical_bytes(self):
        sparse = self.target / 'sparse'
        with sparse.open('wb') as f:
            f.truncate(100 * 1024 * 1024)
        self.assertGreaterEqual(self.scan()[0], 100 * 1024 * 1024)

    def test_symlink_to_external_or_internal_path_rejected(self):
        external = self.root / 'outside'
        external.mkdir()
        link = self.target / 'link'
        for destination in [external, self.target]:
            link.symlink_to(destination, target_is_directory=True)
            try:
                with self.assertRaises(qg.Block):
                    self.scan()
            finally:
                link.unlink()

    def test_missing_scope_path_and_target_outside_scope_rejected(self):
        with self.assertRaises((qg.Block, OSError)):
            self.scan([str(self.target), str(self.root / 'missing')])
        other = self.root / 'other'
        other.mkdir()
        with self.assertRaises(qg.Block):
            self.scan([str(other)])

    def test_entry_and_time_limits_reject(self):
        (self.target / 'one').touch()
        with self.assertRaises(qg.Block):
            self.scan(max_entries=1)
        with mock.patch.object(qg.time, 'monotonic', side_effect=[0, 100]), self.assertRaises(qg.Block):
            self.scan(timeout=1)

    def test_special_file_rejected(self):
        os.mkfifo(self.target / 'pipe')
        with self.assertRaises(qg.Block):
            self.scan()

    def test_cross_filesystem_entry_is_rejected(self):
        file = self.target / 'file'
        file.touch()
        actual = Path.lstat
        def different_device(path, *args, **kwargs):
            result = actual(path, *args, **kwargs)
            if path == file:
                return types.SimpleNamespace(st_dev=result.st_dev + 1)
            return result
        with mock.patch.object(Path, 'lstat', different_device), self.assertRaises(qg.Block):
            self.scan()

    @unittest.skipIf(os.name != 'posix' or (hasattr(os, 'geteuid') and os.geteuid() == 0), 'permission denial requires nonroot POSIX user')
    def test_real_inaccessible_directory_is_not_silently_skipped(self):
        denied = self.target / 'denied'
        denied.mkdir()
        denied.chmod(0)
        try:
            with self.assertRaises((qg.Block, PermissionError)):
                self.scan()
        finally:
            denied.chmod(0o700)

    def test_observed_mutation_during_scan_rejected(self):
        file = self.target / 'file'
        file.write_bytes(b'old')
        actual = Path.lstat
        calls = 0
        def mutate(path, *args, **kwargs):
            nonlocal calls
            if path == file:
                calls += 1
                if calls == 2:
                    file.write_bytes(b'changed size')
            return actual(path, *args, **kwargs)
        with mock.patch.object(Path, 'lstat', mutate), self.assertRaises(qg.Block):
            self.scan()

    def test_directory_mode_end_to_end_cli_and_manual_quota_rejection(self):
        c = dict(self.config, mode='directory', directories=[str(self.target)], quota_bytes=1000000)
        self.config = c
        path = self.save()
        code, _ = self.invoke('init', '--config', path)
        self.assertEqual(code, 0)
        code, result = self.invoke('check', '--config', path, '--size', '100', '--request-id', 'small')
        self.assertEqual(code, 0, result)
        code, result = self.invoke('check', '--config', path, '--size', '1000000', '--request-id', 'large')
        self.assertEqual(code, 1, result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
