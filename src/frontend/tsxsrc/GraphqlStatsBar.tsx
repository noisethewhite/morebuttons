import { ReactNode, useCallback, useEffect, useRef, useState } from "react"
import AppBridge from "../tssrc/app_bridge"
import { setGraphqlHeaderListener } from "../tssrc/graphql_fetch_interceptor"

const COOLDOWN_MS = 2000
const POLL_MS = 3000

const fetchInit: RequestInit = { credentials: "same-origin" }

interface MutationAllowResponse {
    allowMutations?: boolean
    error?: string
}

export default function GraphqlStatsBar(): ReactNode {
    const [queries, setQueries] = useState(0)
    const [mutations, setMutations] = useState(0)
    const [deltaQ, setDeltaQ] = useState(0)
    const [deltaM, setDeltaM] = useState(0)
    const [allowMutations, setAllowMutations] = useState(false)
    const [switchLoading, setSwitchLoading] = useState(true)
    const [switchError, setSwitchError] = useState<string | null>(null)
    const deltaQRef = useRef(0)
    const deltaMRef = useRef(0)
    const qTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const mTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const fetchMutationAllow = useCallback(async (silent: boolean) => {
        if (!silent) {
            setSwitchError(null)
        }
        try {
            const res = await AppBridge.fetchWithToken(
                "/api/graphql-mutation-allow",
                fetchInit
            )
            const data = (await res.json()) as MutationAllowResponse
            if (!res.ok) {
                if (!silent) {
                    setSwitchError(data.error ?? `Request failed (${res.status}).`)
                }
                return
            }
            if (typeof data.allowMutations === "boolean") {
                setAllowMutations(data.allowMutations)
            }
        } catch {
            if (!silent) {
                setSwitchError("Could not load mutation switch.")
            }
        } finally {
            if (!silent) {
                setSwitchLoading(false)
            }
        }
    }, [])

    useEffect(() => {
        let cancelled = false
        void (async () => {
            await fetchMutationAllow(false)
            if (cancelled) {
                return
            }
        })()
        const interval = setInterval(() => {
            if (!cancelled) {
                void fetchMutationAllow(true)
            }
        }, POLL_MS)
        return () => {
            cancelled = true
            clearInterval(interval)
        }
    }, [fetchMutationAllow])

    const onToggleAllowMutations = useCallback(
        async (next: boolean) => {
            setSwitchError(null)
            setSwitchLoading(true)
            try {
                const res = await AppBridge.fetchWithToken("/api/graphql-mutation-allow", {
                    ...fetchInit,
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ allowMutations: next }),
                })
                const data = (await res.json()) as MutationAllowResponse
                if (!res.ok) {
                    setSwitchError(data.error ?? `Request failed (${res.status}).`)
                    return
                }
                if (typeof data.allowMutations === "boolean") {
                    setAllowMutations(data.allowMutations)
                }
            } catch {
                setSwitchError("Could not update mutation switch.")
            } finally {
                setSwitchLoading(false)
            }
        },
        []
    )

    useEffect(() => {
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
                deltaQRef.current = 0
                setDeltaQ(0)
                qTimerRef.current = null
            }, COOLDOWN_MS)
        }

        const scheduleMClear = () => {
            clearM()
            mTimerRef.current = setTimeout(() => {
                deltaMRef.current = 0
                setDeltaM(0)
                mTimerRef.current = null
            }, COOLDOWN_MS)
        }

        const onHeaders = (q: number, m: number) => {
            if (q > 0) {
                setQueries((t) => t + q)
                deltaQRef.current += q
                setDeltaQ(deltaQRef.current)
                scheduleQClear()
            }
            if (m > 0) {
                setMutations((t) => t + m)
                deltaMRef.current += m
                setDeltaM(deltaMRef.current)
                scheduleMClear()
            }
        }

        setGraphqlHeaderListener(onHeaders)
        return () => {
            setGraphqlHeaderListener(null)
            clearQ()
            clearM()
        }
    }, [])

    return (
        <div className="graphql-stats" aria-label="GraphQL operation counts">
            <div className="graphql-stats__main">
                <span className="graphql-stats__title">GraphQL</span>
                <div className="graphql-stats__counts">
                    <span className="graphql-stats__item">
                        <span className="graphql-stats__label">Queries</span>
                        <span className="graphql-stats__value">
                            <span key={queries} className="graphql-stats__bump-target">
                                {queries}
                            </span>
                        </span>
                        <span
                            className={
                                deltaQ > 0
                                    ? "graphql-stats__delta graphql-stats__delta--on"
                                    : "graphql-stats__delta"
                            }
                            aria-hidden={deltaQ === 0}
                        >
                            <span
                                key={deltaQ > 0 ? deltaQ : "q-idle"}
                                className="graphql-stats__bump-target"
                            >
                                {deltaQ > 0 ? `+${deltaQ}` : "\u00a0"}
                            </span>
                        </span>
                    </span>
                    <span className="graphql-stats__item">
                        <span className="graphql-stats__label">Mutations</span>
                        <span className="graphql-stats__value">
                            <span key={mutations} className="graphql-stats__bump-target">
                                {mutations}
                            </span>
                        </span>
                        <span
                            className={
                                deltaM > 0
                                    ? "graphql-stats__delta graphql-stats__delta--on"
                                    : "graphql-stats__delta"
                            }
                            aria-hidden={deltaM === 0}
                        >
                            <span
                                key={deltaM > 0 ? deltaM : "m-idle"}
                                className="graphql-stats__bump-target"
                            >
                                {deltaM > 0 ? `+${deltaM}` : "\u00a0"}
                            </span>
                        </span>
                    </span>
                </div>
            </div>
            <div className="graphql-stats__controls">
                <label className="graphql-stats__switch-label">
                    <span className="graphql-stats__switch-text">Allow mutations</span>
                    <input
                        type="checkbox"
                        className="graphql-stats__switch-input"
                        role="switch"
                        checked={allowMutations}
                        disabled={switchLoading}
                        aria-checked={allowMutations}
                        onChange={(e) => void onToggleAllowMutations(e.target.checked)}
                    />
                    <span className="graphql-stats__switch-track" aria-hidden />
                </label>
                {switchError ? (
                    <span className="graphql-stats__switch-err" role="alert">
                        {switchError}
                    </span>
                ) : null}
            </div>
        </div>
    )
}
