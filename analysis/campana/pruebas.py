"""Pruebas pre-registradas (plan-campana-v1, sección 6) sobre diferencias pareadas por bloque (MicroK8s − K3s)."""
import math

import numpy as np
from scipy import stats

ALFA = 0.05
MARGEN_EQUIV = math.log(1.05)  # ±5 % sobre el logaritmo de la razón


def distribucion_rangos(n):
    """Cuentas exactas del estadístico de rangos con signo T+ para n pares sin empates: c[t] = número de signos con T+ = t."""
    c = [1] + [0] * (n * (n + 1) // 2)
    for k in range(1, n + 1):
        for t in range(len(c) - 1, k - 1, -1):
            c[t] += c[t - k]
    return c


def wilcoxon(d):
    """Wilcoxon de rangos con signo, exacto y bilateral. Con ceros o empates, scipy usa la aproximación normal (se informa)."""
    d = np.asarray(d, float)
    exacto = bool(np.all(d != 0) and len(set(np.abs(d))) == len(d))
    r = stats.wilcoxon(d, alternative="two-sided", method="exact" if exacto else "approx")
    return {"estadistico": float(r.statistic), "p": float(r.pvalue), "metodo": "exacto" if exacto else "normal (ceros o empates)"}


def t_pareada(d):
    d = np.asarray(d, float)
    r = stats.ttest_1samp(d, 0.0)
    ic = stats.t.interval(0.95, len(d) - 1, loc=d.mean(), scale=stats.sem(d)) if len(d) > 1 else (None, None)
    return {"media": float(d.mean()), "t": float(r.statistic), "p": float(r.pvalue), "ic95": [float(ic[0]), float(ic[1])]}


def hodges_lehmann(d, confianza=0.95):
    """Estimador de Hodges–Lehmann (mediana de los promedios de Walsh) con el intervalo exacto de nivel alcanzado
    más cercano a `confianza` (con n = 8 los niveles son discretos; el nivel alcanzado se informa)."""
    d = np.asarray(d, float)
    n = len(d)
    w = np.sort([(d[i] + d[j]) / 2 for i in range(n) for j in range(i, n)])
    c = distribucion_rangos(n)
    total, acum, mejor = 2 ** n, 0, None
    for k in range(1, len(w) // 2 + 1):  # intervalo [w_(k), w_(N-k+1)] (índices desde 1): nivel = 1 - 2 P(T+ <= k-1)
        acum += c[k - 1]
        nivel = 1 - 2 * acum / total
        if mejor is None or abs(nivel - confianza) < abs(mejor[1] - confianza):
            mejor = (k, nivel)
    k, nivel = mejor
    return {"estimador": float(np.median(w)), "ic": [float(w[k - 1]), float(w[len(w) - k])], "nivel_alcanzado": round(nivel, 4)}


def holm(ps):
    """p ajustados de Holm, en el mismo orden de entrada."""
    m = len(ps)
    orden = sorted(range(m), key=lambda i: ps[i])
    aj, maximo = [0.0] * m, 0.0
    for r, i in enumerate(orden):
        maximo = max(maximo, min(1.0, (m - r) * ps[i]))
        aj[i] = maximo
    return aj


def tost_log(p_micro, p_k3s, margen=MARGEN_EQUIV, alfa=ALFA):
    """TOST pareado sobre ln(P_MicroK8s / P_K3s) por bloque, con intervalo al 1 − 2α (90 %) y robustez con Hodges–Lehmann."""
    x = np.log(np.asarray(p_micro, float) / np.asarray(p_k3s, float))
    n, m, se = len(x), x.mean(), stats.sem(x)
    p_inf = 1 - stats.t.cdf((m + margen) / se, n - 1)  # H0: media <= -margen
    p_sup = stats.t.cdf((m - margen) / se, n - 1)  # H0: media >= +margen
    ic = stats.t.interval(1 - 2 * alfa, n - 1, loc=m, scale=se)
    hl = hodges_lehmann(x, 1 - 2 * alfa)
    return {"media_log": float(m), "razon": float(math.exp(m)), "ic90_log": [float(ic[0]), float(ic[1])],
            "ic90_razon": [math.exp(ic[0]), math.exp(ic[1])], "p_tost": float(max(p_inf, p_sup)),
            "equivalente": bool(ic[0] > -margen and ic[1] < margen), "margen_log": margen,
            "hl_log": hl, "hl_equivalente": bool(hl["ic"][0] > -margen and hl["ic"][1] < margen)}


def comparar(pares, metricas, alfa=ALFA):
    """Familia de pruebas pareadas. pares: {métrica: (valores_k3s, valores_microk8s)} alineados por bloque.
    Devuelve una fila por métrica con Wilcoxon (p y p de Holm en la familia), t pareada y Hodges–Lehmann."""
    filas = []
    for met in metricas:
        k, m = (np.asarray(v, float) for v in pares[met])
        ok = ~(np.isnan(k) | np.isnan(m))
        d = m[ok] - k[ok]
        f = {"metrica": met, "n_bloques": int(ok.sum()), "media_k3s": float(k[ok].mean()) if ok.any() else None,
             "media_microk8s": float(m[ok].mean()) if ok.any() else None}
        if ok.sum() >= 2 and np.any(d != 0):
            w, t, hl = wilcoxon(d), t_pareada(d), hodges_lehmann(d)
            f |= {"dif_media": t["media"], "wilcoxon_p": w["p"], "wilcoxon_metodo": w["metodo"], "t_p": t["p"],
                  "t_ic95": t["ic95"], "hl": hl["estimador"], "hl_ic": hl["ic"], "hl_nivel": hl["nivel_alcanzado"]}
        else:
            f |= {"dif_media": float(d.mean()) if len(d) else None, "wilcoxon_p": None, "wilcoxon_metodo": "sin datos o sin diferencias"}
        filas.append(f)
    validas = [f for f in filas if f["wilcoxon_p"] is not None]
    for f, p in zip(validas, holm([f["wilcoxon_p"] for f in validas])):
        f["wilcoxon_p_holm"], f["significativa"] = p, p < alfa
    return filas


def veredicto(fila_principal, tost):
    """Resultado de un escenario de la familia principal: diferencia detectada, equivalencia demostrada o inconcluso."""
    if fila_principal.get("significativa"):
        return "diferencia detectada" + (" (dentro del margen de equivalencia)" if tost["equivalente"] else "")
    return "equivalencia demostrada" if tost["equivalente"] else "inconcluso"


def autotest():
    assert sum(distribucion_rangos(8)) == 256 and distribucion_rangos(3) == [1, 1, 1, 2, 1, 1, 1]
    # p exacto mínimo con 8 bloques: 2/256 = 0,0078 (sección 6.3 del pre-registro)
    assert abs(wilcoxon([1, 2, 3, 4, 5, 6, 7, 8])["p"] - 2 / 256) < 1e-12
    assert holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    rng = np.random.default_rng(20261028)
    # efecto conocido: +0,20 W en MicroK8s con ruido de bloque común a ambas distribuciones
    bloque = rng.normal(0, 0.5, 8)
    k3s = 5 + bloque + rng.normal(0, 0.02, 8)
    mk = 5.2 + bloque + rng.normal(0, 0.02, 8)
    hl = hodges_lehmann(mk - k3s)
    assert abs(hl["estimador"] - 0.2) < 0.03 and hl["ic"][0] < 0.2 < hl["ic"][1] and 0.9 < hl["nivel_alcanzado"] < 0.99
    fam = comparar({"idle": (k3s, mk), "nulo": (k3s, k3s + rng.normal(0, 0.02, 8))}, ["idle", "nulo"])
    assert fam[0]["significativa"] and fam[0]["wilcoxon_p"] == 2 / 256 and not fam[1]["significativa"]
    # TOST: efecto nulo con dispersión pequeña concluye equivalencia; +20 % no
    assert tost_log(k3s * np.exp(rng.normal(0, 0.005, 8)), k3s)["equivalente"]
    t = tost_log(k3s * 1.2 * np.exp(rng.normal(0, 0.005, 8)), k3s)
    assert not t["equivalente"] and abs(t["razon"] - 1.2) < 0.01
    assert veredicto(fam[0], t) == "diferencia detectada" and veredicto({"significativa": False}, t) == "inconcluso"
    print("autotest ok")


if __name__ == "__main__":
    autotest()
