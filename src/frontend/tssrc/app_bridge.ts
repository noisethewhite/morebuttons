export default class AppBridge {
    static #app: unknown;
    static #getSessionToken: (app: unknown) => Promise<string>;
    static #created: boolean = false;

    static #create(): void {
        const apiKey: string = document.body?.dataset.apiKey ?? "";
        const host: string = new URL(window.location.href).searchParams.get("host") ?? "";

        const appBridge = (window as any)["app-bridge"];
        const createApp = appBridge?.default as (opts: { apiKey: string; host: string; forceRedirect: boolean }) => unknown;

        AppBridge.#app = createApp({ apiKey, host, forceRedirect: true });

        AppBridge.#getSessionToken = ((window as any)["app-bridge-utils"] as {
            getSessionToken: (app: unknown) => Promise<string>;
        }).getSessionToken;

        Object.freeze(AppBridge.#app as object);
        Object.freeze(AppBridge.#getSessionToken as unknown as object);
        AppBridge.#created = true;
    };

    static async fetchWithToken(path: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
        if (!AppBridge.#created) { AppBridge.#create() }
        const token = await AppBridge.#getSessionToken(AppBridge.#app);
        const headers = new Headers((init as any).headers || {});
        headers.set("Authorization", `Bearer ${token}`);
        return fetch(path, { ...init, headers });
    }
}
