import { Routes, Route } from 'react-router-dom'
import { Suspense, lazy } from 'react'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import { Loader2 } from 'lucide-react'

// Lazy-load all pages except Dashboard (initial landing page)
const Sessions = lazy(() => import('./pages/Sessions'))
const Vision = lazy(() => import('./pages/Vision'))
const Automation = lazy(() => import('./pages/Automation'))
const Species = lazy(() => import('./pages/Species'))
const Builder = lazy(() => import('./pages/Builder'))
const Transcripts = lazy(() => import('./pages/Transcripts'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const Planner = lazy(() => import('./pages/Planner'))
const Wizard = lazy(() => import('./pages/Wizard'))
const ContaminationGuide = lazy(() => import('./pages/ContaminationGuide'))
const Cultures = lazy(() => import('./pages/Cultures'))
const Chambers = lazy(() => import('./pages/Chambers'))
const Experiments = lazy(() => import('./pages/Experiments'))
const ShoppingList = lazy(() => import('./pages/ShoppingList'))

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="w-6 h-6 animate-spin text-emerald-400" />
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/sessions" element={<Suspense fallback={<PageLoader />}><Sessions /></Suspense>} />
        <Route path="/vision" element={<Suspense fallback={<PageLoader />}><Vision /></Suspense>} />
        <Route path="/automation" element={<Suspense fallback={<PageLoader />}><Automation /></Suspense>} />
        <Route path="/species" element={<Suspense fallback={<PageLoader />}><Species /></Suspense>} />
        <Route path="/planner" element={<Suspense fallback={<PageLoader />}><Planner /></Suspense>} />
        <Route path="/wizard" element={<Suspense fallback={<PageLoader />}><Wizard /></Suspense>} />
        <Route path="/contamination" element={<Suspense fallback={<PageLoader />}><ContaminationGuide /></Suspense>} />
        <Route path="/cultures" element={<Suspense fallback={<PageLoader />}><Cultures /></Suspense>} />
        <Route path="/chambers" element={<Suspense fallback={<PageLoader />}><Chambers /></Suspense>} />
        <Route path="/experiments" element={<Suspense fallback={<PageLoader />}><Experiments /></Suspense>} />
        <Route path="/shopping" element={<Suspense fallback={<PageLoader />}><ShoppingList /></Suspense>} />
        <Route path="/builder" element={<Suspense fallback={<PageLoader />}><Builder /></Suspense>} />
        <Route path="/transcripts" element={<Suspense fallback={<PageLoader />}><Transcripts /></Suspense>} />
        <Route path="/settings" element={<Suspense fallback={<PageLoader />}><SettingsPage /></Suspense>} />
      </Route>
    </Routes>
  )
}
