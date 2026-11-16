"""Análisis retrospectivo del desfase de ≈ 1 W (E6, capa 1). Exploratorio: orienta el diagnóstico, no concluye.

Uso (desde la raíz del repositorio):
  python3 -m analysis.desfase_retro --salida analysis/salidas/2026-11-16_desfase_retro
  python3 -m analysis.desfase_retro --autotest

Lee los datos versionados de las jornadas 1 a 4, la validación integral (VI), las corridas de control y el reposo del host.
Calcula en la fase estable de cada corrida la potencia RAPL y las covariables que hay en la ventana de Prometheus y en los
metadatos. Agrupa los niveles de potencia con el idle de cada sesión y mide qué covariables acompañan al nivel.
"""
import argparse, csv, glob, json, os, statistics, sys, time

from scipy.stats import spearmanr

from analysis.recursos_latencia import cargar_gz
from k6.lib.comun import RAIZ

# (jornada, carpeta con {d} = distribución, configuración); ver data/README.md y el informe 3, sección 5
SESIONES = [
    ("J1", "data/exploratorio/2026-10-26_{d}", "inicial"),
    ("J2", "data/pilotos/2026-10-27_{d}", "inicial"),
    ("VI", "data/verificacion/2026-10-27_{d}_T-22", "definitiva"),
    ("J3", "data/pilotos/2026-10-28_{d}", "definitiva"),
    ("J4", "data/pilotos/2026-11-02_{d}", "definitiva"),
    ("J4c", "data/pilotos/2026-11-02_{d}_control", "definitiva"),
]
DIST = ("k3s", "microk8s")
SALTO_W = 0.3  # umbral propio: el mismo que define «mueve el nivel» en la regla del diagnóstico
GRUPOS_CPU = {"cpu_0_1": range(0, 2), "cpu_2_7": range(2, 8), "cpu_8_15": range(8, 16)}  # k6, vcpupin de las VMs, resto
MODOS = ("user", "nice", "system", "iowait", "irq", "softirq", "steal")


def tramo(pts, t0, t1):
    return [(t, v) for t, v in pts if t0 <= t <= t1]


def tasa(pts):
    """Variación por segundo de un contador entre la primera y la última muestra (None si hay < 2 o reinicio)."""
    if len(pts) < 2 or pts[-1][1] < pts[0][1] or pts[-1][0] == pts[0][0]:
        return None
    return (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])


def media(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def leer_ventana(ruta, t0, t1):
    """Series de la ventana recortadas a la fase estable: {(nombre, job, instancia, etiquetas extra): [(t, v)]}."""
    out, nombres = {}, set()
    for sel in cargar_gz(ruta)["resultado"].values():
        for s in sel:
            m = s["metric"]
            nombres.add(m["__name__"])
            extra = tuple(sorted((k, v) for k, v in m.items() if k not in ("__name__", "job", "instance", "distribution", "role")))
            out[(m["__name__"], m.get("job"), m.get("instance"), extra)] = tramo([(float(t), float(v)) for t, v in s["values"]], t0, t1)
    return out, nombres


def sel(series, nombre, job=None, **et):
    return {k: v for k, v in series.items() if k[0] == nombre and (job is None or k[1] == job)
            and all(dict(k[3]).get(a) == b for a, b in et.items())}


def cpu_host(series):
    """Fracción de la CPU total del host por modo, guest aparte, y fracción ocupada por grupo de núcleos y por núcleo."""
    d = {}
    for k, pts in sel(series, "node_cpu_seconds_total", "node_exporter_host").items():
        e = dict(k[3])
        r = tasa(pts)
        if r is not None:
            d.setdefault(int(e["cpu"]), {})[e["mode"]] = r
    if not d:
        return {}, {}
    total = sum(sum(m.values()) for m in d.values())
    r = {f"host_{m}": sum(c.get(m, 0) for c in d.values()) / total for m in MODOS}
    g = sum(tasa(p) or 0 for p in sel(series, "node_cpu_guest_seconds_total", "node_exporter_host").values())
    r["host_guest"] = g / total
    nucleo = {c: 1 - m.get("idle", 0) / sum(m.values()) for c, m in d.items()}
    for nom, rango in GRUPOS_CPU.items():
        r[f"host_ocupada_{nom}"] = media([nucleo.get(c) for c in rango])
    return r, nucleo


def cpu_vms(series):
    por_vm = {}
    for k, pts in sel(series, "node_cpu_seconds_total", "node_exporter_vms").items():
        e = dict(k[3])
        x = tasa(pts)
        if x is not None:
            por_vm.setdefault(k[2], {}).setdefault(e["mode"], 0.0)
            por_vm[k[2]][e["mode"]] += x
    if not por_vm:
        return {}
    ocup = [1 - m.get("idle", 0) / sum(m.values()) for m in por_vm.values()]
    steal = [m.get("steal", 0) / sum(m.values()) for m in por_vm.values()]
    return {"vm_ocupada_media": media(ocup), "vm_ocupada_max": max(ocup), "vm_steal_media": media(steal)}


def memoria_host(series):
    def m(nombre):
        pts = [v for p in sel(series, nombre, "node_exporter_host").values() for _, v in p]
        return statistics.mean(pts) / 2**20 if pts else None
    tot, libre = m("node_memory_SwapTotal_bytes"), m("node_memory_SwapFree_bytes")
    return {"host_memavailable_mb": m("node_memory_MemAvailable_bytes"), "host_swap_usado_mb": tot - libre if tot is not None and libre is not None else None,
            "host_swapcached_mb": m("node_memory_SwapCached_bytes"), "host_anonhugepages_mb": m("node_memory_AnonHugePages_bytes"),
            "host_cached_mb": m("node_memory_Cached_bytes")}


def red_disco(series):
    def dev(nombre, pred):
        xs = [tasa(p) for k, p in sel(series, nombre, "node_exporter_host").items() if pred(dict(k[3]).get("device", ""))]
        xs = [x for x in xs if x is not None]
        return sum(xs) if xs else None
    r = {}
    for nom, pred in (("wifi", lambda d: d.startswith("wl")), ("lab", lambda d: d.startswith("vnet")),
                      ("contenedores", lambda d: d.startswith(("docker", "veth", "br-", "incus")))):
        rx, tx = dev("node_network_receive_bytes_total", pred), dev("node_network_transmit_bytes_total", pred)
        r[f"red_{nom}_Bps"] = None if rx is None and tx is None else (rx or 0) + (tx or 0)
    r["disco_escrito_Bps"] = dev("node_disk_written_bytes_total", lambda d: d.startswith("nvme"))
    # cada veth es un contenedor con red en el host (incus/docker), aunque no haya tráfico
    r["veth_presentes"] = len({dict(k[3]).get("device") for k in sel(series, "node_network_receive_bytes_total", "node_exporter_host")
                               if dict(k[3]).get("device", "").startswith("veth")})
    return r


def scaph(series):
    f = [v for p in sel(series, "scaph_host_cpu_frequency").values() for _, v in p]
    carga = [v for p in sel(series, "node_load1", "node_exporter_host").values() for _, v in p]
    return {"frecuencia_mhz": statistics.mean(f) if f else None, "carga1_host": statistics.mean(carga) if carga else None}


def ms_reloj(txt):
    """'0.000750983 seconds fast of NTP time' -> ms con signo (+ adelantado)."""
    try:
        x = float(txt.split()[0]) * 1000
        return x if "fast" in txt else -x
    except (AttributeError, ValueError, IndexError):
        return None


def leer_corrida(ruta_meta, jornada, config):
    m = json.load(open(ruta_meta))
    t0, t1 = m["t_inicio"], m["t_fin"]
    eh = m.get("estado_host") or {}
    top = eh.get("procesos_top_cpu") or []
    fila = {"jornada": jornada, "configuracion": config, "distribucion": m["distribution"], "escenario": m["escenario"],
            "repeticion": m["repeticion"], "archivo": os.path.relpath(ruta_meta, RAIZ),
            "hora_inicio": time.strftime("%Y-%m-%d %H:%M", time.localtime(t0)), "potencia_W": m["rapl"]["potencia_media_W"],
            "temperatura_C": eh.get("temperatura_cpu_C"), "carga1_metadatos": eh.get("carga_1min"),
            "memoria_disponible_mb_inicio": eh.get("memoria_disponible_mb"),
            "ksmd_en_top10": any(p[0] == "ksmd" for p in top),
            "ksmd_cpu_pct": next((float(p[1].replace(",", ".")) for p in top if p[0] == "ksmd"), 0.0),
            "top10": " ".join(f"{p[0]}:{p[1]}" for p in top),
            "reloj_host_ms": ms_reloj(((m.get("reloj_antes") or {}).get("host") or {}).get("System time")),
            "reloj_espera_s": m.get("reloj_espera_s")}
    ruta_v = os.path.join(RAIZ, m["ventana_prometheus"]["archivo"])
    series, nombres = leer_ventana(ruta_v, t0, t1)
    ch, nucleo = cpu_host(series)
    for parte in (ch, cpu_vms(series), memoria_host(series), red_disco(series), scaph(series)):
        fila.update(parte)
    muestras = [len(p) for p in sel(series, "node_cpu_seconds_total", "node_exporter_host").values()]
    contenido = {"archivo": fila["archivo"], "series": len(series), "muestras_cpu_host_fase_estable": min(muestras) if muestras else 0,
                 "guest_host": "node_cpu_guest_seconds_total" in nombres,
                 "scaphandre_por_proceso": any(n.startswith("scaph_process") for n in nombres),
                 "kube_state_metrics": any(n.startswith("kube_") for n in nombres),
                 "familias": len(nombres)}
    return fila, {c: round(v, 5) for c, v in sorted(nucleo.items())}, contenido


def niveles(valores, salto=SALTO_W):
    """Agrupa valores ordenados: un salto mayor que `salto` abre un nivel nuevo. Devuelve {valor: nivel (1 = el más bajo)}."""
    orden = sorted(valores)
    nivel, out = 1, {}
    for i, v in enumerate(orden):
        if i and v - orden[i - 1] > salto:
            nivel += 1
        out[v] = nivel
    return out


def reposo():
    filas = []
    for f in sorted(glob.glob(os.path.join(RAIZ, "data/reposo/reposo_host_s*.json"))):
        if "boost" in f:
            continue
        d = json.load(open(f))
        for w in d["ventanas"]:
            filas.append({"jornada": "reposo", "configuracion": "sin VMs", "distribucion": "-", "escenario": "reposo_host",
                          "repeticion": f"{d['sesion']}.{w['ventana']}", "archivo": os.path.relpath(f, RAIZ),
                          "hora_inicio": time.strftime("%Y-%m-%d %H:%M", time.localtime(w["t_inicio"])),
                          "potencia_W": w["potencia_media_W"], "temperatura_C": w["sondas"].get("temperatura_cpu_C"),
                          "carga1_metadatos": w["sondas"].get("carga_1min")})
    return filas


def numericas(filas):
    claves = []
    for f in filas:
        for k, v in f.items():
            if k not in claves and isinstance(v, (int, float)) and not isinstance(v, bool) and k not in ("repeticion", "potencia_W"):
                claves.append(k)
    return claves + ["ksmd_en_top10"]


def analizar(corridas):
    """Sesiones (jornada × distribución) con su nivel y covariables que acompañan al nivel (solo idle, sin tráfico)."""
    ses = {}
    for f in corridas:
        ses.setdefault((f["jornada"], f["distribucion"]), []).append(f)
    tabla = []
    for (j, d), fs in ses.items():
        fila = {"jornada": j, "distribucion": d, "configuracion": fs[0]["configuracion"], "corridas": len(fs),
                "hora_primera": min(f["hora_inicio"] for f in fs)}
        for esc in ("idle", "media", "alta"):
            p = [f["potencia_W"] for f in fs if f["escenario"] == esc]
            fila[f"{esc}_W"] = round(statistics.mean(p), 3) if p else None
            fila[f"{esc}_rango_W"] = round(max(p) - min(p), 3) if len(p) > 1 else None
        idle = [f for f in fs if f["escenario"] == "idle"]
        for k in numericas(idle):
            fila[k] = media([float(f.get(k)) if f.get(k) is not None else None for f in idle])
        tabla.append(fila)
    con_idle = [s for s in tabla if s["idle_W"] is not None]
    nv = niveles([s["idle_W"] for s in con_idle])
    for s in tabla:
        if s["idle_W"] is not None:
            s["nivel"] = nv[s["idle_W"]]
        else:  # J4c (solo media): mismo clúster y día que J4, se le asigna el nivel de J4
            s["nivel"] = next((x["nivel"] for x in tabla if x["jornada"] == s["jornada"].rstrip("c") and x["distribucion"] == s["distribucion"]
                               and x.get("nivel")), None)
    saltos = []
    for f in corridas:
        celda = [g["potencia_W"] for g in ses[(f["jornada"], f["distribucion"])] if g["escenario"] == f["escenario"]]
        if len(celda) > 2 and abs(f["potencia_W"] - statistics.median(celda)) > SALTO_W:
            saltos.append({k: f[k] for k in ("jornada", "distribucion", "escenario", "repeticion", "hora_inicio", "potencia_W")}
                          | {"mediana_celda_W": statistics.median(celda)})
    asoc = []
    for k in numericas([f for f in corridas if f["escenario"] == "idle"]):
        pares = [(s["idle_W"], s[k]) for s in con_idle if s.get(k) is not None]
        if len(pares) < 4 or len({b for _, b in pares}) < 2:
            continue
        rho, p = spearmanr([a for a, _ in pares], [b for _, b in pares])
        por_nivel = {}
        for s in con_idle:
            if s.get(k) is not None:
                por_nivel.setdefault(s["nivel"], []).append(s[k])
        ns = sorted(por_nivel)
        mono = all(min(por_nivel[b]) > max(por_nivel[a]) for a, b in zip(ns, ns[1:])) or \
            all(max(por_nivel[b]) < min(por_nivel[a]) for a, b in zip(ns, ns[1:]))
        asoc.append({"covariable": k, "sesiones": len(pares), "spearman_rho": round(rho, 3), "p_nominal": round(p, 4),
                     "separa_niveles": mono, **{f"nivel{n}_media": round(statistics.mean(v), 4) for n, v in por_nivel.items()}})
    asoc.sort(key=lambda r: (-r["separa_niveles"], -abs(r["spearman_rho"])))
    return sorted(tabla, key=lambda s: (s["hora_primera"], s["distribucion"])), saltos, asoc


def escribir(filas, ruta):
    claves = []
    for f in filas:
        claves += [k for k in f if k not in claves]
    with open(ruta, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=claves)
        w.writeheader()
        for f in filas:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in f.items()})


def autotest():
    assert niveles([4.16, 4.17, 4.96, 5.75, 5.88]) == {4.16: 1, 4.17: 1, 4.96: 2, 5.75: 3, 5.88: 3}
    assert tasa([(0, 10), (10, 30)]) == 2 and tasa([(0, 10), (10, 5)]) is None and tasa([(0, 1)]) is None
    assert ms_reloj("0.000750983 seconds fast of NTP time") > 0 > ms_reloj("0.0005 seconds slow of NTP time")
    serie = {("node_cpu_seconds_total", "node_exporter_host", "h", (("cpu", "0"), ("mode", "idle"))): [(0, 0), (10, 7)],
             ("node_cpu_seconds_total", "node_exporter_host", "h", (("cpu", "0"), ("mode", "user"))): [(0, 0), (10, 3)]}
    r, n = cpu_host(serie)
    assert abs(r["host_user"] - 0.3) < 1e-9 and abs(n[0] - 0.3) < 1e-9
    print("autotest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida")
    ap.add_argument("--autotest", action="store_true")
    a = ap.parse_args()
    if a.autotest:
        return autotest()
    if not a.salida:
        ap.error("falta --salida")
    corridas, nucleos, contenido = [], [], []
    for j, patron, config in SESIONES:
        for d in DIST:
            for ruta in sorted(glob.glob(os.path.join(RAIZ, patron.format(d=d), "metadatos", "*.json"))):
                if "fallo" in os.path.basename(ruta) or ruta.endswith(".observador.json"):
                    continue
                f, n, c = leer_corrida(ruta, j, config)
                corridas.append(f)
                nucleos.append({"archivo": f["archivo"], "potencia_W": f["potencia_W"], **{f"cpu{k}": v for k, v in n.items()}})
                contenido.append(c)
    sesiones, saltos, asoc = analizar(corridas)
    os.makedirs(a.salida, exist_ok=True)
    escribir(corridas + reposo(), os.path.join(a.salida, "corridas.csv"))
    escribir(nucleos, os.path.join(a.salida, "nucleos.csv"))
    escribir(contenido, os.path.join(a.salida, "contenido_ventanas.csv"))
    escribir(sesiones, os.path.join(a.salida, "sesiones.csv"))
    escribir(saltos, os.path.join(a.salida, "saltos_en_sesion.csv"))
    escribir(asoc, os.path.join(a.salida, "covariables.csv"))
    print(f"{len(corridas)} corridas, {len(sesiones)} sesiones; salida en {a.salida}")
    for s in sesiones:
        print(f"  {s['jornada']:4} {s['distribucion']:9} nivel {s['nivel']}  idle {s['idle_W']}  media {s['media_W']}  alta {s['alta_W']}")
    print("Saltos dentro de una sesión:", [(x["jornada"], x["distribucion"], x["escenario"], x["repeticion"], x["potencia_W"]) for x in saltos])
    print("Covariables que separan los niveles:", [x["covariable"] for x in asoc if x["separa_niveles"]])


if __name__ == "__main__":
    sys.exit(main())
