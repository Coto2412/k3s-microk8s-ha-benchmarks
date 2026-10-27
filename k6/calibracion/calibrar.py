"""Calibración de tasas (T-20.5): escalones de carga en modelo abierto hasta saturación; los datos son calibración, no resultados.

Un escalón es sostenido si, en su tramo estable: se aplicó ≥ 99 % de la tasa pedida, fallaron ≤ 0,1 % de las solicitudes,
el pod no está estrangulado por CFS (≤ 1 % de los periodos), y el generador no está limitado
(CPU de los núcleos de k6 < 85 %, VUs en uso < 80 % de maxVUs). La mediana del p95 por segundo se informa, pero no decide:
la regla inicial (p95 > 3 veces el del primer escalón) se retiró tras ver datos por arbitraria (ver evidencia_T-20, sección 6). Si el escalón falla por el generador, el techo medido
es del generador, no del nodo.

Ejemplo: python3 -m k6.calibracion.calibrar --distribucion k3s
"""
import argparse, json, os, statistics, subprocess, sys, time

from k6.lib import agregado, estado_host, fallo
from k6.lib.comun import IPS_NODOS, IP_VIP_SVC, RAIZ, estabilizar, prom, sha256


def consulta(url, expr, t):
    r = prom(url, expr, t)
    return {x["metric"].get("instance", "-"): round(float(x["value"][1]), 4) for x in r}


def escalon(a, tasa, n, p0, pod):
    base = f"calib_{a.distribucion}_p{n:02d}_{int(tasa)}rps"
    f_json = os.path.join(a.d_crudo, f"calib_{a.distribucion}_{a.ts}_p{n:02d}_{int(tasa)}rps.json.gz")
    f_res = os.path.join("/tmp", base + ".resumen.json")
    env = dict(os.environ, DISTRIBUCION=a.distribucion, ESCENARIO="calibracion", REPETICION=str(n), TASA=str(tasa),
               RAMPA_S=str(a.rampa), ESTABLE_S=str(a.estable), DESCENSO_S="1", PRE_VUS=str(a.pre_vus),
               MAX_VUS=str(a.max_vus), OBJETIVO=a.objetivo)
    c0 = fallo.cpu_pod(a.acc, pod[1], pod[0])
    t0 = time.time()
    rc = subprocess.run(["taskset", "-c", a.cpus, "k6", "run", "--out", f"json={f_json}", "--summary-export", f_res,
                         os.path.join(RAIZ, "k6", "escenarios", "calibracion.js")], env=env, capture_output=True).returncode
    t_k6 = time.time()
    c1 = fallo.cpu_pod(a.acc, pod[1], pod[0])
    t_ini, t_fin = t0 + a.rampa + a.recorte, t0 + a.rampa + a.estable
    filas = [f for f in agregado.por_segundo(f_json) if t_ini <= f["t"] < t_fin]
    n_seg = max(1, len(filas))
    sol = sum(f["solicitudes"] for f in filas)
    p95 = [f["p95_ms"] for f in filas if f["p95_ms"] is not None]
    resumen = json.load(open(f_res)) if os.path.exists(f_res) else {}
    vus_max = resumen.get("metrics", {}).get("vus_max", {}).get("max") or resumen.get("metrics", {}).get("vus", {}).get("max")
    espera = 12  # un par de scrapes de 10 s después del tramo para que rate() lo cubra
    time.sleep(espera)
    ventana = int(t_fin - t_ini)
    cpu_vm = consulta(a.prometheus, f'1 - avg by (instance)(rate(node_cpu_seconds_total{{job="node_exporter_vms",mode="idle"}}[{ventana}s]))', t_fin + espera)
    cpu_gen = consulta(a.prometheus, f'1 - avg(rate(node_cpu_seconds_total{{job="node_exporter_host",mode="idle",cpu=~"{"|".join(a.cpus.split(","))}"}}[{ventana}s]))', t_fin + espera)
    return {"n": n, "tasa_pedida": tasa, "k6_rc": rc, "t_tramo": [round(t_ini, 1), round(t_fin, 1)], "segundos": len(filas),
            "tasa_aplicada": round(sol / n_seg, 1), "fallidas": sum(f["fallidas"] for f in filas), "solicitudes": sol,
            "descartadas": sum(f["descartadas"] for f in filas),
            "p95_mediana_ms": round(statistics.median(p95), 3) if p95 else None,
            "p99_mediana_ms": round(statistics.median([f["p99_ms"] for f in filas]), 3) if filas else None,
            "p99_max_ms": max((f["p99_ms"] for f in filas), default=None),
            "pod_cpu_nucleos": round((c1["usage_usec"] - c0["usage_usec"]) / 1e6 / (t_k6 - t0), 3),
            "pod_periodos": c1["nr_periods"] - c0["nr_periods"], "pod_periodos_estrangulados": c1["nr_throttled"] - c0["nr_throttled"],
            "vus_max": vus_max, "cpu_vms": cpu_vm, "cpu_generador": next(iter(cpu_gen.values()), None),
            "crudo": {"archivo": os.path.relpath(f_json, RAIZ), "sha256": sha256(f_json)}}


def veredicto(e, p95_ref, max_vus):
    """Lista de motivos de falla; vacía = escalón sostenido. 'generador' marca que el límite no es del nodo."""
    m = []
    if e["k6_rc"] not in (0, 99):
        m.append(f"k6 terminó con código {e['k6_rc']}")
    if e["solicitudes"] == 0 or e["tasa_aplicada"] < 0.99 * e["tasa_pedida"]:
        m.append("tasa aplicada < 99 % de la pedida")
    if e["solicitudes"] and e["fallidas"] / e["solicitudes"] > 0.001:
        m.append("fallidas > 0,1 %")
    if e["pod_periodos"] and e["pod_periodos_estrangulados"] / e["pod_periodos"] > 0.01:
        m.append("contenedor: más de 1 % de los periodos con throttling de CFS (límite de CPU del pod)")
    if e["cpu_generador"] is not None and e["cpu_generador"] >= 0.85:
        m.append("generador: CPU de los núcleos de k6 ≥ 85 %")
    if e["vus_max"] and e["vus_max"] >= 0.8 * max_vus:
        m.append("VUs ≥ 80 % de maxVUs (solicitudes acumuladas en vuelo; no distingue entre generador y plataforma)")
    return m


def reanalizar(ruta):
    """Aplica el criterio vigente a una calibración ya guardada, sin tocar el archivo."""
    m = json.load(open(ruta))
    ok = None
    for p in m["pasos"]:
        f = veredicto(p, None, m["parametros"]["max_vus"])
        print(f"{p['tasa_pedida']:>6.0f} rps  aplicada {p['tasa_aplicada']:>7}  p95 {p['p95_mediana_ms']} ms  -> {f or 'sostenido'}")
        if not f and (ok is None or p["tasa_pedida"] > ok):
            ok = p["tasa_pedida"]
    print("última tasa sostenida:", ok)


def autotest():
    e = {"k6_rc": 0, "solicitudes": 1000, "tasa_aplicada": 100, "tasa_pedida": 100, "fallidas": 0, "p95_mediana_ms": 1.0,
         "cpu_generador": 0.1, "vus_max": 5, "pod_periodos": 100, "pod_periodos_estrangulados": 0}
    assert veredicto(e, 1.0, 100) == []
    assert len(veredicto(dict(e, tasa_aplicada=90, p95_mediana_ms=4.0), 1.0, 100)) == 1
    assert veredicto(dict(e, pod_periodos_estrangulados=5), 1.0, 100)[0].startswith("contenedor")
    print("autotest ok")


def main():
    if "--autotest" in sys.argv:
        return autotest()
    if len(sys.argv) == 3 and sys.argv[1] == "--reanalizar":
        return reanalizar(sys.argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("--distribucion", required=True, choices=["k3s", "microk8s"])
    ap.add_argument("--tasas", default="100,200,400,800,1200,1600,2400,3200,4800,6400")
    ap.add_argument("--rampa", type=int, default=5)
    ap.add_argument("--estable", type=int, default=60, help="s del escalón incluida la rampa")
    ap.add_argument("--recorte", type=int, default=10, help="s descartados tras la rampa")
    ap.add_argument("--seguir", action="store_true", help="recorre toda la escalera aunque un escalón falle (sin refinar)")
    ap.add_argument("--nota", default="", help="texto libre que se guarda en los metadatos (p. ej. cambios exploratorios en el clúster)")
    ap.add_argument("--pausa", type=int, default=20, help="s entre escalones")
    ap.add_argument("--pre-vus", type=int, default=100)
    ap.add_argument("--max-vus", type=int, default=400)
    ap.add_argument("--cpus", default="0,1")
    ap.add_argument("--objetivo", default=f"http://{IP_VIP_SVC}:80/")
    ap.add_argument("--prometheus", default="http://127.0.0.1:9090")
    a = ap.parse_args()

    pol = estado_host.cargar_politica()
    if pol is None:
        sys.exit("Falta /etc/tesis/medicion.json: correr el playbook del host (rol host_mediciones)")
    acc = fallo.acceso(RAIZ, a.distribucion)
    a.acc = acc
    pod = fallo.pod_nginx(a.distribucion, acc, IPS_NODOS[0])
    estabilizar(a.prometheus, a.distribucion, 30, a.objetivo)
    reloj, motivos_reloj, _ = estado_host.esperar_reloj(lambda: fallo.reloj(acc, IPS_NODOS), pol)
    if motivos_reloj:
        sys.exit(f"Reloj sin converger: {motivos_reloj}")
    estado, motivos_estado = estado_host.estado_host(pol)
    a.ts = time.strftime("%Y%m%dT%H%M%S")
    sesion = f"{time.strftime('%Y-%m-%d')}_{a.distribucion}"
    salida = os.path.join(RAIZ, "data", "calibracion", sesion, f"calib_{a.distribucion}_{a.ts}.json")
    a.d_crudo = os.path.join(RAIZ, "data", "k6-crudo", "calibracion", sesion)
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    os.makedirs(a.d_crudo, exist_ok=True)

    pendientes, pasos, p95_ref, ultimo_ok, refinados = [float(x) for x in a.tasas.split(",")], [], None, None, False
    while pendientes:
        tasa = pendientes.pop(0)
        e = escalon(a, tasa, len(pasos) + 1, p95_ref, pod)
        p95_ref = p95_ref or e["p95_mediana_ms"]
        e["motivos_falla"] = veredicto(e, p95_ref, a.max_vus)
        pasos.append(e)
        print(f"{tasa:>7.0f} rps: aplicada {e['tasa_aplicada']}, p95 {e['p95_mediana_ms']} ms, fallidas {e['fallidas']}, "
              f"pod {e['pod_cpu_nucleos']} núcleos, estrangulados {e['pod_periodos_estrangulados']}/{e['pod_periodos']}, cpu VMs {e['cpu_vms']}, generador {e['cpu_generador']} -> {e['motivos_falla'] or 'sostenido'}", flush=True)
        if not e["motivos_falla"]:
            ultimo_ok = tasa
        elif a.seguir:
            pass
        elif not refinados and ultimo_ok is not None:
            refinados = True
            pendientes = [round(ultimo_ok + (tasa - ultimo_ok) * k / 3) for k in (1, 2)]
        else:
            pendientes = []
        time.sleep(a.pausa)
    por_generador = any(any(m.startswith("generador") for m in p["motivos_falla"]) for p in pasos)
    meta = {"esquema": 1, "tipo": "calibracion", "distribucion": a.distribucion,
            "parametros": {k: getattr(a, k) for k in ("tasas", "rampa", "estable", "recorte", "pausa", "pre_vus", "max_vus", "cpus", "objetivo")},
            "nota": a.nota, "criterio": __doc__.split("\n\n")[0], "reloj_antes": reloj, "estado_host": estado, "motivos_estado": motivos_estado,
            "pod": {"uid": pod[0], "nodo_ip": pod[1]}, "pasos": pasos, "ultima_tasa_sostenida": ultimo_ok,
            "limite_por_generador": por_generador,
            "limite_por_contenedor": any(any(m.startswith("contenedor") for m in p["motivos_falla"]) for p in pasos)}
    json.dump(meta, open(salida, "w"), indent=2, default=str)
    print(json.dumps({"archivo": os.path.relpath(salida, RAIZ), "ultima_tasa_sostenida": ultimo_ok, "limite_por_generador": por_generador}))


if __name__ == "__main__":
    sys.exit(main() or 0)
