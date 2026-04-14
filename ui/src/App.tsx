import { Routes, Route } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import Sessions from './pages/Sessions'
import Vision from './pages/Vision'
import Automation from './pages/Automation'
import Species from './pages/Species'
import Builder from './pages/Builder'
import Transcripts from './pages/Transcripts'
import SettingsPage from './pages/SettingsPage'
import Planner from './pages/Planner'
import Wizard from './pages/Wizard'
import ContaminationGuide from './pages/ContaminationGuide'
import Cultures from './pages/Cultures'
import Chambers from './pages/Chambers'
import Experiments from './pages/Experiments'
import ShoppingList from './pages/ShoppingList'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/sessions" element={<Sessions />} />
        <Route path="/vision" element={<Vision />} />
        <Route path="/automation" element={<Automation />} />
        <Route path="/species" element={<Species />} />
        <Route path="/planner" element={<Planner />} />
        <Route path="/wizard" element={<Wizard />} />
        <Route path="/contamination" element={<ContaminationGuide />} />
        <Route path="/cultures" element={<Cultures />} />
        <Route path="/chambers" element={<Chambers />} />
        <Route path="/experiments" element={<Experiments />} />
        <Route path="/shopping" element={<ShoppingList />} />
        <Route path="/builder" element={<Builder />} />
        <Route path="/transcripts" element={<Transcripts />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
