import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import axios from 'axios'

interface TrendPoint {
  time: string
  value: number
}

interface TrendChartProps {
  field: string
  label: string
  color?: string
  minutes?: number
}

// Fetches historical data from /api/history/:field and renders a line chart.
// Refreshes every 30 seconds — historian writes every 5s so data is near-live.
export function TrendChart({ field, label, color = '#60a5fa', minutes = 60 }: TrendChartProps) {
  const [data, setData] = useState<TrendPoint[]>([])

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await axios.get(`/api/history/${field}?minutes=${minutes}`)
        setData(
          res.data.data.map((d: { time: string; value: number }) => ({
            time: new Date(d.time).toLocaleTimeString(),
            value: d.value,
          }))
        )
      } catch {
        // Historian may not have data yet — silently wait
      }
    }
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [field, minutes])

  return (
    <div className="bg-gray-800 rounded p-4">
      <h3 className="text-white text-sm font-semibold mb-3">{label}</h3>
      {data.length === 0 ? (
        <p className="text-gray-500 text-sm">Waiting for historian data...</p>
      ) : (
        <ResponsiveContainer width="100%" height={150}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis dataKey="time" tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: 'none', color: '#f9fafb' }} />
            <Line type="monotone" dataKey="value" stroke={color} dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
