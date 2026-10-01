import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App_dev.jsx'
import './index.css'

// A render crash shows a bilingual "reload" card instead of a blank page.
// Reload also drops this tab's saved queue, in case that is what broke the render.
class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false } }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(err, info) { console.error('Alimne crashed:', err, info?.componentStack) }
  reload = () => {
    try { sessionStorage.removeItem('alimne_queue_v1') } catch { /* ignore */ }
    window.location.reload()
  }
  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div role="alert" style={{minHeight:'100vh', display:'flex', alignItems:'center', justifyContent:'center',
        padding:'16px', background:'#0a1628', color:'#e2e8f0', fontFamily:'Inter, system-ui, sans-serif'}}>
        <div style={{maxWidth:380, width:'100%', textAlign:'center', padding:'1.75rem 1.5rem', borderRadius:16,
          background:'rgba(255,255,255,0.04)', border:'1px solid rgba(148,163,184,0.25)'}}>
          <div style={{fontWeight:700, fontSize:'1.05rem', marginBottom:'0.4rem'}}>Something went wrong — please reload.</div>
          <div dir="rtl" lang="ar" style={{fontWeight:700, fontSize:'1.05rem', marginBottom:'1.25rem'}}>حدث خطأ ما — يرجى إعادة تحميل الصفحة.</div>
          <button onClick={this.reload} style={{padding:'0.7rem 1.4rem', borderRadius:10, border:'none', cursor:'pointer',
            background:'linear-gradient(135deg,#4f8ef7,#8b5cf6)', color:'#fff', fontWeight:700, fontSize:'0.92rem', fontFamily:'inherit'}}>
            Reload · إعادة التحميل
          </button>
        </div>
      </div>
    )
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
