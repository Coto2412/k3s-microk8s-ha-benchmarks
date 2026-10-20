#!/usr/bin/env python3
"""Continuidad de la recoleccion en una ventana de metadatos (JSON con distribution, t_inicio, t_fin)."""
import sys, json, math, urllib.parse, urllib.request

PROM = "http://127.0.0.1:9090/api/v1/query"
INTERVALO_S = 10
MIN_COBERTURA, MAX_HUECO_S, MAX_DOWN = 0.99, 30, 0.01

meta = json.load(open(sys.argv[1]))
n_targets = int(sys.argv[2]) if len(sys.argv) > 2 else 7
t0, t1 = meta["t_inicio"], meta["t_fin"]
dt = t1 - t0
q = urllib.parse.urlencode({"query": f"up[{math.ceil(dt)}s]", "time": t1})
d = json.load(urllib.request.urlopen(f"{PROM}?{q}", timeout=15))
assert d["status"] == "success", d

series = d["data"]["result"]
distros = sorted({s["metric"].get("distribution", "(sin etiqueta)") for s in series})
propias = [s for s in series if s["metric"].get("distribution") == meta["distribution"]]
ok = len(propias) == n_targets and distros == [meta["distribution"]]
print(f"ventana {dt:.0f} s, distribuciones en la ventana: {distros}, targets de {meta['distribution']}: {len(propias)} (esperados {n_targets})")

esperadas = dt / INTERVALO_S
for s in sorted(propias, key=lambda s: (s["metric"]["job"], s["metric"]["instance"])):
    v = [(float(t), x) for t, x in s["values"] if t0 <= float(t) <= t1]
    ts = [t for t, _ in v]
    hueco = max([b - a for a, b in zip(ts, ts[1:])] or [0])
    down = sum(1 for _, x in v if x == "0")
    cob, frac = len(v) / esperadas, down / len(v)
    bueno = cob >= MIN_COBERTURA and hueco <= MAX_HUECO_S and frac <= MAX_DOWN
    ok &= bueno
    m = s["metric"]
    print(f"{'OK  ' if bueno else 'FALLA'} {m['job']:<20} {m['instance']:<22} role={m.get('role', '-'):<5} "
          f"muestras={len(v)}/{esperadas:.0f} cobertura={cob:.3f} hueco_max={hueco:.1f}s up0={down}")
sys.exit(0 if ok else 1)
