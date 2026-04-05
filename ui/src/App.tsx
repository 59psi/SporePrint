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

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/sessions" element={<Sessions />} />
        <Route path="/vision" element={<Vision />} />
        <Route path="/automation" element={<Automation />} />
        <Route path="/species" element={<Species />} />
        <Route path="/builder" element={<Builder />} />
        <Route path="/transcripts" element={<Transcripts />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
