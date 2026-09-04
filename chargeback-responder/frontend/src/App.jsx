import { useState } from "react";
import MerchantDashboard from "./MerchantDashboard";
import CustomerPortal from "./CustomerPortal";
import "./App.css";

export default function App() {
  const [tab, setTab] = useState("merchant");
  const [merchantToken, setMerchantToken] = useState(
    () => {
      const token = localStorage.getItem("merchant_token");
      // Never silently retain the old repository-wide demo credential.
      return token === "demo_merchant_token" ? "" : (token || "");
    }
  );

  const handleTokenChange = (value) => {
    setMerchantToken(value);
    localStorage.setItem("merchant_token", value);
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar__title">
          <h1>Chargeback Evidence Responder</h1>
          <span>ai risk desk</span>
        </div>

        <nav className="tabs">
          <button data-active={tab === "merchant"} onClick={() => setTab("merchant")}>
            Merchant Dashboard
          </button>
          <button data-active={tab === "customer"} onClick={() => setTab("customer")}>
            Customer Portal
          </button>
        </nav>

        {tab === "merchant" ? (
          <div className="token-bar">
            <label htmlFor="merchant-token" style={{ fontSize: 11, color: "var(--text-dim)" }}>
              Merchant token
            </label>
            <input
              id="merchant-token"
              value={merchantToken}
              onChange={(e) => handleTokenChange(e.target.value)}
            />
          </div>
        ) : (
          <div />
        )}
      </header>

      {tab === "merchant" ? (
        <MerchantDashboard merchantToken={merchantToken} setMerchantToken={handleTokenChange} />
      ) : (
        <CustomerPortal />
      )}
    </div>
  );
}
