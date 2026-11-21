"""Integridad de las corridas con fallo (T-25.3): continuidad de cada fuente en la fase estable, secuencia de eventos y
coherencia de las marcas de tiempo. Una fila por corrida y una columna por verificación (ok, falla o no aplica).

  python3 -m analysis.campana.integridad_fallo --datos data/campana --salida analysis/salidas/<fecha>_campana
  python3 -m analysis.campana.integridad_fallo --sesiones data/pilotos/2026-11-02_k3s_fallo,... --salida <dir>
"""
import argparse, glob, gzip, json, os, sys

from analysis.campana.consolidar import sesiones
from analysis.campana.todo import escribir
from k6.lib import fallo
from k6.lib.comun import RAIZ

# Huecos máximos por fuente (s). Propios: 3 veces el período nominal (Prometheus 10 s, observador 1 y 2 s, k6 1 s).
HUECO_MAX = {"prometheus": 30, "observador_http": 3, "observador_kubectl": 6, "k6": 3}
COBERTURA_MIN = 0.9
COTA_INYECCION_S = 2
TOLERANCIA_S = 2  # inyección y restauración respecto de lo programado


def _hueco_cobertura(ts, t0, t1, periodo):
    ts = sorted(t for t in ts if t0 <= t <= t1)
    if not ts:
        return None, 0.0
    bordes = [ts[0] - t0, t1 - ts[-1]]
    return round(max([b - a for a, b in zip(ts, ts[1:])] + bordes), 1), round(len(ts) * periodo / (t1 - t0), 3)


def fuentes(m, t0, t1):
    """{fuente: (hueco_max_s, cobertura, ok)} en [t0, t1]."""
    out = {}

    def poner(nombre, clase, ts, periodo):
        h, c = _hueco_cobertura(ts, t0, t1, periodo)
        out[nombre] = (h, c, h is not None and h <= HUECO_MAX[clase] and c >= COBERTURA_MIN)

    v = m.get("ventana_prometheus") or {}
    ruta = os.path.join(RAIZ, v["archivo"]) if v.get("archivo") else None
    if ruta and os.path.exists(ruta):
        sel = [s for r in json.load(gzip.open(ruta, "rt"))["resultado"].values() for s in r]
        for s in sel:
            if s["metric"]["__name__"] == "up":
                pts = [(float(t), x) for t, x in s["values"]]
                poner(f"{s['metric']['job']}@{s['metric']['instance']}", "prometheus", [t for t, x in pts if x == "1"], 10)
        ksm = {float(t) for s in sel if s["metric"]["__name__"] == "kube_node_status_condition" for t, _ in s["values"]}
        poner("kube_state_metrics", "prometheus", ksm, 10)
    else:
        out["prometheus"] = (None, 0.0, False)
    obs = (m["fallo"].get("observador") or "")
    obs = os.path.join(RAIZ, obs) if obs else None
    if obs and os.path.exists(obs):
        o = json.load(gzip.open(obs, "rt"))
        poner("observador_http", "observador_http", [x["t"] for x in o["muestras"]], 1)
        poner("observador_kubectl", "observador_kubectl", [x["t"] for x in o["estado"]], 2)
    else:
        out["observador"] = (None, 0.0, False)
    k6 = (m.get("k6") or {}).get("por_segundo") or m.get("k6_por_segundo")
    k6 = k6 if k6 and os.path.isabs(k6) else (os.path.join(RAIZ, k6) if k6 else None)
    if not k6:  # convención de los pilotos y del orquestador: k6-resultados/<nombre>.por_segundo.json.gz
        base = os.path.basename(m["_ruta"])[:-len(".json")]
        k6 = os.path.join(os.path.dirname(os.path.dirname(m["_ruta"])), "k6-resultados", base + ".por_segundo.json.gz")
    if os.path.exists(k6):
        poner("k6", "k6", [x["t"] for x in json.load(gzip.open(k6, "rt")) if x["solicitudes"]], 1)
    else:
        out["k6"] = (None, 0.0, False)
    r = m.get("rapl") or {}
    lect = (r.get("lectura_inicio_s") or [None])[0], (r.get("lectura_fin_s") or [None])[0]
    rapl_ok = r.get("delta_uj", 0) > 0 and None not in lect and abs(lect[0] - t0) <= 1 and abs(lect[1] - t1) <= 1
    out["rapl"] = (None, None, rapl_ok)
    return out


def _titular_previo(lista):
    previos = [x["titular"] for x in lista if x["t_s"] <= 0]
    return previos[-1] if previos else None


def eventos(m):
    """{verificación: (estado, detalle)} con estado ok, falla o no aplica."""
    fa = m["fallo"]
    an, ev, par = fa.get("analisis") or {}, fa.get("eventos") or {}, fa.get("parametros") or {}
    if not an:
        return {"analisis": ("falla", "sin bloque analisis")}
    nodo = fa["nodo_fallado"]
    t = fallo.tiempos(an, nodo, ev.get("t_restaura"))
    fin = m["t_fin"] - an["t_fallo"]
    r = {}

    def chk(nombre, ok, detalle=""):
        r[nombre] = ("ok" if ok else "falla", detalle)

    programado = m["t_inicio"] + par.get("fallo_en_s", 30)
    chk("inyeccion", ev.get("rc_inyeccion") == 0 and an["cota_t_fallo_s"] <= COTA_INYECCION_S
        and abs(an["t_fallo"] - programado) <= TOLERANCIA_S,
        f"rc={ev.get('rc_inyeccion')} cota={an['cota_t_fallo_s']} desvio={round(an['t_fallo'] - programado, 1)}")
    rest = t["restauracion"]
    chk("restauracion", (ev.get("restauracion") or [1])[0] == 0 and rest is not None
        and abs(rest - par.get("retener_s", 120)) <= TOLERANCIA_S, f"t={rest}")
    chk("notready", t["notready"] is not None and 0 < t["notready"] < (rest or fin), f"t={t['notready']}")
    for vip, clave, mig in (("vip_plano_control", "titular_vip_cp", "migracion_vip_plano_control"),
                            ("vip_servicio", "titular_vip_svc", "migracion_vip_servicio")):
        previo = _titular_previo(an.get(clave, []))
        if previo != nodo:  # la VIP la tenía otro nodo: no debe moverse
            r["migracion_" + vip] = ("no aplica" if t[mig] is None else "falla", f"titular previo {previo}, t={t[mig]}")
        else:
            chk("migracion_" + vip, t[mig] is not None and 0 < t[mig] < (rest or fin), f"t={t[mig]}")
    if t["api_caida_desde"] is None:
        r["api"] = ("no aplica", "sin caída de la API")
    else:
        chk("api", t["api_restablecida"] is not None and 0 <= t["api_caida_desde"] <= t["api_restablecida"] < (rest or fin),
            f"{t['api_caida_desde']}–{t['api_restablecida']}")
    nr = an.get("nodo_notready_kubectl") or {}
    chk("ready", t["ready_tras_restauracion"] is not None and t["ready_tras_restauracion"] >= 0
        and nr.get("hasta_s") is not None and nr["hasta_s"] <= fin and ev.get("nodo_listo_al_final") is True,
        f"t={t['ready_tras_restauracion']} final={ev.get('nodo_listo_al_final')}")
    chk("estrato_lider", t["nodo_fallado_lideraba"] is not None, f"lider={t['lider_controller_manager_previo']}")
    return r


def revisar(ruta):
    m = json.load(open(ruta))
    m["_ruta"] = ruta
    t0, t1 = m["t_inicio"], m["t_fin"]
    fila = {"corrida": os.path.relpath(ruta, RAIZ), "distribucion": m.get("distribution"),
            "valida_para_campana": m.get("valida_para_campana")}
    fs = fuentes(m, t0, t1)
    for k, (h, c, ok) in sorted(fs.items()):
        fila[f"fuente:{k}"] = ("ok" if ok else "falla") + ("" if h is None else f" (hueco {h} s, cobertura {c})")
    ev = eventos(m)
    for k, (estado, det) in ev.items():
        fila[f"evento:{k}"] = f"{estado} ({det})" if det else estado
    fila["cumple"] = all(ok for *_, ok in fs.values()) and all(e != "falla" for e, _ in ev.values())
    return fila


def corridas_fallo(carpetas):
    return [r for c in carpetas for r in sorted(glob.glob(os.path.join(c, "metadatos", "*.json")))
            if not r.endswith(".observador.json") and json.load(open(r)).get("fallo")]


def autotest():
    assert _hueco_cobertura([0, 1, 2, 3], 0, 3, 1) == (1, 1.333)
    assert _hueco_cobertura([0, 1, 10], 0, 10, 1)[0] == 9
    assert _hueco_cobertura([], 0, 10, 1) == (None, 0.0)
    assert _titular_previo([{"t_s": -29, "titular": "a"}, {"t_s": 25, "titular": "b"}]) == "a"
    an = {"t_fallo": 1030.0, "cota_t_fallo_s": 0.8, "api_vip": [{"desde_s": 1, "hasta_s": 26}], "app_vip": [],
          "titular_vip_cp": [{"t_s": -30, "titular": "n1"}, {"t_s": 25, "titular": "n3"}],
          "titular_vip_svc": [{"t_s": -30, "titular": "n2"}],
          "nodo_notready_kubectl": {"desde_s": 74, "hasta_s": 134}, "leases": [{"t_s": -60, "kube-controller-manager": "n1_x"}]}
    m = {"t_inicio": 1000.0, "t_fin": 1180.0, "fallo": {"nodo_fallado": "n1", "analisis": an, "parametros": {"fallo_en_s": 30, "retener_s": 120},
         "eventos": {"rc_inyeccion": 0, "t_restaura": 1150.5, "restauracion": [0, "active"], "nodo_listo_al_final": True}}}
    e = eventos(m)
    assert all(v[0] == "ok" for k, v in e.items() if k != "migracion_vip_servicio"), e
    assert e["migracion_vip_servicio"][0] == "no aplica"
    m["fallo"]["eventos"]["rc_inyeccion"] = 1
    an["titular_vip_cp"] = an["titular_vip_cp"][:1]  # la VIP del nodo fallado no migró
    an["nodo_notready_kubectl"]["hasta_s"] = None
    e = eventos(m)
    assert [k for k, v in e.items() if v[0] == "falla"] == ["inyeccion", "migracion_vip_plano_control", "ready"], e
    print("autotest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", help="raíz de la campaña (bNN_<dist>)")
    ap.add_argument("--sesiones", help="carpetas separadas por coma (pruebas con pilotos)")
    ap.add_argument("--salida", required="--autotest" not in sys.argv)
    ap.add_argument("--autotest", action="store_true")
    a = ap.parse_args()
    if a.autotest:
        return autotest()
    carpetas = list(sesiones(a.datos).values()) if a.datos else (a.sesiones or "").split(",")
    filas = [revisar(r) for r in corridas_fallo([c for c in carpetas if c])]
    if not filas:
        sys.exit("sin corridas con fallo")
    os.makedirs(a.salida, exist_ok=True)
    escribir(os.path.join(a.salida, "integridad_fallo.csv"), filas)
    n = sum(f["cumple"] for f in filas)
    print(f"integridad: {n}/{len(filas)} corridas cumplen")
    for f in filas:
        if not f["cumple"]:
            print(" ", f["corrida"], "|", "; ".join(f"{k}={v}" for k, v in f.items() if isinstance(v, str) and v.startswith("falla")))


if __name__ == "__main__":
    main()
