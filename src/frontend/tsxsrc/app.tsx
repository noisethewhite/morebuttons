import { ReactNode } from "react"
import GraphqlStatsBar from "./GraphqlStatsBar"
import ShippingRatesPanel from "./ShippingRatesPanel"

export default function App(): ReactNode {
    return (
        <main>
            <GraphqlStatsBar />
            <ShippingRatesPanel />
        </main>
    )
}
