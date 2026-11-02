"""CPU, RAM, energía y latencia por corrida en la fase estable, y tiempos de recuperación (informe 3).

Uso (desde la raíz del repositorio; las figuras se generan aparte con analysis.figuras):
  python3 -m analysis.recursos_latencia --sesion data/pilotos/2026-10-28_k3s --sesion data/pilotos/2026-10-28_microk8s \
      --salida analysis/salidas/2026-10-28
  python3 -m analysis.recursos_latencia --autotest

La latencia de la fase estable sale del JSON crudo de k6 (data/k6-crudo/, no versionado); se guarda en `cache_latencia.json`
junto al CSV para poder repetir el análisis sin el crudo. El resumen de k6 (`*.resumen.json`) es de la ejecución completa
(rampa, fase estable y descenso) y no trae p99, por eso va en columnas `res_*` aparte.
"""
import argparse, csv, datetime, glob, gzip, json, math, os, statistics, sys

from k6.lib import fallo
from k6.lib.agregado import pct
from k6.lib.comun import RAIZ

METRICAS_T = ["http_req_blocked", "http_req_connecting", "http_req_waiting", "http_req_sending", "http_req_receiving"]
HIST_BASE_MS, HIST_RAZON = 0.05, 1.02  # contenedores geométricos: error relativo de un cuantil <= 2 %
ORDEN_ESC = {"idle": 0, "media": 1, "alta": 2}
NOMBRE = {"k3s": "K3s", "microk8s": "MicroK8s"}


def cargar_gz(ruta):
    with gzip.open(ruta, "rt") as fh:
        return json.load(fh)


def series_ventana(ruta):
    """{(job, instance, __name__, cpu|modo...): [(t, valor)]} de node_cpu_seconds_total y memoria desde la ventana de Prometheus."""
    sel = next(iter(cargar_gz(ruta)["resultado"].values()))
    out = {}
    for s in sel:
        m = s["metric"]
        if m["__name__"] in ("node_cpu_seconds_total", "node_memory_MemTotal_bytes", "node_memory_MemAvailable_bytes"):
            out[(m["job"], m["instance"], m["__name__"], m.get("cpu"), m.get("mode"))] = [(float(t), float(v)) for t, v in s["values"]]
    return out


def utilizacion_cpu(series, instancia, t0, t1):
    """1 - Δidle/Δtotal entre la primera muestra >= t0 y la última <= t1 (resolución de scrape: 10 s)."""
    por_t = {}
    for (job, inst, nom, cpu, modo), pts in series.items():
        if inst == instancia and nom == "node_cpu_seconds_total":
            for t, v in pts:
                if t0 <= t <= t1:
                    d = por_t.setdefault(t, {"idle": 0.0, "total": 0.0})
                    d["total"] += v
                    d["idle"] += v if modo == "idle" else 0.0
    ts = sorted(t for t, d in por_t.items() if d["total"] > 0)
    if len(ts) < 2:
        return None
    a, b = por_t[ts[0]], por_t[ts[-1]]
    return 1 - (b["idle"] - a["idle"]) / (b["total"] - a["total"])


def ram_usada_mb(series, instancia, t0, t1):
    """Media de MemTotal - MemAvailable en las muestras de la fase estable."""
    def v(nom):
        return {t: x for (j, i, n, c, m), pts in series.items() if i == instancia and n == nom for t, x in pts if t0 <= t <= t1}
    tot, disp = v("node_memory_MemTotal_bytes"), v("node_memory_MemAvailable_bytes")
    u = [(tot[t] - disp[t]) / 2**20 for t in tot if t in disp]
    return (statistics.mean(u), min(tot[t] - disp[t] for t in tot if t in disp) / 2**20, max(u)) if u else None


def histograma(d):
    """Histograma log-binneado de latencias (ms): {"base_ms", "razon", "bins": [[índice, cuenta]]}; el contenedor i cubre [base·razón^i, base·razón^(i+1))."""
    c = {}
    for v in d:
        i = max(0, int(math.log(max(v, 1e-9) / HIST_BASE_MS) / math.log(HIST_RAZON)))
        c[i] = c.get(i, 0) + 1
    return {"base_ms": HIST_BASE_MS, "razon": HIST_RAZON, "bins": sorted(c.items())}


def cuantil_hist(h, p):
    """Cuantil p (0 a 1) de un histograma de `histograma()`: punto medio geométrico del contenedor que lo contiene."""
    n = sum(c for _, c in h["bins"])
    objetivo, acum = p * n, 0
    for i, c in h["bins"]:
        acum += c
        if acum > objetivo:
            return h["base_ms"] * h["razon"] ** (i + 0.5)
    i = h["bins"][-1][0]
    return h["base_ms"] * h["razon"] ** (i + 0.5)


def latencia_ventana(ruta_crudo, t0, t1):
    """p50/p95/p99 de http_req_duration, medias de los componentes, fallidas y descartadas de [t0, t1) en el crudo de k6."""
    d, acum, falla, n, desc = [], {m: [0.0, 0] for m in METRICAS_T}, 0, 0, 0
    with gzip.open(ruta_crudo, "rt") as fh:
        for linea in fh:
            if not any(k in linea for k in ('"http_req_duration"', '"http_req_failed"', '"dropped_iterations"', *METRICAS_T)):
                continue
            p = json.loads(linea)
            if p.get("type") != "Point":
                continue
            t = datetime.datetime.fromisoformat(p["data"]["time"]).timestamp()
            if not t0 <= t < t1:
                continue
            m, v = p["metric"], p["data"]["value"]
            if m == "http_req_duration":
                d.append(v)
            elif m == "http_req_failed":
                n, falla = n + 1, falla + (1 if v else 0)
            elif m == "dropped_iterations":
                desc += int(v)
            elif m in acum:
                acum[m][0] += v
                acum[m][1] += 1
    d.sort()
    r = {"solicitudes": n, "fallidas": falla, "descartadas": desc}
    if d:
        r |= {"p50_ms": pct(d, .5), "p95_ms": pct(d, .95), "p99_ms": pct(d, .99), "max_ms": d[-1], "hist": histograma(d)}
    r |= {m.replace("http_req_", "") + "_media_ms": round(a / c, 4) for m, (a, c) in acum.items() if c}
    return r


def leer_corrida(meta_ruta, cache):
    m = json.load(open(meta_ruta))
    base = os.path.basename(meta_ruta)[:-5]
    sesion_dir = os.path.dirname(os.path.dirname(meta_ruta))
    t0, t1 = m["t_inicio"], m["t_fin"]
    fila = {"sesion": os.path.relpath(sesion_dir, RAIZ), "base": base, "tipo": m.get("tipo"), "distribucion": m["distribution"],
            "escenario": m["escenario"], "repeticion": m["repeticion"], "tasa": m["parametros"]["tasa"],
            "potencia_W": m["rapl"]["potencia_media_W"], "con_rtt": bool(m.get("rtt")), "con_cgroup": bool(m.get("cgroup_cp"))}
    ventana = os.path.join(RAIZ, m["ventana_prometheus"]["archivo"]) if m.get("ventana_prometheus") else None
    if ventana and os.path.exists(ventana):
        s = series_ventana(ventana)
        inst = {"host": "127.0.0.1:9100", "vm1": "192.168.100.11:9100", "vm2": "192.168.100.12:9100", "vm3": "192.168.100.13:9100"}
        for k, i in inst.items():
            u, r = utilizacion_cpu(s, i, t0, t1), ram_usada_mb(s, i, t0, t1)
            fila[f"cpu_{k}_pct"] = None if u is None else round(100 * u, 3)
            fila[f"ram_{k}_mb"] = None if r is None else round(r[0], 1)
        for k, u in (("cpu", "pct"), ("ram", "mb")):
            v = [fila[f"{k}_vm{i}_{u}"] for i in (1, 2, 3)]
            fila[f"{k}_vm_media"] = round(statistics.mean(v), 3) if None not in v else None
        disp = [x for (j, i, n, c, mo), pts in s.items() if i == inst["host"] and n == "node_memory_MemAvailable_bytes" for t, x in pts if t0 <= t <= t1]
        fila["ram_host_min_disp_mb"] = round(min(disp) / 2**20, 1) if disp else None
    fotos = [(m.get("recursos_host") or {}).get(k) or {} for k in ("inicio", "fin")]
    if all(x.get("qemu") and len(x["qemu"]) == 3 for x in fotos):
        for i in range(3):
            fila[f"rss_vm{i + 1}_mb"] = round(statistics.mean(x["qemu"][i]["VmRSS"] for x in fotos) / 1024, 1)
        fila["memtotal_mb"] = round(statistics.mean(x["memtotal_kb"] for x in fotos) / 1024, 1)
    res_ruta = os.path.join(RAIZ, m["k6"]["resumen"])
    if os.path.exists(res_ruta):
        mt = json.load(open(res_ruta))["metrics"]
        d = mt.get("http_req_duration", {})
        fila |= {"res_p50_ms": d.get("med"), "res_p95_ms": d.get("p(95)"), "res_avg_ms": d.get("avg"),
                 "res_fallidas": mt.get("http_req_failed", {}).get("passes", 0), "res_descartadas": mt.get("dropped_iterations", {}).get("count", 0)}
        for k in METRICAS_T:
            fila["res_" + k.replace("http_req_", "") + "_media_ms"] = mt.get(k, {}).get("avg")
    crudo = os.path.join(RAIZ, m["k6"]["json"])
    clave = f"{base}|{m['k6'].get('sha256_json')}|{t0}|{t1}"
    if m["escenario"] != "idle":
        if ("hist" not in cache.get(clave, {})) and os.path.exists(crudo):
            cache[clave] = latencia_ventana(crudo, t0, t1)
        for k, v in cache.get(clave, {}).items():
            if k != "hist":
                fila["ve_" + k] = v
    return fila


def sesion_metas(sesion):
    return sorted(f for f in glob.glob(os.path.join(sesion, "metadatos", "*.json")) if not f.endswith(".observador.json"))


def comprobar_configuracion(filas):
    """Una sola configuración por salida: la misma tasa por escenario y un solo tipo de corrida."""
    tasas = {}
    for f in filas:
        tasas.setdefault(f["escenario"], set()).add(f["tasa"])
    if any(len(v) > 1 for v in tasas.values()) or len({f["tipo"] for f in filas}) > 1:
        sys.exit(f"Configuraciones mezcladas (tasas por escenario {tasas}, tipos {sorted({str(f['tipo']) for f in filas})}): "
                 "analiza cada configuración por separado")


def escribir_csv(filas, ruta):
    cols = []
    for f in filas:
        cols += [c for c in f if c not in cols]
    with open(ruta, "w", newline="") as fh:
        w = csv.DictWriter(fh, cols)
        w.writeheader()
        w.writerows(sorted(filas, key=lambda f: (f["distribucion"], ORDEN_ESC[f["escenario"]], f["repeticion"])))


def corridas_fallo(patrones):
    """Una fila por corrida con fallo, con los tiempos de fallo.tiempos() sobre el análisis guardado en los metadatos."""
    filas = []
    for pat in patrones:
        for ruta in sorted(glob.glob(os.path.join(RAIZ, pat, "metadatos", "*-fallo_*.json"))):
            m = json.load(open(ruta))
            f = m.get("fallo") or {}
            if "analisis" not in f:
                continue
            t = fallo.tiempos(f["analisis"], f["nodo_fallado"], (f.get("eventos") or {}).get("t_restaura"))
            filas.append({"sesion": os.path.relpath(os.path.dirname(os.path.dirname(ruta)), RAIZ), "base": os.path.basename(ruta)[:-5],
                          "tipo": m.get("tipo"), "distribucion": m["distribution"], "repeticion": m["repeticion"], "tasa": m["parametros"]["tasa"],
                          "nodo_fallado": f["nodo_fallado"], "retener_s": (f.get("parametros") or {}).get("retener_s"),
                          "pod_movido": bool(f.get("pod_movido")), **t})
    return filas


def resumen_texto(filas):
    out = []
    for dist in ("k3s", "microk8s"):
        for esc in ("idle", "media", "alta"):
            r = [f for f in filas if f["distribucion"] == dist and f["escenario"] == esc]
            if r:
                def med(c):
                    v = [f[c] for f in r if f.get(c) is not None]
                    return f"{statistics.mean(v):.3f}" if v else "-"
                out.append(f"{dist:9s}{esc:6s} n={len(r)} W={med('potencia_W')} cpuVM%={med('cpu_vm_media')} ramVM_MB={med('ram_vm_media')} "
                           f"p95_ve={med('ve_p95_ms')} p95_res={med('res_p95_ms')}")
    return "\n".join(out)


def resumen_control(filas):
    """Media y desviación muestral por condición (base, rtt, cgroup) y diferencia con la base; con n = 3 no es una prueba de equivalencia."""
    def cond(f):
        return "rtt" if f["con_rtt"] else "cgroup" if f["con_cgroup"] else "base"
    out = []
    for dist in ("k3s", "microk8s"):
        ref = None
        for c in ("base", "rtt", "cgroup"):
            r = [f for f in filas if f["distribucion"] == dist and f["escenario"] == "media" and cond(f) == c]
            if not r:
                continue
            fila = {"distribucion": dist, "condicion": c, "n": len(r)}
            for col in ("potencia_W", "cpu_host_pct", "cpu_vm_media", "ve_p95_ms", "ve_p99_ms", "ve_descartadas"):
                v = [f[col] for f in r if f.get(col) is not None]
                fila[col] = (round(statistics.mean(v), 3), round(statistics.stdev(v), 3) if len(v) > 1 else None) if v else None
            ref = ref or fila
            fila["dif_potencia_W"] = None if not (fila["potencia_W"] and ref["potencia_W"]) else round(fila["potencia_W"][0] - ref["potencia_W"][0], 3)
            fila["dif_p95_ms"] = None if not (fila["ve_p95_ms"] and ref["ve_p95_ms"]) else round(fila["ve_p95_ms"][0] - ref["ve_p95_ms"][0], 3)
            out.append(fila)
    return out


def autotest():
    s = {("node_exporter_host", "i", "node_cpu_seconds_total", "0", "idle"): [(10.0, 1.0), (20.0, 9.0)],
         ("node_exporter_host", "i", "node_cpu_seconds_total", "0", "user"): [(10.0, 1.0), (20.0, 3.0)]}
    assert abs(utilizacion_cpu(s, "i", 0, 30) - 0.2) < 1e-9
    s2 = {("j", "i", "node_memory_MemTotal_bytes", None, None): [(1.0, 4 * 2**20), (2.0, 4 * 2**20)],
          ("j", "i", "node_memory_MemAvailable_bytes", None, None): [(1.0, 1 * 2**20), (2.0, 3 * 2**20)]}
    assert ram_usada_mb(s2, "i", 0, 5) == (2.0, 1.0, 3.0)
    t = os.path.join(os.environ.get("TMPDIR", "/tmp"), "autotest_recursos_latencia.json.gz")
    with gzip.open(t, "wt") as fh:
        for tt, d in ((1, 2.0), (2, 4.0), (3, 6.0), (9, 100.0)):
            iso = datetime.datetime.fromtimestamp(tt, datetime.timezone.utc).isoformat()
            for met, v in (("http_req_duration", d), ("http_req_failed", 0), ("http_req_waiting", d - 1)):
                fh.write(json.dumps({"metric": met, "type": "Point", "data": {"time": iso, "value": v}}) + "\n")
    r = latencia_ventana(t, 1, 4)
    os.remove(t)
    h = r["hist"]
    assert abs(cuantil_hist(h, .5) / 4.0 - 1) < 0.02 and sum(c for _, c in h["bins"]) == 3, h
    assert r["solicitudes"] == 3 and r["p50_ms"] == 4.0 and r["waiting_media_ms"] == 3.0, r
    try:
        comprobar_configuracion([{"escenario": "media", "tasa": 450, "tipo": "piloto"}, {"escenario": "media", "tasa": 900, "tipo": "piloto"}])
        raise AssertionError("debió rechazar la mezcla")
    except SystemExit:
        pass
    print("autotest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sesion", action="append", default=[], help="carpeta de sesión (data/<tipo>/<sesión>); repetible")
    ap.add_argument("--salida", default=os.path.join(RAIZ, "analysis", "salidas"))
    ap.add_argument("--fallo", action="append", default=[], help="carpeta de sesión con corridas -fallo (recuperacion.csv); repetible")
    ap.add_argument("--control", action="store_true", help="resumen por condición (base, rtt, cgroup) de una sesión de control")
    ap.add_argument("--autotest", action="store_true")
    a = ap.parse_args()
    if a.autotest:
        return autotest()
    os.makedirs(a.salida, exist_ok=True)
    if a.sesion:
        f_cache = os.path.join(a.salida, "cache_latencia.json")
        cache = json.load(open(f_cache)) if os.path.exists(f_cache) else {}
        filas = [leer_corrida(m, cache) for s in a.sesion for m in sesion_metas(os.path.join(RAIZ, s) if not os.path.isabs(s) else s)]
        json.dump(cache, open(f_cache, "w"))
        comprobar_configuracion(filas)
        escribir_csv(filas, os.path.join(a.salida, "recursos_latencia.csv"))
        print(resumen_texto(filas))
        if a.control:
            ctl = resumen_control(filas)
            json.dump(ctl, open(os.path.join(a.salida, "control_rtt_cgroup.json"), "w"), indent=1, ensure_ascii=False)
            for x in ctl:
                print(x)
    if a.fallo:
        filas_f = corridas_fallo(a.fallo)
        comprobar_configuracion([{"escenario": "media", "tasa": f["tasa"], "tipo": f["tipo"]} for f in filas_f])
        escribir_csv([dict(f, escenario="media") for f in filas_f], os.path.join(a.salida, "recuperacion.csv"))
        for f in filas_f:
            print({k: f[k] for k in ("distribucion", "repeticion", "nodo_fallado", "notready", "migracion_vip_plano_control", "api_restablecida",
                                      "ready_tras_restauracion", "nodo_fallado_lideraba")})


if __name__ == "__main__":
    main()
