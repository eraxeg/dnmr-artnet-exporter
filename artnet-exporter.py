import socket
import struct
import time
from prometheus_client import start_http_server, Gauge

ARTNET_PORT = 6454
EXPECTED_FPS = 44.0
EXPECTED_INTERVAL = 1.0 / EXPECTED_FPS
EMA_ALPHA = 0.2  # smoothing factor

# --- Combined position metric ---
device_position = Gauge(
    "device_position",
    "16bit position value of devices moving in one dimension",
    ["device"]
)

# --- Portal metrics ---
portal = Gauge("portal_position", "Portal position", ['x', 'y'])
portal_rotation = Gauge("portal_rotation", "Portal rotation")
portal_robot = Gauge("portal_robot", "Portal robot values", ['1', '2'])

# --- Packet timestamps ---
universe_last_packet = Gauge(
    "artnet_universe_last_packet_timestamp",
    "Unix timestamp of last ArtDMX packet received",
    ["universe"]
)

# --- Interval + jitter metrics ---
packet_interval = Gauge(
    "artnet_universe_packet_interval_seconds",
    "Time between consecutive ArtDMX packets",
    ["universe"]
)

packet_jitter = Gauge(
    "artnet_universe_jitter_seconds",
    "Absolute jitter vs expected interval",
    ["universe"]
)

packet_jitter_ema = Gauge(
    "artnet_universe_jitter_ema_seconds",
    "Smoothed jitter (EMA)",
    ["universe"]
)

# --- State tracking ---
last_packet_time = {}
jitter_ema_state = {}


def parse_16bit(data, offset):
    if len(data) >= offset + 2:
        return (data[offset] << 8) | data[offset + 1]
    return None


def update_timing(universe, now):
    universe_str = str(universe)

    if universe in last_packet_time:
        interval = now - last_packet_time[universe]
        packet_interval.labels(universe_str).set(interval)

        jitter = abs(interval - EXPECTED_INTERVAL)
        packet_jitter.labels(universe_str).set(jitter)

        # EMA smoothing
        prev_ema = jitter_ema_state.get(universe, jitter)
        ema = (EMA_ALPHA * jitter) + ((1 - EMA_ALPHA) * prev_ema)
        jitter_ema_state[universe] = ema
        packet_jitter_ema.labels(universe_str).set(ema)

    last_packet_time[universe] = now


def listen():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", ARTNET_PORT))

    while True:
        packet, _ = sock.recvfrom(1024)

        if packet[:8] != b'Art-Net\x00':
            continue

        opcode = struct.unpack('<H', packet[8:10])[0]
        if opcode != 0x5000:  # ArtDMX
            continue

        universe = struct.unpack('<H', packet[14:16])[0]
        length = struct.unpack('>H', packet[16:18])[0]
        dmx_data = packet[18:18+length]

        now = time.time()

        # Timestamp metric
        universe_last_packet.labels(str(universe)).set(now)

        # Jitter measurement
        update_timing(universe, now)

        # --- Universe 11: Turntable ---
        if universe == 11:
            value = parse_16bit(dmx_data, 0)
            if value is not None:
                device_position.labels("turntable").set(value)

        # --- Universe 2: Blind ---
        elif universe == 2:
            value = parse_16bit(dmx_data, 0)
            if value is not None:
                device_position.labels("blind").set(value)

        # --- Universe 3: Shutter ---
        elif universe == 3:
            value = parse_16bit(dmx_data, 0)
            if value is not None:
                device_position.labels("shutter").set(value)

        # --- Universe 1: Portal ---
        elif universe == 1:
            if len(dmx_data) >= 10:
                portal.labels(x=parse_16bit(dmx_data, 0), y=parse_16bit(dmx_data, 8)).set(parse_16bit(dmx_data, 4))
                portal_rotation.set(parse_16bit(dmx_data, 2))
                portal_robot.labels('1', '2').set(parse_16bit(dmx_data, 6), parse_16bit(dmx_data, 4))


if __name__ == "__main__":
    start_http_server(9288)
    print("Exporter running on :9288/metrics")
    listen()