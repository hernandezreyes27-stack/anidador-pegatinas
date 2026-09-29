"""Lectura de un diseño SVG: separa el arte del trazado de corte y lo prepara como bloque PDF."""
import io
import re
import xml.etree.ElementTree as ET
import numpy as np
import pikepdf
import pymupdf
from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union

PT = 25.4 / 72  # mm por punto
DIBUJABLES = {'path', 'polygon', 'polyline', 'rect', 'circle', 'ellipse', 'line'}
SVGNS = 'http://www.w3.org/2000/svg'


class DisenoError(ValueError):
    pass


def _norm_hex(c):
    c = (c or '').strip().lower()
    if re.fullmatch(r'#[0-9a-f]{3}', c):
        c = '#' + ''.join(ch * 2 for ch in c[1:])
    return c


def _estilos_css_en_linea(s):
    """Illustrator exporta clases CSS (.st0{...}); MuPDF no las lee, así que se pasan a atributos."""
    reglas = {cls: body for cls, body in re.findall(r'\.([\w-]+)\s*\{([^}]*)\}', s)}

    def sustituir(m):
        clases = m.group(1).split()
        attrs = []
        for cls in clases:
            for decl in reglas.get(cls, '').split(';'):
                if ':' in decl:
                    k, v = decl.split(':', 1)
                    attrs.append(f'{k.strip()}="{v.strip()}"')
        return ' '.join(attrs)
    return re.sub(r'class="([^"]*)"', sustituir, s)


def _color_trazo(el):
    st = el.get('stroke')
    m = re.search(r'stroke\s*:\s*([^;]+)', el.get('style', ''))
    if m:
        st = m.group(1)
    return _norm_hex(st)


def _separar(svg_text, color_corte):
    ET.register_namespace('', SVGNS)
    ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    root_arte = ET.fromstring(svg_text)
    root_corte = ET.fromstring(svg_text)
    color_corte = _norm_hex(color_corte)

    def es_corte(el):
        tag = el.tag.split('}')[-1]
        ident = (el.get('id') or '').lower()
        return tag in DIBUJABLES and (_color_trazo(el) == color_corte or 'cutcontour' in ident)

    n = 0
    for root, quitar_corte in ((root_arte, True), (root_corte, False)):
        padres = {c: p for p in root.iter() for c in p}
        for el in list(root.iter()):
            tag = el.tag.split('}')[-1]
            if el is root or tag in ('g', 'defs', 'style', 'clipPath', 'mask', 'svg'):
                continue
            corte = es_corte(el)
            if quitar_corte and corte:
                padres[el].remove(el); n += 1
            elif not quitar_corte:
                if corte:
                    el.set('fill', 'none'); el.set('stroke', '#000000')
                    el.attrib.pop('style', None)
                elif el in padres:
                    padres[el].remove(el)
    if n == 0:
        raise DisenoError(f'No se encontró ningún trazado de corte con el color {color_corte}.')
    return ET.tostring(root_arte, encoding='unicode'), ET.tostring(root_corte, encoding='unicode')


def _svg_a_pdf(svg):
    return pymupdf.open('pdf', pymupdf.open(stream=svg.encode(), filetype='svg').convert_to_pdf())


class Pegatina:
    def __init__(self, nombre, svg_bytes, color_corte='#0BF786'):
        self.nombre = nombre
        s = _estilos_css_en_linea(svg_bytes.decode('utf-8', errors='replace'))
        arte, corte = _separar(s, color_corte)
        doc_arte, doc_corte = _svg_a_pdf(arte), _svg_a_pdf(corte)
        pagina = doc_corte[0]
        self.H = pagina.rect.height

        # Trazado de corte: polígono (mm, y hacia abajo) + operadores PDF (pt, y hacia arriba)
        polys, ops = [], []
        f = lambda v: f'{v:.3f}'
        for d in pagina.get_drawings():
            sub, ultimo = [], None
            for it in d['items']:
                k = it[0]
                if k == 're':
                    r = it[1]; esq = [r.tl, r.tr, r.br, r.bl]
                    polys.append(Polygon([(p.x * PT, p.y * PT) for p in esq]))
                    ops.append(f'{f(r.x0)} {f(self.H - r.y1)} {f(r.width)} {f(r.height)} re')
                    continue
                if k == 'qu':
                    q = it[1]; esq = [q.ul, q.ur, q.lr, q.ll]
                    polys.append(Polygon([(p.x * PT, p.y * PT) for p in esq]))
                    ops.append(f'{f(esq[0].x)} {f(self.H-esq[0].y)} m ' + ' '.join(f'{f(p.x)} {f(self.H-p.y)} l' for p in esq[1:]) + ' h')
                    continue
                p0 = it[1]
                if ultimo is None or abs(p0.x - ultimo.x) > 1e-3 or abs(p0.y - ultimo.y) > 1e-3:
                    if len(sub) > 2:
                        polys.append(Polygon(sub))
                    sub = [(p0.x * PT, p0.y * PT)]
                    ops.append(f'{f(p0.x)} {f(self.H - p0.y)} m')
                if k == 'l':
                    p1 = it[2]
                    sub.append((p1.x * PT, p1.y * PT))
                    ops.append(f'{f(p1.x)} {f(self.H - p1.y)} l')
                    ultimo = p1
                elif k == 'c':
                    c1, c2, p1 = it[2], it[3], it[4]
                    for t in np.linspace(0, 1, 9)[1:]:
                        x = (1-t)**3*p0.x + 3*(1-t)**2*t*c1.x + 3*(1-t)*t**2*c2.x + t**3*p1.x
                        y = (1-t)**3*p0.y + 3*(1-t)**2*t*c1.y + 3*(1-t)*t**2*c2.y + t**3*p1.y
                        sub.append((x * PT, y * PT))
                    ops.append(f'{f(c1.x)} {f(self.H-c1.y)} {f(c2.x)} {f(self.H-c2.y)} {f(p1.x)} {f(self.H-p1.y)} c')
                    ultimo = p1
            if len(sub) > 2:
                polys.append(Polygon(sub))
        if not polys:
            raise DisenoError('El trazado de corte no forma ninguna figura cerrada.')
        P = unary_union([p.buffer(0) for p in polys])
        # Solo cuenta el contorno exterior: los huecos interiores no dejan sitio a otras pegatinas
        if P.geom_type == 'Polygon':
            P = Polygon(P.exterior)
        else:
            P = unary_union([Polygon(g.exterior) for g in P.geoms])
        P = P.simplify(0.05)
        self.X0, self.Y0 = P.bounds[:2]
        self.P = affinity.translate(P, -self.X0, -self.Y0)
        self.ancho = self.P.bounds[2]; self.alto = self.P.bounds[3]

        # Bloque indivisible: arte + contorno en tinta plana CutContour
        tmp = pikepdf.open(io.BytesIO(doc_arte.tobytes()))
        pg = tmp.pages[0]
        sep = pikepdf.Array([pikepdf.Name.Separation, pikepdf.Name('/CutContour'), pikepdf.Name.DeviceCMYK,
                             tmp.make_indirect(pikepdf.Dictionary(FunctionType=2, Domain=[0, 1], C0=[0, 0, 0, 0], C1=[0, 1, 0, 0], N=1))])
        if '/Resources' not in pg.obj:
            pg.obj.Resources = pikepdf.Dictionary()
        if '/ColorSpace' not in pg.obj.Resources:
            pg.obj.Resources.ColorSpace = pikepdf.Dictionary()
        pg.obj.Resources.ColorSpace.CutCS = sep
        pg.contents_add(pikepdf.Stream(tmp, ('q /CutCS CS 1 SCN 0.25 w ' + ' '.join(ops) + ' S Q').encode()))
        self.pdf = tmp
