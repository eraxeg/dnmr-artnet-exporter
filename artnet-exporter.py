import socket
import struct
import time
from prometheus_client import start_http_server, Gauge

ARTNET_PORT = 6454
EXPECTED_FPS = 44.0
# Expected FPS per universe
EXPECTED_FPS_PER_UNIVERSE = {
    0: 30.0,   # TouchDesigner
    1: 44.0,   # Portal
    2: 44.0,   # Blind
    3: 44.0,   # Shutter
    4: 44.0,   # Membrane Motors
    11: 1.0,  # Turntable
}

# Precompute intervals
EXPECTED_INTERVAL_PER_UNIVERSE = {u: 1.0/fps for u, fps in EXPECTED_FPS_PER_UNIVERSE.items()}
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

universe_time_since_last_packet = Gauge(
    "artnet_universe_time_since_last_packet_seconds",
    "Time since last ArtDMX packet was received",
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

    # Get expected interval for this universe, fallback to 44 FPS
    expected_interval = EXPECTED_INTERVAL_PER_UNIVERSE.get(universe, 1.0 / 44.0)

    # Compute time since last packet
    if universe in last_packet_time:
        interval = now - last_packet_time[universe]
        universe_time_since_last_packet.labels(universe_str).set(interval)

        # Raw jitter vs expected interval
        jitter = abs(interval - expected_interval)
        packet_interval.labels(universe_str).set(interval)
        packet_jitter.labels(universe_str).set(jitter)

        # EMA smoothing
        prev_ema = jitter_ema_state.get(universe, jitter)
        ema = (EMA_ALPHA * jitter) + ((1 - EMA_ALPHA) * prev_ema)
        jitter_ema_state[universe] = ema
        packet_jitter_ema.labels(universe_str).set(ema)

    else:
        # First packet: set time-since-last to 0
        universe_time_since_last_packet.labels(universe_str).set(0.0)

    # Update last packet time
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

        # --- Universe 4: Membrane Motors --
        elif universe == 4:
            value = parse_16bit(dmx_data, 210)
            if value is not None:
                device_position.labels("membrane_motor_1").set(value)
            value = parse_16bit(dmx_data, 212)
            if value is not None:
                device_position.labels("membrane_motor_2").set(value)

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
