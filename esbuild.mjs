import * as esbuild from "esbuild"
import fs from "fs"

esbuild.build({
    entryPoints: ["src/frontend/main.tsx"],
    outfile: "dist/script.js",
    tsconfig: "./tsconfig.json",
    jsx: "automatic",
    bundle: true,
    minify: true,
    sourcemap: true,
    platform: "browser",
    format: "iife",
    target: "es2020",
    globalName: "App",
    loader: {
        ".ts": "ts",
        ".tsx": "tsx"
    }
}).then(() => {
    fs.copyFileSync(
        "src/frontend/styles/graphql-stats.css",
        "dist/graphql-stats.css"
    )
    fs.copyFileSync(
        "src/frontend/styles/app-tabs.css",
        "dist/app-tabs.css"
    )
    fs.copyFileSync(
        "src/frontend/styles/shipping-rates.css",
        "dist/shipping-rates.css"
    )
});
