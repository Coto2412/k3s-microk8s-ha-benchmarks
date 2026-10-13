#!/usr/bin/env python3
"""Mide energia de una ventana: contador crudo RAPL package-0 y metricas de Scaphandre."""
import sys, time, json, re, urllib.request
BASE = "/sys/class/powercap/intel-rapl:0/"
MAX = int(open(BASE + "max_energy_range_uj").read())

def raw():
    return int(open(BASE + "energy_uj").read())

def scaph():
    txt = urllib.request.urlopen("http://127.0.0.1:8080/metrics", timeout=5).read().decode()
    out = {}
    for k in ("scaph_host_energy_microjoules", "scaph_socket_energy_microjoules"):
        m = re.search(r"^" + k + r"(?:\{[^}]*\})?\s+([0-9.eE+-]+)", txt, re.M)
        out[k] = int(float(m.group(1))) if m else None
    return out

def delta(a, b):
    d = b - a
    return d + MAX if d < 0 else d

dur = float(sys.argv[1]) if len(sys.argv) > 1 else 60
t0, r0, s0 = time.time(), raw(), scaph()
time.sleep(dur)
t1, r1, s1 = time.time(), raw(), scaph()
dt = t1 - t0
res = {"t_inicio": t0, "t_fin": t1, "dt_s": round(dt, 3),
       "raw_pkg0_uj": delta(r0, r1)}
res["raw_pkg0_W"] = round(res["raw_pkg0_uj"] / 1e6 / dt, 3)
for k in s0:
    if s0[k] is not None and s1[k] is not None:
        res[k + "_uj"] = delta(s0[k], s1[k])
        res[k + "_W"] = round(res[k + "_uj"] / 1e6 / dt, 3)
print(json.dumps(res, indent=2))
