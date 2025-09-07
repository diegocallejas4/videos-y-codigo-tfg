import network
import time
import machine
from umqtt.robust import MQTTClient

WIFI_SSID     = "XXXXX"
WIFI_PASS     = "XXXXX"
BROKER_IP     = "XXXXX"
CLIENT_ID     = b"controlador_cruce1_escenario3"

TOPICO_SOLICITUD   = b"cruce/solicitud"
TOPICO_RESPUESTA   = b"cruce/respuesta"
TOPICO_REPORTES    = b"cruce/reportes"
TOPICO_ESTADO_ACT  = b"cruce/estado/active_robot"
TOPICO_ESTADO_COLA = b"cruce/estado/cola"
TOPICO_SYNC        = b"robots/solicitar_estado"

cruce_ocupado = False
active_robot  = None
cola_espera   = []
prioridades   = { "robot1":1, "robot2":2, "robot3":3, "robot4":4 }
client = None

TIEMPO_MAX_CRUCE = 10
tiempo_inicio_cruce = 0
wdt = machine.WDT(timeout=150000)

def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    while not wlan.isconnected():
        time.sleep(1)
    print("WiFi OK", wlan.ifconfig())

def verificar_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print("WiFi desconectado. Reconectando...")
        wlan.active(True)
        wlan.connect(WIFI_SSID, WIFI_PASS)
        while not wlan.isconnected():
            time.sleep(1)
        print("WiFi reconectado:", wlan.ifconfig())

def extraer_robot_id(msg: bytes) -> str:
    return msg.decode().split(":", 1)[0].strip()

def obtener_prioridad(robot_id: str) -> int:
    return prioridades.get(robot_id, 99)

def publicar_estado():
    if active_robot:
        client.publish(TOPICO_ESTADO_ACT, active_robot.encode(), qos=1, retain=True)
    else:
        client.publish(TOPICO_ESTADO_ACT, b"", qos=1, retain=True)

    if cola_espera:
        cola_str = ",".join(cola_espera)
        client.publish(TOPICO_ESTADO_COLA, cola_str.encode(), qos=1, retain=True)
    else:
        client.publish(TOPICO_ESTADO_COLA, b"", qos=1, retain=True)

def restaurar_estado(topic, msg):
    global active_robot, cola_espera, cruce_ocupado, tiempo_inicio_cruce
    if topic == TOPICO_ESTADO_ACT:
        if msg and len(msg.strip()) > 0:
            active_robot = msg.decode().strip()
            cruce_ocupado = True
            tiempo_inicio_cruce = time.time()
            print("Estado restaurado: active_robot =", active_robot)
        else:
            active_robot = None
            cruce_ocupado = False
            print("Estado restaurado: sin robot activo")
    elif topic == TOPICO_ESTADO_COLA:
        if msg and len(msg.strip()) > 0:
            cola_espera[:] = msg.decode().strip().split(",")
            print("Estado restaurado: cola_espera =", sorted(cola_espera, key=obtener_prioridad))
        else:
            cola_espera.clear()
            print("Estado restaurado: cola vacía")

def procesar_mensaje(topic, msg):
    global cruce_ocupado, active_robot, cola_espera, tiempo_inicio_cruce
    if topic == TOPICO_SOLICITUD:
        if not msg or len(msg.strip()) == 0:
            return
        r = extraer_robot_id(msg)
        if r == active_robot:
            print("Solicitud repetida de robot activo, ignorando.")
            return
        print("Solicitud de paso recibida de:", r)
        if not cruce_ocupado:
            cruce_ocupado = True
            active_robot = r
            tiempo_inicio_cruce = time.time()
            print("Cruce libre. Autorizando paso a:", r)
            client.publish(TOPICO_RESPUESTA, f"{r}:pasar".encode(), qos=1)
            publicar_estado()
            client.publish(TOPICO_SOLICITUD, b"", qos=1, retain=True)
        else:
            print("Cruce ocupado por:", active_robot)
            if r != active_robot and r not in cola_espera:
                cola_espera.append(r)
                print("Añadiendo a cola de espera:", r)
            print("Cola de espera actual:", sorted(cola_espera, key=obtener_prioridad))
            client.publish(TOPICO_RESPUESTA, f"{r}:esperar".encode(), qos=1)
    elif topic == TOPICO_REPORTES:
        origen, evento = msg.decode().split(":", 1)
        if evento == "cruce_liberado" and origen == active_robot:
            print("Cruce liberado por:", origen)
            cruce_ocupado = False
            active_robot = None
            tiempo_inicio_cruce = 0
            publicar_estado()
            if cola_espera:
                siguiente = sorted(cola_espera, key=obtener_prioridad)[0]
                cola_espera.remove(siguiente)
                cruce_ocupado = True
                active_robot = siguiente
                tiempo_inicio_cruce = time.time()
                print("Autorizando paso a robot con prioridad:", siguiente)
                client.publish(TOPICO_RESPUESTA, f"{siguiente}:pasar".encode(), qos=1)
                publicar_estado()
            print("Cola de espera actual:", sorted(cola_espera, key=obtener_prioridad))

def revisar_timeout():
    global cruce_ocupado, active_robot, tiempo_inicio_cruce
    if cruce_ocupado and active_robot:
        ahora = time.time()
        if ahora - tiempo_inicio_cruce > TIEMPO_MAX_CRUCE:
            print("Timeout:", active_robot, "ha tardado demasiado. Liberando el cruce.")
            client.publish(TOPICO_REPORTES, f"{active_robot}:timeout".encode(), qos=1)
            client.publish(TOPICO_RESPUESTA, f"{active_robot}:expulsado".encode(), qos=1)
            cruce_ocupado = False
            active_robot = None
            tiempo_inicio_cruce = 0
            publicar_estado()
            if cola_espera:
                siguiente = sorted(cola_espera, key=obtener_prioridad)[0]
                cola_espera.remove(siguiente)
                cruce_ocupado = True
                active_robot = siguiente
                tiempo_inicio_cruce = time.time()
                print("Autorizando paso a robot con prioridad:", siguiente)
                client.publish(TOPICO_RESPUESTA, f"{siguiente}:pasar".encode(), qos=1)
                publicar_estado()
            print("Cola de espera actual:", sorted(cola_espera, key=obtener_prioridad))
            
def conectar_broker():
    global client
    while True:
        try:
            client = MQTTClient(client_id=CLIENT_ID, server=BROKER_IP, keepalive=60)
            client.set_last_will(topic=TOPICO_REPORTES, msg=CLIENT_ID + b":offline", retain=True, qos=1)
            client.connect(clean_session=False)
            print("Conectado al broker MQTT")
            break
        except OSError as e:
            print("Broker no disponible. Reintentando en 5s...", e)
            time.sleep(5)

def inicializar_mqtt():
    global tiempo_inicio_cruce
    client.set_callback(restaurar_estado)
    client.subscribe(TOPICO_ESTADO_ACT, qos=1)
    client.subscribe(TOPICO_ESTADO_COLA, qos=1)
    client.check_msg()
    client.publish(TOPICO_SYNC, b"reanunciar", qos=1)
    client.set_callback(procesar_mensaje)
    client.subscribe(TOPICO_SOLICITUD, qos=1)
    client.subscribe(TOPICO_REPORTES, qos=1)
    client.publish(TOPICO_REPORTES, CLIENT_ID + b":online", qos=1, retain=True)
    publicar_estado()
    print("Estado inicial publicado.")
    if cruce_ocupado and active_robot:
        tiempo_inicio_cruce = time.time()
        print("Reconexión: reinicio contador de cruce para", active_robot)

def main():
    global client
    conectar_wifi()
    conectar_broker()
    inicializar_mqtt()
    while True:
        try:
            verificar_wifi()
            client.check_msg()
            revisar_timeout()
        except OSError as e:
            print("MQTT desconectado. Reintentando en 5s...", e)
            time.sleep(5)
            conectar_broker()
            inicializar_mqtt()
        except Exception as e:
            print("Error de bucle:", e)
        wdt.feed()
        time.sleep(0.5)

if __name__ == "__main__":
    main()