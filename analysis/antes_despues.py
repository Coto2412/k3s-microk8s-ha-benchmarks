"""Mejoras de la Etapa 3, antes y después (E9.3), solo con datos versionados.

  python3 -m analysis.antes_despues [--salida analysis/salidas/<fecha>_antes_despues]

Cada fila cita su fuente. Las mejoras sin datos versionados se marcan así y citan su evidencia; nunca llevan un valor.
"""
import argparse, csv, glob, json, os, statistics, sys

from k6.lib.comun import RAIZ

ESCENARIOS = ("idle", "media", "alta")
SAL = "analysis/salidas"
# (mejora, condición, distribución, sesión de metadatos, evidencia)
POTENCIA = [
    ("boost de CPU", "activo", "k3s", "data/exploratorio/2026-10-25_k3s_boost-activo", "evidencia_T-20.md 6.3"),
    ("boost de CPU", "apagado", "k3s", "data/exploratorio/2026-10-26_k3s", "evidencia_T-20.md 7.4"),
    ("aplicación de referencia", "NGINX estático, límite 500m", "k3s", "data/pilotos/2026-10-27_k3s", "evidencia_T-20.md 7.1"),
    ("aplicación de referencia", "NGINX estático, límite 500m", "microk8s", "data/pilotos/2026-10-27_microk8s", "evidencia_T-20.md 7.1"),
    ("aplicación de referencia", "SHA-256 x300, límite 2000m", "k3s", "data/pilotos/2026-10-28_k3s", "evidencia_T-20.md 7.6"),
    ("aplicación de referencia", "SHA-256 x300, límite 2000m", "microk8s", "data/pilotos/2026-10-28_microk8s", "evidencia_T-20.md 7.6"),
]
REPOSO = [("boost de CPU (reposo del host, sin VMs)", "activo", "data/reposo/reposo_host_boost-activo_s0*.json", "evidencia_T-20.md 2.3"),
          ("boost de CPU (reposo del host, sin VMs)", "apagado", "data/reposo/reposo_host_s0*.json", "evidencia_T-20.md 2.3")]
# kube-vip: la sesión del 19-oct es la configuración original (evidencia_T-19.md, nombres de los datos)
KUBE_VIP = [("original", f"{SAL}/2026-10-20_recuperacion_inicial/recuperacion.csv", lambda f: f["sesion"].endswith("2026-10-19_k3s")),
            ("nuevo (apiserver local)", f"{SAL}/2026-10-20_recuperacion_inicial/recuperacion.csv", lambda f: not f["sesion"].endswith("2026-10-19_k3s")),
            ("nuevo (apiserver local)", f"{SAL}/2026-10-27_recuperacion_definitiva/recuperacion.csv", lambda f: True),
            ("nuevo (apiserver local)", f"{SAL}/2026-11-02_recuperacion/recuperacion.csv", lambda f: True)]
SIN_DATOS = [("diseño estadístico", "muestras independientes frente a diferencias por bloque",
              "simulación sin salida versionada (analysis/potencia.py la regenera)", "evidencia_T-21.md 4.3")]


def _r(x, n=3):
    return None if x is None else round(x, n)


def potencia(sesion):
    """{escenario: (tasa, n, media W, sd W)} con la potencia RAPL de la fase estable de cada corrida."""
    por = {}
    for r in sorted(glob.glob(os.path.join(RAIZ, sesion, "metadatos", "*.json"))):
        if r.endswith(".observador.json"):
            continue
        m = json.load(open(r))
        if m.get("fallo") or m.get("escenario") not in ESCENARIOS:
            continue
        por.setdefault(m["escenario"], []).append(((m.get("parametros") or {}).get("tasa"), m["rapl"]["potencia_media_W"]))
    return {e: (v[0][0], len(v), statistics.mean(p for _, p in v), statistics.stdev(p for _, p in v) if len(v) > 1 else None)
            for e, v in por.items()}


def filas():
    out = []
    for mejora, cond, dist, ses, ev in POTENCIA:
        p = potencia(ses)
        if not p:
            out.append({"mejora": mejora, "condicion": cond, "distribucion": dist, "metrica": "potencia del paquete (W)",
                        "valor": "sin datos versionados", "fuente": ses, "evidencia": ev})
        for e in ESCENARIOS:
            if e in p:
                tasa, n, med, sd = p[e]
                out.append({"mejora": mejora, "condicion": cond, "distribucion": dist, "escenario": e, "tasa_rps": tasa, "n": n,
                            "metrica": "potencia del paquete (W)", "valor": _r(med), "sd": _r(sd), "fuente": ses, "evidencia": ev})
    for mejora, cond, patron, ev in REPOSO:
        v = [w["potencia_media_W"] for r in sorted(glob.glob(os.path.join(RAIZ, patron))) for w in json.load(open(r))["ventanas"]]
        out.append({"mejora": mejora, "condicion": cond, "n": len(v), "metrica": "potencia del paquete (W)",
                    "valor": _r(statistics.mean(v)) if v else "sin datos versionados", "sd": _r(statistics.stdev(v)) if len(v) > 1 else None,
                    "fuente": patron, "evidencia": ev})
    for cond, ruta, sel in KUBE_VIP:
        fs = [f for f in csv.DictReader(open(os.path.join(RAIZ, ruta))) if sel(f)]
        for dist in sorted({f["distribucion"] for f in fs}):
            d = [f for f in fs if f["distribucion"] == dist]
            mig = [float(f["migracion_vip_plano_control"]) for f in d if f["migracion_vip_plano_control"]]
            api = [float(f["api_restablecida"]) for f in d if f["api_restablecida"]]
            base = {"mejora": "kube-vip", "condicion": cond, "distribucion": dist, "escenario": "media",
                    "tasa_rps": d[0]["tasa"], "n": len(d), "fuente": ruta, "evidencia": "evidencia_T-19.md 2.3"}
            out.append(base | {"metrica": "corridas en que migró la VIP del plano de control", "valor": f"{len(mig)}/{len(d)}"})
            out.append(base | {"metrica": "restablecimiento de la API, mediana (s)", "valor": _r(statistics.median(api), 1) if api else None})
    for mejora, cond, motivo, ev in SIN_DATOS:
        out.append({"mejora": mejora, "condicion": cond, "valor": "sin datos versionados", "fuente": motivo, "evidencia": ev})
    dec = sorted(glob.glob(os.path.join(RAIZ, SAL, "*diagnostico*", "decision.json")))
    if dec:
        d = json.load(open(dec[-1]))
        out.append({"mejora": "factor del diagnóstico del desfase", "condicion": d.get("decision"), "valor": json.dumps(d, ensure_ascii=False),
                    "fuente": os.path.relpath(dec[-1], RAIZ), "evidencia": "evidencia_E6.md"})
    else:
        out.append({"mejora": "factor del diagnóstico del desfase", "valor": "sin datos versionados", "fuente": "pendiente del 19-nov",
                    "evidencia": "evidencia_E6.md 2.5"})
    return out


def autotest():
    f = filas()
    boost = {x["condicion"]: x["valor"] for x in f if x["mejora"] == "boost de CPU" and x.get("escenario") == "alta"}
    assert boost["activo"] > boost["apagado"], boost
    assert any(x["mejora"] == "kube-vip" and x["condicion"] == "original" and x["valor"] == "0/1" for x in f)
    assert all(x["valor"] == "sin datos versionados" for x in f if x["mejora"] == "diseño estadístico")
    print("autotest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida")
    ap.add_argument("--autotest", action="store_true")
    a = ap.parse_args()
    if a.autotest:
        return autotest()
    f = filas()
    cols = ["mejora", "condicion", "distribucion", "escenario", "tasa_rps", "n", "metrica", "valor", "sd", "fuente", "evidencia"]
    if a.salida:
        os.makedirs(a.salida, exist_ok=True)
    w = csv.DictWriter(open(os.path.join(a.salida, "antes_despues.csv"), "w", newline="") if a.salida else sys.stdout, cols)
    w.writeheader()
    w.writerows(f)
    if a.salida:
        print("escrito", os.path.join(a.salida, "antes_despues.csv"))


if __name__ == "__main__":
    sys.exit(main())
