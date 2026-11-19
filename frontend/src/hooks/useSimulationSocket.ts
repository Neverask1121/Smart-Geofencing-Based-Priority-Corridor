import { useEffect } from 'react'
import { useStore } from '../state/store'
import { PROTOCOL, type ServerMessage } from '../types/simulation'

const KNOWN = new Set(['snapshot', 'frame', 'status', 'pong', 'error'])

function parse(raw: string): ServerMessage | null {
  try {
    const m = JSON.parse(raw)
    if (!m || !KNOWN.has(m.type)) return null
    if ((m.type === 'snapshot' || m.type === 'frame') && m.v !== PROTOCOL) return null
    return m as ServerMessage
  } catch {
    return null
  }
}

/** Owns the WebSocket: reconnects with backoff, measures latency and asks for a resync on a gap. */
export function useSimulationSocket(): void {
  useEffect(() => {
    let ws: WebSocket | null = null
    let retry = 0
    let closed = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let ping: ReturnType<typeof setInterval> | undefined
    let lastSeq = 0
    const sent = new Map<number, number>()
    let nonce = 0
    const { ingest } = useStore.getState()

    const connect = () => {
      useStore.setState({ connection: 'connecting' })
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/simulation`)
      ws.onopen = () => {
        retry = 0
        lastSeq = 0
        useStore.setState({ connection: 'online' })
        ping = setInterval(() => {
          nonce++
          sent.set(nonce, performance.now())
          ws?.send(JSON.stringify({ type: 'ping', nonce }))
        }, 5000)
      }
      ws.onmessage = (e) => {
        const m = parse(e.data as string)
        if (!m) {
          console.warn('Ignored an invalid simulation message')
          return
        }
        if (m.type === 'pong') {
          const t0 = m.nonce === null ? undefined : sent.get(m.nonce)
          if (t0 !== undefined) {
            useStore.setState({ latencyMs: Math.round(performance.now() - t0) })
            sent.delete(m.nonce as number)
          }
          return
        }
        if (m.type === 'frame' && lastSeq === 0) return // deltas mean nothing before the first snapshot
        if (m.type === 'frame' && m.seq !== lastSeq + 1) {
          ws?.send(JSON.stringify({ type: 'resync' }))
          lastSeq = 0
          return
        }
        if (m.type === 'snapshot' || m.type === 'frame' || m.type === 'status') lastSeq = m.seq
        ingest(m)
      }
      ws.onclose = () => {
        clearInterval(ping)
        if (closed) return
        useStore.setState({ connection: 'offline' })
        timer = setTimeout(connect, Math.min(500 * 2 ** retry++, 8000))
      }
      ws.onerror = () => ws?.close()
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      clearInterval(ping)
      ws?.close()
    }
  }, [])
}
