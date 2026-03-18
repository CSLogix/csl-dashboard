import * as Sentry from '@sentry/react'
import DispatchDashboard from './DispatchDashboard'

function App() {
  return (
    <Sentry.ErrorBoundary fallback={<div style={{ padding: 40, color: '#fff', background: '#0A0E17', minHeight: '100vh', fontFamily: 'sans-serif' }}>
      <h2>Something went wrong</h2>
      <p style={{ color: '#8B95A8', marginTop: 8 }}>The error has been reported. Try refreshing the page.</p>
    </div>}>
      <DispatchDashboard />
    </Sentry.ErrorBoundary>
  )
}

export default App
