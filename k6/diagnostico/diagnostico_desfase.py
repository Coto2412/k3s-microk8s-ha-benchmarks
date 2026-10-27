"""Diagnóstico del desfase de ≈ 1 W entre series con la misma carga (T-24.4).

Mide potencia RAPL en ventanas de reposo (clúster arriba, sin k6) con los contadores de instrumentacion.py.
Se lanza como usuario desde la consola de texto, con Claude Code cerrado y el modo medición activo:

  python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase serie                # ≈ 1 h sin intervenir
  python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase ciclos --ciclos 3    # salir/entrar entre ventanas
  sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase abab --factor ksm   # ksm|cstates|haltpoll (root); emulatorpin (sin sudo)

--simulacro acorta las ventanas y no exige precondiciones; no hace salir/entrar. Devolver todo data/diagnostico/.
El script no decide la causa: el veredicto lo escribo después, con el análisis de los JSON.
"""
import argparse, glob, json, os, subprocess, sys, time

from k6.lib import estado_host, fallo, instrumentacion
from k6.lib.comun import RAIZ, IPS_NODOS, RAPL, delta_rapl, leer_rapl

TEMP_MAX_C = 85  # umbral mío de aborto, sin derivar de una prueba
MODO = "/usr/local/sbin/tesis-modo-medicion"


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
        return o, lambda: _wr(r, "0" if o == "1" else "1"), lambda: _wr(r, o), True
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
        return o, lambda: [pin(d, "8-15") for d in doms], lambda: [pin(d, c) for d, c in o.items()], False
    raise SystemExit(f"factor desconocido: {nombre}")


def precondiciones(acc):
    m = []
    if not os.path.exists(estado_host.ESTADO_MODO):
        m.append(f"modo medición no activo (sudo {MODO} entrar)")
    if estado_host.activo("display-manager.service"):
        m.append("sesión gráfica activa")
    if subprocess.run(["pgrep", "-x", "k6"], capture_output=True).returncode == 0:
        m.append("hay un k6 en ejecución")
    for ip in IPS_NODOS:
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
    i0 = instrumentacion.leer(acc, IPS_NODOS)
    e0, ta0, tb0 = leer_rapl()
    time.sleep(max(0, tb0 + segs - time.time()))
    e1, ta1, tb1 = leer_rapl()
    i1 = instrumentacion.leer(acc, IPS_NODOS)
    t0, t1 = (ta0 + tb0) / 2, (ta1 + tb1) / 2
    d = delta_rapl(e0, e1, int(_rd(RAPL + "max_energy_range_uj")))
    w = {"etiqueta": etiqueta, **extra, "t_inicio": round(t0, 3), "t_fin": round(t1, 3), "delta_uj": d,
         "potencia_media_W": round(d / 1e6 / (t1 - t0), 3), "desbordamiento": e1 < e0,
         "instrumentacion": instrumentacion.delta(i0, i1)}
    print(f"[{time.strftime('%H:%M:%S')}] {etiqueta}: {w['potencia_media_W']} W", flush=True)
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--distribucion", required=True, choices=["k3s", "microk8s"])
    ap.add_argument("--fase", required=True, choices=["serie", "ciclos", "abab"])
    ap.add_argument("--factor", choices=["ksm", "cstates", "haltpoll", "emulatorpin"])
    ap.add_argument("--ventanas", type=int, default=20, help="serie: ventanas consecutivas (20 × 180 s ≈ 1 h)")
    ap.add_argument("--ciclos", type=int, default=3)
    ap.add_argument("--ventanas-por-condicion", type=int, default=3, help="ciclos y abab: ventanas tras cada cambio")
    ap.add_argument("--pares", type=int, default=2, help="abab: número de pares A,B (2 = ABAB)")
    ap.add_argument("--ventana", type=int, default=180)
    ap.add_argument("--calentamiento", type=int, default=120)
    ap.add_argument("--limite-h", type=float, default=4.0)
    ap.add_argument("--simulacro", action="store_true")
    a = ap.parse_args()
    if a.fase == "abab" and not a.factor:
        ap.error("--fase abab exige --factor")
    if a.simulacro:
        a.ventana, a.calentamiento = 10, 3
    acc = fallo.acceso(RAIZ, a.distribucion)
    pol = estado_host.cargar_politica()
    if pol is None and not a.simulacro:
        sys.exit("Falta /etc/tesis/medicion.json: correr el playbook del host")
    motivos = precondiciones(acc)
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
