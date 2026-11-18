"""CP/M 2.2 file system on one drive of a Pocket8086 CP/M card.

Works on an in-memory copy of the drive (bytearray of drive['sectors']*512
bytes).  Drive geometry comes from build.plan_drives().  Only the layouts
build.py creates are supported: 16-bit block pointers (DSM > 255), directory
in the first blocks, no system tracks.
"""
import fnmatch
import os

TEXT_EXT = {'.ASM', '.A86', '.TXT', '.SUB', '.DOC', '.LIB', '.MAC', '.PAS',
            '.C', '.H', '.PRN', '.ME', '.Z80', '.FOR', '.PLI', '.HEX'}


class CpmError(Exception):
    pass


def to_cpm_text(data):
    """Host text -> CP/M text: CR LF line ends, ^Z at the end."""
    data = data.split(b'\x1a')[0].replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    return data + b'\x1a'


def from_cpm_text(data):
    """CP/M text -> host text: cut at ^Z (line ends stay CR LF)."""
    return data.split(b'\x1a')[0]


def is_text_name(name):
    return os.path.splitext(name)[1].upper() in TEXT_EXT


def split_name(name):
    """'hello.com' -> (b'HELLO   ', b'COM'); raises CpmError if not 8.3."""
    base, _, ext = os.path.basename(name).upper().partition('.')
    bad = set(' <>.,;:=?*[]|()/\\"')
    if not base or len(base) > 8 or len(ext) > 3 or \
            any(c in bad or ord(c) < 33 or ord(c) > 126 for c in base + ext):
        raise CpmError('%r is not a valid CP/M 8.3 file name' % name)
    return base.ljust(8).encode('ascii'), ext.ljust(3).encode('ascii')


def display_name(n8, e3):
    n = bytes(b & 0x7F for b in n8).decode('ascii', 'replace').rstrip()
    e = bytes(b & 0x7F for b in e3).decode('ascii', 'replace').rstrip()
    return n + ('.' + e if e else '')


class CpmDrive:
    def __init__(self, data, d):
        self.data = data
        self.bls = d['bls']
        self.dsm = d['dsm']
        self.drm = d['drm']
        self.exm = d['exm']
        if self.dsm < 256:
            raise CpmError('8-bit block pointers are not supported')
        self.nent = self.drm + 1
        self.dirblocks = (self.nent * 32 + self.bls - 1) // self.bls
        self.recs_per_entry = 8 * self.bls // 128

    # -- directory -------------------------------------------------------
    def entry(self, i):
        return self.data[i * 32:(i + 1) * 32]

    def set_entry(self, i, ent):
        assert len(ent) == 32
        self.data[i * 32:(i + 1) * 32] = ent

    def files(self):
        """{(user, name8, ext3): [entry indexes]} for user areas 0-15."""
        out = {}
        for i in range(self.nent):
            e = self.entry(i)
            if e[0] <= 15:
                key = (e[0], bytes(b & 0x7F for b in e[1:9]),
                       bytes(b & 0x7F for b in e[9:12]))
                out.setdefault(key, []).append(i)
        return out

    def match(self, pattern, user=None):
        """Keys of files matching a wildcard pattern like '*.COM'."""
        pat = pattern.upper()
        if '.' not in pat:
            pat += '.*' if '*' in pat or '?' in pat else '.'
        res = []
        for key in sorted(self.files()):
            if user is not None and key[0] != user:
                continue
            name = display_name(key[1], key[2])
            full = name if '.' in name else name + '.'
            if fnmatch.fnmatchcase(full, pat) or fnmatch.fnmatchcase(name, pat):
                res.append(key)
        return res

    def ext_number(self, e):
        return (e[12] & 0x1F) | (e[14] << 5)

    def pointers(self, e):
        return [int.from_bytes(e[16 + 2 * k:18 + 2 * k], 'little') for k in range(8)]

    def used_blocks(self):
        used = set(range(self.dirblocks))
        for i in range(self.nent):
            e = self.entry(i)
            if e[0] != 0xE5:
                used.update(p for p in self.pointers(e) if p)
        return used

    def free_blocks(self):
        used = self.used_blocks()
        return [b for b in range(self.dsm + 1) if b not in used]

    def free_entries(self):
        return [i for i in range(self.nent) if self.entry(i)[0] == 0xE5]

    def records(self, key):
        """Total 128-byte records of a file."""
        ents = sorted((self.entry(i) for i in self.files()[key]), key=self.ext_number)
        last = ents[-1]
        return (self.ext_number(last) // (self.exm + 1)) * self.recs_per_entry + \
            (self.ext_number(last) & self.exm) * 128 + last[15]

    def block(self, b):
        return self.data[b * self.bls:(b + 1) * self.bls]

    # -- operations ------------------------------------------------------
    def read(self, key):
        idx = self.files().get(key)
        if not idx:
            raise CpmError('file not found')
        nrec = self.records(key)
        out = bytearray()
        for e in sorted((self.entry(i) for i in idx), key=self.ext_number):
            for p in self.pointers(e):
                if p:
                    if p > self.dsm:
                        raise CpmError('bad block number %d' % p)
                    out += self.block(p)
        return bytes(out[:nrec * 128])

    def erase(self, key):
        for i in self.files().get(key, []):
            e = bytearray(self.entry(i))
            e[0] = 0xE5
            self.set_entry(i, bytes(e))

    def write(self, name, data, user=0, replace=False):
        """Add a file.  Returns (records, blocks)."""
        n8, e3 = split_name(name)
        key = (user, n8, e3)
        if key in self.files():
            if not replace:
                raise CpmError('%s already exists (use --force to replace)' %
                               display_name(n8, e3))
            self.erase(key)
        if len(data) % 128:
            pad = b'\x1a' if is_text_name(name) else b'\0'
            data += pad * (128 - len(data) % 128)
        nrec = len(data) // 128
        nblocks = (len(data) + self.bls - 1) // self.bls
        nent = max(1, (nrec + self.recs_per_entry - 1) // self.recs_per_entry)
        free = self.free_blocks()
        slots = self.free_entries()
        if nblocks > len(free):
            raise CpmError('disk full: need %d KB, %d KB free' % (
                nblocks * self.bls // 1024, len(free) * self.bls // 1024))
        if nent > len(slots):
            raise CpmError('directory full')
        blocks = free[:nblocks]
        for k, b in enumerate(blocks):
            chunk = data[k * self.bls:(k + 1) * self.bls]
            self.data[b * self.bls:b * self.bls + len(chunk)] = chunk
        for e in range(nent):
            n = min(self.recs_per_entry, nrec - e * self.recs_per_entry)
            if n <= 0:
                ext, rc = e * (self.exm + 1), 0
            else:
                lastx = (n - 1) // 128
                ext, rc = e * (self.exm + 1) + lastx, n - lastx * 128
            al = blocks[e * 8:(e + 1) * 8]
            ent = bytes([user]) + n8 + e3 + bytes([ext & 0x1F, 0, ext >> 5, rc])
            ent += b''.join(b.to_bytes(2, 'little') for b in al).ljust(16, b'\0')
            self.set_entry(slots[e], ent)
        return nrec, nblocks

    def free_kb(self):
        return len(self.free_blocks()) * self.bls // 1024
