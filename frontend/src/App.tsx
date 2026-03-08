import { useEffect, useState, useCallback } from 'react'
import axios from 'axios'
import { DataCard } from './components/DataCard'
import { AlarmPanel } from './components/AlarmPanel'
import { TrendChart } from './components/TrendChart'

interface PlantState {
  tank_level: number
  flow_rate: number
  setpoint: number
  running: boolean
  fill_valve_open: boolean
  discharge_valve_open: boolean
  connected: boolean
  alarms: Array<{ id: string; message: string; severity: string; acknowledged: boolean }>
}

const initialState: PlantState = {
  tank_level: 0, flow_rate: 0, setpoint: 0,
  running: false, fill_valve_open: false, discharge_valve_open: false,
  connected: false, alarms: [],
}

// API key for control commands — in production this would come from
// an environment variable injected at build time (VITE_API_KEY)
const API_KEY = import.meta.env.VITE_API_KEY || 'MG_6Qt8KJctCsZNO4t0XRFU2_3PUns_cG4TOmBsC4qk'

function tankStatus(level: number): 'ok' | 'warn' | 'crit' {
  if (level >= 90 || level <= 10) return 'crit'
  if (level >= 80 || level <= 20) return 'warn'
  return 'ok'
}

export default function App() {
  const [state, setState] = useState<PlantState>(initialState)
  const [lastUpdate, setLastUpdate] = useState<string>('')

  // Poll /api/state every 2 seconds for live sensor values
  const fetchState = useCallback(async () => {
    try {
      const res = await axios.get<PlantState>('/api/state')
      setState(res.data)
      setLastUpdate(new Date().toLocaleTimeString())
    } catch {
      // connection not ready
    }
  }, [])

  useEffect(() => {
    fetchState()
    const interval = setInterval(fetchState, 2000)
    return () => clearInterval(interval)
  }, [fetchState])

  const acknowledgeAlarm = async (id: string) => {
    try {
      await axios.post(`/api/alarms/${id}/acknowledge`, null, {
        headers: { 'X-API-Key': API_KEY },
      })
      fetchState()
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        alert('Acknowledge rejected — check API key')
      }
    }
  }

  // Send a valve command to the backend — requires API key
  const sendControl = async (endpoint: string, body: object) => {
    try {
      await axios.post(`/api/control/${endpoint}`, body, {
        headers: { 'X-API-Key': API_KEY },
      })
      // Immediately refresh state so the button reflects the new position
      fetchState()
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        alert('Control rejected — check API key')
      }
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">

      {/* Header */}
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold tracking-wide">Water Treatment Plant — T-001 SCADA HMI</h1>
          <p className="text-gray-400 text-sm">Last update: {lastUpdate || 'connecting...'}</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${state.connected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm text-gray-400">
            {state.connected ? 'Factory.io Online' : 'Factory.io Offline'}
          </span>
        </div>
      </header>

      {/* Sensor values */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <DataCard label="Tank Level"   value={state.tank_level} unit="%" status={tankStatus(state.tank_level)} />
        <DataCard label="Flow Rate"    value={state.flow_rate}  unit="L/min" />
        <DataCard label="Setpoint"     value={state.setpoint} />
        <DataCard label="Plant Status" value={state.running ? 'RUNNING' : 'STOPPED'} status={state.running ? 'ok' : 'warn'} />
      </div>

      {/* Alarms */}
      <div className="mb-6">
        <AlarmPanel alarms={state.alarms} onAcknowledge={acknowledgeAlarm} />
      </div>

      {/* Operator controls */}
      <div className="bg-gray-800 rounded p-4 mb-6">
        <h2 className="text-white font-semibold mb-3">
          Operator Controls
          <span className="ml-2 text-yellow-400 text-xs">(requires API key)</span>
        </h2>
        <div className="flex gap-3 flex-wrap">
          <button
            onClick={() => sendControl('fill-valve', { open: !state.fill_valve_open })}
            className={`py-2 px-6 rounded font-semibold text-sm transition-colors ${
              state.fill_valve_open ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700'
            }`}
          >
            Fill Valve — {state.fill_valve_open ? 'OPEN (click to close)' : 'CLOSED (click to open)'}
          </button>
          <button
            onClick={() => sendControl('discharge-valve', { open: !state.discharge_valve_open })}
            className={`py-2 px-6 rounded font-semibold text-sm transition-colors ${
              state.discharge_valve_open ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700'
            }`}
          >
            Discharge Valve — {state.discharge_valve_open ? 'OPEN (click to close)' : 'CLOSED (click to open)'}
          </button>
        </div>
      </div>

      {/* Trend charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TrendChart field="tank_level" label="Tank Level — last 60 min" color="#60a5fa" />
        <TrendChart field="flow_rate"  label="Flow Rate — last 60 min"  color="#34d399" />
      </div>

    </div>
  )
}
