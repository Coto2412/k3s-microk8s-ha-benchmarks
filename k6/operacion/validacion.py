"""Validación preliminar integral de una distribución (HU-22): construye, comprueba, corre idle/media/alta y un fallo, y destruye.

Se lanza por distribución, desde la raíz del repositorio, en la consola de texto y con el modo medición activo:
  python3 -m k6.operacion.validacion --distribucion <k3s|microk8s>
Todo se marca `verificacion` (valida_para_campana: false). Si un paso falla, se detiene sin reintentar ni destruir el clúster.
"""
import argparse, glob, gzip, hashlib, json, os, re, subprocess, sys, threading, time

from k6.lib import estado_host, fallo
from k6.lib.comun import IPS_NODOS, IP_VIP_CP, IP_VIP_SVC, RAIZ, prom
from k6.medicion import orquestador

TASAS = {"media": 450, "alta": 900}
PASO_SCRAPE_S = 10  # intervalo de Prometheus, verificado en T-21.1
ESPERA_HA_S = 60  # Prometheus puede tardar un scrape (10 s) en ver lo recién desplegado; si sigue fallando, es un fallo real
FRACCION_MINIMA = 0.9  # fracción de las muestras esperadas para llamar utilizable una fuente (criterio mío)


class Detener(Exception):
    pass


def valor_gv(dist, clave):
    txt = open(os.path.join(RAIZ, f"{dist}HA", "ansible", "group_vars", "all.yml")).read()
    return re.search(rf"^{clave}:\s*\"?([^\"\s]+)\"?", txt, re.M).group(1)


def milis(q):
    return int(q[:-1]) if q.endswith("m") else int(float(q) * 1000)


def hash_esperado(n):
    h = "referencia"
    for _ in range(n):
        h = hashlib.sha256(h.encode()).hexdigest()
    return h


def psi():
    r = {}
    for linea in open("/proc/pressure/memory"):
        tipo, *kv = linea.split()
        d = dict(x.split("=") for x in kv)
        r[tipo + "_avg10"], r[tipo + "_total_us"] = float(d["avg10"]), int(d["total"])
    return r


def muestra_host():
    mi = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
    vm = {l.split()[0]: int(l.split()[1]) for l in open("/proc/vmstat") if l.startswith(("pswpin ", "pswpout "))}
    return {"t": time.time(), "mem_disponible_kb": mi["MemAvailable"], "swap_total_kb": mi["SwapTotal"],
            "swap_libre_kb": mi["SwapFree"], **vm, **psi()}


class Muestreador(threading.Thread):
    """Memoria, swap y PSI del host cada `cada` s. Solo lee /proc: no toca las VM (un SSH periódico produjo picos de latencia en k6)."""

    def __init__(self, cada=5):
        super().__init__(daemon=True)
        self.cada, self.host, self.errores = cada, [], 0
        self.parar = threading.Event()

    def run(self):
        while not self.parar.is_set():
            t = time.time()
            try:
                self.host.append(muestra_host())
            except Exception:
                self.errores += 1
            self.parar.wait(max(0, self.cada - (time.time() - t)))


def resumen_ventana(host, t0, t1):
    """Mínimos y diferencias de los contadores dentro de [t0, t1]. Resolución: la del muestreo."""
    h = [x for x in host if t0 <= x["t"] <= t1]
    if not h:
        return None
    mb = lambda kb: round(kb / 1024)
    mn = min(h, key=lambda x: x["mem_disponible_kb"])
    r = {"muestras_host": len(h), "mem_disponible_min_mb": mb(mn["mem_disponible_kb"]), "mem_disponible_min_t": round(mn["t"], 1),
         "swap_libre_min_mb": mb(min(x["swap_libre_kb"] for x in h)), "swap_total_mb": mb(h[0]["swap_total_kb"]),
         "pswpin_delta": h[-1]["pswpin"] - h[0]["pswpin"], "pswpout_delta": h[-1]["pswpout"] - h[0]["pswpout"],
         "psi_some_avg10_max": max(x["some_avg10"] for x in h),
         "psi_some_delta_us": h[-1]["some_total_us"] - h[0]["some_total_us"], "psi_full_delta_us": h[-1]["full_total_us"] - h[0]["full_total_us"]}
    return r


def memoria_vms(ventana, t0, t1):
    """Memoria y swap de cada VM desde Node Exporter, en la ventana exportada de Prometheus (10 s de resolución), sin tocar las VM."""
    por_vm = {}
    for v in ventana["resultado"].values():
        for s in v:
            m = s["metric"]
            if m.get("job") == "node_exporter_vms" and m["__name__"] in ("node_memory_MemAvailable_bytes", "node_memory_SwapTotal_bytes", "node_memory_SwapFree_bytes"):
                d = por_vm.setdefault(m["instance"], {}).setdefault(m["__name__"], {})
                d.update({float(t): float(x) for t, x in s["values"] if t0 <= float(t) <= t1})
    mb = lambda b: round(b / 1048576)
    r = {}
    for ip, d in sorted(por_vm.items()):
        disp, tot, libre = (d.get(k, {}) for k in ("node_memory_MemAvailable_bytes", "node_memory_SwapTotal_bytes", "node_memory_SwapFree_bytes"))
        if disp:
            r[ip] = {"muestras": len(disp), "mem_disponible_min_mb": mb(min(disp.values())),
                     "swap_usado_max_mb": mb(max(tot[t] - libre[t] for t in tot if t in libre)) if tot and libre else None}
    return r


def max_muestras(resultado, job, metrica, filtro=None, clave="instance"):
    """Máximo de muestras de una serie, por el valor de la etiqueta `clave`, para un job y una métrica."""
    r = {}
    for s in resultado:
        m = s["metric"]
        if m.get("job") == job and m.get("__name__") == metrica and (not filtro or all(m.get(k) == v for k, v in filtro.items())):
            r[m.get(clave, "")] = max(r.get(m.get(clave, ""), 0), len(s["values"]))
    return r


def fuentes(meta, raiz=RAIZ):
    """Una entrada por fuente: ok y detalle. «Utilizable» = presente y con ≥ FRACCION_MINIMA de las muestras esperadas."""
    esc, dur = meta["escenario"], meta["t_fin"] - meta["t_inicio"]
    r = {}
    rapl = meta["rapl"]
    r["rapl"] = {"ok": rapl["delta_uj"] > 0, "delta_uj": rapl["delta_uj"], "potencia_media_W": rapl["potencia_media_W"],
                 "desbordamiento": rapl["desbordamiento"], "ventana_s": round(dur, 1)}
    k = meta["k6"]
    tam = os.path.getsize(os.path.join(raiz, k["json"])) if os.path.exists(os.path.join(raiz, k["json"])) else 0
    ok_k6 = k["codigo_salida"] == 0 and tam > 0
    d = {"codigo_salida": k["codigo_salida"], "json_bytes": tam}
    if esc != "idle":
        filas = json.load(gzip.open(os.path.join(raiz, k["por_segundo"]), "rt"))
        en = [f for f in filas if meta["t_inicio"] - 1 <= f["t"] <= meta["t_fin"]]
        d |= {"segundos_con_datos": len(en), "solicitudes_por_s": round(sum(f["solicitudes"] for f in en) / max(1, len(en)), 1),
              "fallidas": sum(f["fallidas"] for f in en), "descartadas": sum(f["descartadas"] for f in en)}
        ok_k6 = ok_k6 and len(en) >= FRACCION_MINIMA * int(dur)
    r["k6"] = {"ok": ok_k6, **d}
    ventana = json.load(gzip.open(os.path.join(raiz, meta["ventana_prometheus"]["archivo"]), "rt"))
    res = [s for v in ventana["resultado"].values() for s in v]
    esperadas = int((ventana["t_hasta"] - ventana["t_desde"]) / PASO_SCRAPE_S)
    minimo = int(FRACCION_MINIMA * esperadas)
    sc = max_muestras(res, "scaphandre", "scaph_host_energy_microjoules")
    r["scaphandre"] = {"ok": bool(sc) and max(sc.values()) >= minimo, "muestras": sc, "esperadas": esperadas}
    nh = max_muestras(res, "node_exporter_host", "node_memory_MemAvailable_bytes")
    nv = max_muestras(res, "node_exporter_vms", "node_memory_MemAvailable_bytes")
    r["node_exporter"] = {"ok": bool(nh) and max(nh.values()) >= minimo and len(nv) == len(IPS_NODOS) and min(nv.values()) >= minimo,
                          "host": nh, "vms": nv, "esperadas": esperadas}
    kn = max_muestras(res, "kube_state_metrics", "kube_node_status_condition", {"condition": "Ready", "status": "true"}, "node")
    kp = {k: v for k, v in max_muestras(res, "kube_state_metrics", "kube_pod_status_ready", {"condition": "true"}, "pod").items() if k.startswith("nginx-referencia")}
    r["kube_state_metrics"] = {"ok": len(kn) >= len(IPS_NODOS) and min(kn.values()) >= minimo and bool(kp) and max(kp.values()) >= minimo,
                               "nodos": len(kn), "muestras_nodo_min": min(kn.values(), default=0), "pod": kp, "esperadas": esperadas}
    return r


def siguiente_ciclo(dist):
    ruta = os.path.join(RAIZ, "data", "despliegue", f"despliegue_{dist}.jsonl")
    try:
        return max(json.loads(l)["ciclo"] for l in open(ruta) if l.strip()) + 1
    except (OSError, ValueError):
        return 1


def despliegue(dist, accion, ciclo):
    r = subprocess.run([os.path.join(RAIZ, "k6", "operacion", "despliegue.sh"), dist, accion, str(ciclo)], capture_output=True, text=True)
    try:
        reg = json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        reg = {"error": "sin registro", "stdout": r.stdout[-500:], "stderr": r.stderr[-500:]}
    reg["log"] = f"/tmp/despliegue_{dist}_{accion}_c{ciclo}.log"
    return r.returncode, reg


def precondiciones(a):
    m = []
    pol = estado_host.cargar_politica()
    if pol is None:
        return ["falta /etc/tesis/medicion.json (rol host_mediciones)"]
    _, motivos = estado_host.estado_host(pol)
    m += motivos
    if subprocess.run(["pgrep", "-x", "k6"], capture_output=True).returncode == 0:
        m.append("hay un k6 en ejecución")
    try:
        distros = {x["metric"].get("distribution") for x in prom(a.prometheus, "last_over_time(up[30s])")}
        if distros != {a.distribucion}:
            m.append(f"Prometheus etiqueta {sorted(map(str, distros))}; correr el playbook del host con -e active_distribution={a.distribucion}")
    except Exception as e:
        m.append(f"Prometheus no responde en {a.prometheus}: {type(e).__name__}")
    vivos = [ip for ip in IPS_NODOS + [IP_VIP_CP, IP_VIP_SVC] if subprocess.run(["ping", "-c1", "-W1", ip], capture_output=True).returncode == 0]
    if vivos:
        m.append(f"ya hay un clúster arriba (responden {vivos}); destruirlo antes")
    if not os.path.isdir(os.path.join(RAIZ, f"{a.distribucion}HA")):
        m.append(f"no existe {a.distribucion}HA")
    return m


def comprobar_ha(a, acc):
    d, k = a.distribucion, fallo.KUBECTL[a.distribucion]
    r = {}
    rc, out = fallo.ssh(acc, IPS_NODOS[0], f"{k} get nodes --no-headers", 60)
    listos = [l.split()[0] for l in out.splitlines() if len(l.split()) > 1 and l.split()[1] == "Ready"]
    r["nodos_ready"] = {"ok": rc == 0 and len(listos) == len(IPS_NODOS), "listos": listos}
    http = subprocess.run(["curl", "-sk", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}", f"https://{IP_VIP_CP}:{fallo.PUERTO_API[d]}/healthz"],
                          capture_output=True, text=True).stdout
    r["vip_plano_control"] = {"ok": http in ("200", "401", "403"), "ip": IP_VIP_CP, "http": http}
    n = int(valor_gv(d, "nginx_sha_iteraciones"))
    cuerpo = subprocess.run(["curl", "-s", "-m", "5", f"http://{IP_VIP_SVC}:80/"], capture_output=True, text=True).stdout.strip()
    r["vip_servicio"] = {"ok": cuerpo == hash_esperado(n), "ip": IP_VIP_SVC, "sha256_iteraciones": n, "respuesta_prefijo": cuerpo[:16]}
    tit = orquestador.titulares(a.prometheus, d)
    r["titulares"] = {"ok": "no determinado" not in tit.values(), **tit}
    jp = ("{.spec.template.spec.containers[0].resources.limits.cpu} {.spec.template.spec.containers[0].resources.requests.cpu} "
          "{.status.readyReplicas} {.spec.template.spec.containers[0].image}")
    rc, out = fallo.ssh(acc, IPS_NODOS[0], f"{k} get deploy nginx-referencia -o jsonpath='{jp}'", 30)
    p = out.split()
    lim, req = valor_gv(d, "nginx_cpu_limit"), valor_gv(d, "nginx_cpu_request")
    r["aplicacion"] = {"ok": rc == 0 and len(p) == 4 and milis(p[0]) == milis(lim) and milis(p[1]) == milis(req) and p[2] == "1" and p[3] == valor_gv(d, "nginx_image"),
                       "limite_cpu": p[0] if p else None, "solicitud_cpu": p[1] if len(p) > 1 else None,
                       "esperado": {"limite": lim, "solicitud": req}, "replicas_listas": p[2] if len(p) > 2 else None}
    return r


def resumen_fallo(meta):
    f = meta["fallo"]
    if not f or "analisis" not in f:
        return {"ok": False, "motivo": (f or {}).get("error", "sin bloque de fallo")}
    an = f["analisis"]
    return {"ok": True, "nodo_fallado": f["nodo_fallado"], "pod_movido": f["pod_movido"], "reinicios_kube_vip": f["reinicios_kube_vip"],
            "api_vip": an["api_vip"], "app_vip": an["app_vip"], "titular_vip_cp": an["titular_vip_cp"], "titular_vip_svc": an["titular_vip_svc"],
            "nodo_notready_kubectl": an["nodo_notready_kubectl"], "nodo_notready_ksm": an["nodo_notready_ksm"], "k6": an["k6"],
            "nodo_listo_al_final": f["eventos"].get("nodo_listo_al_final"), "cota_t_fallo_s": an["cota_t_fallo_s"]}


def main():
    if "--autotest" in sys.argv:
        return autotest()
    ap = argparse.ArgumentParser()
    ap.add_argument("--distribucion", required=True, choices=["k3s", "microk8s"])
    ap.add_argument("--sesion", help="por defecto <fecha>_<distribución>_T-22; no se puede repetir una sesión ya usada")
    ap.add_argument("--prometheus", default="http://127.0.0.1:9090")
    ap.add_argument("--solo-precondiciones", action="store_true", help="comprueba el host y sale, sin construir nada")
    a = ap.parse_args()
    d = a.distribucion
    sesion = a.sesion or f"{time.strftime('%Y-%m-%d')}_{d}_T-22"
    carpeta = os.path.join(RAIZ, "data", "verificacion", sesion, "validacion")

    motivos = precondiciones(a)
    if motivos or a.solo_precondiciones:
        print("Precondiciones " + ("NO cumplidas:\n- " + "\n- ".join(motivos) if motivos else "cumplidas"))
        return 1 if motivos else 0
    os.makedirs(carpeta, exist_ok=True)
    salida = os.path.join(carpeta, f"validacion_{d}_{time.strftime('%Y%m%dT%H%M')}.json")
    ciclo = siguiente_ciclo(d)
    res = {"esquema": 1, "tipo": "verificacion", "valida_para_campana": False, "distribucion": d, "sesion": sesion, "ciclo_despliegue": ciclo,
           "inicio": round(time.time(), 3), "pasos": [], "corridas": {}, "incidencias": [], "detenida": None,
           "ajustes_manuales": "ninguno por el script: construyó con despliegue.sh y no ejecutó comandos fuera de la secuencia; lo confirma quien lo lanzó"}
    mu = Muestreador()
    mu.start()

    def guardar():
        res["memoria_errores_muestreo"] = mu.errores
        json.dump(res, open(salida, "w"), indent=1, default=str)
        json.dump({"host": mu.host}, open(salida.replace("validacion_", "memoria_"), "w"))

    def paso(nombre, **datos):
        p = {"paso": nombre, "inicio": round(time.time(), 3), **datos}
        res["pasos"].append(p)
        print(f"[{time.strftime('%H:%M:%S')}] {nombre}", flush=True)
        return p

    def cerrar(p, ok, motivo=None):
        p["fin"], p["ok"] = round(time.time(), 3), ok
        guardar()
        if not ok:
            raise Detener(f"{p['paso']}: {motivo}")

    acc = None
    try:
        p = paso("1 construcción completa (terraform + ansible, aplicación definitiva)")
        rc, reg = despliegue(d, "construir", ciclo)
        p["registro"] = reg
        cerrar(p, rc == 0, f"despliegue.sh construir rc={rc}; log en {reg['log']}")
        acc = fallo.acceso(RAIZ, d)

        p = paso("2 comprobaciones de HA y de la aplicación")
        t_ini = time.time()
        while True:
            p["comprobaciones"] = comprobar_ha(a, acc)
            malas = [k for k, v in p["comprobaciones"].items() if not v["ok"]]
            p["intentos"], p["espera_s"] = p.get("intentos", 0) + 1, round(time.time() - t_ini, 1)
            if not malas or time.time() - t_ini > ESPERA_HA_S:
                break
            time.sleep(5)
        cerrar(p, not malas, f"fallaron {malas}")
        res["swap_libre_inicio_mb"] = round(mu.host[-1]["swap_libre_kb"] / 1024)

        secuencia = [("idle", []), ("media", ["--tasa", str(TASAS["media"])]), ("alta", ["--tasa", str(TASAS["alta"])]),
                     ("media", ["--tasa", str(TASAS["media"]), "--fallo"])]
        for esc, extra in secuencia:
            nombre = esc + ("-fallo" if "--fallo" in extra else "")
            p = paso(f"3 corrida {nombre} (1 repetición, {TASAS.get(esc, 'sin carga')} rps)")
            base = f"verif_{d}_{nombre}_r01"
            t0 = time.time()
            with open(os.path.join(carpeta, f"orquestador_{nombre}.log"), "w") as log:
                rc = subprocess.run([sys.executable, "-m", "k6.medicion.orquestador", "--distribucion", d, "--escenario", esc, "--repeticion", "1",
                                     "--tipo", "verificacion", "--sesion", sesion, "--estabilizacion", "120", *extra],
                                    cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT).returncode
            t1 = time.time()
            ruta = os.path.join(RAIZ, "data", "verificacion", sesion, "metadatos", base + ".json")
            p["meta"] = os.path.relpath(ruta, RAIZ)
            if rc or not os.path.exists(ruta):
                cerrar(p, False, f"orquestador rc={rc} (ver {os.path.relpath(log.name, RAIZ)})")
            meta = json.load(open(ruta))
            c = res["corridas"][nombre] = {"meta": p["meta"], "valida_para_campana": meta["valida_para_campana"],
                                           "duracion_total_s": round(t1 - t0, 1), "fuentes": fuentes(meta),
                                           "memoria_corrida_completa": resumen_ventana(mu.host, t0, t1),
                                           "memoria_fase_estable": resumen_ventana(mu.host, meta["t_inicio"], meta["t_fin"])}
            vent = json.load(gzip.open(os.path.join(RAIZ, meta["ventana_prometheus"]["archivo"]), "rt"))
            c["memoria_vms_ventana_completa"] = memoria_vms(vent, 0, float("inf"))
            c["memoria_vms_fase_estable"] = memoria_vms(vent, meta["t_inicio"], meta["t_fin"])
            if nombre.endswith("fallo"):
                c["fallo"] = resumen_fallo(meta)
            hosts = [x for x in meta["motivos_no_valida"] if not x.startswith("tipo ")]
            m = c["memoria_corrida_completa"] or {}
            if m.get("pswpin_delta") or m.get("pswpout_delta") or m.get("swap_libre_min_mb", 1 << 30) < res["swap_libre_inicio_mb"]:
                res["incidencias"].append(f"{nombre}: el host usó swap (pswpin +{m.get('pswpin_delta')}, pswpout +{m.get('pswpout_delta')}); sin ajustar")
            malas = [k for k, v in c["fuentes"].items() if not v["ok"]]
            if meta["valida_para_campana"]:
                motivo = "la corrida salió marcada válida para la campaña"
            elif hosts:
                motivo = f"verificación del host no cumplida: {hosts}"
            elif m.get("mem_disponible_min_mb", 1 << 30) < estado_host.MEM_MIN_MB:
                motivo = f"memoria disponible mínima {m['mem_disponible_min_mb']} MB < {estado_host.MEM_MIN_MB} MB (resultado de T-22.4)"
            elif malas:
                motivo = f"fuentes sin registros utilizables: {malas}"
            elif nombre.endswith("fallo") and not c["fallo"]["ok"]:
                motivo = "la corrida con fallo no produjo análisis"
            else:
                motivo = None
            cerrar(p, motivo is None, motivo)

        p = paso("4 destrucción del clúster")
        rc, reg = despliegue(d, "destruir", ciclo)
        p["registro"] = reg
        cerrar(p, rc == 0, f"despliegue.sh destruir rc={rc}; log en {reg['log']}")
    except Detener as e:
        res["detenida"] = str(e)
        res["clúster"] = f"queda arriba; para destruirlo: k6/operacion/despliegue.sh {d} destruir {ciclo}"
    except KeyboardInterrupt:
        res["detenida"] = "interrumpida por el usuario"
        res["clúster"] = f"puede quedar arriba; para destruirlo: k6/operacion/despliegue.sh {d} destruir {ciclo}"
    finally:
        mu.parar.set()
        mu.join(timeout=10)
        res["fin"] = round(time.time(), 3)
        guardar()
    print(json.dumps({"archivo": os.path.relpath(salida, RAIZ), "detenida": res["detenida"], "incidencias": res["incidencias"],
                      "pasos": [(p["paso"][:2], p.get("ok")) for p in res["pasos"]]}, ensure_ascii=False, indent=1))
    return 2 if res["detenida"] else 0


def autotest():
    host = [{"t": t, "mem_disponible_kb": 2048 * 1024 - 1024 * t, "swap_total_kb": 100, "swap_libre_kb": 100 - (t > 3), "pswpin": 5, "pswpout": 10 + t,
             "some_avg10": 0.5 * t, "some_total_us": 100 * t, "full_total_us": 10 * t} for t in range(6)]
    r = resumen_ventana(host, 1, 4)
    assert r["muestras_host"] == 4 and r["mem_disponible_min_mb"] == 2044 and r["swap_libre_min_mb"] == 0
    assert r["pswpin_delta"] == 0 and r["pswpout_delta"] == 3 and r["psi_some_delta_us"] == 300
    assert resumen_ventana(host, 10, 11) is None
    mm = 1048576
    ser = lambda n, v: {"metric": {"job": "node_exporter_vms", "__name__": n, "instance": "ip"}, "values": [[t, str(x)] for t, x in enumerate(v)]}
    vent = {"resultado": {"q": [ser("node_memory_MemAvailable_bytes", [4 * mm, 3 * mm, 5 * mm]), ser("node_memory_SwapTotal_bytes", [10 * mm] * 3),
                                ser("node_memory_SwapFree_bytes", [10 * mm, 7 * mm, 10 * mm])]}}
    assert memoria_vms(vent, 0, 9) == {"ip": {"muestras": 3, "mem_disponible_min_mb": 3, "swap_usado_max_mb": 3}}
    assert memoria_vms(vent, 2, 9)["ip"]["mem_disponible_min_mb"] == 5 and memoria_vms(vent, 7, 9) == {}
    assert milis("2000m") == milis("2") == 2000 and milis("500m") == 500
    assert hash_esperado(1) == hashlib.sha256(b"referencia").hexdigest() and hash_esperado(2) != hash_esperado(1)
    ser = [{"metric": {"job": "j", "__name__": "m", "instance": "a"}, "values": [[0, "1"]] * 5},
           {"metric": {"job": "j", "__name__": "m", "instance": "a", "x": "y"}, "values": [[0, "1"]] * 7},
           {"metric": {"job": "j", "__name__": "m", "instance": "b"}, "values": [[0, "1"]] * 2}]
    assert max_muestras(ser, "j", "m") == {"a": 7, "b": 2} and max_muestras(ser, "j", "m", {"x": "y"}) == {"a": 7}
    assert max_muestras([{"metric": {"job": "j", "__name__": "m", "node": "n1"}, "values": [1]}], "j", "m", None, "node") == {"n1": 1}
    print("autotest ok")


if __name__ == "__main__":
    sys.exit(main() or 0)
