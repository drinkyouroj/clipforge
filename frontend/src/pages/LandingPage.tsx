import { useNavigate, Link } from "react-router-dom";

const TIERS = [
  {
    name: "Free",
    price: "$0",
    period: "/month",
    features: ["10 exports/month", "All platforms", "AI clip detection", "Smart reframe"],
    cta: "Get Started",
    href: "/register",
    highlight: false,
  },
  {
    name: "Starter",
    price: "$19",
    period: "/month",
    features: ["100 exports/month", "All platforms", "AI clip detection", "Smart reframe", "Animated captions"],
    cta: "Start Free Trial",
    href: "/register",
    highlight: true,
  },
  {
    name: "Pro",
    price: "$49",
    period: "/month",
    features: ["Unlimited exports", "All platforms", "AI clip detection", "Smart reframe", "Animated captions", "Multi-platform export"],
    cta: "Go Pro",
    href: "/register",
    highlight: false,
  },
];

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="landing">
      {/* Hero */}
      <section className="landing__hero">
        <h1>Turn long videos into viral clips with AI</h1>
        <p className="landing__subtitle">
          Upload a podcast, talk, or stream. ClipForge detects the most viral-worthy
          moments, reframes for any platform, and burns in animated captions.
        </p>
        <button className="landing__cta" onClick={() => navigate("/register")}>
          Get Started Free
        </button>
      </section>

      {/* How It Works */}
      <section className="landing__steps">
        <h2>How It Works</h2>
        <div className="landing__steps-grid">
          <div className="landing__step">
            <div className="landing__step-number">1</div>
            <h3>Upload</h3>
            <p>Drop in your long-form video — podcast, talk, stream, vlog.</p>
          </div>
          <div className="landing__step">
            <div className="landing__step-number">2</div>
            <h3>AI Detects Clips</h3>
            <p>Our AI analyzes the transcript and finds the most engaging moments.</p>
          </div>
          <div className="landing__step">
            <div className="landing__step-number">3</div>
            <h3>Export</h3>
            <p>Smart reframe, animated captions, and platform-ready formats.</p>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="landing__features">
        <h2>Features</h2>
        <div className="landing__features-grid">
          <div className="landing__feature">
            <h3>AI Virality Scoring</h3>
            <p>Each clip gets a virality score based on hook strength, information density, emotional resonance, and shareability.</p>
          </div>
          <div className="landing__feature">
            <h3>Smart Reframe</h3>
            <p>Automatic face detection and smooth crop for 9:16 (Shorts, TikTok, Reels), 1:1 (Square), and 16:9 (Twitter).</p>
          </div>
          <div className="landing__feature">
            <h3>Animated Captions</h3>
            <p>Word-by-word highlighted captions burned directly into the video. No separate subtitle file needed.</p>
          </div>
          <div className="landing__feature">
            <h3>Multi-Platform Export</h3>
            <p>One click to export for YouTube Shorts, TikTok, Instagram Reels, Instagram Square, or X (Twitter).</p>
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="landing__pricing">
        <h2>Pricing</h2>
        <div className="landing__pricing-grid">
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              className={`landing__tier ${tier.highlight ? "landing__tier--highlight" : ""}`}
            >
              <h3>{tier.name}</h3>
              <div className="landing__tier-price">
                <span className="landing__tier-amount">{tier.price}</span>
                <span className="landing__tier-period">{tier.period}</span>
              </div>
              <ul className="landing__tier-features">
                {tier.features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <button
                className={`landing__tier-cta ${tier.highlight ? "landing__tier-cta--highlight" : ""}`}
                onClick={() => navigate(tier.href)}
              >
                {tier.cta}
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="landing__footer">
        <div className="landing__footer-links">
          <Link to="/terms">Terms of Service</Link>
          <Link to="/privacy">Privacy Policy</Link>
          <Link to="/login">Log In</Link>
        </div>
        <p>&copy; 2026 ClipForge</p>
      </footer>
    </div>
  );
}
