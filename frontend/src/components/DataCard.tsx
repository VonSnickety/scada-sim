interface DataCardProps {
  label: string
  value: string | number
  unit?: string
  status?: 'ok' | 'warn' | 'crit'
}

// Displays a single sensor value with a coloured left border that reflects
// alarm status — green = normal, yellow = warning, red = critical
export function DataCard({ label, value, unit, status = 'ok' }: DataCardProps) {
  const borderColor = {
    ok:   'border-green-500',
    warn: 'border-yellow-500',
    crit: 'border-red-500',
  }[status]

  return (
    <div className={`bg-gray-800 border-l-4 ${borderColor} rounded p-4`}>
      <p className="text-gray-400 text-xs uppercase tracking-wide">{label}</p>
      <p className="text-white text-2xl font-mono mt-1">
        {typeof value === 'number' ? value.toFixed(1) : value}
        {unit && <span className="text-gray-400 text-sm ml-1">{unit}</span>}
      </p>
    </div>
  )
}
