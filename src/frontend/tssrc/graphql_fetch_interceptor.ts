export type GraphqlHeaderListener = (queries: number, mutations: number) => void

export type GraphqlPhaseListener = (done: number, total: number) => void

let listener: GraphqlHeaderListener | null = null
let phaseListener: GraphqlPhaseListener | null = null
let pendingQ = 0
let pendingM = 0

export function setGraphqlHeaderListener(fn: GraphqlHeaderListener | null): void {
    listener = fn
    if (fn !== null && (pendingQ !== 0 || pendingM !== 0)) {
        fn(pendingQ, pendingM)
        pendingQ = 0
        pendingM = 0
    }
}

export function setGraphqlPhaseListener(fn: GraphqlPhaseListener | null): void {
    phaseListener = fn
}

/** Hide the phase progress bar until the next stepped job emits phase headers. */
export function clearGraphqlPhase(): void {
    phaseListener?.(0, 0)
}

function parseHeader(value: string | null): number {
    if (value === null || value === "") {
        return 0
    }
    const n = parseInt(value, 10)
    return Number.isFinite(n) ? n : 0
}

/**
 * Wraps `window.fetch` so responses from this app can expose per-request GraphQL counts
 * (Flask ``g``) via headers, without changing AppBridge.
 */
export function installGraphqlFetchInterceptor(): void {
    const orig = window.fetch.bind(window)
    let batchQ = 0
    let batchM = 0
    let flushScheduled = false

    const flushBatch = () => {
        flushScheduled = false
        const q = batchQ
        const m = batchM
        batchQ = 0
        batchM = 0
        if (q === 0 && m === 0) {
            return
        }
        if (listener) {
            listener(q, m)
        } else {
            pendingQ += q
            pendingM += m
        }
    }

    window.fetch = async (
        input: RequestInfo | URL,
        init?: RequestInit
    ): Promise<Response> => {
        const res = await orig(input, init)
        const q = parseHeader(res.headers.get("X-GraphQL-Queries-Request"))
        const m = parseHeader(res.headers.get("X-GraphQL-Mutations-Request"))
        const phaseDone = parseHeader(res.headers.get("X-GraphQL-Phase-Done"))
        const phaseTotal = parseHeader(res.headers.get("X-GraphQL-Phase-Total"))
        if (phaseTotal > 0 || phaseDone > 0) {
            phaseListener?.(phaseDone, phaseTotal)
        }
        if (q === 0 && m === 0) {
            return res
        }
        batchQ += q
        batchM += m
        if (!flushScheduled) {
            flushScheduled = true
            queueMicrotask(flushBatch)
        }
        return res
    }
}
