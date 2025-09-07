import network
import time
from umqtt.simple import MQTTClient

WIFI_SSID   = "XXXXXX"
WIFI_PASS   = "XXXXXX"
BROKER_IP   = "XXXXXX"
CLIENT_ID   = "controlador_cruce_escenario1"

TOPICO_SOLICITUD = b"cruce/solicitud"
TOPICO_RESPUESTA = b"cruce/respuesta"
TOPICO_REPORTES  = b"cruce/reportes"

cruce_ocupado = False
active_robot = None
cola_espera = []
client = None

def conectar_wifi():
    print("Activando WiFi...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    print("Conectando a WiFi...")
    while not wlan.isconnected():
        time.sleep(1)
    print("Conectado a WiFi:", wlan.ifconfig())

def extraer_robot_id(msg):
    return msg.split(":")[0].strip()

def sub_cb(topic, msg):
    global cruce_ocupado, active_robot, cola_espera
    t = topic.decode()
    m = msg.decode()
    print("Mensaje recibido en", t, ":", m)
    if t == "cruce/solicitud":
        robot_id = extraer_robot_id(m)
        print("Solicitud de paso recibida de:", robot_id)
        if not cruce_ocupado:
            cruce_ocupado = True
            active_robot = robot_id
            print("Cruce libre. Autorizando paso a:", robot_id)
            client.publish(TOPICO_RESPUESTA, (robot_id + ":pasar").encode())
        else:
            print("Cruce ocupado por:", active_robot)
            if robot_id != active_robot and robot_id not in cola_espera:
                cola_espera.append(robot_id)
                print("Añadiendo a cola de espera:", robot_id)
            client.publish(TOPICO_RESPUESTA, (robot_id + ":esperar").encode())
    elif t == "cruce/reportes":
        parts = m.split(":")
        if len(parts) >= 2 and parts[1].strip() == "cruce_liberado":
            print("Reporte de cruce liberado por:", parts[0].strip())
            if parts[0].strip() == active_robot:
                cruce_ocupado = False
                active_robot = None
                print("Cruce liberado. Revisando cola de espera...")
                if cola_espera:
                    siguiente = cola_espera.pop(0)
                    cruce_ocupado = True
                    active_robot = siguiente
                    print("Autorizando paso a siguiente robot en cola:", siguiente)
                    client.publish(TOPICO_RESPUESTA, (siguiente + ":pasar").encode())

def main():
    global client
    conectar_wifi()
    print("Conectando al broker MQTT...")
    client = MQTTClient(CLIENT_ID, BROKER_IP)
    client.set_callback(sub_cb)
    client.connect()
    print("Conectado al broker MQTT")

    client.subscribe(TOPICO_SOLICITUD)
    client.subscribe(TOPICO_REPORTES)
    print("Suscrito a los tópicos:", TOPICO_SOLICITUD.decode(), "y", TOPICO_REPORTES.decode())

    client.publish(TOPICO_REPORTES, b"controlador_cruce_escenario1:listo")
    print("Mensaje de inicio publicado")
    
    while True:
        client.check_msg()
        time.sleep(0.1)

if __name__ == '__main__':
    main()