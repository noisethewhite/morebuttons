import ReactDOM from "react-dom/client"
import App from "./tsxsrc/app"
import doOAuth from "./tssrc/auth"
import { installGraphqlFetchInterceptor } from "./tssrc/graphql_fetch_interceptor"

const root = ReactDOM.createRoot(
    document.getElementById("root") as HTMLElement
)

async function main() {
    installGraphqlFetchInterceptor()
    const authResult = await doOAuth();
    console.log("Auth Result: ", authResult)
    if (authResult) { root.render(<App/>) }
}

document.addEventListener("DOMContentLoaded", main);
