import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function Layout() {
  return (
    <div className="min-h-screen">
      <Sidebar />
      <main className="lg:ml-56 p-6 pt-16 lg:pt-6">
        <Outlet />
      </main>
    </div>
  )
}
