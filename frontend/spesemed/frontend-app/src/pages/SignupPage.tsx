import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ApiError } from '../lib/api';
import { SpinnerIcon, AlertCircleIcon, ShieldCheckIcon, CheckIcon } from '../components/Icons';

export const SignupPage: React.FC = () => {
  const { signup } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Calcolo forza password
  const hasMinLength = password.length >= 8;
  const hasLetter = /[a-zA-Z]/.test(password);
  const hasNumber = /[0-9]/.test(password);
  const isPasswordValid = hasMinLength && hasLetter && hasNumber;
  const doPasswordsMatch = password.length > 0 && password === confirmPassword;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!email.trim() || !password) {
      setErrorMsg('Compila tutti i campi obbligatori.');
      return;
    }

    if (!isPasswordValid) {
      setErrorMsg('La password deve contenere almeno 8 caratteri, una lettera e un numero.');
      return;
    }

    if (!doPasswordsMatch) {
      setErrorMsg('Le password inserite non coincidono.');
      return;
    }

    setIsLoading(true);
    setErrorMsg(null);

    try {
      await signup({ email: email.trim(), password });
      navigate('/app/dashboard', { replace: true });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 403) {
          setErrorMsg('Le registrazioni pubbliche sono temporaneamente disabilitate.');
        } else if (err.status === 429) {
          setErrorMsg('Troppe richieste di registrazione. Attendi prima di riprovare.');
        } else if (err.status === 400) {
          setErrorMsg('Indirizzo email o password non validi. Verifica i dati.');
        } else {
          setErrorMsg(err.detail);
        }
      } else {
        setErrorMsg('Impossibile completare la registrazione. Riprova più tardi.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{
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
          Crea il tuo archivio medico sicuro
        </p>
      </div>

      <div
        className="surface"
        style={{
          width: '100%',
          maxWidth: '480px',
          padding: 'clamp(1.8rem, 5vw, 2.6rem)',
          backgroundColor: '#ffffff',
          boxShadow: '0 4px 24px rgba(22, 33, 26, 0.07)',
        }}
      >
        <div style={{ marginBottom: '1.6rem' }}>
          <h2>Crea un account</h2>
          <p className="dim" style={{ fontSize: '0.95rem', marginTop: '0.3rem' }}>
            Inizia a organizzare le tue ricevute mediche in modo semplice.
          </p>
        </div>

        {errorMsg && (
          <div
            className="chip-err"
            style={{
              padding: '0.85rem 1rem',
              borderRadius: 'var(--radius-sm)',
              marginBottom: '1.4rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.6rem',
              fontSize: '0.9rem',
            }}
            role="alert"
          >
            <AlertCircleIcon size={18} style={{ flexShrink: 0 }} />
            <span>{errorMsg}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="signup-email">Indirizzo email</label>
            <input
              id="signup-email"
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
            <label htmlFor="signup-password">Password</label>
            <input
              id="signup-password"
              type="password"
              required
              autoComplete="new-password"
              className="in"
              placeholder="Minimo 8 caratteri"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />

            {/* Requisiti password visivi */}
            <div style={{ marginTop: '0.6rem', display: 'grid', gap: '0.35rem', fontSize: '0.82rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: hasMinLength ? 'var(--success)' : 'var(--ink-3)' }}>
                <CheckIcon size={14} style={{ opacity: hasMinLength ? 1 : 0.3 }} /> Almeno 8 caratteri
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: (hasLetter && hasNumber) ? 'var(--success)' : 'var(--ink-3)' }}>
                <CheckIcon size={14} style={{ opacity: (hasLetter && hasNumber) ? 1 : 0.3 }} /> Almeno una lettera e un numero
              </div>
            </div>
          </div>

          <div className="field">
            <label htmlFor="signup-confirm-password">Conferma password</label>
            <input
              id="signup-confirm-password"
              type="password"
              required
              autoComplete="new-password"
              className="in"
              placeholder="Ripeti la password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
            {confirmPassword.length > 0 && !doPasswordsMatch && (
              <p className="error-text">Le password non corrispondono.</p>
            )}
          </div>

          <button
            type="submit"
            className="btn btn-green btn-block"
            disabled={isLoading || !isPasswordValid || !doPasswordsMatch}
            style={{ marginTop: '0.8rem' }}
          >
            {isLoading ? (
              <>
                <SpinnerIcon size={18} /> Creazione account...
              </>
            ) : (
              'Registrati'
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
          Hai già un account?{' '}
          <Link to="/login" style={{ fontWeight: 700, color: 'var(--green-deep)' }}>
            Accedi
          </Link>
        </div>
      </div>

      <div style={{ marginTop: '1.6rem', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.86rem', color: 'var(--ink-3)' }}>
        <ShieldCheckIcon size={16} style={{ color: 'var(--success)' }} />
        <span>Spazio riservato e privato · Nessuna spesa pubblica</span>
      </div>
    </div>
  );
};
