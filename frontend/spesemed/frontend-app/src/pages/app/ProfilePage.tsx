import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { api, ApiError } from '../../lib/api';
import { BillingStatusResponse } from '../../types/api';
import {
  LogoutIcon,
  RefreshIcon,
  SpinnerIcon,
  CheckIcon,
  AlertCircleIcon,
  ShieldCheckIcon,
  LockIcon,
  ArrowRightIcon,
} from '../../components/Icons';

export const ProfilePage: React.FC = () => {
  const { session, userEmail, userId, logout, refreshToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null);

  const [billing, setBilling] = useState<BillingStatusResponse | null>(null);
  const [isBillingLoading, setIsBillingLoading] = useState(true);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [isCheckoutLoading, setIsCheckoutLoading] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  const loadBilling = useCallback(async () => {
    setIsBillingLoading(true);
    setBillingError(null);
    try {
      const data = await api.billingStatus();
      setBilling(data);
    } catch (err) {
      console.warn('Lettura piano non riuscita:', err);
      setBillingError('Non riusciamo a leggere il tuo piano in questo momento.');
    } finally {
      setIsBillingLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBilling();
  }, [loadBilling]);

  const billingResult = searchParams.get('billing');

  useEffect(() => {
    if (billingResult !== 'success') return;
    let cancelled = false;
    let attempts = 0;
    let timer: number | undefined;

    const checkStatus = async () => {
      if (cancelled) return;
      let active = false;
      try {
        const data = await api.billingStatus();
        if (cancelled) return;
        setBilling(data);
        active =
          data.plan === 'pro' && (data.status === 'active' || data.status === 'trialing');
      } catch {
        active = false;
      }
      if (active) return;
      attempts += 1;
      if (attempts < 5) {
        timer = window.setTimeout(checkStatus, 3000);
      }
    };

    timer = window.setTimeout(checkStatus, 3000);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [billingResult]);

  const dismissBillingResult = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('billing');
    setSearchParams(next, { replace: true });
  };

  const handleCheckout = async () => {
    setIsCheckoutLoading(true);
    setCheckoutError(null);
    try {
      const result = await api.billingCheckout();
      if (!result.checkout_url) {
        throw new Error('Checkout senza URL');
      }
      window.location.assign(result.checkout_url);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.detail
          : 'Non siamo riusciti ad aprire il pagamento. Riprova tra poco.';
      setCheckoutError(message);
      setIsCheckoutLoading(false);
    }
  };

  const isPro =
    !!billing &&
    billing.plan === 'pro' &&
    (billing.status === 'active' || billing.status === 'trialing');

  const canSubscribe = !!billing && billing.billing_enabled && !isPro;

  const usageLimit = billing?.extractions_limit ?? 0;
  const usageUsed = billing?.extractions_used ?? 0;
  const usagePercent =
    usageLimit > 0 ? Math.min(100, Math.round((usageUsed / usageLimit) * 100)) : 0;

  const planLabel = billing?.plan === 'pro' ? 'Pro' : 'Gratuito';
  const checkoutLabel =
    billing?.status === 'past_due' ? 'Aggiorna il pagamento' : 'Abbonati a Pro';

  const statusLabel = (status?: string) => {
    switch (status) {
      case 'active':
        return 'Attivo';
      case 'trialing':
        return 'In prova';
      case 'past_due':
        return 'Pagamento da aggiornare';
      case 'canceled':
        return 'Annullato';
      case 'unpaid':
        return 'Da saldare';
      default:
        return 'Non attivo';
    }
  };

  const formatPeriodEnd = (value?: string | null) => {
    if (!value) return null;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return null;
    return parsed.toLocaleDateString('it-IT', { day: '2-digit', month: 'long', year: 'numeric' });
  };

  const periodEnd = formatPeriodEnd(billing?.period_end);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setNotice(null);
    try {
      await refreshToken();
      setNotice({ text: 'Sessione rinnovata. La tua protezione è aggiornata.' });
    } catch {
      setNotice({ text: 'Impossibile rinnovare la sessione. Effettua nuovamente l’accesso.', error: true });
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await logout();
      navigate('/login', { replace: true });
    } finally {
      setIsLoggingOut(false);
    }
  };

  const formatExpires = () => {
    if (!session?.expiresAt) return 'Sessione attiva';
    const diff = session.expiresAt - Date.now();
    if (diff <= 0) return 'In scadenza';
    const minutes = Math.floor(diff / 60_000);
    return `Valido per circa ${minutes} minuti`;
  };

  return (
    <div className="container ctr" style={{ paddingTop: '2.5rem' }}>
      <span className="chip chip-neut" style={{ marginBottom: '1rem', display: 'inline-flex' }}>
        Profilo e sicurezza
      </span>
      <h2 style={{ margin: '0.4rem 0 0.6rem' }}>Gestione account</h2>
      <p className="dim" style={{ marginBottom: '2rem' }}>
        Dati di autenticazione, sicurezza della sessione e stato dell’archivio privato.
      </p>

      {notice && (
        <div
          className={notice.error ? 'banner banner-err' : 'banner banner-ok'}
          style={{ marginBottom: '1.4rem' }}
          role={notice.error ? 'alert' : 'status'}
        >
          {notice.error ? <AlertCircleIcon size={16} /> : <CheckIcon size={16} />}
          <span>{notice.text}</span>
        </div>
      )}

      {billingResult && (
        <div
          className={billingResult === 'success' ? 'banner banner-ok' : 'banner banner-info'}
          style={{ marginBottom: '1.4rem', alignItems: 'center', flexWrap: 'wrap' }}
          role="status"
        >
          {billingResult === 'success' ? <CheckIcon size={16} /> : <AlertCircleIcon size={16} />}
          <span style={{ flex: '1 1 220px' }}>
            {billingResult === 'success'
              ? 'Pagamento completato. Stiamo attivando il piano Pro: può richiedere qualche secondo.'
              : 'Pagamento annullato. Nessun addebito è stato effettuato.'}
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={dismissBillingResult}>
            Chiudi
          </button>
        </div>
      )}

      {/* Scheda Utente */}
      <div className="surface" style={{ padding: '1.8rem', backgroundColor: 'var(--bg)', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
          <div
            style={{
              width: '54px',
              height: '54px',
              borderRadius: '50%',
              backgroundColor: 'var(--green)',
              color: 'var(--green-deep)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 800,
              fontSize: '1.25rem',
            }}
          >
            {userEmail.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: '1.15rem' }}>{userEmail}</div>
            <div className="mono dim" style={{ fontSize: '0.82rem', marginTop: '0.2rem' }}>
              ID: {userId || 'sessione-locale'}
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gap: '0.9rem', borderTop: '1px solid var(--line)', paddingTop: '1.2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>Stato sessione</span>
            <span className="chip chip-ok">
              <CheckIcon size={12} /> Autenticato
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>Scadenza token</span>
            <span className="mono dim" style={{ fontSize: '0.88rem' }}>
              {formatExpires()}
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>Archivio Storage</span>
            <span className="chip chip-neut" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
              <LockIcon size={12} /> Bucket privato cifrato
            </span>
          </div>
        </div>

        {/* Azioni sessione */}
        <div style={{ marginTop: '1.8rem', display: 'flex', gap: '0.8rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleRefresh}
            disabled={isRefreshing}
          >
            {isRefreshing ? (
              <>
                <SpinnerIcon size={14} /> Rinnovo...
              </>
            ) : (
              <>
                <RefreshIcon size={14} /> Rinnova sessione
              </>
            )}
          </button>

          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={handleLogout}
            disabled={isLoggingOut}
            style={{ marginLeft: 'auto' }}
          >
            {isLoggingOut ? (
              <>
                <SpinnerIcon size={14} /> Uscita...
              </>
            ) : (
              <>
                <LogoutIcon size={14} /> Esci dall’account
              </>
            )}
          </button>
        </div>
      </div>

      <div className="surface" style={{ padding: '1.8rem', marginBottom: '1.5rem' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '0.8rem',
            flexWrap: 'wrap',
            marginBottom: '1.1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <ShieldCheckIcon size={18} style={{ color: 'var(--green-deep)' }} />
            <h3 style={{ margin: 0 }}>Il tuo piano</h3>
          </div>
          {!isBillingLoading && billing && (
            <span className={isPro ? 'chip chip-ok' : 'chip chip-neut'}>
              {isPro && <CheckIcon size={12} />} {planLabel}
            </span>
          )}
        </div>

        {isBillingLoading ? (
          <div
            className="dim"
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 0' }}
            role="status"
          >
            <SpinnerIcon size={16} /> Carico il tuo piano...
          </div>
        ) : billingError ? (
          <div
            className="banner banner-info"
            style={{ alignItems: 'center', flexWrap: 'wrap' }}
            role="status"
          >
            <AlertCircleIcon size={16} />
            <span style={{ flex: '1 1 220px' }}>{billingError}</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={loadBilling}>
              Riprova
            </button>
          </div>
        ) : billing ? (
          <>
            <div
              style={{
                display: 'grid',
                gap: '0.9rem',
                borderTop: '1px solid var(--line)',
                paddingTop: '1.1rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>Stato del piano</span>
                <span className={isPro ? 'chip chip-ok' : 'chip chip-neut'}>
                  {statusLabel(billing.status)}
                </span>
              </div>

              {periodEnd && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>Prossimo rinnovo</span>
                  <span className="mono dim" style={{ fontSize: '0.88rem' }}>
                    {periodEnd}
                  </span>
                </div>
              )}

              <div>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    gap: '0.6rem',
                    marginBottom: '0.45rem',
                  }}
                >
                  <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>
                    Estrazioni questo mese
                  </span>
                  <span className="mono dim" style={{ fontSize: '0.88rem' }}>
                    {usageLimit > 0 ? `${usageUsed} di ${usageLimit}` : '—'}
                  </span>
                </div>

                {usageLimit > 0 && (
                  <div
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={usageLimit}
                    aria-valuenow={Math.min(usageUsed, usageLimit)}
                    aria-label="Estrazioni usate nel mese"
                    style={{ height: '8px', background: 'var(--line)', borderRadius: '4px', overflow: 'hidden' }}
                  >
                    <div
                      style={{
                        height: '100%',
                        width: `${usagePercent}%`,
                        background: 'var(--green)',
                        transition: 'width 0.4s var(--ease)',
                      }}
                    />
                  </div>
                )}

                <p className="dim" style={{ fontSize: '0.84rem', marginTop: '0.45rem' }}>
                  {!billing.billing_enabled
                    ? 'In questa fase non ci sono limiti di piano.'
                    : usageLimit > 0
                    ? `Ti restano ${Math.max(0, usageLimit - usageUsed)} estrazioni incluse.`
                    : 'Nessun piano attivo: attiva Pro per estrarre nuove ricevute.'}
                </p>
              </div>
            </div>

            {checkoutError && (
              <div className="banner banner-err" style={{ marginTop: '1.1rem' }} role="alert">
                <AlertCircleIcon size={16} />
                <span>{checkoutError}</span>
              </div>
            )}

            {canSubscribe ? (
              <div style={{ marginTop: '1.3rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <button
                  type="button"
                  className="btn btn-green btn-block"
                  onClick={handleCheckout}
                  disabled={isCheckoutLoading}
                >
                  {isCheckoutLoading ? (
                    <>
                      <SpinnerIcon size={18} /> Apro il pagamento...
                    </>
                  ) : (
                    <>
                      {checkoutLabel} <ArrowRightIcon size={16} />
                    </>
                  )}
                </button>
                <p className="dim" style={{ fontSize: '0.82rem', textAlign: 'center' }}>
                  Pagamento sicuro con Stripe. Puoi disdire quando vuoi.
                </p>
              </div>
            ) : isPro ? (
              <p className="dim" style={{ fontSize: '0.86rem', marginTop: '1.2rem' }}>
                Il piano Pro è attivo: tutte le estrazioni incluse sono a tua disposizione.
              </p>
            ) : (
              <p className="dim" style={{ fontSize: '0.86rem', marginTop: '1.2rem' }}>
                I pagamenti online non sono ancora attivi. Continui a usare SPESEMED come prima.
              </p>
            )}
          </>
        ) : null}
      </div>

      {/* Box Informazioni di Sicurezza */}
      <div className="band" style={{ borderRadius: 'var(--radius)', padding: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, fontSize: '0.95rem' }}>
          <ShieldCheckIcon size={18} style={{ color: 'var(--success)' }} />
          <span>Garanzia di riservatezza SPESEMED</span>
        </div>
        <p className="dim" style={{ fontSize: '0.86rem', marginTop: '0.5rem', lineHeight: '1.6' }}>
          Ogni accesso è protetto da credenziali che si rinnovano automaticamente. I documenti medici e
          gli scontrini restano in un archivio privato, accessibile solo a te. Nessun dato viene venduto
          o usato da terzi.
        </p>
      </div>
    </div>
  );
};
