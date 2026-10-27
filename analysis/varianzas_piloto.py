"""T-21.4: componentes de varianza de la potencia de los pilotos (boost apagado: 26 y 27-oct)."""
import glob, json, statistics as st, datetime
from collections import defaultdict

celdas = defaultdict(list)
for f in sorted(glob.glob("data/exploratorio/2026-10-26_*/metadatos/*.json") + glob.glob("data/pilotos/*/metadatos/*.json")):
    if f.endswith("observador.json"):
        continue
    d = json.load(open(f))
    dia = datetime.datetime.fromtimestamp(d["t_inicio"]).strftime("%d-oct")
    celdas[(dia, d["distribution"], d["escenario"])].append(d["rapl"]["potencia_media_W"])

print("celda (día, distribución, escenario): media y sd de 3 repeticiones")
sds = {}
for k, v in sorted(celdas.items()):
    sds[k] = st.stdev(v)
    print(f"  {k}: n={len(v)} media {st.mean(v):.3f} W, sd {sds[k]:.3f} W")
sin = [s for k, s in sds.items() if k != ("26-oct", "k3s", "media")]
print(f"sd dentro de celda, mediana {st.median(sds.values()):.3f} W; máxima {max(sds.values()):.3f} W (K3s media 26-oct)")
print(f"sd agrupada sin la celda dividida: {(sum(s*s for s in sin)/len(sin))**0.5:.3f} W; con ella: {(sum(s*s for s in sds.values())/len(sds))**0.5:.3f} W")

print("\nentre días, misma distribución y escenario (medias de celda)")
for dist in ("k3s", "microk8s"):
    for esc in ("idle", "media", "alta"):
        m = [st.mean(celdas[(dia, dist, esc)]) for dia in ("26-oct", "27-oct")]
        print(f"  {dist:8} {esc:5}: 26-oct {m[0]:.3f}  27-oct {m[1]:.3f}  diferencia {m[1]-m[0]:+.3f} W")

print("\nentre distribuciones (MicroK8s - K3s), misma sesión (medias de celda)")
for dia in ("26-oct", "27-oct"):
    for esc in ("idle", "media", "alta"):
        a, b = st.mean(celdas[(dia, "k3s", esc)]), st.mean(celdas[(dia, "microk8s", esc)])
        print(f"  {dia} {esc:5}: {b-a:+.3f} W")
