#!/usr/bin/env python3
"""Copy files to and from a Pocket8086 CP/M-86 card (or a card image).

    python tools/cpmfiles.py D: dir                    list drive A: of the card in D:
    python tools/cpmfiles.py D: put MBASIC.COM *.BAS   copy files onto the card
    python tools/cpmfiles.py D: get *.ASM -o out       copy files off the card
    python tools/cpmfiles.py D: era OLD.COM            delete files
    python tools/cpmfiles.py D: sys build/cpm86.img    update boot sector + system only
    python tools/cpmfiles.py build/cpm86.img dir       same, on an image file

Options:  -c B      CP/M drive (A-P, default A)
          -u N      CP/M user area (default 0; for dir/get/era: all users)
          --force   put: replace files that already exist
          --binary  put/get: no text conversion (default: .ASM .TXT .SUB ...
                    get CR LF line ends and a ^Z, and lose it again on get)
          --text    put/get: text conversion for any file (e.g. ASCII .BAS)

TARGET is a card image file, or the Windows drive letter of the card (e.g. D:).
Raw card access needs administrator rights: the tool asks for them itself (one
UAC prompt).  It only touches removable disks whose first sector carries the
CP/M-86 partition entry (type DBh) written by build.py.
"""
import argparse
import ctypes
import glob
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cpmfs  # noqa: E402
from build import plan_drives, RESERVED as RESERVED_SECTORS, PART_TYPE  # noqa: E402

MAX_CARD = 64 * 1024 ** 3


# ----------------------------------------------------------------- devices
class ImageFile:
    def __init__(self, path, writable):
        self.f = open(path, 'r+b' if writable else 'rb')
        self.f.seek(0, 2)
        self.size = self.f.tell()

    def read(self, lba, n):
        self.f.seek(lba * 512)
        return self.f.read(n * 512)

    def write(self, lba, data):
        self.f.seek(lba * 512)
        self.f.write(data)

    def close(self):
        self.f.close()


if os.name == 'nt':
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    INVALID = wintypes.HANDLE(-1).value


def ioctl(h, code, outsize=0):
    out = ctypes.create_string_buffer(outsize) if outsize else None
    got = wintypes.DWORD()
    ok = k32.DeviceIoControl(h, code, None, 0, out, outsize, ctypes.byref(got), None)
    if not ok:
        raise OSError(ctypes.get_last_error(), 'DeviceIoControl %08X failed' % code)
    return out.raw[:got.value] if out else b''


def open_handle(path, write):
    access = 0x80000000 | (0x40000000 if write else 0)
    h = k32.CreateFileW(path, access, 3, None, 3, 0, None)
    if h == INVALID or h is None:
        raise OSError(ctypes.get_last_error(), 'cannot open %s' % path)
    return h


class CardDevice:
    """The physical disk behind a removable drive letter."""

    def __init__(self, letter, writable):
        self.letter = letter
        if k32.GetDriveTypeW('%s:\\' % letter) != 2:          # DRIVE_REMOVABLE
            raise SystemExit('%s: is not a removable drive' % letter)
        h = open_handle(r'\\.\%s:' % letter, False)
        try:
            dtype, dnum, _ = struct.unpack('<III', ioctl(h, 0x2D1080, 12))
        finally:
            k32.CloseHandle(h)
        self.disk = dnum
        self.path = r'\\.\PhysicalDrive%d' % dnum
        h = open_handle(self.path, False)
        try:
            self.size = struct.unpack('<q', ioctl(h, 0x7405C, 8))[0]
        finally:
            k32.CloseHandle(h)
        if self.size > MAX_CARD:
            raise SystemExit('%s: is %d GB - too big to be the CP/M card' %
                             (letter, self.size >> 30))
        self.lock = None
        self.f = open(self.path, 'rb', buffering=0)
        self.writable = writable

    def read(self, lba, n):
        self.f.seek(lba * 512)
        return self.f.read(n * 512)

    def begin_write(self):
        # lock and dismount the volume so Windows lets us write the raw disk
        h = open_handle(r'\\.\%s:' % self.letter, True)
        try:
            ioctl(h, 0x90018)            # FSCTL_LOCK_VOLUME
            ioctl(h, 0x90020)            # FSCTL_DISMOUNT_VOLUME
        except OSError as e:
            k32.CloseHandle(h)
            raise SystemExit('cannot lock %s: (close Explorer windows / programs '
                             'using it): %s' % (self.letter, e))
        self.lock = h
        self.f.close()
        self.f = open(self.path, 'r+b', buffering=0)

    def write(self, lba, data):
        self.f.seek(lba * 512)
        self.f.write(data)

    def close(self):
        self.f.close()
        if self.lock:
            k32.CloseHandle(self.lock)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True


def relaunch_elevated(argv):
    """Re-run this script elevated (UAC), wait, and show its output."""
    class SEI(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', ctypes.c_ulong),
                    ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                    ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int),
                    ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p),
                    ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE),
                    ('hProcess', wintypes.HANDLE)]
    fd, log = tempfile.mkstemp(prefix='cpmfiles_', suffix='.log')
    os.close(fd)
    args = [os.path.abspath(__file__)] + argv + ['--log', log, '--cwd', os.getcwd()]
    params = ' '.join('"%s"' % a.replace('"', '\\"') for a in args)
    sei = SEI(cbSize=ctypes.sizeof(SEI), fMask=0x40, lpVerb='runas',
              lpFile=sys.executable, lpParameters=params, nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        raise SystemExit('administrator rights are needed to access the card '
                         '(UAC prompt was declined)')
    k32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    k32.CloseHandle(sei.hProcess)
    with open(log, encoding='utf-8', errors='replace') as f:
        sys.stdout.write(f.read())
    os.remove(log)
    return code.value


# ----------------------------------------------------------------- commands
def find_layout(dev):
    mbr = dev.read(0, 1)
    if mbr[510:512] != b'\x55\xaa' or mbr[0x1BE + 4] != PART_TYPE:
        raise SystemExit('this does not look like a Pocket8086 CP/M-86 card '
                         '(no CP/M partition entry) - nothing changed')
    first, count = struct.unpack('<II', mbr[0x1BE + 8:0x1BE + 16])
    drives = plan_drives(first + count, 16)
    if drives[0]['base'] != first:
        raise SystemExit('unexpected card layout (drive A: at %d, expected %d)' %
                         (first, drives[0]['base']))
    if first + count > dev.size // 512:
        raise SystemExit('card is smaller than its partition table says')
    return drives


def cmd_dir(drv, letter, a):
    files = drv.files()
    keys = sorted({k for p in (a.names or ['*.*']) for k in drv.match(p, a.user)},
                  key=lambda k: (k[0], k[1], k[2]))
    for k in keys:
        recs = drv.records(k)
        print('%2d %s:%-12s %8d bytes  (%d records)' % (
            k[0], letter, cpmfs.display_name(k[1], k[2]), recs * 128, recs))
    print('%d file(s), %d KB free of %d KB' % (
        len(keys), drv.free_kb(), (drv.dsm + 1) * drv.bls // 1024))
    return False


def cmd_put(drv, letter, a):
    paths = []
    for p in a.names:
        hits = glob.glob(p)
        if not hits:
            raise SystemExit('no such file: %s' % p)
        paths += [h for h in hits if os.path.isfile(h)]
    user = a.user or 0
    for p in paths:
        data = open(p, 'rb').read()
        text = (cpmfs.is_text_name(p) or a.text) and not a.binary
        if text:
            data = cpmfs.to_cpm_text(data)
        try:
            recs, _ = drv.write(os.path.basename(p), data, user, a.force)
        except cpmfs.CpmError as e:
            raise SystemExit('%s: %s - nothing written' % (p, e))
        print('put %-30s -> %s:%s%s  (%d bytes%s)' % (
            p, letter, os.path.basename(p).upper(), '' if not user else ' [user %d]' % user,
            recs * 128, ', text' if text else ''))
    print('%d KB free' % drv.free_kb())
    return bool(paths)


def cmd_get(drv, letter, a):
    os.makedirs(a.out, exist_ok=True)
    keys = sorted({k for p in a.names for k in drv.match(p, a.user)})
    if not keys:
        raise SystemExit('no matching files')
    for k in keys:
        name = cpmfs.display_name(k[1], k[2])
        data = drv.read(k)
        if (cpmfs.is_text_name(name) or a.text) and not a.binary:
            data = cpmfs.from_cpm_text(data)
        dest = os.path.join(a.out, name)
        with open(dest, 'wb') as f:
            f.write(data)
        print('get %s:%s -> %s  (%d bytes)' % (letter, name, dest, len(data)))
    return False


def cmd_era(drv, letter, a):
    keys = sorted({k for p in a.names for k in drv.match(p, a.user)})
    if not keys:
        raise SystemExit('no matching files')
    for k in keys:
        drv.erase(k)
        print('era %s:%s' % (letter, cpmfs.display_name(k[1], k[2])))
    print('%d KB free' % drv.free_kb())
    return True


COMMANDS = {'dir': cmd_dir, 'put': cmd_put, 'get': cmd_get, 'era': cmd_era,
            'sys': None}


def cmd_sys(dev, is_card, a):
    """Replace the boot sector + loader (LBA 0-63) from a built image."""
    if len(a.names) != 1:
        raise SystemExit('usage: cpmfiles.py TARGET sys build/cpm86.img')
    new = open(a.names[0], 'rb').read(RESERVED_SECTORS * 512)
    old = dev.read(0, RESERVED_SECTORS)
    if new[0x1BE:0x1FE] != old[0x1BE:0x1FE]:
        raise SystemExit('the image was built for a different card layout '
                         '(partition tables differ) - nothing written')
    dirty = [s for s in range(RESERVED_SECTORS)
             if new[s * 512:(s + 1) * 512] != old[s * 512:(s + 1) * 512]]
    if not dirty:
        print('system area already up to date')
        return
    if is_card:
        dev.begin_write()
    for s in sorted(dirty, reverse=True):          # boot sector last
        dev.write(s, new[s * 512:(s + 1) * 512])
    bad = [s for s in dirty if dev.read(s, 1) != new[s * 512:(s + 1) * 512]]
    if bad:
        raise SystemExit('VERIFY FAILED on %d sector(s)!' % len(bad))
    print('system (boot sector + loader): %d sector(s) written and verified' % len(dirty))


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split('\n', 2)[2])
    ap.add_argument('target', help='card drive letter (D:) or image file')
    ap.add_argument('command', choices=sorted(COMMANDS))
    ap.add_argument('names', nargs='*')
    ap.add_argument('-c', '--cpm-drive', default='A')
    ap.add_argument('-u', '--user', type=int, choices=range(16), default=None)
    ap.add_argument('-o', '--out', default='.')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--binary', action='store_true')
    ap.add_argument('--text', action='store_true')
    ap.add_argument('--log', help=argparse.SUPPRESS)
    ap.add_argument('--cwd', help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.log:                                  # elevated child: report via log
        sys.stdout = sys.stderr = open(a.log, 'w', encoding='utf-8')
    if a.cwd:
        os.chdir(a.cwd)
    if a.command in ('put', 'get', 'era', 'sys') and not a.names:
        ap.error('%s needs file names' % a.command)

    writes = a.command in ('put', 'era', 'sys')
    if a.command == 'sys' and a.names:
        a.names = [os.path.abspath(n) for n in a.names]
    tgt = a.target.rstrip('\\/')
    is_card = len(tgt) == 2 and tgt[1] == ':' and tgt[0].isalpha()
    if is_card:
        if os.name != 'nt':
            raise SystemExit('drive letters work on Windows only; use an image or a device file')
        if not is_admin():
            return relaunch_elevated(argv)
        dev = CardDevice(tgt[0].upper(), writes)
    else:
        dev = ImageFile(a.target, writes)

    try:
        drives = find_layout(dev)
        if a.command == 'sys':
            cmd_sys(dev, is_card, a)
            return 0
        ci = ord(a.cpm_drive.upper()[0]) - 65
        if not 0 <= ci < len(drives):
            raise SystemExit('the card has CP/M drives A: to %s:' % chr(64 + len(drives)))
        d = drives[ci]
        letter = chr(65 + ci)
        orig = dev.read(d['base'], d['sectors'])
        region = bytearray(orig)
        drv = cpmfs.CpmDrive(region, d)
        changed = COMMANDS[a.command](drv, letter, a)
        if changed:
            dirsecs = drv.dirblocks * drv.bls // 512
            dirty = [s for s in range(d['sectors'])
                     if region[s * 512:(s + 1) * 512] != orig[s * 512:(s + 1) * 512]]
            # data first, directory last: a cut-off write never leaves the
            # directory pointing at unwritten blocks
            dirty.sort(key=lambda s: (s < dirsecs, s))
            if is_card:
                dev.begin_write()
            for s in dirty:
                dev.write(d['base'] + s, bytes(region[s * 512:(s + 1) * 512]))
            bad = [s for s in dirty
                   if dev.read(d['base'] + s, 1) != region[s * 512:(s + 1) * 512]]
            if bad:
                raise SystemExit('VERIFY FAILED on %d sector(s)!' % len(bad))
            print('%d sector(s) written and verified' % len(dirty))
    except OSError as e:
        raise SystemExit('I/O error: %s' % e)
    finally:
        dev.close()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit as e:
        if isinstance(e.code, str):
            print('error: ' + e.code)
            sys.exit(1)
        raise
