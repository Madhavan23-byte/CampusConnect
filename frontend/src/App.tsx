import { BrowserRouter, Route, Routes, Navigate } from 'react-router-dom'

/**
 * CampusConnect App Root
 * Router and top-level route structure.
 * Individual feature pages are registered here.
 * Auth protection and role-based routing is implemented in router/index.tsx (Day 2+).
 */
function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Placeholder routes — full implementation in Day 2 */}
        <Route
          path="/"
          element={
            <div className="min-h-screen flex items-center justify-center bg-surface-50">
              <div className="card p-8 max-w-md w-full text-center animate-fade-in">
                <div className="w-16 h-16 bg-primary-600 rounded-2xl flex items-center justify-center mx-auto mb-4">
                  <span className="text-white text-2xl font-bold">CC</span>
                </div>
                <h1 className="text-2xl font-bold text-surface-900 mb-2">CampusConnect</h1>
                <p className="text-surface-500 text-sm mb-6">
                  College Club &amp; Event Governance Platform
                </p>
                <div className="bg-success-50 border border-success-500 rounded-lg px-4 py-3">
                  <p className="text-success-700 text-sm font-medium">
                    ✅ Day 1 Foundation Complete
                  </p>
                  <p className="text-success-700 text-xs mt-1">
                    Backend, database schema, and frontend scaffold ready.
                  </p>
                </div>
                <p className="text-surface-400 text-xs mt-4">
                  Authentication and full UI — Day 2
                </p>
              </div>
            </div>
          }
        />
        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
