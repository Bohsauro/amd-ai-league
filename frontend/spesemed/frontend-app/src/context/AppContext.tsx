import React, { createContext, useContext, useState, useEffect } from 'react';
import { SpesaMedica } from '../types/api';

interface AppContextType {
  expenses: SpesaMedica[];
  setExpenses: React.Dispatch<React.SetStateAction<SpesaMedica[]>>;
  addExpenses: (newItems: SpesaMedica[]) => void;
  updateExpense: (id: string, updated: Partial<SpesaMedica>) => void;
  confirmExpense: (id: string) => void;
  removeExpense: (id: string) => void;
  activeJobId: string | null;
  setActiveJobId: (id: string | null) => void;
  summaryRefreshTrigger: number;
  triggerSummaryRefresh: () => void;
}

const STORAGE_EXPENSES_KEY = 'spesemed_local_expenses_v2';

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [expenses, setExpenses] = useState<SpesaMedica[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_EXPENSES_KEY);
      if (saved) {
        return JSON.parse(saved);
      }
    } catch {
      // fallback
    }
    return [];
  });

  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [summaryRefreshTrigger, setSummaryRefreshTrigger] = useState<number>(0);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_EXPENSES_KEY, JSON.stringify(expenses));
    } catch (e) {
      console.warn('Impossibile salvare spese in localStorage:', e);
    }
  }, [expenses]);

  const addExpenses = (newItems: SpesaMedica[]) => {
    const prepared = newItems.map((item, idx) => ({
      ...item,
      id: item.id || `exp-${Date.now()}-${idx}`,
      status: item.status || 'pending',
    }));
    setExpenses((prev) => [...prepared, ...prev]);
    setSummaryRefreshTrigger((t) => t + 1);
  };

  const updateExpense = (id: string, updated: Partial<SpesaMedica>) => {
    setExpenses((prev) =>
      prev.map((exp) => (exp.id === id ? { ...exp, ...updated } : exp))
    );
    setSummaryRefreshTrigger((t) => t + 1);
  };

  const confirmExpense = (id: string) => {
    updateExpense(id, { status: 'validated' });
  };

  const removeExpense = (id: string) => {
    setExpenses((prev) => prev.filter((exp) => exp.id !== id));
    setSummaryRefreshTrigger((t) => t + 1);
  };

  const triggerSummaryRefresh = () => {
    setSummaryRefreshTrigger((t) => t + 1);
  };

  return (
    <AppContext.Provider
      value={{
        expenses,
        setExpenses,
        addExpenses,
        updateExpense,
        confirmExpense,
        removeExpense,
        activeJobId,
        setActiveJobId,
        summaryRefreshTrigger,
        triggerSummaryRefresh,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export function useApp(): AppContextType {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
}
