import { useState, useRef, useCallback, useEffect } from 'react'
import { createClient } from '@supabase/supabase-js'
import {
  BookOpen, Sun, Moon, Upload, FileText, Download,
  Loader2, CheckCircle2, AlertCircle, Sparkles, RotateCcw,
  Globe, Cpu, WifiOff, X, Files, ChevronDown,
  Youtube, Type, Brain, BarChart2, Map, Printer,
  ThumbsUp, ThumbsDown, MessageSquare, History, ClipboardList, ShieldCheck, ScrollText,
  LogIn, LogOut, User, Zap, Copy, Gift
} from 'lucide-react'

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
    privacy: 'Your files are processed in memory and never saved or seen by anyone. Nothing is stored after your session ends.',
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
    loginSub: '1 free token per month — no credit card required',
    loginBtn: 'Continue with Google',
    upgradeTitle: 'Out of tokens',
    upgradeSub: "You've used your free token for this month.",
    upgradeFeatures: ['20 tokens per month', 'Priority processing', 'All features included'],
    upgradeBtn: 'Upgrade — $2.99 / month',
    upgradeFree: 'Free plan: 1 token per month',
    signIn: 'Sign in',
    signOut: 'Sign out',
    tokensLeft: 'tokens',
    manageBtn: 'Manage subscription',
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
    privacy: 'ملفاتك تُعالج في الذاكرة فقط ولا تُحفظ أو يراها أحد. لا يُخزَّن أي شيء بعد انتهاء جلستك.',
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
    loginSub: 'رمز مجاني واحد شهرياً — بدون بطاقة ائتمانية',
    loginBtn: 'المتابعة عبر Google',
    upgradeTitle: 'نفدت رموزك',
    upgradeSub: 'لقد استخدمت رمزك المجاني لهذا الشهر.',
    upgradeFeatures: ['20 رمزاً شهرياً', 'معالجة ذات أولوية', 'جميع الميزات متاحة'],
    upgradeBtn: 'ترقية — 2.99$ / شهر',
    upgradeFree: 'الخطة المجانية: رمز واحد شهرياً',
    signIn: 'تسجيل الدخول',
    signOut: 'تسجيل الخروج',
    tokensLeft: 'رموز متبقية',
    manageBtn: 'إدارة الاشتراك',
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
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)'}}>Flash Cards</span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'2rem',textAlign:'center',color:'var(--text-secondary)'}}>
          {error ? <><AlertCircle size={20} style={{marginBottom:8,color:'#ef4444'}}/><div style={{color:'#ef4444'}}>{error}</div></> : <Loader2 size={20} className="spin" />}
        </div>
      </div>
    </div>
  )

  const progressPct = cards.length ? (knownCount / cards.length * 100) : 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{maxWidth:560}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <Brain size={15} /> Flash Cards
            {reviewMode && <span style={{fontSize:'0.75rem',color:'#fbbf24',fontWeight:500}}> — Review Missed</span>}
          </span>
          <div style={{display:'flex',gap:'0.4rem',alignItems:'center'}}>
            <button className="ctrl-btn" style={{fontSize:'0.75rem'}} onClick={resetAll}>Reset</button>
            <button className="modal-close" onClick={onClose}><X size={16} /></button>
          </div>
        </div>

        {/* Progress bar */}
        <div style={{padding:'0.75rem 1.25rem 0'}}>
          <div style={{display:'flex',justifyContent:'space-between',fontSize:'0.75rem',color:'var(--text-muted)',marginBottom:4}}>
            <span>{knownCount}/{cards.length} known</span>
            <span>{activeCards.length > 0 ? `${idx+1}/${activeCards.length}` : 'Complete'}</span>
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
                Round Complete!
              </div>
              <div style={{fontSize:'0.88rem',color:'var(--text-secondary)',marginBottom:20}}>
                {knownCount} known · {cards.length - knownCount} to review
              </div>
              <div style={{display:'flex',gap:'0.75rem',justifyContent:'center',flexWrap:'wrap'}}>
                {cards.length - knownCount > 0 && (
                  <button className="submit-btn" style={{flex:'none',padding:'0.6rem 1.2rem'}} onClick={resetReview}>
                    <RotateCcw size={14} /> Review Missed ({cards.length - knownCount})
                  </button>
                )}
                <button className="ctrl-btn" onClick={onClose}>Done</button>
              </div>
            </div>
          ) : currentCard ? (
            <>
              <div className={`fc-card${flipped ? ' flipped' : ''}`} onClick={() => setFlipped(f => !f)} style={{marginBottom:'1rem'}}>
                <div className="fc-card-inner">
                  <div className="fc-front">
                    <div style={{fontSize:'0.97rem',fontWeight:600,textAlign:'center'}}>{currentCard.q}</div>
                    <div style={{fontSize:'0.75rem',color:'rgba(255,255,255,0.5)',marginTop:'0.75rem',textAlign:'center'}}>Click to reveal answer</div>
                  </div>
                  <div className="fc-back">
                    <div style={{fontSize:'0.92rem',lineHeight:1.6}}>{currentCard.a}</div>
                  </div>
                </div>
              </div>
              <div style={{display:'flex',gap:'0.5rem',marginBottom:'0.75rem'}}>
                <button className="quiz-action-btn wrong" style={{flex:1}} onClick={() => mark(false)}>
                  <ThumbsDown size={14} /> Missed
                </button>
                <button className="quiz-action-btn" style={{flex:1}} onClick={() => setFlipped(f => !f)}>
                  Flip
                </button>
                <button className="quiz-action-btn correct" style={{flex:1}} onClick={() => mark(true)}>
                  <ThumbsUp size={14} /> Know it
                </button>
              </div>
              <div style={{display:'flex',justifyContent:'center'}}>
                <button className="ctrl-btn" style={{fontSize:'0.78rem'}}
                  onClick={() => speak(flipped ? currentCard.a : currentCard.q)}>
                  {speaking ? <><Loader2 size={12} className="spin" /> Speaking…</> : '🔊 Read aloud'}
                </button>
              </div>
            </>
          ) : (
            <div style={{textAlign:'center',color:'var(--text-muted)',padding:'2rem'}}>No cards available.</div>
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

  useEffect(() => {
    fetch(`/api/guide/${jobId}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) { setError(d.error); return }
        setMcqs(d.mcqs || [])
      })
      .catch(() => setError('Failed to load quiz'))
  }, [jobId])

  const pick = (letter) => {
    if (answered) return
    setAnswered(true)
    setSelected(letter)
    if (letter === mcqs[idx].answer) setScore(s => s + 1)
  }

  const next = () => {
    if (idx + 1 >= mcqs.length) {
      const finalScore = score
      const hist = JSON.parse(localStorage.getItem('quizHistory') || '[]')
      hist.unshift({ jobId, filename: filename || 'Quiz', score: finalScore, total: mcqs.length, date: new Date().toLocaleDateString() })
      localStorage.setItem('quizHistory', JSON.stringify(hist.slice(0, 50)))
      setDone(true)
    } else {
      setIdx(i => i + 1)
      setAnswered(false)
      setSelected(null)
    }
  }

  if (!mcqs) return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)'}}>Quiz</span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'2rem',textAlign:'center'}}>
          {error ? <div style={{color:'#ef4444'}}>{error}</div> : <Loader2 size={20} className="spin" />}
        </div>
      </div>
    </div>
  )

  const q = mcqs[idx]
  const pct = mcqs.length ? (idx / mcqs.length * 100) : 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{maxWidth:560}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <ClipboardList size={15} /> Quiz
          </span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'1rem 1.25rem',flex:1,overflowY:'auto'}}>
          {done ? (
            <div style={{textAlign:'center',padding:'1.5rem 0'}}>
              <div style={{fontSize:'3rem',fontWeight:700,color:'var(--accent)',marginBottom:8}}>{score}/{mcqs.length}</div>
              <div style={{color:'var(--text-secondary)',marginBottom:20}}>Quiz complete!</div>
              <button className="ctrl-btn" onClick={onClose}>Close</button>
            </div>
          ) : q ? (
            <>
              <div className="progress-track" style={{marginBottom:'1rem'}}>
                <div className="progress-bar" style={{width:`${pct}%`}} />
              </div>
              <div style={{fontSize:'0.8rem',color:'var(--text-muted)',marginBottom:6}}>Question {idx+1} of {mcqs.length}</div>
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
                    {idx + 1 >= mcqs.length ? 'Finish' : 'Next →'}
                  </button>
                </div>
              )}
            </>
          ) : (
            <div style={{textAlign:'center',color:'var(--text-muted)',padding:'2rem'}}>No questions available.</div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Quiz History Modal ─────────────────────────────────────────────────────────
function HistoryModal({ onClose }) {
  const hist = JSON.parse(localStorage.getItem('quizHistory') || '[]')
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{maxWidth:480}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <History size={15} /> Quiz History
          </span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'1rem 1.25rem',flex:1,overflowY:'auto',maxHeight:400}}>
          {hist.length === 0 ? (
            <div style={{textAlign:'center',color:'var(--text-muted)',padding:'2rem'}}>No quiz results yet.</div>
          ) : hist.map((h, i) => (
            <div key={i} style={{
              display:'flex',alignItems:'center',justifyContent:'space-between',
              padding:'0.65rem 0',
              borderBottom: i < hist.length - 1 ? '1px solid var(--glass-border)' : 'none'
            }}>
              <div>
                <div style={{fontSize:'0.88rem',fontWeight:500,color:'var(--text-primary)'}}>{h.filename}</div>
                <div style={{fontSize:'0.75rem',color:'var(--text-muted)'}}>{h.date}</div>
              </div>
              <div style={{
                fontWeight:700,fontSize:'0.97rem',
                color: h.score / h.total >= 0.7 ? '#22c55e' : h.score / h.total >= 0.4 ? '#fbbf24' : '#ef4444'
              }}>
                {h.score}/{h.total}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Mindmap Modal ──────────────────────────────────────────────────────────────
function MindmapModal({ jobId, onClose }) {
  const [guide, setGuide] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`/api/guide/${jobId}`)
      .then(r => r.json())
      .then(d => { if (d.error) { setError(d.error); return } setGuide(d) })
      .catch(() => setError('Failed to load guide'))
  }, [jobId])

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{maxWidth:640,maxHeight:'90vh'}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <Map size={15} /> Mindmap
          </span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <div style={{padding:'1.25rem',flex:1,overflowY:'auto'}}>
          {!guide ? (
            <div style={{textAlign:'center',padding:'2rem'}}>
              {error ? <div style={{color:'#ef4444'}}>{error}</div> : <Loader2 size={20} className="spin" />}
            </div>
          ) : (
            <div style={{fontFamily:'inherit'}}>
              <div style={{textAlign:'center',marginBottom:'1.5rem'}}>
                <div style={{
                  display:'inline-block',padding:'0.6rem 1.4rem',
                  background:'linear-gradient(135deg,var(--navy-600),var(--navy-400))',
                  color:'var(--white)',borderRadius:12,fontWeight:700,fontSize:'1rem',
                  boxShadow:'0 4px 18px var(--accent-glow)'
                }}>
                  {guide.title || 'Study Guide'}
                </div>
              </div>
              {(guide.keywords || []).length > 0 && (
                <div style={{marginBottom:'1.25rem'}}>
                  <div style={{
                    fontSize:'0.8rem',fontWeight:700,textTransform:'uppercase',
                    color:'var(--accent)',letterSpacing:'0.06em',marginBottom:'0.6rem'
                  }}>Keywords</div>
                  <div style={{display:'flex',flexWrap:'wrap',gap:'0.4rem'}}>
                    {(guide.keywords || []).slice(0, 20).map((k, i) => (
                      <span key={i} style={{
                        padding:'0.25rem 0.7rem',borderRadius:50,
                        background:'rgba(79,142,247,0.12)',border:'1px solid rgba(79,142,247,0.25)',
                        color:'var(--text-secondary)',fontSize:'0.78rem',fontWeight:500
                      }}>
                        {typeof k === 'object' ? k.term : k}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {(guide.objectives || []).length > 0 && (
                <div style={{
                  padding:'0.75rem 1rem',borderRadius:10,
                  background:'rgba(34,197,94,0.06)',border:'1px solid rgba(34,197,94,0.2)',
                  marginBottom:'1rem'
                }}>
                  <div style={{fontSize:'0.78rem',fontWeight:700,color:'#22c55e',textTransform:'uppercase',marginBottom:6}}>Objectives</div>
                  {(guide.objectives || []).map((o, i) => (
                    <div key={i} style={{fontSize:'0.84rem',color:'var(--text-secondary)',marginBottom:2}}>◆ {o}</div>
                  ))}
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
function ChatModal({ jobId, onClose, lang }) {
  const [msgs, setMsgs] = useState([{ role: 'ai', text: 'Ask me anything about this study guide!' }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const endRef = useRef()

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  const send = async () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setMsgs(m => [...m, { role: 'user', text: q }])
    setLoading(true)
    try {
      const r = await fetch(`/api/chat/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, language: lang })
      })
      const d = await r.json()
      setMsgs(m => [...m, { role: 'ai', text: d.answer || d.error || 'No response' }])
    } catch {
      setMsgs(m => [...m, { role: 'ai', text: 'Error — could not reach server.' }])
    }
    setLoading(false)
  }

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
              <div className="chat-bubble">{m.text}</div>
            </div>
          ))}
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
• Free plan: 1 processing token per month. No credit card required.
• Pro plan: $2.99/month (billed via Stripe). Includes 20 tokens per month.
• Tokens reset at the start of each calendar month.
• Subscriptions can be cancelled anytime via the billing portal. No refunds for partial months.
• Payments are processed by Stripe, Inc. and are subject to Stripe's Terms of Service.

3. YOUR FILES — PRIVACY & NO STORAGE
• Files you upload are processed entirely in server memory and never written to permanent storage.
• No copy of your document is retained after processing is complete.
• Generated study guides are held in temporary server memory for up to 90 minutes so you can download them, then deleted automatically.
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
• الخطة المجانية: رمز معالجة واحد شهرياً. لا تحتاج إلى بطاقة ائتمانية.
• الخطة الاحترافية: 2.99$ شهرياً (عبر Stripe). تشمل 30 رمزاً شهرياً.
• تُعاد الرموز في بداية كل شهر.
• يمكن إلغاء الاشتراك في أي وقت عبر بوابة الفوترة. لا يوجد استرداد للأشهر الجزئية.
• تُعالَج المدفوعات بواسطة Stripe وتخضع لشروط خدمة Stripe.

٣. ملفاتك — الخصوصية وعدم التخزين
• تُعالَج الملفات التي ترفعها في ذاكرة الخادم فقط ولا تُكتب على أي تخزين دائم.
• لا تُحتفظ بأي نسخة من مستنداتك بعد اكتمال المعالجة.
• تُحفظ أدلة الدراسة المولَّدة في ذاكرة الخادم المؤقتة لمدة 90 دقيقة للتنزيل ثم تُحذف تلقائياً.
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
function LoginModal({ onClose, onLogin, lang }) {
  const t = T[lang] || T['en']
  const isAr = lang === 'ar'
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
            <BookOpen size={24} color="#fff" />
          </div>
          <div style={{fontWeight:700, fontSize:'1.15rem', color:'var(--text-primary)', marginBottom:'0.4rem'}}>
            {t.loginTitle}
          </div>
          <div style={{fontSize:'0.82rem', color:'var(--text-muted)', lineHeight:1.55}}>
            {t.loginSub}
          </div>
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
  const [ollama, setOllama]   = useState(null)
  const [inputTab, setInputTab] = useState('upload')
  const [ytUrl, setYtUrl]     = useState('')
  const [pasteText, setPasteText] = useState('')
  const [pasteUrl, setPasteUrl]   = useState('')

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
  const [showUpgrade, setShowUpgrade] = useState(false)
  const [authLoading, setAuthLoading] = useState(true)

  // Referral
  const [refStats, setRefStats]     = useState(null)
  const [copied, setCopied]         = useState(false)

  const inputRef = useRef()
  const t = T[lang] || T['en']

  const quizHistory = JSON.parse(localStorage.getItem('quizHistory') || '[]')

  // ── Capture referral code from URL ────────────────────────────────────────
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const ref = params.get('ref')
    if (ref) {
      localStorage.setItem('alimne_ref', ref.toUpperCase())
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  // ── Status polling ─────────────────────────────────────────────────────────
  useEffect(() => {
    const check = () =>
      fetch('/api/status').then(r => r.json()).then(setOllama).catch(() => setOllama({ ollama: false }))
    check()
    const id = setInterval(check, 8000)
    return () => clearInterval(id)
  }, [])

  // ── Supabase init + auth ────────────────────────────────────────────────────
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(cfg => {
        setAuthEnabled(!!cfg.auth_enabled)
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
      .then(d => { if (d.url) window.location.href = d.url })
      .catch(() => {})
  }

  const handleManageBilling = () => {
    fetch('/api/stripe/portal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({})
    })
      .then(r => r.json())
      .then(d => { if (d.url) window.location.href = d.url })
      .catch(() => {})
  }

  // handle 401/402 from any SSE stream
  const handleAuthError = (status, item, resolve) => {
    if (status === 401) {
      setShowLogin(true)
      if (item) updateItem(item.id, { status: 'error', error: 'Please sign in to continue.' })
      if (resolve) resolve()
      return true
    }
    if (status === 402) {
      setShowUpgrade(true)
      if (item) updateItem(item.id, { status: 'error', error: 'No tokens remaining. Upgrade to continue.' })
      if (resolve) resolve()
      return true
    }
    return false
  }

  const addFiles = useCallback(fileList => {
    const valid = Array.from(fileList).filter(f => f.name.match(/\.(pptx?|pdf|docx?|txt)$/i))
    if (!valid.length) return
    setQueue(prev => [
      ...prev,
      ...valid.map(f => ({ id: uid(), file: f, name: f.name, status: 'queued', jobId: null, error: null, step: null, msg: null }))
    ])
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
          (err, status) => {
            if (!handleAuthError(status, item, resolve))
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
    if (!url) return
    const qitem = { id: uid(), file: null, name: url, status: 'processing', jobId: null, error: null, step: 'extract', msg: 'Fetching transcript…' }
    setQueue(prev => [...prev, qitem])
    setInputTab('upload')

    streamSSE(
      '/api/youtube',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ url, language: lang })
      },
      (ev) => {
        if (ev.language && lang === 'auto') setLang(ev.language)
        if (ev.error) { updateItem(qitem.id, { status: 'error', error: ev.error }); return }
        if (ev.step === 'done') {
          updateItem(qitem.id, { status: 'done', jobId: ev.job_id, step: 'done', msg: 'Ready' })
          if (ev.tokens_remaining !== undefined && userInfo)
            setUserInfo(u => ({ ...u, tokens_remaining: ev.tokens_remaining }))
        } else {
          updateItem(qitem.id, { step: ev.step, msg: ev.msg })
        }
      },
      (err, status) => {
        if (!handleAuthError(status, qitem, null))
          updateItem(qitem.id, { status: 'error', error: err })
      }
    )
    setYtUrl('')
  }

  // ── Paste text / URL SSE ───────────────────────────────────────────────────
  const processText = () => {
    const text = pasteText.trim()
    const url  = pasteUrl.trim()
    if (!text && !url) return
    const name = url ? url.replace(/^https?:\/\//, '').slice(0, 40) : 'Pasted text'
    const qitem = { id: uid(), file: null, name, status: 'processing', jobId: null, error: null, step: 'extract', msg: 'Processing text…' }
    setQueue(prev => [...prev, qitem])
    setInputTab('upload')

    streamSSE(
      '/api/summarize-text',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ text, url, language: lang, filename: name })
      },
      (ev) => {
        if (ev.error) { updateItem(qitem.id, { status: 'error', error: ev.error }); return }
        if (ev.step === 'done') {
          updateItem(qitem.id, { status: 'done', jobId: ev.job_id, step: 'done', msg: 'Ready' })
          if (ev.tokens_remaining !== undefined && userInfo)
            setUserInfo(u => ({ ...u, tokens_remaining: ev.tokens_remaining }))
        } else {
          updateItem(qitem.id, { step: ev.step, msg: ev.msg })
        }
      },
      (err, status) => {
        if (!handleAuthError(status, qitem, null))
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
  }

  const downloadAnki = (item) => {
    if (!item.jobId) return
    const a = document.createElement('a')
    a.href = `/api/export/anki/${item.jobId}`
    a.click()
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
                <div className="brand-icon"><BookOpen size={16} color="#fff" /></div>
                <div style={{display:'flex',flexDirection:'column',gap:'1px',lineHeight:1}}>
                  <span className="brand-name">{t.brand}</span>
                  <span style={{fontSize:'0.62rem',color:'var(--text-muted)',letterSpacing:'0.02em',fontWeight:400}}>
                    by <a href="https://souc.ai" target="_blank" rel="noopener noreferrer"
                      style={{color:'var(--accent)',textDecoration:'none',fontWeight:500}}>souc.ai</a>
                  </span>
                </div>
              </div>
              <div className="nav-controls">
                {ollama === null ? (
                  <div className="ctrl-btn"><Loader2 size={13} className="spin" /></div>
                ) : ollama.ollama ? (
                  <div className="ctrl-btn active"><Cpu size={13} /><span className="ctrl-label"> {(ollama.model||'AI').split('-')[0]}</span></div>
                ) : (
                  <div className="ctrl-btn" style={{borderColor:'rgba(79,142,247,0.4)',color:'var(--text-muted)'}}>
                    <Cpu size={13} />
                  </div>
                )}
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
                      <button
                        className="ctrl-btn"
                        style={{
                          cursor: 'pointer',
                          borderColor: (userInfo?.tokens_remaining ?? 1) <= 0 ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.3)',
                          color: (userInfo?.tokens_remaining ?? 1) <= 0 ? '#ef4444' : '#22c55e',
                        }}
                        onClick={() => setShowUpgrade(true)}
                        title="Tokens remaining"
                      >
                        <Zap size={12} />
                        <span className="ctrl-label"> {userInfo?.tokens_remaining ?? '…'} {t.tokensLeft}</span>
                      </button>
                      {/* User avatar / sign out */}
                      <button className="ctrl-btn" onClick={signOut} title={t.signOut}>
                        {userInfo?.avatar_url
                          ? <img src={userInfo.avatar_url} alt="" style={{width:18,height:18,borderRadius:'50%',objectFit:'cover'}} />
                          : <User size={13} />}
                      </button>
                    </>
                  ) : (
                    <button
                      className="ctrl-btn"
                      style={{borderColor:'var(--accent)',color:'var(--accent)'}}
                      onClick={() => setShowLogin(true)}
                    >
                      <LogIn size={13} /><span className="ctrl-label"> {t.signIn}</span>
                    </button>
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
                    style={{width:'100%',marginBottom:'0.55rem'}}
                    placeholder={t.textPlaceholder}
                    value={pasteText}
                    onChange={e => setPasteText(e.target.value)}
                  />
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

              {/* Language + Generate All row (only for upload tab) */}
              {inputTab === 'upload' && (
                <div className="options-row" style={{marginTop:'1rem'}}>
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
                          <button className="action-btn" title="Flash Cards" onClick={() => setFlashModal(item.jobId)}>
                            <Brain size={12} /><span className="action-label"> Cards</span>
                          </button>
                          <button className="action-btn" title="Quiz" onClick={() => setQuizModal({jobId:item.jobId,filename:item.name})}>
                            <ClipboardList size={12} /><span className="action-label"> Quiz</span>
                          </button>
                          <button className="action-btn" title="Mindmap" onClick={() => setMindmapModal(item.jobId)}>
                            <Map size={12} /><span className="action-label"> Map</span>
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
            {lang === 'ar'
              ? 'رمز مجاني شهرياً · لا يُحفظ أي شيء'
              : '1 free token/month · No data stored'}
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
      {chatModal    && <ChatModal jobId={chatModal} onClose={() => setChatModal(null)} lang={lang} />}
      {mindmapModal && <MindmapModal jobId={mindmapModal} onClose={() => setMindmapModal(null)} />}
      {showHistory  && <HistoryModal onClose={() => setShowHistory(false)} />}
      {showTerms    && <TermsModal lang={lang} onClose={() => setShowTerms(false)} />}
      {showLogin    && <LoginModal onClose={() => setShowLogin(false)} onLogin={signIn} lang={lang} />}
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
