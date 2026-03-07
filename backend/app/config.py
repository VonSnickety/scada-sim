from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Factory.io runs locally under Wine, Modbus server on port 502
    factoryio_host: str = "127.0.0.1"
    factoryio_port: int = 502

    # Set to true to run without Factory.io (returns static values)
    # Useful for testing the API/frontend without the simulation running
    mock_mode: bool = False

    # API key required for control commands (valve writes)
    # Read endpoints are public — control endpoints are protected
    api_key: str = "change-me"

    # InfluxDB connection — historian that stores all sensor readings
    influx_url: str = "http://influxdb:8086"
    influx_token: str = "change-me"
    influx_org: str = "scadasim"
    influx_bucket: str = "plant_data"

    # OPC-UA server endpoint — republishes plant data for external SCADA clients
    opcua_endpoint: str = "opc.tcp://0.0.0.0:4840/scada/"

    class Config:
        env_file = ".env"


settings = Settings()
