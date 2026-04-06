import { ReactNode, useState } from "react"
import GraphqlStatsBar from "./GraphqlStatsBar"
import ProductTagPricingPanel from "./ProductTagPricingPanel"
import ShippingRatesPanel from "./ShippingRatesPanel"

type TabId = "shipping" | "products"

export default function App(): ReactNode {
    const [tab, setTab] = useState<TabId>("shipping")

    return (
        <main>
            <GraphqlStatsBar />
            <div className="app-tabs">
                <div className="app-tabs__bar" role="tablist" aria-label="Pricing tools">
                    <button
                        type="button"
                        role="tab"
                        id="tab-shipping"
                        className={
                            tab === "shipping"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "shipping"}
                        aria-controls="panel-shipping"
                        onClick={() => setTab("shipping")}
                    >
                        Delivery rates
                    </button>
                    <button
                        type="button"
                        role="tab"
                        id="tab-products"
                        className={
                            tab === "products"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "products"}
                        aria-controls="panel-products"
                        onClick={() => setTab("products")}
                    >
                        Product tag prices
                    </button>
                </div>
                <div
                    id="panel-shipping"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-shipping"
                    hidden={tab !== "shipping"}
                >
                    <ShippingRatesPanel />
                </div>
                <div
                    id="panel-products"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-products"
                    hidden={tab !== "products"}
                >
                    <ProductTagPricingPanel />
                </div>
            </div>
        </main>
    )
}
