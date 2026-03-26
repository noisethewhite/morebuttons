import { ReactNode, useEffect, useMemo, useState } from "react"
import type { SubmitEventHandler } from "react"
import AppBridge from "../tssrc/app_bridge"

interface FilterProfile {
    id: string
    name: string
}

interface FilterZone {
    id: string
    name: string
}

interface NamesResponse {
    names: string[]
    profiles?: FilterProfile[]
    zonesByProfile?: Record<string, FilterZone[]>
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

/** Compare first numeric token in strings like "12.00 USD". */
function priceChangeKind(current: string, next: string): "up" | "down" | "same" {
    const parseAmount = (s: string): number | null => {
        const first = s.trim().split(/\s+/)[0]
        if (!first) {
            return null
        }
        const n = parseFloat(first.replace(",", ""))
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

const ALL_VALUE = ""

type AdjustmentMode = "percent" | "offset"

export default function ShippingRatesPanel(): ReactNode {
    const [names, setNames] = useState<string[]>([])
    const [profiles, setProfiles] = useState<FilterProfile[]>([])
    const [zonesByProfile, setZonesByProfile] = useState<Record<string, FilterZone[]>>(
        {}
    )
    const [selected, setSelected] = useState("")
    const [profileId, setProfileId] = useState(ALL_VALUE)
    const [zoneId, setZoneId] = useState(ALL_VALUE)
    const [adjustmentMode, setAdjustmentMode] = useState<AdjustmentMode>("percent")
    const [percent, setPercent] = useState("")
    const [loadingNames, setLoadingNames] = useState(true)
    const [submitting, setSubmitting] = useState(false)
    const [pendingConfirmation, setPendingConfirmation] = useState(false)
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
                setProfiles(data.profiles ?? [])
                setZonesByProfile(data.zonesByProfile ?? {})
                setProfileId(ALL_VALUE)
                setZoneId(ALL_VALUE)
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
        if (pendingConfirmation) {
            return
        }
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
                    if (adjustmentMode === "offset") {
                        q.set("mode", "offset")
                    }
                    if (profileId) {
                        q.set("profileId", profileId)
                    }
                    if (zoneId) {
                        q.set("zoneId", zoneId)
                    }
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
    }, [selected, percent, profileId, zoneId, pendingConfirmation, adjustmentMode])

    const zoneOptions: FilterZone[] = useMemo(() => {
        if (profileId) {
            return zonesByProfile[profileId] ?? []
        }
        const seen = new Set<string>()
        const out: FilterZone[] = []
        for (const p of profiles) {
            for (const z of zonesByProfile[p.id] ?? []) {
                if (!seen.has(z.id)) {
                    seen.add(z.id)
                    out.push(z)
                }
            }
        }
        return out.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }))
    }, [profileId, profiles, zonesByProfile])

    function onProfileChange(value: string): void {
        setProfileId(value)
        setZoneId(ALL_VALUE)
    }

    const onSubmitSet: SubmitEventHandler<HTMLFormElement> = (e) => {
        e.preventDefault()
        if (!selected.trim()) {
            setStatus({ kind: "err", text: "Choose a rate name." })
            return
        }
        const p = percent.trim()
        if (p === "" || Number.isNaN(Number(p))) {
            setStatus({
                kind: "err",
                text:
                    adjustmentMode === "percent"
                        ? "Enter a valid percent (e.g. 10 or -5)."
                        : "Enter a valid amount (e.g. 5 or -2).",
            })
            return
        }
        if (previewLoading) {
            setStatus({ kind: "err", text: "Wait for the preview to finish loading." })
            return
        }
        if (!preview || preview.length === 0) {
            setStatus({
                kind: "err",
                text: "No rates match this adjustment. Change the name or percent first.",
            })
            return
        }
        setStatus({ kind: "idle", text: "" })
        setPendingConfirmation(true)
    }

    async function onConfirm(): Promise<void> {
        const p = percent.trim()
        if (!selected.trim() || p === "" || Number.isNaN(Number(p))) {
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
                    ...(adjustmentMode === "offset" ? { mode: "offset" } : {}),
                    ...(profileId ? { profileId } : {}),
                    ...(zoneId ? { zoneId } : {}),
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
            const parts: string[] = [`Updated ${data.updated} rate${data.updated === 1 ? "" : "s"}.`]
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
            setPendingConfirmation(false)
            const q = new URLSearchParams({ name: selected, percent: p })
            if (adjustmentMode === "offset") {
                q.set("mode", "offset")
            }
            if (profileId) {
                q.set("profileId", profileId)
            }
            if (zoneId) {
                q.set("zoneId", zoneId)
            }
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

    function onRevert(): void {
        setPendingConfirmation(false)
        setStatus({ kind: "idle", text: "" })
    }

    const busy = loadingNames || submitting
    const pTrim = percent.trim()
    const previewReady =
        Boolean(selected) && pTrim !== "" && !Number.isNaN(Number(pTrim))
    const controlsLocked = pendingConfirmation
    const canSet =
        previewReady &&
        !previewLoading &&
        Boolean(preview?.length) &&
        !pendingConfirmation

    return (
        <section className="shipping-rates" aria-labelledby="shipping-rates-heading">
            <h2 id="shipping-rates-heading" className="shipping-rates__title">
                Adjust shipping rates by name
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
                    {loadingNames ? (
                        <p className="shipping-rates__loading">Loading rate names…</p>
                    ) : names.length === 0 ? (
                        <p className="shipping-rates__list-hint">
                            No named shipping rates found, or they could not be loaded.
                        </p>
                    ) : (
                        <p className="shipping-rates__list-hint">
                            Narrow by delivery profile and zone, or leave both on All. Applies
                            where the rate name matches.
                        </p>
                    )}
                    <form onSubmit={onSubmitSet}>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="shipping-rate-name">Rate name</label>
                                <select
                                    id="shipping-rate-name"
                                    value={selected}
                                    onChange={(e) => setSelected(e.target.value)}
                                    disabled={busy || names.length === 0 || controlsLocked}
                                >
                                    {names.map((n) => (
                                        <option key={n} value={n}>
                                            {n}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="shipping-rates__field shipping-rates__field--filter">
                                <label htmlFor="shipping-profile">Delivery profile</label>
                                <select
                                    id="shipping-profile"
                                    value={profileId}
                                    onChange={(e) => onProfileChange(e.target.value)}
                                    disabled={busy || controlsLocked}
                                >
                                    <option value={ALL_VALUE}>All</option>
                                    {profiles.map((p) => (
                                        <option key={p.id} value={p.id}>
                                            {p.name || "Unnamed profile"}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="shipping-rates__field shipping-rates__field--filter">
                                <label htmlFor="shipping-zone">Delivery zone</label>
                                <select
                                    id="shipping-zone"
                                    value={zoneId}
                                    onChange={(e) => setZoneId(e.target.value)}
                                    disabled={busy || controlsLocked}
                                >
                                    <option value={ALL_VALUE}>All</option>
                                    {zoneOptions.map((z) => (
                                        <option key={z.id} value={z.id}>
                                            {z.name || "Unnamed zone"}
                                        </option>
                                    ))}
                                </select>
                            </div>
                            <div className="shipping-rates__field-group shipping-rates__field-group--value">
                                <div className="shipping-rates__field shipping-rates__field--mode">
                                    <span
                                        id="shipping-rate-adjustment-label"
                                        className="shipping-rates__segment-label"
                                    >
                                        Adjustment
                                    </span>
                                    <div
                                        className="shipping-rates__segment"
                                        role="group"
                                        aria-labelledby="shipping-rate-adjustment-label"
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
                                    <label htmlFor="shipping-rate-percent">
                                        {adjustmentMode === "percent" ? "Percent" : "Amount"}
                                    </label>
                                    <input
                                        id="shipping-rate-percent"
                                        type="text"
                                        inputMode="decimal"
                                        autoComplete="off"
                                        placeholder={
                                            adjustmentMode === "percent" ? "e.g. 10" : "e.g. 5 or -2"
                                        }
                                        value={percent}
                                        onChange={(e) => setPercent(e.target.value)}
                                        disabled={busy || controlsLocked}
                                        aria-describedby="shipping-rate-percent-hint"
                                    />
                                </div>
                            </div>
                            <button
                                type="submit"
                                className="shipping-rates__set"
                                disabled={busy || names.length === 0 || !canSet}
                            >
                                Set
                            </button>
                        </div>
                        <p id="shipping-rate-percent-hint" className="shipping-rates__list-hint">
                            {adjustmentMode === "percent" ? (
                                <>
                                    Positive increases price; negative decreases (e.g. -10 for 10%
                                    off).
                                </>
                            ) : (
                                <>
                                    Adds or subtracts this amount from each rate in its zone
                                    currency (negative reduces the price; results below zero become
                                    0).
                                </>
                            )}
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
                    {previewLoading ? (
                        <p className="shipping-rates__loading">Updating preview…</p>
                    ) : !previewReady ? (
                        <p className="shipping-rates__preview-empty">
                            Choose a rate name and enter a{" "}
                            {adjustmentMode === "percent" ? "percent" : "fixed amount change"} to
                            list affected rates.
                        </p>
                    ) : previewError ? (
                        <p className="shipping-rates__preview-empty" role="alert">
                            {previewError}
                        </p>
                    ) : !preview || preview.length === 0 ? (
                        <p className="shipping-rates__preview-empty">
                            No adjustable rates match this name (or none have a fixed price to
                            update).
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
