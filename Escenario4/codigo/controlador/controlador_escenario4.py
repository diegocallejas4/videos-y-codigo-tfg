import network
import time
import machine
from umqtt.robust import MQTTClient

WIFI_SSID = "XXXXXX"
WIFI_PASS = "XXXXXX"
BROKER_IP = "XXXXXX"
CLIENT_ID = b"controlador_escenario4"

TOPICO_SOLICITUD = b"cruce/solicitud"
TOPICO_RESPUESTA = b"cruce/respuesta"
TOPICO_REPORTES  = b"cruce/reportes"
TOPICO_ESTADO_ACT = b"cruce/estado/active_robot"
TOPICO_ESTADO_COLA = b"cruce/estado/cola"
TOPICO_SYNC = b"robots/solicitar_estado"

recursos = {"I1": False, "I2": False}
colas_verticales = {"vertical_A": [], "vertical_B": []}
cola_horizontal = []
tipo_por_robot = {}
tiempo_inicio = {}
prioridades = {"robot1": 1, "robot2": 2, "robot3": 3, "robot4": 4}
TIEMPO_MAX_CRUCE = 10
wdt = machine.WDT(timeout=150000)

client = None

def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        while not wlan.isconnected():
            time.sleep(0.5)
    print("WiFi conectado:", wlan.ifconfig())

def verificar_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print("WiFi desconectado. Reconectando...")
        conectar_wifi()

def publicar_estado():
    if tipo_por_robot:
        activos = ",".join(tipo_por_robot.keys())
        client.publish(TOPICO_ESTADO_ACT, activos.encode(), qos=1, retain=True)
    else:
        client.publish(TOPICO_ESTADO_ACT, b"", qos=1, retain=True)
    partes = [
        f"vertical_A|{','.join(colas_verticales['vertical_A'])}",
        f"vertical_B|{','.join(colas_verticales['vertical_B'])}",
        f"horizontal|{','.join(cola_horizontal)}"
    ]
    payload = ";".join(partes).encode()
    client.publish(TOPICO_ESTADO_COLA, payload, qos=1, retain=True)

def restaurar_estado(topic, msg):
    texto = msg.decode().strip()
    if topic == TOPICO_ESTADO_ACT:
        if texto:
            robots = texto.split(",")
            if not any(recursos.values()):
                print("[CONTROL] Estado retenido pero sin recursos -> ignorado")
                tipo_por_robot.clear()
            else:
                for r in robots:
                    tipo_por_robot.setdefault(r, [])
                    tiempo_inicio[r] = time.time()
                print("Recuperado active_robot(s):", robots)
        else:
            tipo_por_robot.clear()
            print("No hay active_robot retenido.")
    elif topic == TOPICO_ESTADO_COLA:
        if texto:
            partes = texto.split(";")
            for parte in partes:
                if "|" not in parte:
                    continue
                zona, lst = parte.split("|", 1)
                robots = lst.split(",") if lst else []
                if zona in colas_verticales:
                    colas_verticales[zona] = [r for r in robots if r]
                elif zona == "horizontal":
                    cola_horizontal[:] = [r for r in robots if r]
            print("Recuperadas colas:", colas_verticales, cola_horizontal)
        else:
            print("Colas retenidas vacías.")

def otorgar_permiso(robot_id, lista_recursos):
    for r in lista_recursos:
        recursos[r] = True
    tipo_por_robot[robot_id] = lista_recursos
    tiempo_inicio[robot_id] = time.time()
    client.publish(TOPICO_RESPUESTA, f"{robot_id}:pasar".encode(), qos=1)
    publicar_estado()
    print(f"[CONTROL] Permiso a {robot_id} -> {lista_recursos}")

def liberar_recursos(robot_id):
    res_list = tipo_por_robot.pop(robot_id, [])
    if not res_list:
        print(f"[CONTROL] liberar_recursos: {robot_id} no tenía recursos asignados.")
    else:
        print(f"[CONTROL] Liberando recursos {res_list} de {robot_id}")
        for r in res_list:
            recursos[r] = False
    tiempo_inicio.pop(robot_id, None)
    publicar_estado()
    reasignar_esperas()

def reasignar_esperas():
    while True:
        servido = False
        proximo_A = None
        proximo_B = None
        proximo_H = None
        if colas_verticales["vertical_A"]:
            colas_verticales["vertical_A"].sort(key=lambda rid: prioridades.get(rid, 99))
            proximo_A = colas_verticales["vertical_A"][0]
        if colas_verticales["vertical_B"]:
            colas_verticales["vertical_B"].sort(key=lambda rid: prioridades.get(rid, 99))
            proximo_B = colas_verticales["vertical_B"][0]
        if cola_horizontal:
            cola_horizontal.sort(key=lambda rid: prioridades.get(rid, 99))
            proximo_H = cola_horizontal[0]
        if (not recursos["I1"]) and (not recursos["I2"]) and proximo_H:
            pr_H = prioridades.get(proximo_H, 99)
            pr_A = prioridades.get(proximo_A, 99) if proximo_A else 999
            pr_B = ninguna_prioridad(proximo_B)
            if pr_H < pr_A and pr_H < pr_B:
                cola_horizontal.pop(0)
                otorgar_permiso(proximo_H, ["I1", "I2"])
                servido = True
                continue
        if (not recursos["I1"]) and proximo_A:
            colas_verticales["vertical_A"].pop(0)
            otorgar_permiso(proximo_A, ["I1"])
            servido = True
            continue
        if (not recursos["I2"]) and proximo_B:
            colas_verticales["vertical_B"].pop(0)
            otorgar_permiso(proximo_B, ["I2"])
            servido = True
            continue
        if not servido:
            break

def ninguna_prioridad(candidate):
    return obtener_prioridad(candidate, default=999)

def obtener_prioridad(rid, default=999):
    return prioridades.get(rid, default)

def procesar_mensaje(topic, msg):
    try:
        if topic == TOPICO_SOLICITUD:
            text = msg.decode()
            if ":" not in text:
                print("[CONTROL] solicitud formato inválido:", text)
                return
            robot_id, tipo = text.split(":", 1)
            robot_id = robot_id.strip()
            tipo = tipo.strip()
            print(f"[CONTROL] Solicitud de {robot_id} tipo {tipo}")
            if tipo == "vertical_A":
                if not recursos["I1"]:
                    otorgar_permiso(robot_id, ["I1"])
                else:
                    if robot_id not in colas_verticales["vertical_A"]:
                        colas_verticales["vertical_A"].append(robot_id)
            elif tipo == "vertical_B":
                if not recursos["I2"]:
                    otorgar_permiso(robot_id, ["I2"])
                else:
                    if robot_id not in colas_verticales["vertical_B"]:
                        colas_verticales["vertical_B"].append(robot_id)
            elif tipo == "horizontal":
                if (not recursos["I1"]) and (not recursos["I2"]):
                    otorgar_permiso(robot_id, ["I1", "I2"])
                else:
                    if robot_id not in cola_horizontal:
                        cola_horizontal.append(robot_id)
        elif topic == TOPICO_REPORTES:
            origen, evento = msg.decode().split(":", 1)
            origen = origen.strip()
            evento = evento.strip()
            if evento in ("cruce_liberado", "expulsado", "offline"):
                if origen in tipo_por_robot or origen in sum(list(colas_verticales.values()), []) or origen in cola_horizontal:
                    print(f"[CONTROL] Reporte {evento} de {origen}")
                    if origen in tipo_por_robot:
                        liberar_recursos(origen)
                    else:
                        quitar_de_colas(origen)
                        publicar_estado()
    except Exception as e:
        print("[CONTROL] Error en procesar_mensaje:", e)

def quitar_de_colas(robot_id):
    for k in colas_verticales:
        if robot_id in colas_verticales[k]:
            colas_verticales[k] = [r for r in colas_verticales[k] if r != robot_id]
    if robot_id in cola_horizontal:
        cola_horizontal[:] = [r for r in cola_horizontal if r != robot_id]

def revisar_timeout():
    ahora = time.time()
    for robot_id, inicio in list(tiempo_inicio.items()):
        if ahora - inicio > TIEMPO_MAX_CRUCE:
            print("[CONTROL] Timeout:", robot_id)
            try:
                client.publish(TOPICO_REPORTES, f"{robot_id}:expulsado".encode(), qos=1)
            except Exception as e:
                print("[CONTROL] No se pudo publicar timeout:", e)
            if robot_id in tipo_por_robot:
                liberar_recursos(robot_id)
            else:
                quitar_de_colas(robot_id)
                publicar_estado()

def conectar_broker():
    global client
    while True:
        try:
            client = MQTTClient(client_id=CLIENT_ID, server=BROKER_IP, keepalive=60)
            client.set_last_will(topic=TOPICO_REPORTES, msg=CLIENT_ID + b":offline", retain=True, qos=1)
            client.connect(clean_session=False)
            print("[CONTROL] Conectado al broker MQTT")
            return
        except Exception as e:
            print("[CONTROL] Broker no disponible. Reintentando en 5s...", e)
            time.sleep(5)

def inicializar_mqtt():
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
    print("[CONTROL] Inicializado MQTT y publicado estado inicial.")
def main():
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
            print("Error loop principal:", e)
        wdt.feed()
        time.sleep(0.1)

if __name__ == "__main__":
    main()