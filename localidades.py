"""Cobertura de Credifin: busca una localidad en el folleto de localidades.

Los datos están en localidades.json (sacados del folleto de marzo 2026).
Cuando salga un folleto nuevo hay que actualizar ese archivo.
"""
import difflib
import json
import os
import re
import unicodedata

_ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "localidades.json")
with open(_ARCHIVO, encoding="utf-8") as f:
    LOCALIDADES = json.load(f)  # [{"n": nombre, "p": provincia, "f": frecuencia, "s": sucursal}]

# Sucursales que maneja este bot (para los pedidos de retiro)
SUCURSALES_PROPIAS = ("Tres de Febrero", "Morón")

_ABREV = [
    (r"\bgral\b", "general"), (r"\bsta\b", "santa"), (r"\bsto\b", "santo"), (r"\bfco\b", "francisco"),
    (r"\bpte\b", "presidente"), (r"\bpres\b", "presidente"), (r"\bgdor\b", "gobernador"),
    (r"\bconcep\b", "concepcion"), (r"\bpqe\b", "parque"), (r"\bind\b", "industrial"),
    (r"\bindu\b", "industrial"), (r"\bctro\b", "centro"), (r"\bcod\b", "cp"),
    (r"\bsanta r de\b", "santa rosa de"), (r"\br de\b", "remedios de"), (r"\bs m\b", "san martin"), (r"\bs\b", "san"),
    (r"\bv\b", "villa"), (r"\bp\b", "parque"), (r"\bbs as\b", "buenos aires"),
    (r"\bcaba\b", "capital federal"), (r"^capital$", "capital federal"), (r"\bciudad de buenos aires\b", "capital federal"),
]


def normalizar(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9ñ ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for patron, completo in _ABREV:
        t = re.sub(patron, completo, t)
    return re.sub(r"\s+", " ", t).strip()


_CLAVES = [(normalizar(l["n"]), l) for l in LOCALIDADES]
_PROVINCIAS = {normalizar(l["p"]) for l in LOCALIDADES}


def buscar(texto):
    """Devuelve (encontradas, parecidas). Las dos son listas de localidades."""
    q = normalizar(texto)
    # "pilar cordoba" o "pilar, buenos aires": separar la provincia si la escribieron
    provincia = None
    for p in sorted(_PROVINCIAS, key=len, reverse=True):
        if q.endswith(" " + p) and q != p:
            provincia, q = p, q[: -len(p)].strip()
            break
    if not q:
        return [], []

    def filtrar(lista):
        if provincia:
            lista = [l for l in lista if normalizar(l["p"]) == provincia] or lista
        return lista

    exactas = [l for k, l in _CLAVES if k == q]
    # "merlo" -> "Merlo centro", "gerli" -> "Gerli CP 1823",
    # "remedios de escalada" -> también "R. de Escalada de S.M."
    empiezan = [l for k, l in _CLAVES if k.startswith(q + " ")] if len(q) >= 4 else []
    if exactas or empiezan:
        return filtrar(exactas + empiezan)[:6], []
    if q in _PROVINCIAS:  # escribió una provincia: mostrar a dónde llegamos ahí
        de_la_provincia = [l for l in LOCALIDADES if normalizar(l["p"]) == q]
        return [], de_la_provincia
    contienen = [l for k, l in _CLAVES if len(q) >= 5 and q in k]
    nombres = difflib.get_close_matches(q, [k for k, _ in _CLAVES], n=4, cutoff=0.78)
    parecidas = contienen + [l for k, l in _CLAVES if k in nombres and l not in contienen]
    return [], filtrar(parecidas)[:5]


def es_provincia(texto):
    return normalizar(texto) in _PROVINCIAS


_DIAS = {"lu": "lunes", "ma": "martes", "mi": "miércoles", "mie": "miércoles", "ju": "jueves",
         "jue": "jueves", "vi": "viernes", "vie": "viernes", "sab": "sábados",
         "martes": "martes", "miercoles": "miércoles", "viernes": "viernes"}


def frecuencia_texto(loc):
    """'24/48 hs' -> 'entrega en 24/48 hs' ; 'Ma-Ju' -> 'martes y jueves'"""
    f = (loc.get("f") or "").strip()
    if not f:
        texto = "a confirmar con la sucursal"
    elif "hs" in f:
        texto = f"entrega en {f}"
    else:
        partes = [_DIAS.get(normalizar(p), p) for p in re.split(r"[-/]| y ", f) if p.strip()]
        texto = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    if loc.get("nota"):
        texto += f". {loc['nota']}"
    return texto


def descripcion(loc):
    return (f"✅ *{loc['n']}* ({loc['p']})\n"
            f"Frecuencia: {frecuencia_texto(loc)}\n"
            f"La atiende la sucursal: {loc['s']}")
