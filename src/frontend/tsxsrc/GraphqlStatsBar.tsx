import { ReactNode, useEffect, useRef, useState } from "react"
import AppBridge from "../tssrc/app_bridge"

const COOLDOWN_MS = 2000
const POLL_MS = 400

interface StatsResponse {
    queries?: number
    mutations?: number
    error?: string
}

export default function GraphqlStatsBar(): ReactNode {
    const [queries, setQueries] = useState(0)
    const [mutations, setMutations] = useState(0)
    const [deltaQ, setDeltaQ] = useState(0)
    const [deltaM, setDeltaM] = useState(0)
    const lastQRef = useRef<number | null>(null)
    const lastMRef = useRef<number | null>(null)
    const qTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const mTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(() => {
        let cancelled = false

        const clearQ = () => {
            if (qTimerRef.current) {
                clearTimeout(qTimerRef.current)
                qTimerRef.current = null
            }
        }
        const clearM = () => {
            if (mTimerRef.current) {
                clearTimeout(mTimerRef.current)
                mTimerRef.current = null
            }
        }

        const scheduleQClear = () => {
            clearQ()
            qTimerRef.current = setTimeout(() => {
                setDeltaQ(0)
                qTimerRef.current = null
            }, COOLDOWN_MS)
        }

        const scheduleMClear = () => {
            clearM()
            mTimerRef.current = setTimeout(() => {
                setDeltaM(0)
                mTimerRef.current = null
            }, COOLDOWN_MS)
        }

        const tick = async () => {
            try {
                const res = await AppBridge.fetchWithToken("/api/graphql-stats")
                const data = (await res.json()) as StatsResponse
                if (cancelled || !res.ok) {
                    return
                }
                const q = typeof data.queries === "number" ? data.queries : 0
                const m = typeof data.mutations === "number" ? data.mutations : 0
                setQueries(q)
                setMutations(m)
                if (lastQRef.current === null || lastMRef.current === null) {
                    lastQRef.current = q
                    lastMRef.current = m
                    return
                }
                const dq = q - lastQRef.current
                const dm = m - lastMRef.current
                lastQRef.current = q
                lastMRef.current = m
                if (dq > 0) {
                    setDeltaQ((p) => p + dq)
                    scheduleQClear()
                }
                if (dm > 0) {
                    setDeltaM((p) => p + dm)
                    scheduleMClear()
                }
            } catch {
                /* ignore */
            }
        }

        void tick()
        const interval = setInterval(() => void tick(), POLL_MS)
        return () => {
            cancelled = true
            clearInterval(interval)
            clearQ()
            clearM()
        }
    }, [])

    return (
        <div className="graphql-stats" aria-label="GraphQL operation counts">
            <span className="graphql-stats__title">GraphQL</span>
            <div className="graphql-stats__counts">
                <span className="graphql-stats__item">
                    <span className="graphql-stats__label">Queries</span>
                    <span className="graphql-stats__value">{queries}</span>
                    <span
                        className={
                            deltaQ > 0
                                ? "graphql-stats__delta graphql-stats__delta--on"
                                : "graphql-stats__delta"
                        }
                        aria-hidden={deltaQ === 0}
                    >
                        {deltaQ > 0 ? `+${deltaQ}` : "\u00a0"}
                    </span>
                </span>
                <span className="graphql-stats__item">
                    <span className="graphql-stats__label">Mutations</span>
                    <span className="graphql-stats__value">{mutations}</span>
                    <span
                        className={
                            deltaM > 0
                                ? "graphql-stats__delta graphql-stats__delta--on"
                                : "graphql-stats__delta"
                        }
                        aria-hidden={deltaM === 0}
                    >
                        {deltaM > 0 ? `+${deltaM}` : "\u00a0"}
                    </span>
                </span>
            </div>
        </div>
    )
}
