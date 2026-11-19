"""Veredicto del diagnóstico del desfase (E6, capa 3) con la regla fijada antes del jueves 19.

  python3 -m analysis.diagnostico --datos data/diagnostico/<fecha> --salida analysis/salidas/<fecha>_diagnostico
  python3 -m analysis.diagnostico --autotest

Regla (plan de la Etapa 4, E6): en la fase abab de cada factor,
- mueve el nivel si |B − A| ≥ 0,3 W en ambos pares, con |A1 − A2| ≤ 0,05 W y |B1 − B2| ≤ 0,05 W;
- se descarta si |B − A| < 0,1 W en ambos pares;
- en otro caso, no concluyente.
Si varios mueven el nivel, se elige el de mayor |B − A| medio. Si hubo confirmación de ese factor, su dispersión entre
construcciones debe ser menor o igual a la de la reconstrucción sin factor. La decisión final es del usuario.

Prueba de fclk (fijada el 19-nov antes de medir, después de ver los tres niveles del 18-nov): con los ciclos y la
reconstrucción sin factor (A) y con fclk en B (relojes del SoC fijos):
- si el rango de las medias de condición en A es < 0,3 W, no hubo desfase que explicar: no concluyente;
- si en A es ≥ 0,3 W y en B es ≤ 0,1 W, fclk fija el nivel (se propone fijarlo en el modo medición);
- en otro caso, fclk no fija el nivel.
Además se informa si el nivel de fclk acompaña a los cambios de nivel en A (descriptivo, no decide).
"""
import argparse, csv, glob, json, os, statistics, sys

MUEVE_W, DESCARTA_W, IGUALES_W = 0.3, 0.1, 0.05


def media(xs):
    return round(statistics.fmean(xs), 4) if xs else None


def condiciones(archivos):
    """Una fila por (archivo, condición) con la media y la dispersión de sus ventanas."""
    filas = []
    for f in archivos:
        d = json.load(open(f))
        for c in d["condiciones"]:
            w = [v["potencia_media_W"] for v in c["ventanas"]]
            fc = {}
            for v in c["ventanas"]:  # fracción media de tiempo en cada nivel de fclk (si se registró)
                for nivel, fr in (((v.get("muestreo") or {}).get("fase_estable") or {}).get("fclk_mhz") or {}).items():
                    fc[nivel] = fc.get(nivel, 0) + fr / len(c["ventanas"])
            modal = max(fc, key=fc.get) if fc else None
            filas.append({"fclk_modal_mhz": modal, "fclk_frac_modal": round(fc[modal], 3) if modal else None,
                          "archivo": os.path.basename(f), "fase": d["fase"], "factor": d.get("factor") or "",
                          "condicion": c["condicion"], "n": len(w), "media_W": media(w),
                          "sd_W": round(statistics.stdev(w), 4) if len(w) > 1 else None,
                          "min_W": min(w, default=None), "max_W": max(w, default=None), "abortada": d.get("abortada") or ""})
    return filas


def regla(a1, b1, a2, b2):
    d1, d2 = abs(b1 - a1), abs(b2 - a2)
    if d1 >= MUEVE_W and d2 >= MUEVE_W and abs(a1 - a2) <= IGUALES_W and abs(b1 - b2) <= IGUALES_W:
        return "mueve el nivel"
    if d1 < DESCARTA_W and d2 < DESCARTA_W:
        return "descartado"
    return "no concluyente"


def dispersion(filas, fase, factor=""):
    """Rango y desviación de las medias por construcción (condiciones cicloN) del último archivo de esa fase."""
    arch = sorted({f["archivo"] for f in filas if f["fase"] == fase and f["factor"] == factor})
    if not arch:
        return None
    m = [f["media_W"] for f in filas if f["archivo"] == arch[-1] and f["condicion"].startswith("ciclo") and f["n"]]
    if len(m) < 2:
        return None
    return {"archivo": arch[-1], "construcciones": len(m), "rango_W": round(max(m) - min(m), 4), "sd_W": round(statistics.stdev(m), 4)}


def veredictos(filas):
    """Un veredicto por factor con el último archivo abab completo (A1, B1, A2, B2) de ese factor."""
    out = []
    for factor in sorted({f["factor"] for f in filas if f["fase"] == "abab"}):
        arch = sorted({f["archivo"] for f in filas if f["fase"] == "abab" and f["factor"] == factor})
        v = {"factor": factor, "archivo": arch[-1], "veredicto": "incompleto"}
        for a in reversed(arch):
            m = {f["condicion"]: f["media_W"] for f in filas if f["archivo"] == a and f["n"]}
            if all(k in m for k in ("A1", "B1", "A2", "B2")):
                v = {"factor": factor, "archivo": a, **{k: m[k] for k in ("A1", "B1", "A2", "B2")},
                     "dif_par1_W": round(m["B1"] - m["A1"], 4), "dif_par2_W": round(m["B2"] - m["A2"], 4),
                     "dif_media_abs_W": round((abs(m["B1"] - m["A1"]) + abs(m["B2"] - m["A2"])) / 2, 4),
                     "veredicto": regla(m["A1"], m["B1"], m["A2"], m["B2"])}
                break
        out.append(v)
    return out


def decision(ver, filas):
    mueven = sorted((v for v in ver if v["veredicto"] == "mueve el nivel"), key=lambda v: -v["dif_media_abs_W"])
    if not mueven:
        return {"factor": None, "texto": "ningún factor cumple la regla: la causa queda no resuelta y la campaña sigue sin cambios"}
    f = mueven[0]["factor"]
    base, conf = dispersion(filas, "reconstruccion"), dispersion(filas, "confirmacion", f)
    r = {"factor": f, "dif_media_abs_W": mueven[0]["dif_media_abs_W"], "otros_que_mueven": [v["factor"] for v in mueven[1:]],
         "dispersion_reconstruccion": base, "dispersion_confirmacion": conf}
    if conf and base:
        ok = conf["rango_W"] <= base["rango_W"]
        r["confirmacion"] = "cumple" if ok else "no cumple"
        r["texto"] = f"candidato {f}; confirmación {'cumple' if ok else 'NO cumple'} (rango {conf['rango_W']} W vs {base['rango_W']} W sin factor)"
    else:
        r["confirmacion"] = "sin confirmación"
        r["texto"] = f"candidato {f}; sin confirmación comparable"
    return r


def prueba_fclk(filas):
    """Regla de la prueba de fclk (docstring del módulo) con las condiciones de ciclos, reconstrucción y confirmación."""
    sel = lambda fac, fases: [f for f in filas if f["factor"] == fac and f["fase"] in fases and f["n"] and f["media_W"] is not None]
    a, b = sel("", ("ciclos", "reconstruccion")), sel("fclk", ("ciclos", "confirmacion"))
    if not a or not b:
        return None
    rango = lambda xs: round(max(x["media_W"] for x in xs) - min(x["media_W"] for x in xs), 4)
    ra, rb = rango(a), rango(b)
    v = "no concluyente: sin desfase en A" if ra < MUEVE_W else ("fclk fija el nivel" if rb <= DESCARTA_W else "fclk no fija el nivel")
    pares = [(x, y) for i, x in enumerate(a) for y in a[i + 1:] if abs(x["media_W"] - y["media_W"]) >= MUEVE_W]
    acompana = None if not pares or any(x["fclk_modal_mhz"] is None for x in a) else all(
        x["fclk_modal_mhz"] != y["fclk_modal_mhz"] or abs(x["fclk_frac_modal"] - y["fclk_frac_modal"]) >= 0.2 for x, y in pares)
    return {"rango_A_W": ra, "rango_B_W": rb, "condiciones_A": len(a), "condiciones_B": len(b), "veredicto": v,
            "fclk_acompana_los_niveles": acompana}


def escribir(ruta, filas):
    if not filas:
        return
    claves = list(dict.fromkeys(k for f in filas for k in f))
    with open(ruta, "w", newline="") as fh:
        w = csv.DictWriter(fh, claves)
        w.writeheader()
        w.writerows(filas)


def autotest():
    assert regla(5.0, 5.4, 5.02, 5.41) == "mueve el nivel"
    assert regla(5.0, 5.4, 5.1, 5.41) == "no concluyente"  # A1 y A2 difieren más de 0,05 W
    assert regla(5.0, 5.05, 5.0, 4.95) == "descartado"
    assert regla(5.0, 5.2, 5.0, 5.2) == "no concluyente"
    fila = lambda a, fase, fac, c, w: {"archivo": a, "fase": fase, "factor": fac, "condicion": c, "n": 3, "media_W": w}
    filas = [fila("abab_ksm", "abab", "ksm", c, w) for c, w in (("A1", 5.0), ("B1", 4.6), ("A2", 5.01), ("B2", 4.62))]
    filas += [fila("abab_cst", "abab", "cstates", c, w) for c, w in (("A1", 5.0), ("B1", 5.5), ("A2", 5.0), ("B2", 5.52))]
    filas += [fila("abab_hp", "abab", "haltpoll", c, w) for c, w in (("A1", 5.0), ("B1", 5.02))]
    filas += [fila("rec", "reconstruccion", "", c, w) for c, w in (("ciclo1", 5.0), ("ciclo2", 5.9))]
    filas += [fila("conf", "confirmacion", "cstates", c, w) for c, w in (("ciclo1", 5.5), ("ciclo2", 5.6))]
    ver = {v["factor"]: v for v in veredictos(filas)}
    assert ver["ksm"]["veredicto"] == ver["cstates"]["veredicto"] == "mueve el nivel" and ver["haltpoll"]["veredicto"] == "incompleto"
    d = decision(list(ver.values()), filas)
    assert d["factor"] == "cstates" and d["otros_que_mueven"] == ["ksm"] and d["confirmacion"] == "cumple"
    assert decision([ver["haltpoll"]], filas)["factor"] is None
    fc = lambda a, fase, fac, c, w, m, fr: dict(fila(a, fase, fac, c, w), fclk_modal_mhz=m, fclk_frac_modal=fr)
    pf = [fc("cic", "ciclos", "", "base", 4.9, "800", 1.0), fc("cic", "ciclos", "", "ciclo1", 4.1, "400", 0.9),
          fc("rec", "reconstruccion", "", "ciclo1", 5.8, "1200", 1.0),
          fc("cicB", "ciclos", "fclk", "base", 6.0, "1333", 1.0), fc("conf", "confirmacion", "fclk", "ciclo1", 6.05, "1333", 1.0)]
    r = prueba_fclk(pf)
    assert r["veredicto"] == "fclk fija el nivel" and r["fclk_acompana_los_niveles"] is True, r
    pf[-1]["media_W"] = 6.5
    assert prueba_fclk(pf)["veredicto"] == "fclk no fija el nivel"
    assert prueba_fclk(pf[:3]) is None
    print("autotest ok")


def main():
    if "--autotest" in sys.argv:
        return autotest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", required=True, help="data/diagnostico/<fecha>")
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()
    archivos = sorted(f for f in glob.glob(os.path.join(a.datos, "*.json")))
    filas = condiciones(archivos)
    ver = veredictos(filas)
    dec = decision(ver, filas)
    pf = prueba_fclk(filas)
    if pf:
        dec["prueba_fclk"] = pf
    os.makedirs(a.salida, exist_ok=True)
    escribir(os.path.join(a.salida, "condiciones.csv"), filas)
    escribir(os.path.join(a.salida, "veredictos.csv"), ver)
    json.dump(dec, open(os.path.join(a.salida, "decision.json"), "w"), indent=1, ensure_ascii=False)
    for f in filas:
        print(f"{f['fase']:14} {f['factor']:11} {f['condicion']:10} n={f['n']} {f['media_W']} W (sd {f['sd_W']})")
    for v in ver:
        print(f"{v['factor']:11} {v['veredicto']:15} {v.get('dif_par1_W', '')} {v.get('dif_par2_W', '')}")
    print(dec["texto"])
    if pf:
        print(f"prueba fclk: {pf['veredicto']} (rango A {pf['rango_A_W']} W, B {pf['rango_B_W']} W; fclk acompaña: {pf['fclk_acompana_los_niveles']})")


if __name__ == "__main__":
    sys.exit(main())
