import { ReactNode, useCallback, useEffect, useRef, useState } from "react"

export type StatusLogKind = "idle" | "ok" | "err"

export interface StatusLogEntry {
    id: string
    at: number
    kind: StatusLogKind
    text: string
}

export function useStatusMessageLog(): {
    entries: StatusLogEntry[]
    push: (kind: StatusLogKind, text: string) => void
} {
    const [entries, setEntries] = useState<StatusLogEntry[]>([])
    const push = useCallback((kind: StatusLogKind, text: string) => {
        const t = text.trim()
        if (!t) {
            return
        }
        setEntries((prev) => [
            ...prev,
            {
                id: `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`,
                at: Date.now(),
                kind,
                text: t,
            },
        ])
    }, [])
    return { entries, push }
}

function formatLogTime(at: number): string {
    return new Date(at).toLocaleString(undefined, {
        dateStyle: "short",
        timeStyle: "medium",
    })
}

export default function StatusMessageLog({
    entries,
}: {
    entries: StatusLogEntry[]
}): ReactNode {
    const scrollRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const el = scrollRef.current
        if (el) {
            el.scrollTop = el.scrollHeight
        }
    }, [entries])

    if (entries.length === 0) {
        return null
    }

    return (
        <div
            className="shipping-rates__status-log"
            ref={scrollRef}
            role="log"
            aria-label="Activity messages"
            tabIndex={0}
        >
            <ul className="shipping-rates__status-log-list">
                {entries.map((e) => (
                    <li key={e.id} className="shipping-rates__status-log-item">
                        <time
                            className="shipping-rates__status-log-time"
                            dateTime={new Date(e.at).toISOString()}
                        >
                            {formatLogTime(e.at)}
                        </time>
                        <p
                            className={
                                e.kind === "err"
                                    ? "shipping-rates__status shipping-rates__status--error shipping-rates__status-log-msg"
                                    : e.kind === "ok"
                                      ? "shipping-rates__status shipping-rates__status--ok shipping-rates__status-log-msg"
                                      : "shipping-rates__status shipping-rates__status-log-msg"
                            }
                            role={e.kind === "err" ? "alert" : undefined}
                        >
                            {e.text}
                        </p>
                    </li>
                ))}
            </ul>
        </div>
    )
}
