interface Alarm {
  id: string
  message: string
  severity: string
}

interface AlarmPanelProps {
  alarms: Alarm[]
}

// Shows active alarms colour-coded by severity.
// Empty = all clear (green text). This is what operators watch constantly.
export function AlarmPanel({ alarms }: AlarmPanelProps) {
  const severityStyle: Record<string, string> = {
    CRIT: 'bg-red-900 border-red-500 text-red-200',
    HIGH: 'bg-orange-900 border-orange-500 text-orange-200',
    WARN: 'bg-yellow-900 border-yellow-500 text-yellow-200',
  }

  return (
    <div className="bg-gray-800 rounded p-4">
      <h2 className="text-white font-semibold mb-3">
        Active Alarms
        {alarms.length > 0 && (
          <span className="ml-2 bg-red-600 text-white text-xs px-2 py-0.5 rounded-full">
            {alarms.length}
          </span>
        )}
      </h2>
      {alarms.length === 0 ? (
        <p className="text-green-400 text-sm">No active alarms</p>
      ) : (
        <div className="space-y-2">
          {alarms.map((alarm) => (
            <div
              key={alarm.id}
              className={`border rounded px-3 py-2 text-sm ${severityStyle[alarm.severity] ?? 'bg-gray-700 border-gray-500 text-gray-200'}`}
            >
              <span className="font-mono font-bold">[{alarm.severity}]</span>{' '}
              <span className="font-mono text-xs opacity-70">{alarm.id}</span>{' '}
              {alarm.message}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
