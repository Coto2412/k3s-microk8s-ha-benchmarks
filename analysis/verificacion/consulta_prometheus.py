#!/usr/bin/env python3
"""Compara una ventana de ventana_energia.py (JSON) con lo que Prometheus guardo en esa ventana."""
import sys, json, urllib.parse, urllib.request

PROM = "http://127.0.0.1:9090/api/v1/"
M = "scaph_host_energy_microjoules"

def get(path, **params):
    url = PROM + path + "?" + urllib.parse.urlencode(params)
    d = json.load(urllib.request.urlopen(url, timeout=10))
    assert d["status"] == "success", d
    return d["data"]["result"]

def interp(s, t):
    for (ta, va), (tb, vb) in zip(s, s[1:]):
        if ta <= t <= tb:
            return va + (vb - va) * (t - ta) / (tb - ta)
    raise ValueError(f"t={t} fuera de las muestras de Prometheus")

w = json.load(open(sys.argv[1]))
t0, t1, dt = w["t_inicio"], w["t_fin"], w["dt_s"]
r = get("query", query=f"{M}[{int(dt) + 60}s]", time=t1 + 30)
assert len(r) == 1, f"se esperaba 1 serie, hay {len(r)}"
s = [(float(t), float(v)) for t, v in r[0]["values"]]
muestras = [(t, v) for t, v in s if t0 <= t <= t1]

inc = get("query", query=f"increase({M}[{int(round(dt))}s])", time=t1)
res = {"muestras_en_ventana": len(muestras)}
e_interp = interp(s, t1) - interp(s, t0)
res["prom_interpolado_uj"] = round(e_interp)
res["prom_interpolado_W"] = round(e_interp / 1e6 / dt, 3)
if inc:
    res["prom_increase_uj"] = round(float(inc[0]["value"][1]))
    res["prom_increase_W"] = round(res["prom_increase_uj"] / 1e6 / dt, 3)
for k in ("raw_pkg0_uj", "scaph_host_energy_microjoules_uj"):
    res[f"prom_interpolado_vs_{k}_%"] = round((e_interp / w[k] - 1) * 100, 3)
    if "prom_increase_uj" in res:
        res[f"prom_increase_vs_{k}_%"] = round((res["prom_increase_uj"] / w[k] - 1) * 100, 3)
print(json.dumps(res, indent=2))
assert len(muestras) >= 5, "pocas muestras en la ventana: Prometheus no scrapeo scaphandre"
