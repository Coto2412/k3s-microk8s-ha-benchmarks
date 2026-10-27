"""Fallo controlado de un nodo (T-19): inyección, observación desde el host y cálculo de tiempos.

Lo usa k6/medicion/orquestador.py con --fallo. El protocolo es el de la Etapa 2, sección 4.4.
"""
import datetime, gzip, json, os, re, ssl, subprocess, threading, time, urllib.error, urllib.request

UNIDAD = {"k3s": "k3s", "microk8s": "snap.microk8s.daemon-kubelite"}
KUBECTL = {"k3s": "sudo k3s kubectl", "microk8s": "sudo microk8s kubectl"}
PUERTO_API = {"k3s": 6443, "microk8s": 16443}
DIR_DIST = {"k3s": "k3sHA", "microk8s": "microk8sHA"}
SSH_OPC = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
           "-o", "ConnectTimeout=5", "-o", "BatchMode=yes"]
IP_VIP_CP, IP_VIP_SVC = "192.168.100.100", "192.168.100.150"
CTX = ssl._create_unverified_context()
# El reinicio automático de systemd (Restart=always, 5 s) recupera el proceso antes de que el nodo se marque NotReady.
DROP_IN = "/run/systemd/system/{u}.service.d/sin-reinicio.conf"


def acceso(raiz, dist):
    """Usuario y llave SSH del inventario que genera Terraform."""
    d = os.path.join(raiz, DIR_DIST[dist], "ansible")
    txt = open(os.path.join(d, "inventory.ini")).read()
    usuario = re.search(r"^ansible_user=(\S+)", txt, re.M).group(1)
    llave = re.search(r"^ansible_ssh_private_key_file=(\S+)", txt, re.M).group(1)
    return usuario, os.path.normpath(os.path.join(d, llave))


def ssh(acc, ip, cmd, timeout=60):
    try:
        r = subprocess.run(["ssh", "-i", acc[1], *SSH_OPC, f"{acc[0]}@{ip}", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return 255, ""


def preparar(dist, acc, ip):
    u = UNIDAD[dist]
    d = os.path.dirname(DROP_IN.format(u=u))
    cmd = (f"sudo mkdir -p {d} && printf '[Service]\\nRestart=no\\n' | sudo tee {DROP_IN.format(u=u)} >/dev/null "
           f"&& sudo systemctl daemon-reload && systemctl show {u} -p Restart")
    return ssh(acc, ip, cmd)


def restaurar(dist, acc, ip):
    """Idempotente: quita el drop-in y arranca la unidad (si ya corre, no hace nada)."""
    u = UNIDAD[dist]
    return ssh(acc, ip, f"sudo rm -f {DROP_IN.format(u=u)} && sudo systemctl daemon-reload && sudo systemctl start {u}"
                        f" && systemctl is-active {u}", 120)


def inyectar(raiz, dist, acc, ip):
    r = subprocess.run(["bash", os.path.join(raiz, "k6", "fallo-controlado.sh"), dist, ip, *acc],
                       capture_output=True, text=True)
    m = dict(re.findall(r"(t_\w+)=([\d.]+)", r.stdout))
    return r.returncode, float(m["t_antes"]), float(m["t_despues"])


def mover_pod(dist, acc, ip_sobreviviente, nodo):
    k = KUBECTL[dist]
    parche = '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/hostname":"%s"}}}}}' % nodo
    return ssh(acc, ip_sobreviviente, f"{k} patch deployment nginx-referencia -p '{parche}' "
                                       f"&& {k} rollout status deployment/nginx-referencia --timeout=120s", 150)


def reiniciar_kube_vip(dist, acc, ip):
    """Fuerza una nueva elección de líder de las dos VIP (cada una tiene su propio lease)."""
    k = KUBECTL[dist]
    return ssh(acc, ip, f"{k} -n kube-system rollout restart ds/kube-vip-ds "
                        f"&& {k} -n kube-system rollout status ds/kube-vip-ds --timeout=120s", 150)


def parametros_efectivos(dist, acc, ip):
    """Líneas de configuración de detección y tolerancia, tal como están en el nodo (no valores por defecto)."""
    k = KUBECTL[dist]
    patron = "node-monitor|grace|toleration|eviction|nodeStatus|node-status|default-not-ready|default-unreachable"
    if dist == "k3s":
        fuente = (f"sudo journalctl -u k3s --no-pager | grep -E 'Running kube-controller-manager|Running kube-apiserver' | tail -2 | tr ' ' '\\n' | grep -E '^--' ; "
                  f"sudo sh -c 'cat /etc/rancher/k3s/config.yaml /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/*.conf 2>/dev/null'")
    else:
        fuente = "sudo cat /var/snap/microk8s/current/args/kube-controller-manager /var/snap/microk8s/current/args/kubelet /var/snap/microk8s/current/args/kube-apiserver 2>/dev/null"
    _, args = ssh(acc, ip, f"({fuente}) | grep -E '{patron}' | sort -u")
    _, tol = ssh(acc, ip, f"{k} get pod -l app=nginx-referencia -o jsonpath='{{.items[0].spec.tolerations}}'")
    return {"argumentos_explicitos": args.splitlines(), "tolerancias_pod": json.loads(tol) if tol else None}


def reloj(acc, ips):
    """chronyc tracking del host y de cada VM, antes de lanzar k6."""
    def campos(txt):
        return {k: v for k, v in re.findall(r"^(Reference ID|Stratum|System time|Last offset|Leap status)\s*:\s*(.+)$", txt, re.M)}
    r = subprocess.run(["chronyc", "tracking"], capture_output=True, text=True)
    return {"host": campos(r.stdout), "vms": {ip: campos(ssh(acc, ip, "chronyc tracking", 20)[1]) for ip in ips}}


def pod_nginx(dist, acc, ip):
    """(uid, IP del nodo) del pod de referencia."""
    rc, out = ssh(acc, ip, f"{KUBECTL[dist]} get pod -l app=nginx-referencia "
                  "-o jsonpath='{.items[0].metadata.uid} {.items[0].status.hostIP}'")
    if rc or len(out.split()) != 2:
        raise RuntimeError(f"no encontré el pod de referencia: {out}")
    return tuple(out.split())


def cpu_pod(acc, ip, uid):
    """cpu.stat del cgroup del pod (usage_usec, nr_periods, nr_throttled, throttled_usec) en su nodo."""
    cmd = (f"sudo find /sys/fs/cgroup -type f -name cpu.stat \\( -path '*pod{uid}/cpu.stat' -o "
           f"-path '*pod{uid.replace('-', '_')}.slice/cpu.stat' \\) | head -1 | xargs -r sudo cat")
    rc, out = ssh(acc, ip, cmd)
    d = dict((k, int(v)) for k, v in re.findall(r"^(usage_usec|nr_periods|nr_throttled|throttled_usec) (\d+)$", out, re.M))
    if rc or len(d) != 4:
        raise RuntimeError(f"no pude leer cpu.stat del pod {uid}: {out}")
    return d


def _http(url, https=False):
    t0 = time.time()
    try:
        c = urllib.request.urlopen(url, timeout=1, context=CTX if https else None).status
    except urllib.error.HTTPError as e:
        c = e.code
    except Exception as e:
        c = type(e).__name__
    return c, round((time.time() - t0) * 1e3)


def _mac(ip):
    o = subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True).stdout
    m = re.search(r"lladdr ([0-9a-f:]{17})", o)
    return m.group(1) if m else None


class Observador:
    """Muestrea desde el host cada ~1 s la app (.150), la API (.100) y la MAC de cada VIP, y cada ~2 s
    el estado de los nodos y los leases de kube-vip y del controller-manager/scheduler vistos desde un nodo que no se falla."""

    def __init__(self, dist, acc, ip_sobreviviente, nombre_de_mac):
        self.dist, self.acc, self.ip, self.nombre = dist, acc, ip_sobreviviente, nombre_de_mac
        self.muestras, self.estado = [], []
        self._fin = threading.Event()
        self._hilos = [threading.Thread(target=self._muestrear, daemon=True),
                       threading.Thread(target=self._estado, daemon=True)]

    def iniciar(self):
        for h in self._hilos:
            h.start()

    def detener(self):
        self._fin.set()
        for h in self._hilos:
            h.join(timeout=20)

    def _muestrear(self):
        puerto = PUERTO_API[self.dist]
        while not self._fin.is_set():
            t = time.time()
            app, app_ms = _http(f"http://{IP_VIP_SVC}:80/")
            cp, cp_ms = _http(f"https://{IP_VIP_CP}:{puerto}/livez", True)
            m_cp, m_svc = _mac(IP_VIP_CP), _mac(IP_VIP_SVC)
            self.muestras.append({"t": round(t, 3), "app": app, "app_ms": app_ms, "cp": cp, "cp_ms": cp_ms,
                                  "titular_cp": self.nombre.get(m_cp, m_cp), "titular_svc": self.nombre.get(m_svc, m_svc)})
            self._fin.wait(max(0, t + 1 - time.time()))

    def _estado(self):
        k = KUBECTL[self.dist]
        nodos = "{range .items[*]}{.metadata.name}={.status.conditions[?(@.type==\"Ready\")].status} {end}"
        leases = "{range .items[*]}{.metadata.name}={.spec.holderIdentity} {end}"
        cmd = f"{k} get nodes -o jsonpath='{nodos}'; echo; {k} -n kube-system get lease -o jsonpath='{leases}'"
        while not self._fin.is_set():
            t = time.time()
            rc, out = ssh(self.acc, self.ip, cmd, 10)
            lineas = out.split("\n") if rc == 0 else ["", ""]
            if len(lineas) == 2:
                self.estado.append({"t": round(t, 3),
                                    "nodos": dict(p.split("=") for p in lineas[0].split() if "=" in p),
                                    "leases": {n: h for n, h in (p.split("=", 1) for p in lineas[1].split() if "=" in p)
                                               if n.startswith("plndr-") or n in ("kube-controller-manager", "kube-scheduler")}})
            self._fin.wait(max(0, t + 2 - time.time()))

    def nodo_listo(self, nodo):
        return bool(self.estado) and self.estado[-1]["nodos"].get(nodo) == "True"


def _caidas(serie):
    """[(t_inicio, t_fin|None)] de los tramos consecutivos con ok=False."""
    out, ini = [], None
    for t, ok in serie:
        if not ok and ini is None:
            ini = t
        elif ok and ini is not None:
            out.append((ini, t))
            ini = None
    return out + ([(ini, None)] if ini is not None else [])


def _rel(x, t0):
    return None if x is None else round(x - t0, 1)


def k6_fallidas(ruta, t_fallo):
    """Solicitudes fallidas y descartadas por k6 antes y después del fallo (http_req_failed, dropped_iterations)."""
    r = {"fallidas_antes": 0, "fallidas_despues": 0, "total_antes": 0, "total_despues": 0, "descartadas_despues": 0,
         "ultima_fallida_s": None}
    with gzip.open(ruta, "rt") as fh:
        for linea in fh:
            if '"http_req_failed"' not in linea and '"dropped_iterations"' not in linea:
                continue
            p = json.loads(linea)
            if p.get("type") != "Point":
                continue
            t = datetime.datetime.fromisoformat(p["data"]["time"]).timestamp()
            v = p["data"]["value"]
            lado = "antes" if t < t_fallo else "despues"
            if p["metric"] == "dropped_iterations":
                if lado == "despues":
                    r["descartadas_despues"] += int(v)
            else:
                r["total_" + lado] += 1
                if v:
                    r["fallidas_" + lado] += 1
                    if lado == "despues":
                        r["ultima_fallida_s"] = round(t - t_fallo, 1)
    return r


def analizar(obs, t_antes, t_despues, nodo, ksm, ruta_k6):
    """Tiempos relativos al fallo (s). Resolución: 1 s (muestras del host), 2 s (estado vía kubectl) y 10 s (kube-state-metrics)."""
    t0 = (t_antes + t_despues) / 2
    m = [x for x in obs.muestras if x["t"] >= t0 - 30]
    ok_cp = [(x["t"], x["cp"] in (200, 401, 403)) for x in m]
    ok_app = [(x["t"], x["app"] == 200) for x in m]

    def titulares(clave):
        out, prev = [], None
        for x in m:
            if x[clave] != prev:
                out.append({"t_s": _rel(x["t"], t0), "titular": x[clave]})
                prev = x[clave]
        return out

    def caidas(serie):
        return [{"desde_s": _rel(a, t0), "hasta_s": _rel(b, t0)} for a, b in _caidas([s for s in serie if s[0] >= t0 - 5])]

    listo = [(e["t"], e["nodos"].get(nodo) == "True") for e in obs.estado]
    nr = _caidas([s for s in listo if s[0] >= t0])
    ksm_c = _caidas([s for s in ksm if s[0] >= t0])
    return {
        "t_fallo": round(t0, 3), "cota_t_fallo_s": round((t_despues - t_antes) / 2, 3),
        "api_vip": caidas(ok_cp), "app_vip": caidas(ok_app),
        "titular_vip_cp": titulares("titular_cp"), "titular_vip_svc": titulares("titular_svc"),
        "nodo_notready_kubectl": {"desde_s": _rel(nr[0][0], t0), "hasta_s": _rel(nr[0][1], t0)} if nr else None,
        "nodo_notready_ksm": {"desde_s": _rel(ksm_c[0][0], t0), "hasta_s": _rel(ksm_c[0][1], t0)} if ksm_c else None,
        "leases": [{"t_s": _rel(e["t"], t0), **e["leases"]} for i, e in enumerate(obs.estado)
                   if i == 0 or e["leases"] != obs.estado[i - 1]["leases"]],
        "k6": k6_fallidas(ruta_k6, t0) if ruta_k6 and os.path.exists(ruta_k6) else None,
    }
