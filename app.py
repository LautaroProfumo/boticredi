"""Servidor de Boticredi: conecta WhatsApp (Cloud API de Meta) con boticredi.py.

Arrancar:  python app.py      (necesita las variables del archivo .env)
"""
import hashlib
import hmac
import os
import re
import threading
import time

import requests
from flask import Flask, abort, request

import boticredi

# Mensaje de cierre si el cliente deja de responder un rato.
MINUTOS_INACTIVIDAD = 10
MENSAJE_DESPEDIDA = (
    "¡Muchas gracias por comunicarte con nosotros! 🙌\n"
    "Quedamos a tu disposición para lo que necesites.\n\n"
    "Credifin Express Tres de Febrero"
)

TOKEN = os.getenv("WHATSAPP_TOKEN", "")            # token de acceso de Meta
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")      # ID del número de WhatsApp
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "")       # palabra que inventás vos
APP_SECRET = os.getenv("APP_SECRET", "")           # opcional: clave secreta de la app de Meta
AVISO_NUMERO = os.getenv("AVISO_NUMERO", "")       # opcional: celular que recibe las derivaciones (549...)
GRAPH = f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION', 'v21.0')}"

app = Flask(__name__)
_ya_vistos = []  # ids de mensajes ya procesados (Meta a veces reenvía)


def _normalizar(telefono):
    """Argentina: WhatsApp manda 549XXXXXXXXXX, pero la API quiere 54XXXXXXXXXX."""
    numero = re.sub(r"\D", "", telefono or "")
    if numero.startswith("549"):
        numero = "54" + numero[3:]
    return numero


def enviar(telefono, texto):
    r = requests.post(
        f"{GRAPH}/{PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"messaging_product": "whatsapp", "to": _normalizar(telefono), "type": "text",
              "text": {"body": texto, "preview_url": False}},
        timeout=15,
    )
    if r.status_code >= 400:
        print("[ERROR al enviar]", r.status_code, r.text[:300])


def _avisar_local(texto):
    print("[AVISO AL LOCAL]", texto)
    if AVISO_NUMERO:
        enviar(AVISO_NUMERO, "🔔 Boticredi: " + texto)


boticredi.avisar_local = _avisar_local


def _vigilar_inactividad():
    """Cada minuto revisa las charlas y manda el cierre si pasaron 10 min sin respuesta."""
    while True:
        time.sleep(60)
        ahora = time.time()
        for telefono, s in list(boticredi._sesiones.items()):
            if s.get("despedido"):
                continue
            if ahora - s.get("visto", 0) >= MINUTOS_INACTIVIDAD * 60:
                try:
                    enviar(telefono, MENSAJE_DESPEDIDA)
                except Exception as e:  # que un fallo no corte el vigía
                    print("[despedida] error:", repr(e))
                s["despedido"] = True


threading.Thread(target=_vigilar_inactividad, daemon=True).start()


@app.get("/webhook")
def verificar():
    """Meta llama acá una sola vez para comprobar que el servidor es tuyo."""
    if VERIFY_TOKEN and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge", "")
    abort(403)


@app.post("/webhook")
def recibir():
    if APP_SECRET:
        firma = request.headers.get("X-Hub-Signature-256", "")
        esperada = "sha256=" + hmac.new(APP_SECRET.encode(), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(firma, esperada):
            abort(403)

    datos = request.get_json(silent=True) or {}
    for entrada in datos.get("entry", []):
        for cambio in entrada.get("changes", []):
            for msj in cambio.get("value", {}).get("messages", []) or []:
                if msj.get("id") in _ya_vistos:
                    continue
                _ya_vistos.append(msj.get("id"))
                del _ya_vistos[:-500]
                telefono = msj.get("from")
                if msj.get("type") == "text":
                    texto = msj["text"]["body"]
                elif msj.get("type") == "interactive":
                    i = msj["interactive"]
                    texto = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                else:
                    enviar(telefono, "Por ahora solo puedo leer mensajes de texto. Escribí *menú* para ver las opciones.")
                    continue
                try:
                    respuestas = boticredi.responder(telefono, texto)
                except Exception as e:  # que un error no deje al cliente sin respuesta
                    print("[ERROR]", repr(e))
                    respuestas = ["Tuve un problema para responderte. Escribí *5* para hablar con una persona."]
                # El cliente volvió a escribir: permitir una nueva despedida más adelante.
                sesion = boticredi._sesiones.get(telefono)
                if sesion:
                    sesion["despedido"] = False
                for r in respuestas:
                    enviar(telefono, r)
    return "ok"


@app.get("/")
def inicio():
    return "Boticredi está funcionando."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
