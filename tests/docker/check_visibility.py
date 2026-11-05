"""Expected coverage paths must all exist inside the caller's mount namespace."""
import sys
from pathlib import Path
sys.path.insert(0, '/app')
import gg_quotaguard as qg

roots = ['/billed/visible', '/billed/outside']
if sys.argv[1] == 'complete':
    total, entries = qg.scan_usage(roots, '/billed/visible')
    assert total >= sum(p.stat().st_size for root in roots for p in Path(root).rglob('*') if p.is_file())
    assert entries >= 4
    print('PASS: both billed bind mounts were measured')
else:
    try:
        qg.scan_usage(roots, '/billed/visible')
    except (qg.Block, OSError):
        print('PASS: missing billed path in partial container view rejected')
    else:
        raise AssertionError('partial namespace was accepted')
