import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from .config import settings

logger = logging.getLogger(__name__)

# ── Alarm thresholds ───────────────────────────────────────────────────────────
# These are the process limits for the water treatment tank.
# Operators are alerted when values cross these boundaries.
TANK_HIGH_WARN = 80.0   # % — filling fast, keep an eye on it
TANK_HIGH_CRIT = 90.0   # % — stop filling immediately, overflow risk
TANK_LOW_WARN  = 20.0   # % — tank getting low
TANK_LOW_CRIT  = 10.0   # % — pump cavitation risk if running dry
FLOW_NO_FLOW_TICKS = 3  # consecutive zero-flow polls before alarming


@dataclass
class Alarm:
    id: str
    message: str
    severity: str  # CRIT, HIGH, WARN
    acknowledged: bool = False


@dataclass
class PlantState:
    # Analog sensors (from Input Registers)
    tank_level: float = 0.0   # % (0-100)
    flow_rate: float  = 0.0   # units depend on Factory.io scaling
    setpoint: float   = 0.0   # current setpoint value from panel

    # Digital status (from Discrete Inputs)
    running: bool  = False
    paused: bool   = False
    start_btn: bool = False
    stop_btn: bool  = False

    # Actuator state — what we last wrote to the plant
    fill_valve_open: bool      = False
    discharge_valve_open: bool = False

    # System
    connected: bool = False
    alarms: list = field(default_factory=list)


class FactoryIOClient:
    def __init__(self):
        self.client: Optional[AsyncModbusTcpClient] = None
        self.state = PlantState()
        self._lock = asyncio.Lock()
        self._zero_flow_ticks: int = 0

    async def connect(self) -> bool:
        """Open the Modbus TCP connection to Factory.io."""
        if settings.mock_mode:
            logger.info("Mock mode — skipping Modbus connection")
            self.state.connected = True
            return True
        try:
            self.client = AsyncModbusTcpClient(
                settings.factoryio_host,
                port=settings.factoryio_port,
                timeout=3,
            )
            connected = await self.client.connect()
            if connected:
                logger.info(f"Connected to Factory.io at {settings.factoryio_host}:{settings.factoryio_port}")
            else:
                logger.warning("Could not connect to Factory.io")
            self.state.connected = connected
            return connected
        except Exception as exc:
            logger.error(f"Connection error: {exc}")
            self.state.connected = False
            return False

    async def disconnect(self):
        """Close the Modbus TCP connection."""
        if self.client:
            self.client.close()
            self.state.connected = False

    async def read(self) -> PlantState:
        """
        Poll Factory.io for current sensor values.
        Called every second by the main loop.

        Register map (matches Factory.io Modbus driver config):
          Discrete Inputs FC2:  0=Start btn, 1=Reset btn, 2=Stop btn, 3=Running
          Input Registers FC4:  0=Level, 1=Flow, 2=Setpoint
          Coils FC1:            0=Start light, 1=Reset light, 2=Stop light
          Holding Registers FC3: 0=Fill valve, 1=Discharge valve, 2=SP, 3=PV
        """
        async with self._lock:
            if settings.mock_mode:
                self.state = self._mock_state()
                return self.state

            if not self.client or not self.client.connected:
                logger.warning("Not connected — attempting reconnect")
                await self.connect()
                if not self.state.connected:
                    self.state.alarms = [Alarm("SYS_COMMS_LOST", "Factory.io comms lost", "CRIT")]
                    return self.state

            try:
                # Read discrete inputs: Start(0), Reset(1), Stop(2), Running(3)
                di = await self.client.read_discrete_inputs(address=0, count=4, slave=1)
                if di.isError():
                    raise ModbusException(str(di))
                self.state.start_btn = bool(di.bits[0])
                self.state.stop_btn  = bool(di.bits[2])
                self.state.running   = bool(di.bits[3])

                # Read input registers: Level(0), Flow(1), Setpoint(2)
                ir = await self.client.read_input_registers(address=0, count=3, slave=1)
                if ir.isError():
                    raise ModbusException(str(ir))
                # Factory.io scales 0-1000 = 0-100% for level/flow values
                self.state.tank_level = float(ir.registers[0]) / 10.0
                self.state.flow_rate  = float(ir.registers[1]) / 10.0
                self.state.setpoint   = float(ir.registers[2])

                self.state.connected = True
                self.state.alarms = self._evaluate_alarms()

            except ModbusException as exc:
                logger.error(f"Modbus read error: {exc}")
                self.state.connected = False
                self.state.alarms = [Alarm("SYS_COMMS_LOST", f"Modbus error: {exc}", "CRIT")]

            return self.state

    def _evaluate_alarms(self) -> list:
        """
        Check current plant state against process limits.
        Returns a list of active alarms — empty means all clear.
        Acknowledgement is preserved across polls: if an alarm was acknowledged
        in the previous cycle and the condition is still active, the flag carries forward.
        """
        # Build a lookup of previously acknowledged alarm ids
        previously_acked = {a.id for a in self.state.alarms if a.acknowledged}

        alarms = []
        level = self.state.tank_level

        if level >= TANK_HIGH_CRIT:
            alarms.append(Alarm("T001_HH", f"Tank critical high: {level:.1f}%", "CRIT"))
        elif level >= TANK_HIGH_WARN:
            alarms.append(Alarm("T001_HIGH", f"Tank high level: {level:.1f}%", "HIGH"))

        if level <= TANK_LOW_CRIT:
            alarms.append(Alarm("T001_LL", f"Tank critical low: {level:.1f}%", "CRIT"))
        elif level <= TANK_LOW_WARN:
            alarms.append(Alarm("T001_LOW", f"Tank low level: {level:.1f}%", "WARN"))

        if self.state.fill_valve_open and self.state.flow_rate == 0.0:
            self._zero_flow_ticks += 1
        else:
            self._zero_flow_ticks = 0
        if self._zero_flow_ticks >= FLOW_NO_FLOW_TICKS:
            alarms.append(Alarm("FLOW_NO_FLOW", "Fill valve open but no flow detected — blocked pipe or sensor fault", "HIGH"))

        # Carry forward acknowledgement for alarms that are still active
        for alarm in alarms:
            if alarm.id in previously_acked:
                alarm.acknowledged = True

        return alarms

    def _mock_state(self) -> PlantState:
        """Realistic static values for testing without Factory.io running."""
        return PlantState(
            tank_level=65.0,
            flow_rate=42.0,
            setpoint=70.0,
            running=True,
            paused=False,
            fill_valve_open=True,
            discharge_valve_open=False,
            connected=True,
            alarms=[],
        )

    # ── Actuator commands ──────────────────────────────────────────────────────
    # These write to Factory.io's holding registers to open/close valves.
    # Values are floats: 0.0 = fully closed, 1.0 = fully open.

    async def cmd_fill_valve(self, open_valve: bool):
        """Open or close the fill valve (Holding Register 0)."""
        value = 32767 if open_valve else 0  # Factory.io float: 32767 = fully open, 0 = closed
        await self._write_register(0, value)
        self.state.fill_valve_open = open_valve

    async def cmd_discharge_valve(self, open_valve: bool):
        """Open or close the discharge valve (Holding Register 1)."""
        value = 32767 if open_valve else 0
        await self._write_register(1, value)
        self.state.discharge_valve_open = open_valve

    async def _write_register(self, address: int, value: int):
        """Write a single holding register value to Factory.io."""
        if settings.mock_mode:
            logger.info(f"Mock: write register {address} = {value}")
            return
        if not self.client or not self.client.connected:
            raise RuntimeError("Not connected to Factory.io")
        async with self._lock:
            result = await self.client.write_register(address=address, value=value, slave=1)  # nosemgrep: modbus-write-no-connection-check
            if result.isError():
                raise ModbusException(f"Write register {address} failed: {result}")
            logger.info(f"Wrote register {address} = {value}")
