"""Pipeline pre-registrado de la campaña (E7, plan-campana-v1).

  python3 -m analysis.campana.todo --datos data/campana --salida analysis/salidas/<fecha>_campana
  python3 -m analysis.campana.todo --autotest
  # prueba de punta a punta con las jornadas 3 y 4 como dos bloques ficticios (salidas sin interpretar):
  python3 -m analysis.campana.todo --ficticio 1:k3s:data/pilotos/2026-10-28_k3s --ficticio 1:microk8s:data/pilotos/2026-10-28_microk8s \\
      --ficticio 2:k3s:data/pilotos/2026-11-02_k3s,data/pilotos/2026-11-02_k3s_fallo \\
      --ficticio 2:microk8s:data/pilotos/2026-11-02_microk8s,data/pilotos/2026-11-02_microk8s_fallo \\
      --incluir-no-validas --salida /tmp/prueba_pipeline

Salidas (CSV salvo donde se indica): corridas, tramos, celdas, anomalias, principal (+ principal.json con el TOST y el
veredicto por escenario), una tabla por familia secundaria, sensibilidad (modelo mixto y sobrecosto en reposo),
exploratorio_* (rotulados) y resumen.txt.
"""
import argparse, csv, json, math, os, statistics, sys, warnings

import numpy as np

from analysis.campana import consolidar as con
from analysis.campana import pruebas as pr

ESC = ("idle", "media", "alta")
CON_CARGA = ("media", "alta")
DISTS = ("k3s", "microk8s")
# Métricas por celda (promedio de las corridas incluidas)
METRICAS_CELDA = ["potencia_W", "j_por_solicitud", "cpu_vm_media", "cpu_host_pct", "memavailable_min_host_mb", "rss_qemu_total_mb",
                  "swap_paginas", "ve_p50_ms", "ve_p95_ms", "ve_p99_ms", "ve_descartadas", "ve_fallidas", "ve_solicitudes",
                  "scaphandre_W", "temperatura_media_C", "frecuencia_media_mhz"]
# Familias secundarias (sección 6.5 del pre-registro): (nombre, [(métrica, escenarios o None si es por tramo)])
FAMILIAS = [
    ("energia_por_solicitud", [("j_por_solicitud", CON_CARGA)]),
    ("cpu", [("cpu_vm_media", ESC), ("cpu_host_pct", ESC)]),
    ("memoria", [("memavailable_min_host_mb", ESC), ("rss_qemu_total_mb", ESC), ("swap_paginas", ESC)]),
    ("latencia", [("ve_p50_ms", CON_CARGA), ("ve_p95_ms", CON_CARGA), ("ve_p99_ms", CON_CARGA)]),
    ("despliegue", [("construccion_s", None), ("construccion_J", None)]),
    ("recuperacion", [("migracion_vip_plano_control", "fallo"), ("migracion_vip_servicio", "fallo"),
                      ("api_restablecida", "fallo"), ("ready_tras_restauracion", "fallo")]),
    ("almacenamiento", [("almacenamiento_distribucion_bytes", None), ("almacenamiento_containerd_bytes", None),
                        ("df_usado_bytes", None), ("qcow2_total_bytes", None), ("contenido_imagenes_bytes", None),
                        ("escrito_idle_bytes_por_nodo", None)]),
]


def escribir(ruta, filas):
    if not filas:
        open(ruta, "w").close()
        return
    cols = list(dict.fromkeys(k for f in filas for k in f))
    with open(ruta, "w", newline="") as fh:
        w = csv.DictWriter(fh, cols)
        w.writeheader()
        w.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in f.items()} for f in filas)


def pares_por_bloque(filas, metrica, filtro=lambda f: True):
    """(k3s, microk8s) alineados por bloque, solo bloques con ambos valores numéricos."""
    por = {}
    for f in filas:
        if filtro(f) and isinstance(f.get(metrica), (int, float)):
            por.setdefault(f["bloque"], {})[f["distribucion"]] = f[metrica]
    bloques = sorted(b for b, v in por.items() if all(d in v for d in DISTS))
    return [por[b]["k3s"] for b in bloques], [por[b]["microk8s"] for b in bloques], bloques


def principal(celdas):
    fam, tost, pares = [], {}, {}
    for e in ESC:
        k, m, bl = pares_por_bloque(celdas, "potencia_W", lambda f: f["escenario"] == e)
        pares[e] = (k, m)
    fam = pr.comparar(pares, ESC)
    for f in fam:
        k, m = pares[f["metrica"]]
        f["escenario"] = f.pop("metrica")
        if len(k) >= 2:
            tost[f["escenario"]] = pr.tost_log(m, k)
            f["veredicto"] = pr.veredicto(f, tost[f["escenario"]])
    return fam, tost


def secundaria(nombre, metricas, celdas, tramos, corridas):
    pares, orden = {}, []
    for met, escs in metricas:
        if escs is None:
            claves = [(met, tramos, lambda f: True)]
        elif escs == "fallo":  # en la campaña hay una por tramo; si hubiera varias, se promedian
            por = {}
            for f in corridas:
                if f["fallo"] and f["incluida"] and isinstance(f.get(met), (int, float)):
                    por.setdefault((f["bloque"], f["distribucion"]), []).append(f[met])
            fuente = [{"bloque": b, "distribucion": d, met: statistics.fmean(v)} for (b, d), v in por.items()]
            claves = [(met, fuente, lambda f: True)]
        else:
            claves = [(f"{met}|{e}", celdas, (lambda e: lambda f: f["escenario"] == e)(e)) for e in escs]
        for clave, fuente, filtro in claves:
            k, m, _ = pares_por_bloque(fuente, clave.split("|")[0], filtro)
            pares[clave] = (k, m)
            orden.append(clave)
    filas = pr.comparar(pares, orden)
    for f in filas:
        f["familia"] = nombre
    return filas


def modelo_mixto(corridas):
    """Sensibilidad: potencia ~ distribución × escenario, efecto aleatorio de bloque; jornada fija y, si no converge, aleatoria."""
    import pandas as pd
    import statsmodels.formula.api as smf
    df = pd.DataFrame([{k: f[k] for k in ("potencia_W", "distribucion", "escenario", "bloque", "jornada")}
                       for f in corridas if f["incluida"] and not f["fallo"]])
    if df.empty or df["bloque"].nunique() < 2:
        return {"ajustado": False, "motivo": "menos de 2 bloques"}
    df["jornada"] = df["jornada"].fillna(0).astype(str)
    intentos = [("jornada fija", "potencia_W ~ C(distribucion) * C(escenario) + C(jornada)", None)]
    intentos.append(("jornada aleatoria", "potencia_W ~ C(distribucion) * C(escenario)", {"jornada": "0 + C(jornada)"}))
    for etiqueta, formula, vc in intentos:
        if df["jornada"].nunique() < 2:  # una sola jornada: no hay efecto que estimar
            etiqueta, formula, vc = "sin jornada (un solo nivel)", formula.replace(" + C(jornada)", ""), None
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter("always")
            try:
                r = smf.mixedlm(formula, df, groups=df["bloque"], vc_formula=vc).fit(reml=True)
            except Exception as e:  # matriz singular u otro fallo numérico: se prueba la siguiente especificación
                avisos.append(e)
                continue
        conv = r.converged and not any("converge" in str(a).lower() for a in avisos)
        if conv:
            return {"ajustado": True, "especificacion": etiqueta, "formula": formula, "n": len(df),
                    "coeficientes": {k: [round(float(r.params[k]), 4), round(float(r.bse[k]), 4), round(float(r.pvalues[k]), 4)]
                                     for k in r.params.index if not k.endswith("Var")},
                    "varianza_bloque": round(float(r.cov_re.iloc[0, 0]), 5), "varianza_residual": round(float(r.scale), 5)}
    return {"ajustado": False, "motivo": "no convergió con jornada fija ni aleatoria"}


def exploratorios(tramos, corridas):
    """Rotulados como exploratorios: nivel idle por construcción y covariables; NotReady por estrato."""
    from analysis.desfase_retro import niveles
    from scipy import stats
    ex_niv = []
    vals = [t["idle_media_W"] for t in tramos if t["idle_media_W"] is not None]
    nv = niveles(vals) if vals else {}
    for t in tramos:
        ex_niv.append({"rotulo": "exploratorio", "bloque": t["bloque"], "distribucion": t["distribucion"], "jornada": t["jornada"],
                       "idle_media_W": t["idle_media_W"], "nivel_idle": nv.get(t["idle_media_W"]), "referencia_W": t["referencia_W"]})
    cov = []
    for col in ("referencia_W", "temperatura_media_C", "frecuencia_media_mhz", "memavailable_min_host_mb"):
        fuente = tramos if col == "referencia_W" else [
            {"idle_media_W": t["idle_media_W"], col: statistics.fmean(v) if (v := [c[col] for c in corridas if c["bloque"] == t["bloque"] and
             c["distribucion"] == t["distribucion"] and c["escenario"] == "idle" and c["incluida"] and isinstance(c.get(col), (int, float))]) else None}
            for t in tramos]
        xy = [(f[col], f["idle_media_W"]) for f in fuente if isinstance(f.get(col), (int, float)) and f["idle_media_W"] is not None]
        if len(xy) >= 3:
            r = stats.spearmanr(*zip(*xy))
            cov.append({"rotulo": "exploratorio", "covariable": col, "n_tramos": len(xy), "spearman_rho": round(float(r.statistic), 3),
                        "p_sin_ajuste": round(float(r.pvalue), 4)})
    nr = [{"rotulo": "exploratorio (descriptivo)", "distribucion": f["distribucion"], "bloque": f["bloque"],
           "nodo_fallado_lideraba": f.get("nodo_fallado_lideraba"), "notready_s": f.get("notready")}
          for f in corridas if f["fallo"]]
    return ex_niv, cov, nr


def figuras(salida, corridas, celdas, cache, rotulo):
    """T-26.5: solo donde los datos son extensos (potencia por bloque, espectro de latencia, recuperación); el resto va en CSV."""
    from analysis import figuras as fg
    normales = [f for f in corridas if f["incluida"] and not f["fallo"]]
    fg.fig_bloques(celdas, os.path.join(salida, "figura_potencia_bloques.pdf"), rotulo)
    if any(f["escenario"] != "idle" for f in normales):
        fg.fig_espectro(normales, cache, os.path.join(salida, "figura_espectro_latencia.pdf"), rotulo)
    rec = [dict(f, repeticion=f["bloque"]) for f in corridas if f["fallo"] and f["incluida"] and f.get("restauracion") is not None]
    if rec:  # en la campaña hay una corrida con fallo por tramo: la fila se rotula con el bloque
        fg.fig_recuperacion(rec, os.path.join(salida, "figura_recuperacion.pdf"), rotulo, prefijo="b")


def ejecutar(mapa, salida, incluir_no_validas=False, rotulo=""):
    os.makedirs(salida, exist_ok=True)
    ruta_cache = os.path.join(salida, "cache_latencia.json")
    cache = json.load(open(ruta_cache)) if os.path.exists(ruta_cache) else {}
    corridas, tramos = con.consolidar(mapa, incluir_no_validas, cache)
    json.dump(cache, open(ruta_cache, "w"))
    celdas = con.celdas(corridas, METRICAS_CELDA)
    anom = con.anomalias(corridas, tramos, celdas)
    for n, f in (("corridas", corridas), ("tramos", tramos), ("celdas", celdas), ("anomalias", anom)):
        escribir(os.path.join(salida, n + ".csv"), f)
    fam, tost = principal(celdas)
    escribir(os.path.join(salida, "principal.csv"), fam)
    json.dump({"familia_principal": fam, "tost": tost}, open(os.path.join(salida, "principal.json"), "w"), indent=1, ensure_ascii=False)
    for nombre, mets in FAMILIAS:
        escribir(os.path.join(salida, f"secundaria_{nombre}.csv"), secundaria(nombre, mets, celdas, tramos, corridas))
    sobre = secundaria("sensibilidad_sobrecosto_reposo", [("sobrecosto_reposo_W", None)], celdas, tramos, corridas)
    k, m, _ = pares_por_bloque(tramos, "idle_media_W")
    kr, mr, _ = pares_por_bloque(tramos, "sobrecosto_reposo_W")
    sens = {"modelo_mixto": modelo_mixto(corridas), "sobrecosto_reposo": sobre}
    json.dump(sens, open(os.path.join(salida, "sensibilidad.json"), "w"), indent=1, ensure_ascii=False, default=str)
    niv, cov, nr = exploratorios(tramos, corridas)
    escribir(os.path.join(salida, "exploratorio_niveles_idle.csv"), niv)
    escribir(os.path.join(salida, "exploratorio_covariables_idle.csv"), cov)
    escribir(os.path.join(salida, "exploratorio_notready_estrato.csv"), nr)
    lineas = [f"Bloques con ambas distribuciones: {len(pares_por_bloque(celdas, 'potencia_W', lambda f: f['escenario'] == 'idle')[2])}",
              f"Corridas: {len(corridas)} ({sum(f['incluida'] for f in corridas)} incluidas); anomalías: {len(anom)}"]
    for f in fam:
        t = tost.get(f["escenario"], {})
        lineas.append(f"{f['escenario']:5s} dif {f.get('dif_media')} W, HL {f.get('hl')} {f.get('hl_ic')} ({f.get('hl_nivel')}), "
                      f"p Wilcoxon {f.get('wilcoxon_p')} (Holm {f.get('wilcoxon_p_holm')}), razón {t.get('razon')} "
                      f"IC90 {t.get('ic90_razon')}: {f.get('veredicto', 'sin pares suficientes')}")
    mm = sens["modelo_mixto"]
    lineas.append(f"Modelo mixto: {mm.get('especificacion', mm.get('motivo'))}")
    open(os.path.join(salida, "resumen.txt"), "w").write("\n".join(lineas) + "\n")
    figuras(salida, corridas, celdas, cache, rotulo)
    print("\n".join(lineas))
    return corridas, tramos, celdas


def autotest():
    pr.autotest()
    con.autotest()
    # Holm ordena bien dentro de una familia: el p menor se ajusta por m, el siguiente por m - 1
    fam = pr.comparar({"a": ([1, 2, 3, 4, 5, 6, 7, 8], [2, 3, 4, 5, 6, 7, 8, 9.5]), "b": ([1] * 8, [1.01, 0.99] * 4)}, ["a", "b"])
    assert fam[0]["wilcoxon_p_holm"] == min(1, 2 * fam[0]["wilcoxon_p"])
    # celdas sintéticas: 8 bloques, +0,20 W en MicroK8s en los tres escenarios
    rng = np.random.default_rng(1)
    celdas = [{"bloque": b, "distribucion": d, "escenario": e, "potencia_W": base + rng.normal(0, 0.02) + (0.2 if d == "microk8s" else 0)}
              for b in range(1, 9) for e, base0 in zip(ESC, (5, 10, 15)) for base in [base0 + rng.normal(0, 0.5)] for d in DISTS]
    fam, tost = principal(celdas)
    assert all(f["significativa"] and abs(f["hl"] - 0.2) < 0.05 for f in fam)
    assert all(f["veredicto"].startswith("diferencia detectada") for f in fam)
    print("autotest ok")


def main():
    if "--autotest" in sys.argv:
        return autotest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", help="data/campana")
    ap.add_argument("--ficticio", action="append", default=[], help="BLOQUE:DIST:carpeta[,carpeta] (solo pruebas del pipeline)")
    ap.add_argument("--incluir-no-validas", action="store_true", help="solo pruebas del pipeline con pilotos o simulacros")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--rotulo", default="", help="texto en la esquina de cada figura")
    a = ap.parse_args()
    if a.datos:
        mapa = {k: [v] for k, v in con.sesiones(a.datos).items()}
    else:
        mapa = {}
        for x in a.ficticio:
            b, d, cs = x.split(":", 2)
            mapa[(int(b), d)] = cs.split(",")
    if not mapa:
        ap.error("sin sesiones: --datos o --ficticio")
    ejecutar(mapa, a.salida, a.incluir_no_validas, a.rotulo)


if __name__ == "__main__":
    sys.exit(main())
