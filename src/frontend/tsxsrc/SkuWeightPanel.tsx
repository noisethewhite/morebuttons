import {
    ReactNode,
    useCallback,
    useEffect,
    useState,
} from "react"
import type { SubmitEventHandler } from "react"
import AppBridge from "../tssrc/app_bridge"
import { runSteppedCatalogJob } from "../tssrc/catalog_job"
import StatusMessageLog, { useStatusMessageLog } from "./status_message_log"

interface SkuWeightRow {
    variantId: string
    sku: string
    productName: string
    current: string
    new: string
}

interface PreviewResponse {
    rows: SkuWeightRow[]
    warnings?: string[]
    error?: string
}

interface SetResponse {
    updated: number
    warnings: string[]
    userErrors: string[]
    error?: string
    code?: string
}

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

function weightChangeKind(current: string, next: string): "up" | "down" | "same" {
    if (current === "—") return "same"
    const parse = (s: string): number | null => {
        const m = s.match(/[\d.]+/)
        if (!m) return null
        const n = parseFloat(m[0])
        return Number.isFinite(n) ? n : null
    }
    const a = parse(current)
    const b = parse(next)
    if (a === null || b === null) return "same"
    if (b > a) return "up"
    if (b < a) return "down"
    return "same"
}

export default function SkuWeightPanel(): ReactNode {
    const [pattern, setPattern] = useState("")
    const [weightGrams, setWeightGrams] = useState("")

    const [catalogLoading, setCatalogLoading] = useState(false)
    const [loadedPattern, setLoadedPattern] = useState("")
    const [variantCount, setVariantCount] = useState<number | null>(null)

    const [previewRows, setPreviewRows] = useState<SkuWeightRow[] | null>(null)
    const [previewLoading, setPreviewLoading] = useState(false)
    const [previewError, setPreviewError] = useState<string | null>(null)
    const [previewWarnings, setPreviewWarnings] = useState<string | null>(null)

    const [pendingConfirmation, setPendingConfirmation] = useState(false)
    const [submitting, setSubmitting] = useState(false)

    const { entries: statusLog, push: pushStatus } = useStatusMessageLog()

    const loadCatalog = useCallback(async (pat: string): Promise<void> => {
        setCatalogLoading(true)
        setLoadedPattern("")
        setVariantCount(null)
        setPreviewRows(null)
        try {
            const result = await runSteppedCatalogJob(
                "/api/sku-weight-catalog/start",
                "/api/sku-weight-catalog/step",
                { pattern: pat },
            )
            const vc = result.variantCount
            setVariantCount(typeof vc === "number" ? vc : 0)
            setLoadedPattern(pat)
            const w = result.warnings
            if (Array.isArray(w) && w.length) {
                pushStatus("ok", `Loaded. Notes: ${(w as string[]).join(" ")}`)
            }
        } catch (e) {
            pushStatus("err", e instanceof Error ? e.message : "Could not load SKU catalog.")
        } finally {
            setCatalogLoading(false)
        }
    }, [pushStatus])

    // Preview: refresh when loadedPattern or weightGrams changes
    useEffect(() => {
        if (pendingConfirmation) return
        if (catalogLoading) {
            setPreviewLoading(false)
            return
        }
        const trimmedPat = pattern.trim()
        const trimmedW = weightGrams.trim()
        const wNum = Number(trimmedW)
        if (
            !trimmedPat ||
            loadedPattern !== trimmedPat ||
            trimmedW === "" ||
            Number.isNaN(wNum) ||
            wNum < 0
        ) {
            setPreviewRows(null)
            setPreviewError(null)
            setPreviewWarnings(null)
            setPreviewLoading(false)
            return
        }
        let cancelled = false
        const handle = window.setTimeout(() => {
            ;(async () => {
                setPreviewLoading(true)
                setPreviewError(null)
                setPreviewWarnings(null)
                try {
                    const q = new URLSearchParams({ pattern: trimmedPat, weight: trimmedW })
                    const res = await AppBridge.fetchWithToken(`/api/sku-weight/preview?${q.toString()}`)
                    const data = await readJsonBody<PreviewResponse>(res)
                    if (cancelled) return
                    if (!res.ok) {
                        setPreviewRows(null)
                        setPreviewError(data?.error ?? `Preview failed (${res.status}).`)
                        return
                    }
                    if (!data) {
                        setPreviewRows(null)
                        setPreviewError("Preview failed: response was not JSON.")
                        return
                    }
                    setPreviewRows(data.rows ?? [])
                    setPreviewWarnings(data.warnings?.length ? data.warnings.join(" ") : null)
                } catch {
                    if (!cancelled) {
                        setPreviewRows(null)
                        setPreviewError("Could not load preview.")
                    }
                } finally {
                    if (!cancelled) setPreviewLoading(false)
                }
            })()
        }, 280)
        return () => {
            cancelled = true
            clearTimeout(handle)
        }
    }, [pattern, loadedPattern, weightGrams, pendingConfirmation, catalogLoading])

    const onSubmitSet: SubmitEventHandler<HTMLFormElement> = (e) => {
        e.preventDefault()
        const trimmedPat = pattern.trim()
        if (!trimmedPat) {
            pushStatus("err", "Enter a SKU regex pattern.")
            return
        }
        const trimmedW = weightGrams.trim()
        const wNum = Number(trimmedW)
        if (trimmedW === "" || Number.isNaN(wNum) || wNum < 0) {
            pushStatus("err", "Enter a valid weight in grams (0 or more).")
            return
        }
        if (catalogLoading || loadedPattern !== trimmedPat) {
            pushStatus("err", "Scan the SKU catalog first.")
            return
        }
        if (previewLoading) {
            pushStatus("err", "Wait for the preview to finish loading.")
            return
        }
        if (!previewRows || previewRows.length === 0) {
            pushStatus("err", "No variants match this pattern.")
            return
        }
        setPendingConfirmation(true)
    }

    async function onConfirm(): Promise<void> {
        const trimmedPat = pattern.trim()
        const trimmedW = weightGrams.trim()
        if (!trimmedPat || trimmedW === "") return
        setSubmitting(true)
        try {
            const result = await runSteppedCatalogJob(
                "/api/sku-weight/set/start",
                "/api/sku-weight/set/step",
                { pattern: trimmedPat, weight: Number(trimmedW) },
            )
            const updated = (result.updated as number) ?? 0
            const userErrors = (result.userErrors as string[]) ?? []
            const warnings = (result.warnings as string[]) ?? []
            const parts = [`Updated ${updated} variant${updated === 1 ? "" : "s"}.`]
            if (userErrors.length) parts.push(`Shopify: ${userErrors.join("; ")}`)
            if (warnings.length) parts.push(warnings.join(" "))
            pushStatus(userErrors.length > 0 ? "err" : "ok", parts.join(" "))
            setPendingConfirmation(false)
            await loadCatalog(trimmedPat)
        } catch (e) {
            pushStatus("err", e instanceof Error ? e.message : "Could not apply changes.")
        } finally {
            setSubmitting(false)
        }
    }

    function onRevert(): void {
        setPendingConfirmation(false)
    }

    const busy = catalogLoading || submitting
    const trimmedPat = pattern.trim()
    const trimmedW = weightGrams.trim()
    const wNum = Number(trimmedW)
    const weightValid = trimmedW !== "" && !Number.isNaN(wNum) && wNum >= 0
    const catalogReady = loadedPattern === trimmedPat && !catalogLoading && trimmedPat !== ""
    const canSet =
        catalogReady &&
        weightValid &&
        !previewLoading &&
        Boolean(previewRows?.length) &&
        !pendingConfirmation
    const controlsLocked = pendingConfirmation

    return (
        <section className="shipping-rates" aria-labelledby="sku-weight-heading">
            <h2 id="sku-weight-heading" className="shipping-rates__title">
                Set variant weights by SKU pattern
            </h2>
            <div className="shipping-rates__layout">
                <div
                    className={
                        controlsLocked
                            ? "shipping-rates__controls shipping-rates__controls--locked"
                            : "shipping-rates__controls"
                    }
                    aria-busy={controlsLocked}
                >
                    {controlsLocked ? (
                        <p className="shipping-rates__locked-banner" role="status">
                            Review the preview and confirm or revert to continue editing.
                        </p>
                    ) : null}
                    <p className="shipping-rates__list-hint">
                        Enter a regex to match SKUs (case-insensitive), scan to load matching
                        variants, then set the target weight.
                    </p>
                    <form onSubmit={onSubmitSet}>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="sku-pattern">SKU regex</label>
                                <input
                                    id="sku-pattern"
                                    type="text"
                                    autoComplete="off"
                                    placeholder="e.g. ^WIDGET- or -XL$"
                                    value={pattern}
                                    onChange={(e) => setPattern(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter") {
                                            e.preventDefault()
                                            if (trimmedPat && !busy && !controlsLocked) {
                                                void loadCatalog(trimmedPat)
                                            }
                                        }
                                    }}
                                    disabled={busy || controlsLocked}
                                />
                            </div>
                            <button
                                type="button"
                                className="shipping-rates__scan-btn"
                                onClick={() => {
                                    if (trimmedPat) void loadCatalog(trimmedPat)
                                }}
                                disabled={busy || !trimmedPat || controlsLocked}
                            >
                                {catalogLoading ? "Scanning…" : "Scan ↺"}
                            </button>
                        </div>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field shipping-rates__field--percent">
                                <label htmlFor="sku-weight">Weight (g)</label>
                                <input
                                    id="sku-weight"
                                    type="number"
                                    min={0}
                                    step="any"
                                    autoComplete="off"
                                    placeholder="e.g. 500"
                                    value={weightGrams}
                                    onChange={(e) => setWeightGrams(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                            <button
                                type="submit"
                                className="shipping-rates__set"
                                disabled={busy || !canSet}
                            >
                                Set
                            </button>
                        </div>
                        <p className="shipping-rates__list-hint">
                            {catalogLoading ? (
                                "Scanning all products…"
                            ) : catalogReady ? (
                                <>
                                    {variantCount} variant{variantCount === 1 ? "" : "s"} matched.
                                </>
                            ) : trimmedPat ? (
                                "Press Scan or Enter to load matching variants."
                            ) : (
                                "Enter a regex pattern, then press Scan."
                            )}
                        </p>
                    </form>
                    <StatusMessageLog entries={statusLog} />
                </div>

                <div
                    className="shipping-rates__preview-wrap"
                    aria-label="Variants whose weight will change"
                >
                    <h3 className="shipping-rates__preview-title">Preview</h3>
                    {pendingConfirmation ? (
                        <div className="shipping-rates__confirm-bar">
                            <button
                                type="button"
                                className="shipping-rates__btn shipping-rates__btn--confirm"
                                onClick={() => void onConfirm()}
                                disabled={submitting || !previewRows?.length}
                            >
                                {submitting ? "Applying…" : "Confirm"}
                            </button>
                            <button
                                type="button"
                                className="shipping-rates__btn shipping-rates__btn--revert"
                                onClick={onRevert}
                                disabled={submitting}
                            >
                                Revert
                            </button>
                        </div>
                    ) : null}
                    {catalogLoading ? (
                        <p className="shipping-rates__loading">Scanning products for matching SKUs…</p>
                    ) : previewLoading ? (
                        <p className="shipping-rates__loading">Updating preview…</p>
                    ) : !catalogReady ? (
                        <p className="shipping-rates__preview-empty">
                            Enter a SKU regex and press Scan to find matching variants.
                        </p>
                    ) : !weightValid ? (
                        <p className="shipping-rates__preview-empty">
                            {variantCount === 0
                                ? "No variants matched this pattern."
                                : "Enter a target weight in grams to preview changes."}
                        </p>
                    ) : previewError ? (
                        <p className="shipping-rates__preview-empty" role="alert">
                            {previewError}
                        </p>
                    ) : !previewRows || previewRows.length === 0 ? (
                        <p className="shipping-rates__preview-empty">
                            No variants matched this SKU pattern.
                        </p>
                    ) : (
                        <div className="shipping-rates__preview">
                            {previewWarnings ? (
                                <p className="shipping-rates__preview-note">{previewWarnings}</p>
                            ) : null}
                            <table className="shipping-rates__sku-table">
                                <thead>
                                    <tr>
                                        <th>SKU</th>
                                        <th>Product</th>
                                        <th>Weight</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {previewRows.map((row) => {
                                        const dir = weightChangeKind(row.current, row.new)
                                        return (
                                            <tr key={row.variantId}>
                                                <td className="shipping-rates__sku-table-sku">
                                                    {row.sku}
                                                </td>
                                                <td>{row.productName}</td>
                                                <td
                                                    className={
                                                        dir === "up"
                                                            ? "shipping-rates__sku-table-weight shipping-rates__sku-weight--up"
                                                            : dir === "down"
                                                              ? "shipping-rates__sku-table-weight shipping-rates__sku-weight--down"
                                                              : "shipping-rates__sku-table-weight"
                                                    }
                                                >
                                                    {row.current} → {row.new}
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </section>
    )
}
