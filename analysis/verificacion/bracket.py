#!/usr/bin/env python3
import re, time, urllib.request
B = "/sys/class/powercap/intel-rapl:0/energy_uj"
def raw(): return int(open(B).read())
def sock():
    t = urllib.request.urlopen("http://127.0.0.1:8080/metrics", timeout=5).read().decode()
    m = re.search(r'^scaph_socket_energy_microjoules\{[^}]*\}\s+([0-9.eE+-]+)', t, re.M)
    return int(float(m.group(1)))
for i in range(20):
    a = raw(); s = sock(); b = raw()
    print(i, a, s, b, "entre" if a <= s <= b else "FUERA", s - a, s - b)
    time.sleep(3)
