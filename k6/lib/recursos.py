"""RTT con ping, memoria y swap del host, RSS de QEMU, cgroups del plano de control y red virtual (informe 3).

Todo se lee fuera de la fase estable y de la ventana de RAPL; un error queda en el JSON y no detiene la corrida.
"""
import glob, re, subprocess, sys, time
import threading
import xml.etree.ElementTree as ET

from k6.lib import fallo

VIRSH = ["virsh", "-c", "qemu:///system"]
UNIDADES_CP = {
    "k3s": ["k3s.service"],
    "microk8s": ["snap.microk8s.daemon-kubelite.service", "snap.microk8s.daemon-k8s-dqlite.service",
                 "snap.microk8s.daemon-containerd.service"],
}
SCRIPT_CGROUP = ('for u in {unidades}; do d=/sys/fs/cgroup/system.slice/$u; '
                 'echo "$u $(awk \'/^usage_usec/{{print $2}}\' $d/cpu.stat 2>/dev/null) $(cat $d/memory.current 2>/dev/null)"; done')


def parsear_ping(txt):
    """Resumen de `ping -q`: enviados, recibidos, pérdida (%) y min/media/máx/mdev en ms (None si todo se perdió)."""
    m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received.*?([\d.]+)% packet loss", txt, re.S)
    if not m:
        return {"error": txt.strip()[-200:] or "sin salida"}
    r = {"enviados": int(m[1]), "recibidos": int(m[2]), "perdida_pct": float(m[3])}
    t = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", txt)
    r.update(dict(zip(("min_ms", "media_ms", "max_ms", "mdev_ms"), map(float, t.groups()))) if t else {})
    return r


def _ping_cmd(destino, n, intervalo):
    return ["ping", "-c", str(n), "-i", str(intervalo), "-q", destino]


def ping_local(destino, n=20, intervalo=0.2):
    try:
        r = subprocess.run(_ping_cmd(destino, n, intervalo), capture_output=True, text=True, timeout=n * intervalo + 30)
    except subprocess.TimeoutExpired:
        return {"error": "ping excedió el tiempo"}
    return parsear_ping(r.stdout + r.stderr)


def ping_remoto(acc, origen, destino, n=20, intervalo=0.2):
    rc, out = fallo.ssh(acc, origen, " ".join(_ping_cmd(destino, n, intervalo)), int(n * intervalo + 30))
    return parsear_ping(out) if out else {"error": f"ssh rc={rc}"}


def medir_rtt(acc, ips_nodos, vip_cp, vip_svc, n=20, intervalo=0.2):
    """Desde el host a las dos VIP y a cada nodo, y entre nodos por SSH; todo en serie para no cargar la red virtual."""
    r = {"muestras": n, "intervalo_s": intervalo, "t_inicio": round(time.time(), 3), "host": {}, "entre_nodos": {}}
    for nombre, ip in [("vip_servicio", vip_svc), ("vip_plano_control", vip_cp)] + [(f"nodo_{ip}", ip) for ip in ips_nodos]:
        r["host"][nombre] = ping_local(ip, n, intervalo)
    for o in ips_nodos:
        for d in ips_nodos:
            if o != d:
                r["entre_nodos"][f"{o}->{d}"] = ping_remoto(acc, o, d, n, intervalo)
    r["t_fin"] = round(time.time(), 3)
    return r


def _meminfo():
    return {k: int(v) for k, v in re.findall(r"^(\w+):\s+(\d+) kB", open("/proc/meminfo").read(), re.M)}


def _vmstat():
    return {k: int(v) for k, v in re.findall(r"^(pswpin|pswpout) (\d+)$", open("/proc/vmstat").read(), re.M)}


def rss_qemu():
    """VmRSS (y su desglose) en kB de cada proceso qemu, con el nombre del dominio de libvirt."""
    out = []
    for ruta in glob.glob("/proc/[0-9]*/comm"):
        try:
            if open(ruta).read().strip() != "qemu-system-x86":
                continue
            pid = ruta.split("/")[2]
            cmd = open(f"/proc/{pid}/cmdline").read().split("\0")
            nombre = next((re.match(r"guest=([^,]+)", cmd[i + 1])[1] for i, x in enumerate(cmd[:-1]) if x == "-name"), None)
            st = dict(re.findall(r"^(VmRSS|RssAnon|RssFile|RssShmem):\s+(\d+) kB", open(f"/proc/{pid}/status").read(), re.M))
            out.append({"dominio": nombre, "pid": int(pid), **{k: int(v) for k, v in st.items()}})
        except (OSError, TypeError):
            continue
    return sorted(out, key=lambda x: x["dominio"] or "")


def foto_host():
    """Memoria, swap (nivel y contadores acumulados) y RSS de QEMU del host, sin tocar la red ni las VM."""
    try:
        m = _meminfo()
        return {"t": round(time.time(), 3), "memavailable_kb": m["MemAvailable"], "memtotal_kb": m["MemTotal"],
                "swaptotal_kb": m["SwapTotal"], "swapfree_kb": m["SwapFree"], **_vmstat(), "qemu": rss_qemu()}
    except (OSError, KeyError) as e:
        return {"error": str(e)}


def resumen_host(ini, fin, memavailable_min_mb=None):
    """Actividad de swap entre dos fotos (páginas; el tamaño de página no se lee aquí) y mínimo de MemAvailable."""
    if "error" in ini or "error" in fin:
        return {"error": "foto incompleta"}
    return {"pswpin_paginas": fin["pswpin"] - ini["pswpin"], "pswpout_paginas": fin["pswpout"] - ini["pswpout"],
            "swap_usado_kb_inicio": ini["swaptotal_kb"] - ini["swapfree_kb"],
            "swap_usado_kb_fin": fin["swaptotal_kb"] - fin["swapfree_kb"],
            "memavailable_min_mb_prometheus": memavailable_min_mb}


def parsear_cgroup(txt):
    """'unidad usage_usec memory_current' por línea; None si el cgroup no existe."""
    d = {}
    for linea in txt.splitlines():
        p = linea.split()
        d[p[0]] = {"usage_usec": int(p[1]), "memory_current": int(p[2])} if len(p) == 3 and p[1].isdigit() and p[2].isdigit() else None
    return d


def leer_cgroup_cp(dist, acc, ips):
    """Una lectura de cpu.stat y memory.current de las unidades del plano de control en cada nodo, en paralelo."""
    res, t0 = {}, time.time()
    cmd = SCRIPT_CGROUP.format(unidades=" ".join(UNIDADES_CP[dist]))

    def uno(ip):
        rc, out = fallo.ssh(acc, ip, cmd, 20)
        res[ip] = parsear_cgroup(out) if rc == 0 else {"error": f"ssh rc={rc}"}

    hilos = [threading.Thread(target=uno, args=(ip,)) for ip in ips]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return {"t_inicio": round(t0, 3), "t_fin": round(time.time(), 3), "nodos": res}


def red_virtual():
    """Tipo y modelo de la NIC de cada dominio activo y modo de la red de libvirt (NAT o bridge) que usa."""
    def virsh(*a):
        return subprocess.run([*VIRSH, *a], capture_output=True, text=True, timeout=20).stdout
    try:
        dominios, redes = {}, {}
        for dom in virsh("list", "--name").split():
            filas = [l.split() for l in virsh("domiflist", dom).splitlines()[2:] if l.split()]
            dominios[dom] = [{"interfaz": f[0], "tipo": f[1], "red": f[2], "modelo": f[3], "mac": f[4]} for f in filas if len(f) >= 5]
            for f in dominios[dom]:
                if f["red"] not in redes:
                    x = ET.fromstring(virsh("net-dumpxml", f["red"]))
                    fw, br, ip = x.find("forward"), x.find("bridge"), x.find("ip")
                    redes[f["red"]] = {"forward": fw.get("mode") if fw is not None else None,
                                       "bridge": br.get("name") if br is not None else None,
                                       "ip": ip.get("address") if ip is not None else None,
                                       "mascara": ip.get("netmask") if ip is not None else None}
        return {"dominios": dominios, "redes": redes}
    except (OSError, subprocess.SubprocessError, ET.ParseError, IndexError) as e:
        return {"error": str(e)}


def autotest():
    t = parsear_ping("--- x ping statistics ---\n20 packets transmitted, 19 received, 5% packet loss, time 3800ms\n"
                     "rtt min/avg/max/mdev = 0.210/0.350/1.200/0.100 ms\n")
    assert t == {"enviados": 20, "recibidos": 19, "perdida_pct": 5.0, "min_ms": 0.21, "media_ms": 0.35, "max_ms": 1.2, "mdev_ms": 0.1}, t
    assert parsear_ping("20 packets transmitted, 0 received, 100% packet loss, time 1ms")["perdida_pct"] == 100.0
    assert "error" in parsear_ping("ping: connect: Network is unreachable")
    assert parsear_cgroup("k3s.service 5000 7000\nx.service  \n") == {"k3s.service": {"usage_usec": 5000, "memory_current": 7000}, "x.service": None}
    r = resumen_host({"pswpin": 1, "pswpout": 5, "swaptotal_kb": 10, "swapfree_kb": 10},
                     {"pswpin": 4, "pswpout": 5, "swaptotal_kb": 10, "swapfree_kb": 7})
    assert r["pswpin_paginas"] == 3 and r["swap_usado_kb_fin"] == 3
    f = foto_host()
    assert "error" not in f and f["memavailable_kb"] > 0, f
    p = ping_local("127.0.0.1", 3, 0.2)
    assert p["recibidos"] == 3 and p["perdida_pct"] == 0, p
    print("autotest ok; qemu visibles:", [x["dominio"] for x in f["qemu"]], "; red_virtual:", sorted(red_virtual()))


if __name__ == "__main__":
    autotest() if "--autotest" in sys.argv else print(__doc__)
