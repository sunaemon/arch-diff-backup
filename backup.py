#!/usr/bin/python
import sys
import re
import os
import subprocess
import datetime
import difflib

def debug_message(*objects):
    print("[DEBUG]", *objects, file=sys.stderr)

def warning_message(*objects):
    print("[WARNING]", *objects, file=sys.stderr)

def error_message(*objects):
    print("[ERROR]", *objects, file=sys.stderr)

def get_pkg_name(pkg):
    p = subprocess.Popen(["/usr/bin/pacman", "-Qi", pkg], stdout=subprocess.PIPE)

    prop = {}
    for line in p.stdout:
        m = re.match(r"^([\w\s]*?)\s* : (.*)$", line.decode())
        if m:
            prop[m.group(1)] = m.group(2)

    return prop["Name"] + "-" + prop["Version"] + "-" + prop["Architecture"] + ".pkg.tar.xz"

def write_diff(path, f):
    s = subprocess.check_output(["/usr/bin/pacman", "-Qo", path]).decode();
    m = re.match("^\S+ is owned by (?P<pkg>\S+) \S*$", s)
    pkg_path = "/var/cache/pacman/pkg/" + get_pkg_name(m.group("pkg"))
    tar = subprocess.Popen(["/bin/tar", "xfO", pkg_path, path.lstrip('/')], stdout=subprocess.PIPE)

    difflib.unified_diff(
    diff = subprocess.Popen(["/bin/diff", "-u", "--label=" + path, "-", path], stdin=tar.stdout, stdout=subprocess.PIPE)
    patch, errs = diff.communicate()
    f.write(patch.decode())

patterns = [re.compile(line.rstrip("\n")) for line in open("ignore", "r") if not re.match(r"^#|^\s*$", line)]
def is_ignored(path):
    for pattern in patterns:
        if pattern.match(path):
            debug_message(path, "is ignored because it matched to", pattern)
            return True
    return False

save_dir = "saya-" + datetime.datetime.now().isoformat()
os.makedirs(save_dir)
arch_diff = open(save_dir + "/arch-diff", "w")
patch = open(save_dir + "/patch", "w")

#p = subprocess.Popen(["/usr/local/bin/arch-diff"], stdout=subprocess.PIPE);
for line in sys.stdin: #p.stdout:
    arch_diff.write(line)
    m = re.match(r"^\[modified\]\s+(?P<type>size|type|link|md5|uid|gid|mode) \S+ != \S+:\s+(?P<path>.*)$", line)
    if m:
        if not is_ignored(m.group("path")):
            write_diff(m.group("path"), patch)
            debug_message("modified", m.group("path"))
        continue
    m = re.match(r"^\[untracked\]\s+(?P<path>.*)$", line)
    if m:
        if not is_ignored(m.group("path")):
            debug_message("untracked", m.group("path"))
        continue

    debug_message("unused", line)

arch_diff.close()
