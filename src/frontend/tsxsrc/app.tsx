import { ReactNode, useState } from "react"
import GraphqlStatsBar from "./GraphqlStatsBar"
import OrderLookupPanel from "./OrderLookupPanel"
import ProductTagPricingPanel from "./ProductTagPricingPanel"
import ShippingRatesPanel from "./ShippingRatesPanel"
import SkuWeightPanel from "./SkuWeightPanel"
import AddVariantPanel from "./AddVariantPanel"

type TabId = "shipping" | "products" | "orders" | "skuweight" | "addvariant"

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
                    <button
                        type="button"
                        role="tab"
                        id="tab-orders"
                        className={
                            tab === "orders"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "orders"}
                        aria-controls="panel-orders"
                        onClick={() => setTab("orders")}
                    >
                        Order lookup
                    </button>
                    <button
                        type="button"
                        role="tab"
                        id="tab-skuweight"
                        className={
                            tab === "skuweight"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "skuweight"}
                        aria-controls="panel-skuweight"
                        onClick={() => setTab("skuweight")}
                    >
                        SKU weights
                    </button>
                    <button
                        type="button"
                        role="tab"
                        id="tab-addvariant"
                        className={
                            tab === "addvariant"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "addvariant"}
                        aria-controls="panel-addvariant"
                        onClick={() => setTab("addvariant")}
                    >
                        Add variant
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
                <div
                    id="panel-orders"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-orders"
                    hidden={tab !== "orders"}
                >
                    <OrderLookupPanel />
                </div>
                <div
                    id="panel-skuweight"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-skuweight"
                    hidden={tab !== "skuweight"}
                >
                    <SkuWeightPanel />
                </div>
                <div
                    id="panel-addvariant"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-addvariant"
                    hidden={tab !== "addvariant"}
                >
                    <AddVariantPanel />
                </div>
            </div>
        </main>
    )
}
