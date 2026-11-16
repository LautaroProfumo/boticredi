"""Conexión con el sistema de Credifin (el mismo servicio que usa credifin.com.ar).

- Seguimiento y localidades: servicio público, no necesita clave.
- Cotizar: usa la clave propia (CREDIFIN_API_KEY) si está cargada; si no, lee la
  configuración pública del cotizador de la web. Si el sistema no responde, el
  bot deriva la cotización a una persona.
"""
import os
import re
from datetime import datetime

import requests

BASE = os.getenv("CREDIFIN_API", "https://thegroup.credifin.com.ar").rstrip("/")
PUBLICA = f"{BASE}/public/api"
INTEGRACION = f"{BASE}/api/v1"
API_KEY = os.getenv("CREDIFIN_API_KEY", "").strip()
LINK_SEGUIMIENTO = "https://credifin.com.ar/seguimiento/"
TIMEOUT = 15

# El sitio de Credifin rechaza pedidos que no parezcan de un navegador, así que
# todas las consultas salen con estos encabezados (si no, falla en silencio).
_sesion = requests.Session()
_sesion.headers.update({
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-AR,es;q=0.9",
    "Origin": "https://credifin.com.ar",
    "Referer": "https://credifin.com.ar/",
})


class ErrorCredifin(Exception):
    """El sistema de Credifin no respondió o respondió algo inesperado."""


def _get(url, params=None):
    """Devuelve el campo "data" de la respuesta, o None si no existe (404)."""
    try:
        r = _sesion.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ErrorCredifin(str(e)) from e
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise ErrorCredifin(f"HTTP {r.status_code}")
    try:
        cuerpo = r.json()
    except ValueError as e:
        raise ErrorCredifin("respuesta no es JSON") from e
    return cuerpo.get("data") if isinstance(cuerpo, dict) else None


# ---------------------------------------------------------------- seguimiento

def rastrear(codigo):
    """Busca un envío por código de seguimiento o etiqueta.

    Devuelve None si no existe, o un dict:
      {"etiqueta", "movimientos": [{"fecha", "descripcion", "estado"}],
       "entrega", "sucursal", "bultos"}
    Los movimientos quedan ordenados del más nuevo al más viejo.
    """
    codigo = str(codigo).strip()
    guia = _get(f"{PUBLICA}/guia/{codigo}")
    etiqueta = codigo
    sucursal = None
    bultos = 1
    destinatario = None
    if guia:
        info = guia.get("guia_info") or {}
        sucursal = guia.get("dfilial") or info.get("dfilial")
        destinatario = _primero(info, ("dnombre", "destinatario_nombre", "dnombre_completo"))
        lista = info.get("guias_detalles_bulto") or []
        bultos = len(lista) or 1
        etiquetas = [str(b.get("etiqueta")) for b in lista if b.get("etiqueta")]
        if etiquetas:
            etiqueta = codigo if codigo in etiquetas else etiquetas[0]

    seg = _get(f"{PUBLICA}/seguimiento/{etiqueta}")
    if not guia and not seg:
        return None
    seg = seg or {}
    movimientos = [m for m in (seg.get("tracking") or []) if isinstance(m, dict)]
    movimientos.sort(key=lambda m: str(m.get("fecha") or ""), reverse=True)
    return {
        "etiqueta": etiqueta,
        "movimientos": movimientos,
        "entrega": seg.get("entrega"),
        "sucursal": sucursal,
        "bultos": bultos,
        "destinatario": destinatario,
    }


def fecha_linda(valor):
    """'2026-11-12T14:30:00Z' -> '12/11 14:30'. Si no se puede, devuelve tal cual."""
    if not valor:
        return ""
    texto = str(valor).replace("Z", "").split("+")[0].split(".")[0]
    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).strftime("%d/%m %H:%M")
        except ValueError:
            continue
    return str(valor)


# ---------------------------------------------------------------- localidades

def _primero(d, claves):
    for c in claves:
        v = d.get(c)
        if v not in (None, "", []):
            return v
    return None


def buscar_localidades(texto):
    """Busca localidades con cobertura. Devuelve [{"nombre", "cp"}] (máx. 6)."""
    data = _get(f"{PUBLICA}/localidades", params={"q": texto, "cobertura": 1})
    crudas = (data or {}).get("localidades") if isinstance(data, dict) else data
    resultado = []
    for loc in crudas or []:
        if not isinstance(loc, dict):
            continue
        cp = _primero(loc, ("cp", "codigo_postal", "codigoPostal"))
        nombre = _primero(loc, ("localidad_nombre", "localidad", "nombre", "descripcion", "label"))
        if not cp or not nombre:
            continue
        provincia = _primero(loc, ("provincia_nombre", "provincia", "provincias_nombre"))
        if isinstance(provincia, dict):
            provincia = _primero(provincia, ("nombre", "descripcion", "provincia"))
        prov_txt = str(provincia).title() if provincia else ""
        if prov_txt and prov_txt.lower() not in str(nombre).lower():
            nombre = f"{nombre}, {prov_txt}"
        resultado.append({"nombre": str(nombre).title(), "cp": str(cp), "provincia": prov_txt})
        if len(resultado) == 6:
            break
    return resultado


def cp_de_localidad(nombre, provincia=None):
    """Devuelve el CP de una localidad, eligiendo la de la provincia pedida si hay varias."""
    opciones = buscar_localidades(nombre)
    if not opciones:
        return None
    if provincia:
        for o in opciones:
            if provincia.lower() in (o.get("provincia") or "").lower():
                return o["cp"]
    return opciones[0]["cp"]


# ------------------------------------------------------------------- cotizar
#
# El cotizador necesita una clave de integración. Dos formas de obtenerla:
#  a) CREDIFIN_API_KEY cargada a mano (clave propia que pida la sucursal a central).
#  b) Si no hay clave, se lee la configuración pública del cotizador de la web
#     (la misma que la página carga al abrirse) y se usa esa. Se relee cada tanto,
#     así que si central la cambia, el bot la toma sola.

COTIZADOR_URL = "https://credifin.com.ar/cotizador/"
_cache_cfg = {"base": None, "key": None, "t": 0.0}
_CACHE_SEGUNDOS = 1800  # releer la config cada 30 minutos


def _config_cotizador():
    """Devuelve (base_integracion, clave). Lanza ErrorCredifin si no la consigue."""
    if API_KEY:
        return INTEGRACION, API_KEY
    import time
    ahora = time.time()
    if _cache_cfg["key"] and ahora - _cache_cfg["t"] < _CACHE_SEGUNDOS:
        return _cache_cfg["base"], _cache_cfg["key"]
    try:
        html = _sesion.get(COTIZADOR_URL, timeout=TIMEOUT).text
        archivo = re.search(r"assets/index-[A-Za-z0-9_-]+\.js", html).group(0)
        js = _sesion.get(COTIZADOR_URL + archivo, timeout=TIMEOUT).text
        base = re.search(r'"(https://[A-Za-z0-9.-]*credifin\.com\.ar)"', js).group(1) + "/api/v1"
        clave = re.search(r'INTEGRATION_API_KEY:"([^"]+)"', js).group(1)
    except (requests.RequestException, AttributeError) as e:
        raise ErrorCredifin("no pude leer la configuración del cotizador: " + str(e)) from e
    _cache_cfg.update(base=base, key=clave, t=ahora)
    return base, clave


def puede_cotizar():
    return True


def cotizar(cp_origen, cp_destino, bultos):
    """Pide el precio al cotizador. Devuelve la lista de cotizaciones (una por bulto).

    bultos: lista de dicts {peso, largo, ancho, alto, valor}.
    """
    base, clave = _config_cotizador()
    payload = [{
        "cp_origen": cp_origen, "cp_destino": cp_destino,
        "peso": b["peso"], "x": b["largo"], "y": b["ancho"], "z": b["alto"],
        "cantidad": 1, "valor_declarado": b.get("valor", 0) or 0,
    } for b in bultos]
    try:
        r = _sesion.post(
            f"{base}/cotizar", json=payload, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {clave}"},
        )
        r.raise_for_status()
        cuerpo = r.json()
    except (requests.RequestException, ValueError) as e:
        raise ErrorCredifin(str(e)) from e
    data = cuerpo.get("data") if isinstance(cuerpo, dict) else None
    if isinstance(data, dict):
        return data.get("cotizaciones") or []
    return data or []
