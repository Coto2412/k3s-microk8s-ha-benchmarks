"""Ejecutor de la campaña (E5, Etapa 4): recorre los tramos de una jornada según el plan fijado.

  python3 -m k6.medicion.campana --plan data/campana/plan_campana_v1.json --jornada <n> --bloques <i>-<j> [--reanudar] [--simulacro]
  python3 -m k6.medicion.campana --plan ... --jornada 0 --bloques 0 --tipo piloto      # bloque 0: orden del bloque 1, en data/pilotos/
  python3 -m k6.medicion.campana --plan ... --jornada 4 --bloques 3 --reserva          # bloque de reserva: sesiones b03r_<dist>

Cada tramo: etiqueta, memoria, ventana de referencia, construcción (un reintento), verificación, RTT y plano de control,
6 corridas, repeticiones de las no válidas, almacenamiento, corrida con fallo, destrucción y respaldo. Todo queda en el
diario (<datos>/<tipo>/diario/jornada_<n>.jsonl y .log) y en estado_actual.json. Ctrl+C o SIGTERM: detiene k6, restaura
el fallo, registra y sale sin destruir datos ni el clúster.
"""
import argparse, glob, json, os, shutil, signal, subprocess, sys, tarfile, time
import urllib.request

from k6.lib import estado_host, fallo
from k6.lib.comun import IPS_NODOS, RAIZ, sha256
from k6.medicion import tramo
from k6.operacion import etiqueta

CODIGO_ABORTO_MEMORIA = 86  # el mismo del orquestador (k6/medicion/orquestador.py)
REPETICION_OFFSET = 10  # una corrida repetida lleva repetición 10 + la original (r01 -> r11)
DURACION_TRAMO_MIN = {"k3s": 60, "microk8s": 69}  # típicos del plan (cálculo, no medición); el bloque 0 los verifica
CODIGO_GIT = ["k6", "ansible", "k3sHA", "microk8sHA"]
LIBRE_MIN_GB = 20
TIPO_DIR = {"definitiva": "campana", "piloto": "pilotos"}
PREFIJO = {"definitiva": "", "piloto": "piloto_"}
FASES = {False: {"rampa": 30, "estable": 180, "descenso": 30, "estabilizacion": 120, "fallo_en": 30, "fallo_retener": 120,
                 "ref_espera": 120, "ref_medicion": 180},
         True: {"rampa": 15, "estable": 30, "descenso": 10, "estabilizacion": 10, "fallo_en": 5, "fallo_retener": 15,
                "ref_espera": 3, "ref_medicion": 10}}


class Interrumpido(Exception):
    pass


class Diario:
    def __init__(self, carpeta, jornada):
        os.makedirs(carpeta, exist_ok=True)
        self.jsonl = os.path.join(carpeta, f"jornada_{jornada}.jsonl")
        self.log = os.path.join(carpeta, f"jornada_{jornada}.log")
        self.estado = os.path.join(carpeta, "estado_actual.json")
        self.jornada, self.contexto = jornada, {}

    def paso(self, paso, resultado, t0=None, **detalle):
        ahora = time.time()
        linea = {"t": round(ahora, 3), "hora": time.strftime("%Y-%m-%d %H:%M:%S"), "jornada": self.jornada, **self.contexto,
                 "paso": paso, "resultado": resultado, "duracion_s": round(ahora - t0, 1) if t0 else None, **detalle}
        with open(self.jsonl, "a") as fh:
            fh.write(json.dumps(linea, ensure_ascii=False, default=str) + "\n")
        resumen = " ".join(f"{k}={v}" for k, v in detalle.items() if isinstance(v, (str, int, float, bool)) and len(str(v)) < 80)
        with open(self.log, "a") as fh:
            fh.write(f"[{linea['hora']}] {self.contexto.get('sesion', '-'):14} {paso:22} {resultado:12} "
                     f"{'' if linea['duracion_s'] is None else str(linea['duracion_s']) + ' s'} {resumen}\n")
        print(f"[{linea['hora']}] {self.contexto.get('sesion', '-')} {paso}: {resultado}", flush=True)
        self.actualizar(paso=paso, resultado=resultado)
        return linea

    def actualizar(self, **kv):
        d = json.load(open(self.estado)) if os.path.exists(self.estado) else {}
        if not self.contexto:  # fuera de un tramo no quedan datos del tramo anterior
            for k in ("bloque", "distribucion", "sesion", "corrida"):
                d.pop(k, None)
        d.update(kv, t=round(time.time(), 3), hora=time.strftime("%Y-%m-%d %H:%M:%S"), jornada=self.jornada, **self.contexto)
        tmp = self.estado + ".tmp"
        json.dump(d, open(tmp, "w"), indent=1, ensure_ascii=False, default=str)
        os.replace(tmp, self.estado)

    def lineas(self):
        return [json.loads(l) for l in open(self.jsonl)] if os.path.exists(self.jsonl) else []


def leer_bloques(texto):
    i, _, j = texto.partition("-")
    return list(range(int(i), int(j or i) + 1))


def tramos_de(plan, bloques, reserva):
    """[(bloque, distribución, sesión, corridas)] en el orden sorteado. El bloque 0 usa el orden y las corridas del bloque 1."""
    por_n = {b["bloque"]: b for b in plan["bloques"]}
    out = []
    for n in bloques:
        b = por_n[1 if n == 0 else n]
        for t in b["tramos"]:
            out.append((n, t["distribucion"], f"b{n:02d}{'r' if reserva else ''}_{t['distribucion']}", t["corridas"]))
    return out


def precondiciones(a, plan):
    """Las de la jornada (sección E5.1 del plan). En simulacro solo informan, salvo las VMs encendidas."""
    m = []
    pol = estado_host.cargar_politica()
    est, motivos = estado_host.estado_host(pol, memoria_invalida=False) if pol else ({}, ["falta la política del host"])
    if est.get("sesion_grafica_activa"):
        m.append("sesión gráfica activa")
    if not est.get("modo_medicion"):
        m.append("modo medición no activo")
    m += [x for x in motivos if x.startswith(("contenedores", "equipo sin corriente"))]
    if a.tipo == "definitiva" and plan.get("estado") != "fijado":
        m.append(f"el plan no está fijado (estado: {plan.get('estado')})")
    sucio = subprocess.run(["git", "status", "--porcelain", "--", *CODIGO_GIT], cwd=RAIZ, capture_output=True, text=True).stdout.strip()
    if sucio:
        m.append(f"cambios sin commit en el código de medición: {sucio.splitlines()[:5]}")
    libre = shutil.disk_usage(RAIZ).free / 1e9
    if libre < LIBRE_MIN_GB:
        m.append(f"{libre:.1f} GB libres en el host (< {LIBRE_MIN_GB} GB)")
    vms = tramo.vms_encendidas()
    bloqueantes = [f"VMs encendidas: {vms}"] if vms else []
    return m, bloqueantes, est


def orquestar(a, fases, dist, sesion, escenario, rep, tasa, extra, actual):
    """Una corrida con el orquestador. Devuelve (rc, ruta de metadatos o None)."""
    cmd = [sys.executable, "-m", "k6.medicion.orquestador", "--distribucion", dist, "--escenario", escenario,
           "--repeticion", str(rep), "--tipo", a.tipo, "--sesion", sesion, "--datos", a.datos, "--sin-snapshot",
           "--rampa", str(fases["rampa"]), "--estable", str(fases["estable"]), "--descenso", str(fases["descenso"]),
           "--estabilizacion", str(fases["estabilizacion"]), *extra]
    if tasa:
        cmd += ["--tasa", str(tasa)]
    base = f"{PREFIJO[a.tipo]}{dist}_{escenario}{'-fallo' if '--fallo' in extra else ''}_r{rep:02d}"
    carpeta = os.path.join(RAIZ, a.datos, TIPO_DIR[a.tipo], sesion)
    os.makedirs(os.path.join(carpeta, "registros"), exist_ok=True)
    with open(os.path.join(carpeta, "registros", base + ".log"), "w") as log:
        actual["proc"] = subprocess.Popen(cmd, cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT)
        rc = actual["proc"].wait()
        actual["proc"] = None
    ruta = os.path.join(carpeta, "metadatos", base + ".json")
    return rc, (ruta if os.path.exists(ruta) else None)


def validez(rc, ruta, simulacro):
    """(estado, motivos). estado: valida, no_valida (falla del procedimiento: se repite una vez) o abortada_memoria.
    La latencia, las fallidas, las descartadas y la memoria bajo 1024 MB son resultados: no invalidan."""
    if rc == CODIGO_ABORTO_MEMORIA:
        return "abortada_memoria", ["MemAvailable < 512 MB"]
    if ruta is None:
        return "no_valida", [f"sin metadatos (orquestador rc={rc}: precondición o reloj)"]
    m = json.load(open(ruta))
    if m.get("estado") == "abortada_memoria":
        return "abortada_memoria", ["MemAvailable < 512 MB"]
    motivos = [x for x in m.get("motivos_no_valida", []) if not x.startswith("tipo ")]
    if simulacro:  # con la sesión gráfica abierta el estado del host nunca cumple; solo cuenta el procedimiento
        motivos = [x for x in motivos if x in ("abortada_memoria", "fase estable incompleta")]
    if "error" in m.get("rapl", {}) or m.get("rapl", {}).get("delta_uj", 0) <= 0:
        motivos.append("lectura de RAPL fallida")
    return ("no_valida" if motivos else "valida"), motivos


def respaldar_k6(a, sesion):
    """Copia los JSON crudos de k6 del tramo fuera del repositorio, con su SHA-256."""
    origen = os.path.join(RAIZ, a.datos, "k6-crudo", TIPO_DIR[a.tipo], sesion)
    destino = os.path.join(a.respaldo, "k6-crudo", TIPO_DIR[a.tipo], sesion)
    os.makedirs(destino, exist_ok=True)
    out = {}
    for f in sorted(glob.glob(os.path.join(origen, "*.json.gz"))):
        shutil.copy2(f, destino)
        out[os.path.basename(f)] = sha256(os.path.join(destino, os.path.basename(f)))
    return {"destino": destino, "archivos": out}


def respaldar_prometheus(a, bloque, prometheus, datos_prom):
    """Snapshot de la TSDB al final del bloque, empaquetado en tar fuera del repositorio, con su SHA-256."""
    r = json.load(urllib.request.urlopen(urllib.request.Request(prometheus + "/api/v1/admin/tsdb/snapshot", method="POST"), timeout=120))
    nombre = r["data"]["name"]
    os.makedirs(os.path.join(a.respaldo, "prometheus"), exist_ok=True)
    destino = os.path.join(a.respaldo, "prometheus", f"j{a.jornada}_b{bloque:02d}_{nombre}.tar")
    with tarfile.open(destino, "w") as tar:
        tar.add(os.path.join(datos_prom, "snapshots", nombre), arcname=nombre)
    return {"snapshot": nombre, "archivo": destino, "bytes": os.path.getsize(destino), "sha256": sha256(destino)}


def apartar(a, sesion):
    """Una sesión interrumpida se renombra (no se borra) para rehacer el tramo desde el inicio."""
    for raiz in (os.path.join(RAIZ, a.datos, TIPO_DIR[a.tipo]), os.path.join(RAIZ, a.datos, "k6-crudo", TIPO_DIR[a.tipo])):
        src = os.path.join(raiz, sesion)
        if os.path.exists(src):
            os.rename(src, f"{src}_interrumpido_{time.strftime('%Y%m%dT%H%M%S')}")


def estado_reanudacion(diario_lineas, todos):
    """Desde el diario: tramos terminados (fin de tramo registrado) y sus jornadas."""
    hechos = {}
    for l in diario_lineas:
        if l.get("paso") == "tramo_fin":
            hechos[l["sesion"]] = l
    return {s: hechos[s] for _, _, s, _ in todos if s in hechos}


def plan_de_reanudacion(todos, hechos, jornada):
    """Qué tramos correr y cuáles apartar. Un bloque nunca mezcla tramos de dos jornadas: si un tramo del bloque terminó
    en otra jornada, se rehace el bloque completo."""
    correr, apartar_ = [], []
    por_bloque = {}
    for t in todos:
        por_bloque.setdefault(t[0], []).append(t)
    for n, ts in por_bloque.items():
        terminados = [t for t in ts if t[2] in hechos]
        if len(terminados) == len(ts) or any(hechos[t[2]]["resultado"] == "construccion_fallida" for t in terminados):
            continue  # bloque terminado o ya enviado a la reserva
        if any(hechos[t[2]]["jornada"] != jornada for t in terminados):
            correr += ts
            apartar_ += [t[2] for t in ts]
        else:
            pendientes = [t for t in ts if t[2] not in hechos]
            correr += pendientes
            apartar_ += [t[2] for t in pendientes]
    return correr, apartar_


def ejecutar_tramo(a, fases, n, dist, sesion, corridas, diario, actual):
    """Devuelve 'completo', 'abortado_memoria' o 'construccion_fallida'."""
    diario.contexto = {"bloque": n, "distribucion": dist, "sesion": sesion}
    carpeta = os.path.join(RAIZ, a.datos, TIPO_DIR[a.tipo], sesion)
    os.makedirs(carpeta, exist_ok=True)
    f_tramo = os.path.join(carpeta, "tramo.json")
    registro = os.path.join(RAIZ, a.datos, TIPO_DIR[a.tipo], f"despliegue_{dist}.jsonl")
    logs = os.path.join(carpeta, "registros")
    ciclo = tramo.ciclo_de(n, a.reserva)
    tramo.guardar(f_tramo, "contexto", {"bloque": n, "distribucion": dist, "sesion": sesion, "jornada": a.jornada, "tipo": a.tipo,
                                       "simulacro": a.simulacro, "ciclo_despliegue": ciclo, "fases": fases,
                                       "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True).stdout.strip()})
    diario.paso("tramo_inicio", "ok", ciclo=ciclo)

    t0 = time.time()
    r = etiqueta.cambiar(dist, a.prometheus)
    diario.paso("etiqueta", r["resultado"], t0, t_api=r["t_api"], t_up=r["t_up"])
    tramo.guardar(f_tramo, "etiqueta", r)
    if r["resultado"] != "ok":
        raise SystemExit("la etiqueta de Prometheus no se confirmó; se detiene la jornada")

    t0 = time.time()
    r = tramo.preparar_memoria()
    tramo.guardar(f_tramo, "memoria", r)
    diario.paso("memoria", "ok" if r["ok"] else "error", t0, swapfree_antes=r.get("antes", {}).get("SwapFree_kB"),
                memavailable_despues=r.get("despues", {}).get("MemAvailable_kB"))

    t0 = time.time()
    r = tramo.referencia(fases["ref_espera"], fases["ref_medicion"])
    tramo.guardar(f_tramo, "referencia", r)
    diario.paso("referencia", "ok" if r["ok"] else "no_valida", t0, potencia_W=r.get("potencia_media_W"), motivo=r.get("motivo"))

    construcciones = []
    for intento in (1, 2):
        if intento == 2:
            t0 = time.time()
            rd = tramo.destruir(dist, ciclo, registro, logs)
            construcciones.append({"limpieza_antes_del_reintento": rd})
            diario.paso("destruccion_reintento", "ok" if rd["ok"] else "error", t0)
        t0 = time.time()
        rc_ = tramo.construir(dist, ciclo, registro, logs)
        diario.paso("construccion", "ok" if rc_["ok"] else "error", t0, intento=intento, energia_J=rc_["rapl"]["energia_J"])
        rv = tramo.verificar(dist, a.prometheus) if rc_["ok"] else {"ok": False, "motivo": "construcción fallida"}
        construcciones.append({"intento": intento, "construccion": rc_, "verificacion": rv})
        tramo.guardar(f_tramo, "construccion", construcciones)
        diario.paso("verificacion", "ok" if rv["ok"] else "error", None, fallidas=rv.get("fallidas"))
        if rv["ok"]:
            break
    else:
        t0 = time.time()
        rd = tramo.destruir(dist, ciclo, registro, logs)
        tramo.guardar(f_tramo, "destruccion", rd)
        diario.paso("destruccion", "ok" if rd["ok"] else "error", t0)
        return "construccion_fallida"

    t0 = time.time()
    tramo.guardar(f_tramo, "rtt", tramo.rtt(dist))
    tramo.guardar(f_tramo, "plano_control", tramo.plano_control(dist))
    diario.paso("rtt_plano_control", "ok", t0)

    resultado = "completo"
    corridas_tramo, repetir = [], []
    lista = [(c["escenario"], c["repeticion"], c["tasa_rps"]) for c in corridas]
    for ronda in ("plan", "repeticion"):
        for esc, rep, tasa in (lista if ronda == "plan" else repetir):
            n_rep = rep if ronda == "plan" else REPETICION_OFFSET + rep
            diario.actualizar(corrida=f"{esc} r{n_rep:02d}")
            t0 = time.time()
            rc, ruta = orquestar(a, fases, dist, sesion, esc, n_rep, tasa, [], actual)
            est, motivos = validez(rc, ruta, a.simulacro)
            potencia = json.load(open(ruta))["rapl"].get("potencia_media_W") if ruta else None
            corridas_tramo.append({"escenario": esc, "repeticion": n_rep, "ronda": ronda, "rc": rc, "estado": est, "motivos": motivos,
                                   "metadatos": ruta and os.path.relpath(ruta, RAIZ)})
            tramo.guardar(f_tramo, "corridas", corridas_tramo)
            diario.paso("corrida", est, t0, escenario=esc, repeticion=n_rep, rc=rc, potencia_W=potencia, motivos=motivos)
            if est == "abortada_memoria":
                resultado = "abortado_memoria"
                break
            if est == "no_valida" and ronda == "plan":
                repetir.append((esc, rep, tasa))
        if resultado != "completo":
            break

    if resultado == "completo":
        t0 = time.time()
        idles = [(m["t_inicio"], m["t_fin"]) for m in (json.load(open(os.path.join(RAIZ, c["metadatos"])))
                 for c in corridas_tramo if c["escenario"] == "idle" and c["estado"] == "valida")]
        tramo.guardar(f_tramo, "almacenamiento", tramo.almacenamiento(dist, a.prometheus, idles))
        diario.paso("almacenamiento", "ok", t0)

        t0 = time.time()
        diario.actualizar(corrida="media-fallo r01")
        actual["fallo"] = dist
        rc, ruta = orquestar(a, fases, dist, sesion, "media", 1, 450,
                             ["--fallo", "--fallo-en", str(fases["fallo_en"]), "--fallo-retener", str(fases["fallo_retener"])], actual)
        actual["fallo"] = None
        est, motivos = validez(rc, ruta, a.simulacro)
        tramo.guardar(f_tramo, "corrida_fallo", {"rc": rc, "estado": est, "motivos": motivos, "metadatos": ruta and os.path.relpath(ruta, RAIZ)})
        diario.paso("corrida_fallo", est, t0, rc=rc, motivos=motivos)
        if est == "abortada_memoria":
            resultado = "abortado_memoria"

    t0 = time.time()
    rd = tramo.destruir(dist, ciclo, registro, logs)
    tramo.guardar(f_tramo, "destruccion", rd)
    diario.paso("destruccion", "ok" if rd["ok"] else "error", t0)
    t0 = time.time()
    rk = respaldar_k6(a, sesion)
    tramo.guardar(f_tramo, "respaldo_k6", rk)
    diario.paso("respaldo_k6", "ok", t0, archivos=len(rk["archivos"]), destino=rk["destino"])
    return resultado


def main():
    if "--autotest" in sys.argv:
        return autotest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--jornada", required=True, type=int)
    ap.add_argument("--bloques", required=True, help="i-j o un solo número; 0 = bloque 0 de ensayo")
    ap.add_argument("--reanudar", action="store_true")
    ap.add_argument("--simulacro", action="store_true", help="ventanas cortas, sin exigir el modo medición; escribe en data/campana_simulacro")
    ap.add_argument("--tipo", default="definitiva", choices=["definitiva", "piloto"])
    ap.add_argument("--reserva", action="store_true", help="bloques del día de reserva: sesiones bNNr_<dist>")
    ap.add_argument("--prometheus", default="http://127.0.0.1:9090")
    ap.add_argument("--datos-prometheus", default="/var/lib/prometheus/data")
    ap.add_argument("--respaldo", default=os.path.expanduser("~/tesis_respaldo"))
    a = ap.parse_args()
    a.datos = "data/campana_simulacro" if a.simulacro else "data"
    if a.simulacro:
        a.respaldo = os.path.join(RAIZ, a.datos, "respaldo")
    fases = FASES[a.simulacro]
    plan = json.load(open(a.plan))
    bloques = leer_bloques(a.bloques)
    if 0 in bloques and a.tipo != "piloto" and not a.simulacro:
        ap.error("el bloque 0 se corre con --tipo piloto")
    todos = tramos_de(plan, bloques, a.reserva)
    diario = Diario(os.path.join(RAIZ, a.datos, TIPO_DIR[a.tipo], "diario"), a.jornada)

    motivos, bloqueantes, est = precondiciones(a, plan)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True).stdout.strip()
    if bloqueantes or (motivos and not a.simulacro):
        diario.paso("precondiciones", "no_cumplidas", motivos=motivos + bloqueantes, commit=commit)
        print("No se inicia la jornada:\n- " + "\n- ".join(motivos + bloqueantes) +
              (f"\nPara destruir un clúster que quedó arriba (ciclo = 100 + bloque):\n  DESPLIEGUE_REGISTRO={a.datos}/{TIPO_DIR[a.tipo]}/despliegue_<dist>.jsonl "
                                         "k6/operacion/despliegue.sh <dist> destruir <ciclo>" if bloqueantes else ""))
        return 2

    apartar_ = []
    if a.reanudar:
        lineas = [json.loads(l) for f in sorted(glob.glob(os.path.join(diario_dir(a), "jornada_*.jsonl"))) for l in open(f)]
        hechos = estado_reanudacion(lineas, todos)
        todos, apartar_ = plan_de_reanudacion(todos, hechos, a.jornada)
        for s in apartar_:
            apartar(a, s)
    else:
        existentes = [s for _, _, s, _ in todos if os.path.exists(os.path.join(RAIZ, a.datos, TIPO_DIR[a.tipo], s))]
        if existentes:
            print(f"Ya existen las sesiones {existentes}: usar --reanudar o revisar el diario")
            return 2
    diario.paso("jornada_inicio", "ok", commit=commit, plan=os.path.relpath(os.path.abspath(a.plan), RAIZ), bloques=a.bloques,
                tipo=a.tipo, simulacro=a.simulacro, reanudar=a.reanudar, apartadas=apartar_, motivos_simulacro=motivos)

    fin_est = time.time() + 60 * sum(DURACION_TRAMO_MIN[d] for _, d, _, _ in todos) * (0.25 if a.simulacro else 1)
    print(f"Jornada {a.jornada}: {len(todos)} tramos")
    for n, d, s, c in todos:
        print(f"  bloque {n:2d}  {d:9}  {s}  {len(c)} corridas + fallo")
    print(f"Término estimado: {time.strftime('%Y-%m-%d %H:%M', time.localtime(fin_est))} (cálculo con los tiempos típicos)")
    diario.actualizar(termino_estimado=time.strftime("%Y-%m-%d %H:%M", time.localtime(fin_est)), tramos=[s for _, _, s, _ in todos])

    actual = {"proc": None, "fallo": None}

    def senal(num, _):
        raise Interrumpido(signal.Signals(num).name)

    signal.signal(signal.SIGTERM, senal)
    signal.signal(signal.SIGINT, senal)
    pendientes_reserva, codigo = [], 0
    try:
        for i, (n, d, s, c) in enumerate(todos):
            if n in pendientes_reserva:
                diario.contexto = {"bloque": n, "distribucion": d, "sesion": s}
                diario.paso("tramo_omitido", "bloque_para_reserva")
                continue
            res = ejecutar_tramo(a, fases, n, d, s, c, diario, actual)
            diario.paso("tramo_fin", res)
            if res == "construccion_fallida":
                pendientes_reserva.append(n)
            ultimo_del_bloque = i + 1 == len(todos) or todos[i + 1][0] != n
            if ultimo_del_bloque:
                t0 = time.time()
                rp = respaldar_prometheus(a, n, a.prometheus, a.datos_prometheus)
                diario.paso("respaldo_prometheus", "ok", t0, **rp)
        diario.contexto = {}
        diario.paso("jornada_fin", "ok", bloques_para_reserva=pendientes_reserva)
    except Interrumpido as e:
        for sig in (signal.SIGINT, signal.SIGTERM):  # una segunda señal no corta la limpieza
            signal.signal(sig, signal.SIG_IGN)
        p = actual.get("proc")
        if p and p.poll() is None:
            p.terminate()  # el orquestador termina k6 y restaura el fallo en su finally
            try:
                p.wait(timeout=300)
            except subprocess.TimeoutExpired:
                p.kill()
        restaurado = None
        if actual.get("fallo"):
            acc = fallo.acceso(RAIZ, actual["fallo"])
            restaurado = {ip: fallo.restaurar(actual["fallo"], acc, ip) for ip in IPS_NODOS}
        diario.paso("interrumpido", str(e), restauracion_fallo=restaurado,
                    nota=f"clúster y datos sin tocar; antes de --reanudar, destruir el clúster si quedó arriba (DESPLIEGUE_REGISTRO={a.datos}/{TIPO_DIR[a.tipo]}/despliegue_<dist>.jsonl)")
        codigo = 130
    diario.actualizar(paso="terminado" if codigo == 0 else "interrumpido")
    return codigo


def autotest():
    plan = json.load(open(os.path.join(RAIZ, "data", "campana", "plan_campana_v1.json")))
    t = tramos_de(plan, [0, 1, 2], False)
    assert [x[2] for x in t[:4]] == ["b00_k3s", "b00_microk8s", "b01_k3s", "b01_microk8s"] and t[0][3] == t[2][3]
    assert tramos_de(plan, [3], True)[0][2].startswith("b03r_") and leer_bloques("4-6") == [4, 5, 6] and leer_bloques("0") == [0]
    fin = lambda s, j, r="completo": {"sesion": s, "jornada": j, "resultado": r}
    # misma jornada: retoma en el tramo interrumpido
    c, ap_ = plan_de_reanudacion(t[2:], {"b01_k3s": fin("b01_k3s", 1)}, 1)
    assert [x[2] for x in c][:1] == ["b01_microk8s"] and "b01_k3s" not in ap_
    # bloque a medias de otra jornada: se rehace completo
    c, ap_ = plan_de_reanudacion(t[2:4], {"b01_k3s": fin("b01_k3s", 1)}, 2)
    assert [x[2] for x in c] == ["b01_k3s", "b01_microk8s"] == ap_
    # bloque enviado a la reserva: no se corre
    assert plan_de_reanudacion(t[2:4], {"b01_k3s": fin("b01_k3s", 1, "construccion_fallida")}, 1) == ([], [])
    assert validez(CODIGO_ABORTO_MEMORIA, None, False)[0] == "abortada_memoria" and validez(1, None, False)[0] == "no_valida"
    print("autotest ok")


def diario_dir(a):
    return os.path.join(RAIZ, a.datos, TIPO_DIR[a.tipo], "diario")


if __name__ == "__main__":
    sys.exit(main())
