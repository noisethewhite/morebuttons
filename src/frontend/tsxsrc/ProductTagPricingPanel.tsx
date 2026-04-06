import {
    ReactNode,
    useCallback,
    useEffect,
    useMemo,
    useState,
} from "react"
import type { SubmitEventHandler } from "react"
import AppBridge from "../tssrc/app_bridge"
import { runSteppedCatalogJob } from "../tssrc/catalog_job"
import StatusMessageLog, { useStatusMessageLog } from "./status_message_log"

interface PreviewRow {
    id: string
    boundary: string
    current: string
    new: string
}

interface PreviewZone {
    id: string
    name: string
    rows: PreviewRow[]
}

interface PreviewProfile {
    id: string
    name: string
    zones: PreviewZone[]
}

interface PreviewResponse {
    profiles: PreviewProfile[]
    warnings?: string[]
    error?: string
}

interface TagsResponse {
    tags?: string[]
    error?: string
}

interface AdjustResponse {
    updated: number
    warnings: string[]
    userErrors: string[]
    error?: string
    code?: string
}

async function readJsonBody<T>(res: Response): Promise<T | null> {
    const text = await res.text()
    const trimmed = text.trimStart()
    if (trimmed === "" || trimmed.startsWith("<")) {
        return null
    }
    try {
        return JSON.parse(text) as T
    } catch {
        return null
    }
}

function priceChangeKind(current: string, next: string): "up" | "down" | "same" {
    const parseAmount = (s: string): number | null => {
        const m = s.match(/[\d]+(?:[.,]\d+)?/)
        if (!m) {
            return null
        }
        const n = parseFloat(m[0].replace(",", "."))
        return Number.isFinite(n) ? n : null
    }
    const a = parseAmount(current)
    const b = parseAmount(next)
    if (a === null || b === null) {
        return "same"
    }
    if (b > a) {
        return "up"
    }
    if (b < a) {
        return "down"
    }
    return "same"
}

type AdjustmentMode = "percent" | "offset"

export default function ProductTagPricingPanel(): ReactNode {
    const [tags, setTags] = useState<string[]>([])
    const [selectedTag, setSelectedTag] = useState("")
    const [adjustmentMode, setAdjustmentMode] = useState<AdjustmentMode>("percent")
    const [percent, setPercent] = useState("")
    const [loadingTags, setLoadingTags] = useState(true)
    const [loadingCatalog, setLoadingCatalog] = useState(false)
    const [submitting, setSubmitting] = useState(false)
    const [pendingConfirmation, setPendingConfirmation] = useState(false)
    const [preview, setPreview] = useState<PreviewProfile[] | null>(null)
    const [previewLoading, setPreviewLoading] = useState(false)
    const [previewError, setPreviewError] = useState<string | null>(null)
    const [previewWarnings, setPreviewWarnings] = useState<string | null>(null)
    const [variantCount, setVariantCount] = useState<number | null>(null)
    const { entries: statusLog, push: pushStatus } = useStatusMessageLog()

    useEffect(() => {
        let cancelled = false
        ;(async () => {
            setLoadingTags(true)
            try {
                const res = await AppBridge.fetchWithToken("/api/product-tags")
                const data = await readJsonBody<TagsResponse>(res)
                if (cancelled) {
                    return
                }
                if (!res.ok || !data) {
                    pushStatus(
                        "err",
                        data?.error ?? `Failed to load tags (${res.status}).`,
                    )
                    setTags([])
                    return
                }
                setTags(data.tags ?? [])
            } catch {
                if (!cancelled) {
                    pushStatus("err", "Could not load product tags.")
                }
            } finally {
                if (!cancelled) {
                    setLoadingTags(false)
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [pushStatus])

    const loadTagCatalog = useCallback(async (tag: string) => {
        if (!tag.trim()) {
            setVariantCount(null)
            return
        }
        setLoadingCatalog(true)
        setVariantCount(null)
        try {
            const result = await runSteppedCatalogJob(
                "/api/product-tag-catalog/start",
                "/api/product-tag-catalog/step",
                { tag: tag.trim() }
            )
            const vc = result.variantCount
            setVariantCount(typeof vc === "number" ? vc : 0)
            const w = result.warnings
            if (Array.isArray(w) && w.length) {
                pushStatus(
                    "ok",
                    `Loaded variants. Notes: ${(w as string[]).join(" ")}`,
                )
            }
        } catch (e) {
            pushStatus(
                "err",
                e instanceof Error ? e.message : "Could not load tagged products.",
            )
            setVariantCount(null)
        } finally {
            setLoadingCatalog(false)
        }
    }, [pushStatus])

    useEffect(() => {
        if (!selectedTag.trim()) {
            setPreview(null)
            setVariantCount(null)
            return
        }
        void loadTagCatalog(selectedTag)
    }, [selectedTag, loadTagCatalog])

    useEffect(() => {
        if (pendingConfirmation) {
            return
        }
        if (loadingCatalog) {
            setPreviewLoading(false)
            return
        }
        const p = percent.trim()
        const tag = selectedTag.trim()
        if (!tag || p === "" || Number.isNaN(Number(p))) {
            setPreview(null)
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
                    const q = new URLSearchParams({
                        tag,
                        percent: p,
                    })
                    if (adjustmentMode === "offset") {
                        q.set("mode", "offset")
                    }
                    const res = await AppBridge.fetchWithToken(
                        `/api/product-tag-pricing/preview?${q.toString()}`
                    )
                    const data = await readJsonBody<PreviewResponse>(res)
                    if (cancelled) {
                        return
                    }
                    if (!res.ok) {
                        setPreview(null)
                        setPreviewError(data?.error ?? `Preview failed (${res.status}).`)
                        return
                    }
                    if (!data) {
                        setPreview(null)
                        setPreviewError(
                            `Preview failed (${res.status}): response was not JSON.`
                        )
                        return
                    }
                    setPreview(data.profiles ?? [])
                    setPreviewWarnings(
                        data.warnings?.length ? data.warnings.join(" ") : null
                    )
                } catch {
                    if (!cancelled) {
                        setPreview(null)
                        setPreviewError("Could not load preview.")
                    }
                } finally {
                    if (!cancelled) {
                        setPreviewLoading(false)
                    }
                }
            })()
        }, 280)
        return () => {
            cancelled = true
            window.clearTimeout(handle)
        }
    }, [selectedTag, percent, pendingConfirmation, adjustmentMode, loadingCatalog])

    const onSubmitSet: SubmitEventHandler<HTMLFormElement> = (e) => {
        e.preventDefault()
        const tag = selectedTag.trim()
        if (!tag) {
            pushStatus("err", "Choose a product tag.")
            return
        }
        const p = percent.trim()
        if (p === "" || Number.isNaN(Number(p))) {
            pushStatus(
                "err",
                adjustmentMode === "percent"
                    ? "Enter a valid percent (e.g. 10 or -5)."
                    : "Enter a valid amount (e.g. 5 or -2).",
            )
            return
        }
        if (previewLoading) {
            pushStatus("err", "Wait for the preview to finish loading.")
            return
        }
        if (!preview || preview.length === 0) {
            pushStatus(
                "err",
                "No variants match this adjustment. Change the tag or value first.",
            )
            return
        }
        setPendingConfirmation(true)
    }

    async function onConfirm(): Promise<void> {
        const tag = selectedTag.trim()
        const p = percent.trim()
        if (!tag || p === "" || Number.isNaN(Number(p))) {
            return
        }
        setSubmitting(true)
        try {
            const res = await AppBridge.fetchWithToken("/api/product-tag-pricing/adjust", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tag,
                    percent: Number(p),
                    ...(adjustmentMode === "offset" ? { mode: "offset" } : {}),
                }),
            })
            const data = await readJsonBody<AdjustResponse>(res)
            if (!res.ok) {
                pushStatus(
                    "err",
                    data?.code === "MUTATIONS_BLOCKED"
                        ? (data.error ??
                          "Mutations are disabled. Turn on Allow mutations in the GraphQL bar.")
                        : (data?.error ?? `Request failed (${res.status}).`),
                )
                return
            }
            if (!data) {
                pushStatus(
                    "err",
                    "Could not read server response after applying changes.",
                )
                return
            }
            const parts: string[] = [
                `Updated ${data.updated} variant${data.updated === 1 ? "" : "s"}.`,
            ]
            if (data.userErrors?.length) {
                parts.push(`Shopify: ${data.userErrors.join("; ")}`)
            }
            if (data.warnings?.length) {
                parts.push(data.warnings.join(" "))
            }
            const hasErr =
                (data.userErrors?.length ?? 0) > 0 ||
                (data.updated === 0 && (data.userErrors?.length ?? 0) > 0)
            pushStatus(hasErr ? "err" : "ok", parts.join(" "))
            setPendingConfirmation(false)
            await loadTagCatalog(tag)
            const q = new URLSearchParams({ tag, percent: p })
            if (adjustmentMode === "offset") {
                q.set("mode", "offset")
            }
            try {
                const prevRes = await AppBridge.fetchWithToken(
                    `/api/product-tag-pricing/preview?${q.toString()}`
                )
                const prevJson = await readJsonBody<PreviewResponse>(prevRes)
                if (prevRes.ok && prevJson?.profiles) {
                    setPreview(prevJson.profiles)
                    setPreviewWarnings(
                        prevJson.warnings?.length ? prevJson.warnings.join(" ") : null
                    )
                    setPreviewError(null)
                }
            } catch {
                setPreviewError("Could not refresh preview after applying.")
            }
        } catch (error) {
            console.error(error)
            pushStatus("err", "Could not apply changes.")
        } finally {
            setSubmitting(false)
        }
    }

    function onRevert(): void {
        setPendingConfirmation(false)
    }

    const busy = loadingTags || loadingCatalog || submitting
    const pTrim = percent.trim()
    const previewReady =
        Boolean(selectedTag.trim()) && pTrim !== "" && !Number.isNaN(Number(pTrim))
    const controlsLocked = pendingConfirmation
    const catalogReadyForTag = !selectedTag.trim() || variantCount !== null
    const canSet =
        previewReady &&
        !previewLoading &&
        Boolean(preview?.length) &&
        !pendingConfirmation &&
        catalogReadyForTag

    const tagHint = useMemo(() => {
        if (loadingTags) {
            return "Loading tags…"
        }
        if (tags.length === 0) {
            return "No product tags found in this shop (or tags could not be loaded)."
        }
        return "Prices apply to every variant on products with this tag."
    }, [loadingTags, tags.length])

    return (
        <section className="shipping-rates" aria-labelledby="product-tag-heading">
            <h2 id="product-tag-heading" className="shipping-rates__title">
                Adjust variant prices by product tag
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
                    <p className="shipping-rates__list-hint">{tagHint}</p>
                    <form onSubmit={onSubmitSet}>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="product-tag-select">Product tag</label>
                                <select
                                    id="product-tag-select"
                                    value={selectedTag}
                                    onChange={(e) => setSelectedTag(e.target.value)}
                                    disabled={busy || tags.length === 0 || controlsLocked}
                                >
                                    <option value="">Select a tag…</option>
                                    {tags.map((t) => (
                                        <option key={t} value={t}>
                                            {t}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="shipping-rates__field-group shipping-rates__field-group--value">
                                <div className="shipping-rates__field shipping-rates__field--mode">
                                    <span
                                        id="product-tag-adjustment-label"
                                        className="shipping-rates__segment-label"
                                    >
                                        Adjustment
                                    </span>
                                    <div
                                        className="shipping-rates__segment"
                                        role="group"
                                        aria-labelledby="product-tag-adjustment-label"
                                    >
                                        <button
                                            type="button"
                                            className={
                                                adjustmentMode === "percent"
                                                    ? "shipping-rates__segment-btn shipping-rates__segment-btn--active"
                                                    : "shipping-rates__segment-btn"
                                            }
                                            aria-pressed={adjustmentMode === "percent"}
                                            disabled={busy || controlsLocked}
                                            onClick={() => setAdjustmentMode("percent")}
                                        >
                                            Percent
                                        </button>
                                        <button
                                            type="button"
                                            className={
                                                adjustmentMode === "offset"
                                                    ? "shipping-rates__segment-btn shipping-rates__segment-btn--active"
                                                    : "shipping-rates__segment-btn"
                                            }
                                            aria-pressed={adjustmentMode === "offset"}
                                            disabled={busy || controlsLocked}
                                            onClick={() => setAdjustmentMode("offset")}
                                        >
                                            Amount
                                        </button>
                                    </div>
                                </div>
                                <div className="shipping-rates__field shipping-rates__field--percent">
                                    <label htmlFor="product-tag-percent">
                                        {adjustmentMode === "percent" ? "Percent" : "Amount"}
                                    </label>
                                    <input
                                        id="product-tag-percent"
                                        type="text"
                                        inputMode="decimal"
                                        autoComplete="off"
                                        placeholder={
                                            adjustmentMode === "percent" ? "e.g. 10" : "e.g. 5 or -2"
                                        }
                                        value={percent}
                                        onChange={(e) => setPercent(e.target.value)}
                                        disabled={busy || controlsLocked}
                                        aria-describedby="product-tag-percent-hint"
                                    />
                                </div>
                            </div>
                            <button
                                type="submit"
                                className="shipping-rates__set"
                                disabled={busy || !selectedTag.trim() || !canSet}
                            >
                                Set
                            </button>
                        </div>
                        <p id="product-tag-percent-hint" className="shipping-rates__list-hint">
                            {variantCount !== null && selectedTag ? (
                                <>
                                    {variantCount} variant{variantCount === 1 ? "" : "s"} loaded
                                    for this tag.{" "}
                                </>
                            ) : null}
                            {adjustmentMode === "percent" ? (
                                <>
                                    Positive increases price; negative decreases (e.g. -10 for 10%
                                    off).
                                </>
                            ) : (
                                <>
                                    Adds or subtracts this amount from each variant price in shop
                                    currency (negative reduces; results below zero become 0).
                                </>
                            )}
                        </p>
                    </form>
                    <StatusMessageLog entries={statusLog} />
                </div>

                <div
                    className="shipping-rates__preview-wrap"
                    aria-label="Variant prices that will change"
                >
                    <h3 className="shipping-rates__preview-title">Preview</h3>
                    {pendingConfirmation ? (
                        <div className="shipping-rates__confirm-bar">
                            <button
                                type="button"
                                className="shipping-rates__btn shipping-rates__btn--confirm"
                                onClick={() => void onConfirm()}
                                disabled={submitting || !preview?.length}
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
                    {loadingCatalog && selectedTag ? (
                        <p className="shipping-rates__loading">Loading tagged variants…</p>
                    ) : previewLoading ? (
                        <p className="shipping-rates__loading">Updating preview…</p>
                    ) : !selectedTag.trim() ? (
                        <p className="shipping-rates__preview-empty">
                            Select a product tag to load variants and preview price changes.
                        </p>
                    ) : !previewReady ? (
                        <p className="shipping-rates__preview-empty">
                            Enter a{" "}
                            {adjustmentMode === "percent" ? "percent" : "fixed amount change"} to
                            list affected variants.
                        </p>
                    ) : previewError ? (
                        <p className="shipping-rates__preview-empty" role="alert">
                            {previewError}
                        </p>
                    ) : !preview || preview.length === 0 ? (
                        <p className="shipping-rates__preview-empty">
                            No variants found for this tag, or catalog is still loading.
                        </p>
                    ) : (
                        <div className="shipping-rates__preview">
                            {previewWarnings ? (
                                <p className="shipping-rates__preview-note">{previewWarnings}</p>
                            ) : null}
                            {preview.map((prof) => (
                                <section
                                    key={prof.id}
                                    className="shipping-rates__profile"
                                    aria-label={prof.name || "Product"}
                                >
                                    <h4 className="shipping-rates__profile-name">
                                        {prof.name || "Untitled product"}
                                    </h4>
                                    {prof.zones.map((zone) => (
                                        <div
                                            key={`${prof.id}-${zone.id}`}
                                            className="shipping-rates__zone"
                                        >
                                            <h5 className="shipping-rates__zone-name">
                                                {zone.name || "Variants"}
                                            </h5>
                                            <ul className="shipping-rates__rate-list">
                                                {zone.rows.map((row) => {
                                                    const dir = priceChangeKind(
                                                        row.current,
                                                        row.new
                                                    )
                                                    const rowClass =
                                                        dir === "up"
                                                            ? "shipping-rates__preview-row shipping-rates__preview-row--up"
                                                            : dir === "down"
                                                              ? "shipping-rates__preview-row shipping-rates__preview-row--down"
                                                              : "shipping-rates__preview-row"
                                                    const priceClass =
                                                        dir === "up"
                                                            ? "shipping-rates__preview-prices shipping-rates__preview-prices--up"
                                                            : dir === "down"
                                                              ? "shipping-rates__preview-prices shipping-rates__preview-prices--down"
                                                              : "shipping-rates__preview-prices"
                                                    return (
                                                        <li key={row.id} className={rowClass}>
                                                            <span className="shipping-rates__preview-boundary">
                                                                {row.boundary}
                                                            </span>
                                                            <span className={priceClass}>
                                                                {row.current} → {row.new}
                                                            </span>
                                                        </li>
                                                    )
                                                })}
                                            </ul>
                                        </div>
                                    ))}
                                </section>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </section>
    )
}
