from machine import Pin, PWM
import time
from umqtt.simple import MQTTClient
import network

WIFI_SSID   = "XXXXXXX"
WIFI_PASS   = "XXXXXXX" 
BROKER_IP   = "XXXXXXX"
CLIENT_ID   = "robotX"

TOPICO_SOLICITUD = b"cruce/solicitud"
TOPICO_RESPUESTA = b"cruce/respuesta"
TOPICO_REPORTES  = b"cruce/reportes"

PIN_SERVO_IZQ = 13
PIN_SERVO_DER = 14

led = Pin(2, Pin.OUT)

servo_izq = PWM(Pin(PIN_SERVO_IZQ), freq=50)
servo_der = PWM(Pin(PIN_SERVO_DER), freq=50)

en_cruce = False

def mover(d_izq, d_der):
    servo_izq.duty_u16(d_izq)
    servo_der.duty_u16(d_der)

def avanzar():
    print("[ROBOT] Avanzando...")
    mover(4940, 4413)

def detener():
    print("[ROBOT] Detenido.")
    mover(4700, 4800)

def led_parpadeo(intervalo, veces=None):
    count = 0
    while veces is None or count < veces:
        led.on()
        time.sleep(intervalo)
        led.off()
        time.sleep(intervalo)
        count += 1
        
def led_encendido():
    led.on()

def led_apagado():
    led.off()

def conectar_wifi():
    print("[ROBOT] Conectando a WiFi...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    while not wlan.isconnected():
        led_parpadeo(0.2, 1)
        time.sleep(1)
    print("[ROBOT] WiFi conectado:", wlan.ifconfig())
    led_encendido()

def on_mensaje(topic, msg):
    global en_cruce
    print(f"[ROBOT] Mensaje recibido en {topic}: {msg}")
    if msg.decode().startswith(CLIENT_ID + ":pasar"):
        print("[ROBOT] Permiso para cruzar recibido.")
        en_cruce = True

def main():
    detener()
    conectar_wifi()
    print("[ROBOT] Conectando al broker MQTT...")
    client = MQTTClient(CLIENT_ID, BROKER_IP)
    client.set_callback(on_mensaje)
    client.connect()
    print("[ROBOT] Conectado al broker como", CLIENT_ID)
    client.subscribe(TOPICO_RESPUESTA)
    print("[ROBOT] Suscrito a:", TOPICO_RESPUESTA)
    time.sleep(2)
    avanzar()
    time.sleep(4)
    detener()
    client.publish(TOPICO_SOLICITUD, CLIENT_ID.encode() + b":solicitud")
    print("[ROBOT] Solicitud de cruce enviada.")
    print("[ROBOT] Esperando permiso para cruzar...")
    while not en_cruce:
        client.check_msg()
        time.sleep(0.1)
    avanzar()
    time.sleep(4)
    detener()
    client.publish(TOPICO_REPORTES, CLIENT_ID.encode() + b":llego")
    print("[ROBOT] Reporte enviado: llego")
    client.publish(TOPICO_REPORTES, CLIENT_ID.encode() + b":cruce_liberado")
    print("[ROBOT] Reporte enviado: cruce liberado")
    time.sleep(2)
    avanzar()
    time.sleep(4)
    detener()
    print("[ROBOT] Cruce completado.")
    time.sleep(1000)

if __name__ == '__main__':
    main()