#!/usr/bin/env python3
"""Download VCPM, the NEC V20/V30 CP/M-80 emulator for CP/M-86, into extras/.

    python tools/get_vcpm.py
    python tools/build.py --sectors N          # or: cpmfiles.py D: put extras/VCPM.A86

VCPM (C) 1988 Stephen Hunt runs CP/M-80 .COM programs under CP/M-86 by putting
the V20/V30 into its 8080 emulation mode, the same trick as the pocket8086-cpm
card.  It comes with no license statement, so it is not part of this
repository; this script fetches NECVCPM.ZIP from the Unofficial CP/M Web Site,
checks that it is exactly the expected file and saves the source as
extras/VCPM.A86 (git ignores extras/).

Build it on the Pocket8086 (the EXTRA option gives it its 64K 8080 segment):

    A>ASM86 VCPM $PZSZ
    A>GENCMD VCPM EXTRA[M1000]
    A>VCPM D:ASM HELLO          (runs the CP/M-80 program ASM.COM)

It needs an NEC V20/V30; it will not work on an Intel 8086/8088.
"""
import hashlib
import io
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'http://www.cpm.z80.de/download/necvcpm.zip'
SHA256 = 'd84544bad79aa41999b31d698275630228becf8fddcf79b8cf870254bb2365cc'


def main():
    print('downloading', URL)
    with urllib.request.urlopen(URL, timeout=60) as r:
        data = r.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        sys.exit('necvcpm.zip checksum mismatch (got %s) - not using it' % digest)
    src = zipfile.ZipFile(io.BytesIO(data)).read('VCPM15.A86')
    out = os.path.join(ROOT, 'extras')
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'VCPM.A86'), 'wb') as f:
        f.write(src)
    print('extras/VCPM.A86 (%d bytes)' % len(src))


if __name__ == '__main__':
    main()
