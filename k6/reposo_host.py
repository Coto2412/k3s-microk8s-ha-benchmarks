#!/usr/bin/env python3
"""Reposo del host (T-20.7): potencia RAPL en ventanas consecutivas, sin VMs ni k6, en el estado de medición.

Estado de medición = sin sesión gráfica + `sudo tesis-modo-medicion entrar` (solo corren las unidades permitidas).
Ejemplo: k6/reposo_host.py --sesion 1
"""
import argparse, json, os, subprocess, sys, time

import estado_host
from orquestador import RAIZ, delta_rapl, leer_rapl, prom, RAPL


def precondiciones():
    """Motivos por los que no se puede medir el reposo (lista vacía = se puede)."""
    m = []
    vms = subprocess.run(["virsh", "list", "--name"], capture_output=True, text=True).stdout.split()
    if vms:
        m.append(f"hay VMs encendidas: {vms}")
    if subprocess.run(["pgrep", "-x", "k6"], capture_output=True).returncode == 0:
        m.append("hay un k6 en ejecución")
    if estado_host.activo("display-manager.service"):
        m.append("la sesión gráfica está activa")
    if not os.path.exists(estado_host.ESTADO_MODO):
        m.append("el modo medición no está activo (sudo /usr/local/sbin/tesis-modo-medicion entrar)")
    return m


def sondas(prom_url, ventana):
    """Variables del host al cierre de cada ventana (no entran en la potencia, solo describen el reposo)."""
    s = {"carga_1min": os.getloadavg()[0]}
    try:
        r = prom(prom_url, f'1 - avg(rate(node_cpu_seconds_total{{job="node_exporter_host",mode="idle"}}[{ventana}s]))')
        s["cpu_ocupada_node_exporter"] = round(float(r[0]["value"][1]), 5) if r else None
    except Exception as e:
        s["cpu_ocupada_node_exporter"] = f"error: {type(e).__name__}"
    estado, _ = estado_host.estado_host(estado_host.cargar_politica())
    s["temperatura_cpu_C"] = estado.get("temperatura_cpu_C")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sesion", required=True, type=int, help="orden de la sesión en la secuencia (1, 2, ...)")
    ap.add_argument("--ventanas", type=int, default=3)
    ap.add_argument("--ventana", type=int, default=180, help="s por ventana (la misma que la fase estable)")
    ap.add_argument("--calentamiento", type=int, default=120, help="s de espera tras el cambio de condición")
    ap.add_argument("--prometheus", default="http://127.0.0.1:9090")
    a = ap.parse_args()

    pol = estado_host.cargar_politica()
    salida = os.path.join(RAIZ, "data", "reposo", f"reposo_host_s{a.sesion:02d}.json")
    if os.path.exists(salida):
        sys.exit(f"Ya existe {salida}; no se sobrescribe")
    motivos = precondiciones()
    if motivos:
        sys.exit("No se puede medir: " + "; ".join(motivos))

    print(f"calentamiento {a.calentamiento} s", flush=True)
    time.sleep(a.calentamiento)
    estado_ini, motivos_estado = estado_host.estado_host(pol)
    reloj = subprocess.run(["chronyc", "tracking"], capture_output=True, text=True).stdout
    lecturas = [leer_rapl()]
    ventanas = []
    maximo = int(open(RAPL + "max_energy_range_uj").read())
    for i in range(a.ventanas):
        time.sleep(max(0, lecturas[-1][2] + a.ventana - time.time()))
        lecturas.append(leer_rapl())
        (e0, ta0, tb0), (e1, ta1, tb1) = lecturas[-2], lecturas[-1]
        t0, t1 = (ta0 + tb0) / 2, (ta1 + tb1) / 2
        d = delta_rapl(e0, e1, maximo)
        w = {"ventana": i + 1, "t_inicio": round(t0, 3), "t_fin": round(t1, 3), "delta_uj": d,
             "potencia_media_W": round(d / 1e6 / (t1 - t0), 3), "desbordamiento": e1 < e0,
             "sondas": sondas(a.prometheus, a.ventana)}
        ventanas.append(w)
        print(f"ventana {i + 1}: {w['potencia_media_W']} W", flush=True)

    meta = {"esquema": 1, "tipo": "reposo_host", "sesion": a.sesion,
            "parametros": {"ventana_s": a.ventana, "ventanas": a.ventanas, "calentamiento_s": a.calentamiento},
            "rapl": {"dominio": "package-0", "max_energy_range_uj": maximo}, "ventanas": ventanas,
            "estado_host_inicio": estado_ini, "motivos_estado": motivos_estado, "chronyc_tracking": reloj}
    json.dump(meta, open(salida, "w"), indent=2)
    print(json.dumps({"archivo": os.path.relpath(salida, RAIZ), "W": [w["potencia_media_W"] for w in ventanas]}))


if __name__ == "__main__":
    main()
