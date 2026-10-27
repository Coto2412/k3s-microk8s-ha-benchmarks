#!/usr/bin/env python3
"""Orquestador de una repetición (T-32.1): estabiliza, ejecuta k6, mide RAPL, registra titulares y toma el snapshot.

Ejemplo (verificación corta, no es una repetición válida):
  k6/orquestador.py --distribucion k3s --escenario media --repeticion 0 --tasa 50 \
      --rampa 5 --estable 20 --descenso 5 --estabilizacion 10 --verificacion
"""
import argparse, gzip, hashlib, json, os, re, shutil, subprocess, sys, time
import threading
import urllib.parse, urllib.request

import agregado, estado_host, fallo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAPL = "/sys/class/powercap/intel-rapl:0/"
IP_VIP_CP, IP_VIP_SVC = "192.168.100.100", "192.168.100.150"
IPS_NODOS = ["192.168.100.11", "192.168.100.12", "192.168.100.13"]
OBJETIVOS_ESPERADOS = 7  # host, 3 VMs, scaphandre, kube-state-metrics y prometheus
B_POR_SOLICITUD = 144  # bytes del .json.gz por solicitud: máximo de 4 corridas de humo (133 a 144)
LIMITE_ARCHIVO, UMBRAL_AVISO = 100_000_000, 0.8  # GitHub rechaza archivos > 100 MB


def delta_rapl(a, b, maximo):
    """Delta del contador con un solo desbordamiento posible (la ventana dura minutos)."""
    return b - a if b >= a else b - a + maximo


def mac_de(ip):
    subprocess.run(["ping", "-c1", "-W1", ip], capture_output=True)
    out = subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True).stdout
    m = re.search(r"lladdr ([0-9a-f:]{17})", out)
    return m.group(1) if m else None


def prom(url, consulta, t=None):
    q = {"query": consulta}
    if t:
        q["time"] = t
    d = json.load(urllib.request.urlopen(f"{url}/api/v1/query?" + urllib.parse.urlencode(q), timeout=15))
    assert d["status"] == "success", d
    return d["data"]["result"]


def prom_rango(url, consulta, t0, t1):
    q = urllib.parse.urlencode({"query": consulta, "start": t0, "end": t1, "step": 5})
    d = json.load(urllib.request.urlopen(f"{url}/api/v1/query_range?" + q, timeout=30))
    assert d["status"] == "success", d
    return [(float(t), v == "1") for t, v in d["data"]["result"][0]["values"]] if d["data"]["result"] else []


def nombres_nodos(url, distribucion):
    return {x["metric"]["internal_ip"]: x["metric"]["node"]
            for x in prom(url, f'kube_node_info{{distribution="{distribucion}"}}')}


def titulares(url, distribucion):
    """Nodo de cada VIP por la MAC que el host ve en ARP; el pod, por kube-state-metrics."""
    macs = {ip: mac_de(ip) for ip in IPS_NODOS}
    nombre_de_ip = nombres_nodos(url, distribucion)

    def nodo(vip):
        m = mac_de(vip)
        ips = [ip for ip, mm in macs.items() if m and mm == m]
        if len(ips) != 1:
            return "no determinado"
        return nombre_de_ip.get(ips[0], ips[0])

    pods = prom(url, f'kube_pod_info{{distribution="{distribucion}",namespace="default",pod=~"nginx-referencia-.*"}}')
    nodos_pod = {x["metric"]["node"] for x in pods}
    return {"nodo_vip_plano_control": nodo(IP_VIP_CP), "nodo_vip_servicio": nodo(IP_VIP_SVC),
            "nodo_pod": nodos_pod.pop() if len(nodos_pod) == 1 else "no determinado"}


def leer_rapl():
    t0 = time.time()
    try:
        v = int(open(RAPL + "energy_uj").read())
    except PermissionError:
        v = int(subprocess.run(["sudo", "-n", "/usr/bin/cat", RAPL + "energy_uj"],
                               capture_output=True, text=True, check=True).stdout)
    return v, t0, time.time()


def estabilizar(url, distribucion, segundos, objetivo):
    time.sleep(segundos)
    up = prom(url, "last_over_time(up[30s])")  # excluye series de la etiqueta anterior que aún están en la ventana de 5 min
    distros = {x["metric"].get("distribution") for x in up}
    if distros != {distribucion}:
        sys.exit(f"Prometheus etiqueta {sorted(map(str, distros))} y se pidió '{distribucion}': "
                 "correr el playbook del host con -e active_distribution=" + distribucion)
    caidos = [x["metric"]["job"] + "/" + x["metric"]["instance"] for x in up if x["value"][1] != "1"]
    if len(up) != OBJETIVOS_ESPERADOS or caidos:
        sys.exit(f"Targets: {len(up)} (esperados {OBJETIVOS_ESPERADOS}), caídos: {caidos}")
    codigo = urllib.request.urlopen(objetivo, timeout=5).status
    if codigo != 200:
        sys.exit(f"{objetivo} respondió {codigo}")


def exportar_ventana(url, t0, t1, destino):
    """Muestras crudas de la ventana (consulta de rango vectorial) para que cada repetición sea analizable sin la TSDB."""
    dur = int(t1 - t0) + 1
    selectores = [f'{{job=~"node_exporter_host|node_exporter_vms|scaphandre"}}[{dur}s]',
                  f'{{job="kube_state_metrics",__name__=~"kube_node_status_condition|kube_node_info|kube_pod_info|kube_pod_status_ready"}}[{dur}s]']
    datos = {}
    for sel in selectores:
        q = urllib.parse.urlencode({"query": sel, "time": t1})
        d = json.load(urllib.request.urlopen(f"{url}/api/v1/query?{q}", timeout=60))
        assert d["status"] == "success", d
        datos[sel] = d["data"]["result"]
    with gzip.open(destino, "wt") as fh:
        json.dump({"t_desde": t0, "t_hasta": t1, "resultado": datos}, fh)
    return {"archivo": destino, "series": sum(len(v) for v in datos.values())}


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def snapshot(url, datos_prom, destino, copiar):
    r = json.load(urllib.request.urlopen(urllib.request.Request(url + "/api/v1/admin/tsdb/snapshot", method="POST"), timeout=60))
    nombre = r["data"]["name"]
    if not copiar:
        return {"nombre": nombre, "copiado": False, "motivo": "snapshot cumulativo: se copia solo con --copiar-snapshot"}
    try:
        shutil.copytree(os.path.join(datos_prom, "snapshots", nombre), os.path.join(destino, nombre))
        return {"nombre": nombre, "copiado": True, "destino": os.path.join("data/prometheus-snapshots", nombre)}
    except OSError as e:
        return {"nombre": nombre, "copiado": False, "error": str(e)}


def preparar_fallo(a, acc, tit):
    """Nodo a fallar = titular de la .100 y la .150 a la vez; el pod de NGINX no puede estar en él (se mueve si coincide).
    Cada VIP tiene su lease: si los titulares difieren, se reinicia kube-vip (hasta 3 veces) para que se vuelvan a elegir."""
    ip_de = {n: ip for ip, n in nombres_nodos(a.prometheus, a.distribucion).items()}
    reinicios = 0
    while "no determinado" in tit.values() or tit["nodo_vip_plano_control"] != tit["nodo_vip_servicio"]:
        if reinicios == 3:
            sys.exit(f"Las VIP siguen en nodos distintos tras 3 reinicios de kube-vip: {tit}")
        rc, out = fallo.reiniciar_kube_vip(a.distribucion, acc, next(iter(ip_de.values())))
        if rc:
            sys.exit(f"No pude reiniciar kube-vip: {out}")
        reinicios += 1
        time.sleep(30)
        tit = titulares(a.prometheus, a.distribucion)
    nodo = tit["nodo_vip_plano_control"]
    otros = sorted(n for n in ip_de if n != nodo)
    movido = None
    if tit["nodo_pod"] == nodo:
        rc, out = fallo.mover_pod(a.distribucion, acc, ip_de[otros[0]], otros[0])
        if rc:
            sys.exit(f"No pude mover el pod a {otros[0]}: {out}")
        movido = {"desde": nodo, "hacia": otros[0]}
        for _ in range(18):
            time.sleep(5)
            if titulares(a.prometheus, a.distribucion)["nodo_pod"] == otros[0]:
                break
        else:
            sys.exit("kube-state-metrics no refleja el pod en el nodo nuevo")
    return nodo, ip_de[nodo], ip_de[otros[0]], movido, reinicios


def autotest():
    assert delta_rapl(10, 25, 100) == 15
    assert delta_rapl(95, 5, 100) == 10
    print("autotest ok")


def main():
    if "--autotest" in sys.argv:
        return autotest()
    ap = argparse.ArgumentParser()
    ap.add_argument("--distribucion", required=True, choices=["k3s", "microk8s"])
    ap.add_argument("--escenario", required=True, choices=["idle", "media", "alta"])
    ap.add_argument("--repeticion", required=True, type=int)
    ap.add_argument("--tasa", type=float, help="solicitudes/s de la fase estable (obligatoria en media y alta)")
    ap.add_argument("--rampa", type=int, default=30)
    ap.add_argument("--estable", type=int, default=180)
    ap.add_argument("--descenso", type=int, default=30)
    ap.add_argument("--pre-vus", type=int, default=50)
    ap.add_argument("--max-vus", type=int, default=200)
    ap.add_argument("--estabilizacion", type=int, default=60, help="s de espera antes de lanzar k6 (provisional)")
    ap.add_argument("--objetivo", default=f"http://{IP_VIP_SVC}:80/")
    ap.add_argument("--prometheus", default="http://127.0.0.1:9090")
    ap.add_argument("--datos-prometheus", default="/var/lib/prometheus/data")
    ap.add_argument("--cpus", default="0,1")
    ap.add_argument("--fallo", action="store_true", help="inyecta el fallo controlado (solo escenario media)")
    ap.add_argument("--fallo-en", type=int, default=30, help="s desde el inicio de la fase estable (provisional)")
    ap.add_argument("--fallo-retener", type=int, default=120, help="s con el proceso caído antes de restaurarlo (provisional)")
    ap.add_argument("--tipo", default="definitiva", choices=["definitiva", "piloto", "calibracion", "verificacion"],
                    help="piloto, calibración y verificación no son resultados finales; llevan prefijo en los archivos")
    ap.add_argument("--verificacion", action="store_const", const="verificacion", dest="tipo", help="alias de --tipo verificacion")
    ap.add_argument("--sesion", help="carpeta de sesión en data/<tipo>/ (por defecto: fecha local y distribución)")
    ap.add_argument("--sin-snapshot", action="store_true")
    ap.add_argument("--copiar-snapshot", action="store_true",
                    help="copia el snapshot a data/ (cada uno contiene los anteriores: copiar el último de cada bloque)")
    a = ap.parse_args()
    if a.escenario != "idle" and a.tasa is None:
        ap.error("--tasa es obligatoria en media y alta")
    if a.fallo and a.escenario != "media":
        ap.error("--fallo solo se define en el escenario media (protocolo, sección 4.4)")

    prefijo = {"definitiva": "", "piloto": "piloto_", "calibracion": "calib_", "verificacion": "verif_"}[a.tipo]
    base = prefijo + f"{a.distribucion}_{a.escenario}{'-fallo' if a.fallo else ''}_r{a.repeticion:02d}"
    tipo_dir = {"definitiva": "campana", "piloto": "pilotos", "calibracion": "calibracion", "verificacion": "verificacion"}[a.tipo]
    sesion = a.sesion or f"{time.strftime('%Y-%m-%d')}_{a.distribucion}"
    d_k6, d_meta, d_ventana = (os.path.join(RAIZ, "data", tipo_dir, sesion, x) for x in (
        "k6-resultados", "metadatos", "prometheus-ventanas"))
    d_snap, d_crudo = os.path.join(RAIZ, "data", "prometheus-snapshots"), os.path.join(RAIZ, "data", "k6-crudo", tipo_dir, sesion)
    f_json, f_res, f_meta = (os.path.join(d_crudo, base + ".json.gz"), os.path.join(d_k6, base + ".resumen.json"),
                             os.path.join(d_meta, base + ".json"))
    f_seg, f_ventana = os.path.join(d_k6, base + ".por_segundo.json.gz"), os.path.join(d_ventana, base + ".json.gz")
    for f in (f_json, f_res, f_meta, f_seg, f_ventana):
        if os.path.exists(f):
            sys.exit(f"Ya existe {f}; no se sobrescribe")
    for d in (d_k6, d_meta, d_snap, d_crudo, d_ventana):
        os.makedirs(d, exist_ok=True)

    if a.tasa:
        est = a.tasa * (a.rampa / 2 + a.estable + a.descenso / 2) * B_POR_SOLICITUD
        if est > UMBRAL_AVISO * LIMITE_ARCHIVO:
            print(f"AVISO: el JSON de k6 estimaría {est / 1e6:.0f} MB (límite de GitHub 100 MB por archivo)", file=sys.stderr)

    estabilizar(a.prometheus, a.distribucion, a.estabilizacion, a.objetivo)
    try:
        acc = fallo.acceso(RAIZ, a.distribucion)
    except (OSError, AttributeError):
        acc = None
    if a.fallo and acc is None:
        sys.exit(f"Falta el inventario de {a.distribucion} (lo genera Terraform) para acceder por SSH")
    pol = estado_host.cargar_politica()
    if pol is None:
        sys.exit("Falta /etc/tesis/medicion.json: correr el playbook del host (rol host_mediciones)")
    if acc is None:
        sys.exit(f"Falta el inventario de {a.distribucion} (lo genera Terraform): sin SSH no se puede verificar el reloj de las VM")
    reloj, motivos_reloj, espera_reloj = estado_host.esperar_reloj(lambda: fallo.reloj(acc, IPS_NODOS), pol)
    if motivos_reloj:
        sys.exit(f"Reloj sin converger tras {espera_reloj} s, no se lanza k6: {motivos_reloj}")
    estado, motivos_estado = estado_host.estado_host(pol)
    tit_ini = titulares(a.prometheus, a.distribucion)
    plan = None
    if a.fallo:
        plan = preparar_fallo(a, acc, tit_ini)
        tit_ini = titulares(a.prometheus, a.distribucion)
        params = fallo.parametros_efectivos(a.distribucion, acc, plan[2])
        macs = {ip: mac_de(ip) for ip in IPS_NODOS}
        obs = fallo.Observador(a.distribucion, acc, plan[2], {m: nombres_nodos(a.prometheus, a.distribucion)[ip] for ip, m in macs.items()})

    env = dict(os.environ, DISTRIBUCION=a.distribucion, ESCENARIO=a.escenario, REPETICION=str(a.repeticion),
               RAMPA_S=str(a.rampa), ESTABLE_S=str(a.estable), DESCENSO_S=str(a.descenso),
               PRE_VUS=str(a.pre_vus), MAX_VUS=str(a.max_vus), OBJETIVO=a.objetivo)
    if a.tasa is not None:
        env["TASA"] = str(a.tasa)
    cmd = ["taskset", "-c", a.cpus, "k6", "run", "--out", f"json={f_json}", "--summary-export", f_res,
           os.path.join(RAIZ, "k6", f"{a.escenario}.js")]
    ev, hilo = {}, None
    if plan:
        nodo_f, ip_f, ip_s, movido, reinicios = plan
        ev["preparacion"] = fallo.preparar(a.distribucion, acc, ip_f)
        obs.iniciar()
    t_lanzado = time.time()
    k6 = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def fallar():
        time.sleep(max(0, t_lanzado + a.rampa + a.fallo_en - time.time()))
        ev["rc_inyeccion"], ev["t_antes"], ev["t_despues"] = fallo.inyectar(RAIZ, a.distribucion, acc, ip_f)
        time.sleep(a.fallo_retener)
        ev["t_restaura"] = time.time()
        ev["restauracion"] = fallo.restaurar(a.distribucion, acc, ip_f)

    try:
        if plan:
            hilo = threading.Thread(target=fallar)
            hilo.start()
        time.sleep(max(0, t_lanzado + a.rampa - time.time()))
        e0, ta0, tb0 = leer_rapl()
        time.sleep(max(0, t_lanzado + a.rampa + a.estable - time.time()))
        e1, ta1, tb1 = leer_rapl()
        rc = k6.wait()
        t_fin_ejec = time.time()
    finally:
        if plan:
            if hilo:
                hilo.join(timeout=a.fallo_retener + 200)
            ev["restauracion_final"] = fallo.restaurar(a.distribucion, acc, ip_f)
            for _ in range(150):
                if obs.nodo_listo(nodo_f):
                    break
                time.sleep(2)
            ev["nodo_listo_al_final"] = obs.nodo_listo(nodo_f)
            obs.detener()

    maximo = int(open(RAPL + "max_energy_range_uj").read())
    t_ini_v, t_fin_v = (ta0 + tb0) / 2, (ta1 + tb1) / 2
    d_uj = delta_rapl(e0, e1, maximo)
    tit_fin = titulares(a.prometheus, a.distribucion)
    snap = None if a.sin_snapshot else snapshot(a.prometheus, a.datos_prometheus, d_snap, a.copiar_snapshot)
    ventana = exportar_ventana(a.prometheus, t_lanzado - 30, time.time(), f_ventana)
    ventana["archivo"] = os.path.relpath(f_ventana, RAIZ)
    filas = agregado.por_segundo(f_json) if os.path.exists(f_json) else []
    with gzip.open(f_seg, "wt") as fh:
        json.dump(filas, fh)

    tam_json = os.path.getsize(f_json) if os.path.exists(f_json) else None
    if tam_json and tam_json > UMBRAL_AVISO * LIMITE_ARCHIVO:
        print(f"AVISO: {f_json} pesa {tam_json / 1e6:.0f} MB (límite de GitHub 100 MB por archivo)", file=sys.stderr)
    bloque_fallo = None
    if plan and "t_antes" in ev:
        consulta = (f'kube_node_status_condition{{distribution="{a.distribucion}",node="{nodo_f}",'
                    'condition="Ready",status="true"}')
        ksm = prom_rango(a.prometheus, consulta, ev["t_antes"] - 60, time.time())
        f_obs = os.path.join(d_meta, base + ".observador.json.gz")
        with gzip.open(f_obs, "wt") as fh:
            json.dump({"muestras": obs.muestras, "estado": obs.estado, "ksm": ksm}, fh)
        bloque_fallo = {
            "nodo_fallado": nodo_f, "ip": ip_f, "unidad": fallo.UNIDAD[a.distribucion], "nodo_observador": ip_s,
            "parametros": {"fallo_en_s": a.fallo_en, "retener_s": a.fallo_retener, "reinicio_automatico": "desactivado durante la retención"},
            "pod_movido": movido, "reinicios_kube_vip": reinicios,
            "parametros_efectivos": params, "eventos": ev,
            "observador": os.path.relpath(f_obs, RAIZ),
            "analisis": fallo.analizar(obs, ev["t_antes"], ev["t_despues"], nodo_f, ksm, f_json),
        }
    elif plan:
        bloque_fallo = {"error": "no se inyectó el fallo", "eventos": ev}
    primer_punto = None
    if os.path.exists(f_json):
        with gzip.open(f_json, "rt") as fh:
            for linea in fh:
                m = re.search(r'"time":"([^"]+)"', linea)
                if m:
                    primer_punto = m.group(1)
                    break
    meta = {
        "esquema": 2, "tipo": a.tipo, "verificacion": a.tipo == "verificacion", "distribution": a.distribucion,
        "escenario": a.escenario, "repeticion": a.repeticion,
        "t_inicio": round(t_ini_v, 3), "t_fin": round(t_fin_v, 3),
        "t_ejecucion_inicio": round(t_lanzado, 3), "t_ejecucion_fin": round(t_fin_ejec, 3),
        "parametros": {"tasa": a.tasa, "rampa_s": a.rampa, "estable_s": a.estable, "descenso_s": a.descenso,
                       "pre_vus": a.pre_vus, "max_vus": a.max_vus, "estabilizacion_s": a.estabilizacion,
                       "objetivo": a.objetivo},
        "rapl": {"dominio": "package-0", "max_energy_range_uj": maximo, "energy_uj_inicio": e0, "energy_uj_fin": e1,
                 "lectura_inicio_s": [round(ta0, 3), round(tb0, 3)], "lectura_fin_s": [round(ta1, 3), round(tb1, 3)],
                 "desbordamiento": e1 < e0, "delta_uj": d_uj,
                 "potencia_media_W": round(d_uj / 1e6 / (t_fin_v - t_ini_v), 3)},
        "titulares": {"inicio": tit_ini, "fin": tit_fin, "cambiaron": tit_ini != tit_fin,
                      "metodo": "VIP: MAC vista por el host en ARP (ip neigh tras ping) comparada con la MAC de cada nodo; "
                                "pod: kube_pod_info de kube-state-metrics vía Prometheus"},
        "k6": {"codigo_salida": rc, "cpus": a.cpus, "json": os.path.relpath(f_json, RAIZ),
               "resumen": os.path.relpath(f_res, RAIZ), "tamano_json_bytes": tam_json, "sha256_json": sha256(f_json) if tam_json else None,
               "por_segundo": os.path.relpath(f_seg, RAIZ), "primer_punto_json": primer_punto,
               "version": subprocess.run(["k6", "version"], capture_output=True, text=True).stdout.strip()},
        "snapshot": snap, "ventana_prometheus": ventana, "reloj_antes": reloj,
        "reloj_espera_s": espera_reloj, "estado_host": estado, "valida_para_campana": a.tipo == "definitiva" and not motivos_estado,
        "motivos_no_valida": motivos_estado + ([f"tipo {a.tipo}"] if a.tipo != "definitiva" else []), "fallo": bloque_fallo,
    }
    json.dump(meta, open(f_meta, "w"), indent=2)
    print(json.dumps({k: meta[k] for k in ("t_inicio", "t_fin", "titulares", "snapshot")} | {"k6_rc": rc,
          "rapl_W": meta["rapl"]["potencia_media_W"], "meta": os.path.relpath(f_meta, RAIZ)}, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main() or 0)
