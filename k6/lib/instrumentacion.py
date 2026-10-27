"""Contadores acumulados del host y de las VMs para explicar el nivel de potencia (T-24.4).

leer() toma una foto; delta(a, b) calcula diferencias y tasas entre dos fotos. Un error al leer queda en el JSON y no detiene la corrida.
"""
import glob, os, re, subprocess, threading, time

from k6.lib import fallo

HZ = os.sysconf("SC_CLK_TCK")
SYS = "/sys/devices/system/cpu"
SCRIPT_VM = r"""
echo driver=$(cat /sys/devices/system/cpu/cpuidle/current_driver 2>/dev/null)
echo gobernador=$(cat /sys/devices/system/cpu/cpuidle/current_governor 2>/dev/null)
for f in /sys/devices/system/cpu/cpu*/cpuidle/state*; do
  [ -d "$f" ] && echo "estado $(echo $f | cut -d/ -f6) $(cat $f/name) $(cat $f/time) $(cat $f/usage)"
done
head -1 /proc/stat | sed 's/^/cpu /'
awk '$1=="intr"{print "intr",$2} $1=="ctxt"{print "ctxt",$2}' /proc/stat
awk 'NR>1{s=0; n=$1; for(i=2;i<=NF;i++){ if($i ~ /^[0-9]+$/) s+=$i; else n=n"_"$i } t[n]+=s} END{for(k in t) print "irq",k,t[k]}' /proc/interrupts
"""


def _txt(ruta):
    try:
        return open(ruta).read().strip()
    except OSError:
        return None


def _ticks(ruta_stat):
    try:
        s = open(ruta_stat).read()
        f = s[s.rindex(")") + 2:].split()
        return int(f[11]) + int(f[12])
    except (OSError, ValueError):
        return None


def _clase(comm):
    if "KVM" in comm:
        return "vcpu" + comm.split()[1].split("/")[0]
    if comm.startswith("vhost"):
        return "vhost"
    if comm.startswith("kvm-"):
        return "otros"
    return "emulador_io"


def host():
    h = {"cpuidle": {}, "irq": {}, "qemu": {}, "ksm": {}, "kvm_halt_poll": {}}
    for f in sorted(glob.glob(f"{SYS}/cpu[0-9]*/cpuidle/state*")):
        cpu = f.split("/")[-3]
        nombre = _txt(f + "/name")
        h["cpuidle"].setdefault(cpu, {})[f"{f[-1]}_{nombre}"] = [_txt(f + "/time"), _txt(f + "/usage")]
    por_cpu, por_irq = None, {}
    for l in open("/proc/interrupts").read().splitlines()[1:]:
        c = l.split()
        n = [x for x in c[1:] if x.isdigit()]
        if por_cpu is None:
            por_cpu = [0] * len(n)
        for i, x in enumerate(n[:len(por_cpu)]):
            por_cpu[i] += int(x)
        por_irq[c[0].rstrip(":") + " " + " ".join(c[1 + len(n):])[:30]] = sum(int(x) for x in n)
    h["irq"] = {"por_cpu": por_cpu, "por_irq": por_irq}
    for pidf in glob.glob("/run/libvirt/qemu/*.pid"):
        dom, pid = os.path.basename(pidf)[:-4], _txt(pidf)
        acum = {}
        for t in os.listdir(f"/proc/{pid}/task"):
            comm = _txt(f"/proc/{pid}/task/{t}/comm") or ""
            tk = _ticks(f"/proc/{pid}/task/{t}/stat")
            if tk is not None:
                acum[t] = [_clase(comm), tk]
        h["qemu"][dom] = acum
    k = subprocess.run(["pgrep", "-x", "ksmd"], capture_output=True, text=True).stdout.split()
    h["ksm"] = {"ksmd_ticks": _ticks(f"/proc/{k[0]}/stat") if k else None}
    for f in glob.glob("/sys/kernel/mm/ksm/*"):
        h["ksm"][os.path.basename(f)] = _txt(f)
    for f in glob.glob("/sys/module/kvm/parameters/halt_poll*"):
        h["kvm_halt_poll"][os.path.basename(f)] = _txt(f)
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        if _txt(hw + "/name") == "k10temp":
            h["temperatura_mC"] = _txt(hw + "/temp1_input")
    h["frecuencia_khz"] = {os.path.basename(os.path.dirname(os.path.dirname(f))): _txt(f)
                           for f in sorted(glob.glob(f"{SYS}/cpu[0-9]*/cpufreq/scaling_cur_freq"))}
    return h


def vm(acc, ip):
    rc, out = fallo.ssh(acc, ip, SCRIPT_VM, 20)
    if rc != 0:
        return {"error": f"ssh rc={rc}"}
    v = {"cpuidle": {}, "irq": {}}
    for l in out.splitlines():
        c = l.split()
        if c[0] in ("driver", "gobernador"):
            v[c[0]] = l.split("=", 1)[1]
        elif c[0] == "estado":
            v["cpuidle"].setdefault(c[1], {})[c[2]] = [c[3], c[4]]
        elif c[0] == "cpu":
            v["cpu_ticks"] = dict(zip(("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest"), map(int, c[2:11])))
        elif c[0] in ("intr", "ctxt"):
            v[c[0]] = int(c[1])
        elif c[0] == "irq":
            v["irq"][" ".join(c[1:-1])] = int(c[-1])
    return v


def leer(acc, ips):
    f = {"t": time.time(), "vms": {}}
    hilos = []
    for ip in ips:
        def tarea(ip=ip):
            try:
                f["vms"][ip] = vm(acc, ip)
            except Exception as e:
                f["vms"][ip] = {"error": type(e).__name__}
        hilos.append(threading.Thread(target=tarea))
        hilos[-1].start()
    try:
        f["host"] = host()
    except Exception as e:
        f["host"] = {"error": f"{type(e).__name__}: {e}"}
    for h in hilos:
        h.join()
    return f


def _dif(a, b):
    return None if a is None or b is None else int(b) - int(a)


def delta(a, b, top=10):
    """Diferencias y tasas entre dos fotos. Residencia de cpuidle como fracción de la ventana."""
    dt = b["t"] - a["t"]
    ha, hb = a["host"], b["host"]
    r = {"dt_s": round(dt, 3)}
    if "error" not in ha and "error" not in hb:
        r["cpuidle_residencia"] = {cpu: {e: round(_dif(ha["cpuidle"][cpu][e][0], v[0]) / 1e6 / dt, 4)
                                         for e, v in estados.items()} for cpu, estados in hb["cpuidle"].items()}
        r["cpuidle_entradas"] = {cpu: {e: _dif(ha["cpuidle"][cpu][e][1], v[1]) for e, v in estados.items()}
                                 for cpu, estados in hb["cpuidle"].items()}
        r["interrupciones_por_s_por_cpu"] = [round((y - x) / dt, 1) for x, y in zip(ha["irq"]["por_cpu"], hb["irq"]["por_cpu"])]
        d = {k: hb["irq"]["por_irq"][k] - v for k, v in ha["irq"]["por_irq"].items() if k in hb["irq"]["por_irq"]}
        r["interrupciones_top_por_s"] = {k: round(v / dt, 1) for k, v in sorted(d.items(), key=lambda x: -x[1])[:top]}
        r["qemu_cpu_s"] = {}
        for dom, hilos in hb["qemu"].items():
            c = r["qemu_cpu_s"].setdefault(dom, {})
            for tid, (clase, tk) in hilos.items():
                if tid in ha["qemu"].get(dom, {}):
                    c[clase] = round(c.get(clase, 0) + (tk - ha["qemu"][dom][tid][1]) / HZ, 3)
        ka, kb = ha["ksm"], hb["ksm"]
        r["ksm"] = {"ksmd_cpu_s": None if kb["ksmd_ticks"] is None or ka["ksmd_ticks"] is None else round((kb["ksmd_ticks"] - ka["ksmd_ticks"]) / HZ, 3),
                    "full_scans": _dif(ka.get("full_scans"), kb.get("full_scans")),
                    "pages_sharing_fin": kb.get("pages_sharing"), "pages_shared_fin": kb.get("pages_shared"), "run": kb.get("run")}
        r["kvm_halt_poll"] = hb["kvm_halt_poll"]
        r["temperatura_C"] = [None if x.get("temperatura_mC") is None else int(x["temperatura_mC"]) / 1000 for x in (ha, hb)]
        r["frecuencia_khz_fin"] = hb["frecuencia_khz"]
    else:
        r["host"] = {"error": ha.get("error") or hb.get("error")}
    r["vms"] = {}
    for ip, vb in b["vms"].items():
        va = a["vms"].get(ip, {})
        if "error" in va or "error" in vb:
            r["vms"][ip] = {"error": va.get("error") or vb.get("error")}
            continue
        r["vms"][ip] = {
            "driver_cpuidle": vb.get("driver"), "gobernador": vb.get("gobernador"),
            "cpu_s": {k: round((v - va["cpu_ticks"][k]) / HZ, 3) for k, v in vb["cpu_ticks"].items()},
            "interrupciones_por_s": round((vb["intr"] - va["intr"]) / dt, 1),
            "cambios_de_contexto_por_s": round((vb["ctxt"] - va["ctxt"]) / dt, 1),
            "irq_top_por_s": {k: round((v - va["irq"].get(k, 0)) / dt, 1) for k, v in sorted(
                vb["irq"].items(), key=lambda x: -(x[1] - va["irq"].get(x[0], 0)))[:top]},
            "cpuidle_residencia": {cpu: {e: round((int(v[0]) - int(va["cpuidle"][cpu][e][0])) / 1e6 / dt, 4) for e, v in est.items()}
                                   for cpu, est in vb["cpuidle"].items()} if vb["cpuidle"] else {},
        }
    return r


def autotest():
    ha = {"t": 0, "host": {"cpuidle": {"cpu0": {"1_C1": ["0", "0"], "2_C2": ["0", "0"]}}, "irq": {"por_cpu": [0, 0], "por_irq": {"a": 0, "b": 0}},
                           "qemu": {"d": {"1": ["vcpu0", 0], "2": ["emulador_io", 50]}}, "ksm": {"ksmd_ticks": 0, "full_scans": "1"}, "kvm_halt_poll": {}, "frecuencia_khz": {}}, "vms": {}}
    hb = {"t": 10, "host": {"cpuidle": {"cpu0": {"1_C1": ["2000000", "5"], "2_C2": ["5000000", "3"]}}, "irq": {"por_cpu": [100, 50], "por_irq": {"a": 120, "b": 30}},
                            "qemu": {"d": {"1": ["vcpu0", 200]}}, "ksm": {"ksmd_ticks": 50, "full_scans": "3"}, "kvm_halt_poll": {"halt_poll_ns": "200000"}, "frecuencia_khz": {}}, "vms": {}}
    d = delta(ha, hb)
    assert d["cpuidle_residencia"]["cpu0"] == {"1_C1": 0.2, "2_C2": 0.5}
    assert d["interrupciones_por_s_por_cpu"] == [10.0, 5.0] and list(d["interrupciones_top_por_s"])[0] == "a"
    assert d["qemu_cpu_s"]["d"] == {"vcpu0": 200 / HZ}  # el hilo 2 terminó: no resta and d["ksm"]["full_scans"] == 2
    print("autotest ok")


if __name__ == "__main__":
    import json, sys
    if "--autotest" in sys.argv:
        autotest()
    else:
        a = leer(None, [])
        time.sleep(5)
        print(json.dumps(delta(a, leer(None, [])), indent=1)[:3000])
