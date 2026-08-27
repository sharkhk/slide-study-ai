import { useState, useRef, useCallback, useEffect } from 'react'
import { createClient } from '@supabase/supabase-js'
import {
  Sun, Moon, Upload, FileText, Download,
  Loader2, CheckCircle2, AlertCircle, Sparkles, RotateCcw,
  Globe, X, Files, ChevronDown,
  Youtube, Type, Brain, BarChart2, Map, Printer,
  ThumbsUp, ThumbsDown, MessageSquare, History, ClipboardList, ShieldCheck, ScrollText,
  LogIn, LogOut, User, Zap, Copy, Gift
} from 'lucide-react'

// Alimne brand mark — the "A + spark" glyph (white, for use inside a gradient tile)
const AlimneGlyph = ({ size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 96 96" fill="none" aria-hidden="true">
    <path d="M31 69 L48 27 L65 69" fill="none" stroke="#fff" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M39.5 55 H56.5" stroke="#fff" strokeWidth="8" strokeLinecap="round"/>
    <path d="M71 24 l2.4 6 6 2.4 -6 2.4 -2.4 6 -2.4 -6 -6 -2.4 6 -2.4 Z" fill="#fff"/>
  </svg>
)

const T = {
  en: {
    brand: 'Alimne',
    badge: 'AI-Powered · Smart Study',
    h1a: 'Turn Slides into',
    h1b: 'Study Guides',
    sub: 'Upload slides, paste text, or enter a YouTube URL to get exam-ready study guides.',
    dropTitle: 'Drop your PowerPoint or PDF files here',
    dropSub: 'or click to browse — .pptx / .ppt / .pdf / .docx / .doc / .txt, multiple files supported',
    langAuto: 'Auto-detect language',
    langEn: 'English output',
    langAr: 'Arabic output (عربي)',
    privacy: 'Your files are processed in memory only — never written to disk or seen by anyone. Everything is wiped automatically within 15 minutes.',
    generateAll: 'Generate All',
    generating: 'Processing…',
    download: 'Download PDF',
    addMore: 'Add more files',
    clearAll: 'Clear all',
    queued: 'Queued',
    processing: 'Processing…',
    done: 'Ready',
    error: 'Failed',
    pills: ['Multiple files', 'Individual downloads', 'Smart AI'],
    ollamaOff: 'AI service not reachable',
    ollamaOffSub: 'The backend may still be starting up. Please wait a moment.',
    tabUpload: 'Upload File',
    tabYoutube: 'YouTube URL',
    tabText: 'Paste Text / URL',
    ytPlaceholder: 'https://youtube.com/watch?v=...',
    ytBtn: 'Generate from YouTube',
    textPlaceholder: 'Paste article text here…',
    urlPlaceholder: 'https://example.com/article (fetches page text)',
    textBtn: 'Generate from Text',
    // Auth
    loginTitle: 'Sign in to continue',
    loginSub: '3 free tokens per month — no credit card required',
    loginBtn: 'Continue with Google',
    emailPh: 'you@email.com',
    passwordPh: 'Password (min 6 characters)',
    emailBtn: 'Continue with email',
    orDivider: 'or',
    authWeak: 'Enter a valid email and a password of at least 6 characters.',
    authCheckEmail: 'Account created \u2014 check your email to confirm, then sign in.',
    authError: 'Sign-in failed \u2014 please try again.',
    upgradeTitle: 'Out of tokens',
    upgradeSub: "You've used all your free tokens for this month.",
    upgradeFeatures: ['30 tokens per month', 'Priority processing', 'All features included'],
    upgradeBtn: 'Upgrade — $2.99 / month',
    upgradeFree: 'Free plan: 3 tokens per month',
    signIn: 'Sign in',
    signOut: 'Sign out',
    tokensLeft: 'tokens',
    manageBtn: 'Manage / cancel subscription',
    loginTitleSignup: 'Create your free account',
    loginSubSignup: '3 free tokens every month, no card required',
    emailBtnSignup: 'Create free account',
    noAccount: 'New here? Create a free account',
    haveAccount: 'Already have an account? Sign in',
    wrongPassword: 'Incorrect email or password.',
    accountExists: 'An account already exists for this email. Sign in instead.',
    freeLeft: (n) => `${n} free ${n === 1 ? 'preview' : 'previews'} left`,
    freeTry: 'Try free, no sign-up',
    signInForMore: 'Free previews used. Sign up free for more.',
    // Referral
    referTitle: 'Refer & Earn',
    referSub: 'Share your link. Each person who subscribes earns you 10 free tokens — no limit.',
    referCopy: 'Copy link',
    referCopied: 'Copied!',
    referStats: (paid) => paid > 0 ? `${paid} subscriber${paid > 1 ? 's' : ''} · ${paid * 10} tokens earned` : 'No referrals yet',
  },
  ar: {
    brand: 'علّمني',
    badge: 'ذكاء اصطناعي · دراسة ذكية',
    h1a: 'حوّل الشرائح إلى',
    h1b: 'أدلة دراسة',
    sub: 'ارفع شرائح أو الصق نصاً أو أدخل رابط YouTube للحصول على أدلة دراسة.',
    dropTitle: 'أسقط ملفات PowerPoint أو PDF هنا',
    dropSub: 'أو انقر للتصفح — .pptx / .ppt / .pdf / .docx / .doc / .txt، يدعم ملفات متعددة',
    langAuto: 'اكتشاف اللغة تلقائياً',
    langEn: 'الإخراج بالإنجليزية',
    langAr: 'الإخراج بالعربية',
    privacy: 'ملفاتك تُعالَج في الذاكرة فقط — لا تُكتب على القرص ولا يراها أحد. يُمسح كل شيء تلقائياً خلال 15 دقيقة.',
    generateAll: 'توليد الكل',
    generating: 'جارٍ المعالجة…',
    download: 'تحميل PDF',
    addMore: 'إضافة المزيد',
    clearAll: 'مسح الكل',
    queued: 'في الانتظار',
    processing: 'جارٍ…',
    done: 'جاهز',
    error: 'فشل',
    pills: ['ملفات متعددة', 'تحميل منفصل', 'ذكاء اصطناعي'],
    ollamaOff: 'خدمة الذكاء الاصطناعي غير متاحة',
    ollamaOffSub: 'قد تكون الخدمة لا تزال تُشغَّل. يرجى الانتظار لحظة.',
    tabUpload: 'رفع ملف',
    tabYoutube: 'رابط YouTube',
    tabText: 'لصق نص / رابط',
    ytPlaceholder: 'https://youtube.com/watch?v=...',
    ytBtn: 'توليد من YouTube',
    textPlaceholder: 'الصق نص المقال هنا…',
    urlPlaceholder: 'https://example.com/article',
    textBtn: 'توليد من النص',
    // Auth
    loginTitle: 'سجّل الدخول للمتابعة',
    loginSub: '3 رموز مجانية شهرياً — بدون بطاقة ائتمانية',
    loginBtn: 'المتابعة عبر Google',
    emailPh: 'you@email.com',
    passwordPh: 'كلمة المرور (6 أحرف على الأقل)',
    emailBtn: 'المتابعة بالبريد',
    orDivider: 'أو',
    authWeak: 'أدخل بريداً صحيحاً وكلمة مرور من 6 أحرف على الأقل.',
    authCheckEmail: 'تم إنشاء الحساب — تحقق من بريدك للتأكيد ثم سجّل الدخول.',
    authError: 'فشل تسجيل الدخول — حاول مجدداً.',
    upgradeTitle: 'نفدت رموزك',
    upgradeSub: 'لقد استخدمت رموزك المجانية لهذا الشهر.',
    upgradeFeatures: ['30 رمزاً شهرياً', 'معالجة ذات أولوية', 'جميع الميزات متاحة'],
    upgradeBtn: 'ترقية — 2.99$ / شهر',
    upgradeFree: 'الخطة المجانية: 3 رموز شهرياً',
    signIn: 'تسجيل الدخول',
    signOut: 'تسجيل الخروج',
    tokensLeft: 'رموز متبقية',
    manageBtn: 'إدارة / إلغاء الاشتراك',
    loginTitleSignup: 'أنشئ حسابك المجاني',
    loginSubSignup: '3 رموز مجانية شهرياً، بدون بطاقة',
    emailBtnSignup: 'إنشاء حساب مجاني',
    noAccount: 'جديد هنا؟ أنشئ حساباً مجانياً',
    haveAccount: 'لديك حساب بالفعل؟ سجّل الدخول',
    wrongPassword: 'البريد أو كلمة المرور غير صحيحة.',
    accountExists: 'يوجد حساب بهذا البريد بالفعل. سجّل الدخول بدلاً من ذلك.',
    freeLeft: (n) => `${n} ${n === 1 ? 'معاينة' : 'معاينات'} مجانية متبقية`,
    freeTry: 'جرّب مجاناً، بدون تسجيل',
    signInForMore: 'انتهت المعاينات المجانية. سجّل مجاناً للمزيد.',
    // Referral
    referTitle: 'أحِل واكسب',
    referSub: 'شارك رابطك. كل شخص يشترك عبر رابطك يمنحك 10 رموز مجانية — بلا حدود.',
    referCopy: 'نسخ الرابط',
    referCopied: 'تم النسخ!',
    referStats: (paid) => paid > 0 ? `${paid} مشترك · ${paid * 10} رمز مكتسب` : 'لا إحالات بعد',
  }
}

const STATUS_COLOR = {
  queued:     { bg: 'rgba(79,142,247,0.12)', color: '#4f8ef7',  border: 'rgba(79,142,247,0.3)' },
  processing: { bg: 'rgba(251,191,36,0.12)', color: '#fbbf24',  border: 'rgba(251,191,36,0.3)' },
  done:       { bg: 'rgba(34,197,94,0.12)',  color: '#22c55e',  border: 'rgba(34,197,94,0.3)'  },
  error:      { bg: 'rgba(239,68,68,0.12)',  color: '#ef4444',  border: 'rgba(239,68,68,0.3)'  },
}

let _id = 0
const uid = () => ++_id

// ── Toast notifications ────────────────────────────────────────────────────
function ToastContainer() {
  const [toasts, setToasts] = useState([])
  useEffect(() => {
    window._addToast = (msg, type = 'success') => {
      const id = uid()
      setToasts(p => [...p, { id, msg, type }])
      setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 2500)
    }
    return () => { delete window._addToast }
  }, [])
  if (!toasts.length) return null
  return (
    <div style={{position:'fixed',bottom:'1.5rem',left:'50%',transform:'translateX(-50%)',zIndex:9999,display:'flex',flexDirection:'column',gap:'0.4rem',alignItems:'center',pointerEvents:'none'}}>
      {toasts.map(t => (
        <div key={t.id} style={{
          background: t.type==='error' ? '#ef4444' : t.type==='info' ? '#4f8ef7' : '#22c55e',
          color:'#fff',padding:'0.45rem 1.1rem',borderRadius:8,fontSize:'0.82rem',fontWeight:600,
          boxShadow:'0 4px 20px rgba(0,0,0,0.3)',whiteSpace:'nowrap',animation:'toastIn 0.18s ease'
        }}>{t.msg}</div>
      ))}
    </div>
  )
}
const toast = (msg, type) => window._addToast?.(msg, type)

// ── Escape key hook ────────────────────────────────────────────────────────
function useEscapeKey(fn) {
  useEffect(() => {
    const h = e => { if (e.key === 'Escape') fn() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [fn])
}

// ── SSE stream helper ─────────────────────────────────────────────────────────
// onError receives (message, httpStatus, rawData)
function streamSSE(url, options, onEvent, onError) {
  fetch(url, options).then(async res => {
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      onError(data.error || `Server error ${res.status}`, res.status, data)
      return
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n\n')
      buf = parts.pop()
      for (const part of parts) {
        const line = part.replace(/^data:\s*/, '').trim()
        if (!line) continue
        try { onEvent(JSON.parse(line)) } catch {}
      }
    }
    // flush leftover
    if (buf.trim()) {
      const line = buf.replace(/^data:\s*/, '').trim()
      if (line) try { onEvent(JSON.parse(line)) } catch {}
    }
  }).catch(err => onError(String(err), 0, {}))
}

// ── FlashCard Modal ────────────────────────────────────────────────────────────
function FlashCardModal({ jobId, onClose }) {
  const [cards, setCards]       = useState(null)
  const [idx, setIdx]           = useState(0)
  const [flipped, setFlipped]   = useState(false)
  const [known, setKnown]       = useState(() => {
    try { return JSON.parse(localStorage.getItem(`sr_${jobId}`) || '{}') } catch { return {} }
  })
  const [reviewMode, setReviewMode] = useState(false)
  const [roundDone, setRoundDone]   = useState(false)
  const [error, setError]           = useState(null)
  const [speaking, setSpeaking]     = useState(false)
  const [glang, setGlang]           = useState('en')
  const isAr = glang === 'ar'
  const FL = isAr ? {
    title:'بطاقات المراجعة', reviewMissed:'مراجعة الأخطاء', shuffle:'خلط', reset:'إعادة',
    known:(k,t)=>`${k}/${t} معروفة`, complete:'اكتمل', roundDone:'انتهت الجولة!',
    summary:(k,r)=>`${k} معروفة · ${r} للمراجعة`, done:'تم', reveal:'اضغط لإظهار الإجابة',
    missed:'خطأ', flip:'قلب', knowIt:'أعرفها', readAloud:'🔊 استماع', speaking:'يتحدث…',
    shortcuts:'مسافة=قلب · K=أعرف · M=خطأ', noCards:'لا توجد بطاقات.', loading:'جارٍ تحميل البطاقات…',
    reviewMissedN:(n)=>`مراجعة الأخطاء (${n})`
  } : {
    title:'Flash Cards', reviewMissed:'Review Missed', shuffle:'Shuffle', reset:'Reset',
    known:(k,t)=>`${k}/${t} known`, complete:'Complete', roundDone:'Round Complete!',
    summary:(k,r)=>`${k} known · ${r} to review`, done:'Done', reveal:'Click to reveal answer',
    missed:'Missed', flip:'Flip', knowIt:'Know it', readAloud:'🔊 Read aloud', speaking:'Speaking…',
    shortcuts:'Space=flip · K=know · M=missed', noCards:'No cards available.', loading:'Loading flash cards…',
    reviewMissedN:(n)=>`Review Missed (${n})`
  }

  useEscapeKey(onClose)

  const shuffle = () => {
    setCards(c => [...c].sort(() => Math.random() - 0.5))
    setIdx(0); setFlipped(false); setRoundDone(false)
  }

  const saveKnown = (k) => {
    localStorage.setItem(`sr_${jobId}`, JSON.stringify(k))
    setKnown(k)
  }

  useEffect(() => {
    fetch(`/api/guide/${jobId}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) { setError(d.error); return }
        setCards(d.flashcards || [])
        setGlang(d.language || 'en')
      })
      .catch(() => setError('Failed to load flashcards'))
  }, [jobId])

  const activeCards = cards ? (reviewMode
    ? cards.filter((_, i) => !known[i])
    : cards) : []

  const currentCard = activeCards[idx]
  const knownCount  = cards ? cards.filter((_, i) => known[i]).length : 0

  const speak = (text) => {
    if (!window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.onend = () => setSpeaking(false)
    setSpeaking(true)
    window.speechSynthesis.speak(u)
  }

  const mark = (isKnown) => {
    if (!cards) return
    const globalIdx = cards.indexOf(currentCard)
    const newKnown = { ...known, [globalIdx]: isKnown }
    saveKnown(newKnown)
    window.speechSynthesis?.cancel()
    setSpeaking(false)
    setFlipped(false)
    if (idx + 1 >= activeCards.length) {
      setRoundDone(true)
    } else {
      setIdx(idx + 1)
    }
  }

  // Keyboard shortcuts: Space=flip, K/←=Know, M/→=Missed
  // (declared after currentCard/mark to avoid a temporal-dead-zone crash)
  useEffect(() => {
    if (!cards || roundDone) return
    const h = (e) => {
      if (e.key === ' ') { e.preventDefault(); setFlipped(f => !f); return }
      if (!currentCard) return
      if (e.key === 'k' || e.key === 'K' || e.key === 'ArrowLeft') { if (flipped) mark(true) }
      if (e.key === 'm' || e.key === 'M' || e.key === 'ArrowRight') { if (flipped) mark(false) }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cards, roundDone, currentCard, flipped])

  const resetReview = () => {
    setIdx(0)
    setFlipped(false)
    setRoundDone(false)
    setReviewMode(true)
  }

  const resetAll = () => {
    saveKnown({})
    setIdx(0)
    setFlipped(false)
    setRoundDone(false)
    setReviewMode(false)
  }

  if (!cards) return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{direction:isAr?'rtl':'ltr'}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)'}}>{FL.title}</span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'2rem',textAlign:'center',color:'var(--text-secondary)'}}>
          {error ? <><AlertCircle size={20} style={{marginBottom:8,color:'#ef4444'}}/><div style={{color:'#ef4444'}}>{error}</div></> : <><Loader2 size={20} className="spin" style={{marginBottom:8}}/><div style={{fontSize:'0.82rem'}}>{FL.loading}</div></>}
        </div>
      </div>
    </div>
  )

  const progressPct = cards.length ? (knownCount / cards.length * 100) : 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{maxWidth:560,direction:isAr?'rtl':'ltr'}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <Brain size={15} /> {FL.title}
            {reviewMode && <span style={{fontSize:'0.75rem',color:'#fbbf24',fontWeight:500}}> — {FL.reviewMissed}</span>}
          </span>
          <div style={{display:'flex',gap:'0.4rem',alignItems:'center'}}>
            <button className="ctrl-btn" style={{fontSize:'0.75rem'}} onClick={shuffle} title={FL.shuffle}>
              <RotateCcw size={12} /> {FL.shuffle}
            </button>
            <button className="ctrl-btn" style={{fontSize:'0.75rem'}} onClick={resetAll}>{FL.reset}</button>
            <button className="modal-close" onClick={onClose}><X size={16} /></button>
          </div>
        </div>

        {/* Progress bar */}
        <div style={{padding:'0.75rem 1.25rem 0'}}>
          <div style={{display:'flex',justifyContent:'space-between',fontSize:'0.75rem',color:'var(--text-muted)',marginBottom:4}}>
            <span>{FL.known(knownCount, cards.length)}</span>
            <span>{activeCards.length > 0 ? `${idx+1}/${activeCards.length}` : FL.complete}</span>
          </div>
          <div className="progress-track">
            <div className="progress-bar" style={{width:`${progressPct}%`}} />
          </div>
        </div>

        <div style={{padding:'1rem 1.25rem',flex:1,overflowY:'auto'}}>
          {roundDone ? (
            <div style={{textAlign:'center',padding:'1.5rem 0'}}>
              <CheckCircle2 size={40} color="#22c55e" style={{marginBottom:12}} />
              <div style={{fontSize:'1.1rem',fontWeight:700,color:'var(--text-primary)',marginBottom:8}}>
                {FL.roundDone}
              </div>
              <div style={{fontSize:'0.88rem',color:'var(--text-secondary)',marginBottom:20}}>
                {FL.summary(knownCount, cards.length - knownCount)}
              </div>
              <div style={{display:'flex',gap:'0.75rem',justifyContent:'center',flexWrap:'wrap'}}>
                {cards.length - knownCount > 0 && (
                  <button className="submit-btn" style={{flex:'none',padding:'0.6rem 1.2rem'}} onClick={resetReview}>
                    <RotateCcw size={14} /> {FL.reviewMissedN(cards.length - knownCount)}
                  </button>
                )}
                <button className="ctrl-btn" onClick={onClose}>{FL.done}</button>
              </div>
            </div>
          ) : currentCard ? (
            <>
              <div className={`fc-card${flipped ? ' flipped' : ''}`} onClick={() => setFlipped(f => !f)} style={{marginBottom:'1rem'}}>
                <div className="fc-card-inner">
                  <div className="fc-front">
                    <div style={{fontSize:'0.97rem',fontWeight:600,textAlign:'center'}}>{currentCard.q}</div>
                    <div style={{fontSize:'0.75rem',color:'rgba(255,255,255,0.5)',marginTop:'0.75rem',textAlign:'center'}}>{FL.reveal}</div>
                  </div>
                  <div className="fc-back">
                    <div style={{fontSize:'0.92rem',lineHeight:1.6}}>{currentCard.a}</div>
                    <button onClick={e => { e.stopPropagation(); navigator.clipboard.writeText(currentCard.a); toast('Copied!') }}
                      style={{position:'absolute',top:8,right:8,background:'none',border:'none',cursor:'pointer',color:'var(--text-muted)',padding:4,borderRadius:5,opacity:0.7}}>
                      <Copy size={12} />
                    </button>
                  </div>
                </div>
              </div>
              <div style={{display:'flex',gap:'0.5rem',marginBottom:'0.75rem'}}>
                <button className="quiz-action-btn wrong" style={{flex:1}} onClick={() => mark(false)}>
                  <ThumbsDown size={14} /> {FL.missed}
                </button>
                <button className="quiz-action-btn" style={{flex:1}} onClick={() => setFlipped(f => !f)}>
                  {FL.flip}
                </button>
                <button className="quiz-action-btn correct" style={{flex:1}} onClick={() => mark(true)}>
                  <ThumbsUp size={14} /> {FL.knowIt}
                </button>
              </div>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:'0.5rem'}}>
                <button className="ctrl-btn" style={{fontSize:'0.78rem'}}
                  onClick={() => speak(flipped ? currentCard.a : currentCard.q)}>
                  {speaking ? <><Loader2 size={12} className="spin" /> {FL.speaking}</> : FL.readAloud}
                </button>
                <span style={{fontSize:'0.68rem',color:'var(--text-muted)',fontStyle:'italic'}}>
                  {FL.shortcuts}
                </span>
              </div>
            </>
          ) : (
            <div style={{textAlign:'center',color:'var(--text-muted)',padding:'2rem'}}>{FL.noCards}</div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Quiz Modal ────────────────────────────────────────────────────────────────
function QuizModal({ jobId, filename, onClose }) {
  const [mcqs, setMcqs]       = useState(null)
  const [idx, setIdx]         = useState(0)
  const [score, setScore]     = useState(0)
  const [answered, setAnswered] = useState(false)
  const [selected, setSelected] = useState(null)
  const [done, setDone]       = useState(false)
  const [error, setError]     = useState(null)
  const [wrongs, setWrongs]   = useState([])
  const [glang, setGlang]     = useState('en')
  const isAr = glang === 'ar'
  const QL = isAr ? {
    title:'اختبار', loading:'جارٍ تحميل الاختبار…', perfect:'🎉 درجة كاملة!', complete:'انتهى الاختبار!',
    toReview:(n)=>`${n} ${n===1?'سؤال':'أسئلة'} للمراجعة`, reviewMissed:'مراجعة الأخطاء',
    restart:'إعادة', done:'تم', questionOf:(i,n)=>`سؤال ${i} من ${n}`, finish:'إنهاء', next:'التالي ←', noQ:'لا توجد أسئلة.'
  } : {
    title:'Quiz', loading:'Loading quiz…', perfect:'🎉 Perfect score!', complete:'Quiz complete!',
    toReview:(n)=>`${n} question${n>1?'s':''} to review`, reviewMissed:'Review Missed',
    restart:'Restart', done:'Done', questionOf:(i,n)=>`Question ${i} of ${n}`, finish:'Finish', next:'Next →', noQ:'No questions available.'
  }

  useEscapeKey(onClose)

  useEffect(() => {
    fetch(`/api/guide/${jobId}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) { setError(d.error); return }
        setMcqs(d.mcqs || [])
        setGlang(d.language || 'en')
      })
      .catch(() => setError('Failed to load quiz'))
  }, [jobId])

  const pick = (letter) => {
    if (answered) return
    setAnswered(true)
    setSelected(letter)
    if (letter === mcqs[idx].answer) {
      setScore(s => s + 1)
    } else {
      setWrongs(w => [...w, { q: mcqs[idx].q, answer: mcqs[idx].answer, selected: letter, options: mcqs[idx].options }])
    }
  }

  const next = () => {
    if (idx + 1 >= mcqs.length) {
      try {
        const hist = JSON.parse(localStorage.getItem('quizHistory') || '[]')
        hist.unshift({ jobId, filename: filename || 'Quiz', score, total: mcqs.length, date: new Date().toLocaleDateString() })
        localStorage.setItem('quizHistory', JSON.stringify(hist.slice(0, 50)))
      } catch {}
      setDone(true)
    } else {
      setIdx(i => i + 1)
      setAnswered(false)
      setSelected(null)
    }
  }

  const restart = () => {
    setIdx(0); setScore(0); setAnswered(false)
    setSelected(null); setDone(false); setWrongs([])
  }

  if (!mcqs) return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{direction:isAr?'rtl':'ltr'}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)'}}>{QL.title}</span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'2rem',textAlign:'center',color:'var(--text-secondary)'}}>
          {error ? <div style={{color:'#ef4444'}}>{error}</div> : <><Loader2 size={20} className="spin" style={{marginBottom:8}}/><div style={{fontSize:'0.82rem'}}>{QL.loading}</div></>}
        </div>
      </div>
    </div>
  )

  const q = mcqs[idx]
  const pct = mcqs.length ? (idx / mcqs.length * 100) : 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{maxWidth:560,direction:isAr?'rtl':'ltr'}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <ClipboardList size={15} /> {QL.title}
          </span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'1rem 1.25rem',flex:1,overflowY:'auto'}}>
          {done ? (() => {
            const pct = Math.round(score / mcqs.length * 100)
            const grade = pct >= 90 ? 'A' : pct >= 80 ? 'B' : pct >= 70 ? 'C' : pct >= 60 ? 'D' : 'F'
            const gradeColor = pct >= 80 ? '#22c55e' : pct >= 60 ? '#fbbf24' : '#ef4444'
            return (
            <div style={{padding:'0.5rem 0'}}>
              <div style={{textAlign:'center',marginBottom:'1.25rem'}}>
                <div style={{display:'flex',alignItems:'baseline',justifyContent:'center',gap:'0.75rem',marginBottom:'0.4rem'}}>
                  <div className="quiz-score-display" style={{fontSize:'2.8rem',fontWeight:800,color:'var(--accent)',lineHeight:1}}>{score}/{mcqs.length}</div>
                  <div className="quiz-grade-display" style={{fontSize:'2rem',fontWeight:800,color:gradeColor,lineHeight:1}}>{grade}</div>
                </div>
                <div style={{fontSize:'1.1rem',fontWeight:600,color:gradeColor,marginBottom:'0.3rem'}}>{pct}%</div>
                <div style={{fontSize:'0.82rem',color:'var(--text-muted)'}}>
                  {score === mcqs.length ? QL.perfect : wrongs.length === 0 ? QL.complete : QL.toReview(wrongs.length)}
                </div>
              </div>
              {wrongs.length > 0 && (
                <div style={{marginBottom:'1rem'}}>
                  <div style={{fontSize:'0.75rem',fontWeight:700,color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.05em',marginBottom:'0.5rem'}}>
                    {QL.reviewMissed}
                  </div>
                  {wrongs.map((w, i) => (
                    <div key={i} style={{
                      padding:'0.6rem 0.75rem',borderRadius:8,marginBottom:'0.4rem',
                      background:'rgba(239,68,68,0.06)',border:'1px solid rgba(239,68,68,0.15)',
                      fontSize:'0.8rem'
                    }}>
                      <div style={{color:'var(--text-primary)',fontWeight:500,marginBottom:'0.25rem'}}>{w.q}</div>
                      <div style={{color:'#22c55e',fontWeight:600}}>
                        ✓ {w.options?.find(o => o.startsWith(w.answer)) || w.answer}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div style={{display:'flex',gap:'0.5rem',justifyContent:'center'}}>
                <button className="submit-btn" style={{flex:'none',padding:'0.5rem 1.1rem',fontSize:'0.85rem'}} onClick={restart}>
                  <RotateCcw size={13} /> {QL.restart}
                </button>
                <button className="ctrl-btn" onClick={onClose}>{QL.done}</button>
              </div>
            </div>
            )
          })() : q ? (
            <>
              <div className="progress-track" style={{marginBottom:'1rem'}}>
                <div className="progress-bar" style={{width:`${pct}%`}} />
              </div>
              <div style={{fontSize:'0.8rem',color:'var(--text-muted)',marginBottom:6}}>{QL.questionOf(idx+1, mcqs.length)}</div>
              <div style={{fontSize:'0.97rem',fontWeight:600,color:'var(--text-primary)',marginBottom:'1rem',lineHeight:1.5}}>{q.q}</div>
              {(q.options || []).map((opt, i) => {
                const letter = opt[0]
                let cls = 'quiz-option'
                if (answered) {
                  if (letter === q.answer) cls += ' correct'
                  else if (letter === selected) cls += ' wrong'
                }
                return (
                  <button key={i} className={cls} disabled={answered} onClick={() => pick(letter)}>
                    {opt}
                  </button>
                )
              })}
              {answered && (
                <div style={{marginTop:'0.75rem',padding:'0.75rem',borderRadius:9,background:'rgba(79,142,247,0.08)',border:'1px solid rgba(79,142,247,0.2)',fontSize:'0.84rem',color:'var(--text-secondary)'}}>
                  {q.explanation}
                </div>
              )}
              {answered && (
                <div style={{display:'flex',justifyContent:'flex-end',marginTop:'0.75rem'}}>
                  <button className="submit-btn" style={{flex:'none',padding:'0.5rem 1.2rem',fontSize:'0.85rem'}} onClick={next}>
                    {idx + 1 >= mcqs.length ? QL.finish : QL.next}
                  </button>
                </div>
              )}
            </>
          ) : (
            <div style={{textAlign:'center',color:'var(--text-muted)',padding:'2rem'}}>{QL.noQ}</div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Quiz History Modal ─────────────────────────────────────────────────────────
function HistoryModal({ onClose }) {
  const [hist, setHist] = useState(() => JSON.parse(localStorage.getItem('quizHistory') || '[]'))

  const clearAll = () => {
    localStorage.removeItem('quizHistory')
    setHist([])
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{maxWidth:480}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <History size={15} /> Quiz History
          </span>
          <div style={{display:'flex',gap:'0.4rem',alignItems:'center'}}>
            {hist.length > 0 && (
              <button className="ctrl-btn" style={{fontSize:'0.73rem',color:'#ef4444',borderColor:'rgba(239,68,68,0.3)'}} onClick={clearAll}>
                Clear
              </button>
            )}
            <button className="modal-close" onClick={onClose}><X size={16} /></button>
          </div>
        </div>
        <div style={{padding:'1rem 1.25rem',flex:1,overflowY:'auto',maxHeight:420}}>
          {hist.length === 0 ? (
            <div style={{textAlign:'center',color:'var(--text-muted)',padding:'2rem'}}>No quiz results yet.</div>
          ) : hist.map((h, i) => {
            const pct   = Math.round(h.score / h.total * 100)
            const grade = pct >= 90 ? 'A' : pct >= 80 ? 'B' : pct >= 70 ? 'C' : pct >= 60 ? 'D' : 'F'
            const col   = pct >= 70 ? '#22c55e' : pct >= 50 ? '#fbbf24' : '#ef4444'
            return (
              <div key={i} style={{
                display:'flex',alignItems:'center',justifyContent:'space-between',
                padding:'0.7rem 0',
                borderBottom: i < hist.length - 1 ? '1px solid var(--glass-border)' : 'none'
              }}>
                <div style={{flex:1,minWidth:0}}>
                  <div style={{fontSize:'0.87rem',fontWeight:500,color:'var(--text-primary)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{h.filename}</div>
                  <div style={{fontSize:'0.73rem',color:'var(--text-muted)',marginTop:2}}>{h.date}</div>
                </div>
                <div style={{display:'flex',alignItems:'center',gap:'0.6rem',flexShrink:0}}>
                  <div style={{fontSize:'0.8rem',color:'var(--text-muted)'}}>{h.score}/{h.total}</div>
                  <div style={{
                    fontWeight:700,fontSize:'0.97rem',color:col,
                    minWidth:28,textAlign:'right'
                  }}>
                    {grade}
                    <div style={{fontSize:'0.68rem',fontWeight:500,color:col,textAlign:'center'}}>{pct}%</div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Overview Modal ─────────────────────────────────────────────────────────────
function OverviewModal({ jobId, onClose }) {
  const [guide, setGuide]         = useState(null)
  const [error, setError]         = useState(null)
  const [openSections, setOpen]   = useState({})

  useEscapeKey(onClose)

  useEffect(() => {
    fetch(`/api/guide/${jobId}`)
      .then(r => r.json())
      .then(d => { if (d.error) { setError(d.error); return } setGuide(d) })
      .catch(() => setError('Failed to load guide'))
  }, [jobId])

  const toggle = (i) => setOpen(s => ({ ...s, [i]: !s[i] }))

  const isAr = guide?.language === 'ar'
  const GL = isAr ? {
    overview:'نظرة عامة', title:'دليل الدراسة', objectives:'الأهداف التعليمية',
    sections:'الأقسام', keywords:'المصطلحات',
    summary:(s,k,f)=>`${s} أقسام · ${k} مصطلحاً · ${f} بطاقة`,
    points:(n)=>`${n} نقطة`, section:(i)=>`القسم ${i}`
  } : {
    overview:'Overview', title:'Study Guide', objectives:'Learning Objectives',
    sections:'Sections', keywords:'Keywords',
    summary:(s,k,f)=>`${s} sections · ${k} keywords · ${f} flash cards`,
    points:(n)=>`${n} point${n!==1?'s':''}`, section:(i)=>`Section ${i}`
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{maxWidth:660,maxHeight:'90vh',direction:isAr?'rtl':'ltr'}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <Map size={15} /> {GL.overview}
          </span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'1.25rem',flex:1,overflowY:'auto'}}>
          {!guide ? (
            <div style={{textAlign:'center',padding:'2rem'}}>
              {error ? <div style={{color:'#ef4444'}}>{error}</div> : <Loader2 size={20} className="spin" />}
            </div>
          ) : (
            <div>
              {/* Title */}
              <div style={{textAlign:'center',marginBottom:'1.5rem'}}>
                <div style={{
                  display:'inline-block',padding:'0.65rem 1.5rem',
                  background:'linear-gradient(135deg,var(--navy-600),var(--navy-400))',
                  color:'#fff',borderRadius:14,fontWeight:700,fontSize:'1.05rem',
                  boxShadow:'0 4px 18px var(--accent-glow)'
                }}>
                  {guide.title || GL.title}
                </div>
                <div style={{marginTop:'0.6rem',fontSize:'0.75rem',color:'var(--text-muted)'}}>
                  {GL.summary((guide.sections||[]).length, (guide.keywords||[]).length, (guide.flashcards||[]).length)}
                </div>
              </div>

              {/* Objectives */}
              {(guide.objectives||[]).length > 0 && (
                <div style={{
                  padding:'0.85rem 1rem',borderRadius:10,marginBottom:'1.1rem',
                  background:'rgba(34,197,94,0.06)',border:'1px solid rgba(34,197,94,0.2)',
                }}>
                  <div style={{fontSize:'0.72rem',fontWeight:700,color:'#22c55e',textTransform:'uppercase',letterSpacing:'0.06em',marginBottom:'0.5rem'}}>
                    {GL.objectives}
                  </div>
                  {(guide.objectives||[]).map((o,i) => (
                    <div key={i} style={{fontSize:'0.84rem',color:'var(--text-secondary)',marginBottom:'0.25rem',display:'flex',gap:'0.4rem',lineHeight:1.5}}>
                      <span style={{color:'#22c55e',flexShrink:0}}>◆</span>{o}
                    </div>
                  ))}
                </div>
              )}

              {/* Sections — collapsible */}
              {(guide.sections||[]).length > 0 && (
                <div style={{marginBottom:'1.1rem'}}>
                  <div style={{fontSize:'0.72rem',fontWeight:700,color:'var(--accent)',textTransform:'uppercase',letterSpacing:'0.06em',marginBottom:'0.6rem'}}>
                    {GL.sections}
                  </div>
                  {(guide.sections||[]).map((sec,i) => {
                    const bullets = Array.isArray(sec.bullets) ? sec.bullets : []
                    const isOpen  = !!openSections[i]
                    return (
                      <div key={i} style={{borderRadius:10,marginBottom:'0.45rem',border:'1px solid var(--glass-border)',overflow:'hidden'}}>
                        <button onClick={() => toggle(i)} style={{
                          width:'100%',display:'flex',alignItems:'center',justifyContent:'space-between',
                          padding:'0.65rem 0.9rem',background:'none',border:'none',cursor:'pointer',
                          color:'var(--text-primary)',fontWeight:600,fontSize:'0.88rem',
                          fontFamily:'inherit',textAlign:'left',gap:'0.5rem'
                        }}>
                          <span style={{flex:1}}>{sec.title || GL.section(i+1)}</span>
                          <span style={{display:'flex',alignItems:'center',gap:'0.4rem',flexShrink:0}}>
                            {bullets.length > 0 && (
                              <span style={{fontSize:'0.68rem',color:'var(--text-muted)',fontWeight:400}}>
                                {GL.points(bullets.length)}
                              </span>
                            )}
                            <ChevronDown size={13} style={{color:'var(--text-muted)',transform:isOpen?'rotate(180deg)':'none',transition:'transform 0.15s'}} />
                          </span>
                        </button>
                        {isOpen && bullets.length > 0 && (
                          <div style={{padding:'0.5rem 0.9rem 0.8rem',borderTop:'1px solid var(--glass-border)'}}>
                            {bullets.map((b,j) => {
                              const text = typeof b === 'string' ? b : (b.text || b.fact || b.point || JSON.stringify(b))
                              return (
                                <div key={j} style={{
                                  fontSize:'0.82rem',color:'var(--text-secondary)',
                                  padding:'0.28rem 0',display:'flex',gap:'0.5rem',lineHeight:1.55,
                                  borderBottom: j < bullets.length-1 ? '1px solid rgba(79,142,247,0.05)' : 'none'
                                }}>
                                  <span style={{color:'var(--accent)',flexShrink:0,marginTop:'0.15rem'}}>·</span>
                                  {text}
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Keywords */}
              {(guide.keywords||[]).length > 0 && (
                <div>
                  <div style={{fontSize:'0.72rem',fontWeight:700,color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em',marginBottom:'0.55rem'}}>
                    {GL.keywords}
                  </div>
                  <div style={{display:'flex',flexWrap:'wrap',gap:'0.4rem'}}>
                    {(guide.keywords||[]).slice(0,30).map((k,i) => {
                      const term = typeof k === 'object' ? k.term : k
                      const def  = typeof k === 'object' ? k.definition : ''
                      return (
                        <span key={i} title={def||undefined} style={{
                          padding:'0.28rem 0.72rem',borderRadius:50,
                          background:'rgba(79,142,247,0.1)',border:'1px solid rgba(79,142,247,0.22)',
                          color:'var(--text-secondary)',fontSize:'0.77rem',fontWeight:500,
                          cursor: def ? 'help' : 'default'
                        }}>
                          {term}
                        </span>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Chat Modal ─────────────────────────────────────────────────────────────────
const CHAT_SUGGESTIONS = [
  'Summarize the key points',
  'What are the main topics?',
  'What should I focus on for the exam?',
  'Give me the most important definitions',
]

function ChatModal({ jobId, onClose, lang, getAuthHeaders }) {
  const [msgs, setMsgs] = useState([{ role: 'ai', text: 'Ask me anything — definitions, hints, explanations, key points.' }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const endRef = useRef()

  useEscapeKey(onClose)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  const sendMsg = async (q) => {
    if (!q || loading) return
    setMsgs(m => [...m, { role: 'user', text: q }])
    setLoading(true)
    try {
      const r = await fetch(`/api/chat/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ question: q, language: lang })
      })
      const d = await r.json()
      setMsgs(m => [...m, { role: 'ai', text: d.answer || d.error || 'No response' }])
    } catch {
      setMsgs(m => [...m, { role: 'ai', text: 'Error — could not reach server.' }])
    }
    setLoading(false)
  }

  const send = () => {
    const q = input.trim()
    if (!q) return
    setInput('')
    sendMsg(q)
  }

  const showSuggestions = msgs.length === 1 && !loading

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box chat-box" style={{maxWidth:520}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <MessageSquare size={15} /> Ask the Guide
          </span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="chat-msgs">
          {msgs.map((m, i) => (
            <div key={i} className={`chat-msg ${m.role}`}>
              <div className="chat-bubble" style={{position:'relative'}}>
                {m.text}
                {m.role === 'ai' && i > 0 && (
                  <button onClick={() => { navigator.clipboard.writeText(m.text); toast('Copied!') }}
                    style={{position:'absolute',top:4,right:4,background:'none',border:'none',cursor:'pointer',color:'var(--text-muted)',padding:3,borderRadius:4,opacity:0.6,lineHeight:1}}>
                    <Copy size={11} />
                  </button>
                )}
              </div>
            </div>
          ))}
          {showSuggestions && (
            <div style={{padding:'0.5rem 0.75rem 0.25rem',display:'flex',flexWrap:'wrap',gap:'0.35rem'}}>
              {CHAT_SUGGESTIONS.map(q => (
                <button key={q} onClick={() => sendMsg(q)} style={{
                  padding:'0.3rem 0.7rem',borderRadius:50,fontSize:'0.76rem',fontWeight:500,
                  border:'1px solid var(--glass-border)',background:'var(--glass-light)',
                  color:'var(--text-secondary)',cursor:'pointer',fontFamily:'inherit',
                  transition:'border-color 0.15s,color 0.15s'
                }}
                onMouseOver={e=>{e.currentTarget.style.borderColor='var(--accent)';e.currentTarget.style.color='var(--accent)'}}
                onMouseOut={e=>{e.currentTarget.style.borderColor='var(--glass-border)';e.currentTarget.style.color='var(--text-secondary)'}}>
                  {q}
                </button>
              ))}
            </div>
          )}
          {loading && (
            <div className="chat-msg ai">
              <div className="chat-bubble"><Loader2 size={14} className="spin" /></div>
            </div>
          )}
          <div ref={endRef} />
        </div>
        <div className="chat-input-row">
          <input
            className="chat-input"
            placeholder="Ask a question…"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && send()}
            autoFocus
          />
          <button className="submit-btn" style={{flex:'none',padding:'0.55rem 1rem',fontSize:'0.85rem'}} onClick={send} disabled={loading}>
            {loading ? <Loader2 size={14} className="spin" /> : 'Send'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── SSE Progress display ───────────────────────────────────────────────────────
function SSEProgressCard({ item, lang }) {
  const STEPS = ['extract', 'overview', 'section', 'flashcards', 'mcq', 'pdf']
  const stepIdx = STEPS.indexOf(item.step || '')
  return (
    <div style={{padding:'1rem 1.25rem'}}>
      <div style={{display:'flex',alignItems:'center',gap:'0.6rem',marginBottom:'0.85rem'}}>
        <Loader2 size={16} className="spin" color="var(--accent)" />
        <span style={{fontSize:'0.88rem',fontWeight:600,color:'var(--text-primary)'}}>
          {item.msg || 'Processing…'}
        </span>
      </div>
      <div className="progress-track" style={{marginBottom:'0.85rem'}}>
        <div className="progress-bar" style={{width:`${Math.max(8, stepIdx >= 0 ? ((stepIdx + 1) / STEPS.length * 100) : 10)}%`}} />
      </div>
      <div className="steps-list">
        {['Extracting content', 'Analysing structure', 'Building sections', 'Flash cards', 'Quiz questions', 'Building PDF'].map((label, i) => (
          <div key={i} className={`step-item${i < stepIdx ? ' done' : i === stepIdx ? ' active' : ''}`}>
            <div className="step-dot" />
            {label}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Terms & Conditions Modal ───────────────────────────────────────────────────
const TERMS_EN = `TERMS AND CONDITIONS
Alimne (علّمني) — a souc.ai product
Effective: May 2026

1. ABOUT THIS SERVICE
Alimne is an AI-powered study tool registered under the souc.ai platform. It converts PowerPoint files, PDFs, YouTube videos, and text into structured exam study guides. The service is provided for educational and personal use on a freemium subscription model.

2. SUBSCRIPTION & BILLING
• Free plan: 3 processing tokens per month. No credit card required.
• Pro plan: $2.99/month (billed via Stripe). Includes 30 tokens per month.
• Tokens reset at the start of each calendar month.
• Subscriptions can be cancelled anytime via the billing portal. No refunds for partial months.
• Payments are processed by Stripe, Inc. and are subject to Stripe's Terms of Service.

3. YOUR FILES — PRIVACY & NO STORAGE
• Files you upload are processed entirely in server memory and never written to permanent storage.
• No copy of your document is retained after processing is complete.
• Generated study guides are held in temporary server memory for up to 15 minutes so you can download them, then deleted automatically.
• We do not access, read, or review the content of your files. Your documents are your own.

4. AI-GENERATED CONTENT DISCLAIMER
• Study guides are generated by AI (Groq API / Llama & Whisper models). Output may contain inaccuracies, omissions, or errors.
• Generated content is for study assistance only. Do not rely on it as academically verified or professionally authoritative.
• We are not responsible for any decisions made based on AI-generated content.

5. ACCEPTABLE USE
You agree not to use this service to:
• Upload content that infringes third-party intellectual property rights.
• Upload illegal, harmful, abusive, or malicious content.
• Attempt to reverse-engineer, overload, or otherwise abuse the service.
• Resell or commercially redistribute the service or its outputs without permission.

6. INTELLECTUAL PROPERTY
• Your uploaded files and their content remain entirely your property.
• AI-generated study guides are provided for your personal educational use.
• The Alimne application, its interface, and underlying code are the property of souc.ai and its developers.

7. THIRD-PARTY SERVICES
This service relies on:
• souc.ai — platform registry and infrastructure provider (souc.ai).
• Groq API — for AI text generation and audio transcription (subject to Groq's own terms at groq.com).
• Stripe — for payment processing (subject to Stripe's terms at stripe.com).
• Supabase — for authentication (subject to Supabase's terms at supabase.com).
• YouTube — for video caption and audio extraction (subject to YouTube's Terms of Service).

8. LIMITATION OF LIABILITY
• The service is provided "as is", without warranties of any kind — express or implied.
• We are not liable for any direct, indirect, incidental, or consequential loss arising from use of this service.
• We do not guarantee uninterrupted uptime, accuracy of AI results, or permanent availability of the service.

9. CHANGES TO TERMS
These terms may be updated at any time without prior notice. Continued use of the service after changes constitutes your acceptance of the revised terms.

10. CONTACT
Questions or concerns: hello@souc.ai`

const TERMS_AR = `الشروط والأحكام
Alimne (علّمني) — منتج souc.ai
ساري المفعول: مايو 2026

١. عن هذه الخدمة
Alimne (علّمني) أداة دراسة مدعومة بالذكاء الاصطناعي مسجّلة تحت منصة souc.ai. تحوّل ملفات PowerPoint وPDF ومقاطع YouTube والنصوص إلى أدلة دراسة منظمة للاختبارات. تُقدَّم الخدمة للاستخدام التعليمي والشخصي وفق نموذج اشتراك مجاني مدفوع.

٢. الاشتراك والفوترة
• الخطة المجانية: 3 رموز معالجة شهرياً. لا تحتاج إلى بطاقة ائتمانية.
• الخطة الاحترافية: 2.99$ شهرياً (عبر Stripe). تشمل 30 رمزاً شهرياً.
• تُعاد الرموز في بداية كل شهر.
• يمكن إلغاء الاشتراك في أي وقت عبر بوابة الفوترة. لا يوجد استرداد للأشهر الجزئية.
• تُعالَج المدفوعات بواسطة Stripe وتخضع لشروط خدمة Stripe.

٣. ملفاتك — الخصوصية وعدم التخزين
• تُعالَج الملفات التي ترفعها في ذاكرة الخادم فقط ولا تُكتب على أي تخزين دائم.
• لا تُحتفظ بأي نسخة من مستنداتك بعد اكتمال المعالجة.
• تُحفظ أدلة الدراسة المولَّدة في ذاكرة الخادم المؤقتة لمدة 15 دقيقة للتنزيل ثم تُحذف تلقائياً.
• لا نطّلع على محتوى ملفاتك ولا نراجعها. مستنداتك ملكك وحدك.

٤. إخلاء مسؤولية المحتوى المولَّد بالذكاء الاصطناعي
• تُولَّد أدلة الدراسة بواسطة الذكاء الاصطناعي (Groq API / نماذج Llama وWhisker). قد يحتوي الناتج على أخطاء أو إغفالات.
• المحتوى المولَّد للمساعدة في الدراسة فقط. لا تعتمد عليه مرجعاً أكاديمياً أو مهنياً موثوقاً.
• لا نتحمل أي مسؤولية عن قرارات تُتخذ بناءً على المحتوى المولَّد بالذكاء الاصطناعي.

٥. الاستخدام المقبول
توافق على عدم استخدام الخدمة من أجل:
• رفع محتوى ينتهك حقوق الملكية الفكرية لأطراف أخرى.
• رفع محتوى غير قانوني أو ضار أو مسيء.
• محاولة الهندسة العكسية أو إرهاق الخدمة أو إساءة استخدامها.
• إعادة بيع الخدمة أو مخرجاتها تجارياً دون إذن.

٦. الملكية الفكرية
• ملفاتك ومحتواها تظل ملكك الكامل.
• أدلة الدراسة المولَّدة مقدَّمة لاستخدامك التعليمي الشخصي.
• تطبيق Alimne (علّمني) وواجهته وشفرته البرمجية ملك لـ souc.ai ومطوّريها.

٧. الخدمات الخارجية
تعتمد هذه الخدمة على:
• souc.ai — منصة التسجيل والبنية التحتية (souc.ai).
• Groq API — لتوليد النصوص والنسخ الصوتي بالذكاء الاصطناعي (خاضع لشروط Groq على groq.com).
• Stripe — لمعالجة المدفوعات (خاضع لشروط Stripe على stripe.com).
• Supabase — للمصادقة (خاضع لشروط Supabase على supabase.com).
• YouTube — لاستخراج التسميات التوضيحية والصوت (خاضع لشروط خدمة YouTube).

٨. تحديد المسؤولية
• تُقدَّم الخدمة كما هي دون أي ضمانات صريحة أو ضمنية.
• لا نتحمل أي مسؤولية عن أي خسائر مباشرة أو غير مباشرة أو عرضية ناجمة عن استخدام الخدمة.
• لا نضمن استمرارية التشغيل أو دقة نتائج الذكاء الاصطناعي أو التوافر الدائم للخدمة.

٩. التغييرات على الشروط
قد تُحدَّث هذه الشروط في أي وقت دون إشعار مسبق. استمرارك في استخدام الخدمة بعد أي تغيير يعني قبولك للشروط المعدَّلة.

١٠. التواصل
للأسئلة والاستفسارات: hello@souc.ai`

function TermsModal({ lang, onClose }) {
  const isAr = lang === 'ar'
  const content = isAr ? TERMS_AR : TERMS_EN
  return (
    <div className="modal-overlay" onClick={onClose} style={{alignItems:'center'}}>
      <div className="modal-box" onClick={e => e.stopPropagation()}
        style={{maxWidth:'680px', width:'94vw', maxHeight:'82vh', display:'flex', flexDirection:'column', direction: isAr ? 'rtl' : 'ltr'}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'1rem', flexShrink:0}}>
          <div style={{display:'flex', alignItems:'center', gap:'0.5rem', fontWeight:700, fontSize:'1rem', color:'var(--text-primary)'}}>
            <ScrollText size={16} color="var(--accent)" />
            {isAr ? 'الشروط والأحكام' : 'Terms & Conditions'}
          </div>
          <button onClick={onClose} style={{background:'none',border:'none',cursor:'pointer',color:'var(--text-secondary)',padding:'4px'}}>
            <X size={18} />
          </button>
        </div>
        <div style={{overflowY:'auto', flex:1, paddingRight: isAr ? 0 : '0.5rem', paddingLeft: isAr ? '0.5rem' : 0}}>
          <pre style={{
            whiteSpace:'pre-wrap', wordBreak:'break-word',
            fontSize:'0.78rem', lineHeight:1.7,
            color:'var(--text-secondary)', fontFamily:'inherit',
            textAlign: isAr ? 'right' : 'left',
          }}>{content}</pre>
        </div>
      </div>
    </div>
  )
}

// ── Login Modal ────────────────────────────────────────────────────────────────
function LoginModal({ onClose, onLogin, lang, sbClient, toast, initialMode }) {
  const t = T[lang] || T['en']
  const isAr = lang === 'ar'
  const [mode, setMode]         = useState(initialMode === 'signup' ? 'signup' : 'signin')
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy]         = useState(false)
  const isSignup = mode === 'signup'
  const emailAuth = async () => {
    const em = email.trim()
    if (!sbClient) { toast && toast(t.authError, 'error'); return }
    if (!/.+@.+\..+/.test(em) || password.length < 6) { toast && toast(t.authWeak, 'error'); return }
    setBusy(true)
    try {
      if (isSignup) {
        const { data, error } = await sbClient.auth.signUp({ email: em, password })
        if (error) {
          const m = (error.message || '').toLowerCase()
          if (m.includes('already') || m.includes('registered') || m.includes('exists')) {
            toast && toast(t.accountExists, 'error'); setMode('signin'); setBusy(false); return
          }
          throw error
        }
        if (!data.session) { toast && toast(t.authCheckEmail, 'success'); setBusy(false); return }
        onClose()
      } else {
        const { error } = await sbClient.auth.signInWithPassword({ email: em, password })
        if (error) {
          const m = (error.message || '').toLowerCase()
          toast && toast(m.includes('invalid') || m.includes('credentials') ? t.wrongPassword : (error.message || t.authError), 'error')
          setBusy(false); return
        }
        onClose()
      }
    } catch (e) {
      toast && toast((e && e.message) || t.authError, 'error')
      setBusy(false)
    }
  }
  return (
    <div className="modal-overlay" onClick={onClose} style={{alignItems:'center'}}>
      <div className="modal-box" onClick={e => e.stopPropagation()}
        style={{maxWidth:380, width:'92vw', direction: isAr ? 'rtl' : 'ltr', padding:'2rem', textAlign:'center'}}>
        <div style={{marginBottom:'1.75rem'}}>
          <div style={{
            width:52, height:52, borderRadius:16, margin:'0 auto 1rem',
            background:'linear-gradient(135deg,var(--navy-600),var(--navy-400))',
            display:'flex', alignItems:'center', justifyContent:'center',
            boxShadow:'0 4px 18px var(--accent-glow)'
          }}>
            <AlimneGlyph size={26} />
          </div>
          <div style={{fontWeight:700, fontSize:'1.15rem', color:'var(--text-primary)', marginBottom:'0.4rem'}}>
            {isSignup ? t.loginTitleSignup : t.loginTitle}
          </div>
          <div style={{fontSize:'0.82rem', color:'var(--text-muted)', lineHeight:1.55}}>
            {isSignup ? t.loginSubSignup : t.loginSub}
          </div>
        </div>
        <input
          type="email" value={email} onChange={e => setEmail(e.target.value)}
          placeholder={t.emailPh} autoComplete="email"
          style={{width:'100%', padding:'0.7rem 0.9rem', marginBottom:'0.6rem', borderRadius:10,
                  border:'1px solid var(--border, rgba(120,140,180,0.3))', background:'var(--input-bg, rgba(255,255,255,0.04))',
                  color:'var(--text-primary)', fontSize:'0.9rem', textAlign: isAr ? 'right' : 'left', direction:'ltr'}}
        />
        <input
          type="password" value={password} onChange={e => setPassword(e.target.value)}
          placeholder={t.passwordPh} autoComplete={isSignup ? 'new-password' : 'current-password'}
          onKeyDown={e => { if (e.key === 'Enter') emailAuth() }}
          style={{width:'100%', padding:'0.7rem 0.9rem', marginBottom:'0.8rem', borderRadius:10,
                  border:'1px solid var(--border, rgba(120,140,180,0.3))', background:'var(--input-bg, rgba(255,255,255,0.04))',
                  color:'var(--text-primary)', fontSize:'0.9rem', textAlign: isAr ? 'right' : 'left', direction:'ltr'}}
        />
        <button
          className="submit-btn"
          disabled={busy}
          style={{width:'100%', justifyContent:'center', padding:'0.75rem 1.25rem', fontSize:'0.9rem', marginBottom:'0.75rem', opacity: busy ? 0.7 : 1}}
          onClick={emailAuth}
        >
          {busy ? '…' : (isSignup ? t.emailBtnSignup : t.emailBtn)}
        </button>
        <button
          onClick={() => setMode(isSignup ? 'signin' : 'signup')}
          style={{background:'none', border:'none', color:'var(--accent)', fontSize:'0.8rem', cursor:'pointer', marginBottom:'1rem', padding:'0.25rem'}}
        >
          {isSignup ? t.haveAccount : t.noAccount}
        </button>
        <div style={{display:'flex', alignItems:'center', gap:'0.75rem', margin:'0 0 1rem', color:'var(--text-muted)', fontSize:'0.75rem'}}>
          <span style={{flex:1, height:1, background:'var(--border, rgba(120,140,180,0.25))'}} />
          {t.orDivider}
          <span style={{flex:1, height:1, background:'var(--border, rgba(120,140,180,0.25))'}} />
        </div>
        <button
          className="submit-btn"
          style={{width:'100%', justifyContent:'center', padding:'0.75rem 1.25rem', fontSize:'0.9rem', gap:'0.65rem'}}
          onClick={onLogin}
        >
          {/* Google logo */}
          <svg width="18" height="18" viewBox="0 0 48 48" style={{flexShrink:0}}>
            <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 2.9l5.7-5.7C34.5 6.6 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.6-.4-3.9z"/>
            <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 19 13 24 13c3.1 0 5.8 1.1 8 2.9l5.7-5.7C34.5 6.6 29.6 4 24 4 16.3 4 9.7 8.4 6.3 14.7z"/>
            <path fill="#4CAF50" d="M24 44c5.4 0 10.3-2 14-5.3l-6.5-5.5C29.6 35 26.9 36 24 36c-5.3 0-9.7-3.3-11.3-8H6.3C9.7 35.6 16.3 40 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.3 4.1-4.3 5.5l6.5 5.5C37.2 35.8 44 30.6 44 24c0-1.3-.1-2.6-.4-3.9z"/>
          </svg>
          {t.loginBtn}
        </button>
        <div style={{marginTop:'1rem', fontSize:'0.73rem', color:'var(--text-muted)'}}>
          {lang === 'ar'
            ? 'بالمتابعة، أنت توافق على شروطنا وأحكامنا'
            : 'By continuing, you agree to our Terms & Conditions'}
        </div>
      </div>
    </div>
  )
}

// ── Upgrade Modal ──────────────────────────────────────────────────────────────
function UpgradeModal({ onClose, onUpgrade, onManage, isSubscribed, lang }) {
  const t = T[lang] || T['en']
  const isAr = lang === 'ar'
  return (
    <div className="modal-overlay" onClick={onClose} style={{alignItems:'center'}}>
      <div className="modal-box" onClick={e => e.stopPropagation()}
        style={{maxWidth:400, width:'92vw', direction: isAr ? 'rtl' : 'ltr'}}>
        <div className="modal-header">
          <span style={{fontWeight:700, color:'var(--text-primary)', display:'flex', alignItems:'center', gap:'0.4rem'}}>
            <Zap size={15} color="#fbbf24" /> {t.upgradeTitle}
          </span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'1.25rem'}}>
          <div style={{
            textAlign:'center', padding:'1.5rem 1rem',
            background:'rgba(79,142,247,0.06)', borderRadius:12,
            border:'1px solid rgba(79,142,247,0.15)', marginBottom:'1.25rem'
          }}>
            <div style={{fontSize:'0.84rem', color:'var(--text-muted)', marginBottom:'0.65rem'}}>{t.upgradeSub}</div>
            <div style={{fontSize:'2.75rem', fontWeight:800, color:'var(--accent)', lineHeight:1}}>$2.99</div>
            <div style={{fontSize:'0.8rem', color:'var(--text-muted)', marginTop:'0.2rem'}}>/ month</div>
          </div>
          <div style={{marginBottom:'1.25rem'}}>
            {t.upgradeFeatures.map((f, i) => (
              <div key={i} style={{
                display:'flex', alignItems:'center', gap:'0.5rem',
                padding:'0.35rem 0', fontSize:'0.86rem', color:'var(--text-secondary)'
              }}>
                <CheckCircle2 size={14} color="#22c55e" style={{flexShrink:0}} /> {f}
              </div>
            ))}
          </div>
          {isSubscribed ? (
            <button className="submit-btn" style={{width:'100%', justifyContent:'center', padding:'0.75rem'}} onClick={onManage}>
              {t.manageBtn}
            </button>
          ) : (
            <button className="submit-btn" style={{width:'100%', justifyContent:'center', padding:'0.75rem'}} onClick={onUpgrade}>
              <Sparkles size={15} /> {t.upgradeBtn}
            </button>
          )}
          <div style={{textAlign:'center', marginTop:'0.75rem', fontSize:'0.75rem', color:'var(--text-muted)'}}>
            {t.upgradeFree}
          </div>
        </div>
      </div>
    </div>
  )
}


// ── Main App ───────────────────────────────────────────────────────────────────
export default function App() {
  const [theme, setTheme]   = useState('dark')
  const [lang, setLang]     = useState('auto')
  const [queue, setQueue]   = useState([])
  const [drag, setDrag]     = useState(false)
  const [running, setRunning] = useState(false)

  const [inputTab, setInputTab] = useState('upload')
  const [ytUrl, setYtUrl]     = useState('')
  const [pasteText, setPasteText] = useState('')
  const [pasteUrl, setPasteUrl]   = useState('')

  // Modals
  const [detail, setDetail] = useState('standard')
  const [summaryOnly, setSummaryOnly] = useState(false)

  // Modals
  const [flashModal, setFlashModal] = useState(null)
  const [quizModal, setQuizModal]   = useState(null)
  const [chatModal, setChatModal]   = useState(null)
  const [mindmapModal, setMindmapModal] = useState(null)
  const [showHistory, setShowHistory]   = useState(false)
  const [showTerms, setShowTerms]       = useState(false)

  // Auth
  const [session, setSession]         = useState(null)
  const [userInfo, setUserInfo]       = useState(null)
  const [sbClient, setSbClient]       = useState(null)
  const [authEnabled, setAuthEnabled] = useState(false)
  const [showLogin, setShowLogin]     = useState(false)
  const [loginMode, setLoginMode]     = useState('signin')
  const [showUpgrade, setShowUpgrade] = useState(false)
  const [authLoading, setAuthLoading] = useState(true)
  const [anonInfo, setAnonInfo]       = useState(null)  // {limit, remaining} for signed-out users

  const openLogin = (mode = 'signin') => { setLoginMode(mode); setShowLogin(true) }

  // Referral
  const [refStats, setRefStats]     = useState(null)
  const [copied, setCopied]         = useState(false)

  const inputRef = useRef()
  const t = T[lang] || T['en']

  const quizHistory = (() => { try { return JSON.parse(localStorage.getItem('quizHistory') || '[]') } catch { return [] } })()

  // ── Capture referral code from URL ────────────────────────────────────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const ref = params.get('ref')
    if (ref) {
      localStorage.setItem('alimne_ref', ref.toUpperCase())
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])


  // ── Supabase init + auth ────────────────────────────────────────────────────
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(cfg => {
        setAuthEnabled(!!cfg.auth_enabled)
        if (cfg.anon_free_limit !== undefined)
          setAnonInfo({ limit: cfg.anon_free_limit, remaining: cfg.anon_remaining ?? cfg.anon_free_limit })
        if (!cfg.auth_enabled || !cfg.supabase_url || !cfg.supabase_anon_key) {
          setAuthLoading(false)
          return
        }
        const sb = createClient(cfg.supabase_url, cfg.supabase_anon_key)
        setSbClient(sb)
        sb.auth.getSession().then(({ data }) => {
          setSession(data.session)
          setAuthLoading(false)
          if (data.session) {
            _fetchUserInfo(data.session.access_token)
            _fetchRefStats(data.session.access_token)
          }
        })
        const { data: { subscription } } = sb.auth.onAuthStateChange((_event, sess) => {
          setSession(sess)
          if (sess) {
            _fetchUserInfo(sess.access_token)
            _fetchRefStats(sess.access_token)
            // Apply stored referral code (only fires once, code removed after)
            const storedRef = localStorage.getItem('alimne_ref')
            if (storedRef) {
              fetch('/api/referral/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sess.access_token}` },
                body: JSON.stringify({ code: storedRef })
              }).then(() => localStorage.removeItem('alimne_ref')).catch(() => {})
            }
          } else {
            setUserInfo(null)
            setRefStats(null)
          }
        })
        return () => subscription.unsubscribe()
      })
      .catch(() => setAuthLoading(false))
  }, [])

  const _fetchUserInfo = (token) => {
    fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(d => { if (!d.error) setUserInfo(d) })
      .catch(() => {})
  }

  const _fetchRefStats = (token) => {
    fetch('/api/referral/stats', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(d => setRefStats(d))
      .catch(() => {})
  }

  const copyReferral = (code) => {
    const link = `${window.location.origin}?ref=${code}`
    navigator.clipboard.writeText(link).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => {})
  }

  const getAuthHeaders = () =>
    session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}

  const signIn = () => {
    if (!sbClient) return
    sbClient.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin }
    })
  }

  const signOut = () => {
    sbClient?.auth.signOut()
    setSession(null)
    setUserInfo(null)
  }

  const handleCheckout = () => {
    fetch('/api/stripe/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({})
    })
      .then(r => r.json())
      .then(d => { if (d.url) window.location.href = d.url; else throw new Error(d.error || 'No URL') })
      .catch(e => toast(`Payment error — ${e.message || 'please try again'}`, 'error'))
  }

  const handleManageBilling = () => {
    fetch('/api/stripe/portal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({})
    })
      .then(r => r.json())
      .then(d => { if (d.url) window.location.href = d.url; else throw new Error(d.error || 'No URL') })
      .catch(e => toast(`Billing error — ${e.message || 'please try again'}`, 'error'))
  }

  // handle 401/402 from any SSE stream
  const handleAuthError = (status, item, resolve, data) => {
    const code = data?.code
    if (status === 401 || code === 'auth_required') {
      openLogin('signin')
      if (item) updateItem(item.id, { status: 'error', error: t.signInForMore })
      if (resolve) resolve()
      return true
    }
    if (status === 402) {
      // Anonymous visitor out of free previews → invite sign-up (free tokens).
      // Signed-in user out of tokens → show the upgrade / subscribe modal.
      if (code === 'signin_for_more') {
        openLogin('signup')
        if (item) updateItem(item.id, { status: 'error', error: t.signInForMore })
      } else {
        setShowUpgrade(true)
        if (item) updateItem(item.id, { status: 'error', error: 'No tokens remaining. Upgrade to continue.' })
      }
      if (resolve) resolve()
      return true
    }
    return false
  }

  const addFiles = useCallback(fileList => {
    const valid = Array.from(fileList).filter(f => f.name.match(/\.(pptx?|pdf|docx?|txt)$/i))
    if (!valid.length) return
    setQueue(prev => {
      const merged = [
        ...prev,
        ...valid.map(f => ({ id: uid(), file: f, name: f.name, status: 'queued', jobId: null, error: null, step: null, msg: null }))
      ]
      if (merged.length > 3) toast('You can process up to 3 files at a time.', 'error')
      return merged.slice(0, 3)
    })
  }, [])

  const onDrop = e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }
  const onDragOver = e => { e.preventDefault(); setDrag(true) }
  const onDragLeave = () => setDrag(false)

  const removeItem = id => setQueue(prev => prev.filter(i => i.id !== id))
  const clearAll   = () => setQueue([])

  const updateItem = (id, patch) =>
    setQueue(prev => prev.map(i => i.id === id ? { ...i, ...patch } : i))

  // ── File processing with SSE ───────────────────────────────────────────────
  const processAll = async () => {
    const pending = queue.filter(i => i.status === 'queued' || i.status === 'error')
    if (!pending.length) return
    setRunning(true)

    for (const item of pending) {
      updateItem(item.id, { status: 'processing', error: null, step: 'extract', msg: 'Starting…' })
      await new Promise(resolve => {
        const fd = new FormData()
        fd.append('file', item.file)
        fd.append('language', lang)
        fd.append('detail', detail)
        fd.append('mode', summaryOnly ? 'summary' : 'full')
        streamSSE(
          '/api/summarize-stream',
          { method: 'POST', body: fd, headers: getAuthHeaders() },
          (ev) => {
            if (ev.language && lang === 'auto') setLang(ev.language)
            if (ev.error) { updateItem(item.id, { status: 'error', error: ev.error }); resolve(); return }
            if (ev.step === 'done') {
              updateItem(item.id, { status: 'done', jobId: ev.job_id, step: 'done', msg: 'Ready' })
              if (ev.tokens_remaining !== undefined && userInfo)
                setUserInfo(u => ({ ...u, tokens_remaining: ev.tokens_remaining }))
              resolve()
            } else {
              updateItem(item.id, { step: ev.step, msg: ev.msg })
            }
          },
          (err, status, data) => {
            if (!handleAuthError(status, item, resolve, data))
              { updateItem(item.id, { status: 'error', error: err }); resolve() }
          }
        )
      })
    }
    setRunning(false)
  }

  // ── YouTube SSE ────────────────────────────────────────────────────────────
  const processYoutube = () => {
    const url = ytUrl.trim()
    if (!url || running) return
    setRunning(true)
    const qitem = { id: uid(), file: null, name: url, status: 'processing', jobId: null, error: null, step: 'extract', msg: 'Fetching transcript…' }
    setQueue(prev => [...prev, qitem])
    setInputTab('upload')

    streamSSE(
      '/api/youtube',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ url, language: lang, detail, mode: summaryOnly ? 'summary' : 'full' })
      },
      (ev) => {
        if (ev.language && lang === 'auto') setLang(ev.language)
        if (ev.error) { updateItem(qitem.id, { status: 'error', error: ev.error }); setRunning(false); return }
        if (ev.step === 'done') {
          updateItem(qitem.id, { status: 'done', jobId: ev.job_id, step: 'done', msg: 'Ready' })
          if (ev.tokens_remaining !== undefined && userInfo)
            setUserInfo(u => ({ ...u, tokens_remaining: ev.tokens_remaining }))
          else if (ev.tokens_remaining !== undefined && !session)
            setAnonInfo(a => a ? { ...a, remaining: ev.tokens_remaining } : a)
          setRunning(false)
        } else {
          updateItem(qitem.id, { step: ev.step, msg: ev.msg })
        }
      },
      (err, status, data) => {
        setRunning(false)
        if (!handleAuthError(status, qitem, null, data))
          updateItem(qitem.id, { status: 'error', error: err })
      }
    )
    setYtUrl('')
  }

  // ── Paste text / URL SSE ───────────────────────────────────────────────────
  const processText = () => {
    const text = pasteText.trim()
    const url  = pasteUrl.trim()
    if ((!text && !url) || running) return
    setRunning(true)
    const name = url ? url.replace(/^https?:\/\//, '').slice(0, 40) : 'Pasted text'
    const qitem = { id: uid(), file: null, name, status: 'processing', jobId: null, error: null, step: 'extract', msg: 'Processing text…' }
    setQueue(prev => [...prev, qitem])
    setInputTab('upload')

    streamSSE(
      '/api/summarize-text',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ text, url, language: lang, filename: name, detail, mode: summaryOnly ? 'summary' : 'full' })
      },
      (ev) => {
        if (ev.error) { updateItem(qitem.id, { status: 'error', error: ev.error }); setRunning(false); return }
        if (ev.step === 'done') {
          updateItem(qitem.id, { status: 'done', jobId: ev.job_id, step: 'done', msg: 'Ready' })
          if (ev.tokens_remaining !== undefined && userInfo)
            setUserInfo(u => ({ ...u, tokens_remaining: ev.tokens_remaining }))
          else if (ev.tokens_remaining !== undefined && !session)
            setAnonInfo(a => a ? { ...a, remaining: ev.tokens_remaining } : a)
          setRunning(false)
        } else {
          updateItem(qitem.id, { step: ev.step, msg: ev.msg })
        }
      },
      (err, status, data) => {
        setRunning(false)
        if (!handleAuthError(status, qitem, null, data))
          updateItem(qitem.id, { status: 'error', error: err })
      }
    )
    setPasteText('')
    setPasteUrl('')
  }

  const downloadPDF = (item) => {
    if (!item.jobId) return
    const a = document.createElement('a')
    a.href = `/api/download/${item.jobId}`
    a.download = item.name.replace(/\.(pptx?|pdf)$/i, '') + '_study_guide.pdf'
    a.click()
    toast('PDF downloading…', 'info')
  }

  const downloadAnki = (item) => {
    if (!item.jobId) return
    const a = document.createElement('a')
    a.href = `/api/export/anki/${item.jobId}`
    a.click()
    toast('Anki CSV downloading…', 'info')
  }

  const deleteNow = (item) => {
    if (!item.jobId) return
    fetch(`/api/delete/${item.jobId}`, { method: 'POST', headers: getAuthHeaders() })
      .then(() => {
        setQueue(prev => prev.filter(q => q.id !== item.id))
        toast('Your data was deleted from the server.', 'success')
      })
      .catch(() => toast('Could not delete — it is auto-wiped within 15 minutes.', 'error'))
  }

  const openPrint = (item) => {
    if (!item.jobId) return
    window.open(`/api/view/md/${item.jobId}`, '_blank')
  }

  const doneCount    = queue.filter(i => i.status === 'done').length
  const pendingCount = queue.filter(i => i.status === 'queued' || i.status === 'error').length
  const hasQueue     = queue.length > 0
  const hasHistory   = quizHistory.length > 0
  const isSubscribed = userInfo?.subscription_status === 'active'

  return (
    <div data-theme={theme} dir={lang === 'ar' ? 'rtl' : 'ltr'}>
      <ToastContainer />
      <div className="bg-orb orb-1" />
      <div className="bg-orb orb-2" />
      <div className="bg-orb orb-3" />
      <div className="bg-orb orb-4" />
      <div className="bg-mesh" />
      <div className="app-wrap">

        {/* ── Nav ── */}
        <nav className="nav">
          <div className="container">
            <div className="nav-inner">
              <div className="nav-brand">
                <div className="brand-icon"><AlimneGlyph size={18} /></div>
                <div style={{display:'flex',flexDirection:'column',gap:'1px',lineHeight:1}}>
                  <span className="brand-name">{t.brand}</span>
                  <span style={{fontSize:'0.62rem',color:'var(--text-muted)',letterSpacing:'0.02em',fontWeight:400}}>
                    by <a href="https://souc.ai" target="_blank" rel="noopener noreferrer"
                      style={{color:'var(--accent)',textDecoration:'none',fontWeight:500}}>souc.ai</a>
                  </span>
                </div>
              </div>
              <div className="nav-controls">
                {hasHistory && (
                  <button className="ctrl-btn" onClick={() => setShowHistory(true)}>
                    <History size={13} /><span className="ctrl-label"> Scores</span>
                  </button>
                )}

                {/* Auth controls */}
                {authEnabled && !authLoading && (
                  session ? (
                    <>
                      {/* Token counter */}
                      {(() => {
                        const rem  = userInfo?.tokens_remaining ?? null
                        const low  = rem !== null && rem <= 1 && !isSubscribed
                        const dead = rem !== null && rem <= 0
                        return (
                          <button
                            className="ctrl-btn"
                            style={{
                              cursor: 'pointer',
                              borderColor: dead ? 'rgba(239,68,68,0.4)' : low ? 'rgba(251,191,36,0.5)' : 'rgba(34,197,94,0.3)',
                              color: dead ? '#ef4444' : low ? '#fbbf24' : '#22c55e',
                              animation: low && !dead ? 'tokenPulse 2s ease infinite' : 'none',
                            }}
                            onClick={() => setShowUpgrade(true)}
                            title={rem === null ? 'Tokens' : `${rem} token${rem === 1 ? '' : 's'} remaining · ${isSubscribed ? 'Pro' : 'Free'} plan`}
                          >
                            <Zap size={12} />
                            <span className="ctrl-label">
                              {' '}{rem ?? '…'} {isSubscribed ? 'Pro' : 'Free'}
                            </span>
                          </button>
                        )
                      })()}
                      {/* User avatar / sign out */}
                      <button className="ctrl-btn" onClick={signOut}
                        title={`${userInfo?.name || userInfo?.email || ''} — ${t.signOut}`}>
                        {userInfo?.avatar_url
                          ? <img src={userInfo.avatar_url} alt="" style={{width:18,height:18,borderRadius:'50%',objectFit:'cover'}} />
                          : <User size={13} />}
                        {userInfo?.name && <span className="ctrl-label"> {String(userInfo.name).split(' ')[0]}</span>}
                      </button>
                    </>
                  ) : (
                    <>
                      {/* Anonymous free-preview counter */}
                      {anonInfo && anonInfo.limit > 0 && (
                        <button
                          className="ctrl-btn"
                          style={{
                            cursor:'pointer',
                            borderColor: anonInfo.remaining > 0 ? 'rgba(34,197,94,0.3)' : 'rgba(251,191,36,0.5)',
                            color: anonInfo.remaining > 0 ? '#22c55e' : '#fbbf24',
                          }}
                          onClick={() => openLogin('signup')}
                          title={anonInfo.remaining > 0 ? t.freeLeft(anonInfo.remaining) : t.signInForMore}
                        >
                          <Zap size={12} />
                          <span className="ctrl-label"> {anonInfo.remaining > 0 ? t.freeLeft(anonInfo.remaining) : t.signInForMore}</span>
                        </button>
                      )}
                      <button
                        className="ctrl-btn"
                        style={{borderColor:'var(--accent)',color:'var(--accent)'}}
                        onClick={() => openLogin('signin')}
                      >
                        <LogIn size={13} /><span className="ctrl-label"> {t.signIn}</span>
                      </button>
                    </>
                  )
                )}

                <button className="ctrl-btn" onClick={() => setLang(p => p === 'en' ? 'ar' : p === 'ar' ? 'auto' : 'en')}>
                  <Globe size={13} /><span className="ctrl-label">{lang === 'ar' ? ' EN' : lang === 'auto' ? ' عربي' : ' عربي'}</span>
                </button>
                <button className="ctrl-btn" onClick={() => setTheme(p => p === 'dark' ? 'light' : 'dark')}>
                  {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
                </button>
              </div>
            </div>
          </div>
        </nav>

        <main className="main">
          <div className="container">

            {/* Hero */}
            <div className="hero">
              <div className="hero-badge"><Sparkles size={12} />{t.badge}</div>
              <h1>{t.h1a} <span>{t.h1b}</span></h1>
              <p>{t.sub}</p>
            </div>

            {/* Input mode tabs + card */}
            <div className="glass upload-card">
              {/* Tabs */}
              <div style={{display:'flex',gap:'0.4rem',marginBottom:'1.1rem'}}>
                {[
                  { key: 'upload',  icon: <Upload size={13} />,  label: t.tabUpload  },
                  { key: 'youtube', icon: <Youtube size={13} />, label: t.tabYoutube },
                  { key: 'text',    icon: <Type size={13} />,    label: t.tabText    },
                ].map(tab => (
                  <button
                    key={tab.key}
                    className={`detail-tab${inputTab === tab.key ? ' active' : ''}`}
                    onClick={() => setInputTab(tab.key)}
                  >
                    {tab.icon}<span className="tab-label"> {tab.label}</span>
                  </button>
                ))}
              </div>

              {/* Upload tab */}
              {inputTab === 'upload' && (
                <div
                  className={`drop-zone${drag ? ' drag-over' : ''}`}
                  onDrop={onDrop} onDragOver={onDragOver} onDragLeave={onDragLeave}
                  onClick={() => inputRef.current?.click()}
                >
                  <input ref={inputRef} type="file" accept=".pptx,.ppt,.pdf,.docx,.doc,.txt" multiple
                    onChange={e => addFiles(e.target.files)} style={{display:'none'}} />
                  <div className="drop-icon"><Upload size={22} /></div>
                  <div className="drop-title">{t.dropTitle}</div>
                  <div className="drop-sub">{t.dropSub}</div>
                </div>
              )}

              {/* YouTube tab */}
              {inputTab === 'youtube' && (
                <div>
                  <div className="input-row">
                    <input className="text-input"
                      placeholder={t.ytPlaceholder}
                      value={ytUrl}
                      onChange={e => setYtUrl(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && processYoutube()}
                    />
                    <button className="submit-btn" style={{flex:'none'}}
                      onClick={processYoutube}
                      disabled={!ytUrl.trim()}>
                      <Youtube size={15} /><span className="tab-label"> {t.ytBtn}</span>
                    </button>
                  </div>
                  <div style={{fontSize:'0.75rem',color:'var(--text-muted)',marginTop:'0.55rem'}}>
                    Works with any video — uses captions or audio transcription automatically.
                  </div>
                </div>
              )}

              {/* Paste Text tab */}
              {inputTab === 'text' && (
                <div>
                  <textarea className="text-input"
                    style={{width:'100%',marginBottom:'0.25rem'}}
                    placeholder={t.textPlaceholder}
                    value={pasteText}
                    onChange={e => setPasteText(e.target.value)}
                  />
                  <div style={{fontSize:'0.71rem',color:'var(--text-muted)',textAlign:'right',marginBottom:'0.35rem'}}>
                    {pasteText.trim() ? `${pasteText.trim().split(/\s+/).length} words` : ''}
                  </div>
                  <div className="input-row">
                    <input className="text-input"
                      placeholder={t.urlPlaceholder}
                      value={pasteUrl}
                      onChange={e => setPasteUrl(e.target.value)}
                    />
                    <button className="submit-btn" style={{flex:'none'}}
                      onClick={processText}
                      disabled={!pasteText.trim() && !pasteUrl.trim()}>
                      <Type size={15} /><span className="tab-label"> {t.textBtn}</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Detail level — always visible */}
              <div style={{display:'flex',alignItems:'center',gap:'0.45rem',marginTop:'0.85rem',flexWrap:'wrap'}}>
                <span style={{fontSize:'0.73rem',color:'var(--text-muted)',fontWeight:500,flexShrink:0}}>Level:</span>
                {[
                  { key:'brief',    label:'Brief',    hint:'6 cards · 5 Qs'  },
                  { key:'standard', label:'Standard', hint:'14 cards · 10 Qs' },
                  { key:'detailed', label:'Detailed', hint:'20 cards · 15 Qs' },
                ].map(d => (
                  <button key={d.key}
                    className={`detail-tab${detail === d.key ? ' active' : ''}`}
                    style={{fontSize:'0.73rem',padding:'0.28rem 0.6rem'}}
                    title={d.hint}
                    onClick={() => setDetail(d.key)}>
                    {d.label}
                  </button>
                ))}
                <span style={{fontSize:'0.7rem',color:'var(--text-muted)',marginLeft:'auto',flexShrink:0}}>
                  {detail === 'brief' ? '6 cards · 5 Qs' : detail === 'standard' ? '14 cards · 10 Qs' : '20 cards · 15 Qs'}
                </span>
              </div>

              {/* Output mode: full (with quiz) or summary only */}
              <div style={{display:'flex',alignItems:'center',gap:'0.55rem',marginTop:'0.6rem',flexWrap:'wrap'}}>
                <span style={{fontSize:'0.73rem',color:'var(--text-muted)',fontWeight:500,flexShrink:0}}>Output:</span>
                <button
                  className={`detail-tab${!summaryOnly ? ' active' : ''}`}
                  style={{fontSize:'0.73rem',padding:'0.28rem 0.6rem'}}
                  onClick={() => setSummaryOnly(false)}>
                  {lang === 'ar' ? 'دليل كامل + اختبار' : 'Full guide + quiz'}
                </button>
                <button
                  className={`detail-tab${summaryOnly ? ' active' : ''}`}
                  style={{fontSize:'0.73rem',padding:'0.28rem 0.6rem'}}
                  onClick={() => setSummaryOnly(true)}>
                  {lang === 'ar' ? 'ملخّص فقط' : 'Summary only'}
                </button>
              </div>

              {/* Language + Generate All row (only for upload tab) */}
              {inputTab === 'upload' && (
                <div className="options-row" style={{marginTop:'0.65rem'}}>
                  <select className="lang-select" value={lang} onChange={e => setLang(e.target.value)}>
                    <option value="auto">{t.langAuto}</option>
                    <option value="en">{t.langEn}</option>
                    <option value="ar">{t.langAr}</option>
                  </select>
                  {hasQueue && (
                    <button className="submit-btn"
                      disabled={running || !pendingCount}
                      onClick={processAll}>
                      {running
                        ? <><Loader2 size={15} className="spin" />{t.generating}</>
                        : <><Sparkles size={15} />{t.generateAll} {pendingCount > 0 ? `(${pendingCount})` : ''}</>
                      }
                    </button>
                  )}
                </div>
              )}

              {/* Privacy notice */}
              <div style={{
                display:'flex', alignItems:'flex-start', gap:'0.45rem',
                marginTop:'0.85rem', padding:'0.6rem 0.85rem',
                background:'var(--privacy-bg, rgba(34,197,94,0.08))',
                border:'1px solid var(--privacy-border, rgba(34,197,94,0.2))',
                borderRadius:'10px', fontSize:'0.78rem',
                color:'var(--privacy-text, #16a34a)',
                lineHeight:1.45,
                direction: lang === 'ar' ? 'rtl' : 'ltr',
              }}>
                <ShieldCheck size={14} style={{flexShrink:0, marginTop:'1px'}} />
                <span>{t.privacy}</span>
              </div>
            </div>

            {/* Referral card — visible only when signed in */}
            {session && userInfo?.referral_code && (
              <div className="glass" style={{
                marginTop:'1rem', padding:'1rem 1.25rem',
                direction: lang === 'ar' ? 'rtl' : 'ltr',
              }}>
                <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'0.55rem', flexWrap:'wrap', gap:'0.4rem'}}>
                  <div style={{display:'flex', alignItems:'center', gap:'0.45rem'}}>
                    <Gift size={14} color="#fbbf24" />
                    <span style={{fontWeight:700, fontSize:'0.88rem', color:'var(--text-primary)'}}>{t.referTitle}</span>
                  </div>
                  {refStats && (
                    <span style={{fontSize:'0.73rem', color: refStats.paid > 0 ? '#22c55e' : 'var(--text-muted)', fontWeight:500}}>
                      {t.referStats(refStats.paid)}
                    </span>
                  )}
                </div>
                <div style={{fontSize:'0.78rem', color:'var(--text-muted)', marginBottom:'0.7rem', lineHeight:1.55}}>
                  {t.referSub}
                </div>
                <div style={{display:'flex', gap:'0.5rem', alignItems:'center'}}>
                  <input
                    readOnly
                    value={`${window.location.origin}?ref=${userInfo.referral_code}`}
                    style={{
                      flex:1, padding:'0.45rem 0.75rem', borderRadius:8,
                      border:'1px solid var(--glass-border)', background:'var(--glass-light)',
                      color:'var(--text-secondary)', fontSize:'0.78rem', fontFamily:'inherit',
                      outline:'none', cursor:'text',
                    }}
                    onClick={e => e.target.select()}
                  />
                  <button
                    className="ctrl-btn"
                    style={copied ? {borderColor:'rgba(34,197,94,0.4)', color:'#22c55e'} : {}}
                    onClick={() => copyReferral(userInfo.referral_code)}
                  >
                    {copied ? <CheckCircle2 size={13} /> : <Copy size={13} />}
                    <span className="ctrl-label"> {copied ? t.referCopied : t.referCopy}</span>
                  </button>
                </div>
              </div>
            )}

            {/* Queue */}
            {hasQueue && (
              <div className="glass" style={{marginTop:'1rem',overflow:'hidden'}}>
                {/* Header */}
                <div className="queue-header">
                  <div style={{display:'flex',alignItems:'center',gap:'0.45rem',fontWeight:600,fontSize:'0.88rem',color:'var(--text-primary)'}}>
                    <Files size={15} />
                    {queue.length} item{queue.length !== 1 ? 's' : ''}
                    {doneCount > 0 && <span style={{fontSize:'0.76rem',color:'#22c55e',fontWeight:500}}>· {doneCount} ready</span>}
                  </div>
                  <div className="queue-header-actions" style={{display:'flex',gap:'0.35rem'}}>
                    {inputTab === 'upload' && (
                      <button className="ctrl-btn" onClick={() => inputRef.current?.click()}>
                        <Upload size={12} /><span className="ctrl-label"> {t.addMore}</span>
                      </button>
                    )}
                    <button className="ctrl-btn" onClick={clearAll}>
                      <X size={12} /><span className="ctrl-label"> {t.clearAll}</span>
                    </button>
                  </div>
                </div>

                {/* Items */}
                {queue.map((item, i) => {
                  const sc = STATUS_COLOR[item.status]
                  return (
                    <div key={item.id} className="queue-item"
                      style={{background: i % 2 === 0 ? 'transparent' : 'var(--glass-light)'}}>

                      {/* Main info row */}
                      <div className="queue-item-main">
                        <div className="queue-icon">
                          {item.status === 'processing' ? <Loader2 size={15} className="spin" />
                            : item.status === 'done'    ? <CheckCircle2 size={15} color="#22c55e" />
                            : item.status === 'error'   ? <AlertCircle size={15} color="#ef4444" />
                            : <FileText size={15} />}
                        </div>

                        <div style={{flex:1,minWidth:0}}>
                          <div className="queue-name">{item.name}</div>
                          {item.error && <div style={{fontSize:'0.72rem',color:'#ef4444',marginTop:2}}>{item.error}</div>}
                          {item.status === 'processing' && (
                            <div style={{fontSize:'0.72rem',color:'var(--text-muted)',marginTop:2}}>{item.msg || 'Processing…'}</div>
                          )}
                        </div>

                        <div className="queue-status-badge"
                          style={{background:sc.bg,color:sc.color,border:`1px solid ${sc.border}`}}>
                          {t[item.status]}
                        </div>

                        {!running && (
                          <button className="ctrl-btn" onClick={() => removeItem(item.id)}
                            style={{padding:'0.3rem 0.4rem',flexShrink:0}}>
                            <X size={13} />
                          </button>
                        )}
                      </div>

                      {/* Progress bar */}
                      {item.status === 'processing' && (
                        <div style={{padding:'0 1.2rem 0.65rem'}}>
                          <div className="progress-track">
                            <div style={{height:'100%',borderRadius:99,background:'linear-gradient(90deg,var(--accent),#a78bfa)',width:'60%',animation:'indeterminate 1.5s ease infinite'}} />
                          </div>
                        </div>
                      )}

                      {/* Action buttons (done items only) */}
                      {item.status === 'done' && (
                        <div className="action-row">
                          <button className="action-btn primary" title="Download PDF" onClick={() => downloadPDF(item)}>
                            <Download size={12} /><span className="action-label"> PDF</span>
                          </button>
                          <button className="action-btn" title="Export Anki CSV" onClick={() => downloadAnki(item)}>
                            <Download size={12} /><span className="action-label"> Anki</span>
                          </button>
                          <button className="action-btn" title="Delete my data from the server now" onClick={() => deleteNow(item)}>
                            <X size={12} /><span className="action-label"> Delete now</span>
                          </button>
                          <button className="action-btn" title="Flash Cards" onClick={() => setFlashModal(item.jobId)}>
                            <Brain size={12} /><span className="action-label"> Cards</span>
                          </button>
                          <button className="action-btn" title="Quiz" onClick={() => setQuizModal({jobId:item.jobId,filename:item.name})}>
                            <ClipboardList size={12} /><span className="action-label"> Quiz</span>
                          </button>
                          <button className="action-btn" title="Overview" onClick={() => setMindmapModal(item.jobId)}>
                            <Map size={12} /><span className="action-label"> Overview</span>
                          </button>
                          <button className="action-btn" title="Print / View" onClick={() => openPrint(item)}>
                            <Printer size={12} /><span className="action-label"> Print</span>
                          </button>
                          <button className="action-btn" title="Ask the guide" onClick={() => setChatModal(item.jobId)}>
                            <MessageSquare size={12} /><span className="action-label"> Chat</span>
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {/* Info pills */}
            {!hasQueue && (
              <div className="info-row">
                {t.pills.map(p => (
                  <div className="info-pill" key={p}><CheckCircle2 size={12} />{p}</div>
                ))}
              </div>
            )}
          </div>
        </main>

        {/* Site footer — must be inside app-wrap to stay above the fixed bg-mesh overlay */}
        <footer className="site-footer" style={{ direction: lang === 'ar' ? 'rtl' : 'ltr' }}>
          <div style={{marginBottom:'0.6rem'}}>
            © 2026 Alimne &nbsp;·&nbsp;
            <button onClick={() => setShowTerms(true)} className="footer-terms-btn">
              {lang === 'ar' ? 'الشروط والأحكام' : 'Terms & Conditions'}
            </button>
            &nbsp;·&nbsp;
            <a href="/privacy" className="footer-terms-btn" style={{textDecoration:'none'}}>
              {lang === 'ar' ? 'سياسة الخصوصية' : 'Privacy Policy'}
            </a>
            &nbsp;·&nbsp;
            {lang === 'ar'
              ? '3 رموز مجانية شهرياً · لا يُحفظ أي شيء'
              : '3 free tokens/month · No data stored'}
          </div>
          <a
            href="https://souc.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="souc-pill"
          >
            <span style={{fontSize:'0.6rem', opacity:0.7}}>⚡</span>
            {lang === 'ar' ? 'مدعوم من souc.ai' : 'Powered by souc.ai'}
          </a>
        </footer>
      </div>

      {/* ── Modals ── */}
      {flashModal   && <FlashCardModal jobId={flashModal} onClose={() => setFlashModal(null)} />}
      {quizModal    && <QuizModal jobId={quizModal.jobId} filename={quizModal.filename} onClose={() => setQuizModal(null)} />}
      {chatModal    && <ChatModal jobId={chatModal} onClose={() => setChatModal(null)} lang={lang} getAuthHeaders={getAuthHeaders} />}
      {mindmapModal && <OverviewModal jobId={mindmapModal} onClose={() => setMindmapModal(null)} />}
      {showHistory  && <HistoryModal onClose={() => setShowHistory(false)} />}
      {showTerms    && <TermsModal lang={lang} onClose={() => setShowTerms(false)} />}
      {showLogin    && <LoginModal onClose={() => setShowLogin(false)} onLogin={signIn} lang={lang} sbClient={sbClient} toast={toast} initialMode={loginMode} />}
      {showUpgrade  && (
        <UpgradeModal
          onClose={() => setShowUpgrade(false)}
          onUpgrade={handleCheckout}
          onManage={handleManageBilling}
          isSubscribed={isSubscribed}
          lang={lang}
        />
      )}

      <style>{`
        @keyframes indeterminate {
          0%   { transform: translateX(-100%); width: 60%; }
          100% { transform: translateX(200%);  width: 60%; }
        }
        @keyframes toastIn {
          from { opacity:0; transform: translateY(8px); }
          to   { opacity:1; transform: translateY(0); }
        }
        @keyframes tokenPulse {
          0%,100% { box-shadow: 0 0 0 0 rgba(251,191,36,0); }
          50%      { box-shadow: 0 0 0 3px rgba(251,191,36,0.25); }
        }
        .chat-input {
          flex: 1;
          padding: 0.6rem 0.9rem;
          border-radius: var(--radius-sm);
          border: 1px solid var(--glass-border);
          background: var(--glass-light);
          color: var(--text-primary);
          font-size: 0.88rem;
          font-family: inherit;
          outline: none;
        }
        .chat-input:focus { border-color: var(--accent); }
        @media print {
          .nav, button, .modal-overlay { display: none !important; }
        }
      `}</style>
    </div>
  )
}
