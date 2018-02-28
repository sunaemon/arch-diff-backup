#!/usr/bin/python

import subprocess
import re
import itertools
import os
import stat
import difflib
import tarfile
import multiprocessing


def get_property_of_pkg(pkg):
    proc = subprocess.Popen(["/usr/bin/pacman", "-Qi", pkg], stdout=subprocess.PIPE)

    prop = {}
    for line in proc.stdout:
        m = re.match(r"^([\w\s]*?)\s* : (.*)$", line.decode())
        if m:
            prop[m.group(1)] = m.group(2)
    return prop


def parse_filename(raw):
    d = ""
    i = 0
    while i < len(raw):
        if raw[i] != '\\':
            d += raw[i]
            i += 1
        else:
            d += chr(int(raw[i + 1:i + 4], 8))
            i += 4
    return d


def get_mtree(pkg):
    prop = get_property_of_pkg(pkg)
    name = prop['Name']
    version = prop['Version']
    mtreepath = f"/var/lib/pacman/local/{name}-{version}/mtree"
    p = subprocess.Popen(["/usr/bin/zcat", mtreepath], stdout=subprocess.PIPE, universal_newlines=True)
    d = {}
    mtree = {}
    for line in p.stdout:
        if line == '':
            continue
        if re.match(r"^#", line):
            continue
        words = line.split()
        if words[0] == "/set":
            for p in itertools.islice(words, 1, None):
                m = re.match(r"^(?P<name>[^=]*)=(?P<value>.*)$", p)
                d[m.group("name")] = m.group("value")
            continue
        if words[0] in ["./.INSTALL", "./.PKGINFO", "./.CHANGELOG", "./.BUILDINFO"]:
            continue
        dd = d.copy()
        for p in itertools.islice(words, 1, None):
            m = re.match(r"^(?P<name>[^=]*)=(?P<value>.*)$", p)
            dd[m.group("name")] = m.group("value")
        dd["package"] = pkg

        mtree[os.path.normpath(os.path.join('/', parse_filename(words[0])))] = dd
    return mtree


def get_mtrees_parallel(packages):
    pool = multiprocessing.Pool()
    callback = pool.map(get_mtree, packages)

    mtree = {}
    for m in callback:
        mtree.update(m)

    return mtree


def get_digest(files):
    digests = {}

    p = subprocess.Popen(["/usr/bin/sha256sum"] + files, stdout=subprocess.PIPE, universal_newlines=True)
    for line in p.stdout:
        match = re.match(r"^(?P<hash>[^ ]*) +(?P<path>.*)$", line)
        digests[match.group("path")] = match.group("hash")

    return digests


def get_digest_parallel(files):
    arg_max = int(subprocess.check_output(["getconf", "ARG_MAX"]))-2
    max_par = int(len(files)/multiprocessing.cpu_count())
    amax = min(arg_max, max_par)

    print("AMAX:", amax)

    chunks = []

    n = 0
    while n < len(files):
        chunks.append(files[n:n + amax])
        n += amax

    pool = multiprocessing.Pool()
    callback = pool.map(get_digest, chunks)

    digests = {}
    for d in callback:
        digests.update(d)

    return digests


# See https://stackoverflow.com/questions/898669/how-can-i-detect-if-a-file-is-binary-non-text-in-python/7392391#7392391
textchars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7f})


def is_binary_string(bytes):
    return bool(bytes.translate(None, textchars))


def is_binary_file(path):
    return is_binary_string(open(path, 'rb').read(1024))


def print_diff(k, v):
    prop = get_property_of_pkg(v["package"])
    name = prop['Name']
    version = prop['Version']
    arch = prop['Architecture']
    pkg_path = f"/var/cache/pacman/pkg/{name}-{version}-{arch}.pkg.tar.xz"
    a = tarfile.open(pkg_path).extractfile(k[1:])
    if not is_binary_string(a.read(1024)) and not is_binary_file(k):
        for l in difflib.unified_diff(a.read().decode().splitlines(), open(k, "r").read().splitlines(), "a"+k, "b"+k):
            print(l.rstrip("\n"))


def run():
    p = subprocess.Popen(["/usr/bin/pacman", "-Q"], stdout=subprocess.PIPE, universal_newlines=True)
    packages = []
    for line in p.stdout:
        packages.append(line.split()[0])

    print("read package list")

    mtree = get_mtrees_parallel(packages)

    print("read mtree")

    files = []
    for k, v in mtree.items():
        if v['type'] == 'file':
            files.append(k)

    print("got file list")

    digests = get_digest_parallel(files)

    print("got digest")

    modified_files_list = []
    for k, v in mtree.items():
        try:
            st = os.lstat(k)
        except PermissionError as e:
            print(e)

        mode = oct(stat.S_IMODE(st.st_mode))[2:]
        uid = str(st.st_uid)
        gid = str(st.st_gid)
        if v['type'] == 'file':
            if not stat.S_ISREG(st.st_mode):
                print(k, "file type changed", v['type'], "to", st)
            if k not in digests:
                print(k, "no digest culculated")
            elif v['sha256digest'] != digests[k]:
                print(k, "hash changed:", v['sha256digest'], "to", digests[k])
                modified_files_list.append((k, v))
            if mode != v['mode']:
                print(k, "mode modified", v['mode'], "to", mode)
            if uid != v['uid']:
                print(k, "uid modified", v['uid'], "to", uid)
            if gid != v['gid']:
                print(k, "gid modified", v['gid'], "to", gid)
        elif v['type'] == 'dir':
            if not stat.S_ISDIR(st.st_mode):
                print(k, "file type changed", v['type'], "to", st)
            if mode != v['mode']:
                print(k, "mode modified", v['mode'], "to", mode)
            if uid != v['uid']:
                print(k, "uid modified", v['uid'], "to", uid)
            if gid != v['gid']:
                print(k, "gid modified", v['gid'], "to", gid)
        elif v['type'] == 'link':
            if not stat.S_ISLNK(st.st_mode):
                print(k, "file type changed", v['type'], "to", st)
            link = os.path.normpath(os.path.join(os.path.dirname(k), v['link']))
            actual = os.path.normpath(os.path.join(os.path.dirname(k), os.readlink(k)))
            if link != actual:
                print(k, "link changed", link, "to", actual)
            if mode != v['mode']:
                print(k, "mode modified", v['mode'], "to", mode)
            if uid != v['uid']:
                print(k, "uid modified", v['uid'], "to", uid)
            if gid != v['gid']:
                print(k, "gid modified", v['gid'], "to", gid)
        else:
            print(k, "unknown file type", v['type'])

    for k, v in modified_files_list:
        print_diff(k, v)


run()
