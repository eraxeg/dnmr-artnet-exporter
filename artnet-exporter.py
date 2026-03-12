import csv
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
    5: 44.0,   # Heliostat
    11: 1.0,  # Turntable
}

# Precompute intervals
EXPECTED_INTERVAL_PER_UNIVERSE = {u: 1.0/fps for u, fps in EXPECTED_FPS_PER_UNIVERSE.items()}
EMA_ALPHA = 0.2  # smoothing factor

# Universe 1 mapping

dmx_descriptions = {}

with open("universe_0.csv", newline='') as csvfile:
    reader = csv.DictReader(csvfile, delimiter=',')
    for row in reader:
        if row['DMX ch (universe 0)']:  # skip empty rows
            channel = int(row['DMX ch (universe 0)'])
            description = row['Device']
            dmx_descriptions[channel] = description

# --- Combined position metric ---
device_position = Gauge(
    "device_position",
    "16bit position value of devices moving in one dimension",
    ["device"]
)

# --- Portal metrics ---
portal = Gauge("portal", "Portal position", ['axis'])
heliostat = Gauge("heliostat", "Heliostat #1 position", ['axis'])

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

dmx_broadcast_values = Gauge( "dmx_broadcast_channel_value", 
    "Captured broadcast dmx channel value", 
    ["channel_number", "description", "universe"] )

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

        # --- Universe 5: Heliostat ---
        elif universe == 5:
            if len(dmx_data) >= 4:
                heliostat.labels(axis='azimuth').set(parse_16bit(dmx_data, 0))
                heliostat.labels(axis='elevation').set(parse_16bit(dmx_data, 2))

        # --- Universe 1: Portal ---
        elif universe == 1:
            if len(dmx_data) >= 10:
                portal.labels(axis='x').set(parse_16bit(dmx_data, 0))
                portal.labels(axis='y').set(parse_16bit(dmx_data, 8))
                portal.labels(axis='rotation').set(parse_16bit(dmx_data, 2))
                portal.labels(axis='1').set(parse_16bit(dmx_data, 6))
                portal.labels(axis='2').set(parse_16bit(dmx_data, 4))
        
        elif universe == 0:
            for i in range(length):
                channel_number = i + 1
                value = dmx_data[i]
                description = dmx_descriptions.get(channel_number, "")  # default to empty string if not found
                # Skip channels with no description or value 0
                if not description or value == 0:
                    continue

                dmx_broadcast_values.labels(str(channel_number), description, str(universe)).set(value)



if __name__ == "__main__":
    start_http_server(9288)
    print("Exporter running on :9288/metrics")
    listen()
