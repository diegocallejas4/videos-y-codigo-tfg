from machine import Pin, PWM
import time, machine
from umqtt.robust import MQTTClient
import network

WIFI_SSID   = "XXXXX"
WIFI_PASS   = "XXXXX"
BROKER_IP   = "XXXXX"
CLIENT_ID   = "robotX"

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
preparado_para_preguntar = False
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

def led_parpadeo(intervalo, veces=None):
    count = 0
    while veces is None or count < veces:
        led.on(); time.sleep(intervalo)
        led.off(); time.sleep(intervalo)
        count += 1

def led_encendido():
    led.on()
    
def led_apagado():
    led.off()

def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    while not wlan.isconnected():
        led_parpadeo(0.2, 1)
        time.sleep(1)
    print("WiFi conectado:", wlan.ifconfig())
    led_encendido()

def verificar_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print("WiFi desconectado. Reconectando...")
        wlan.active(True)
        wlan.connect(WIFI_SSID, WIFI_PASS)
        while not wlan.isconnected():
            time.sleep(1)
        print("WiFi reconectado:", wlan.ifconfig())
        led_encendido()

def procesar_mensaje(topic, msg):
    global autorizado, esperando_autorizacion
    if topic == TOPICO_RESPUESTA:
        try:
            who, orden = msg.split(b":", 1)
        except ValueError:
            return
        if who.decode() != CLIENT_ID:
            return
        orden = orden.decode()
        if orden == "pasar":
            print("Permiso recibido.")
            autorizado = True
            esperando_autorizacion = False
        elif orden == "expulsado":
            print("Expulsado por timeout.")
            autorizado = False
            esperando_autorizacion = False
            client.disconnect()
            machine.deepsleep()
    elif topic == TOPICO_SYNC:
        if esperando_autorizacion and preparado_para_preguntar:
            print("Controlador solicita estado -> reenviando solicitud")
            solicitar_cruce()

def suscribir_temas():
    client.subscribe(TOPICO_RESPUESTA, qos=1)
    client.subscribe(TOPICO_SYNC, qos=1)

def conectar_mqtt():
    global client
    verificar_wifi()
    client = MQTTClient(client_id=CLIENT_ID, server=BROKER_IP, keepalive=60)
    client.set_last_will(topic=TOPICO_REPORTES, msg=(CLIENT_ID + ":offline").encode(), retain=True, qos=1)
    client.set_callback(procesar_mensaje)
    client.connect(clean_session=False)
    suscribir_temas()
    print("MQTT conectado y suscrito.")

def reconectar_mqtt():
    while True:
        try:
            print("Reconectando MQTT...")
            client.set_callback(procesar_mensaje)
            client.connect(clean_session=False)
            suscribir_temas()
            if esperando_autorizacion and not autorizado:
                solicitar_cruce()
            client.publish(TOPICO_REPORTES, (CLIENT_ID + ":online").encode(), qos=1, retain=True)
            print("MQTT reconectado.")
            return
        except Exception as e:
            print("Fallo reconexión:", e)
            time.sleep(2)

def solicitar_cruce():
    global esperando_autorizacion, autorizado
    verificar_wifi()
    autorizado = False
    esperando_autorizacion = True
    try:
        client.publish(TOPICO_SOLICITUD, CLIENT_ID.encode() + b":solicitud", qos=1)
        print("Solicitud enviada.")
    except Exception:
        reconectar_mqtt()
        client.publish(TOPICO_SOLICITUD, CLIENT_ID.encode() + b":solicitud", qos=1)

def esperar_autorizacion(resend_interval_s=60):
    global autorizado
    print("Esperando autorización...")
    t0 = time.time()
    ultimo_envio = t0
    while not autorizado:
        try:
            client.check_msg()
        except Exception:
            reconectar_mqtt()
        ahora = time.time()
        if ahora - ultimo_envio >= resend_interval_s:
            print("No hay autorización tras 1 minuto, reenviando solicitud...")
            solicitar_cruce()
            ultimo_envio = ahora
        time.sleep(0.1)
    return True

def reportar_llegada():
    verificar_wifi()
    try:
        client.publish(TOPICO_REPORTES, CLIENT_ID.encode() + b":llego", qos=1)
        print("He llegado.")
        client.publish(TOPICO_REPORTES, CLIENT_ID.encode() + b":cruce_liberado", qos=1)
        print("Cruce liberado.")
    except Exception:
        reconectar_mqtt()
        client.publish(TOPICO_REPORTES, CLIENT_ID.encode() + b":llego", qos=1)
        client.publish(TOPICO_REPORTES, CLIENT_ID.encode() + b":cruce_liberado", qos=1)

def main():
    global en_cruce
    detener()
    conectar_wifi()
    conectar_mqtt()
    avanzar();
    time.sleep(4);
    detener()
    preparado_para_preguntar = True
    solicitar_cruce()
    esperar_autorizacion(resend_interval_s=60)
    en_cruce = True
    avanzar()
    time.sleep(4)
    detener()
    reportar_llegada()
    en_cruce = False
    print("Cruce completado.")
    avanzar()
    time.sleep(2)
    detener()
    try:
        client.disconnect()
        print("Desconectado del broker MQTT.")
    except Exception as e:
        print("Error al desconectar:", e)

if __name__ == "__main__":
    main()