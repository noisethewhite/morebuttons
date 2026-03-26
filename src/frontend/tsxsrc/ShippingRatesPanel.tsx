import { ReactNode, useEffect, useState } from "react"
import type { SubmitEventHandler } from "react"
import AppBridge from "../tssrc/app_bridge"

interface NamesResponse {
    names: string[]
    warnings?: string[]
    error?: string
}

interface AdjustResponse {
    updated: number
    warnings: string[]
    userErrors: string[]
    error?: string
}

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

export default function ShippingRatesPanel(): ReactNode {
    const [names, setNames] = useState<string[]>([])
    const [selected, setSelected] = useState("")
    const [percent, setPercent] = useState("")
    const [loadingNames, setLoadingNames] = useState(true)
    const [submitting, setSubmitting] = useState(false)
    const [preview, setPreview] = useState<PreviewProfile[] | null>(null)
    const [previewLoading, setPreviewLoading] = useState(false)
    const [previewError, setPreviewError] = useState<string | null>(null)
    const [previewWarnings, setPreviewWarnings] = useState<string | null>(null)
    const [status, setStatus] = useState<{ kind: "idle" | "ok" | "err"; text: string }>({
        kind: "idle",
        text: "",
    })

    useEffect(() => {
        let cancelled = false
        ;(async () => {
            setLoadingNames(true)
            try {
                const res = await AppBridge.fetchWithToken("/api/shipping-rate-names")
                const data = (await res.json()) as NamesResponse
                if (cancelled) {
                    return
                }
                if (!res.ok) {
                    setStatus({
                        kind: "err",
                        text: data.error ?? `Failed to load rate names (${res.status}).`,
                    })
                    setNames([])
                    return
                }
                setNames(data.names ?? [])
                setSelected((data.names ?? [])[0] ?? "")
                if (data.warnings?.length) {
                    setStatus({
                        kind: "ok",
                        text: `Loaded names. Notes: ${data.warnings.join(" ")}`,
                    })
                } else {
                    setStatus({ kind: "idle", text: "" })
                }
            } catch {
                if (!cancelled) {
                    setStatus({
                        kind: "err",
                        text: "Could not load shipping rate names.",
                    })
                }
            } finally {
                if (!cancelled) {
                    setLoadingNames(false)
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [])

    useEffect(() => {
        const p = percent.trim()
        if (!selected || p === "" || Number.isNaN(Number(p))) {
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
                        name: selected,
                        percent: p,
                    })
                    const res = await AppBridge.fetchWithToken(
                        `/api/shipping-rates/preview?${q.toString()}`
                    )
                    const data = (await res.json()) as PreviewResponse
                    if (cancelled) {
                        return
                    }
                    if (!res.ok) {
                        setPreview(null)
                        setPreviewError(data.error ?? `Preview failed (${res.status}).`)
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
    }, [selected, percent])

    const onSubmit: SubmitEventHandler<HTMLFormElement> = async (e) => {
        e.preventDefault()
        if (!selected.trim()) {
            setStatus({ kind: "err", text: "Choose a rate name." })
            return
        }
        const p = percent.trim()
        if (p === "" || Number.isNaN(Number(p))) {
            setStatus({ kind: "err", text: "Enter a valid percent (e.g. 10 or -5)." })
            return
        }
        setSubmitting(true)
        setStatus({ kind: "idle", text: "" })
        try {
            const res = await AppBridge.fetchWithToken("/api/shipping-rates/adjust", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: selected,
                    percent: Number(p),
                }),
            })
            const data = (await res.json()) as AdjustResponse
            if (!res.ok) {
                setStatus({
                    kind: "err",
                    text: data.error ?? `Request failed (${res.status}).`,
                })
                return
            }
            const parts: string[] = [`Updated ${data.updated} rate(s).`]
            if (data.userErrors?.length) {
                parts.push(`Shopify: ${data.userErrors.join("; ")}`)
            }
            if (data.warnings?.length) {
                parts.push(data.warnings.join(" "))
            }
            const hasErr =
                (data.userErrors?.length ?? 0) > 0 ||
                (data.updated === 0 && (data.userErrors?.length ?? 0) > 0)
            setStatus({
                kind: hasErr ? "err" : "ok",
                text: parts.join(" "),
            })
            const q = new URLSearchParams({ name: selected, percent: p })
            const prevRes = await AppBridge.fetchWithToken(
                `/api/shipping-rates/preview?${q.toString()}`
            )
            const prevJson = (await prevRes.json()) as PreviewResponse
            if (prevRes.ok && prevJson.profiles) {
                setPreview(prevJson.profiles)
                setPreviewWarnings(
                    prevJson.warnings?.length ? prevJson.warnings.join(" ") : null
                )
                setPreviewError(null)
            }
        } catch {
            setStatus({ kind: "err", text: "Could not apply changes." })
        } finally {
            setSubmitting(false)
        }
    }

    const busy = loadingNames || submitting
    const pTrim = percent.trim()
    const previewReady =
        Boolean(selected) && pTrim !== "" && !Number.isNaN(Number(pTrim))

    return (
        <section className="shipping-rates" aria-labelledby="shipping-rates-heading">
            <h2 id="shipping-rates-heading" className="shipping-rates__title">
                Adjust shipping rates by name
            </h2>
            <div className="shipping-rates__layout">
                <div className="shipping-rates__controls">
                    {loadingNames ? (
                        <p className="shipping-rates__loading">Loading rate names…</p>
                    ) : names.length === 0 ? (
                        <p className="shipping-rates__list-hint">
                            No named shipping rates found, or they could not be loaded.
                        </p>
                    ) : (
                        <p className="shipping-rates__list-hint">
                            Applies to every zone in every profile where the rate name matches.
                        </p>
                    )}
                    <form onSubmit={onSubmit}>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="shipping-rate-name">Rate name</label>
                                <select
                                    id="shipping-rate-name"
                                    value={selected}
                                    onChange={(e) => setSelected(e.target.value)}
                                    disabled={busy || names.length === 0}
                                >
                                    {names.map((n) => (
                                        <option key={n} value={n}>
                                            {n}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="shipping-rates__field shipping-rates__field--percent">
                                <label htmlFor="shipping-rate-percent">Percent</label>
                                <input
                                    id="shipping-rate-percent"
                                    type="text"
                                    inputMode="decimal"
                                    autoComplete="off"
                                    placeholder="e.g. 10"
                                    value={percent}
                                    onChange={(e) => setPercent(e.target.value)}
                                    disabled={busy}
                                    aria-describedby="shipping-rate-percent-hint"
                                />
                            </div>
                            <button
                                type="submit"
                                className="shipping-rates__set"
                                disabled={busy || names.length === 0}
                            >
                                Set
                            </button>
                        </div>
                        <p id="shipping-rate-percent-hint" className="shipping-rates__list-hint">
                            Positive increases price; negative decreases (e.g. -10 for 10% off).
                        </p>
                    </form>
                    {status.text ? (
                        <p
                            className={
                                status.kind === "err"
                                    ? "shipping-rates__status shipping-rates__status--error"
                                    : status.kind === "ok"
                                      ? "shipping-rates__status shipping-rates__status--ok"
                                      : "shipping-rates__status"
                            }
                            role={status.kind === "err" ? "alert" : undefined}
                        >
                            {status.text}
                        </p>
                    ) : null}
                </div>

                <div
                    className="shipping-rates__preview-wrap"
                    aria-label="Rates that will change"
                >
                    <h3 className="shipping-rates__preview-title">Preview</h3>
                    {previewLoading ? (
                        <p className="shipping-rates__loading">Updating preview…</p>
                    ) : !previewReady ? (
                        <p className="shipping-rates__preview-empty">
                            Choose a rate name and enter a percent to list affected rates.
                        </p>
                    ) : previewError ? (
                        <p className="shipping-rates__preview-empty" role="alert">
                            {previewError}
                        </p>
                    ) : !preview || preview.length === 0 ? (
                        <p className="shipping-rates__preview-empty">
                            No adjustable rates match this name (or none have a fixed price to
                            scale).
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
                                    aria-label={prof.name || "Delivery profile"}
                                >
                                    <h4 className="shipping-rates__profile-name">
                                        {prof.name || "Unnamed profile"}
                                    </h4>
                                    {prof.zones.map((zone) => (
                                        <div
                                            key={`${prof.id}-${zone.id}`}
                                            className="shipping-rates__zone"
                                        >
                                            <h5 className="shipping-rates__zone-name">
                                                {zone.name || "Unnamed zone"}
                                            </h5>
                                            <ul className="shipping-rates__rate-list">
                                                {zone.rows.map((row) => (
                                                    <li
                                                        key={row.id}
                                                        className="shipping-rates__preview-row"
                                                    >
                                                        <span className="shipping-rates__preview-boundary">
                                                            {row.boundary}
                                                        </span>
                                                        <span className="shipping-rates__preview-prices">
                                                            {row.current} → {row.new}
                                                        </span>
                                                    </li>
                                                ))}
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
