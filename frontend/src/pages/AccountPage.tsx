import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";

interface BillingStatus {
  subscription_tier: string;
  period_exports_used: number;
  exports_limit: number | null;
  exports_remaining: number | null;
  current_period_end: string | null;
}

interface UserInfo {
  id: string;
  email: string;
  email_verified: boolean;
  created_at: string;
}

interface ExportItem {
  id: string;
  platform: string;
  status: string;
  created_at: string;
  download_url: string | null;
}

export default function AccountPage() {
  const navigate = useNavigate();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [exports, setExports] = useState<ExportItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const [userResp, billingResp, exportsResp] = await Promise.all([
          api.get("/auth/me"),
          api.get("/billing/status"),
          api.get("/exports/?limit=20"),
        ]);
        setUser(userResp.data);
        setBilling(billingResp.data);
        setExports(exportsResp.data.exports || []);
      } catch {
        navigate("/login");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [navigate]);

  async function handleUpgrade(tier: string) {
    try {
      const resp = await api.post("/billing/checkout", { tier });
      window.location.href = resp.data.checkout_url;
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to start checkout");
    }
  }

  async function handleManageSubscription() {
    try {
      const resp = await api.post("/billing/portal");
      window.location.href = resp.data.portal_url;
    } catch (err: any) {
      alert(err.response?.data?.detail || "Failed to open billing portal");
    }
  }

  if (loading) return <p>Loading...</p>;
  if (!user || !billing) return <p>Could not load account info.</p>;

  const tierLabel = billing.subscription_tier.charAt(0).toUpperCase() + billing.subscription_tier.slice(1);
  const usagePercent = billing.exports_limit
    ? Math.min(100, Math.round((billing.period_exports_used / billing.exports_limit) * 100))
    : 0;

  return (
    <div className="account-page">
      <button onClick={() => navigate("/")} className="back-btn">
        Back to Dashboard
      </button>

      <h2>Account</h2>

      {/* Profile Section */}
      <section className="account-section">
        <h3>Profile</h3>
        <p><strong>Email:</strong> {user.email}</p>
        <p><strong>Member since:</strong> {new Date(user.created_at).toLocaleDateString()}</p>
      </section>

      {/* Subscription Section */}
      <section className="account-section">
        <h3>Subscription</h3>
        <div className="account-tier">
          <span className={`account-tier-badge account-tier-badge--${billing.subscription_tier}`}>
            {tierLabel}
          </span>
          {billing.current_period_end && (
            <span className="account-period-end">
              Renews {new Date(billing.current_period_end).toLocaleDateString()}
            </span>
          )}
        </div>

        {/* Usage */}
        <div className="account-usage">
          <div className="account-usage-label">
            <span>Exports this period</span>
            <span>
              {billing.period_exports_used}
              {billing.exports_limit ? ` / ${billing.exports_limit}` : " (unlimited)"}
            </span>
          </div>
          {billing.exports_limit && (
            <div className="progress-bar" style={{ height: "12px" }}>
              <div
                className="progress-fill"
                style={{
                  width: `${usagePercent}%`,
                  background: usagePercent >= 90 ? "#dc2626" : "#2563eb",
                }}
              />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="account-actions">
          {billing.subscription_tier === "free" && (
            <>
              <button className="account-upgrade-btn" onClick={() => handleUpgrade("starter")}>
                Upgrade to Starter ($19/mo)
              </button>
              <button className="account-upgrade-btn account-upgrade-btn--pro" onClick={() => handleUpgrade("pro")}>
                Upgrade to Pro ($49/mo)
              </button>
            </>
          )}
          {billing.subscription_tier !== "free" && (
            <button className="account-manage-btn" onClick={handleManageSubscription}>
              Manage Subscription
            </button>
          )}
        </div>
      </section>

      {/* Export History */}
      <section className="account-section">
        <h3>Export History</h3>
        {exports.length === 0 ? (
          <p className="account-empty">No exports yet.</p>
        ) : (
          <table className="account-exports-table">
            <thead>
              <tr>
                <th>Platform</th>
                <th>Status</th>
                <th>Date</th>
                <th>Download</th>
              </tr>
            </thead>
            <tbody>
              {exports.map((exp) => (
                <tr key={exp.id}>
                  <td>{exp.platform}</td>
                  <td>{exp.status}</td>
                  <td>{new Date(exp.created_at).toLocaleDateString()}</td>
                  <td>
                    {exp.download_url ? (
                      <a href={exp.download_url} className="download-btn" target="_blank" rel="noreferrer">
                        Download
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
