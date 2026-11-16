"""Consolidación de la campaña (T-24.3, T-26.1): tablas por corrida, por tramo y por celda, y anomalías.

Lee <datos>/bNN_<dist>/ (y bNNr_<dist> del día de reserva, que reemplaza al bloque NN completo). Ignora las sesiones
apartadas por una interrupción (`*_interrumpido_*`).
"""
import glob, json, os, re, statistics

from analysis.recursos_latencia import cargar_gz, leer_corrida
from k6.lib import fallo
from k6.lib.comun import RAIZ

PATRON = re.compile(r"^(?:piloto_)?b(\d\d)(r?)_(k3s|microk8s)$")
UMBRAL_SCAPH_PCT = 10  # diferencia Scaphandre vs RAPL que se anota como anomalía; propio
ESCENARIOS = ("idle", "media", "alta")


def sesiones(datos):
    """{(bloque, dist): carpeta}; si existe la sesión de reserva del bloque, reemplaza a la original."""
    out, reserva = {}, set()
    for d in sorted(glob.glob(os.path.join(datos, "*"))):
        m = PATRON.match(os.path.basename(d))
        if not m or not os.path.isdir(d):
            continue
        clave = (int(m.group(1)), m.group(3))
        if m.group(2):
            reserva.add(int(m.group(1)))
            out[clave] = d
        elif int(m.group(1)) not in reserva:
            out.setdefault(clave, d)
    return {k: v for k, v in out.items() if not (k[0] in reserva and not PATRON.match(os.path.basename(v)).group(2))}


def scaphandre_W(ventana, t0, t1):
    """Potencia de Scaphandre en [t0, t1] con scaph_host_energy_microjoules: se descarta el intervalo con salto
    negativo (desbordamiento del contador) y se divide la energía de los intervalos restantes por su duración."""
    for s in (x for r in cargar_gz(ventana)["resultado"].values() for x in r):
        if s["metric"]["__name__"] == "scaph_host_energy_microjoules":
            pts = [(float(t), float(v)) for t, v in s["values"] if t0 <= float(t) <= t1]
            e = dt = 0.0
            saltos = 0
            for (ta, va), (tb, vb) in zip(pts, pts[1:]):
                if vb < va:
                    saltos += 1
                    continue
                e, dt = e + vb - va, dt + tb - ta
            return (round(e / 1e6 / dt, 3) if dt else None), saltos
    return None, 0


def corrida(meta_ruta, bloque, jornada, cache):
    m = json.load(open(meta_ruta))
    f = leer_corrida(meta_ruta, cache)
    t0, t1 = m["t_inicio"], m["t_fin"]
    mu = ((m.get("muestreo_host") or {}).get("resumen") or {})
    fe = mu.get("fase_estable") or {}
    sol = f.get("ve_solicitudes")
    completadas = None if sol is None else sol - (f.get("ve_fallidas") or 0)
    energia = m["rapl"].get("delta_uj", 0) / 1e6
    ventana = os.path.join(RAIZ, m["ventana_prometheus"]["archivo"]) if m.get("ventana_prometheus") else None
    sc, saltos = scaphandre_W(ventana, t0, t1) if ventana and os.path.exists(ventana) else (None, 0)
    rss = [f.get(f"rss_vm{i}_mb") for i in (1, 2, 3)]
    f |= {"bloque": bloque, "jornada": jornada, "fallo": bool(m.get("fallo")), "estado": m.get("estado"),
          "valida_para_campana": m.get("valida_para_campana"), "motivos": "; ".join(m.get("motivos_no_valida", [])),
          "energia_J": round(energia, 3), "duracion_s": round(t1 - t0, 3), "desbordamiento_rapl": m["rapl"].get("desbordamiento"),
          "j_por_solicitud": round(energia / completadas, 6) if completadas else None,
          "memoria_bajo_umbral": m.get("memoria_bajo_umbral"), "memavailable_min_host_mb": fe.get("memavailable_min_mb"),
          "swap_paginas": None if fe.get("pswpin_paginas") is None else fe["pswpin_paginas"] + fe["pswpout_paginas"],
          "temperatura_media_C": fe.get("temperatura_media_C"), "frecuencia_media_mhz": fe.get("frecuencia_media_mhz"),
          "rss_qemu_total_mb": round(sum(rss), 1) if None not in rss else None,
          "scaphandre_W": sc, "scaphandre_saltos": saltos,
          "titulares_cambiaron": (m.get("titulares") or {}).get("cambiaron")}
    if m.get("fallo") and "analisis" in m["fallo"]:
        fa = m["fallo"]
        f |= fallo.tiempos(fa["analisis"], fa["nodo_fallado"], (fa.get("eventos") or {}).get("t_restaura"))
    return f


def _media(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.fmean(xs), 1) if xs else None


def tramo(carpeta, bloque, dist, corridas_tramo):
    t = json.load(open(os.path.join(carpeta, "tramo.json")))
    ctx = t.get("contexto", {})
    c = (t.get("construccion") or [{}])[-1]
    cons = c.get("construccion") or {}
    al = t.get("almacenamiento") or {}
    nodos = [n for n in (al.get("nodos") or {}).values() if "error" not in n]

    def dirs(patrones):
        """Suma por nodo de los directorios de esos patrones (exactos, o prefijo si terminan en *); None si ninguno existe."""
        def coincide(k):
            return any(k == p or (p.endswith("*") and k.startswith(p[:-1])) for p in patrones)
        por_nodo = [[v for k, v in n["directorios"].items() if isinstance(v, int) and coincide(k)] for n in nodos]
        return _media([sum(v) for v in por_nodo if v])
    from k6.medicion.tramo import DIRECTORIOS
    cont = DIRECTORIOS[dist]["containerd"]
    dist_dirs = [p for p in DIRECTORIOS[dist]["distribucion"]]
    escrito = [sum(i["bytes_por_nodo"].values()) / max(1, len(i["bytes_por_nodo"]))
               for i in (al.get("escrito_disco_idle") or {}).values() if "bytes_por_nodo" in i]
    idle = [x["potencia_W"] for x in corridas_tramo if x["escenario"] == "idle" and not x["fallo"] and x["incluida"]]
    ref = (t.get("referencia") or {})
    ref_w = ref.get("potencia_media_W") if ref.get("ok") else None
    rtt = (t.get("rtt") or {}).get("host") or {}
    return {"bloque": bloque, "distribucion": dist, "jornada": ctx.get("jornada"), "sesion": os.path.relpath(carpeta, RAIZ),
            "ciclo": ctx.get("ciclo_despliegue"), "referencia_W": ref_w, "referencia_ok": ref.get("ok"),
            "construccion_intentos": len([x for x in t.get("construccion", []) if "intento" in x]),
            "construccion_s": (cons.get("registro") or {}).get("duracion_total_s"),
            "construccion_J": (cons.get("rapl") or {}).get("energia_J"),
            "construccion_desbordamiento": (cons.get("rapl") or {}).get("desbordamiento"),
            "construccion_wifi_rx_bytes": sum(v["rx"] for k, v in ((cons.get("red") or {}).get("delta") or {}).items() if k.startswith("wl")),
            "verificacion_intentos": (c.get("verificacion") or {}).get("intentos"),
            "idle_media_W": round(statistics.fmean(idle), 3) if idle else None,
            "sobrecosto_reposo_W": round(statistics.fmean(idle) - ref_w, 3) if idle and ref_w is not None else None,
            "rtt_vip_servicio_ms": (rtt.get("vip_servicio") or {}).get("media_ms"),
            "rtt_vip_plano_control_ms": (rtt.get("vip_plano_control") or {}).get("media_ms"),
            "almacenamiento_distribucion_bytes": dirs(dist_dirs), "almacenamiento_containerd_bytes": dirs(cont),
            "df_usado_bytes": _media([(n.get("df_raiz") or {}).get("usado_bytes") for n in nodos]),
            "imagenes": _media([n.get("imagenes") for n in nodos]), "contenido_imagenes_bytes": _media([n.get("contenido_bytes") for n in nodos]),
            "qcow2_total_bytes": sum(v.get("asignado_bytes_libvirt") or 0 for v in (al.get("qcow2") or {}).values()) or None,
            "escrito_idle_bytes_por_nodo": _media(escrito)}


def celdas(filas, metricas):
    """Promedio de las corridas incluidas de cada celda (bloque × distribución × escenario)."""
    out = {}
    for f in filas:
        if f["incluida"] and not f["fallo"]:
            out.setdefault((f["bloque"], f["distribucion"], f["escenario"]), []).append(f)
    tabla = []
    for (b, d, e), fs in sorted(out.items()):
        fila = {"bloque": b, "distribucion": d, "escenario": e, "n_corridas": len(fs)}
        for m in metricas:
            v = [x[m] for x in fs if isinstance(x.get(m), (int, float))]
            fila[m] = round(statistics.fmean(v), 6) if v else None
        tabla.append(fila)
    return tabla


def anomalias(corridas_, tramos_, celdas_):
    """Una fila por anomalía, con la regla que la detectó. Ninguna excluye por sí misma salvo las de procedimiento."""
    a = []
    for f in corridas_:
        id_ = {"bloque": f["bloque"], "distribucion": f["distribucion"], "base": f["base"]}
        if f["estado"] == "abortada_memoria":
            a.append({**id_, "regla": "E3.3 MemAvailable < 512 MB", "detalle": "corrida abortada; resultado de la distribución"})
        elif not f["incluida"]:
            a.append({**id_, "regla": "E5.4 falla del procedimiento", "detalle": f["motivos"]})
        if f["memoria_bajo_umbral"]:
            a.append({**id_, "regla": "E3.3 MemAvailable < 1024 MB", "detalle": f"mínimo {f['memavailable_min_host_mb']} MB; no excluye"})
        if f["swap_paginas"]:
            a.append({**id_, "regla": "swap en la fase estable", "detalle": f"{f['swap_paginas']} páginas; covariable"})
        if f["desbordamiento_rapl"]:
            a.append({**id_, "regla": "desbordamiento de RAPL", "detalle": "corregido con max_energy_range_uj"})
        if f["scaphandre_saltos"]:
            a.append({**id_, "regla": "desbordamiento de Scaphandre", "detalle": f"{f['scaphandre_saltos']} intervalo(s) descartado(s)"})
        if f["scaphandre_W"] and f["potencia_W"] and abs(f["scaphandre_W"] / f["potencia_W"] - 1) * 100 > UMBRAL_SCAPH_PCT:
            a.append({**id_, "regla": f"Scaphandre difiere de RAPL > {UMBRAL_SCAPH_PCT} %", "detalle": f"{f['scaphandre_W']} vs {f['potencia_W']} W"})
        if f["titulares_cambiaron"] and not f["fallo"]:
            a.append({**id_, "regla": "titular de una VIP cambió sin fallo", "detalle": ""})
        if not f["fallo"] and ((f.get("ve_fallidas") or 0) or (f.get("ve_descartadas") or 0)):
            a.append({**id_, "regla": "fallidas o descartadas en la fase estable", "detalle":
                      f"fallidas {f.get('ve_fallidas')}, descartadas {f.get('ve_descartadas')}; resultado, no excluye"})
    for t in tramos_:
        id_ = {"bloque": t["bloque"], "distribucion": t["distribucion"], "base": "tramo"}
        if not t["referencia_ok"]:
            a.append({**id_, "regla": "ventana de referencia no válida", "detalle": "sin sobrecosto en reposo para este tramo"})
        if t["construccion_intentos"] > 1:
            a.append({**id_, "regla": "construcción reintentada", "detalle": f"{t['construccion_intentos']} intentos"})
        if t["construccion_desbordamiento"]:
            a.append({**id_, "regla": "desbordamiento de RAPL en la construcción", "detalle": "corregido"})
    for c in celdas_:
        if c["n_corridas"] < 2:
            a.append({"bloque": c["bloque"], "distribucion": c["distribucion"], "base": c["escenario"],
                      "regla": "celda con una sola corrida", "detalle": "E5.4: la repetición también fue no válida o hubo aborto"})
    return a


def consolidar(mapa, incluir_no_validas=False, cache=None):
    """mapa: {(bloque, dist): [carpetas]} (sesiones() da una carpeta por tramo; las pruebas del pipeline pueden juntar
    varias). Devuelve (corridas, tramos). incluir_no_validas: solo para probar el pipeline con pilotos o simulacros."""
    cache = {} if cache is None else cache
    filas, tramos_ = [], []
    for (b, d), carpetas in sorted(mapa.items()):
        carpeta = carpetas[0]
        t = json.load(open(os.path.join(carpeta, "tramo.json"))) if os.path.exists(os.path.join(carpeta, "tramo.json")) else {}
        jornada = (t.get("contexto") or {}).get("jornada")
        ct = []
        for meta in sorted(m for c in carpetas for m in glob.glob(os.path.join(c, "metadatos", "*.json"))):
            if meta.endswith((".observador.json", ".muestreo.json")):
                continue
            f = corrida(meta, b, jornada, cache)
            f["incluida"] = f["estado"] != "abortada_memoria" and (bool(f["valida_para_campana"]) or incluir_no_validas)
            ct.append(f)
        filas += ct
        if t:
            tramos_.append(tramo(carpeta, b, d, ct))
    return filas, tramos_


def autotest():
    import tempfile
    r = tempfile.mkdtemp()
    for n in ("b01_k3s", "b01_microk8s", "b03_k3s", "b03r_k3s", "b03r_microk8s", "b02_k3s_interrumpido_20261121T1000", "diario"):
        os.makedirs(os.path.join(r, n))
    s = sesiones(r)
    assert sorted(s) == [(1, "k3s"), (1, "microk8s"), (3, "k3s"), (3, "microk8s")] and s[(3, "k3s")].endswith("b03r_k3s")
    fs = [{"incluida": True, "fallo": False, "bloque": 1, "distribucion": "k3s", "escenario": "idle", "potencia_W": w} for w in (5.0, 5.2)]
    fs.append({"incluida": False, "fallo": False, "bloque": 1, "distribucion": "k3s", "escenario": "idle", "potencia_W": 9.0})
    c = celdas(fs, ["potencia_W"])
    assert c == [{"bloque": 1, "distribucion": "k3s", "escenario": "idle", "n_corridas": 2, "potencia_W": 5.1}]
    print("autotest ok")


if __name__ == "__main__":
    autotest()
