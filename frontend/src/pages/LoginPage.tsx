import { useNavigate, Link } from "react-router-dom";
import LoginForm from "../components/Auth/LoginForm";

export default function LoginPage() {
  const navigate = useNavigate();

  return (
    <div className="auth-page">
      <LoginForm onSuccess={() => navigate("/")} />
      <p>
        Don't have an account? <Link to="/register">Sign up</Link>
      </p>
    </div>
  );
}
