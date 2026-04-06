import AppBridge from "./app_bridge"
import { clearGraphqlPhase } from "./graphql_fetch_interceptor"

const jsonInit: RequestInit = {
    credentials: "same-origin",
    method: "POST",
    headers: { "Content-Type": "application/json" },
}

/**
 * Starts a backend catalog job and POSTs ``/step`` until ``done``.
 * Phase progress is driven by response headers (see GraphqlStatsBar).
 */
export async function runSteppedCatalogJob(
    startUrl: string,
    stepUrl: string,
    startBody: Record<string, unknown>
): Promise<Record<string, unknown>> {
    const startRes = await AppBridge.fetchWithToken(startUrl, {
        ...jsonInit,
        body: JSON.stringify(startBody),
    })
    const startJson = (await startRes.json()) as { jobId?: string; error?: string }
    if (!startRes.ok) {
        clearGraphqlPhase()
        throw new Error(startJson.error ?? `Start failed (${startRes.status}).`)
    }
    const jobId = startJson.jobId
    if (typeof jobId !== "string" || !jobId) {
        clearGraphqlPhase()
        throw new Error("Server did not return a job id.")
    }
    for (;;) {
        const stepRes = await AppBridge.fetchWithToken(stepUrl, {
            ...jsonInit,
            body: JSON.stringify({ jobId }),
        })
        const stepJson = (await stepRes.json()) as {
            done?: boolean
            error?: string
        }
        if (!stepRes.ok) {
            clearGraphqlPhase()
            throw new Error(stepJson.error ?? `Step failed (${stepRes.status}).`)
        }
        if (stepJson.done === true) {
            clearGraphqlPhase()
            return stepJson as Record<string, unknown>
        }
    }
}
