import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { AppProvider } from './context/AppContext';
import { ProtectedRoute, PublicOnlyRoute } from './components/ProtectedRoute';
import { Layout } from './components/Layout';

// Pagine
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { SignupPage } from './pages/SignupPage';
import { DashboardPage } from './pages/app/DashboardPage';
import { UploadPage } from './pages/app/UploadPage';
import { ResultsPage } from './pages/app/ResultsPage';
import { JobsPage } from './pages/app/JobsPage';
import { ExportPage } from './pages/app/ExportPage';
import { ProfilePage } from './pages/app/ProfilePage';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppProvider>
          <Routes>
            {/* Landing page pubblica */}
            <Route path="/" element={<LandingPage />} />

            {/* Rotte di autenticazione per utenti non autenticati */}
            <Route
              path="/login"
              element={
                <PublicOnlyRoute>
                  <LoginPage />
                </PublicOnlyRoute>
              }
            />
            <Route
              path="/signup"
              element={
                <PublicOnlyRoute>
                  <SignupPage />
                </PublicOnlyRoute>
              }
            />

            {/* Sezione App protetta da autenticazione */}
            <Route path="/app" element={<ProtectedRoute />}>
              <Route element={<Layout />}>
                <Route index element={<Navigate to="/app/dashboard" replace />} />
                <Route path="dashboard" element={<DashboardPage />} />
                <Route path="upload" element={<UploadPage />} />
                <Route path="results" element={<ResultsPage />} />
                <Route path="jobs" element={<JobsPage />} />
                <Route path="export" element={<ExportPage />} />
                <Route path="profile" element={<ProfilePage />} />
                {/* Alias: il ritorno da Stripe usa /app/profilo?billing=success|cancel */}
                <Route path="profilo" element={<ProfilePage />} />
              </Route>
            </Route>

            {/* Fallback per rotte sconosciute */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppProvider>
      </AuthProvider>
    </BrowserRouter>
  );
};

export default App;
