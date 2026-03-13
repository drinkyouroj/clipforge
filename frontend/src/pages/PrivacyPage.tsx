import { useNavigate } from "react-router-dom";

export default function PrivacyPage() {
  const navigate = useNavigate();

  return (
    <div className="legal-page">
      <button onClick={() => navigate("/")} className="back-btn">
        Back
      </button>

      <h1>Privacy Policy</h1>
      <p className="legal-updated">Last updated: March 13, 2026</p>

      <section>
        <h2>1. Data We Collect</h2>
        <p>
          We collect the following information: email address (for account creation),
          video files you upload (for processing), payment information (processed by
          Stripe — we do not store card details), and usage data (export counts, login times).
        </p>
      </section>

      <section>
        <h2>2. How We Use Your Data</h2>
        <p>
          Your data is used solely to provide the ClipForge service: processing videos,
          generating transcripts, detecting clips, rendering exports, and managing your
          subscription. We do not sell your data to third parties.
        </p>
      </section>

      <section>
        <h2>3. Data Retention</h2>
        <p>
          Uploaded videos are automatically deleted 30 days after upload. Rendered exports
          are retained until the source video is deleted. You can delete your videos at any
          time from the dashboard.
        </p>
      </section>

      <section>
        <h2>4. Data Deletion</h2>
        <p>
          You can delete individual videos using the delete button on the dashboard.
          Deleting a video immediately removes the video file and all rendered exports
          from our storage. Database records are purged within 7 days.
        </p>
      </section>

      <section>
        <h2>5. Third-Party Services</h2>
        <p>
          ClipForge uses the following third-party services to provide the service:
        </p>
        <ul>
          <li><strong>Stripe</strong> — payment processing. See Stripe's privacy policy.</li>
          <li><strong>OpenAI (Whisper)</strong> — audio transcription. Audio is sent to OpenAI's API for transcription.</li>
          <li><strong>Anthropic (Claude)</strong> — clip detection. Transcript text is sent to Anthropic's API for analysis.</li>
          <li><strong>Cloudflare R2</strong> — file storage. Videos and exports are stored in Cloudflare R2.</li>
        </ul>
      </section>

      <section>
        <h2>6. Contact</h2>
        <p>
          For privacy-related questions, contact us at privacy@clipforge.app.
        </p>
      </section>
    </div>
  );
}
