import { ReactNode, useState } from "react"
import AppBridge from "../tssrc/app_bridge"
import { runSteppedCatalogJob } from "../tssrc/catalog_job"

// ─── API shape types ───────────────────────────────────────────────────────

interface CarrierDoneResponse {
    done: true
    carriers: string[]
}

interface OrderAddress {
    address1?: string | null
    address2?: string | null
    city?: string | null
    province?: string | null
    country?: string | null
    zip?: string | null
    countryCode?: string | null
}

interface OrderResult {
    orderNumber: string
    status: string
    customerName: string
    address?: OrderAddress | null
    weightGrams?: number | null
    deliveryCost?: string | null
    deliveryTitle?: string | null
    orderTotal?: string | null
}

interface LookupResponse {
    orders: OrderResult[]
    warnings?: string[]
    error?: string
}

// ─── Helpers ───────────────────────────────────────────────────────────────

async function readJsonBody<T>(res: Response): Promise<T | null> {
    const text = await res.text()
    const trimmed = text.trimStart()
    if (trimmed === "" || trimmed.startsWith("<")) return null
    try {
        return JSON.parse(text) as T
    } catch {
        return null
    }
}

function formatAddress(addr: OrderAddress): string {
    return [
        addr.address1,
        addr.address2,
        addr.city,
        addr.province,
        addr.zip,
        addr.country ?? addr.countryCode,
    ]
        .filter(Boolean)
        .join(", ")
}

// ─── Component ─────────────────────────────────────────────────────────────

export default function OrderLookupPanel(): ReactNode {
    // Carrier loader
    const [dateFrom, setDateFrom] = useState("")
    const [dateTo, setDateTo] = useState("")
    const [maxOrders, setMaxOrders] = useState("1000")
    const [loadingCarriers, setLoadingCarriers] = useState(false)
    const [carriers, setCarriers] = useState<string[]>([])
    const [selectedCarrier, setSelectedCarrier] = useState("")
    const [carrierError, setCarrierError] = useState<string | null>(null)

    // Tracking lookup
    const [trackingNumber, setTrackingNumber] = useState("")
    const [lookupLoading, setLookupLoading] = useState(false)
    const [orders, setOrders] = useState<OrderResult[] | null>(null)
    const [lookupError, setLookupError] = useState<string | null>(null)
    const [lookupWarnings, setLookupWarnings] = useState<string[]>([])

    async function onRefreshCarriers(): Promise<void> {
        setLoadingCarriers(true)
        setCarriers([])
        setSelectedCarrier("")
        setCarrierError(null)
        try {
            const body: Record<string, unknown> = {
                maxOrders: Math.max(1, Number(maxOrders) || 1000),
            }
            if (dateFrom) body.dateFrom = dateFrom
            if (dateTo) body.dateTo = dateTo
            const result = await runSteppedCatalogJob(
                "/api/order-carrier-catalog/start",
                "/api/order-carrier-catalog/step",
                body,
            )
            const data = result as unknown as CarrierDoneResponse
            setCarriers(data.carriers ?? [])
        } catch (e) {
            setCarrierError(
                e instanceof Error ? e.message : "Could not load carrier list."
            )
        } finally {
            setLoadingCarriers(false)
        }
    }

    async function onLookup(): Promise<void> {
        const tn = trackingNumber.trim()
        if (!tn) return
        setLookupLoading(true)
        setOrders(null)
        setLookupError(null)
        setLookupWarnings([])
        try {
            const q = new URLSearchParams({ trackingNumber: tn })
            if (selectedCarrier) q.set("carrier", selectedCarrier)
            const res = await AppBridge.fetchWithToken(
                `/api/order-by-tracking?${q.toString()}`
            )
            const data = await readJsonBody<LookupResponse>(res)
            if (!res.ok) {
                setLookupError(data?.error ?? `Lookup failed (${res.status}).`)
                return
            }
            if (!data) {
                setLookupError("Could not read server response.")
                return
            }
            setOrders(data.orders ?? [])
            setLookupWarnings(data.warnings ?? [])
        } catch (e) {
            setLookupError(e instanceof Error ? e.message : "Lookup failed.")
        } finally {
            setLookupLoading(false)
        }
    }

    return (
        <section className="order-lookup" aria-labelledby="order-lookup-heading">
            <h2 id="order-lookup-heading" className="order-lookup__title">
                Order lookup by tracking number
            </h2>

            {/* ── Carrier loader ── */}
            <div className="order-lookup__loader">
                <div className="order-lookup__loader-row">
                    <div className="order-lookup__field">
                        <label htmlFor="ol-date-from">From date</label>
                        <input
                            id="ol-date-from"
                            type="date"
                            value={dateFrom}
                            onChange={(e) => setDateFrom(e.target.value)}
                            disabled={loadingCarriers}
                        />
                    </div>
                    <div className="order-lookup__field">
                        <label htmlFor="ol-date-to">To date</label>
                        <input
                            id="ol-date-to"
                            type="date"
                            value={dateTo}
                            onChange={(e) => setDateTo(e.target.value)}
                            disabled={loadingCarriers}
                        />
                    </div>
                    <div className="order-lookup__field order-lookup__field--narrow">
                        <label htmlFor="ol-max-orders">Max orders</label>
                        <input
                            id="ol-max-orders"
                            type="number"
                            min={1}
                            max={10000}
                            value={maxOrders}
                            onChange={(e) => setMaxOrders(e.target.value)}
                            disabled={loadingCarriers}
                        />
                    </div>
                    <button
                        type="button"
                        className="order-lookup__refresh-btn"
                        onClick={() => void onRefreshCarriers()}
                        disabled={loadingCarriers}
                    >
                        {loadingCarriers ? "Loading…" : "Refresh ↺"}
                    </button>
                </div>
                {loadingCarriers ? (
                    <p className="order-lookup__progress" role="status">
                        Scanning orders for carriers…
                    </p>
                ) : null}
                {carrierError ? (
                    <p className="order-lookup__inline-msg order-lookup__inline-msg--error">
                        {carrierError}
                    </p>
                ) : null}
                <div className="order-lookup__carrier-row">
                    <label htmlFor="ol-carrier">Carrier</label>
                    <select
                        id="ol-carrier"
                        value={selectedCarrier}
                        onChange={(e) => setSelectedCarrier(e.target.value)}
                        disabled={loadingCarriers || carriers.length === 0}
                    >
                        <option value="">All</option>
                        {carriers.map((c) => (
                            <option key={c} value={c}>
                                {c}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {/* ── Tracking lookup ── */}
            <div className="order-lookup__search-row">
                <input
                    className="order-lookup__tracking-input"
                    type="text"
                    placeholder="Enter tracking number"
                    autoComplete="off"
                    value={trackingNumber}
                    onChange={(e) => setTrackingNumber(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") void onLookup()
                    }}
                    disabled={lookupLoading}
                    aria-label="Tracking number"
                />
                <button
                    type="button"
                    className="order-lookup__lookup-btn"
                    onClick={() => void onLookup()}
                    disabled={lookupLoading || !trackingNumber.trim()}
                >
                    {lookupLoading ? "Looking up…" : "Look up"}
                </button>
            </div>

            {lookupWarnings.map((w) => (
                <p key={w} className="order-lookup__inline-msg">
                    {w}
                </p>
            ))}
            {lookupError ? (
                <p className="order-lookup__inline-msg order-lookup__inline-msg--error" role="alert">
                    {lookupError}
                </p>
            ) : null}

            {/* ── Results ── */}
            {orders !== null ? (
                orders.length === 0 ? (
                    <p className="order-lookup__inline-msg">No orders found.</p>
                ) : (
                    <div className="order-lookup__results">
                        {orders.map((order) => (
                            <div key={order.orderNumber} className="order-lookup__card">
                                <div className="order-lookup__card-header">
                                    <span className="order-lookup__card-order-number">
                                        {order.orderNumber}
                                    </span>
                                    <span className="order-lookup__card-status">
                                        {order.status.replace(/_/g, " ")}
                                    </span>
                                </div>
                                <div className="order-lookup__card-row">
                                    <span className="order-lookup__card-label">Customer</span>
                                    <span className="order-lookup__card-value">
                                        {order.customerName}
                                    </span>
                                    {order.address ? (
                                        <>
                                            <span className="order-lookup__card-label">Address</span>
                                            <span className="order-lookup__card-value">
                                                {formatAddress(order.address)}
                                            </span>
                                        </>
                                    ) : null}
                                    {order.weightGrams != null ? (
                                        <>
                                            <span className="order-lookup__card-label">Gross weight</span>
                                            <span className="order-lookup__card-value">
                                                {order.weightGrams.toLocaleString()} g
                                            </span>
                                        </>
                                    ) : null}
                                    {order.deliveryCost != null ? (
                                        <>
                                            <span className="order-lookup__card-label">Delivery</span>
                                            <span className="order-lookup__card-value">
                                                {order.deliveryCost}
                                                {order.deliveryTitle
                                                    ? ` (${order.deliveryTitle})`
                                                    : null}
                                            </span>
                                        </>
                                    ) : null}
                                    <span className="order-lookup__card-label">Total</span>
                                    <span className="order-lookup__card-value">
                                        {order.orderTotal ?? "—"}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                )
            ) : null}
        </section>
    )
}
