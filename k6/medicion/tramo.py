"""Mediciones de un tramo de la campaña (E4, Etapa 4). Las llama el ejecutor (k6/medicion/campana.py).

Cada función devuelve un dict que el ejecutor guarda en <datos>/campana/bNN_<dist>/tramo.json con `guardar()`.
Ninguna corre dentro de la fase estable de una corrida: el ejecutor las llama entre corridas.
"""
import json, os, re, subprocess, time

from k6.lib import fallo, instrumentacion, recursos
from k6.lib.comun import IPS_NODOS, IP_VIP_CP, IP_VIP_SVC, RAIZ, RAPL, delta_rapl, leer_rapl, prom

VIRSH = ["virsh", "-c", "qemu:///system"]
POOL = "default"
# Directorios de la distribución en cada nodo; los de containerd son subdirectorios y se informan aparte
DIRECTORIOS = {
    "k3s": {"distribucion": ["/var/lib/rancher", "/etc/rancher"],
            "containerd": ["/var/lib/rancher/k3s/agent/containerd"]},
    "microk8s": {"distribucion": ["/var/snap/microk8s", "/var/lib/snapd/snaps/microk8s*"],
                 "containerd": ["/var/snap/microk8s/common/var/lib/containerd"]},
}
CTR = {"k3s": "sudo k3s ctr -n k8s.io", "microk8s": "sudo microk8s ctr -n k8s.io"}
CONTENIDO = {"k3s": "/var/lib/rancher/k3s/agent/containerd/io.containerd.content.v1.content",
             "microk8s": "/var/snap/microk8s/common/var/lib/containerd/io.containerd.content.v1.content"}


def ciclo_de(bloque, reserva=False):
    """Campo numérico `ciclo` del registro de despliegue: 100 + bloque (bloque 0 = 100); en la reserva, 200 + bloque."""
    return (200 if reserva else 100) + bloque


def guardar(ruta, clave, valor):
    """Agrega o reemplaza una clave en tramo.json de forma atómica."""
    d = json.load(open(ruta)) if os.path.exists(ruta) else {}
    d[clave] = valor
    tmp = ruta + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh, indent=1, default=str)
    os.replace(tmp, ruta)
    return d


def vms_encendidas():
    r = subprocess.run([*VIRSH, "list", "--name", "--state-running"], capture_output=True, text=True, timeout=30)
    return [x for x in r.stdout.split() if x]


def preparar_memoria():
    """E4.1: swapoff/swapon y vaciado de la caché con el ayudante de root (E2)."""
    t0 = time.time()
    r = subprocess.run(["sudo", "-n", "/usr/local/sbin/tesis-preparar-memoria"], capture_output=True, text=True, timeout=600)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {"resultado": "error", "salida": r.stdout[-300:], "error": r.stderr[-300:]}
    return {"ok": r.returncode == 0, "rc": r.returncode, "duracion_s": round(time.time() - t0, 3), **d}


def _rapl_ventana(segs):
    mu = recursos.Muestreador(2.0)
    mu.start()
    h0 = instrumentacion.foto_host()
    e0, ta0, tb0 = leer_rapl()
    time.sleep(max(0, tb0 + segs - time.time()))
    e1, ta1, tb1 = leer_rapl()
    h1 = instrumentacion.foto_host()
    mu.detener()
    t0, t1 = (ta0 + tb0) / 2, (ta1 + tb1) / 2
    maximo = int(open(RAPL + "max_energy_range_uj").read())
    d = delta_rapl(e0, e1, maximo)
    return {"t_inicio": round(t0, 3), "t_fin": round(t1, 3), "energy_uj_inicio": e0, "energy_uj_fin": e1, "delta_uj": d,
            "desbordamiento": e1 < e0, "potencia_media_W": round(d / 1e6 / (t1 - t0), 3),
            "instrumentacion": instrumentacion.delta(h0, h1),
            "muestreo": {"muestras": mu.muestras, "resumen": recursos.resumen_muestreo(mu.muestras, t0, t1, 1024)}}


def referencia(espera_s=120, medicion_s=180):
    """E4.2: ventana de referencia del host sin VMs ni k6. Exige que no haya ninguna VM encendida."""
    vms = vms_encendidas()
    if vms:
        return {"ok": False, "motivo": f"hay VMs encendidas: {vms}"}
    if subprocess.run(["pgrep", "-x", "k6"], capture_output=True).returncode == 0:
        return {"ok": False, "motivo": "hay un k6 en ejecución"}
    t_espera = time.time()
    time.sleep(espera_s)
    v = _rapl_ventana(medicion_s)
    vms = vms_encendidas()
    return {"ok": not vms, "motivo": f"se encendieron VMs durante la ventana: {vms}" if vms else None,
            "espera_s": espera_s, "medicion_s": medicion_s, "t_espera": round(t_espera, 3), **v}


def bytes_red():
    """Bytes recibidos y enviados por la Wi-Fi del host y los puentes de libvirt (/proc/net/dev)."""
    r = {}
    for linea in open("/proc/net/dev").read().splitlines()[2:]:
        nombre, datos = linea.split(":", 1)
        nombre, c = nombre.strip(), datos.split()
        if nombre.startswith(("wl", "virbr")):
            r[nombre] = {"rx": int(c[0]), "tx": int(c[8])}
    return {"t": round(time.time(), 3), "interfaces": r}


def _delta_red(a, b):
    """Un puente que no existía al inicio cuenta desde 0 (lo crea Terraform durante la construcción)."""
    return {n: {k: v[k] - a["interfaces"].get(n, {}).get(k, 0) for k in ("rx", "tx")} for n, v in b["interfaces"].items()}


def despliegue(dist, accion, ciclo, registro, log_dir):
    """despliegue.sh con el registro de la campaña; devuelve rc y la línea que escribió (fases y duraciones)."""
    env = dict(os.environ, DESPLIEGUE_REGISTRO=registro, DESPLIEGUE_LOG=log_dir)
    os.makedirs(log_dir, exist_ok=True)
    cmd = [os.path.join(RAIZ, "k6", "operacion", "despliegue.sh"), dist, accion, str(ciclo)]
    if os.geteuid() == 0 and os.environ.get("SUDO_USER"):  # diagnóstico con sudo: Terraform y Ansible siguen como el operador
        cmd = ["sudo", "-u", os.environ["SUDO_USER"], "-H",
               "--preserve-env=DESPLIEGUE_REGISTRO,DESPLIEGUE_LOG,TF_VAR_emulatorpin", *cmd]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    try:
        reg = json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        reg = {"error": "sin registro", "stdout": r.stdout[-500:], "stderr": r.stderr[-500:]}
    reg["log"] = os.path.join(log_dir, f"despliegue_{dist}_{accion}_c{ciclo}.log")
    return r.returncode, reg


def construir(dist, ciclo, registro, log_dir):
    """E4.3: construcción con RAPL (J, con un desbordamiento posible) y bytes de red al inicio y al término."""
    r0, red0 = leer_rapl(), bytes_red()
    rc, reg = despliegue(dist, "construir", ciclo, registro, log_dir)
    r1, red1 = leer_rapl(), bytes_red()
    maximo = int(open(RAPL + "max_energy_range_uj").read())
    d = delta_rapl(r0[0], r1[0], maximo)
    t0, t1 = (r0[1] + r0[2]) / 2, (r1[1] + r1[2]) / 2
    return {"ok": rc == 0, "rc": rc, "ciclo": ciclo, "registro": reg,
            "rapl": {"energy_uj_inicio": r0[0], "energy_uj_fin": r1[0], "desbordamiento": r1[0] < r0[0], "energia_J": round(d / 1e6, 3),
                     "t_inicio": round(t0, 3), "t_fin": round(t1, 3), "potencia_media_W": round(d / 1e6 / (t1 - t0), 3)},
            "red": {"inicio": red0, "fin": red1, "delta": _delta_red(red0, red1)},
            "fases_s": {k: round(v["duracion_s"], 3) for k, v in reg.get("fases", {}).items()}}


def destruir(dist, ciclo, registro, log_dir):
    """E4.8."""
    rc, reg = despliegue(dist, "destruir", ciclo, registro, log_dir)
    return {"ok": rc == 0, "rc": rc, "ciclo": ciclo, "registro": reg}


def verificar(dist, prometheus, espera_s=60):
    """E4.4: comprobaciones de HA y de la aplicación de la validación integral, con reintentos cada 5 s hasta espera_s."""
    from k6.operacion import validacion  # importación diferida: validacion importa el orquestador
    acc = fallo.acceso(RAIZ, dist)
    a = type("A", (), {"distribucion": dist, "prometheus": prometheus})()
    t0, intentos = time.time(), 0
    while True:
        c = validacion.comprobar_ha(a, acc)
        intentos += 1
        malas = [k for k, v in c.items() if not v["ok"]]
        if not malas or time.time() - t0 > espera_s:
            return {"ok": not malas, "fallidas": malas, "intentos": intentos, "espera_s": round(time.time() - t0, 1), "comprobaciones": c}
        time.sleep(5)


def rtt(dist, muestras=20):
    """E4.5: misma medición que --rtt del orquestador, una vez por tramo y fuera de las ventanas."""
    return recursos.medir_rtt(fallo.acceso(RAIZ, dist), IPS_NODOS, IP_VIP_CP, IP_VIP_SVC, muestras)


def plano_control(dist):
    """E4.6: procesos de cada unidad del plano de control (cgroup completo, con subcgroups), con su nombre, por nodo."""
    acc = fallo.acceso(RAIZ, dist)
    cmd = ("for u in " + " ".join(recursos.UNIDADES_CP[dist]) + "; do d=/sys/fs/cgroup/system.slice/$u; "
           "if [ -d $d ]; then for p in $(find $d -name cgroup.procs -exec cat {} + 2>/dev/null); do "
           "echo \"$u $p $(cat /proc/$p/comm 2>/dev/null)\"; done; else echo \"$u -\"; fi; done")
    r = {}
    for ip in IPS_NODOS:
        rc, out = fallo.ssh(acc, ip, cmd, 60)
        nodo = {u: {"procesos": [], "por_nombre": {}} for u in recursos.UNIDADES_CP[dist]}
        for linea in out.splitlines():
            p = linea.split(None, 2)
            if len(p) == 2 and p[1] == "-":
                nodo[p[0]] = {"existe": False}
            elif len(p) >= 2:
                nombre = p[2] if len(p) > 2 else "?"
                nodo[p[0]]["procesos"].append([int(p[1]), nombre])
                nodo[p[0]]["por_nombre"][nombre] = nodo[p[0]]["por_nombre"].get(nombre, 0) + 1
        r[ip] = nodo if rc == 0 else {"error": f"ssh rc={rc}"}
    return {"t": round(time.time(), 3), "nodos": r}


def _escrito_disco(prometheus, t0, t1):
    """Bytes escritos a disco por nodo entre t0 y t1, con node_disk_written_bytes_total (suma de dispositivos)."""
    def valores(t):
        return {x["metric"]["instance"]: float(x["value"][1]) for x in prom(
            prometheus, 'sum by (instance) (node_disk_written_bytes_total{job="node_exporter_vms"})', t)}
    a, b = valores(t0), valores(t1)
    return {i: int(b[i] - a[i]) for i in b if i in a}


def _qcow2(dist):
    """Tamaño real de cada disco: `vol-info` Allocation de libvirt (sin root; es el espacio ocupado en el host, como
    `actual-size` de qemu-img) y qemu-img si la imagen es legible para el operador."""
    r = {}
    for dom in vms_encendidas():
        if not dom.startswith(dist):
            continue
        filas = subprocess.run([*VIRSH, "domblklist", dom, "--details"], capture_output=True, text=True).stdout.splitlines()[2:]
        for f in filas:
            c = f.split()
            if len(c) == 4 and c[1] == "disk":
                pool = ["--pool", POOL] if c[0] == "volume" else []  # Terraform crea los discos como volúmenes del pool
                info = subprocess.run([*VIRSH, "vol-info", *pool, c[3], "--bytes"], capture_output=True, text=True).stdout
                m = dict(re.findall(r"^(Capacity|Allocation):\s+(\d+)", info, re.M))
                ruta = subprocess.run([*VIRSH, "vol-path", *pool, c[3]], capture_output=True, text=True).stdout.strip() or c[3]
                qi = subprocess.run(["qemu-img", "info", "-U", "--output=json", ruta], capture_output=True, text=True)
                actual = json.loads(qi.stdout).get("actual-size") if qi.returncode == 0 else None
                r[f"{dom}:{c[2]}"] = {"ruta": ruta, "capacidad_bytes": int(m.get("Capacity", 0)) or None,
                                       "asignado_bytes_libvirt": int(m.get("Allocation", 0)) or None, "actual_size_qemu_img": actual}
    return r


def almacenamiento(dist, prometheus, idles):
    """E4.7: tamaño de los directorios de la distribución y de containerd por nodo (du, bytes en disco), df de /,
    imágenes de contenedores (número y bytes del almacén de contenido), qcow2 en el host y bytes escritos en las idle.
    idles: [(t_inicio, t_fin)] de las corridas idle del tramo."""
    acc = fallo.acceso(RAIZ, dist)
    dirs = DIRECTORIOS[dist]
    todos = dirs["distribucion"] + dirs["containerd"]
    cmd = ("for d in " + " ".join(todos) + "; do if sudo ls -d $d >/dev/null 2>&1; then for x in $d; do "
           "echo \"du $x $(sudo du -sB1 $x 2>/dev/null | cut -f1)\"; done; else echo \"du $d -\"; fi; done; "
           "echo \"df $(df -B1 --output=size,used,avail / | tail -1)\"; "
           f"echo \"imagenes $({CTR[dist]} images ls -q 2>/dev/null | wc -l)\"; "
           f"echo \"contenido $(sudo du -sB1 {CONTENIDO[dist]} 2>/dev/null | cut -f1)\"")
    nodos = {}
    for ip in IPS_NODOS:
        rc, out = fallo.ssh(acc, ip, cmd, 120)
        n = {"directorios": {}, "df_raiz": None, "imagenes": None, "contenido_bytes": None}
        for linea in out.splitlines():
            c = linea.split()
            if c[0] == "du":
                n["directorios"][c[1]] = int(c[2]) if len(c) > 2 and c[2].isdigit() else "no existe"
            elif c[0] == "df" and len(c) == 4:
                n["df_raiz"] = dict(zip(("tamano_bytes", "usado_bytes", "libre_bytes"), map(int, c[1:])))
            elif c[0] == "imagenes" and len(c) > 1:
                n["imagenes"] = int(c[1])
            elif c[0] == "contenido" and len(c) > 1 and c[1].isdigit():
                n["contenido_bytes"] = int(c[1])
        nodos[ip] = n if rc == 0 else {"error": f"ssh rc={rc}"}
    escrito = {}
    for i, (t0, t1) in enumerate(idles, 1):
        try:
            escrito[f"idle_{i}"] = {"t_inicio": t0, "t_fin": t1, "bytes_por_nodo": _escrito_disco(prometheus, t0, t1)}
        except (OSError, AssertionError, ValueError) as e:
            escrito[f"idle_{i}"] = {"error": str(e)}
    return {"t": round(time.time(), 3), "directorios_de_containerd_incluidos_en": "los de la distribución (se informan también aparte)",
            "nodos": nodos, "qcow2": _qcow2(dist), "escrito_disco_idle": escrito}


def autotest():
    assert ciclo_de(3) == 103 and ciclo_de(0) == 100 and ciclo_de(3, reserva=True) == 203
    a = {"interfaces": {"wlp3s0": {"rx": 10, "tx": 5}}}
    b = {"interfaces": {"wlp3s0": {"rx": 30, "tx": 6}, "virbr1": {"rx": 7, "tx": 9}}}
    assert _delta_red(a, b) == {"wlp3s0": {"rx": 20, "tx": 1}, "virbr1": {"rx": 7, "tx": 9}}
    import tempfile
    ruta = os.path.join(tempfile.mkdtemp(), "tramo.json")
    guardar(ruta, "a", 1)
    assert guardar(ruta, "b", {"x": 2}) == {"a": 1, "b": {"x": 2}}
    red = bytes_red()
    assert any(n.startswith("wl") for n in red["interfaces"]), red
    print("autotest ok")


if __name__ == "__main__":
    import sys
    autotest() if "--autotest" in sys.argv else print(__doc__)
