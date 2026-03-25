import ReactDOM from "react-dom/client"
import App from "./tsxsrc/app"
import doOAuth from "./tssrc/auth"

const root = ReactDOM.createRoot(
    document.getElementById("root") as HTMLElement
)

async function main() {
    const authResult = await doOAuth();
    console.log("Auth Result: ", authResult)
    if (authResult) { root.render(<App/>) }
}

document.addEventListener("DOMContentLoaded", main);
