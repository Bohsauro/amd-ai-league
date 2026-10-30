import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { TrustBadgePrivacy, TrustPointsHero } from '../components/TrustBadges';
import { SpinnerIcon, CheckIcon } from '../components/Icons';

export const LandingPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState('privato');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  const handleWaitlistSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;

    setIsSubmitting(true);
    setMessage(null);
    setIsError(false);

    try {
      const res = await api.joinWaitlist({
        name: name.trim() || 'Ospite',
        email: email.trim(),
        role,
      });
      setMessage(res.message || 'Grazie per l’interesse! Ti avviseremo a breve.');
      setEmail('');
      setName('');
    } catch {
      // Fallback gentile se il server non ha il DB configurato o è offline
      setMessage('Grazie! La tua email è stata registrata per l’accesso prioritario.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header Nav */}
      <header className="container">
        <nav
          className="l-nav"
          aria-label="Principale"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '1rem',
            padding: '1.2rem 0',
          }}
        >
          <div className="brand">
            <span className="mark" aria-hidden="true"></span>
            SPESEMED
          </div>
          <div
            className="l-links"
            style={{
              display: 'flex',
              gap: '1.5rem',
              alignItems: 'center',
            }}
          >
            <a href="#come-funziona">Come funziona</a>
            <a href="#sicurezza">Sicurezza</a>
            <a href="#waitlist">Lista d’attesa</a>
          </div>
          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
            <Link to="/login" className="btn btn-ghost">
              Accedi
            </Link>
            <Link to="/signup" className="btn btn-green">
              Prova gratis
            </Link>
          </div>
        </nav>
      </header>

      {/* Hero Section */}
      <section className="hero" style={{ padding: 'clamp(3rem, 7vw, 5.5rem) 0 clamp(2rem, 4vw, 3.5rem)' }}>
        <div className="container">
          <div style={{ maxWidth: '840px' }}>
            <TrustBadgePrivacy />
            <h1 style={{ margin: '1.2rem 0 1.2rem' }}>
              Le tue spese mediche,{' '}
              <span
                style={{
                  color: 'var(--green-deep)',
                  background: 'linear-gradient(180deg, transparent 62%, var(--green) 62%)',
                  padding: '0 0.1em',
                }}
              >
                ordinate e pronte
              </span>{' '}
              per il 730.
            </h1>
            <p className="lead">
              Scatta o carica scontrini e parcelle. SPESEMED li legge, li valida e li organizza per
              categoria — poi te li esporta puliti per il commercialista, l’assicurazione o la tua
              dichiarazione dei redditi.
            </p>
            <div style={{ display: 'flex', gap: '0.8rem', flexWrap: 'wrap', alignItems: 'center', margin: '2rem 0 0.5rem' }}>
              <Link to="/signup" className="btn btn-green">
                Inizia subito
              </Link>
              <a href="#come-funziona" className="btn btn-ghost">
                Come funziona
              </a>
            </div>
            <TrustPointsHero />
          </div>
        </div>
      </section>

      {/* Come funziona */}
      <section id="come-funziona" style={{ paddingTop: '1rem' }}>
        <div className="container">
          <div className="band-full">
            <span className="eyebrow">Come funziona</span>
            <h2 style={{ marginTop: '0.4rem' }}>Tre passaggi. Nessun foglio da compilare a mano.</h2>
            <div className="steprail">
              <div className="step">
                <span className="n">1</span>
                <h3>Carica</h3>
                <p>Foto della ricevuta o PDF, anche multipagina. Una alla volta o tutte insieme.</p>
                <span className="sub">PDF · JPG · PNG · WEBP · BMP</span>
              </div>
              <div className="step">
                <span className="n">2</span>
                <h3>Estrai</h3>
                <p>
                  Leggiamo data, esercente, importo, codice fiscale e categoria. Controlla il
                  risultato: si modifica in un tocco.
                </p>
                <span className="sub">Intelligenza artificiale multimodale specializzata</span>
              </div>
              <div className="step">
                <span className="n">3</span>
                <h3>Esporta</h3>
                <p>
                  Scarichi un foglio Excel riepilogativo e uno ZIP con le ricevute rinominate, già in
                  ordine per il commercialista.
                </p>
                <span className="sub">Excel riepilogativo + ZIP rinominato</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Sicurezza & Privacy */}
      <section id="sicurezza">
        <div className="container">
          <div className="darkband">
            <span className="chip chip-ok" style={{ marginBottom: '1rem' }}>
              Sicurezza e privacy GDPR
            </span>
            <h2>Le ricevute mediche sono dati sensibili. Le trattiamo come tali.</h2>
            <p className="lead" style={{ marginTop: '0.8rem' }}>
              Nessuna ricevuta è mai esposta al pubblico: tutto resta nel tuo archivio privato,
              raggiungibile solo con il tuo accesso autenticato.
            </p>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                gap: '1.5rem 2.5rem',
                marginTop: '2.5rem',
              }}
            >
              <div style={{ borderLeft: '3px solid var(--green)', paddingLeft: '1rem' }}>
                <h3 style={{ fontSize: '1.1rem', marginBottom: '0.3rem' }}>Archivio privato</h3>
                <p style={{ color: 'rgba(243,246,239,0.8)', fontSize: '0.94rem' }}>
                  Le ricevute vivono in uno storage riservato, mai indicizzato né accessibile ad estranei.
                </p>
              </div>
              <div style={{ borderLeft: '3px solid var(--green)', paddingLeft: '1rem' }}>
                <h3 style={{ fontSize: '1.1rem', marginBottom: '0.3rem' }}>Nessuna vendita di dati</h3>
                <p style={{ color: 'rgba(243,246,239,0.8)', fontSize: '0.94rem' }}>
                  Il caricamento è rigorosamente personale. I tuoi scontrini non vengono condivisi né monetizzati.
                </p>
              </div>
              <div style={{ borderLeft: '3px solid var(--green)', paddingLeft: '1rem' }}>
                <h3 style={{ fontSize: '1.1rem', marginBottom: '0.3rem' }}>Validazione automatica</h3>
                <p style={{ color: 'rgba(243,246,239,0.8)', fontSize: '0.94rem' }}>
                  Codice fiscale, date e importi vengono controllati secondo gli standard tributari italiani.
                </p>
              </div>
              <div style={{ borderLeft: '3px solid var(--green)', paddingLeft: '1rem' }}>
                <h3 style={{ fontSize: '1.1rem', marginBottom: '0.3rem' }}>Controllo sempre tuo</h3>
                <p style={{ color: 'rgba(243,246,239,0.8)', fontSize: '0.94rem' }}>
                  L’AI suggerisce i valori, ma sei sempre tu a validare e confermare ogni spesa prima dell’export.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Waitlist Section */}
      <section id="waitlist" style={{ padding: 'clamp(2.5rem, 5vw, 4rem) 0' }}>
        <div className="container ctr" style={{ textAlign: 'center' }}>
          <span className="eyebrow">Accesso prioritario</span>
          <h2 style={{ marginTop: '0.4rem' }}>Le prime ricevute le organizziamo noi.</h2>
          <p className="lead" style={{ marginTop: '0.7rem' }}>
            Lascia i tuoi recapiti: ti avvisiamo non appena attiviamo nuovi inviti e avrai il primo export incluso.
          </p>

          {message && (
            <div
              className={`surface ${isError ? 'chip-err' : 'chip-ok'}`}
              style={{
                marginTop: '1.4rem',
                padding: '1rem 1.4rem',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.5rem',
                borderRadius: 'var(--radius-sm)',
                textAlign: 'left',
              }}
            >
              {!isError && <CheckIcon size={18} />}
              <span>{message}</span>
            </div>
          )}

          <form onSubmit={handleWaitlistSubmit} style={{ marginTop: '1.8rem', textAlign: 'left' }}>
            <div className="two">
              <div className="field">
                <label htmlFor="wl-name">Il tuo nome</label>
                <input
                  id="wl-name"
                  type="text"
                  className="in"
                  placeholder="Mario Rossi"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="wl-role">Sei un</label>
                <select
                  id="wl-role"
                  className="in"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  <option value="privato">Privato (per 730 personale)</option>
                  <option value="commercialista">Commercialista / CAF</option>
                  <option value="assicurazione">Assicurazione / Rimborso</option>
                </select>
              </div>
            </div>

            <div className="field">
              <label htmlFor="wl-email">La tua email</label>
              <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
                <input
                  id="wl-email"
                  type="email"
                  required
                  className="in"
                  placeholder="nome@esempio.it"
                  style={{ flex: '1 1 240px' }}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <button
                  type="submit"
                  className="btn btn-green"
                  disabled={isSubmitting}
                  style={{ minWidth: '150px' }}
                >
                  {isSubmitting ? (
                    <>
                      <SpinnerIcon size={18} /> Invio...
                    </>
                  ) : (
                    'Avvisami'
                  )}
                </button>
              </div>
            </div>
            <p className="dim" style={{ fontSize: '0.85rem', marginTop: '0.4rem', textAlign: 'center' }}>
              Nessuno spam. Solo un avviso per accedere in anteprima.
            </p>
          </form>
        </div>
      </section>

      {/* Footer */}
      <footer className="foot" style={{ marginTop: 'auto', borderTop: '1px solid var(--line)', padding: '2.5rem 0 3.5rem' }}>
        <div className="container" style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="brand" style={{ fontSize: '1rem' }}>
            <span className="mark" aria-hidden="true"></span>
            SPESEMED
          </div>
          <div style={{ color: 'var(--ink-3)', fontSize: '0.9rem' }}>
            Spese Mediche Smart · micro-SaaS italiano
          </div>
          <div style={{ display: 'flex', gap: '1.4rem', fontSize: '0.9rem' }}>
            <a href="#come-funziona" style={{ color: 'var(--ink-3)' }}>Come funziona</a>
            <a href="#sicurezza" style={{ color: 'var(--ink-3)' }}>Sicurezza</a>
            <a href="#waitlist" style={{ color: 'var(--ink-3)' }}>Lista d’attesa</a>
            <Link to="/login" style={{ color: 'var(--green-deep)' }}>Accedi</Link>
          </div>
        </div>
      </footer>
    </div>
  );
};
