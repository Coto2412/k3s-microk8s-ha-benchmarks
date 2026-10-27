#!/usr/bin/env python3
"""Estado del host antes de una corrida (T-20.7): reloj convergido y política de servicios.

La política (servicios, perfil de energía, umbrales del reloj) la instala el rol Ansible host_mediciones.
"""
import glob, json, os, re, subprocess, sys, time

POLITICA = "/etc/tesis/medicion.json"
ESTADO_MODO = "/run/tesis-medicion.estado"
MEM_MIN_MB = 1024  # umbral mío, sin derivar de una prueba


def cargar_politica():
    try:
        return json.load(open(POLITICA))
    except (OSError, ValueError):
        return None


def segundos(texto):
    """'0.000220857 seconds slow of NTP time' -> -0.000220857."""
    m = re.match(r"([0-9.]+) seconds (fast|slow)", texto or "")
    return None if not m else float(m[1]) * (1 if m[2] == "fast" else -1)


def hex_ip(ip):
    """chronyc muestra el ID de referencia como IP en hexadecimal (y a veces el nombre del host, no la IP)."""
    return "%02X%02X%02X%02X" % tuple(int(x) for x in ip.split("."))


def motivos_reloj(reloj, pol):
    """Motivos por los que el reloj no está convergido (lista vacía = convergido)."""
    r, m = pol["reloj"], []
    for nombre, c, umbral in [("host", reloj["host"], r["umbral_host_ms"])] + \
            [(ip, c, r["umbral_vm_ms"]) for ip, c in reloj["vms"].items()]:
        off = segundos(c.get("System time"))
        if c.get("Leap status") != "Normal":
            m.append(f"{nombre}: Leap status {c.get('Leap status')}")
        if off is None or abs(off) * 1e3 > umbral:
            m.append(f"{nombre}: System time {c.get('System time')} (umbral {umbral} ms)")
        if nombre != "host" and not c.get("Reference ID", "").startswith(hex_ip(pol["ip_host"])):
            m.append(f"{nombre}: no sigue al host ({c.get('Reference ID')})")
    return m


def esperar_reloj(leer, pol, log=print):
    """Sondea cada 10 s hasta que el reloj converge o vence espera_max_s; devuelve (reloj, motivos, espera_s)."""
    t0 = time.time()
    while True:
        reloj = leer()
        m = motivos_reloj(reloj, pol)
        if not m or time.time() - t0 >= pol["reloj"]["espera_max_s"]:
            return reloj, m, round(time.time() - t0, 1)
        log(f"reloj sin converger ({m[0]}); reintento en 10 s")
        time.sleep(10)


def activo(unidad):
    return subprocess.run(["systemctl", "is-active", "--quiet", unidad]).returncode == 0


def unidades_fuera_de_la_lista(pol):
    """Mismo criterio que `tesis-modo-medicion`: sockets, paths y timers activos y servicios en ejecución no permitidos."""
    salida = ""
    for tipo, estado in (("socket,path,timer", "active"), ("service", "running")):
        salida += subprocess.run(["systemctl", "list-units", f"--type={tipo}", f"--state={estado}", "--no-legend", "--plain"],
                                 capture_output=True, text=True).stdout
    unidades = [l.split()[0] for l in salida.splitlines() if l.strip()]
    return sorted(u for u in unidades if not any(re.fullmatch(p, u) for p in pol["unidades_permitidas"]))


def procesos_top(n=10):
    """Procesos con más CPU en la segunda muestra de top (la primera promedia desde el arranque)."""
    txt = subprocess.run(["top", "-b", "-n", "2", "-d", "1", "-w", "160"], capture_output=True, text=True).stdout
    ultimo = txt.split("top - ")[-1].splitlines()
    i = next((k for k, l in enumerate(ultimo) if l.lstrip().startswith("PID")), None)
    return [] if i is None else [l.split(None, 11)[-1:] + l.split(None, 11)[8:9] for l in ultimo[i + 1:i + 1 + n]]


def _leer(ruta):
    try:
        return open(ruta).read().strip()
    except OSError:
        return None


def estado_host(pol):
    """Estado del host y motivos por los que la corrida no sería válida para la campaña."""
    m = []
    if pol is None:
        return {"politica": None}, ["política de mediciones no instalada: correr el playbook del host (rol host_mediciones)"]
    gui = activo("display-manager.service")
    if gui:
        m.append("sesión gráfica activa")
    modo = os.path.exists(ESTADO_MODO)
    if not modo:
        m.append("modo medición no activo (sudo tesis-modo-medicion entrar)")
    fuera = unidades_fuera_de_la_lista(pol)
    if fuera:
        m.append(f"{len(fuera)} unidades activas fuera de la lista permitida")
    falta = [u for u in pol["servicios_requeridos"] if not activo(u)]
    if falta:
        m.append(f"servicios requeridos inactivos: {falta}")
    perfil = subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True).stdout.strip() or None
    if perfil != pol["perfil_energia"]:
        m.append(f"perfil de energía {perfil}, la política pide {pol['perfil_energia']}")
    boost = _leer("/sys/devices/system/cpu/cpufreq/boost")
    if boost != str(pol["boost_cpu"]):
        m.append(f"boost de CPU en {boost}, la política pide {pol['boost_cpu']}")
    mem = next((int(l.split()[1]) // 1024 for l in open("/proc/meminfo") if l.startswith("MemAvailable")), None)
    if mem is not None and mem < MEM_MIN_MB:
        m.append(f"memoria disponible {mem} MB (< {MEM_MIN_MB} MB): riesgo de presión de memoria")
    ac = [_leer(f) for f in glob.glob("/sys/class/power_supply/AC*/online")]
    if ac != ["1"]:
        m.append("equipo sin corriente alterna")
    temp = None
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if _leer(h + "/name") == "k10temp":
            temp = _leer(h + "/temp1_input")
    brillo = [(_leer(d + "/brightness"), _leer(d + "/max_brightness")) for d in sorted(glob.glob("/sys/class/backlight/*"))]
    estado = {
        "brillo_pantalla": brillo, "sesion_grafica_activa": gui, "modo_medicion": modo,
        "unidades_fuera_de_la_lista": fuera, "procesos_top_cpu": procesos_top(), "perfil_energia": perfil, "boost_cpu": boost, "memoria_disponible_mb": mem,
        "presion_memoria_some_avg60": (re.search(r"some avg10=\S+ avg60=(\S+)", _leer("/proc/pressure/memory") or "") or [None, None])[1],
        "frecuencia_max_khz": _leer("/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq"),
        "epp_cpu0": _leer("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"),
        "perfil_plataforma": _leer("/sys/firmware/acpi/platform_profile"),
        "corriente_alterna": ac == ["1"], "gobernador_cpu": _leer("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
        "temperatura_cpu_C": None if temp is None else round(int(temp) / 1000, 1),
        "carga_1min": os.getloadavg()[0], "ufw_habilitado": "ENABLED=yes" in (_leer("/etc/ufw/ufw.conf") or ""),
        "politica": pol,
    }
    return estado, m


def autotest():
    pol = {"ip_host": "192.168.100.1", "reloj": {"umbral_host_ms": 100, "umbral_vm_ms": 5, "espera_max_s": 0}}
    ok = {"Leap status": "Normal", "System time": "0.000010000 seconds slow of NTP time", "Reference ID": "C0A86401 (coto-thinkpad)"}
    assert hex_ip("192.168.100.1") == "C0A86401"
    reloj = {"host": dict(ok, **{"System time": "0.0019 seconds fast of NTP time"}), "vms": {"192.168.100.11": ok}}
    assert segundos("0.5 seconds slow of NTP time") == -0.5
    assert motivos_reloj(reloj, pol) == []
    reloj["vms"]["192.168.100.11"] = dict(ok, **{"System time": "0.0100 seconds fast of NTP time", "Leap status": "Not synchronised"})
    assert len(motivos_reloj(reloj, pol)) == 2
    print("autotest ok")


if __name__ == "__main__":
    autotest() if "--autotest" in sys.argv else print(json.dumps(estado_host(cargar_politica()), indent=1, default=str))
