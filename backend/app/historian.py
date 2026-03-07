import asyncio
import logging

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from .config import settings

logger = logging.getLogger(__name__)

# How often to write a data point to InfluxDB (seconds)
WRITE_INTERVAL = 5


class Historian:
    def __init__(self, factoryio_client):
        # We hold a reference to the Modbus client so we can read its current state
        self.client = factoryio_client
        self._influx = None
        self._write_api = None
        self._running = False
        self._tick = 0

    def connect(self):
        """Open the InfluxDB connection."""
        self._influx = InfluxDBClient(
            url=settings.influx_url,
            token=settings.influx_token,
            org=settings.influx_org,
        )
        self._write_api = self._influx.write_api(write_options=SYNCHRONOUS)
        logger.info(f"Historian connected to InfluxDB at {settings.influx_url}")

    def disconnect(self):
        """Close the InfluxDB connection."""
        if self._influx:
            self._influx.close()
        self._running = False

    async def start(self):
        """Connect to InfluxDB and start the background write loop."""
        self.connect()
        self._running = True
        asyncio.create_task(self._write_loop())

    async def _write_loop(self):
        """
        Background task that wakes up every second but only writes to
        InfluxDB every WRITE_INTERVAL seconds. This keeps the loop
        responsive to shutdown without a long sleep.
        """
        while self._running:
            await asyncio.sleep(1)
            self._tick += 1
            if self._tick % WRITE_INTERVAL != 0:
                continue

            try:
                state = self.client.state

                # Each Point is one row in InfluxDB — tagged by plant ID so
                # queries can filter by plant if you ever add a second one
                point = (
                    Point("plant_state")
                    .tag("plant", "T001_WaterTreatment")
                    .field("tank_level", state.tank_level)
                    .field("flow_rate", state.flow_rate)
                    .field("setpoint", state.setpoint)
                    .field("running", int(state.running))
                    .field("fill_valve_open", int(state.fill_valve_open))
                    .field("discharge_valve_open", int(state.discharge_valve_open))
                    .field("alarm_count", len(state.alarms))
                )

                self._write_api.write(
                    bucket=settings.influx_bucket,
                    org=settings.influx_org,
                    record=point,
                )
                logger.debug(f"Historian wrote point — level={state.tank_level:.1f}%")

            except Exception as exc:
                # Log but don't crash — a historian failure should never
                # take down the rest of the SCADA system
                logger.error(f"Historian write error: {exc}")

    def query(self, field: str, minutes: int = 60) -> list:
        """
        Fetch the last N minutes of data for a given field.
        Used by the API to serve trend chart data to the HMI.
        """
        query_api = self._influx.query_api()
        query = f'''
        from(bucket: "{settings.influx_bucket}")
          |> range(start: -{minutes}m)
          |> filter(fn: (r) => r._measurement == "plant_state")
          |> filter(fn: (r) => r._field == "{field}")
          |> sort(columns: ["_time"])
        '''
        tables = query_api.query(query, org=settings.influx_org)
        results = []
        for table in tables:
            for record in table.records:
                results.append({
                    "time": record.get_time().isoformat(),
                    "value": record.get_value(),
                })
        return results
