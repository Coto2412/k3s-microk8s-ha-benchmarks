#!/usr/bin/env python3
"""Desfase de cada VM respecto del reloj del host, por SSH persistente (cota = mitad del RTT de cada sonda)."""
import argparse, json, statistics, subprocess, time

ap = argparse.ArgumentParser()
ap.add_argument("--llave", required=True)
ap.add_argument("--usuario", required=True)
ap.add_argument("--ips", nargs="+", default=["192.168.100.11", "192.168.100.12", "192.168.100.13"])
ap.add_argument("--sondas", type=int, default=30)
a = ap.parse_args()

def abrir(ip):
    return subprocess.Popen(
        ["ssh", "-i", a.llave, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         "-o", "LogLevel=ERROR", f"{a.usuario}@{ip}", "while read x; do date +%s.%N; done"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

def sonda(p):
    t0 = time.time()
    p.stdin.write("\n"); p.stdin.flush()
    vm = float(p.stdout.readline())
    t1 = time.time()
    return vm - (t0 + t1) / 2, (t1 - t0) / 2

procs = {ip: abrir(ip) for ip in a.ips}
for p in procs.values():
    sonda(p)
res = {ip: [] for ip in a.ips}
for _ in range(a.sondas):
    for ip, p in procs.items():
        res[ip].append(sonda(p))
        time.sleep(0.2)
for p in procs.values():
    p.stdin.close()
out = {}
for ip, v in res.items():
    off = [o for o, _ in v]
    cota = [c for _, c in v]
    out[ip] = {"mediana_ms": round(statistics.median(off) * 1e3, 3), "min_ms": round(min(off) * 1e3, 3),
               "max_ms": round(max(off) * 1e3, 3), "cota_mediana_ms": round(statistics.median(cota) * 1e3, 3),
               "cota_max_ms": round(max(cota) * 1e3, 3), "sondas": len(v)}
print(json.dumps(out, indent=2))
