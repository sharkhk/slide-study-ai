import { useState, useRef, useCallback, useEffect } from 'react'
import {
  BookOpen, Sun, Moon, Upload, FileText, Download, Loader2,
  CheckCircle2, AlertCircle, Sparkles, Globe, Cpu, WifiOff,
  X, Files, RotateCcw, Pencil, Check, ChevronRight, History,
  HelpCircle, Clock, Archive, GripVertical,
  Play, Pause, Layers, ThumbsUp, ThumbsDown, Trophy,
  ChevronLeft, RefreshCw, Zap, Volume2, Shuffle, BookMarked
} from 'lucide-react'

/* ── Translations ─────────────────────────────────────────────────────────── */
const T = {
  en: {
    brand: 'Slide Study AI', badge: 'Offline · AI-Powered',
    h1a: 'Turn Slides into', h1b: 'Study Guides',
    sub: 'Upload PowerPoints or PDFs — get individual exam-ready study guides with flash cards, quiz & more.',
    drop: 'Drop files here', dropSub: 'Click to browse · .pptx / .ppt / .pdf · multiple files',
    langEn: 'English output', langAr: 'Arabic output (عربي)',
    detailLabel: 'Detail level',
    brief: 'Brief', standard: 'Standard', detailed: 'Detailed',
    genAll: 'Generate All', genN: n => `Generate (${n})`,
    processing: 'Processing…', download: 'PDF', dlMd: 'MD',
    addMore: 'Add files', clearAll: 'Clear all',
    dlZip: n => `ZIP (${n})`,
    retry: 'Retry', rename: 'Rename',
    status: { queued:'Queued', processing:'Processing', done:'Ready', error:'Failed' },
    histTitle: 'Session History', histEmpty: 'No history yet',
    pills: ['PPT · PPTX · PDF','Flash Cards','Quiz','Fully offline'],
    ollamaOff: 'Ollama is not running',
    ollamaOffSub: 'Open a terminal and run: ollama serve',
    cards: 'Cards', quiz: 'Quiz',
    cardTitle: 'Flash Cards', quizTitle: 'Quiz',
    cardKnow: 'Got it', cardSkip: "Don't know",
    cardDone: 'Session complete!',
    cardKnown: n => `${n} known`,
    quizSubmit: 'Submit', quizRetry: 'Try again',
    quizScore: (s,t) => `Score: ${s} / ${t}`,
    timerWork: 'Focus', timerBreak: 'Break',
    timerReset: 'Reset',
    sessionExpired: 'Session expired — re-upload the file to use this feature.',
    kwTab: 'Keywords', readAloud: 'Read aloud', stopReading: 'Stop',
    kwHint: 'Space to flip · ← → to mark',
  },
  ar: {
    brand: 'دليل الدراسة AI', badge: 'بدون إنترنت · ذكاء اصطناعي',
    h1a: 'حوّل الشرائح إلى', h1b: 'أدلة دراسة',
    sub: 'ارفع ملفات PowerPoint أو PDF للحصول على أدلة دراسة مع بطاقات، اختبارات، ومحادثة.',
    drop: 'أسقط الملفات هنا', dropSub: 'انقر للتصفح · .pptx / .ppt / .pdf · ملفات متعددة',
    langEn: 'الإخراج بالإنجليزية', langAr: 'الإخراج بالعربية',
    detailLabel: 'مستوى التفصيل',
    brief: 'مختصر', standard: 'معتدل', detailed: 'مفصّل',
    genAll: 'توليد الكل', genN: n => `توليد (${n})`,
    processing: 'جارٍ…', download: 'PDF', dlMd: 'MD',
    addMore: 'إضافة ملفات', clearAll: 'مسح الكل',
    dlZip: n => `ZIP (${n})`,
    retry: 'إعادة', rename: 'إعادة التسمية',
    status: { queued:'في الانتظار', processing:'جارٍ', done:'جاهز', error:'فشل' },
    histTitle: 'سجل الجلسة', histEmpty: 'لا يوجد سجل',
    pills: ['PPT · PPTX · PDF','بطاقات تعليمية','اختبار','محادثة مع الشرائح','بدون إنترنت'],
    ollamaOff: 'Ollama غير مشغّل',
    ollamaOffSub: 'افتح الطرفية وشغّل: ollama serve',
    cards: 'بطاقات', quiz: 'اختبار',
    cardTitle: 'البطاقات التعليمية', quizTitle: 'الاختبار',
    cardKnow: 'أعرفها', cardSkip: 'لا أعرفها',
    cardDone: 'انتهت الجلسة!',
    cardKnown: n => `${n} معروفة`,
    quizSubmit: 'إرسال', quizRetry: 'إعادة المحاولة',
    quizScore: (s,t) => `النتيجة: ${s} / ${t}`,
    timerWork: 'تركيز', timerBreak: 'استراحة',
    timerReset: 'إعادة',
    sessionExpired: 'انتهت الجلسة — أعد رفع الملف لاستخدام هذه الميزة.',
    kwTab: 'الكلمات المفتاحية', readAloud: 'قراءة بصوت', stopReading: 'إيقاف',
    kwHint: 'مسافة للقلب · ← → للتحديد',
  }
}

const SC = {
  queued:     { bg:'rgba(79,142,247,.12)',  color:'#4f8ef7',  border:'rgba(79,142,247,.3)'  },
  processing: { bg:'rgba(251,191,36,.12)',  color:'#fbbf24',  border:'rgba(251,191,36,.3)'  },
  done:       { bg:'rgba(34,197,94,.12)',   color:'#22c55e',  border:'rgba(34,197,94,.3)'   },
  error:      { bg:'rgba(239,68,68,.12)',   color:'#ef4444',  border:'rgba(239,68,68,.3)'   },
}

let _id = 0
const uid = () => ++_id

/* ── Pomodoro Timer ───────────────────────────────────────────────────────── */
function PomodoroTimer({ t, onClose }) {
  const WORK = 25 * 60, BREAK = 5 * 60
  const [mode, setMode]       = useState('work')
  const [secs, setSecs]       = useState(WORK)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    const h = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  useEffect(() => {
    if (!running) return
    const id = setInterval(() => {
      setSecs(s => {
        if (s <= 1) {
          setRunning(false)
          const next = mode === 'work' ? 'break' : 'work'
          setMode(next)
          return next === 'work' ? WORK : BREAK
        }
        return s - 1
      })
    }, 1000)
    return () => clearInterval(id)
  }, [running, mode])

  const reset = () => { setRunning(false); setSecs(mode === 'work' ? WORK : BREAK) }
  const mm = String(Math.floor(secs / 60)).padStart(2, '0')
  const ss = String(secs % 60).padStart(2, '0')
  const pct = mode === 'work' ? ((WORK - secs) / WORK) * 100 : ((BREAK - secs) / BREAK) * 100

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box timer-box" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}><X size={16}/></button>
        <div className="timer-modes">
          <button className={`timer-mode-btn${mode==='work'?' active':''}`}
            onClick={() => { setMode('work'); setSecs(WORK); setRunning(false) }}>
            <Zap size={13}/>{t.timerWork}
          </button>
          <button className={`timer-mode-btn${mode==='break'?' active':''}`}
            onClick={() => { setMode('break'); setSecs(BREAK); setRunning(false) }}>
            <Clock size={13}/>{t.timerBreak}
          </button>
        </div>
        <div className="timer-ring">
          <svg viewBox="0 0 120 120" className="timer-svg">
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--glass-border)" strokeWidth="6"/>
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--accent)" strokeWidth="6"
              strokeDasharray={`${2 * Math.PI * 52}`}
              strokeDashoffset={`${2 * Math.PI * 52 * (1 - pct / 100)}`}
              strokeLinecap="round" transform="rotate(-90 60 60)"
              style={{transition:'stroke-dashoffset 1s linear'}}/>
          </svg>
          <div className="timer-display">{mm}:{ss}</div>
        </div>
        <div className="timer-controls">
          <button className="ctrl-btn" onClick={reset}><RefreshCw size={14}/>{t.timerReset}</button>
          <button className="submit-btn" style={{flex:'none',padding:'0.6rem 2rem'}} onClick={() => setRunning(r => !r)}>
            {running ? <><Pause size={15}/>Pause</> : <><Play size={15}/>Start</>}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Flash Cards Modal ────────────────────────────────────────────────────── */
function FlashCardModal({ jobId, title, lang, t, onClose }) {
  const [guide,    setGuide]   = useState({ flashcards: [], keywords: [] })
  const [cards,    setCards]   = useState([])
  const [loading,  setLoading] = useState(true)
  const [expired,  setExpired] = useState(false)
  const [tab,      setTab]     = useState('cards')
  const [idx,      setIdx]     = useState(0)
  const [flipped,  setFlipped] = useState(false)
  const [shuffled, setShuffled]= useState(false)
  const [autoPlay, setAutoPlay]= useState(false)
  const [speaking, setSpeaking]= useState(false)
  const [known,    setKnown]   = useState(() => {
    try { return JSON.parse(localStorage.getItem(`fc_${title}`) || '{}') } catch { return {} }
  })
  const origRef    = useRef([])
  // autoRef is a plain ref so async TTS callbacks can read the live value
  // without being trapped in a stale closure.
  const autoRef    = useRef(false)
  const cardsRef   = useRef([])   // always mirrors `cards` state for use in callbacks

  useEffect(() => { cardsRef.current = cards }, [cards])

  useEffect(() => {
    fetch(`/api/guide/${jobId}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) { setExpired(true); setLoading(false); return }
        const fcs = d.flashcards || []
        origRef.current  = fcs
        cardsRef.current = fcs
        setGuide({ flashcards: fcs, keywords: d.keywords || [] })
        setCards(fcs)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [jobId])

  // Stop everything when modal unmounts
  useEffect(() => () => {
    autoRef.current = false
    window.speechSynthesis?.cancel()
  }, [])

  // ── Core TTS helper ────────────────────────────────────────────────────────
  // Speaks `text` and calls `onDone` when the utterance ends (or errors).
  // Cancels any previous speech first so calls can be chained safely.
  const doSpeak = (text, onDone) => {
    if (!window.speechSynthesis) { onDone?.(); return }
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang   = lang === 'ar' ? 'ar-SA' : 'en-US'
    u.onend  = () => { setSpeaking(false); onDone?.() }
    u.onerror= () => { setSpeaking(false); onDone?.() }
    setSpeaking(true)
    window.speechSynthesis.speak(u)
  }

  // ── Auto-play engine ───────────────────────────────────────────────────────
  // Reads card[i] question → waits → flips → reads answer → waits → advances.
  // Each step checks autoRef.current so Stop cancels immediately at any point.
  const playFrom = (i) => {
    const list = cardsRef.current
    if (!autoRef.current || i >= list.length) {
      autoRef.current = false
      setAutoPlay(false)
      setSpeaking(false)
      return
    }
    setIdx(i)
    setFlipped(false)

    // 1. Read the question
    doSpeak(list[i].q, () => {
      if (!autoRef.current) return
      // 2. Pause 400 ms, then flip
      setTimeout(() => {
        if (!autoRef.current) return
        setFlipped(true)
        // 3. Wait for the CSS flip animation (450 ms) then read the answer
        setTimeout(() => {
          if (!autoRef.current) return
          doSpeak(list[i].a, () => {
            if (!autoRef.current) return
            // 4. Pause 900 ms then move to the next card
            setTimeout(() => playFrom(i + 1), 900)
          })
        }, 480)
      }, 400)
    })
  }

  const stopAutoPlay = () => {
    autoRef.current = false
    setAutoPlay(false)
    window.speechSynthesis?.cancel()
    setSpeaking(false)
  }

  const toggleAutoPlay = () => {
    if (autoRef.current) { stopAutoPlay(); return }
    autoRef.current = true
    setAutoPlay(true)
    playFrom(idx)
  }

  // ── Manual speak (keywords tab / one-shot) ─────────────────────────────────
  const speakOnce = (text) => {
    if (autoRef.current) return            // don't interrupt auto-play
    if (speaking) { window.speechSynthesis?.cancel(); setSpeaking(false); return }
    doSpeak(text, null)
  }

  // ── Manual mark (know / don't know) ───────────────────────────────────────
  const markRef = useRef()
  markRef.current = (k) => {
    if (autoRef.current) return            // ignore taps during auto-play
    const next = { ...known, [idx]: k }
    setKnown(next)
    try { localStorage.setItem(`fc_${title}`, JSON.stringify(next)) } catch {}
    window.speechSynthesis?.cancel()
    setSpeaking(false)
    if (idx < cards.length - 1) { setIdx(i => i + 1); setFlipped(false) }
  }

  // ── Keyboard shortcuts ─────────────────────────────────────────────────────
  useEffect(() => {
    const h = e => {
      if (e.key === 'Escape') { stopAutoPlay(); onClose(); return }
      if (tab !== 'cards') return
      if (e.key === ' ')          { e.preventDefault(); setFlipped(f => !f) }
      if (e.key === 'ArrowRight') markRef.current(true)
      if (e.key === 'ArrowLeft')  markRef.current(false)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose, tab])

  // ── Shuffle ────────────────────────────────────────────────────────────────
  const toggleShuffle = () => {
    stopAutoPlay()
    if (shuffled) {
      setCards([...origRef.current])
    } else {
      setCards(c => [...c].sort(() => Math.random() - 0.5))
    }
    setShuffled(s => !s)
    setIdx(0); setFlipped(false); setKnown({})
  }

  const card       = cards[idx]
  const knownCount = Object.values(known).filter(Boolean).length
  const done       = cards.length > 0 && idx >= cards.length

  return (
    <div className="modal-overlay" onClick={() => { stopAutoPlay(); onClose() }}>
      <div className="modal-box" onClick={e => e.stopPropagation()}
           style={{maxHeight:'90vh', display:'flex', flexDirection:'column'}}>

        {/* Header */}
        <div className="modal-header" style={{flexShrink:0}}>
          <div style={{display:'flex',alignItems:'center',gap:'0.4rem',flex:1,minWidth:0}}>
            {[['cards', <Layers size={13}/>, t.cardTitle],
              ['keywords', <BookMarked size={13}/>, t.kwTab]].map(([key, icon, label]) => (
              <button key={key} onClick={() => { stopAutoPlay(); setTab(key) }}
                style={{display:'flex',alignItems:'center',gap:'0.3rem',
                  padding:'3px 10px',borderRadius:6,border:'1px solid',
                  fontSize:'0.8rem',fontFamily:'inherit',cursor:'pointer',
                  borderColor: tab===key ? 'var(--accent)' : 'var(--glass-border)',
                  background:  tab===key ? 'rgba(79,142,247,.15)' : 'transparent',
                  color:       tab===key ? 'var(--accent)' : 'var(--text-muted)'}}>
                {icon}{label}
                {key==='keywords' && guide.keywords.length > 0 &&
                  <span style={{fontSize:'0.72rem',opacity:0.7}}>({guide.keywords.length})</span>}
                {key==='cards' && !loading && cards.length > 0 &&
                  <span style={{fontSize:'0.72rem',opacity:0.7}}>{idx+1}/{cards.length}</span>}
              </button>
            ))}
          </div>
          <div style={{display:'flex',gap:'0.25rem',alignItems:'center'}}>
            {tab==='cards' && cards.length > 0 && (
              <button title="Shuffle" onClick={toggleShuffle}
                style={{background:'none',border:'none',cursor:'pointer',padding:4,borderRadius:6,
                  color: shuffled ? 'var(--accent)' : 'var(--text-muted)',transition:'color 0.2s'}}>
                <Shuffle size={14}/>
              </button>
            )}
            <button className="modal-close" onClick={() => { stopAutoPlay(); onClose() }}><X size={16}/></button>
          </div>
        </div>

        {/* ── CARDS TAB ── */}
        {tab === 'cards' && (
          <>
            {loading  && <div style={{textAlign:'center',padding:'3rem',color:'var(--text-muted)'}}><Loader2 size={28} className="spin"/></div>}
            {expired  && <div style={{padding:'2rem',textAlign:'center',color:'#f74f4f',fontSize:'0.9rem'}}>{t.sessionExpired}</div>}

            {!loading && !expired && done && (
              <div style={{textAlign:'center',padding:'3rem 2rem'}}>
                <Trophy size={48} color="#fbbf24" style={{marginBottom:'1rem'}}/>
                <div style={{fontSize:'1.2rem',fontWeight:700,color:'var(--text-primary)',marginBottom:'0.5rem'}}>{t.cardDone}</div>
                <div style={{color:'var(--text-muted)',marginBottom:'1.5rem'}}>{t.cardKnown(knownCount)} / {cards.length}</div>
                <button className="ctrl-btn" onClick={() => { setIdx(0); setFlipped(false); setKnown({}) }}>
                  <RefreshCw size={14}/>{t.quizRetry}
                </button>
              </div>
            )}

            {!loading && !expired && !done && card && (
              <div style={{padding:'1.25rem 1.5rem 1.5rem'}}>

                {/* Auto-play indicator bar */}
                {autoPlay && (
                  <div style={{display:'flex',alignItems:'center',justifyContent:'center',
                    gap:'0.5rem',marginBottom:'0.75rem',
                    padding:'0.3rem 0.75rem',borderRadius:8,
                    background:'rgba(79,142,247,0.1)',border:'1px solid rgba(79,142,247,0.25)'}}>
                    <div style={{width:7,height:7,borderRadius:'50%',background:'var(--accent)',
                      animation:'pulse 1s ease infinite'}}/>
                    <span style={{fontSize:'0.75rem',color:'var(--accent)',fontWeight:600}}>
                      {speaking
                        ? (flipped ? 'Reading answer…' : 'Reading question…')
                        : 'Auto-reading…'}
                    </span>
                    <button onClick={stopAutoPlay}
                      style={{background:'none',border:'none',cursor:'pointer',
                        color:'var(--accent)',padding:0,lineHeight:1,fontSize:'0.75rem',
                        marginLeft:'0.25rem',textDecoration:'underline',fontFamily:'inherit'}}>
                      Stop
                    </button>
                  </div>
                )}

                {/* Flip card — pointer-events disabled during auto-play */}
                <div className={`fc-card${flipped ? ' flipped' : ''}`}
                  onClick={() => !autoPlay && setFlipped(f => !f)}
                  style={{cursor: autoPlay ? 'default' : 'pointer'}}>
                  <div className="fc-card-inner">
                    <div className="fc-front">
                      <div style={{fontSize:'0.68rem',fontWeight:700,letterSpacing:'0.1em',
                        color:'rgba(255,255,255,0.45)',marginBottom:'0.75rem',textTransform:'uppercase'}}>Question</div>
                      <div style={{fontSize:'1rem',fontWeight:600,color:'#fff',lineHeight:1.5,flex:1}}>{card.q}</div>
                      {!autoPlay && (
                        <div style={{fontSize:'0.72rem',color:'rgba(255,255,255,0.3)',marginTop:'0.75rem'}}>{t.kwHint}</div>
                      )}
                    </div>
                    <div className="fc-back">
                      <div style={{fontSize:'0.68rem',fontWeight:700,letterSpacing:'0.1em',
                        color:'var(--accent)',marginBottom:'0.75rem',textTransform:'uppercase'}}>Answer</div>
                      <div style={{fontSize:'0.95rem',color:'var(--text-primary)',lineHeight:1.6,flex:1}}>{card.a}</div>
                    </div>
                  </div>
                </div>

                {/* Auto-play toggle button */}
                <div style={{display:'flex',justifyContent:'center',marginTop:'0.65rem'}}>
                  <button onClick={toggleAutoPlay}
                    style={{display:'flex',alignItems:'center',gap:'0.4rem',
                      padding:'0.32rem 1.1rem',borderRadius:8,fontFamily:'inherit',
                      fontSize:'0.78rem',cursor:'pointer',transition:'all 0.2s',
                      border: autoPlay
                        ? '1px solid rgba(239,68,68,0.4)'
                        : '1px solid var(--glass-border)',
                      background: autoPlay
                        ? 'rgba(239,68,68,0.1)'
                        : 'rgba(79,142,247,0.08)',
                      color: autoPlay ? '#ef4444' : 'var(--accent)'}}>
                    <Volume2 size={13}/>
                    {autoPlay ? t.stopReading : t.readAloud}
                  </button>
                </div>

                {/* Mark buttons — hidden while auto-playing */}
                {!autoPlay && (
                  <div style={{display:'flex',gap:'0.75rem',marginTop:'0.75rem'}}>
                    <button onClick={() => markRef.current(false)} className="quiz-action-btn wrong" style={{flex:1}}>
                      <ThumbsDown size={15}/>{t.cardSkip}
                    </button>
                    <button onClick={() => markRef.current(true)} className="quiz-action-btn correct" style={{flex:1}}>
                      <ThumbsUp size={15}/>{t.cardKnow}
                    </button>
                  </div>
                )}

                {/* Dot nav */}
                <div style={{display:'flex',justifyContent:'center',gap:'0.45rem',marginTop:'0.9rem',flexWrap:'wrap'}}>
                  {cards.map((_, i) => (
                    <div key={i}
                      onClick={() => {
                        if (autoPlay) return
                        setIdx(i); setFlipped(false)
                        window.speechSynthesis?.cancel(); setSpeaking(false)
                      }}
                      style={{width:9,height:9,borderRadius:'50%',
                        cursor: autoPlay ? 'default' : 'pointer',
                        background: i===idx && autoPlay
                          ? 'var(--accent)'
                          : known[i]===true ? '#22c55e'
                          : known[i]===false ? '#ef4444'
                          : 'var(--glass-border)',
                        border: i===idx ? '2px solid var(--accent)' : '2px solid transparent',
                        transition:'all 0.2s'}}/>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* ── KEYWORDS TAB ── */}
        {tab === 'keywords' && (
          <div style={{overflowY:'auto',flex:1}}>
            {loading && <div style={{textAlign:'center',padding:'3rem',color:'var(--text-muted)'}}><Loader2 size={28} className="spin"/></div>}
            {!loading && guide.keywords.length === 0 && (
              <div style={{textAlign:'center',padding:'3rem',color:'var(--text-muted)',fontSize:'0.88rem'}}>
                No keywords found.
              </div>
            )}
            {!loading && guide.keywords.map((kw, i) => (
              <div key={i} style={{display:'flex',gap:'0.75rem',padding:'0.7rem 1.25rem',
                borderBottom:'1px solid var(--glass-border)',alignItems:'flex-start',
                background: i%2===0 ? 'transparent' : 'var(--glass-light)'}}>
                <div style={{flex:'0 0 38%',fontWeight:600,fontSize:'0.86rem',
                  color:'var(--accent)',wordBreak:'break-word',paddingTop:1}}>
                  {kw.term}
                </div>
                <div style={{flex:1,fontSize:'0.83rem',color:'var(--text-primary)',lineHeight:1.55}}>
                  {kw.definition}
                </div>
                <button onClick={() => speakOnce(`${kw.term}. ${kw.definition}`)}
                  title={t.readAloud}
                  style={{background:'none',border:'none',cursor:'pointer',
                    padding:3,borderRadius:6,color:'var(--text-muted)',flexShrink:0,transition:'color 0.2s'}}
                  onMouseEnter={e => e.currentTarget.style.color='var(--accent)'}
                  onMouseLeave={e => e.currentTarget.style.color='var(--text-muted)'}>
                  <Volume2 size={12}/>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Quiz Modal ───────────────────────────────────────────────────────────── */
function QuizModal({ jobId, title, lang, t, onClose }) {
  const [mcqs, setMcqs]         = useState([])
  const [loading, setLoading]   = useState(true)
  const [expired, setExpired]   = useState(false)
  const [answers, setAnswers]   = useState({})
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    const h = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  useEffect(() => {
    fetch(`/api/guide/${jobId}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) { setExpired(true); setLoading(false); return }
        setMcqs(d.mcqs || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [jobId])

  const score = submitted ? mcqs.filter((m, i) => answers[i] === m.answer).length : 0

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={e => e.stopPropagation()} style={{maxHeight:'90vh',overflowY:'auto'}}>
        <div className="modal-header" style={{position:'sticky',top:0,background:'var(--glass-bg)',backdropFilter:'blur(12px)',zIndex:2}}>
          <div style={{fontWeight:700,fontSize:'1rem',color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <HelpCircle size={16} color="var(--accent)"/>{t.quizTitle}
            {submitted && (
              <span style={{fontSize:'0.82rem',color: score >= mcqs.length*0.7 ? '#22c55e' : '#fbbf24',fontWeight:600}}>
                · {t.quizScore(score, mcqs.length)}
              </span>
            )}
          </div>
          <button className="modal-close" onClick={onClose}><X size={16}/></button>
        </div>

        {loading && <div style={{textAlign:'center',padding:'3rem',color:'var(--text-muted)'}}><Loader2 size={28} className="spin"/></div>}
        {expired && <div style={{padding:'2rem',textAlign:'center',color:'#f74f4f',fontSize:'0.9rem'}}>{t.sessionExpired}</div>}

        {!loading && !expired && mcqs.length > 0 && (
          <div style={{padding:'1rem 1.5rem 1.5rem'}}>
            {/* Progress bar */}
            {!submitted && (
              <div style={{marginBottom:'1rem'}}>
                <div style={{display:'flex',justifyContent:'space-between',
                  fontSize:'0.75rem',color:'var(--text-muted)',marginBottom:'0.4rem'}}>
                  <span>{Object.keys(answers).length} / {mcqs.length} answered</span>
                  <span>{Math.round(Object.keys(answers).length / mcqs.length * 100)}%</span>
                </div>
                <div style={{height:4,borderRadius:99,background:'var(--glass-border)',overflow:'hidden'}}>
                  <div style={{height:'100%',borderRadius:99,
                    background:'linear-gradient(90deg,var(--accent),#a78bfa)',
                    width:`${Object.keys(answers).length / mcqs.length * 100}%`,
                    transition:'width 0.3s ease'}}/>
                </div>
              </div>
            )}
            {mcqs.map((m, qi) => {
              const selected = answers[qi]
              const isCorrect = selected === m.answer
              return (
                <div key={qi} style={{marginBottom:'1.5rem'}}>
                  <div style={{fontWeight:600,fontSize:'0.92rem',color:'var(--text-primary)',
                    marginBottom:'0.65rem',lineHeight:1.5}}>
                    {qi + 1}. {m.q}
                  </div>
                  {(m.options || []).map(opt => {
                    const letter = opt.trim()[0]
                    const sel    = selected === letter
                    const corr   = submitted && letter === m.answer
                    const wrong  = submitted && sel && !isCorrect
                    return (
                      <button key={opt} onClick={() => !submitted && setAnswers(a => ({...a, [qi]: letter}))}
                        className={`quiz-option${sel?' selected':''}${corr?' correct':''}${wrong?' wrong':''}`}>
                        {opt}
                        {corr && <CheckCircle2 size={14} style={{marginLeft:'auto',color:'#22c55e'}}/>}
                        {wrong && <X size={14} style={{marginLeft:'auto',color:'#ef4444'}}/>}
                      </button>
                    )
                  })}
                  {submitted && (
                    <div style={{fontSize:'0.78rem',color:'var(--text-muted)',marginTop:'0.4rem',
                      padding:'0.4rem 0.7rem',background:'var(--glass-light)',borderRadius:6}}>
                      {m.explanation}
                    </div>
                  )}
                </div>
              )
            })}
            <div style={{display:'flex',gap:'0.75rem',paddingTop:'0.5rem'}}>
              {!submitted ? (
                <button className="submit-btn" style={{flex:1}}
                  onClick={() => setSubmitted(true)}
                  disabled={Object.keys(answers).length < mcqs.length}>
                  <CheckCircle2 size={15}/>{t.quizSubmit}
                </button>
              ) : (
                <button className="ctrl-btn" style={{flex:1}}
                  onClick={() => { setAnswers({}); setSubmitted(false) }}>
                  <RefreshCw size={14}/>{t.quizRetry}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}


/* ── App ──────────────────────────────────────────────────────────────────── */
export default function App() {
  const [theme,       setTheme]       = useState('dark')
  const [lang,        setLang]        = useState('en')
  const [queue,       setQueue]       = useState([])
  const [drag,        setDrag]        = useState(false)
  const [running,     setRunning]     = useState(false)
  const [ollama,      setOllama]      = useState(null)
  const [history,     setHistory]     = useState([])
  const [showHist,    setShowHist]    = useState(false)
  const [editId,      setEditId]      = useState(null)
  const [editVal,     setEditVal]     = useState('')
  const [detailLevel, setDetailLevel] = useState('standard')
  const [dragSrcId,   setDragSrcId]   = useState(null)
  const [dragTarget,  setDragTarget]  = useState(null)
  const [showTimer,   setShowTimer]   = useState(false)
  const [flashModal,  setFlashModal]  = useState(null)
  const [quizModal,   setQuizModal]   = useState(null)
  const inputRef = useRef()
  const t = T[lang]

  useEffect(() => {
    const check = () =>
      fetch('/api/status').then(r => r.json()).then(setOllama).catch(() => setOllama({ ollama: false }))
    check()
    const id = setInterval(check, 8000)
    return () => clearInterval(id)
  }, [])

  const addFiles = useCallback(fileList => {
    const valid = Array.from(fileList).filter(f => f.name.match(/\.(pptx?|pdf)$/i))
    if (!valid.length) return
    setQueue(prev => [...prev, ...valid.map(f => ({
      id: uid(), file: f,
      name: f.name.replace(/\.(pptx?|pdf)$/i, ''),
      status: 'queued', pdfUrl: null, mdUrl: null,
      jobId: null, error: null, stepMsg: '', stats: null
    }))])
  }, [])

  const onDrop = e => {
    e.preventDefault()
    setDrag(false)
    if (!dragSrcId) addFiles(e.dataTransfer.files)
  }

  const upd = (id, patch) =>
    setQueue(prev => prev.map(i => i.id === id ? { ...i, ...patch } : i))

  const removeItem = id => setQueue(prev => prev.filter(i => i.id !== id))
  const clearAll   = () => setQueue([])

  /* SSE-based processing */
  const processFile = item => new Promise(resolve => {
    const fd = new FormData()
    fd.append('file', item.file)
    fd.append('language', lang)
    fd.append('filename', item.name)
    fd.append('detail', detailLevel)

    upd(item.id, { status: 'processing', error: null, stepMsg: t.processing })

    fetch('/api/summarize-stream', { method: 'POST', body: fd })
      .then(res => {
        if (!res.ok) return res.json().then(d => { throw new Error(d.error || 'Server error') })
        const reader  = res.body.getReader()
        const decoder = new TextDecoder()
        // Buffer accumulates raw bytes across TCP chunks so that a JSON payload
        // spanning two reads is never split and silently dropped.
        let buffer = ''
        let settled = false
        const settle = () => { if (!settled) { settled = true; resolve() } }

        const processLine = line => {
          if (!line.startsWith('data: ')) return
          let data
          try { data = JSON.parse(line.slice(6)) } catch { return }
          if (data.error) {
            upd(item.id, { status: 'error', error: data.error, stepMsg: '' })
            settle()
          } else if (data.step === 'done') {
            const jid    = data.job_id
            const pdfUrl = `/api/download/${jid}?filename=${encodeURIComponent(item.name + '_study_guide')}&format=pdf`
            const mdUrl  = `/api/download/${jid}?filename=${encodeURIComponent(item.name + '_study_guide')}&format=md`
            const stats  = { sections: data.sections, keywords: data.keywords, flashcards: data.flashcards, mcqs: data.mcqs }
            upd(item.id, { status: 'done', pdfUrl, mdUrl, jobId: jid, stepMsg: '', stats })
            setHistory(h => [{ id: uid(), name: item.name, pdfUrl, stats, ts: Date.now() }, ...h].slice(0, 20))
            settle()
          } else {
            upd(item.id, { stepMsg: data.msg || data.step })
          }
        }

        const read = () => reader.read().then(({ done, value }) => {
          if (done) {
            // Flush any remaining buffered line before resolving
            if (buffer.trim()) processLine(buffer.trim())
            settle(); return
          }
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''  // last element may be an incomplete line
          lines.forEach(processLine)
          read()
        }).catch(settle)
        read()
      })
      .catch(e => { upd(item.id, { status: 'error', error: e.message, stepMsg: '' }); resolve() })
  })

  const processAll = async () => {
    const pending = queue.filter(i => i.status === 'queued' || i.status === 'error')
    if (!pending.length || running) return
    setRunning(true)
    for (const item of pending) await processFile(item)
    setRunning(false)
  }

  const downloadItem = item => {
    const a = document.createElement('a')
    a.href = item.pdfUrl
    a.download = item.name + '_study_guide.pdf'
    a.click()
  }

  const downloadMd = item => {
    const a = document.createElement('a')
    a.href = item.mdUrl
    a.download = item.name + '_study_guide.md'
    a.click()
  }

  const downloadZip = async () => {
    const done = queue.filter(i => i.status === 'done' && i.jobId)
    if (!done.length) return
    const r = await fetch('/api/download-zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_ids: done.map(i => i.jobId) })
    })
    const blob = await r.blob()
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = 'study_guides.zip'; a.click()
    URL.revokeObjectURL(url)
  }

  const startEdit  = item => { setEditId(item.id); setEditVal(item.name) }
  const commitEdit = id   => { if (editVal.trim()) upd(id, { name: editVal.trim() }); setEditId(null) }

  /* Drag-to-reorder */
  const handleDragStart = (e, id) => {
    setDragSrcId(id)
    e.dataTransfer.effectAllowed = 'move'
  }
  const handleDragEnter = (id) => {
    if (!dragSrcId || dragSrcId === id) return
    setDragTarget(id)
  }
  const handleDragEnd = () => { setDragSrcId(null); setDragTarget(null) }
  const handleItemDrop = (e, targetId) => {
    e.preventDefault()
    if (!dragSrcId || dragSrcId === targetId) { setDragSrcId(null); setDragTarget(null); return }
    setQueue(prev => {
      const src = prev.findIndex(i => i.id === dragSrcId)
      const dst = prev.findIndex(i => i.id === targetId)
      if (src === -1 || dst === -1) return prev
      const next = [...prev]
      next.splice(dst, 0, next.splice(src, 1)[0])
      return next
    })
    setDragSrcId(null)
    setDragTarget(null)
  }

  const doneCount    = queue.filter(i => i.status === 'done').length
  const pendingCount = queue.filter(i => i.status === 'queued' || i.status === 'error').length
  const hasQueue     = queue.length > 0

  return (
    <div data-theme={theme} dir={lang === 'ar' ? 'rtl' : 'ltr'}>
      <div className="bg-mesh"/>
      <div className="app-wrap">

        {/* ── Nav ──────────────────────────────────────────────────────────── */}
        <nav className="nav">
          <div className="container">
            <div className="nav-inner">
              <div className="nav-brand">
                <div className="brand-icon"><BookOpen size={18} color="#fff"/></div>
                {t.brand}
              </div>
              <div className="nav-controls">
                {ollama === null
                  ? <div className="ctrl-btn"><Loader2 size={13} className="spin"/>Checking…</div>
                  : ollama.ollama
                  ? <div className="ctrl-btn active"><Cpu size={13}/>{ollama.model || 'Ollama'}</div>
                  : <div className="ctrl-btn" style={{borderColor:'#f74f4f',color:'#f74f4f'}}><WifiOff size={13}/>Offline</div>
                }
                {history.length > 0 && (
                  <button className={`ctrl-btn${showHist ? ' active' : ''}`} onClick={() => setShowHist(p => !p)}>
                    <History size={14}/>{history.length}
                  </button>
                )}
                <button className={`ctrl-btn${showTimer ? ' active' : ''}`} onClick={() => setShowTimer(p => !p)}>
                  <Clock size={14}/>
                </button>
                <button className="ctrl-btn" onClick={() => setLang(p => p === 'en' ? 'ar' : 'en')}>
                  <Globe size={14}/>{lang === 'en' ? 'عربي' : 'EN'}
                </button>
                <button className="ctrl-btn" onClick={() => setTheme(p => p === 'dark' ? 'light' : 'dark')}>
                  {theme === 'dark' ? <Sun size={14}/> : <Moon size={14}/>}
                </button>
              </div>
            </div>
          </div>
        </nav>

        <main className="main">
          <div className="container">

            {/* Ollama warning */}
            {ollama && !ollama.ollama && (
              <div className="glass error-card" style={{marginBottom:'1.25rem'}}>
                <WifiOff size={20} className="error-icon"/>
                <div>
                  <div className="error-msg">{t.ollamaOff}</div>
                  <div className="error-sub">{t.ollamaOffSub}</div>
                </div>
              </div>
            )}

            {/* History panel */}
            {showHist && history.length > 0 && (
              <div className="glass" style={{marginBottom:'1.25rem',overflow:'hidden'}}>
                <div style={{padding:'0.7rem 1.1rem',background:'var(--glass-light)',
                  borderBottom:'1px solid var(--glass-border)',fontWeight:600,fontSize:'0.88rem',
                  color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
                  <History size={14}/>{t.histTitle}
                </div>
                {history.map(h => (
                  <div key={h.id} style={{display:'flex',alignItems:'center',gap:'0.75rem',
                    padding:'0.65rem 1.1rem',borderBottom:'1px solid var(--glass-border)'}}>
                    <FileText size={14} style={{color:'var(--accent)',flexShrink:0}}/>
                    <div style={{flex:1,fontSize:'0.85rem',color:'var(--text-primary)',
                      overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{h.name}</div>
                    {h.stats && (
                      <div style={{fontSize:'0.75rem',color:'var(--text-muted)',flexShrink:0}}>
                        {h.stats.sections}s · {h.stats.keywords}kw · {h.stats.flashcards}fc
                      </div>
                    )}
                    <a href={h.pdfUrl} download={h.name+'_study_guide.pdf'}
                      style={{display:'flex',alignItems:'center',gap:'0.3rem',
                        padding:'0.3rem 0.7rem',borderRadius:6,
                        background:'rgba(79,142,247,.12)',border:'1px solid rgba(79,142,247,.3)',
                        color:'var(--accent)',fontSize:'0.78rem',textDecoration:'none',flexShrink:0}}>
                      <Download size={11}/>PDF
                    </a>
                  </div>
                ))}
              </div>
            )}

            {/* Hero */}
            <div className="hero">
              <div className="hero-badge"><Sparkles size={12}/>{t.badge}</div>
              <h1>{t.h1a} <span>{t.h1b}</span></h1>
              <p>{t.sub}</p>
            </div>

            {/* Upload card */}
            <div className="glass upload-card">
              <div
                className={`drop-zone${drag ? ' drag-over' : ''}`}
                onDrop={onDrop}
                onDragOver={e => { e.preventDefault(); if (!dragSrcId) setDrag(true) }}
                onDragLeave={() => setDrag(false)}
                onClick={() => inputRef.current?.click()}
              >
                <input ref={inputRef} type="file" accept=".pptx,.ppt,.pdf" multiple
                  onChange={e => addFiles(e.target.files)} style={{display:'none'}}/>
                <div className="drop-icon"><Upload size={22}/></div>
                <div className="drop-title">{t.drop}</div>
                <div className="drop-sub">{t.dropSub}</div>
              </div>

              {/* Detail level selector */}
              <div style={{display:'flex',gap:'0.5rem',marginTop:'1rem',justifyContent:'center'}}>
                {['brief','standard','detailed'].map(d => (
                  <button key={d}
                    className={`detail-tab${detailLevel === d ? ' active' : ''}`}
                    onClick={() => setDetailLevel(d)}>
                    {d === 'brief' && <Zap size={12}/>}
                    {d === 'standard' && <Layers size={12}/>}
                    {d === 'detailed' && <Sparkles size={12}/>}
                    {t[d]}
                  </button>
                ))}
              </div>

              <div className="options-row" style={{marginTop:'0.85rem'}}>
                <select className="lang-select" value={lang} onChange={e => setLang(e.target.value)}>
                  <option value="en">{t.langEn}</option>
                  <option value="ar">{t.langAr}</option>
                </select>
                {hasQueue && (
                  <button className="submit-btn"
                    disabled={running || !pendingCount || (ollama && !ollama.ollama)}
                    onClick={processAll}>
                    {running
                      ? <><Loader2 size={15} className="spin"/>{t.processing}</>
                      : <><Sparkles size={15}/>{pendingCount > 0 ? t.genN(pendingCount) : t.genAll}</>}
                  </button>
                )}
              </div>
            </div>

            {/* Queue */}
            {hasQueue && (
              <div className="glass" style={{marginTop:'1.1rem',overflow:'hidden'}}>
                <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',
                  padding:'0.8rem 1.1rem',borderBottom:'1px solid var(--glass-border)',
                  background:'var(--glass-light)'}}>
                  <div style={{display:'flex',alignItems:'center',gap:'0.5rem',
                    fontWeight:600,fontSize:'0.88rem',color:'var(--text-primary)'}}>
                    <Files size={15}/>
                    {queue.length} file{queue.length !== 1 ? 's' : ''}
                    {doneCount > 0 && (
                      <span style={{fontSize:'0.76rem',color:'#22c55e',fontWeight:500}}>· {doneCount} ready</span>
                    )}
                  </div>
                  <div style={{display:'flex',gap:'0.4rem',flexWrap:'wrap'}}>
                    {doneCount > 1 && (
                      <button className="ctrl-btn active" onClick={downloadZip} style={{fontSize:'0.76rem'}}>
                        <Archive size={11}/>{t.dlZip(doneCount)}
                      </button>
                    )}
                    <button className="ctrl-btn" onClick={() => inputRef.current?.click()} style={{fontSize:'0.76rem'}}>
                      <Upload size={11}/>{t.addMore}
                    </button>
                    <button className="ctrl-btn" onClick={clearAll} style={{fontSize:'0.76rem'}}>
                      <X size={11}/>{t.clearAll}
                    </button>
                  </div>
                </div>

                {queue.map((item, idx) => {
                  const sc        = SC[item.status]
                  const isEditing = editId === item.id
                  const isDragTgt = dragTarget === item.id
                  return (
                    <div key={item.id}
                      draggable={!running && item.status !== 'processing'}
                      onDragStart={e => handleDragStart(e, item.id)}
                      onDragEnter={() => handleDragEnter(item.id)}
                      onDragOver={e => { if (dragSrcId) e.preventDefault() }}
                      onDragEnd={handleDragEnd}
                      onDrop={e => handleItemDrop(e, item.id)}
                      style={{
                        padding:'0.75rem 1.1rem',
                        borderBottom: idx < queue.length - 1 ? '1px solid var(--glass-border)' : 'none',
                        background: isDragTgt ? 'rgba(79,142,247,0.08)' : idx % 2 === 0 ? 'transparent' : 'var(--glass-light)',
                        borderLeft: isDragTgt ? '3px solid var(--accent)' : '3px solid transparent',
                        transition: 'all 0.15s',
                        cursor: dragSrcId ? 'grabbing' : 'default',
                      }}>
                      <div style={{display:'flex',alignItems:'center',gap:'0.65rem'}}>

                        {/* Drag handle */}
                        <div style={{color:'var(--text-muted)',cursor:'grab',flexShrink:0,opacity:0.5}}>
                          <GripVertical size={15}/>
                        </div>

                        {/* Icon */}
                        <div style={{width:32,height:32,borderRadius:9,flexShrink:0,
                          background:'rgba(79,142,247,.1)',border:'1px solid rgba(79,142,247,.2)',
                          display:'flex',alignItems:'center',justifyContent:'center',color:'var(--accent)'}}>
                          {item.status === 'processing' ? <Loader2 size={14} className="spin"/>
                           : item.status === 'done'     ? <CheckCircle2 size={14} color="#22c55e"/>
                           : item.status === 'error'    ? <AlertCircle size={14} color="#ef4444"/>
                           : <FileText size={14}/>}
                        </div>

                        {/* Name */}
                        <div style={{flex:1,minWidth:0}}>
                          {isEditing ? (
                            <div style={{display:'flex',gap:'0.4rem',alignItems:'center'}}>
                              <input value={editVal} onChange={e => setEditVal(e.target.value)}
                                onKeyDown={e => { if (e.key === 'Enter') commitEdit(item.id); if (e.key === 'Escape') setEditId(null) }}
                                autoFocus
                                style={{flex:1,padding:'3px 8px',borderRadius:6,fontSize:'0.85rem',
                                  border:'1px solid var(--accent)',background:'var(--glass-light)',
                                  color:'var(--text-primary)',fontFamily:'inherit',outline:'none'}}/>
                              <button onClick={() => commitEdit(item.id)}
                                style={{background:'none',border:'none',cursor:'pointer',color:'#22c55e',padding:2}}>
                                <Check size={14}/>
                              </button>
                              <button onClick={() => setEditId(null)}
                                style={{background:'none',border:'none',cursor:'pointer',color:'var(--text-muted)',padding:2}}>
                                <X size={14}/>
                              </button>
                            </div>
                          ) : (
                            <div style={{display:'flex',alignItems:'center',gap:'0.4rem'}}>
                              <span style={{fontSize:'0.87rem',fontWeight:500,color:'var(--text-primary)',
                                overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                                {item.name}
                              </span>
                              {!running && (
                                <button onClick={() => startEdit(item)}
                                  style={{background:'none',border:'none',cursor:'pointer',
                                    color:'var(--text-muted)',padding:'1px 3px',flexShrink:0,opacity:0.6}}>
                                  <Pencil size={11}/>
                                </button>
                              )}
                            </div>
                          )}

                          {item.status === 'processing' && item.stepMsg && (
                            <div style={{fontSize:'0.75rem',color:'var(--accent)',marginTop:2,
                              display:'flex',alignItems:'center',gap:'0.3rem'}}>
                              <ChevronRight size={11}/>{item.stepMsg}
                            </div>
                          )}
                          {item.status === 'error' && (
                            <div style={{fontSize:'0.75rem',color:'#ef4444',marginTop:2}}>{item.error}</div>
                          )}
                          {item.status === 'done' && item.stats && (
                            <div style={{fontSize:'0.73rem',color:'var(--text-muted)',marginTop:2}}>
                              {item.stats.sections}sec · {item.stats.keywords}kw · {item.stats.flashcards}fc · {item.stats.mcqs}mcq
                            </div>
                          )}
                        </div>

                        {/* Status badge */}
                        <div style={{padding:'3px 9px',borderRadius:50,fontSize:'0.73rem',fontWeight:600,
                          background:sc.bg,color:sc.color,border:`1px solid ${sc.border}`,
                          flexShrink:0,whiteSpace:'nowrap'}}>
                          {t.status[item.status]}
                        </div>

                        {/* Quick actions */}
                        <div style={{display:'flex',gap:'0.3rem',flexShrink:0}}>
                          {item.status === 'error' && !running && (
                            <button className="ctrl-btn" onClick={() => upd(item.id, { status:'queued', error:null })}
                              style={{fontSize:'0.76rem'}}>
                              <RotateCcw size={11}/>{t.retry}
                            </button>
                          )}
                          {!running && (
                            <button className="ctrl-btn" onClick={() => removeItem(item.id)}
                              style={{padding:'0.38rem 0.5rem'}}>
                              <X size={12}/>
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Progress bar */}
                      {item.status === 'processing' && (
                        <div style={{marginTop:'0.5rem',height:3,borderRadius:99,
                          background:'var(--glass-border)',overflow:'hidden'}}>
                          <div style={{height:'100%',borderRadius:99,
                            background:'linear-gradient(90deg,var(--accent),#a78bfa)',
                            animation:'indeterminate 1.8s ease infinite'}}/>
                        </div>
                      )}

                      {/* Done actions row */}
                      {item.status === 'done' && (
                        <div style={{display:'flex',gap:'0.4rem',marginTop:'0.6rem',flexWrap:'wrap'}}>
                          <button className="download-btn" onClick={() => downloadItem(item)}
                            style={{padding:'0.35rem 0.85rem',fontSize:'0.78rem',marginBottom:0}}>
                            <Download size={12}/>{t.download}
                          </button>
                          <button className="ctrl-btn" onClick={() => downloadMd(item)}
                            style={{fontSize:'0.76rem'}}>
                            <FileText size={12}/>{t.dlMd}
                          </button>
                          <button className="ctrl-btn"
                            onClick={() => window.open(`/api/view/md/${item.jobId}`, '_blank')}
                            style={{fontSize:'0.76rem'}}>
                            <FileText size={12}/>View MD
                          </button>
                          <button className="ctrl-btn"
                            onClick={() => setFlashModal({ jobId: item.jobId, title: item.name })}
                            style={{fontSize:'0.76rem'}}>
                            <Layers size={12}/>{t.cards}
                          </button>
                          <button className="ctrl-btn"
                            onClick={() => setQuizModal({ jobId: item.jobId, title: item.name })}
                            style={{fontSize:'0.76rem'}}>
                            <HelpCircle size={12}/>{t.quiz}
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
                  <div className="info-pill" key={p}><CheckCircle2 size={11}/>{p}</div>
                ))}
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Modals */}
      {showTimer  && <PomodoroTimer t={t} onClose={() => setShowTimer(false)}/>}
      {flashModal && <FlashCardModal {...flashModal} lang={lang} t={t} onClose={() => setFlashModal(null)}/>}
      {quizModal  && <QuizModal  {...quizModal}  lang={lang} t={t} onClose={() => setQuizModal(null)}/>}

      <style>{`
        @keyframes indeterminate {
          0%   { transform:translateX(-100%); width:55%; }
          100% { transform:translateX(200%);  width:55%; }
        }
      `}</style>
    </div>
  )
}
