import { ReactNode, useEffect, useRef, useState } from "react"
import { setGraphqlHeaderListener } from "../tssrc/graphql_fetch_interceptor"

const COOLDOWN_MS = 2000

export default function GraphqlStatsBar(): ReactNode {
    const [queries, setQueries] = useState(0)
    const [mutations, setMutations] = useState(0)
    const [deltaQ, setDeltaQ] = useState(0)
    const [deltaM, setDeltaM] = useState(0)
    const deltaQRef = useRef(0)
    const deltaMRef = useRef(0)
    const qTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const mTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
    )
}
