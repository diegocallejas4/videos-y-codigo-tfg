from machine import Pin, PWM
import time
from umqtt.robust import MQTTClient
import network

WIFI_SSID   = "XXXXX"
WIFI_PASS   = "XXXXX"
BROKER_IP   = "XXXXX"
CLIENT_ID   = "robotX"
ROBOT_TIPO  = "XXXXX"        # "vertical_A", "vertical_B" o "horizontal"

TOPICO_SOLICITUD  = b"cruce/solicitud"
TOPICO_RESPUESTA  = b"cruce/respuesta"
TOPICO_REPORTES   = b"cruce/reportes"
TOPICO_SYNC       = b"robots/solicitar_estado"

PIN_SERVO_IZQ = 13
PIN_SERVO_DER = 14
led = Pin(2, Pin.OUT)
servo_izq = PWM(Pin(PIN_SERVO_IZQ), freq=50)
servo_der = PWM(Pin(PIN_SERVO_DER), freq=50)
en_cruce = False
autorizado = False
esperando_autorizacion = False
client = None

def mover(d_izq, d_der):
    servo_izq.duty_u16(d_izq)
    servo_der.duty_u16(d_der)

def avanzar():
    print("[ROBOT] Avanzando...")
    mover(5060, 4390)

def detener():
    print("[ROBOT] Detenido.")
    mover(4800, 4700)

def led_parpadeo(intervalo, veces=1):
    for _ in range(veces):
        led.on(); time.sleep(intervalo)
        led.off(); time.sleep(intervalo)

def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        while not wlan.isconnected():
            time.sleep(0.5)
            led_parpadeo(0.1, 1)
    print("[ROBOT] WiFi conectado:", wlan.ifconfig())
    led.on()

def verificar_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print("[ROBOT] Reconectando WiFi...")
        conectar_wifi()

def procesar_mensaje(topic, msg):
    global autorizado, esperando_autorizacion
    t = topic.decode() if isinstance(topic, bytes) else topic
    m = msg.decode() if isinstance(msg, bytes) else msg
    if t == TOPICO_RESPUESTA.decode():
        try:
            who, orden = m.split(":", 1)
        except ValueError:
            return
        if who != CLIENT_ID:
            return
        orden = orden.strip()
        if orden == "pasar":
            print("[ROBOT] Permiso recibido -> pasar")
            autorizado = True
            esperando_autorizacion = False
        elif orden == "expulsado":
            print("[ROBOT] Expulsado por timeout")
            autorizado = False
            esperando_autorizacion = False
    elif t == TOPICO_SYNC.decode():
        if esperando_autorizacion or not en_cruce:
            print("[ROBOT] Sync recibido -> reenviando solicitud")
            solicitar_cruce()

def _suscribir_temas():
    client.subscribe(TOPICO_RESPUESTA, qos=1)
    client.subscribe(TOPICO_SYNC, qos=1)

def conectar_mqtt():
    global client
    verificar_wifi()
    client = MQTTClient(client_id=CLIENT_ID.encode(), server=BROKER_IP, keepalive=60)
    client.set_last_will(topic=TOPICO_REPORTES, msg=(CLIENT_ID + ":offline").encode(), retain=True, qos=1)
    client.set_callback(lambda t, m: procesar_mensaje(t, m))
    client.connect(clean_session=False)
    _suscribir_temas()
    client.publish(TOPICO_REPORTES, (CLIENT_ID + ":online").encode(), qos=1, retain=True)
    print("[ROBOT] MQTT conectado y suscrito")

def reconectar_mqtt():
    while True:
        try:
            print("[ROBOT] Reconectando MQTT...")
            client.connect(clean_session=False)
            _suscribir_temas()
            client.publish(TOPICO_REPORTES, (CLIENT_ID + ":online").encode(), qos=1, retain=True)
            print("[ROBOT] MQTT reconectado")
            return
        except Exception as e:
            print("[ROBOT] Fallo reconexión:", e)
            time.sleep(2)

def solicitar_cruce():
    global esperando_autorizacion, autorizado
    verificar_wifi()
    autorizado = False
    esperando_autorizacion = True
    try:
        client.publish(TOPICO_SOLICITUD, f"{CLIENT_ID}:{ROBOT_TIPO}".encode(), qos=1)
        print("[ROBOT] Solicitud enviada:", f"{CLIENT_ID}:{ROBOT_TIPO}".encode())
    except Exception as e:
        print("[ROBOT] Fallo al publicar solicitud, reconectando...", e)
        reconectar_mqtt()
        client.publish(TOPICO_SOLICITUD, f"{CLIENT_ID}:{ROBOT_TIPO}".encode(), qos=1)

def esperar_autorizacion(resend_interval_s=60):
    global autorizado
    print("[ROBOT] Esperando autorización...")
    ultimo_envio = time.time()
    while not autorizado:
        try:
            client.check_msg()
        except Exception:
            reconectar_mqtt()
        if time.time() - ultimo_envio >= resend_interval_s:
            print("[ROBOT] Timeout espera -> reenviando solicitud")
            solicitar_cruce()
            ultimo_envio = time.time()
        time.sleep(0.1)
    return True

def reportar_llegada():
    verificar_wifi()
    try:
        client.publish(TOPICO_REPORTES, (CLIENT_ID + ":llego").encode(), qos=1)
        print("[ROBOT] Reporte llego enviado")
        client.publish(TOPICO_REPORTES, (CLIENT_ID + ":cruce_liberado").encode(), qos=1)
        print("[ROBOT] Reporte cruce_liberado enviado")
    except Exception as e:
        print("[ROBOT] Error publicando reportes:", e)
        reconectar_mqtt()
        client.publish(TOPICO_REPORTES, (CLIENT_ID + ":llego").encode(), qos=1)
        client.publish(TOPICO_REPORTES, (CLIENT_ID + ":cruce_liberado").encode(), qos=1)

def main():
    global en_cruce
    detener()
    conectar_wifi()
    conectar_mqtt()
    avanzar()
    time.sleep(2)
    detener()
    solicitar_cruce()
    esperar_autorizacion(resend_interval_s=60)
    en_cruce = True
    avanzar()
    time.sleep(6)
    detener()
    reportar_llegada()
    en_cruce = False
    print("[ROBOT] Cruce completado.")
    avanzar()
    time.sleep(2)
    detener()
    try:
        client.disconnect()
        print("[ROBOT] Desconectado del broker MQTT.")
    except Exception as e:
        print("[ROBOT] Error al desconectar:", e)

if __name__ == "__main__":
    main()