"""Figuras del informe a partir de los CSV de `analysis.recursos_latencia` (no calcula nada nuevo, salvo cuantiles del histograma).

Uso (desde la raíz del repositorio; necesita matplotlib, ver analysis/requirements.txt):
  python3 -m analysis.figuras --recursos analysis/salidas/2026-11-02_pasada_definitiva/recursos_latencia.csv \
      --recuperacion analysis/salidas/2026-11-02_recuperacion/recuperacion.csv \
      --salida analysis/salidas/2026-11-02_figuras --rotulo "Preliminar, una sesión"
  python3 -m analysis.figuras --autotest

Cada CSV debe ser de una sola configuración. El espectro de latencia lee `cache_latencia.json` (mismo directorio que
`recursos_latencia.csv`, o `--cache`). PDF vectorial, 16 cm de ancho, texto de 8 pt, color por distribución (azul K3s,
naranja MicroK8s) y forma distinta (círculo, triángulo) para que también se distingan en impresión en blanco y negro.
"""
import argparse, csv, json, math, os, statistics, sys, tempfile

from analysis.recursos_latencia import comprobar_configuracion, cuantil_hist

DIST = ("k3s", "microk8s")
NOMBRE = {"k3s": "K3s", "microk8s": "MicroK8s"}
COL = {"k3s": "#2a78d6", "microk8s": "#eb6834"}
FORMA = {"k3s": "o", "microk8s": "^"}
TAM = {"k3s": 6.5, "microk8s": 7.5}
TINTA, TINTA2, TENUE, GUIA = "#1f2328", "#57606a", "#8c959f", "#e6e9ec"
ANCHO = 6.3  # pulgadas = 16,0 cm


def leer_csv(ruta):
    def v(x):
        if x == "":
            return None
        if x in ("True", "False"):
            return x == "True"
        try:
            return float(x)
        except ValueError:
            return x
    with open(ruta) as fh:
        return [{k: v(x) for k, x in r.items()} for r in csv.DictReader(fh)]


def _mpl():
    import matplotlib
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    from matplotlib import font_manager
    fuentes = {f.name for f in font_manager.fontManager.ttflist}
    familia = next((f for f in ("Liberation Sans", "DejaVu Sans") if f in fuentes), "sans-serif")
    plt.rcParams.update({
        "font.family": familia, "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "legend.fontsize": 8, "pdf.fonttype": 42, "text.color": TINTA, "axes.labelcolor": TINTA2,
        "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.edgecolor": "#c9ced3", "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "xtick.major.width": 0.8, "ytick.major.width": 0.8,
        "xtick.major.size": 3, "ytick.major.size": 3, "axes.facecolor": "white", "figure.facecolor": "white",
        "axes.axisbelow": True, "legend.frameon": False})
    halo = [pe.withStroke(linewidth=2.6, foreground="white")]
    return plt, halo


def _coma(x, n=1):
    return f"{x:.{n}f}".replace(".", ",")


def _fmt(plt):
    return plt.FuncFormatter(lambda v, _: f"{v:g}".replace(".", ","))


def _guardar(plt, fig, ruta, rotulo):
    if rotulo:
        fig.text(0.99, 0.995, rotulo, ha="right", va="top", fontsize=8, style="italic", color=TINTA2)
    fig.savefig(ruta)
    plt.close(fig)
    print("escrito", ruta)


def _col(filas, dist, esc, col):
    return [f[col] for f in filas if f["distribucion"] == dist and f["escenario"] == esc and f.get(col) is not None]


def _media(filas, dist, esc, col):
    v = _col(filas, dist, esc, col)
    return statistics.mean(v) if v else None


def _tasa(filas, esc):
    return next((f["tasa"] for f in filas if f["escenario"] == esc and f.get("tasa")), None)


def _leyenda_dist(plt, fig, **kw):
    h = [plt.Line2D([], [], ls="", marker=FORMA[d], ms=TAM[d], mfc=COL[d], mec="white", mew=0.8, label=NOMBRE[d]) for d in DIST]
    fig.legend(handles=h, ncol=2, columnspacing=1.6, handletextpad=0.3, **kw)


def _limpiar_x(ax):
    ax.grid(axis="x", color=GUIA, lw=0.6)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)


# ---------------------------------------------------------------------------------------------------------------- 1
def _separar(posiciones, minimo):
    """Reparte posiciones (puntos, de abajo hacia arriba) para que ninguna quede a menos de `minimo` de otra."""
    orden = sorted(range(len(posiciones)), key=lambda i: posiciones[i])
    out = list(posiciones)
    for a, b in zip(orden, orden[1:]):
        if out[b] - out[a] < minimo:
            mov = (minimo - (out[b] - out[a])) / 2
            out[a] -= mov
            out[b] += mov
    return out


def fig_energia_latencia(filas, ruta, rotulo):
    """Potencia frente a p95 de la fase estable: un punto por repetición y una flecha de `media` a `alta` en cada distribución."""
    plt, halo = _mpl()
    fig, ax = plt.subplots(figsize=(ANCHO, 4.1))
    fig.subplots_adjust(left=0.09, right=0.84, bottom=0.17, top=0.9)
    tasa = {e: _tasa(filas, e) for e in ("media", "alta")}
    m, ys = {}, []
    for d in DIST:
        m[d] = {}
        for e in ("media", "alta"):
            x, y = _col(filas, d, e, "ve_p95_ms"), _col(filas, d, e, "potencia_W")
            ax.plot(x, y, ls="", marker=FORMA[d], ms=TAM[d], mfc=COL[d], mec="white", mew=0.9, alpha=0.95, zorder=4)
            m[d][e] = (statistics.mean(x), statistics.mean(y))
            ys += y
        ax.annotate("", xy=m[d]["alta"], xytext=m[d]["media"], zorder=3,
                    arrowprops=dict(arrowstyle="-|>", color=COL[d], lw=1.6, shrinkA=9, shrinkB=10, mutation_scale=11))
        ax.annotate(f"{NOMBRE[d]} · alta · {_coma(tasa['alta'], 0)} rps", m[d]["alta"], xytext=(0, 11), textcoords="offset points",
                    ha="center", va="bottom", color=TINTA, fontweight="bold", path_effects=halo, zorder=5)
    idle = {d: _media(filas, d, "idle", "potencia_W") for d in DIST}
    ys += [v for v in idle.values() if v is not None]
    ax.set_xscale("log")
    ax.set_xlim(1.7, 130)
    ax.set_xticks([2, 5, 10, 20, 50, 100], ["2", "5", "10", "20", "50", "100"])
    ax.xaxis.set_minor_locator(plt.NullLocator())
    ax.set_ylim(min(ys) - 0.45, max(ys) + 0.7)
    fig.canvas.draw()
    pt = lambda xy: ax.transData.transform(xy) * 72 / fig.dpi  # posición en puntos
    # etiqueta del escenario media: una sola si los dos inicios casi coinciden
    ini = [m[d]["media"] for d in DIST]
    cerca = math.dist(pt(ini[0]), pt(ini[1])) < 22
    for d, p in ([(None, min(ini, key=lambda q: q[1]))] if cerca else [(d, m[d]["media"]) for d in DIST]):
        ax.annotate(f"media · {_coma(tasa['media'], 0)} rps", p, xytext=(10, -4), textcoords="offset points", ha="left", va="top",
                    color=TINTA, path_effects=halo, zorder=5)
    # líneas de reposo: etiquetas en el margen derecho, separadas entre sí
    vis = [d for d in DIST if idle[d] is not None]
    alto = ax.get_window_extent().height * 72 / fig.dpi
    ypt = [(idle[d] - ax.get_ylim()[0]) / (ax.get_ylim()[1] - ax.get_ylim()[0]) * alto for d in vis]
    sep = _separar(ypt, 26)
    for j, d in enumerate(vis):
        ax.axhline(idle[d], color=COL[d], lw=1.0, ls=(j * 3.5, (2, 5)) if len(vis) > 1 else (0, (2, 3)), zorder=2)
        ax.annotate(f"reposo {NOMBRE[d]}\n{_coma(idle[d], 2)} W", (1, idle[d]), xycoords=ax.get_yaxis_transform(),
                    xytext=(6, sep[j] - ypt[j]), textcoords="offset points", ha="left", va="center", color=TINTA2, annotation_clip=False)
    ax.yaxis.set_major_formatter(_fmt(plt))
    ax.set_xlabel("Latencia p95 de la fase estable (ms, escala logarítmica)")
    ax.set_ylabel("Potencia media del paquete (W)")
    ax.grid(color=GUIA, lw=0.6)
    _leyenda_dist(plt, fig, loc="upper left", bbox_to_anchor=(0.0, 1.0))
    fig.text(0.0, 0.0, "Un punto por repetición; la flecha va del escenario media al alta. La potencia solo es comparable dentro de una sesión.",
             fontsize=7.5, color=TINTA2, va="bottom")
    _guardar(plt, fig, ruta, rotulo)


# ---------------------------------------------------------------------------------------------------------------- 2
def fig_recursos(filas, ruta, rotulo):
    """CPU y RAM por escenario: un punto por repetición, rango mínimo a máximo y media escrita."""
    plt, halo = _mpl()
    paneles = [("cpu_host_pct", "CPU del host (%)", 1, 1), ("cpu_vm_media", "CPU de las VM (%)", 1, 1),
               ("ram_vm_media", "RAM usada por VM (MB)", 1, 0), ("ram_host_mb", "RAM usada del host (GB)", 1 / 1024, 1)]
    esc = ("idle", "media", "alta")
    etiqueta = [("reposo", None), ("media", _tasa(filas, "media")), ("alta", _tasa(filas, "alta"))]
    fig, axs = plt.subplots(2, 2, figsize=(ANCHO, 4.9), sharey=True)
    for ax, (col, tit, k, nd) in zip(axs.flat, paneles):
        top = max(f[col] * k for f in filas if f.get(col) is not None)
        for i, e in enumerate(esc):
            if i == 1:
                ax.axhspan(-i - 0.5, -i + 0.5, color="#f6f8fa", zorder=0)
            for d, dy in zip(DIST, (0.17, -0.17)):
                v = sorted(x * k for x in _col(filas, d, e, col))
                if not v:
                    continue
                y = -i + dy
                ax.plot([v[0], v[-1]], [y, y], color=COL[d], alpha=0.28, lw=6, solid_capstyle="round", zorder=2)
                ax.plot(v, [y] * len(v), ls="", marker=FORMA[d], ms=TAM[d] - 1, mfc=COL[d], mec="white", mew=0.7, zorder=4)
                ax.annotate(_coma(statistics.mean(v), nd), (v[-1], y), xytext=(8, 0), textcoords="offset points", va="center",
                            ha="left", color=TINTA2, fontsize=7.5, path_effects=halo, zorder=5)
        ax.set_title(tit, loc="left", fontsize=8.5, fontweight="bold", color=TINTA, pad=6)
        ax.set_xlim(0, top * 1.22)
        ax.set_ylim(-2.55, 0.55)
        ax.set_yticks([0, -1, -2], [e if r is None else f"{e}\n{_coma(r, 0)} rps" for e, r in etiqueta])
        _limpiar_x(ax)
        ax.xaxis.set_major_formatter(_fmt(plt))
    n = max((len(_col(filas, "k3s", "idle", "cpu_host_pct")), 1))
    _leyenda_dist(plt, fig, loc="upper left", bbox_to_anchor=(0.0, 1.0))
    fig.text(0.0, 0.0, f"Un punto por repetición (n = {n}); la barra une el mínimo y el máximo y el número es la media. Ejes desde cero.",
             fontsize=7.5, color=TINTA2, va="bottom")
    fig.subplots_adjust(left=0.12, right=0.98, bottom=0.08, top=0.87, hspace=0.34, wspace=0.08)
    _guardar(plt, fig, ruta, rotulo)


# ---------------------------------------------------------------------------------------------------------------- 3
def espectro(h, xs):
    """Latencia (ms) en cada x = log10(1/(1-p)) de un histograma de `recursos_latencia.histograma`."""
    return [cuantil_hist(h, 1 - 10 ** -x) if x > 0 else cuantil_hist(h, 0) for x in xs]


def fig_espectro(filas, cache, ruta, rotulo):
    """Espectro de percentiles (una línea por corrida) de la fase estable, escenarios media y alta."""
    plt, halo = _mpl()
    por_base = {}
    for clave, v in cache.items():
        if "hist" in v:
            por_base[clave.split("|")[0]] = v
    xs = [i / 40 for i in range(0, 157)]
    fig, axs = plt.subplots(1, 2, figsize=(ANCHO, 3.7), sharey=True)
    for ax, e in zip(axs, ("media", "alta")):
        desc = {d: [] for d in DIST}
        for f in filas:
            if f["escenario"] == e and f["base"] in por_base:
                d = f["distribucion"]
                ax.plot(xs, espectro(por_base[f["base"]]["hist"], xs), color=COL[d], lw=1.5, alpha=0.85, zorder=3)
                desc[d].append(f.get("ve_descartadas") or 0)
        for x, nombre in ((math.log10(20), "p95"), (2, "p99"), (3, "p99,9")):
            ax.axvline(x, color="#c9ced3", lw=0.8, ls=(0, (3, 3)), zorder=1)
            ax.text(x, 1.0, nombre, transform=ax.get_xaxis_transform(), ha="center", va="bottom", color=TINTA2, fontsize=7.5)
        ax.set_title(f"{e} · {_coma(_tasa(filas, e), 0)} rps", loc="left", fontsize=8.5, fontweight="bold", pad=15)
        ax.set_yscale("log")
        ax.set_xlim(0, 3.9)
        ax.set_xticks([0, 1, 2, 3], ["0", "90", "99", "99,9"])
        ax.set_xlabel("Percentil (%, la escala se estira hacia las colas)")
        ax.grid(axis="y", color=GUIA, lw=0.6)
        ax.set_ylim(1, 700)
        ax.set_yticks([1, 2, 5, 10, 20, 50, 100, 200, 500], ["1", "2", "5", "10", "20", "50", "100", "200", "500"])
        ax.yaxis.set_minor_locator(plt.NullLocator())
        if e == "alta" and all(desc.values()):
            ax.text(0.03, 0.97, "Descartadas por k6 (no medidas):\n" + "\n".join(
                f"{NOMBRE[d]}: {int(min(v))} a {int(max(v))}" for d, v in desc.items()), transform=ax.transAxes, va="top",
                ha="left", fontsize=7.5, color=TINTA2)
    axs[0].set_ylabel("Latencia (ms, escala logarítmica)")
    h = [plt.Line2D([], [], color=COL[d], lw=2, label=NOMBRE[d] + " (una línea por repetición)") for d in DIST]
    fig.legend(handles=h, ncol=2, loc="upper left", bbox_to_anchor=(0.0, 1.0), columnspacing=1.6)
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.14, top=0.78, wspace=0.06)
    _guardar(plt, fig, ruta, rotulo)


# ---------------------------------------------------------------------------------------------------------------- 4
def fig_memoria(filas, ruta, rotulo):
    """Composición de la memoria del host: RSS de cada VM de QEMU, otros usos y memoria disponible."""
    plt, halo = _mpl()
    cols = [f"rss_vm{i}_mb" for i in (1, 2, 3)]
    if not filas or any(c not in filas[0] for c in cols) or "memtotal_mb" not in filas[0]:
        print("sin columnas rss_vm*_mb en el CSV: omito la figura de memoria")
        return
    nombres = ["VM 1 (RSS de QEMU)", "VM 2 (RSS de QEMU)", "VM 3 (RSS de QEMU)", "Otros usos del host", "Disponible"]
    colores = ["#4b3bb8", "#7767db", "#a79ce8", "#9aa3ab", "#f1f3f5"]
    fig, ax = plt.subplots(figsize=(ANCHO, 2.9))
    total = 0
    for y, d in zip((1, 0), DIST):
        r = [f for f in filas if f["distribucion"] == d and all(f.get(c) is not None for c in cols)]
        if not r:
            continue
        rss = [statistics.mean(f[c] for f in r) / 1024 for c in cols]
        total = statistics.mean(f["memtotal_mb"] for f in r) / 1024
        usado = statistics.mean(f["ram_host_mb"] for f in r) / 1024
        partes = rss + [max(0.0, usado - sum(rss)), total - max(usado, sum(rss))]
        izq = 0.0
        for p, c, nombre in zip(partes, colores, nombres):
            ax.barh(y, p, left=izq, height=0.52, color=c, edgecolor="white", linewidth=1.6, zorder=3)
            claro = c in ("#f1f3f5", "#a79ce8", "#9aa3ab")
            if p >= 0.9:
                ax.text(izq + p / 2, y, _coma(p, 1), ha="center", va="center", color=TINTA if claro else "white", fontweight="bold", zorder=5)
            else:
                ax.annotate(_coma(p, 1), (izq + p / 2, y + 0.26), xytext=(0, 8), textcoords="offset points", ha="center", va="bottom",
                            color=TINTA, fontweight="bold", arrowprops=dict(arrowstyle="-", color=TENUE, lw=0.7, shrinkA=0, shrinkB=0))
            izq += p
    ax.set_yticks([1, 0], [NOMBRE[d] for d in DIST])
    for y, d in zip((1, 0), DIST):
        ax.plot([-0.012], [y], transform=ax.get_yaxis_transform(), marker=FORMA[d], ms=TAM[d], mfc=COL[d], mec="white", mew=0.8,
                ls="", clip_on=False)
    ax.tick_params(axis="y", length=0, pad=14, labelsize=8.5, labelcolor=TINTA)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, total)
    ax.set_ylim(-0.5, 1.55)
    ax.xaxis.set_major_formatter(_fmt(plt))
    ax.grid(axis="x", color=GUIA, lw=0.6)
    ax.set_xlabel("Memoria del host (GB)")
    h = [plt.Rectangle((0, 0), 1, 1, fc=c, ec="#c9ced3" if c == colores[-1] else c, label=n) for n, c in zip(nombres, colores)]
    fig.legend(handles=h, ncol=3, loc="upper left", bbox_to_anchor=(0.0, 1.0), columnspacing=1.4, handlelength=1.2, handletextpad=0.5)
    fig.subplots_adjust(left=0.13, right=0.985, bottom=0.2, top=0.8)
    _guardar(plt, fig, ruta, rotulo)


# ---------------------------------------------------------------------------------------------------------------- 5
def fig_recuperacion(filas, ruta, rotulo):
    """Línea de tiempo por corrida con fallo (segundos desde la inyección), por distribución y por liderazgo del controlador."""
    plt, halo = _mpl()
    from matplotlib.gridspec import GridSpec
    grupos = {d: [[f for f in filas if f["distribucion"] == d and bool(f["nodo_fallado_lideraba"]) == l] for l in (True, False)] for d in DIST}
    filas_d = {d: sum(len(g) for g in grupos[d]) + 2 * sum(1 for g in grupos[d] if g) for d in DIST}
    fig = plt.figure(figsize=(ANCHO, 6.5))
    gs = GridSpec(2, 1, height_ratios=[filas_d[d] for d in DIST], hspace=0.28, figure=fig)
    fin_max = max(f["restauracion"] + (f["ready_tras_restauracion"] or 0) for f in filas)
    rest = statistics.median(f["restauracion"] for f in filas)
    axs = []
    for k, d in enumerate(DIST):
        ax = fig.add_subplot(gs[k], sharex=axs[0] if axs else None)
        axs.append(ax)
        y, ticks = 0.0, []
        for lid, g in zip((True, False), grupos[d]):
            if not g:
                continue
            ax.text(2.5, y - 0.15, ("El nodo fallado lideraba el kube-controller-manager" if lid else "El nodo fallado no lideraba el kube-controller-manager")
                    + f" (n = {len(g)})", ha="left", va="center", color=TINTA2, fontsize=7.5,
                    fontweight="bold")
            y -= 1.15
            for f in sorted(g, key=lambda f: f["repeticion"]):
                ticks.append((y, f"r{int(f['repeticion'])}"))
                ax.axhline(y, color=GUIA, lw=0.7, zorder=1)
                if f.get("api_caida_desde") is not None and f.get("api_restablecida") is not None:
                    ax.barh(y - 0.24, f["api_restablecida"] - f["api_caida_desde"], left=f["api_caida_desde"], height=0.16,
                            color=COL[d], alpha=0.45, zorder=2)
                if f.get("migracion_vip_plano_control") is not None:
                    ax.plot(f["migracion_vip_plano_control"], y + 0.13, ls="", marker="D", ms=4.4, mfc=COL[d], mec="white", mew=0.7, zorder=4)
                if f.get("migracion_vip_servicio") is not None:
                    ax.plot(f["migracion_vip_servicio"], y - 0.02, ls="", marker="o", ms=4.6, mfc=COL[d], mec="white", mew=0.7, zorder=4)
                if f.get("notready") is not None:
                    ax.plot(f["notready"], y, ls="", marker="v", ms=6.5, mfc=TINTA, mec="white", mew=0.7, zorder=4)
                ax.plot([f["restauracion"]] * 2, [y - 0.32, y + 0.32], color=TINTA, lw=1.4, zorder=3)
                ax.plot(f["restauracion"] + (f["ready_tras_restauracion"] or 0), y, ls="", marker="s", ms=5.5, mfc="white", mec=TINTA,
                        mew=1.3, zorder=4)
                y -= 1.0
            y -= 0.55
        ax.axvspan(0, rest, color="#f4f6f8", zorder=0)
        ax.axvline(0, color=TINTA2, lw=1.0, zorder=3)
        ax.set_yticks([t for t, _ in ticks], [n for _, n in ticks])
        ax.set_ylim(y + 0.35, 0.55)
        ax.set_xlim(-3, fin_max + 8)
        _limpiar_x(ax)
        ax.xaxis.set_major_locator(plt.MultipleLocator(20))
        ax.xaxis.set_major_formatter(_fmt(plt))
        ax.plot([-0.115], [1.04], transform=ax.transAxes, marker=FORMA[d], ms=TAM[d], mfc=COL[d], mec="white", mew=0.8, ls="", clip_on=False)
        ax.text(-0.085, 1.04, NOMBRE[d], transform=ax.transAxes, ha="left", va="center", fontsize=9.5, fontweight="bold")
        if k == 0:
            ax.text(rest / 2 + 12, 1.04, "nodo detenido", transform=ax.get_xaxis_transform(), ha="center", va="center", color=TINTA2,
                    fontsize=7.5, style="italic")
            ax.text(1.5, 1.04, "inyección", transform=ax.get_xaxis_transform(), ha="left", va="center", color=TINTA2, fontsize=7.5)
            ax.tick_params(labelbottom=False)
    axs[-1].set_xlabel("Segundos desde la inyección del fallo")
    gris = "#8c959f"
    h = [plt.Rectangle((0, 0), 1, 1, fc=gris, alpha=0.5, label="API no disponible"),
         plt.Line2D([], [], ls="", marker="D", ms=4.4, mfc=gris, mec="white", label="VIP del plano de control migra"),
         plt.Line2D([], [], ls="", marker="o", ms=4.6, mfc=gris, mec="white", label="VIP del servicio migra"),
         plt.Line2D([], [], ls="", marker="v", ms=6.5, mfc=TINTA, mec="white", label="Nodo NotReady"),
         plt.Line2D([], [], color=TINTA, lw=1.4, label="Se restaura el nodo"),
         plt.Line2D([], [], ls="", marker="s", ms=5.5, mfc="white", mec=TINTA, mew=1.3, label="Nodo Ready")]
    fig.legend(handles=h, ncol=3, loc="upper left", bbox_to_anchor=(0.0, 1.0), columnspacing=1.4, handletextpad=0.4)
    fig.subplots_adjust(left=0.115, right=0.985, bottom=0.075, top=0.885)
    _guardar(plt, fig, ruta, rotulo)


# ---------------------------------------------------------------------------------------------------------------- misc
def autotest():
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print("autotest de figuras omitido: falta matplotlib")
        return
    from analysis.recursos_latencia import histograma
    filas, cache = [], {}
    for d, base in (("k3s", 5.0), ("microk8s", 4.0)):
        for e, w, p95, cpu in (("idle", 0, None, 5), ("media", 1, 2.0, 15), ("alta", 2, 8.0 if d == "k3s" else 60.0, 30)):
            for r in (1, 2, 3):
                b = f"{d}_{e}_r{r}"
                filas.append({"base": b, "distribucion": d, "escenario": e, "repeticion": r, "tasa": {"idle": None, "media": 450.0, "alta": 900.0}[e],
                              "tipo": "piloto", "potencia_W": base + w + r * 0.01, "ve_p95_ms": p95, "cpu_host_pct": cpu, "cpu_vm_media": cpu + 1,
                              "ram_vm_media": 900.0, "ram_host_mb": 9000.0, "rss_vm1_mb": 2500.0, "rss_vm2_mb": 2500.0, "rss_vm3_mb": 2500.0,
                              "memtotal_mb": 14800.0, "ve_descartadas": 3})
                if p95:
                    cache[b + "|x"] = {"hist": histograma([p95 * (1 + i / 1000) for i in range(1, 2000)])}
    rec = [{"distribucion": d, "repeticion": r, "nodo_fallado_lideraba": r % 2 == 0, "api_caida_desde": 1.0, "api_restablecida": 19.0,
            "migracion_vip_plano_control": 18.0, "migracion_vip_servicio": 17.0, "notready": 50.0 + 60 * (r % 2 == 0), "restauracion": 121.0,
            "ready_tras_restauracion": 8.0} for d in DIST for r in (1, 2, 3)]
    with tempfile.TemporaryDirectory() as t:
        for f, args in ((fig_energia_latencia, (filas,)), (fig_recursos, (filas,)), (fig_memoria, (filas,)), (fig_espectro, (filas, cache)),
                        (fig_recuperacion, (rec,))):
            ruta = os.path.join(t, f.__name__ + ".pdf")
            f(*args, ruta, "Preliminar")
            assert os.path.getsize(ruta) > 1000, ruta
    print("autotest ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recursos", help="recursos_latencia.csv de una sesión por distribución (misma configuración)")
    ap.add_argument("--cache", help="cache_latencia.json con los histogramas (por defecto, junto a --recursos)")
    ap.add_argument("--recuperacion", help="recuperacion.csv con las corridas con fallo (misma configuración)")
    ap.add_argument("--salida", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "salidas"))
    ap.add_argument("--rotulo", default="", help="texto en la esquina de cada figura, p. ej. «Preliminar, una sesión»")
    ap.add_argument("--autotest", action="store_true")
    a = ap.parse_args()
    if a.autotest:
        return autotest()
    if not (a.recursos or a.recuperacion):
        ap.error("indica --recursos y/o --recuperacion")
    os.makedirs(a.salida, exist_ok=True)
    if a.recursos:
        filas = leer_csv(a.recursos)
        comprobar_configuracion(filas)
        fig_energia_latencia(filas, os.path.join(a.salida, "figura_energia_latencia.pdf"), a.rotulo)
        fig_recursos(filas, os.path.join(a.salida, "figura_cpu_ram.pdf"), a.rotulo)
        fig_memoria(filas, os.path.join(a.salida, "figura_memoria_host.pdf"), a.rotulo)
        cache_ruta = a.cache or os.path.join(os.path.dirname(a.recursos), "cache_latencia.json")
        if os.path.exists(cache_ruta):
            fig_espectro(filas, json.load(open(cache_ruta)), os.path.join(a.salida, "figura_espectro_latencia.pdf"), a.rotulo)
        else:
            print("sin cache_latencia.json: omito el espectro de latencia")
    if a.recuperacion:
        filas = leer_csv(a.recuperacion)
        comprobar_configuracion([{"escenario": "media", "tasa": f["tasa"], "tipo": f["tipo"]} for f in filas])
        fig_recuperacion(filas, os.path.join(a.salida, "figura_recuperacion.pdf"), a.rotulo)


if __name__ == "__main__":
    main()
