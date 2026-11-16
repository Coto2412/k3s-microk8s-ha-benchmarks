"""Diagnóstico del desfase de ≈ 1 W entre series con la misma carga (T-24.4).

Mide potencia RAPL en ventanas de reposo (clúster arriba, sin k6) con los contadores de instrumentacion.py.
Se lanza como usuario desde la consola de texto, sin otras aplicaciones abiertas y con el modo medición activo:

  python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase serie                # ≈ 1 h sin intervenir
  python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase ciclos --ciclos 3    # salir/entrar entre ventanas
  sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase abab --factor ksm   # ksm|cstates|haltpoll (root); emulatorpin (sin sudo)
  python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase reconstruccion --ciclos 2   # referencia, construir, 3 idle, destruir
  python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase reinicio                    # virsh shutdown/start, Ready, 3 idle
  sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase confirmacion --factor ksm --ciclos 2  # reconstruccion con el factor B

reconstruccion y confirmacion destruyen el clúster de la distribución si está arriba y lo dejan destruido.

--simulacro acorta las ventanas y no exige precondiciones; no hace salir/entrar. Devolver todo data/diagnostico/.
El script no decide la causa: el veredicto lo escribo después, con el análisis de los JSON.
"""
import argparse, glob, json, os, subprocess, sys, time

from k6.lib import estado_host, fallo, instrumentacion, recursos
from k6.lib.comun import RAIZ, IPS_NODOS, RAPL, delta_rapl, leer_rapl
from k6.medicion import tramo

TEMP_MAX_C = 85  # umbral mío de aborto, sin derivar de una prueba
MODO = "/usr/local/sbin/tesis-modo-medicion"
EMULADOR_CPUS = "8-15"  # hilos fuera de las vCPU (2-7) y del núcleo del host (0-1)
CICLO_BASE = 300  # campo `ciclo` del registro de despliegue del diagnóstico: 300 + ciclo
CON_CLUSTER = ("serie", "ciclos", "abab", "reinicio")


class Aborto(Exception):
    pass


def _rd(ruta):
    return open(ruta).read().strip()


def _wr(ruta, valor):
    open(ruta, "w").write(str(valor))


def factor(nombre):
    """(estado original, aplicar B, restaurar A, necesita root). A es el estado original; B, el cambio."""
    if nombre == "ksm":
        r = "/sys/kernel/mm/ksm/run"
        o = _rd(r)
        return o, lambda: _wr(r, "0"), lambda: _wr(r, o), True  # B = KSM en pausa (plan, E6); si ya estaba en 0, A = B
    if nombre == "haltpoll":
        r = "/sys/module/kvm/parameters/halt_poll_ns"
        o = _rd(r)
        return o, lambda: _wr(r, "0"), lambda: _wr(r, o), True
    if nombre == "cstates":
        fs = {f: _rd(f) for f in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpuidle/state[2-9]/disable"))}
        return fs, lambda: [_wr(f, "1") for f in fs], lambda: [_wr(f, v) for f, v in fs.items()], True
    if nombre == "emulatorpin":
        doms = subprocess.run(["virsh", "-c", "qemu:///system", "list", "--name"], capture_output=True, text=True).stdout.split()
        o = {d: subprocess.run(["virsh", "-c", "qemu:///system", "emulatorpin", d], capture_output=True, text=True).stdout.split("*:")[-1].strip() for d in doms}
        pin = lambda d, c: subprocess.run(["virsh", "-c", "qemu:///system", "emulatorpin", d, c, "--live"], capture_output=True, check=True)
        return o, lambda: [pin(d, EMULADOR_CPUS) for d in doms], lambda: [pin(d, c) for d, c in o.items()], False
    raise SystemExit(f"factor desconocido: {nombre}")


def precondiciones(acc, con_cluster=True):
    m = []
    if not os.path.exists(estado_host.ESTADO_MODO):
        m.append(f"modo medición no activo (sudo {MODO} entrar)")
    if estado_host.activo("display-manager.service"):
        m.append("sesión gráfica activa")
    if subprocess.run(["pgrep", "-x", "k6"], capture_output=True).returncode == 0:
        m.append("hay un k6 en ejecución")
    for ip in IPS_NODOS if con_cluster else []:
        if fallo.ssh(acc, ip, "true", 10)[0] != 0:
            m.append(f"sin SSH a {ip}")
    return m


def vigilar(acc, pol, t_ini, limite_h, simulacro, esperar_modo=True):
    """Reglas de aborto. Se evalúan tras cada ventana."""
    if time.time() - t_ini > limite_h * 3600:
        raise Aborto(f"límite de tiempo ({limite_h} h)")
    temp = instrumentacion.host().get("temperatura_mC")
    if temp and int(temp) / 1000 > TEMP_MAX_C:
        raise Aborto(f"temperatura {int(temp) / 1000:.1f} °C > {TEMP_MAX_C} °C")
    mem = next(int(l.split()[1]) // 1024 for l in open("/proc/meminfo") if l.startswith("MemAvailable"))
    if mem < estado_host.MEM_MIN_MB:
        raise Aborto(f"memoria disponible {mem} MB < {estado_host.MEM_MIN_MB} MB")
    if simulacro:
        return
    if esperar_modo and not os.path.exists(estado_host.ESTADO_MODO):
        raise Aborto("el modo medición dejó de estar activo")
    _, motivos, _ = estado_host.esperar_reloj(lambda: fallo.reloj(acc, IPS_NODOS), pol)
    if motivos:
        raise Aborto(f"reloj sin converger: {motivos}")


def ventana(acc, segs, etiqueta, **extra):
    mu = recursos.Muestreador(2.0)
    mu.start()
    i0 = instrumentacion.leer(acc, IPS_NODOS)
    e0, ta0, tb0 = leer_rapl()
    time.sleep(max(0, tb0 + segs - time.time()))
    e1, ta1, tb1 = leer_rapl()
    i1 = instrumentacion.leer(acc, IPS_NODOS)
    mu.detener()
    t0, t1 = (ta0 + tb0) / 2, (ta1 + tb1) / 2
    d = delta_rapl(e0, e1, int(_rd(RAPL + "max_energy_range_uj")))
    w = {"etiqueta": etiqueta, **extra, "t_inicio": round(t0, 3), "t_fin": round(t1, 3), "delta_uj": d,
         "potencia_media_W": round(d / 1e6 / (t1 - t0), 3), "desbordamiento": e1 < e0,
         "instrumentacion": instrumentacion.delta(i0, i1),
         "muestreo": recursos.resumen_muestreo(mu.muestras, t0, t1, estado_host.MEM_MIN_MB)}
    print(f"[{time.strftime('%H:%M:%S')}] {etiqueta}: {w['potencia_media_W']} W", flush=True)
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--distribucion", required=True, choices=["k3s", "microk8s"])
    ap.add_argument("--fase", required=True, choices=["serie", "ciclos", "abab", "reconstruccion", "reinicio", "confirmacion"])
    ap.add_argument("--factor", choices=["ksm", "cstates", "haltpoll", "emulatorpin"])
    ap.add_argument("--ventanas", type=int, default=20, help="serie: ventanas consecutivas (20 × 180 s ≈ 1 h)")
    ap.add_argument("--ciclos", type=int, help="ciclos: salir/entrar (3); reconstruccion y confirmacion: construcciones (2); reinicio: reinicios (1)")
    ap.add_argument("--ventanas-por-condicion", type=int, default=3, help="ciclos y abab: ventanas tras cada cambio")
    ap.add_argument("--pares", type=int, default=2, help="abab: número de pares A,B (2 = ABAB)")
    ap.add_argument("--ventana", type=int, default=180)
    ap.add_argument("--calentamiento", type=int, default=120)
    ap.add_argument("--limite-h", type=float, default=4.0)
    ap.add_argument("--simulacro", action="store_true")
    a = ap.parse_args()
    a.ciclos = a.ciclos or {"reconstruccion": 2, "confirmacion": 2, "reinicio": 1}.get(a.fase, 3)  # los del plan (sección 5.1)
    if a.fase in ("abab", "confirmacion") and not a.factor:
        ap.error(f"--fase {a.fase} exige --factor")
    ref = (3, 10) if a.simulacro else (120, 180)  # ventana de referencia: espera y medición, como en la campaña
    if a.simulacro:
        a.ventana, a.calentamiento = 10, 3
    acc = fallo.acceso(RAIZ, a.distribucion) if a.fase in CON_CLUSTER else None
    pol = estado_host.cargar_politica()
    if pol is None and not a.simulacro:
        sys.exit("Falta /etc/tesis/medicion.json: correr el playbook del host")
    motivos = precondiciones(acc, a.fase in CON_CLUSTER)
    if motivos:
        if not a.simulacro:
            sys.exit("No se puede medir: " + "; ".join(motivos))
        print("(simulacro) precondiciones no cumplidas:", motivos)

    t_ini = time.time()
    sufijo = f"{a.fase}{'_' + a.factor if a.factor else ''}_{a.distribucion}_{time.strftime('%Y%m%dT%H%M')}"
    carpeta = os.path.join(RAIZ, "data", "diagnostico", ("simulacro_" if a.simulacro else "") + time.strftime("%Y-%m-%d"))
    os.makedirs(carpeta, exist_ok=True)
    salida = os.path.join(carpeta, sufijo + ".json")
    res = {"esquema": 1, "tipo": "diagnostico_desfase", "fase": a.fase, "distribucion": a.distribucion, "factor": a.factor,
           "parametros": {k: v for k, v in vars(a).items() if k not in ("distribucion", "fase", "factor")},
           "inicio": round(t_ini, 3), "condiciones": [], "abortada": None, "veredicto": "pendiente de análisis"}
    res["estado_host_inicio"], res["motivos_estado"] = (estado_host.estado_host(pol) if pol else (None, ["sin política"]))

    def guardar():
        json.dump(res, open(salida, "w"), indent=1, default=str)

    registro = os.path.join(carpeta, f"despliegue_{a.distribucion}.jsonl")
    logs = os.path.join(carpeta, "registros")
    os.makedirs(logs, exist_ok=True)
    if os.environ.get("SUDO_UID"):  # despliegue.sh corre como el operador y escribe aquí su registro
        for d in (carpeta, logs):
            os.chown(d, int(os.environ["SUDO_UID"]), int(os.environ.get("SUDO_GID", os.environ["SUDO_UID"])))

    def guardar_paso(nombre, r):
        res.setdefault("pasos", []).append({"paso": nombre, **r})
        guardar()
        print(f"[{time.strftime('%H:%M:%S')}] {nombre}: {'ok' if r.get('ok', True) else 'ERROR'}", flush=True)
        if r.get("ok") is False:
            raise Aborto(f"{nombre}: {r.get('motivo') or r.get('fallidas') or r.get('rc')}")

    def destruir_si_arriba(ciclo):
        if any(d.startswith(a.distribucion) for d in tramo.vms_encendidas()):
            guardar_paso(f"destruccion previa (ciclo {ciclo})", tramo.destruir(a.distribucion, ciclo, registro, logs))

    def condicion(nombre, n, calentar=True, **extra):
        c = {"condicion": nombre, **extra, "ventanas": []}
        res["condiciones"].append(c)
        if calentar:
            time.sleep(a.calentamiento)
        for i in range(n):
            c["ventanas"].append(ventana(acc, a.ventana, f"{nombre} v{i + 1}"))
            guardar()
            vigilar(acc, pol, t_ini, a.limite_h, a.simulacro)

    restaurar = None
    try:
        if a.fase == "serie":
            condicion("serie", a.ventanas)
        elif a.fase == "ciclos":
            condicion("base", a.ventanas_por_condicion)
            for c in range(1, a.ciclos + 1):
                if a.simulacro:
                    print("(simulacro) se omite salir/entrar")
                else:
                    for orden in ("salir", "entrar"):
                        if subprocess.run(["sudo", "-n", MODO, orden]).returncode != 0:
                            raise Aborto(f"tesis-modo-medicion {orden} falló")
                        time.sleep(30 if orden == "salir" else 5)
                condicion(f"ciclo{c}", a.ventanas_por_condicion, ciclo=c)
        elif a.fase in ("reconstruccion", "confirmacion"):
            if a.fase == "confirmacion":
                if a.factor == "emulatorpin":  # versión persistente: XSLT de Terraform, en cada construcción
                    os.environ["TF_VAR_emulatorpin"] = EMULADOR_CPUS
                    res["factor_original"] = "sin fijar (TF_VAR_emulatorpin vacío)"
                else:
                    original, aplicar, restaurar, root = factor(a.factor)
                    if root and os.geteuid() != 0:
                        sys.exit(f"El factor {a.factor} escribe en /sys: ejecutar con sudo")
                    res["factor_original"] = original
                    aplicar()
            destruir_si_arriba(CICLO_BASE)
            for c in range(1, a.ciclos + 1):
                ciclo = CICLO_BASE + c
                guardar_paso(f"referencia ciclo{c}", tramo.referencia(*ref))
                guardar_paso(f"construccion ciclo{c}", tramo.construir(a.distribucion, ciclo, registro, logs))
                acc = fallo.acceso(RAIZ, a.distribucion)
                guardar_paso(f"verificacion ciclo{c}", tramo.verificar(a.distribucion, "http://127.0.0.1:9090", 300))
                condicion(f"ciclo{c}", a.ventanas_por_condicion, ciclo=c)
                guardar_paso(f"destruccion ciclo{c}", tramo.destruir(a.distribucion, ciclo, registro, logs))
        elif a.fase == "reinicio":
            for c in range(1, a.ciclos + 1):
                doms = [d for d in tramo.vms_encendidas() if d.startswith(a.distribucion)]
                t0 = time.time()
                for d in doms:
                    subprocess.run([*tramo.VIRSH, "shutdown", d], capture_output=True, check=True)
                while any(d.startswith(a.distribucion) for d in tramo.vms_encendidas()):
                    if time.time() - t0 > 300:
                        raise Aborto("las VMs no se apagaron en 300 s")
                    time.sleep(2)
                t_apagado = time.time()
                for d in doms:
                    subprocess.run([*tramo.VIRSH, "start", d], capture_output=True, check=True)
                guardar_paso(f"reinicio{c}", {"vms": doms, "apagado_s": round(t_apagado - t0, 1)})
                guardar_paso(f"verificacion reinicio{c}", tramo.verificar(a.distribucion, "http://127.0.0.1:9090", 600))
                condicion(f"reinicio{c}", a.ventanas_por_condicion, ciclo=c)
        else:
            original, aplicar, restaurar, root = factor(a.factor)
            if root and os.geteuid() != 0:
                sys.exit(f"El factor {a.factor} escribe en /sys: ejecutar con sudo")
            res["factor_original"] = original
            for p in range(1, a.pares + 1):
                restaurar()
                condicion(f"A{p}", a.ventanas_por_condicion, par=p)
                aplicar()
                condicion(f"B{p}", a.ventanas_por_condicion, par=p)
    except Aborto as e:
        res["abortada"] = str(e)
        print(f"ABORTADA: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        res["abortada"] = "interrumpida por el usuario"
    finally:
        if restaurar:
            try:
                restaurar()
                res["factor_restaurado"] = True
            except Exception as e:
                res["factor_restaurado"] = f"ERROR al restaurar: {e}"
                print(f"ERROR al restaurar {a.factor}: {e}", file=sys.stderr)
        res["fin"] = round(time.time(), 3)
        guardar()
        if os.environ.get("SUDO_UID"):
            subprocess.run(["chown", "-R", f"{os.environ['SUDO_UID']}:{os.environ.get('SUDO_GID', os.environ['SUDO_UID'])}", carpeta])
    print(json.dumps({"archivo": os.path.relpath(salida, RAIZ), "abortada": res["abortada"],
                      "W": {c["condicion"]: [w["potencia_media_W"] for w in c["ventanas"]] for c in res["condiciones"]}}))
    return 2 if res["abortada"] else 0


if __name__ == "__main__":
    sys.exit(main())
