"""Constantes y funciones que comparten el orquestador, la calibración y el diagnóstico."""
import hashlib, json, os, subprocess, sys, time
import urllib.parse, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAPL = "/sys/class/powercap/intel-rapl:0/"
IP_VIP_CP, IP_VIP_SVC = "192.168.100.100", "192.168.100.150"
IPS_NODOS = ["192.168.100.11", "192.168.100.12", "192.168.100.13"]
OBJETIVOS_ESPERADOS = 7  # host, 3 VMs, scaphandre, kube-state-metrics y prometheus


def delta_rapl(a, b, maximo):
    """Delta del contador con un solo desbordamiento posible (la ventana dura minutos)."""
    return b - a if b >= a else b - a + maximo


def leer_rapl():
    t0 = time.time()
    try:
        v = int(open(RAPL + "energy_uj").read())
    except PermissionError:
        v = int(subprocess.run(["sudo", "-n", "/usr/bin/cat", RAPL + "energy_uj"],
                               capture_output=True, text=True, check=True).stdout)
    return v, t0, time.time()


def prom(url, consulta, t=None):
    q = {"query": consulta}
    if t:
        q["time"] = t
    d = json.load(urllib.request.urlopen(f"{url}/api/v1/query?" + urllib.parse.urlencode(q), timeout=15))
    assert d["status"] == "success", d
    return d["data"]["result"]


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


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def autotest():
    assert delta_rapl(10, 25, 100) == 15
    assert delta_rapl(95, 5, 100) == 10
    print("autotest ok")


if __name__ == "__main__":
    autotest()
