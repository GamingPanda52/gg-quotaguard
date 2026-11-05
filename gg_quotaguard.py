#!/usr/bin/env python3
"""GG QuotaGuard: conservative, unprivileged Autobrr external filter. MIT."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time

VERSION = '0.1.0'
MAX_BYTES = 2**63 - 1


class Block(Exception):
    pass


class RejectingArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise Block('invalid command arguments')


def integer(value, label, minimum=0):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,19}', str(value)):
        raise Block(label + ' must be an unsigned integer in bytes')
    result = int(value)
    if not minimum <= result <= MAX_BYTES:
        raise Block(label + ' outside supported range')
    return result


def _reject_duplicate_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise Block('duplicate configuration keys are forbidden')
    return dict(pairs)


def load_config(path):
    try:
        c = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, ValueError):
        raise Block('configuration missing or invalid JSON') from None
    allowed = {'mode', 'target', 'directories', 'quota_bytes', 'reserve_bytes',
               'scope_confirmed', 'startup_pending_confirmed', 'state_dir',
               'scan_timeout_seconds', 'max_entries', 'quota_device'}
    if not isinstance(c, dict) or set(c) - allowed:
        raise Block('unknown configuration keys or invalid configuration object')
    if c.get('mode') not in ('quota', 'directory'):
        raise Block('mode must be quota or directory; filesystem-only approval is forbidden')
    for key in ('scope_confirmed', 'startup_pending_confirmed'):
        if c.get(key) is not True:
            raise Block(key + ' must be explicitly confirmed; see setup guide')
    for key in ('target', 'state_dir'):
        if not isinstance(c.get(key), str) or not Path(c[key]).is_absolute():
            raise Block(key + ' must be an absolute path')
    c['reserve_bytes'] = integer(c.get('reserve_bytes'), 'reserve_bytes', 1)
    c['scan_timeout_seconds'] = integer(c.get('scan_timeout_seconds', 10), 'scan_timeout_seconds', 1)
    if c['scan_timeout_seconds'] > 60:
        raise Block('scan timeout must be at most 60 seconds')
    c['max_entries'] = integer(c.get('max_entries', 250000), 'max_entries', 1)
    if c['mode'] == 'directory':
        c['quota_bytes'] = integer(c.get('quota_bytes'), 'quota_bytes', 1)
        roots = c.get('directories')
        if not isinstance(roots, list) or not roots or any(not isinstance(p, str) or not Path(p).is_absolute() for p in roots):
            raise Block('directory mode requires absolute directories covering the entire billed scope')
    elif not isinstance(c.get('quota_device'), str) or not re.fullmatch(r'/dev/[A-Za-z0-9_./-]+', c['quota_device']):
        raise Block('quota mode requires the verified /dev device for the target filesystem')
    return c


def run(args, timeout=5):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL='C', LANG='C'))
    except (OSError, subprocess.TimeoutExpired):
        raise Block('required storage command unavailable or timed out') from None
    # quota returns nonzero on some implementations when over quota. Reject it.
    if p.returncode != 0 or p.stderr.strip():
        raise Block('storage command failed; no fallback to filesystem space')
    return p.stdout


def parse_quota(output, device):
    """Parse Linux quota-tools -w -p: unscaled 1 KiB blocks, numeric grace."""
    matches = []
    for line in output.splitlines():
        fields = line.split()
        if not fields or fields[0] != device:
            continue
        if len(fields) != 9:
            raise Block('quota row format unsupported; need quota-tools -w -p with numeric grace')
        nums = []
        for i, field in enumerate(fields[1:]):
            if not re.fullmatch(r'[0-9]{1,19}' + (r'\*?' if i in (0, 4) else ''), field):
                raise Block('quota field format unsupported')
            nums.append(integer(field.rstrip('*'), 'quota field'))
        used, soft, hard, _grace, files, fsoft, fhard, _fgrace = nums
        limits = [n for n in (soft, hard) if n > 0]
        if not limits:
            raise Block('no finite user quota limit; filesystem space is not an account quota')
        if (fsoft and files >= fsoft) or (fhard and files >= fhard):
            raise Block('user inode quota is exhausted')
        limit = min(limits) * 1024
        used *= 1024
        if max(used, limit) > MAX_BYTES:
            raise Block('quota value outside supported range')
        matches.append((used, limit))
    if len(matches) != 1:
        raise Block('expected exactly one quota row for the verified device')
    return matches[0]


def verified_target(c):
    target = Path(c['target'])
    try:
        if target.resolve(strict=True) != target or not target.is_dir():
            raise Block('target must be an existing canonical directory without symlink components')
        if not os.access(target, os.W_OK | os.X_OK):
            raise Block('target is not writable/searchable by this user')
        return target.stat()
    except OSError:
        raise Block('target is inaccessible') from None


def scan_usage(roots, target, max_entries=250000, timeout=10):
    """Upper estimate for visible allocated/logical bytes; never follow links."""
    started = time.monotonic()
    seen = set()
    records = []
    roots = [Path(p) for p in roots]
    dev = Path(target).stat().st_dev
    for root in roots:
        if root.resolve(strict=True) != root or not root.is_dir():
            raise Block('scan roots must be existing canonical directories')
    if not any(Path(target) == r or r in Path(target).parents for r in roots):
        raise Block('download target lies outside the measured scope')
    stack = list(roots)
    total = 0
    while stack:
        if time.monotonic() - started > timeout:
            raise Block('directory scan exceeded time budget')
        path = stack.pop()
        s = path.lstat()
        if s.st_dev != dev:
            raise Block('scan crosses filesystems; a single quota scope cannot be established')
        identity = (s.st_dev, s.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        if len(seen) > max_entries:
            raise Block('directory scan exceeded entry budget')
        if stat.S_ISLNK(s.st_mode):
            raise Block('symlink found in measured scope; use verified quota mode or correct the scope')
        if not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)):
            raise Block('special file found in measured scope')
        if not hasattr(s, 'st_blocks'):
            raise Block('allocated block accounting unavailable on this platform')
        # Logical bytes cover sparse/preallocated torrent files; blocks cover metadata/slack.
        total += max(s.st_blocks * 512, s.st_size)
        records.append((path, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns))
        if stat.S_ISDIR(s.st_mode):
            with os.scandir(path) as entries:
                for entry in entries:
                    if len(seen) + len(stack) >= max_entries:
                        raise Block('directory scan exceeded entry budget')
                    if time.monotonic() - started > timeout:
                        raise Block('directory scan exceeded time budget')
                    stack.append(Path(entry.path))
    # This detects many races, but is not a snapshot. Uncoordinated writers remain a limit.
    for path, ino, size, mtime, ctime in records:
        if time.monotonic() - started > timeout:
            raise Block('directory validation exceeded time budget')
        s = path.lstat()
        if (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns) != (ino, size, mtime, ctime):
            raise Block('measured tree changed during scan; retry after activity settles')
    return total, len(seen)


@contextlib.contextmanager
def deadline(seconds):
    if hasattr(signal, 'SIGALRM'):
        def expired(_sig, _frame):
            raise Block('storage measurement timed out')
        previous = signal.signal(signal.SIGALRM, expired)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    else:
        yield


def measure(c):
    verified_target(c)
    with deadline(c['scan_timeout_seconds']):
        if not hasattr(os, 'statvfs'):
            raise Block('Linux/POSIX filesystem accounting required')
        fs = os.statvfs(c['target'])
        if fs.f_flag & getattr(os, 'ST_RDONLY', 1):
            raise Block('target filesystem is read-only')
        filesystem_free = max(0, fs.f_bavail * fs.f_frsize)
        if fs.f_files and fs.f_favail <= 0:
            raise Block('target filesystem has no available inodes')
        if c['mode'] == 'quota':
            source = run(['findmnt', '-n', '-o', 'SOURCE', '--target', c['target']]).strip()
            if source.split('[', 1)[0] != c['quota_device']:
                raise Block('target mount does not match configured quota device')
            used, limit = parse_quota(run(['quota', '-w', '-p', '-u', str(os.getuid())]), c['quota_device'])
            entries = None
        else:
            used, entries = scan_usage(c['directories'], c['target'], c['max_entries'], c['scan_timeout_seconds'])
            limit = c['quota_bytes']
        return {'method': c['mode'], 'used_bytes': used, 'limit_bytes': limit,
                'account_free_bytes': max(0, limit - used), 'filesystem_free_bytes': filesystem_free,
                'available_bytes': min(max(0, limit - used), filesystem_free), 'entries': entries}


def fingerprint(c):
    relevant = {k: v for k, v in c.items() if k != 'state_dir'}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()


def private_directory(path, create=False):
    p = Path(path)
    if create:
        p.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not p.is_dir() or p.resolve(strict=True) != p:
        raise Block('state directory missing or contains symlink components')
    s = p.stat()
    if os.name == 'posix' and (s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) & 0o077):
        raise Block('state directory must belong to this user with permissions 0700')
    return p


@contextlib.contextmanager
def ledger(c, initialize=False):
    directory = private_directory(c['state_dir'], create=initialize)
    p = directory / 'reservations.sqlite3'
    if initialize:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    if not p.is_file() or p.is_symlink():
        raise Block('reservation ledger missing or unsafe; initialize once before enabling filter')
    if os.name == 'posix':
        s = p.stat()
        if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) & 0o077 or s.st_nlink != 1:
            raise Block('reservation ledger ownership, permissions or link count unsafe')
    db = sqlite3.connect(p.as_uri() + '?mode=rw', uri=True, timeout=1, isolation_level=None)
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        if initialize:
            db.execute('CREATE TABLE meta (fingerprint TEXT NOT NULL)')
            db.execute('INSERT INTO meta VALUES (?)', (fingerprint(c),))
            db.execute("CREATE TABLE reservations (id TEXT PRIMARY KEY, bytes INTEGER NOT NULL CHECK(typeof(bytes)='integer' AND bytes>0), created INTEGER NOT NULL CHECK(typeof(created)='integer' AND created>=0))")
        rows = db.execute('SELECT fingerprint FROM meta').fetchall()
        if rows != [(fingerprint(c),)]:
            raise Block('configuration changed since initialization; reconcile pending reservations before migration')
        total = 0
        for key, amount, created in db.execute('SELECT id,bytes,created FROM reservations'):
            if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key):
                raise Block('invalid reservation ledger identifier')
            if type(amount) is not int or not 1 <= amount <= MAX_BYTES or type(created) is not int or created < 0:
                raise Block('invalid reservation ledger values')
            total += amount
            if total > MAX_BYTES:
                raise Block('reservation ledger total exceeds supported range')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def request_hash(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or not value.isprintable() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise Block('request ID must contain 1 to 256 printable characters')
    return hashlib.sha256(value.encode()).hexdigest()


def check(c, size, request_id):
    size = integer(size, 'incoming size', 1)
    key = request_hash(request_id)
    with ledger(c) as db:
        if db.execute('SELECT 1 FROM reservations WHERE id=?', (key,)).fetchone():
            raise Block('request ID already reserved; duplicate/retry rejected without approving twice')
        pending = db.execute('SELECT COALESCE(SUM(bytes),0) FROM reservations').fetchone()[0]
        result = measure(c)
        required = pending + size + c['reserve_bytes']
        result.update(pending_bytes=pending, incoming_bytes=size, reserve_bytes=c['reserve_bytes'], required_bytes=required)
        if result['available_bytes'] < required:
            result.update(decision='reject', reason='insufficient space after pending reservations and safety reserve')
            return result, 1
        if pending + size > MAX_BYTES:
            raise Block('reservation total outside supported range')
        db.execute('INSERT INTO reservations VALUES (?,?,?)', (key, size, int(time.time())))
        result.update(decision='accept', reason='sufficient measured capacity; incoming bytes durably reserved', reservation=key)
    return result, 0


def diagnose(target):
    """Only inspect the given path; never enumerate other users or raw mount tables."""
    report = {'version': VERSION, 'platform': sys.platform, 'nonroot': os.name != 'posix' or os.getuid() != 0,
              'commands': {n: bool(shutil.which(n)) for n in ['python3', 'quota', 'findmnt', 'du', 'df']},
              'target_exists': False, 'quota_row_count': 0,
              'external_exec_verified': False, 'coverage_verified': False,
              'note': 'Run inside the Autobrr execution environment too; host results do not prove container access.'}
    try:
        p = Path(target)
        report['target_exists'] = p.is_dir()
        report['target_writable'] = os.access(p, os.W_OK | os.X_OK)
        if hasattr(os, 'statvfs'):
            fs = os.statvfs(p)
            report['filesystem_free_bytes_NOT_account_quota'] = max(0, fs.f_bavail * fs.f_frsize)
        source = run(['findmnt', '-n', '-o', 'SOURCE,FSTYPE', '--target', str(p)]).split()
        report['filesystem_type'] = source[-1]
        output = run(['quota', '-w', '-p', '-u', str(os.getuid())])
        report['quota_row_count'] = sum(line.lstrip().startswith('/dev/') for line in output.splitlines())
        used, limit = parse_quota(output, source[0].split('[', 1)[0])
        report.update(quota_available=True, quota_used_bytes=used, quota_limit_bytes=limit)
    except (Block, OSError, IndexError):
        report['quota_available'] = False
    return report


def main(argv=None):
    parser = RejectingArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--version', action='version', version='GG QuotaGuard ' + VERSION)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['init', 'check', 'inspect', 'release', 'status']:
        p = sub.add_parser(name, allow_abbrev=False)
        p.add_argument('--config', required=True)
        if name == 'check':
            p.add_argument('--size', required=True, help='positive integer bytes: {{ .Size }}')
            p.add_argument('--request-id', help='optional explicit opaque ID; default is a fresh random attempt ID')
        if name == 'release':
            p.add_argument('--reservation', required=True, help='64-character hash from check/status')
            p.add_argument('--confirmed-accounted-or-cancelled', action='store_true', required=True)
    p = sub.add_parser('diagnose', allow_abbrev=False)
    p.add_argument('--target', default=str(Path.home()))
    try:
        raw_args = list(sys.argv[1:] if argv is None else argv)
        for option in ('--config', '--size', '--request-id', '--reservation', '--target'):
            if sum(arg.split('=', 1)[0] == option for arg in raw_args) > 1:
                raise Block('duplicate command options are forbidden')
        args = parser.parse_args(raw_args)
        if args.command == 'diagnose':
            result, code = diagnose(args.target), 0
        else:
            c = load_config(args.config)
            if args.command == 'check':
                if args.request_id is not None:
                    request_id = args.request_id
                else:
                    try:
                        request_id = secrets.token_hex(16)
                    except (NotImplementedError, OSError, RuntimeError):
                        raise Block('unable to generate a secure reservation ID') from None
                result, code = check(c, args.size, request_id)
            elif args.command == 'init':
                # Validate measurement before creating durable state.
                measure(c)
                with ledger(c, initialize=True):
                    pass
                result, code = {'decision': 'initialized', 'version': VERSION}, 0
            elif args.command == 'inspect':
                result, code = measure(c), 0
                result['decision'] = 'diagnostic_only_no_reservation'
            else:
                with ledger(c) as db:
                    if args.command == 'release':
                        if not re.fullmatch(r'[0-9a-f]{64}', args.reservation):
                            raise Block('invalid reservation hash')
                        measure(c)
                        if db.execute('DELETE FROM reservations WHERE id=?', (args.reservation,)).rowcount != 1:
                            raise Block('reservation not found')
                        result = {'decision': 'released', 'note': 'Operator confirmed download is fully accounted or cancelled.'}
                    else:
                        rows = db.execute('SELECT id,bytes,created FROM reservations ORDER BY created').fetchall()
                        result = {'pending_bytes': sum(r[1] for r in rows), 'reservations': [dict(zip(['id','bytes','created'],r)) for r in rows]}
                code = 0
    except Block as exc:
        result, code = {'decision': 'reject', 'reason': str(exc)}, 2
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError, RecursionError):
        # Exceptions may contain private paths, usernames, or command output.
        result, code = {'decision': 'reject', 'reason': 'storage/configuration/state operation failed; inspect permissions, paths and ledger integrity'}, 2
    except Exception:
        # Any other failure must still reject as JSON with exit 2 (never a traceback or exit 1,
        # which is the "insufficient space" status). Details are intentionally not printed.
        result, code = {'decision': 'reject', 'reason': 'unexpected internal failure; no reservation is approved'}, 2
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
