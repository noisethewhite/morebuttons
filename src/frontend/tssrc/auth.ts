import AppBridge from "./app_bridge"


interface OAuthResult {
    oauthSuccess: boolean
}


export default async function doOAuth(): Promise<boolean> {
    try {
        const data: OAuthResult = await (
            (await AppBridge.fetchWithToken("/api/oauth", { method: "POST" })).json()
        )
        return data.oauthSuccess
    } catch (_) {
        return false
    }
}
