import React, { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ApiError } from '../lib/api';
import { SpinnerIcon, AlertCircleIcon, ShieldCheckIcon } from '../components/Icons';

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Per reindirizzare alla pagina tentata originariamente
  const fromLocation = (location.state as { from?: { pathname: string } })?.from?.pathname || '/app/dashboard';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setErrorMsg('Inserisci sia l’email che la password.');
      return;
    }

    setIsLoading(true);
    setErrorMsg(null);

    try {
      await login({ email: email.trim(), password });
      navigate(fromLocation, { replace: true });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setErrorMsg('Credenziali non valide. Controlla email e password.');
        } else if (err.status === 422) {
          setErrorMsg('Controlla i dati inseriti: email o password non sono validi.');
        } else if (err.status === 429) {
          setErrorMsg('Troppi tentativi di accesso. Per sicurezza attendi un minuto.');
        } else if (err.status === 503) {
          setErrorMsg('Servizio di autenticazione temporaneamente non disponibile.');
        } else {
          setErrorMsg(err.detail);
        }
      } else {
        setErrorMsg('Si è verificato un errore durante l’accesso. Riprova più tardi.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      padding: '2rem 1rem',
      backgroundColor: 'var(--surface)',
    }}>
      <div style={{ marginBottom: '2rem', textAlign: 'center' }}>
        <Link to="/" className="brand" style={{ display: 'inline-flex', fontSize: '1.4rem' }}>
          <span className="mark" aria-hidden="true"></span>
          SPESEMED
        </Link>
        <p className="dim" style={{ fontSize: '0.92rem', marginTop: '0.4rem' }}>
          Spese mediche ordinate e pronte per il commercialista
        </p>
      </div>

      <div
        className="surface"
        style={{
          width: '100%',
          maxWidth: '460px',
          padding: 'clamp(1.8rem, 5vw, 2.6rem)',
          backgroundColor: 'var(--bg)',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <div style={{ marginBottom: '1.6rem' }}>
          <h1 style={{ fontSize: 'clamp(1.6rem, 4vw, 2rem)' }}>Bentornato</h1>
          <p className="dim" style={{ fontSize: '0.95rem', marginTop: '0.3rem' }}>
            Accedi per gestire ed esportare le tue spese mediche.
          </p>
        </div>

        {errorMsg && (
          <div
            className="banner banner-err"
            style={{ marginBottom: '1.4rem' }}
            role="alert"
          >
            <AlertCircleIcon size={18} />
            <span>{errorMsg}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="login-email">Indirizzo email</label>
            <input
              id="login-email"
              type="email"
              required
              autoComplete="email"
              className="in"
              placeholder="nome@esempio.it"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              required
              autoComplete="current-password"
              className="in"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <button
            type="submit"
            className="btn btn-green btn-block"
            disabled={isLoading}
            style={{ marginTop: '0.6rem' }}
          >
            {isLoading ? (
              <>
                <SpinnerIcon size={18} /> Accesso in corso...
              </>
            ) : (
              'Accedi'
            )}
          </button>
        </form>

        <div style={{
          marginTop: '1.8rem',
          paddingTop: '1.2rem',
          borderTop: '1px solid var(--line)',
          textAlign: 'center',
          fontSize: '0.92rem',
          color: 'var(--ink-2)',
        }}>
          Non hai ancora un account?{' '}
          <Link to="/signup" style={{ fontWeight: 700, color: 'var(--green-deep)' }}>
            Registrati gratis
          </Link>
        </div>
      </div>

      <div style={{ marginTop: '1.6rem', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.86rem', color: 'var(--ink-3)' }}>
        <ShieldCheckIcon size={16} style={{ color: 'var(--success-strong)' }} />
        <span>Connessione protetta con cifratura · Privacy GDPR</span>
      </div>
    </main>
  );
};
