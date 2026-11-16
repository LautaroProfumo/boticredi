"""Boticredi: la conversación. Recibe un mensaje y devuelve qué contestar.

No sabe nada de WhatsApp: eso lo maneja app.py. Así se puede probar
desde la compu con probar.py sin gastar ni un mensaje.

Menú:
  1 Seguimiento   2 Cotizar   3 Pedir retiro   4 Localidades   5 Representante
"""
import re
import sys
import time

import credifin
import localidades

# ----------------------------------------------------------- datos del local
# Cambiá estos textos acá si cambia algo en la sucursal.
SUCURSAL = "Credifin Express Tres de Febrero"
DIRECCION = "Presidente Illia 406, Villa Sarmiento"
HORARIO = "lunes a viernes de 9 a 17 h"
PESO_MAXIMO = 100  # kg por bulto que cotiza el sistema; más que eso lo ve una persona

MENU = (
    "¿En qué te podemos ayudar?\n\n"
    "1️⃣ Seguimiento de un envío\n"
    "2️⃣ Cotizamos tu envío\n"
    "3️⃣ Pedir un retiro\n"
    "4️⃣ Consultar si llegamos a una localidad\n"
    "5️⃣ Hablar con un representante\n\n"
    "Escribí el número de la opción."
)
SALUDO = f"¡Hola! Soy *Boticredi* 🤖, el asistente de {SUCURSAL}.\n\n" + MENU
PIE = "\n\nEscribí *menú* para volver al inicio."

MINUTOS_SESION = 30
_sesiones = {}  # telefono -> {"paso": str, "datos": dict, "visto": float}


def avisar_local(texto):
    """app.py reemplaza esta función para avisarle al local por WhatsApp."""
    print("[AVISO AL LOCAL]", texto)


# ------------------------------------------------------------------ utilidades

def _sesion(telefono):
    s = _sesiones.get(telefono)
    if not s or time.time() - s["visto"] > MINUTOS_SESION * 60:
        s = {"paso": None, "datos": {}, "visto": 0, "nuevo": True}
        _sesiones[telefono] = s
    s["visto"] = time.time()
    return s


def _reiniciar(s):
    s["paso"], s["datos"] = None, {}


def _numeros(texto):
    """'2,5 kg' -> [2.5] ; '40 x 30 x 20' -> [40.0, 30.0, 20.0]"""
    return [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", texto)]


def _pesos(valor):
    try:
        return "$ " + f"{float(valor):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(valor)


def _pesos2(valor):
    """Formato con centavos, como la web: 20413.83 -> '$ 20.413,83'."""
    try:
        return "$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(valor)


def _monto(texto):
    """'$ 350.000' -> 350000.0 ; 'no' -> 0 ; otra cosa -> None"""
    limpio = texto.lower().replace("$", "").replace(".", "").strip()
    if limpio.startswith("no") or limpio in ("0", "ninguno", "nada", "sin valor"):
        return 0
    nums = _numeros(limpio)
    return nums[0] if nums else None


def _nombre_corto(nombre):
    """'MARTA GOMEZ' -> 'Marta G.' (muestra el nombre sin exponer el apellido completo)."""
    partes = [p for p in str(nombre or "").split() if p]
    if not partes:
        return ""
    corto = partes[0].capitalize()
    if len(partes) > 1 and partes[1][:1].isalpha():
        corto += " " + partes[1][0].upper() + "."
    return corto


def _codigo_en(texto, seguro=False):
    """Encuentra un código de seguimiento dentro del mensaje.

    Los códigos son cortos, con letras y números (por ejemplo AB12CD). También
    se acepta el número largo de la etiqueta del bulto.
    Con seguro=True (el cliente ya eligió "Seguimiento") se acepta cualquier
    palabra suelta de 4 a 25 letras o números.
    """
    palabras = re.findall(r"[A-Za-z0-9]+", texto)
    for p in palabras:
        mezcla = re.search(r"[A-Za-z]", p) and re.search(r"\d", p)
        if (mezcla and 5 <= len(p) <= 10) or (p.isdigit() and len(p) >= 10):
            return p
    if seguro and len(palabras) == 1 and 4 <= len(palabras[0]) <= 25:
        return palabras[0]
    return None


def _opcion(texto, cantidad):
    """Si el cliente escribió un número de opción válido, lo devuelve; si no, None."""
    t = texto.strip().rstrip(".)")
    return int(t) if t.isdigit() and 1 <= int(t) <= cantidad else None


def _derivar(s, motivo="", detalle=""):
    """Le pasa la consulta a una persona del local."""
    aviso = f"Consulta de +{s['telefono']}"
    if motivo:
        aviso += f" — {motivo}"
    if detalle:
        aviso += "\n" + detalle
    avisar_local(aviso)
    _reiniciar(s)
    return ["Le paso tu consulta a un representante, que te responde por este mismo chat. 🙌\n"
            f"Atendemos de {HORARIO}."]


# ----------------------------------------------------------- 1. seguimiento

def _responder_seguimiento(codigo):
    link = credifin.LINK_SEGUIMIENTO + codigo
    try:
        envio = credifin.rastrear(codigo)
    except credifin.ErrorCredifin:
        return ["En este momento no puedo consultar el sistema de seguimiento. 😕\n"
                f"Podés verlo acá: {link}\n\n"
                "O escribí *5* para hablar con un representante."]
    if envio is None:
        return [f"No encontré ningún envío con el código *{codigo}*.\n"
                "Revisá que esté completo y volvé a enviarlo, o escribí *5* para hablar con un representante."]

    movs = envio["movimientos"]
    entrega = envio.get("entrega")
    entregado = isinstance(entrega, dict) and entrega.get("fecha")

    if not movs and not entregado:
        return [f"Encontré tu envío *{codigo}*, pero todavía no tiene movimientos cargados.\n"
                f"Podés volver a consultarlo más tarde o verlo acá: {link}" + PIE]

    lineas = [f"📦 *Envío {codigo}*"]
    if envio.get("destinatario"):
        lineas.append(f"*A nombre de:* {_nombre_corto(envio['destinatario'])}")

    if entregado:
        lineas += ["", "*Estado actual:* Entregado ✅",
                   f"_{credifin.fecha_linda(entrega.get('fecha'))}_"]
        if entrega.get("recibe"):
            lineas.append(f"Recibió: {_nombre_corto(entrega['recibe'])}")
        anteriores = movs[:3]
    else:
        ultimo = movs[0]
        lineas += ["",
                   f"*Estado actual:* {ultimo.get('descripcion') or ultimo.get('estado') or 'Sin detalle'}",
                   f"_{credifin.fecha_linda(ultimo.get('fecha'))}_"]
        if envio["bultos"] > 1:
            lineas.append(f"(El envío tiene {envio['bultos']} bultos; te muestro el primero.)")
        anteriores = movs[1:4]

    if anteriores:
        lineas += ["", "*Movimientos anteriores:*"]
        lineas += [f"• {credifin.fecha_linda(m.get('fecha'))} — {m.get('descripcion') or m.get('estado') or ''}"
                   for m in anteriores]
    suc = None if entregado else envio["sucursal"]
    if isinstance(suc, dict):
        partes = [str(suc.get(k)) for k in ("calle", "altura") if suc.get(k)]
        loc = suc.get("localidad")
        if isinstance(loc, dict):
            loc = loc.get("localidad") or loc.get("nombre")
        domicilio = (" ".join(partes) + (f", {loc}" if loc else "")).strip(", ")
        if domicilio:
            nombre = f"{suc['nombre']} — " if suc.get("nombre") else ""
            lineas += ["", f"*Sucursal de destino:* {nombre}{domicilio}"]
            if suc.get("telefono"):
                lineas.append(f"Tel.: {suc['telefono']}")
            if suc.get("dias_atencion"):
                lineas.append(f"Atención: {suc['dias_atencion']}")
    lineas += ["", f"Detalle completo: {link}"]
    return ["\n".join(lineas) + PIE]


# ------------------------------------------- localidades (lo usan 2, 3 y 4)

def _elegir_localidad(s, texto, al_elegir, pregunta):
    """Busca la localidad que escribió el cliente en la lista de cobertura.

    Si hay una sola, llama a al_elegir(localidad). Si hay varias, las lista
    y espera el número. Devuelve la respuesta para el cliente.
    """
    d = s["datos"]
    opciones = d.pop("opciones", None)
    if opciones:
        n = _opcion(texto, len(opciones))
        if n:
            return al_elegir(opciones[n - 1])
    if len(texto.strip()) < 3:
        return [pregunta]
    encontradas, parecidas = localidades.buscar(texto)
    if len(encontradas) == 1:
        return al_elegir(encontradas[0])
    lista = encontradas or parecidas
    if not lista:
        return [f"No encontré *{texto.strip()}* en nuestro listado de localidades, así que por ahora no llegamos. 😕\n\n"
                "Podés probar escribiéndola de otra forma, o escribir *5* para consultar con un representante." + PIE]
    if not encontradas and localidades.es_provincia(texto):
        prov = lista[0]["p"]
        if len(lista) > 15:
            return [f"En {prov} llegamos a {len(lista)} localidades. Escribime el nombre de la localidad y te confirmo."]
        d["opciones"] = lista
        filas = "\n".join(f"{i}. {l['n']}" for i, l in enumerate(lista, 1))
        return [f"En {prov} llegamos a estas localidades:\n\n{filas}\n\nEscribí el número de la que te interesa."]
    d["opciones"] = lista
    titulo = "Hay más de una con ese nombre." if encontradas else f"No encontré *{texto.strip()}* tal cual."
    filas = "\n".join(f"{i}. {l['n']} ({l['p']})" for i, l in enumerate(lista, 1))
    return [f"{titulo} ¿Es alguna de estas?\n\n{filas}\n\nEscribí el número, o volvé a escribir la localidad."]


# -------------------------------------------------------------- 2. cotizar

P_COT_RETIRO = ("¿Cómo nos entregás el paquete?\n\n"
                "1. Lo llevo a la sucursal\n2. Quiero que lo retiren por mi domicilio")
P_COT_ENTREGA = ("¿Cómo lo recibe el destinatario?\n\n"
                 "1. Lo retira en la sucursal de destino\n2. Entrega a domicilio")
P_COT_ORIGEN = "¿Desde qué *localidad* sale el envío?"
P_COT_DESTINO = "¿A qué *localidad* va?"
P_COT_PESO = "¿Cuánto *pesa*, en kilos? (por ejemplo: 5)"
P_COT_MEDIDAS = "¿Qué *medidas* tiene? Largo x ancho x alto, en cm (por ejemplo: 40 x 30 x 20)"
P_COT_VALOR = ("¿Cuál es el *valor declarado* de la mercadería, en pesos? (por ejemplo: 350000)\n"
               "El mínimo es $300.000. Si supera los $750.000, necesitás remito o factura fiscal.")
P_COT_OTRO = ("¿Querés agregar otro bulto?\n\n1. Sí, agregar otro\n2. No, cotizar así")


def _pedir_peso(d):
    return f"📦 *Bulto {len(d['bultos']) + 1}*\n\n{P_COT_PESO}"


def _resumen_cotizacion(d):
    lineas = [
        f"• Retiro: {'a domicilio' if d['retiro_dom'] else 'lo lleva a la sucursal'}",
        f"• Entrega: {'a domicilio' if d['entrega_dom'] else 'retira en sucursal de destino'}",
        f"• Origen: {d['origen']['n']} ({d['origen']['p']})",
        f"• Destino: {d['destino']['n']} ({d['destino']['p']})",
    ]
    varios = len(d["bultos"]) > 1
    for i, b in enumerate(d["bultos"], 1):
        etiqueta = f"Bulto {i}" if varios else "Paquete"
        val = _pesos(b["valor"]) if b["valor"] else "sin declarar"
        lineas.append(f"• {etiqueta}: {b['peso']:g} kg, "
                      f"{b['largo']:g} x {b['ancho']:g} x {b['alto']:g} cm, valor {val}")
    return "\n".join(lineas)


def _precio_automatico(d):
    """Pide el precio al cotizador de Credifin. Devuelve el bloque de texto o None."""
    try:
        cps = []
        for cual in ("origen", "destino"):
            cp = credifin.cp_de_localidad(d[cual]["n"], d[cual].get("p"))
            if not cp:
                print(f"[cotizacion] no encontré el código postal de {d[cual]['n']}", file=sys.stderr)
                return None
            cps.append(cp)
        cotizaciones = credifin.cotizar(cps[0], cps[1], d["bultos"])
    except credifin.ErrorCredifin as e:
        print(f"[cotizacion] no pude cotizar: {e}", file=sys.stderr)
        return None
    precios = [c for c in cotizaciones if isinstance(c, dict) and c.get("precio")]
    if not precios:
        return None

    def suma(campo):
        return sum(c.get(campo) or 0 for c in precios if isinstance(c.get(campo), (int, float)))

    envio = suma("precio")
    retiro = suma("adicional_retiro") if d["retiro_dom"] else 0
    entrega = suma("adicional_entrega") if d["entrega_dom"] else 0
    total = envio + retiro + entrega
    lineas = []
    if retiro > 0 or entrega > 0:
        lineas.append(f"Envío a sucursal: {_pesos2(envio)}")
        if retiro > 0:
            lineas.append(f"Retiro a domicilio: + {_pesos2(retiro)}")
        if entrega > 0:
            lineas.append(f"Entrega a domicilio: + {_pesos2(entrega)}")
    lineas.append(f"*Total aproximado:* {_pesos2(total)}")
    lineas.append("_(+ seguro e impuestos)_")
    return "\n".join(lineas)


def _terminar_cotizacion(s):
    d = s["datos"]
    resumen = _resumen_cotizacion(d)
    precio = _precio_automatico(d)
    if precio:
        _reiniciar(s)
        return [f"💰 *Cotización estimada*\n\n{resumen}\n\n{precio}\n\n"
                "El precio es estimado y se confirma al pesar y medir el paquete.\n"
                "Si querés que lo retiremos, escribí *3*." + PIE]
    respuesta = [f"Listo, ya tengo todos los datos:\n\n{resumen}\n\nTe cotizamos enseguida."]
    return respuesta + _derivar(s, "Pedido de cotización", resumen.replace("• ", ""))


def _paso_cotizacion(s, texto):
    paso, d = s["paso"], s["datos"]

    if paso == "cot_retiro":
        n = _opcion(texto, 2)
        if not n:
            return ["Escribí *1* o *2*.\n\n" + P_COT_RETIRO]
        d["retiro_dom"] = n == 2
        s["paso"] = "cot_entrega"
        return [P_COT_ENTREGA]

    if paso == "cot_entrega":
        n = _opcion(texto, 2)
        if not n:
            return ["Escribí *1* o *2*.\n\n" + P_COT_ENTREGA]
        d["entrega_dom"] = n == 2
        s["paso"] = "cot_origen"
        return [P_COT_ORIGEN]

    if paso == "cot_origen":
        def listo(loc):
            d["origen"] = loc
            s["paso"] = "cot_destino"
            return [f"Origen: *{loc['n']}* ({loc['p']}) ✅\n\n{P_COT_DESTINO}"]
        return _elegir_localidad(s, texto, listo, P_COT_ORIGEN)

    if paso == "cot_destino":
        def listo(loc):
            d["destino"] = loc
            s["paso"] = "cot_peso"
            return [f"Destino: *{loc['n']}* ({loc['p']}) ✅\n"
                    f"Frecuencia: {localidades.frecuencia_texto(loc)}\n\n{_pedir_peso(d)}"]
        return _elegir_localidad(s, texto, listo, P_COT_DESTINO)

    if paso == "cot_peso":
        nums = _numeros(texto)
        if not nums or nums[0] <= 0:
            return ["No entendí el peso. Escribilo en kilos, solo el número (por ejemplo: 5 o 2,5)."]
        if nums[0] > PESO_MAXIMO:
            resumen = _resumen_cotizacion(d) + f"\n• Este bulto: {nums[0]:g} kg"
            return [f"Los bultos de más de {PESO_MAXIMO} kg los cotiza un representante."] + \
                _derivar(s, "Cotización con bulto de más de 100 kg", resumen.replace("• ", ""))
        d["_peso"] = nums[0]
        s["paso"] = "cot_medidas"
        return [P_COT_MEDIDAS]

    if paso == "cot_medidas":
        nums = _numeros(texto)
        if len(nums) < 3 or min(nums[:3]) <= 0:
            return ["Necesito las tres medidas en centímetros: largo x ancho x alto (por ejemplo: 40 x 30 x 20)."]
        d["_medidas"] = nums[:3]
        s["paso"] = "cot_valor"
        return [P_COT_VALOR]

    if paso == "cot_valor":
        valor = _monto(texto)
        if valor is None:
            return ["No entendí el valor. Escribí el monto en pesos (por ejemplo: 350000)."]
        valor = max(valor, 300000)  # el valor declarado mínimo asegurable es $300.000
        largo, ancho, alto = d["_medidas"]
        d["bultos"].append({"peso": d["_peso"], "largo": largo, "ancho": ancho, "alto": alto, "valor": valor})
        s["paso"] = "cot_otro"
        return [f"Bulto {len(d['bultos'])} agregado ✅\n\n{P_COT_OTRO}"]

    if paso == "cot_otro":
        n = _opcion(texto, 2)
        if n == 1:
            s["paso"] = "cot_peso"
            return [_pedir_peso(d)]
        if n == 2:
            return _terminar_cotizacion(s)
        return ["Escribí *1* para agregar otro bulto o *2* para cotizar así."]

    _reiniciar(s)
    return [MENU]


# --------------------------------------------------------- 3. pedir retiro

P_RETIRO = (
    "Para coordinar un retiro, escribinos *todo en un solo mensaje* y un representante "
    "te contacta para confirmar día y horario.\n"
    "_Si ya sos cliente habitual, un representante se comunica con vos directamente._\n\n"
    "Necesitamos:\n\n"
    "📤 *Quien envía:* nombre, teléfono y dirección con localidad\n"
    "📥 *Quien recibe:* nombre, teléfono, dirección y localidad\n"
    "🪪 *CUIT o DNI:* del remitente o del destinatario\n"
    "📦 *El envío:* qué mandás (bultos, peso y medidas aprox.) y valor declarado\n"
    "💲 *Pago:* en origen (paga quien envía) o en destino (paga quien recibe)"
)


def _recibir_retiro(s, texto):
    """Toma los datos del retiro en un solo mensaje y los manda al local."""
    texto = texto.strip()
    # Pedimos un mínimo de datos para no mandar un pedido vacío al local.
    tiene_tel = len(re.sub(r"\D", "", texto)) >= 8
    if len(texto) < 25 or not tiene_tel:
        return ["Me falta algo de información. Mandame en un mensaje los datos de quien "
                "envía y quien recibe (con teléfonos), qué enviás y dónde se paga.\n\n" + P_RETIRO]
    avisar_local(f"PEDIDO DE RETIRO de +{s['telefono']}:\n{texto}")
    _reiniciar(s)
    return ["✅ *Pedido de retiro recibido.*\n\n"
            "Un representante te contacta por este chat para confirmar el día y el horario.\n"
            "Si sos cliente habitual, nuestro representante ya se comunica con vos directamente.\n\n"
            "Tené el paquete *embalado* y, si declarás valor, la factura o remito." + PIE]


# ------------------------------------------------------------ 4. localidades

P_LOCALIDAD = "¿A qué *localidad* querés enviar? Escribí el nombre y te digo si llegamos."


def _paso_localidad(s, texto):
    def listo(loc):
        return [localidades.descripcion(loc) +
                "\n\nPodés consultar otra localidad, escribir *2* para cotizar o *menú* para volver."]
    return _elegir_localidad(s, texto, listo, P_LOCALIDAD)


# -------------------------------------------------------------- punto de entrada

def _empezar(s, opcion):
    _reiniciar(s)
    if opcion == 1:
        s["paso"] = "seguimiento"
        return ["Enviame tu *código de seguimiento*: el código de letras y números que figura "
                "en tu comprobante (por ejemplo: AB12CD)."]
    if opcion == 2:
        s["paso"] = "cot_retiro"
        s["datos"]["bultos"] = []
        return ["Te voy a pedir unos datos para cotizar. Podés escribir *cancelar* en cualquier momento.\n\n"
                + P_COT_RETIRO]
    if opcion == 3:
        s["paso"] = "retiro"
        return [P_RETIRO]
    if opcion == 4:
        s["paso"] = "localidad"
        return [P_LOCALIDAD]
    return _derivar(s, "Pidió hablar con un representante")


_SALUDOS = ("hola", "holaa", "holis", "buenas", "buen dia", "buen día", "buenos dias", "buenos días",
            "buenas tardes", "buenas noches", "hi")


def responder(telefono, texto):
    """Recibe el mensaje de un cliente y devuelve la lista de respuestas."""
    s = _sesion(telefono)
    s["telefono"] = telefono
    nuevo = s.pop("nuevo", False)
    texto = (texto or "").strip()
    bajo = texto.lower().strip(" .!¡?¿")
    paso = s["paso"] or ""

    if bajo in ("menu", "menú", "inicio", "cancelar", "salir", "volver"):
        _reiniciar(s)
        return [MENU]
    if bajo in _SALUDOS:
        _reiniciar(s)
        return [SALUDO]
    if bajo in ("representante", "humano", "persona", "asesor", "operador") or "hablar con" in bajo:
        return _derivar(s, "Pidió hablar con un representante")

    if paso.startswith("cot_"):
        return _paso_cotizacion(s, texto)
    if paso == "retiro":
        return _recibir_retiro(s, texto)

    # Fuera de un trámite: opciones del menú
    n = _opcion(texto, 5)
    if n and not s["datos"].get("opciones"):
        return _empezar(s, n)
    if paso == "localidad":
        return _paso_localidad(s, texto)

    codigo = _codigo_en(texto, seguro=(paso == "seguimiento"))
    if codigo:
        _reiniciar(s)
        return _responder_seguimiento(codigo)
    if paso == "seguimiento":
        return ["Eso no parece un código de seguimiento. Es el código corto de letras y números "
                "que figura en tu comprobante (por ejemplo: AB12CD)." + PIE]

    # Primer mensaje, o algo que no entendió: siempre muestra las opciones
    return [SALUDO if nuevo else "No llegué a entenderte. 😅\n\n" + MENU]
