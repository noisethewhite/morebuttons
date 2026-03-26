export type GraphqlHeaderListener = (queries: number, mutations: number) => void

let listener: GraphqlHeaderListener | null = null
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
