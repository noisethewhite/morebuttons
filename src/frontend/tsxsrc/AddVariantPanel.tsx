import {
    ReactNode,
    useCallback,
    useState,
} from "react"
import type { SubmitEventHandler } from "react"
import AppBridge from "../tssrc/app_bridge"
import { runSteppedCatalogJob } from "../tssrc/catalog_job"
import StatusMessageLog, { useStatusMessageLog } from "./status_message_log"

interface AddVariantPreviewRow {
    productId: string
    productTitle: string
    newSku: string
    optionValue: string
    weightGrams: number
    price: string
}

interface PreviewResponse {
    rows: AddVariantPreviewRow[]
    warnings?: string[]
    error?: string
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

export default function AddVariantPanel(): ReactNode {
    const [pattern, setPattern] = useState("")
    const [optionValue, setOptionValue] = useState("")
    const [skuSuffix, setSkuSuffix] = useState("")
    const [weightGrams, setWeightGrams] = useState("")
    const [price, setPrice] = useState("")

    const [catalogLoading, setCatalogLoading] = useState(false)
    const [loadedPattern, setLoadedPattern] = useState("")
    const [productCount, setProductCount] = useState<number | null>(null)

    const [previewRows, setPreviewRows] = useState<AddVariantPreviewRow[] | null>(null)
    const [previewLoading, setPreviewLoading] = useState(false)
    const [previewError, setPreviewError] = useState<string | null>(null)
    const [previewWarnings, setPreviewWarnings] = useState<string | null>(null)

    const [pendingConfirmation, setPendingConfirmation] = useState(false)
    const [submitting, setSubmitting] = useState(false)

    const { entries: statusLog, push: pushStatus } = useStatusMessageLog()

    const loadCatalog = useCallback(async (pat: string): Promise<void> => {
        setCatalogLoading(true)
        setLoadedPattern("")
        setProductCount(null)
        setPreviewRows(null)
        setPreviewError(null)
        setPreviewWarnings(null)
        try {
            const result = await runSteppedCatalogJob(
                "/api/add-variant-catalog/start",
                "/api/add-variant-catalog/step",
                { pattern: pat },
            )
            const pc = result.productCount
            setProductCount(typeof pc === "number" ? pc : 0)
            setLoadedPattern(pat)
            const w = result.warnings
            if (Array.isArray(w) && w.length) {
                pushStatus("ok", `Loaded. Notes: ${(w as string[]).join(" ")}`)
            }
        } catch (e) {
            pushStatus("err", e instanceof Error ? e.message : "Could not load catalog.")
        } finally {
            setCatalogLoading(false)
        }
    }, [pushStatus])

    const refreshPreview = useCallback(async (): Promise<void> => {
        const trimmedPat = pattern.trim()
        const trimmedSuffix = skuSuffix.trim()
        const trimmedOv = optionValue.trim()
        const trimmedW = weightGrams.trim()
        const trimmedP = price.trim()
        if (!trimmedPat || !trimmedSuffix || !trimmedOv || !trimmedW || !trimmedP) return
        if (loadedPattern !== trimmedPat) return
        setPreviewLoading(true)
        setPreviewError(null)
        setPreviewWarnings(null)
        setPreviewRows(null)
        try {
            const q = new URLSearchParams({
                pattern: trimmedPat,
                suffix: trimmedSuffix,
                optionValue: trimmedOv,
                weight: trimmedW,
                price: trimmedP,
            })
            const res = await AppBridge.fetchWithToken(`/api/add-variant/preview?${q.toString()}`)
            const data = await readJsonBody<PreviewResponse>(res)
            if (!res.ok) {
                setPreviewError(data?.error ?? `Preview failed (${res.status}).`)
                return
            }
            if (!data) {
                setPreviewError("Preview failed: response was not JSON.")
                return
            }
            setPreviewRows(data.rows ?? [])
            setPreviewWarnings(data.warnings?.length ? data.warnings.join(" ") : null)
        } catch {
            setPreviewError("Could not load preview.")
        } finally {
            setPreviewLoading(false)
        }
    }, [pattern, skuSuffix, optionValue, weightGrams, price, loadedPattern])

    const onSubmitSet: SubmitEventHandler<HTMLFormElement> = (e) => {
        e.preventDefault()
        const trimmedPat = pattern.trim()
        if (!trimmedPat) { pushStatus("err", "Enter a SKU regex pattern."); return }
        if (catalogLoading || loadedPattern !== trimmedPat) { pushStatus("err", "Scan the catalog first."); return }
        if (!skuSuffix.trim()) { pushStatus("err", "Enter a SKU suffix."); return }
        if (!optionValue.trim()) { pushStatus("err", "Enter an option value."); return }
        const wNum = Number(weightGrams.trim())
        if (weightGrams.trim() === "" || Number.isNaN(wNum) || wNum < 0) {
            pushStatus("err", "Enter a valid weight in grams (0 or more).")
            return
        }
        const pNum = Number(price.trim())
        if (price.trim() === "" || Number.isNaN(pNum) || pNum <= 0) {
            pushStatus("err", "Enter a valid price greater than 0.")
            return
        }
        if (previewLoading) { pushStatus("err", "Wait for the preview to finish loading."); return }
        if (!previewRows || previewRows.length === 0) { pushStatus("err", "No products matched this pattern."); return }
        setPendingConfirmation(true)
    }

    async function onConfirm(): Promise<void> {
        const trimmedPat = pattern.trim()
        const trimmedSuffix = skuSuffix.trim()
        const trimmedOv = optionValue.trim()
        const trimmedW = weightGrams.trim()
        const trimmedP = price.trim()
        if (!trimmedPat || !trimmedSuffix || !trimmedOv || !trimmedW || !trimmedP) return
        setSubmitting(true)
        try {
            const result = await runSteppedCatalogJob(
                "/api/add-variant/set/start",
                "/api/add-variant/set/step",
                {
                    pattern: trimmedPat,
                    suffix: trimmedSuffix,
                    optionValue: trimmedOv,
                    weight: Number(trimmedW),
                    price: trimmedP,
                },
            )
            const updated = (result.updated as number) ?? 0
            const userErrors = (result.userErrors as string[]) ?? []
            const warnings = (result.warnings as string[]) ?? []
            const parts = [`Added variant to ${updated} product${updated === 1 ? "" : "s"}.`]
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
    const wNum = Number(weightGrams.trim())
    const pNum = Number(price.trim())
    const weightValid = weightGrams.trim() !== "" && !Number.isNaN(wNum) && wNum >= 0
    const priceValid = price.trim() !== "" && !Number.isNaN(pNum) && pNum > 0
    const catalogReady = loadedPattern === trimmedPat && !catalogLoading && trimmedPat !== ""
    const allFieldsValid = skuSuffix.trim() !== "" && optionValue.trim() !== "" && weightValid && priceValid
    const canSet =
        catalogReady &&
        allFieldsValid &&
        !previewLoading &&
        Boolean(previewRows?.length) &&
        !previewError &&
        !pendingConfirmation
    const controlsLocked = pendingConfirmation

    return (
        <section className="shipping-rates" aria-labelledby="add-variant-heading">
            <h2 id="add-variant-heading" className="shipping-rates__title">
                Add variant to products by SKU pattern
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
                        Enter a regex to match SKUs (case-insensitive), scan to find matching
                        products, fill in the new variant details, then refresh the preview.
                    </p>
                    <form onSubmit={onSubmitSet}>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="av-sku-pattern">SKU regex</label>
                                <input
                                    id="av-sku-pattern"
                                    type="text"
                                    autoComplete="off"
                                    placeholder="e.g. ^FO-\d{3}-\d{3}$"
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
                                onClick={() => { if (trimmedPat) void loadCatalog(trimmedPat) }}
                                disabled={busy || !trimmedPat || controlsLocked}
                            >
                                {catalogLoading ? "Scanning…" : "Scan ↺"}
                            </button>
                        </div>
                        <p className="shipping-rates__list-hint">
                            {catalogLoading ? (
                                "Scanning all products…"
                            ) : catalogReady ? (
                                <>{productCount} product{productCount === 1 ? "" : "s"} matched.</>
                            ) : trimmedPat ? (
                                "Press Scan or Enter to load matching products."
                            ) : (
                                "Enter a regex pattern, then press Scan."
                            )}
                        </p>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="av-option-value">Option value</label>
                                <input
                                    id="av-option-value"
                                    type="text"
                                    autoComplete="off"
                                    placeholder="e.g. 1kg"
                                    value={optionValue}
                                    onChange={(e) => setOptionValue(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                        </div>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="av-sku-suffix">SKU suffix</label>
                                <input
                                    id="av-sku-suffix"
                                    type="text"
                                    autoComplete="off"
                                    placeholder="e.g. 100"
                                    value={skuSuffix}
                                    onChange={(e) => setSkuSuffix(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                        </div>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field shipping-rates__field--percent">
                                <label htmlFor="av-weight">Weight (g)</label>
                                <input
                                    id="av-weight"
                                    type="number"
                                    min={0}
                                    step="any"
                                    autoComplete="off"
                                    placeholder="e.g. 1000"
                                    value={weightGrams}
                                    onChange={(e) => setWeightGrams(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                        </div>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field shipping-rates__field--percent">
                                <label htmlFor="av-price">Price</label>
                                <input
                                    id="av-price"
                                    type="number"
                                    min={0.01}
                                    step="0.01"
                                    autoComplete="off"
                                    placeholder="e.g. 29.99"
                                    value={price}
                                    onChange={(e) => setPrice(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                        </div>
                        <div className="shipping-rates__row">
                            <button
                                type="button"
                                className="shipping-rates__scan-btn"
                                onClick={() => void refreshPreview()}
                                disabled={
                                    busy || !catalogReady || !allFieldsValid ||
                                    controlsLocked || previewLoading
                                }
                            >
                                {previewLoading ? "Loading…" : "Refresh preview ↺"}
                            </button>
                            <button
                                type="submit"
                                className="shipping-rates__set"
                                disabled={busy || !canSet}
                            >
                                Set
                            </button>
                        </div>
                    </form>
                    <StatusMessageLog entries={statusLog} />
                </div>

                <div
                    className="shipping-rates__preview-wrap"
                    aria-label="Products that will receive a new variant"
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
                    ) : !catalogReady ? (
                        <p className="shipping-rates__preview-empty">
                            Enter a SKU regex and press Scan to find matching products.
                        </p>
                    ) : previewLoading ? (
                        <p className="shipping-rates__loading">Loading preview…</p>
                    ) : previewError ? (
                        <p className="shipping-rates__preview-empty" role="alert">
                            {previewError}
                        </p>
                    ) : !previewRows ? (
                        <p className="shipping-rates__preview-empty">
                            {productCount === 0
                                ? "No products matched this pattern."
                                : "Fill in the variant details and press Refresh preview."}
                        </p>
                    ) : previewRows.length === 0 ? (
                        <p className="shipping-rates__preview-empty">
                            No products matched this SKU pattern.
                        </p>
                    ) : (
                        <div className="shipping-rates__preview">
                            {previewWarnings ? (
                                <p className="shipping-rates__preview-note">{previewWarnings}</p>
                            ) : null}
                            <table className="shipping-rates__sku-table">
                                <thead>
                                    <tr>
                                        <th>Product</th>
                                        <th>New SKU</th>
                                        <th>Option value</th>
                                        <th>Weight</th>
                                        <th>Price</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {previewRows.map((row) => (
                                        <tr key={row.productId}>
                                            <td>{row.productTitle}</td>
                                            <td className="shipping-rates__sku-table-sku">{row.newSku}</td>
                                            <td>{row.optionValue}</td>
                                            <td>{row.weightGrams} g</td>
                                            <td>{row.price}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </section>
    )
}
