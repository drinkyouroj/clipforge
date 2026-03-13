import { useNavigate } from "react-router-dom";

export default function TermsPage() {
  const navigate = useNavigate();

  return (
    <div className="legal-page">
      <button onClick={() => navigate("/")} className="back-btn">
        Back
      </button>

      <h1>Terms of Service</h1>
      <p className="legal-updated">Last updated: March 13, 2026</p>

      <section>
        <h2>1. Acceptance of Terms</h2>
        <p>
          By creating an account or using ClipForge, you agree to be bound by these
          Terms of Service. If you do not agree, do not use the service.
        </p>
      </section>

      <section>
        <h2>2. Service Description</h2>
        <p>
          ClipForge is a video processing service that uses AI to detect viral-worthy
          segments from long-form videos, applies smart reframing and animated captions,
          and exports clips formatted for social media platforms.
        </p>
      </section>

      <section>
        <h2>3. User Content & Ownership</h2>
        <p>
          You retain all rights to the videos you upload. By uploading content, you grant
          ClipForge a limited license to process, store, and transform your content solely
          for the purpose of providing the service. We do not claim ownership of your content.
        </p>
      </section>

      <section>
        <h2>4. Acceptable Use</h2>
        <p>
          You agree not to upload content that is illegal, infringes on third-party rights,
          or violates applicable laws. We reserve the right to remove content that violates
          these terms without notice.
        </p>
      </section>

      <section>
        <h2>5. Limitation of Liability</h2>
        <p>
          ClipForge is provided "as is" without warranties of any kind. We are not liable
          for any damages arising from your use of the service, including but not limited to
          data loss, processing errors, or service interruptions.
        </p>
      </section>

      <section>
        <h2>6. Termination</h2>
        <p>
          We may terminate or suspend your account at any time for violations of these terms.
          You may delete your account at any time. Upon deletion, your data will be removed
          according to our data retention policy.
        </p>
      </section>

      <section>
        <h2>7. Changes to Terms</h2>
        <p>
          We may update these terms from time to time. Continued use of the service after
          changes constitutes acceptance of the new terms.
        </p>
      </section>

      <section>
        <h2>8. Contact</h2>
        <p>
          For questions about these terms, contact us at legal@clipforge.app.
        </p>
      </section>
    </div>
  );
}
