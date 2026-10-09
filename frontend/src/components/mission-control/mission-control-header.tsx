import { useEffect, useState } from 'react'
import {
  Activity,
  Bell,
  CheckCircle2,
  Clock,
  Radio,
  RefreshCw,
  ShieldCheck,
  Zap,
} from 'lucide-react'
import type { ExecutiveDashboardModel } from './types'

export interface MissionControlHeaderProps {
  status: ExecutiveDashboardModel['botStatus']
  onRefresh: () => void
  isLoading?: boolean
}

export function MissionControlHeader({
  status,
  onRefresh,
  isLoading = false,
}: MissionControlHeaderProps) {
  const [currentMytTime, setCurrentMytTime] = useState<string>('')

  useEffect(() => {
    const updateTime = () => {
      const now = new Date()
      const formatter = new Intl.DateTimeFormat('en-MY', {
        timeZone: 'Asia/Kuala_Lumpur',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
      setCurrentMytTime(formatter.format(now))
    }

    updateTime()
    const timer = setInterval(updateTime, 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <header className="glass-panel rounded-2xl p-4 sm:p-5 mb-6 relative overflow-hidden">
      {/* Ambient Top Glow Line */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent" />

      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Left: Bot Identity & Active Status Badges */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-3 pr-3 border-r border-white/[0.08]">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 via-sky-500/10 to-emerald-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.15)]">
              <Zap className="w-5 h-5 text-cyan-400 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base sm:text-lg font-bold tracking-tight text-white flex items-center gap-1.5">
                  Autonomous Futures
                </h1>
                <span className="text-[10px] font-mono font-bold py-0.5 px-2 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/25">
                  v310.2
                </span>
              </div>
              <p className="text-[11px] text-zinc-400 font-mono flex items-center gap-1">
                <span>15m Macro-Confluence Scalper Engine</span>
              </p>
            </div>
          </div>

          {/* 24/7 Animated Status Badge */}
          <div
            className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-semibold backdrop-blur-md ${
              status.state === 'ACTIVE 24/7'
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.15)]'
                : status.state === 'PAUSED'
                  ? 'bg-rose-500/10 border-rose-500/30 text-rose-400'
                  : 'bg-amber-500/10 border-amber-500/30 text-amber-400'
            }`}
          >
            <span className="relative flex h-2 w-2">
              {status.state === 'ACTIVE 24/7' && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              )}
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  status.state === 'ACTIVE 24/7'
                    ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]'
                    : status.state === 'PAUSED'
                      ? 'bg-rose-500'
                      : 'bg-amber-500'
                }`}
              />
            </span>
            <span className="font-mono tracking-wide">{status.state}</span>
          </div>

          {/* Gateway Mode Badge */}
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-cyan-500/25 bg-cyan-500/10 text-cyan-400 text-xs font-mono font-semibold backdrop-blur-md">
            <Radio className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
            <span>{status.gatewayMode}</span>
          </div>

          {/* Circuit Breaker Status */}
          <div
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold backdrop-blur-md ${
              status.circuitBreaker === 'NORMAL'
                ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
                : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
            }`}
          >
            {status.circuitBreaker === 'NORMAL' ? (
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <CheckCircle2 className="w-3.5 h-3.5 text-rose-400" />
            )}
            <span>
              {`CIRCUIT: ${
                status.circuitBreaker === 'NORMAL'
                  ? 'NORMAL (0 tripwires)'
                  : 'TRIPPED'
              }`}
            </span>
          </div>

          {/* Telegram Alert Notification Status Badge */}
          <div className="hidden xl:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border border-sky-500/20 bg-sky-500/10 text-sky-400 text-xs font-mono">
            <Bell className="w-3 h-3 text-sky-400 animate-bounce" />
            <span>Telegram: Aktif</span>
          </div>
        </div>

        {/* Right: Real-Time MYT Clock, WebSocket Status & Instant Refresh */}
        <div className="flex flex-wrap items-center gap-3">
          {/* WebSocket Streaming Indicator */}
          <div
            className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border text-xs font-mono backdrop-blur-md ${
              status.isStreaming
                ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400'
                : 'bg-amber-500/10 border-amber-500/25 text-amber-400'
            }`}
            title={
              status.isStreaming
                ? 'WebSocket Telemetry Live (~5Hz)'
                : 'Reconnecting WebSocket Stream'
            }
          >
            <Activity className="w-3.5 h-3.5 animate-pulse" />
            <span>{status.isStreaming ? 'STREAMING' : 'CONNECTING'}</span>
          </div>

          {/* MYT Clock & Last Synced Time */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/[0.03] border border-white/[0.08] text-xs font-mono shadow-inner">
            <Clock className="w-3.5 h-3.5 text-cyan-400" />
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-white tracking-wider tabular-nums">
                {currentMytTime || '00:00:00'}
              </span>
              <span className="text-[10px] text-cyan-400 font-semibold px-1 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20">
                MYT (UTC+8)
              </span>
            </div>
            {status.lastSyncedAtMyt && (
              <span className="text-[11px] text-zinc-400 hidden sm:inline pl-2 border-l border-white/[0.08]">
                Sync: {status.lastSyncedAtMyt}
              </span>
            )}
          </div>

          {/* Instant Refresh Button */}
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-cyan-500/20 to-emerald-500/20 hover:from-cyan-500/30 hover:to-emerald-500/30 border border-cyan-500/30 hover:border-cyan-500/50 text-cyan-300 hover:text-white text-xs font-medium transition-all shadow-[0_0_15px_rgba(6,182,212,0.12)] active:scale-95 cursor-pointer disabled:opacity-50"
            aria-label="Instant refresh verified data"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`}
            />
            <span>{isLoading ? 'Menyelaras…' : 'Segar Semula'}</span>
          </button>
        </div>
      </div>
    </header>
  )
}
