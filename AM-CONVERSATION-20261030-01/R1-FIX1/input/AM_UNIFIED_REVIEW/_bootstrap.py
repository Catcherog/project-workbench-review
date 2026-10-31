"""Shared offline setup for the fixed-snapshot defect reproducers."""
import os
import sys
import tempfile
from pathlib import Path

_temporary_directory = None
_source_root = None


def bootstrap():
    global _temporary_directory, _source_root
    if _source_root is not None:
        return _source_root
    if sys.version_info < (3, 12):
        raise RuntimeError('被审宿主工程要求 Python 3.12 或以上版本。')
    if not __debug__:
        raise RuntimeError('请勿使用 python -O：本包的 assert 用于证明缺陷现状。')
    supplied = os.environ.get('AM_AUDIT_SOURCE_ROOT')
    if not supplied:
        raise RuntimeError('请设置 AM_AUDIT_SOURCE_ROOT，指向原工程或固定快照的重建根目录。')
    root = Path(supplied).expanduser().resolve(strict=True)
    studio = root / 'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
    required = [
        root / 'local-qwen3.8/feishu-bridge/am_info_sync/store.py',
        root / 'am-conversation-r1/src/am_conversation/documents.py',
        studio / 'src/fs_agent/logic_service.py',
        studio / 'tests/test_document_standards.py',
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError('源码根缺少必要文件：' + ', '.join(missing))

    # No bytecode or default-relative files are written into the source tree.
    sys.dont_write_bytecode = True
    _temporary_directory = tempfile.TemporaryDirectory(prefix='am-audit-repro-')
    os.chdir(_temporary_directory.name)
    sys.path[:0] = [
        str(studio / 'src'),
        str(root / 'am-conversation-r1/src'),
        str(root / 'local-qwen3.8/feishu-bridge'),
    ]

    def offline_only(event, args):
        if event in {'socket.__new__', 'socket.getaddrinfo', 'subprocess.Popen',
                     'os.system', 'os.posix_spawn', 'os.exec'}:
            raise RuntimeError('离线复现禁止网络或外部进程：' + event)

    sys.addaudithook(offline_only)
    _source_root = root
    return root
