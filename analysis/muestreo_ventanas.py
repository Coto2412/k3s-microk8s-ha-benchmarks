"""T-21.1: muestras de Prometheus que caen en la fase estable de cada corrida y regularidad del scrape."""
import glob, gzip, json, statistics as st, sys
from collections import defaultdict

patron = sys.argv[1] if len(sys.argv) > 1 else "data/pilotos/*/metadatos/piloto_*_r0?.json"
filas = []
for m in sorted(glob.glob(patron)):
    meta = json.load(open(m))
    ven = json.load(gzip.open(meta["ventana_prometheus"]["archivo"]))
    t0, t1 = meta["t_inicio"], meta["t_fin"]
    cuentas = defaultdict(list)
    saltos = []
    for expr in ven["resultado"].values():
        for s in expr:
            job, nombre = s["metric"].get("job"), s["metric"].get("__name__")
            ts = [float(t) for t, _ in s["values"] if t0 <= float(t) <= t1]
            cpu0 = nombre == "node_cpu_seconds_total" and s["metric"].get("cpu") == "0" and s["metric"].get("mode") == "idle"
            primera = nombre in ("scaph_socket_power_microwatts", "kube_node_status_condition") and not cuentas[(job, nombre)]
            if cpu0 or primera:
                cuentas[(job, nombre)].append(len(ts))
                saltos += [b - a for a, b in zip(ts, ts[1:])]
    filas.append((meta["distribution"], meta["escenario"], meta["repeticion"], dict(cuentas), saltos))

todas = defaultdict(list)
for _, _, _, c, _ in filas:
    for k, v in c.items():
        todas[k] += v
print(f"{len(filas)} ventanas de {patron}")
for k, v in sorted(todas.items(), key=str):
    print(f"  {k[0]:>18} {k[1]:<32} muestras por serie en la ventana: min {min(v)}, max {max(v)}, mediana {st.median(v)} (n series-ventana = {len(v)})")
s = [x for f in filas for x in f[4]]
print(f"intervalo entre muestras consecutivas: min {min(s):.3f} s, max {max(s):.3f} s, mediana {st.median(s):.3f} s, n = {len(s)}")
print("intervalos fuera de 10 ± 0,5 s:", sum(1 for x in s if abs(x - 10) > 0.5))
