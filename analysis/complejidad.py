"""Complejidad operativa por distribución (E9.2): solo conteos reproducibles desde el repositorio.

  python3 -m analysis.complejidad [--salida analysis/salidas/<fecha>_complejidad]

1. Tareas de Ansible por rol (tareas de primer nivel de tasks/main.yml y handlers).
2. Líneas de IaC (Ansible, Terraform, cloud-init) comunes y específicas: se comparan los archivos de igual ruta en
   k3sHA/ y microk8sHA/, sin comentarios ni líneas vacías, con el nombre de la distribución normalizado.
3. Tareas y órdenes por nodo adicional: tareas del rol del servidor que solo corren fuera del nodo 1.
4. Restricciones operativas: patrones del código con su conteo.
"""
import argparse, csv, difflib, glob, os, re, sys

from k6.lib.comun import RAIZ

DIST = {"k3s": "k3sHA", "microk8s": "microk8sHA"}
SERVIDOR = {"k3s": "k3s_server", "microk8s": "microk8s_server"}
EXT = (".yml", ".yaml", ".j2", ".tf", ".tftpl", ".cfg")
MODULOS_ORDEN = ("command:", "shell:")
RESTRICCIONES = {  # nombre: regex sobre las líneas sin comentarios del rol del servidor y del playbook
    "uniones secuenciales (throttle)": r"^\s*throttle:\s*1",
    "retención de actualizaciones del snap": r"snap refresh --hold",
    "tareas con reintentos (retries)": r"^\s*retries:",
    "esperas de disponibilidad de la API": r"--wait-ready|^\s*wait_for:",
    "regeneración de certificados": r"refresh-certs",
    "reinicios de la distribución": r"snap restart|systemctl restart k3s",
    "servicio enmascarado o desactivado": r"dest: /etc/systemd/system/.*\.service|masked:",
    "token de unión por nodo": r"add-node",
}


def lineas(ruta, dist):
    """Líneas sin comentarios ni vacías, con el nombre de la distribución reemplazado por DIST."""
    out = []
    for x in open(ruta, encoding="utf-8"):
        x = x.rstrip()
        s = x.strip()
        if not s or s.startswith("#") or s.startswith("//") or s == "---":
            continue
        out.append(re.sub(r"microk8s|k3s", "DIST", x, flags=re.I) if dist else x)
    return out


def archivos(dist):
    base = os.path.join(RAIZ, DIST[dist])
    return {os.path.relpath(p, base): p for p in glob.glob(os.path.join(base, "**", "*"), recursive=True)
            if p.endswith(EXT) and os.path.isfile(p)}


def tareas(ruta):
    return sum(1 for x in open(ruta, encoding="utf-8") if x.startswith("- name:"))


def tabla_roles():
    filas = []
    for dist, d in DIST.items():
        for t in sorted(glob.glob(os.path.join(RAIZ, d, "ansible", "roles", "*", "tasks", "main.yml"))):
            rol = t.split(os.sep)[-3]
            h = os.path.join(os.path.dirname(os.path.dirname(t)), "handlers", "main.yml")
            filas.append({"distribucion": dist, "rol": rol, "especifico": rol == SERVIDOR[dist],
                          "tareas": tareas(t), "handlers": tareas(h) if os.path.exists(h) else 0})
    return filas


def tabla_lineas():
    a, b = archivos("k3s"), archivos("microk8s")
    filas = []
    for rel in sorted(set(a) | set(b)):
        la = lineas(a[rel], True) if rel in a else []
        lb = lineas(b[rel], True) if rel in b else []
        comunes = sum(bl.size for bl in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_matching_blocks())
        filas.append({"archivo": rel, "comunes": comunes, "especificas_k3s": len(la) - comunes,
                      "especificas_microk8s": len(lb) - comunes})
    return filas


def por_nodo_adicional(dist):
    """(tareas, órdenes) del rol del servidor con condición inventory_hostname != '<dist>-node1'."""
    ruta = os.path.join(RAIZ, DIST[dist], "ansible", "roles", SERVIDOR[dist], "tasks", "main.yml")
    bloques = re.split(r"(?m)^- name:", open(ruta, encoding="utf-8").read())[1:]
    sel = [b for b in bloques if re.search(rf"inventory_hostname != '{dist}-node1'", b)]
    return len(sel), sum(any(re.search(rf"(?m)^\s+{m}", b) for m in MODULOS_ORDEN) for b in sel)


def restricciones(dist):
    d = os.path.join(RAIZ, DIST[dist], "ansible")
    texto = [x for r in [os.path.join(d, "roles", SERVIDOR[dist], "tasks", "main.yml"), os.path.join(d, "playbook.yml")]
             for x in lineas(r, False)]
    return {n: sum(bool(re.search(p, x)) for x in texto) for n, p in RESTRICCIONES.items()}


def resumen():
    roles, lin = tabla_roles(), tabla_lineas()
    out = []
    for dist in DIST:
        r = [x for x in roles if x["distribucion"] == dist]
        t, o = por_nodo_adicional(dist)
        fila = {"distribucion": dist,
                "tareas_rol_servidor": sum(x["tareas"] + x["handlers"] for x in r if x["especifico"]),
                "tareas_totales": sum(x["tareas"] + x["handlers"] for x in r),
                "lineas_iac_comunes": sum(x["comunes"] for x in lin),
                "lineas_iac_especificas": sum(x[f"especificas_{dist}"] for x in lin),
                "tareas_por_nodo_adicional": t, "ordenes_por_nodo_adicional": o}
        fila |= {f"restriccion: {k}": v for k, v in restricciones(dist).items()}
        out.append(fila)
    return out, roles, lin


def autotest():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
        fh.write("---\n# c\n- name: a k3s\n  command: x\n\n- name: b\n  when: inventory_hostname != 'k3s-node1'\n")
    assert lineas(fh.name, True) == ["- name: a DIST", "  command: x", "- name: b", "  when: inventory_hostname != 'DIST-node1'"]
    assert tareas(fh.name) == 2
    os.unlink(fh.name)
    res, _, lin = resumen()
    assert {x["distribucion"] for x in res} == set(DIST) and all(x["lineas_iac_comunes"] > 0 for x in res)
    assert all(x["comunes"] + x["especificas_k3s"] >= 0 for x in lin)
    print("autotest ok")


def escribir(ruta, filas):
    with open(ruta, "w", newline="") as fh:
        w = csv.DictWriter(fh, list(filas[0]))
        w.writeheader()
        w.writerows(filas)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida")
    ap.add_argument("--autotest", action="store_true")
    a = ap.parse_args()
    if a.autotest:
        return autotest()
    res, roles, lin = resumen()
    for f in res:
        print(f["distribucion"])
        for k, v in f.items():
            if k != "distribucion":
                print(f"  {k}: {v}")
    if a.salida:
        os.makedirs(a.salida, exist_ok=True)
        for n, filas in (("complejidad", res), ("complejidad_roles", roles), ("complejidad_lineas", lin)):
            escribir(os.path.join(a.salida, n + ".csv"), filas)
            print("escrito", os.path.join(a.salida, n + ".csv"))


if __name__ == "__main__":
    sys.exit(main())
