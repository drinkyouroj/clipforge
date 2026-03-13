import { useNavigate, Link } from "react-router-dom";
import RegisterForm from "../components/Auth/RegisterForm";

export default function RegisterPage() {
  const navigate = useNavigate();

  return (
    <div className="auth-page">
      <RegisterForm onSuccess={() => navigate("/login")} />
      <p>
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </div>
  );
}
