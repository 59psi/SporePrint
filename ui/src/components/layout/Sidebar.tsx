import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Sprout,
  Camera,
  Cog,
  BookOpen,
  Wrench,
  FileText,
  Settings,
  Menu,
  X,
  Calendar,
  Wand2,
  Bug,
  GitBranch,
  Box,
  FlaskConical,
  ShoppingCart,
} from 'lucide-react'
import { useState } from 'react'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/sessions', icon: Sprout, label: 'Sessions' },
  { to: '/vision', icon: Camera, label: 'Vision' },
  { to: '/automation', icon: Cog, label: 'Automation' },
  { to: '/species', icon: BookOpen, label: 'Species' },
  { to: '/planner', icon: Calendar, label: 'Planner' },
  { to: '/wizard', icon: Wand2, label: 'Species Wizard' },
  { to: '/contamination', icon: Bug, label: 'Contamination' },
  { to: '/cultures', icon: GitBranch, label: 'Cultures' },
  { to: '/chambers', icon: Box, label: 'Chambers' },
  { to: '/experiments', icon: FlaskConical, label: 'Experiments' },
  { to: '/shopping', icon: ShoppingCart, label: 'Shopping List' },
  { to: '/builder', icon: Wrench, label: 'Builder' },
  { to: '/transcripts', icon: FileText, label: 'Transcripts' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function Sidebar() {
  const [open, setOpen] = useState(false)

  return (
    <>
      {/* Mobile toggle */}
      <button
        onClick={() => setOpen(!open)}
        className="fixed top-4 left-4 z-50 p-2 rounded-lg bg-[var(--color-bg-card)] lg:hidden"
      >
        {open ? <X size={20} /> : <Menu size={20} />}
      </button>

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-56 bg-[var(--color-bg-secondary)] border-r border-[var(--color-border)] flex flex-col transition-transform lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Logo */}
        <div className="p-5 border-b border-[var(--color-border)]">
          <h1 className="text-lg font-semibold tracking-tight">
            <span className="text-[var(--color-accent-gourmet)]">Spore</span>Print
          </h1>
          <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">Grow Automation</p>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-3 overflow-y-auto">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-5 py-2.5 text-sm transition-colors ${
                  isActive
                    ? 'text-[var(--color-text-primary)] bg-[var(--color-bg-hover)] border-r-2 border-[var(--color-accent-gourmet)]'
                    : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)]'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-[var(--color-border)] text-xs text-[var(--color-text-secondary)]">
          v3.0.25
        </div>
      </aside>

      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}
    </>
  )
}
