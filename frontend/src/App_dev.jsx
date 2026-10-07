import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { createClient } from '@supabase/supabase-js'
import {
  Sun, Moon, Upload, FileText, Download,
  Loader2, CheckCircle2, AlertCircle, Sparkles, RotateCcw,
  Globe, X, Files, ChevronDown,
  Youtube, Type, Brain, BarChart2, Map, Printer,
  ThumbsUp, ThumbsDown, MessageSquare, History, ClipboardList, ShieldCheck, ScrollText,
  LogIn, LogOut, User, Zap, Copy, Gift, Mail, Share2, Check
} from 'lucide-react'

// Alimne brand mark — the "A + spark" glyph (white, for use inside a gradient tile)
const AlimneGlyph = ({ size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 96 96" fill="none" aria-hidden="true">
    <path d="M31 69 L48 27 L65 69" fill="none" stroke="#fff" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M39.5 55 H56.5" stroke="#fff" strokeWidth="8" strokeLinecap="round"/>
    <path d="M71 24 l2.4 6 6 2.4 -6 2.4 -2.4 6 -2.4 -6 -6 -2.4 6 -2.4 Z" fill="#fff"/>
  </svg>
)

// "your free guides, the three of them" in Arabic: the count in words up to ten, as the server writes it
const AR_THE_COUNT = { 3: 'الثلاثة', 4: 'الأربعة', 5: 'الخمسة', 6: 'الستة', 7: 'السبعة', 8: 'الثمانية', 9: 'التسعة', 10: 'العشرة' }

const T = {
  en: {
    brand: 'Alimne',
    badge: 'AI-Powered · Smart Study',
    h1a: 'Turn any lecture into',
    h1b: 'Study Guides',
    sub: 'Drop a PowerPoint, PDF, or YouTube lecture — get an exam-ready guide with notes, flashcards, and a practice quiz in seconds.',
    // n = the guides an anonymous visitor may make before a free account is required (from /api/config).
    // 0 is a real answer (the owner asks for an account from the first guide): then no number is promised.
    heroFree: (n) => n === 0 ? 'Free. No card. A free account is needed to make guides.'
      : n === 1 ? 'Free. No card. Your first guide needs no account.' : `Free. No card. Your first ${n} guides need no account.`,
    dropTitle: 'Drop your PowerPoint or PDF files here',
    dropSub: 'or click to browse — .pptx / .ppt / .pdf / .docx / .doc / .txt, multiple files supported',
    dropFree: (n) => n === 0 ? 'Free · a free account is needed to make guides' : `Free · ${n === 1 ? '1 guide' : `${n} guides`} without an account · then a free sign-in`,
    dropFreeUser: 'Free to use · fair-use daily limits apply',
    footerFree: 'Free to use · Files deleted automatically',
    langAuto: 'Auto-detect language',
    langEn: 'English output',
    langAr: 'Arabic output (عربي)',
    // The server keeps files in memory only. One thing does touch the visitor's own disk, and the line says so: a file
    // or text still waiting when the page leaves for Google sign-in is kept in THIS browser until they are back.
    privacy: 'Your files are processed in server memory only — never written to our disks or seen by anyone. The server wipes everything automatically within 15 minutes; this tab keeps a copy of your guide until you close it, remove it or tap Delete now. If you leave to sign in with Google, a file or text still waiting is kept in your own browser only (never uploaded early) so it is there when you return. Flash-card progress is saved on this device.',
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
    loginSub: 'Sign in to your account',
    loginBtn: 'Continue with Google',
    emailPh: 'you@email.com',
    passwordPh: 'Password (min 6 characters)',
    emailBtn: 'Continue with email',
    orDivider: 'or',
    authWeak: 'Enter a valid email and a password of at least 6 characters.',
    authCheckEmail: 'Account created \u2014 check your email to confirm, then sign in.',
    authError: 'Sign-in failed \u2014 please try again.',
    signIn: 'Sign in',
    signOut: 'Sign out',
    accountTitle: 'Your account',
    accountPlan: 'Plan',
    planPro: 'Alimne Pro',
    planFree: 'Free',
    accountStatus: 'Status',
    statusActive: 'Active',
    statusCanceled: 'Canceled',
    statusPastDue: 'Payment issue',
    renewsOn: 'Renews on',
    accountAllowance: 'Daily allowance',
    accountPerDay: (n) => `Up to ${n} guides a day (fair use)`,
    accountFreeNote: 'Alimne is free for everyone now, so you no longer need a paid plan. You can cancel your subscription below at any time.',
    manageNote: "Update your card, see invoices, or cancel your subscription on Stripe's secure billing page.",
    subSuccess: 'Payment received — activating Alimne Pro…',
    manageBtn: 'Manage / cancel subscription',
    freeNow: 'Alimne is free now — no subscription needed.',
    loginTitleSignup: 'Create your account',
    loginSubSignup: 'Free, no card needed — create your account in a minute.',
    emailBtnSignup: 'Create free account',
    noAccount: 'New here? Create a free account',
    haveAccount: 'Already have an account? Sign in',
    wrongPassword: 'Incorrect email or password. Signed up with Google? Use Continue with Google.',
    accountExists: 'An account already exists for this email. Sign in instead.',
    signInFreeCta: 'Sign in free',
    emailInvalid: 'Please enter a valid email address.',
    // Sign-in gate: an anonymous device may make N guides, then a free account is required to make more.
    // The nav counter, the notice in the sign-in modal, the held item, and the toast after signing in.
    anonLeft: (n) => n === 1 ? '1 free guide left' : `${n} free guides left`,
    anonNone: 'Sign in to continue — free',
    // WHY a free account is asked for: three causes, three true texts (the same three the server sends), one call
    // to action. Only the first is about what THIS visitor did, so only it may say "you've used your N free guides".
    signinRequired: (n) => n === 0 ? "Create a free account to make study guides — it's free." : `You've used your ${n === 1 ? 'free guide' : `${n} free guides`}. Create a free account to keep going — it's still free.`,
    signinNetwork: "Today's free guides without an account are used up on your network. Create a free account to keep going — it's still free.",
    signinPool: "Today's free guides without an account are used up. Create a free account to keep going — it's still free.",
    signInToContinue: 'Sign in to continue (free)',
    gateCleared: "You're signed in — you can keep making guides now.",
    // Back from Google sign-in with what was waiting (k = 'file' | 'files' | 'text' | 'link', else several kinds)
    stashReady: (k) => "You're signed in. " + ({ file: 'Your file is ready', files: 'Your files are ready', text: 'Your text is ready', link: 'Your link is ready' }[k] || 'Your items are ready') + ' — tap Generate.',
    stashMissing: (n) => n === 1 ? 'One file could not be kept — please choose it again.' : `${n} files could not be kept — please choose them again.`,
    generateNow: 'Generate',
    // Why sign in (shown in the sign-in modal and in the card after a visitor's first guide).
    // Only real features: more guides (the account's daily fair-use allowance), Chat (needs an account), the invite link.
    perks: (f) => `more guides${f ? ` (up to ${f.user_daily} a day, fair use)` : ''}, chat with your guide, and a link to invite friends`,
    perksNote: (c) => `With a free account you get ${c}.`,
    joinTitle: 'Create a free account',
    // limit 0 = an account is asked for from the very first guide, so nothing was "used"
    joinBody: (c, left, limit) => `${left > 0 ? `You have ${left === 1 ? '1 free guide' : `${left} free guides`} left without an account. ` : limit === 0 ? '' : "You've used your free guides. "}A free account gets you ${c}.`,
    // Invite a friend (plain share link — no rewards)
    referTitle: 'Invite a friend',
    referSub: "Know someone who could use Alimne? Share your link — it's free for them too.",
    referCopy: 'Copy link',
    referCopied: 'Copied!',
    referJoined: (n) => n > 0 ? `${n} friend${n > 1 ? 's' : ''} joined` : 'No friends joined yet',
    // Share
    share: 'Share',
    shareCopy: 'Copy',
    shareTitle: 'Get a public link to this guide',
    shareCopied: 'Public link copied — anyone can open it',
    shareFailed: 'Could not create a share link. Try again.',
    shareNote: 'public link',
    // Instant demo
    sampleCta: 'See it work — try a sample lecture',
    sampleCtaSub: 'No file needed. Watch a real study guide build in seconds.',
    sampleName: 'Sample lecture: Photosynthesis',
    sampleMsg: 'Building your sample guide…',
    sampleOr: 'or use your own below',
    // Landing proof / sample output
    sampleTitle: 'See what you get',
    sampleSub: "Every upload becomes a clean study guide — key points, flashcards, and a quiz you can actually revise from. Here's a real example.",
    steps: [
      { t: 'Upload a lecture', s: 'PowerPoint, PDF, or a YouTube link' },
      { t: 'AI reads & organizes', s: 'Pulls out what actually matters' },
      { t: 'Study smarter', s: 'Notes, flashcards & a quiz — download as PDF' },
    ],
    sampleTag: 'EXAMPLE OUTPUT',
    sampleGuideTitle: 'The Cell Cycle',
    sampleKeyLabel: 'Key points',
    sampleKey: [
      'Two main phases: interphase (growth) and the mitotic (M) phase (division).',
      'Interphase order: G1 (growth) → S (DNA replication) → G2 (prep for mitosis).',
      'Checkpoints (G1, G2, M) halt the cycle if something is wrong — preventing errors like cancer.',
    ],
    sampleFlashLabel: 'Flashcards',
    sampleFlash: [
      { q: 'In which phase is DNA copied?', a: 'S phase' },
      { q: 'What do checkpoints do?', a: 'Halt the cycle to catch and fix errors before the cell divides' },
    ],
    sampleQuizLabel: 'Quiz',
    sampleQuizQ: 'What is the correct order of interphase?',
    sampleQuizOpts: ['G1 → S → G2', 'S → G1 → G2', 'G2 → S → G1'],
    sampleQuizAnswer: 0,
    trust: ['Free · no card needed', 'Files wiped in 15 min', 'English & العربية'],
    // Status / recovery
    expired: 'Expired',
    expiredNote: 'Expired on the server — guides are kept for 15 minutes.',
    restore: 'Restore (free)',
    regenerate: 'Regenerate',
    retry: 'Retry',
    queuePos: (n) => `You are in line — position ${n}`,
    queueWait: 'You are in line — starting soon',
    reselectFile: 'Re-select your file to generate it again.',
    repasteText: 'Paste your text again to regenerate it.',
    partialNote: "Some flashcards or quiz questions couldn't be generated.",
    restored: 'Guide restored',
    restoreFailed: "Couldn't restore this guide — try again, or regenerate it.",
    guideExpired: 'This guide expired on the server.',
    guideExpiredLong: 'This guide expired on the server (guides are kept for 15 minutes). Restore or regenerate it to keep studying.',
    loadFailed: "Couldn't load this guide — check your connection.",
    inAppBanner: 'Downloads may not work inside Instagram/TikTok — open alimne.app in Safari/Chrome (⋯ → Open in browser).',
    items: (n) => `${n} item${n !== 1 ? 's' : ''}`,
    readyCount: (n) => `${n} ready`,
    starting: 'Starting…',
    fetchingTranscript: 'Fetching transcript…',
    processingText: 'Processing text…',
    // Action bar + toasts
    pdf: 'PDF', anki: 'Anki', deleteNow: 'Delete now', cards: 'Cards', quiz: 'Quiz',
    overview: 'Overview', print: 'Print', chat: 'Chat',
    ankiTip: 'Export Anki CSV', deleteTip: 'Delete my data from the server now', cardsTip: 'Flash Cards',
    quizTip: 'Quiz', overviewTip: 'Overview', printTip: 'Print / View', chatTip: 'Ask the guide',
    pdfSaved: 'PDF saved',
    ankiSaved: 'Anki CSV saved',
    openingDownload: 'Starting download… If nothing happens, open alimne.app in Safari or Chrome.',
    noFlashcards: 'This guide has no flashcards.',
    downloadFailed: 'Download failed — check your connection and try again.',
    slowNetwork: 'This is taking too long — check your connection and try again.',
    popupBlocked: 'Allow pop-ups to open the print view.',
    deleted: 'Your data was deleted from the server.',
    deleteFailed: 'Could not delete — it is auto-wiped within 15 minutes.',
    paymentError: 'Payment error — please try again.',
    billingError: 'Billing error — please try again.',
    // Errors
    errNetwork: 'Connection lost — check your internet and tap Retry.',
    streamLost: 'Connection lost before your guide finished — tap Retry.',
    errTooBig: 'File is over 50 MB — compress or split it.',
    errRateLimit: 'Too many requests — please wait a minute and try again.',
    errUpdating: 'Alimne is updating — try again in a minute.',
    errRetry: 'Temporary problem — please try again in a moment.',
    errGeneric: 'Something went wrong — please try again.',
    errNoNotes: "The AI couldn't build notes right now — please try again.",
    // Fair use / capacity (free mode). The anonymous allowance is the sign-in gate above (signinRequired).
    errFairIp: "Lots of students are using Alimne from your network today, so it's paused here for now — please try again later.",
    errFairUser: "You've reached today's fair-use limit. It refills within 24 hours — please try again later.",
    errBusyToday: 'Alimne is very popular today — please try again later.',
    errBusy: 'Many students are generating right now — tap Retry in a minute.',
    errYtBlocked: 'YouTube blocked this video — try one with captions, or paste the transcript in the "Paste Text / URL" tab.',
    fileTooBig: (n) => `${n} is over 50 MB — compress or split it.`,
    maxFiles: 'You can process up to 3 files at a time.',
    unsupportedFile: 'Unsupported file — use .pptx, .ppt, .pdf, .docx, .doc or .txt.',
    // Auth (login modal, session, account)
    close: 'Close',
    sessionExpired: 'Your session expired — please sign in again.',
    linkExpired: 'That link has expired or was already used. If you just signed up, your email may already be confirmed — try signing in with your password, or request a new link.',
    authLinkError: "Sign-in didn't complete — please try again.",
    authUnavailable: 'Sign-in is unavailable right now — please reload the page.',
    authTimeout: 'This is taking too long — check your connection and try again.',
    emailNotConfirmed: 'Please confirm your email first — check your inbox for our link.',
    resendConfirm: 'Resend confirmation email',
    resent: 'Sent — check your inbox (and spam folder).',
    emailRateLimit: 'Too many emails sent — please wait a few minutes and try again.',
    authRateLimit: 'Too many attempts — please wait a minute and try again.',
    weakPassword: 'That password is too weak — use at least 6 characters, mixing letters and numbers.',
    samePassword: 'Choose a password different from your old one.',
    forgotPw: 'Forgot password?',
    resetSent: (e) => `Password reset link sent to ${e} — check your inbox.`,
    enterEmailFirst: 'Enter your email above first.',
    checkInboxTitle: 'Check your inbox',
    checkInbox: (e) => `We sent a confirmation link to ${e}. Open it on this device to finish signing up.`,
    resendEmail: 'Resend email',
    backToSignIn: 'Back to sign in',
    inAppGoogle: "Google sign-in doesn't work inside this app. Open alimne.app in Safari/Chrome (⋯ → Open in browser), or use email below.",
    copyLink: 'Copy link',
    newPwTitle: 'Set a new password',
    newPwSub: 'Choose a new password for your account.',
    newPwPh: 'New password (min 6 characters)',
    newPwBtn: 'Save password',
    pwUpdated: 'Password updated — you are signed in.',
    pwTooShort: 'Use at least 6 characters.',
    accountLoadFailed: "Couldn't load your account.",
    // Chat
    chatTitle: 'Ask the Guide',
    chatIntro: 'Ask me anything — definitions, hints, explanations, key points.',
    chatPh: 'Ask a question…',
    chatSend: 'Send',
    chatSuggest: ['Summarize the key points', 'What are the main topics?', 'What should I focus on for the exam?', 'Give me the most important definitions'],
    chatSignIn: 'Sign in to chat with your guide',
    chatNoAnswer: 'No answer — please try again.',
  },
  ar: {
    brand: 'علّمني',
    badge: 'ذكاء اصطناعي · دراسة ذكية',
    h1a: 'حوّل أي محاضرة إلى',
    h1b: 'أدلة دراسة',
    sub: 'ارفع عرضاً تقديمياً أو PDF أو رابط محاضرة من YouTube — واحصل على دليل جاهز للامتحان مع ملخص وبطاقات وأسئلة مراجعة خلال ثوانٍ.',
    heroFree: (n) => n === 0 ? 'مجاني. بدون بطاقة. يلزم حساب مجاني لإنشاء الأدلة.'
      : n === 1 ? 'مجاني. بدون بطاقة. دليلك الأول لا يحتاج إلى حساب.' : n === 2 ? 'مجاني. بدون بطاقة. أول دليلين لا يحتاجان إلى حساب.'
      : `مجاني. بدون بطاقة. أول ${n} ${n <= 10 ? 'أدلة' : 'دليلاً'} لا تحتاج إلى حساب.`,
    dropTitle: 'أسقط ملفات PowerPoint أو PDF هنا',
    dropSub: 'أو انقر للتصفح — .pptx / .ppt / .pdf / .docx / .doc / .txt، يدعم ملفات متعددة',
    dropFree: (n) => n === 0 ? 'مجاني · يلزم حساب مجاني لإنشاء الأدلة' : `مجاني · ${n === 1 ? 'دليل واحد' : n === 2 ? 'دليلان' : n <= 10 ? `${n} أدلة` : `${n} دليلاً`} دون حساب · ثم تسجيل دخول مجاني`,
    dropFreeUser: 'مجاني للاستخدام · تُطبَّق حدود يومية للاستخدام العادل',
    footerFree: 'مجاني للاستخدام · تُحذف الملفات تلقائياً',
    langAuto: 'اكتشاف اللغة تلقائياً',
    langEn: 'الإخراج بالإنجليزية',
    langAr: 'الإخراج بالعربية',
    privacy: 'ملفاتك تُعالَج في ذاكرة الخادم فقط — لا تُكتب على أقراصنا ولا يراها أحد. يمسح الخادم كل شيء تلقائياً خلال 15 دقيقة، وتحتفظ هذه النافذة بنسخة من دليلك حتى تغلقها أو تزيله أو تضغط «احذف الآن». وإذا غادرت الصفحة لتسجيل الدخول عبر Google، يبقى الملف أو النص الذي ينتظر محفوظاً في متصفحك فقط (دون رفعه مسبقاً) ليكون موجوداً عند عودتك. ويُحفظ تقدّمك في البطاقات على هذا الجهاز.',
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
    loginSub: 'سجّل الدخول إلى حسابك',
    loginBtn: 'المتابعة عبر Google',
    emailPh: 'you@email.com',
    passwordPh: 'كلمة المرور (6 أحرف على الأقل)',
    emailBtn: 'المتابعة بالبريد',
    orDivider: 'أو',
    authWeak: 'أدخل بريداً صحيحاً وكلمة مرور من 6 أحرف على الأقل.',
    authCheckEmail: 'تم إنشاء الحساب — تحقق من بريدك للتأكيد ثم سجّل الدخول.',
    authError: 'فشل تسجيل الدخول — حاول مجدداً.',
    signIn: 'تسجيل الدخول',
    signOut: 'تسجيل الخروج',
    accountTitle: 'حسابك',
    accountPlan: 'الباقة',
    planPro: 'Alimne Pro',
    planFree: 'مجانية',
    accountStatus: 'الحالة',
    statusActive: 'فعّال',
    statusCanceled: 'ملغى',
    statusPastDue: 'مشكلة في الدفع',
    renewsOn: 'يتجدد في',
    accountAllowance: 'الحدّ اليومي',
    accountPerDay: (n) => n === 1 ? 'حتى دليل واحد في اليوم (استخدام عادل)' : n === 2 ? 'حتى دليلين في اليوم (استخدام عادل)'
      : `حتى ${n} ${n <= 10 ? 'أدلة' : 'دليلاً'} في اليوم (استخدام عادل)`,
    accountFreeNote: 'أصبح علّمني مجانياً للجميع، فلم تعد بحاجة إلى خطة مدفوعة. يمكنك إلغاء اشتراكك أدناه في أي وقت.',
    manageNote: 'حدّث بطاقتك، أو اطّلع على الفواتير، أو ألغِ اشتراكك من صفحة الفوترة الآمنة في Stripe.',
    subSuccess: 'تم استلام الدفع — جارٍ تفعيل Alimne Pro…',
    manageBtn: 'إدارة / إلغاء الاشتراك',
    freeNow: 'علّمني مجاني الآن — لا حاجة إلى اشتراك.',
    loginTitleSignup: 'أنشئ حسابك',
    loginSubSignup: 'مجاني وبدون بطاقة — أنشئ حسابك خلال دقيقة.',
    emailBtnSignup: 'إنشاء حساب مجاني',
    noAccount: 'جديد هنا؟ أنشئ حساباً مجانياً',
    haveAccount: 'لديك حساب بالفعل؟ سجّل الدخول',
    wrongPassword: 'البريد أو كلمة المرور غير صحيحة. سجّلت عبر Google؟ استخدم «المتابعة عبر Google».',
    accountExists: 'يوجد حساب بهذا البريد بالفعل. سجّل الدخول بدلاً من ذلك.',
    signInFreeCta: 'سجّل الدخول مجاناً',
    emailInvalid: 'يرجى إدخال بريد إلكتروني صحيح.',
    // بوابة تسجيل الدخول: عدد من الأدلة للزائر، ثم يلزم حساب مجاني لإنشاء المزيد
    anonLeft: (n) => n === 1 ? 'بقي لك دليل مجاني واحد' : n === 2 ? 'بقي لك دليلان مجانيان' : n <= 10 ? `بقي لك ${n} أدلة مجانية` : `بقي لك ${n} دليلاً مجانياً`,
    anonNone: 'سجّل الدخول للمتابعة — مجاناً',
    // سبب طلب الحساب: ثلاثة أسباب وثلاثة نصوص صادقة (هي نفسها التي يرسلها الخادم) ودعوة واحدة في آخرها
    signinRequired: (n) => n === 0 ? 'أنشئ حساباً مجانياً لإنشاء أدلة الدراسة — الاستخدام مجاني.' : `لقد استخدمت ${n === 1 ? 'دليلك المجاني' : n === 2 ? 'دليلَيك المجانيَّين' : `أدلتك المجانية ${AR_THE_COUNT[n] || `الـ${n}`}`}. أنشئ حساباً مجانياً للمتابعة — ما زال الاستخدام مجانياً.`,
    signinNetwork: 'استُنفدت اليوم الأدلة المجانية المتاحة على شبكتك دون حساب. أنشئ حساباً مجانياً للمتابعة — ما زال الاستخدام مجانياً.',
    signinPool: 'استُنفدت اليوم الأدلة المجانية المتاحة دون حساب. أنشئ حساباً مجانياً للمتابعة — ما زال الاستخدام مجانياً.',
    signInToContinue: 'سجّل الدخول للمتابعة (مجاناً)',
    gateCleared: 'تم تسجيل الدخول — يمكنك الآن متابعة إنشاء الأدلة.',
    stashReady: (k) => 'تم تسجيل الدخول. ' + ({ file: 'ملفك جاهز', files: 'ملفاتك جاهزة', text: 'نصّك جاهز', link: 'رابطك جاهز' }[k] || 'عناصرك جاهزة') + ' — اضغط «توليد».',
    stashMissing: (n) => n === 1 ? 'تعذّر الاحتفاظ بملف واحد — يُرجى اختياره مرة أخرى.' : n === 2 ? 'تعذّر الاحتفاظ بملفين — يُرجى اختيارهما مرة أخرى.' : `تعذّر الاحتفاظ بـ${n} ${n >= 3 && n <= 10 ? 'ملفات' : 'ملفاً'} — يُرجى اختيارها مرة أخرى.`,
    generateNow: 'توليد',
    perks: (f) => `المزيد من الأدلة${f ? ` (حتى ${f.user_daily} ${f.user_daily <= 10 ? 'أدلة' : 'دليلاً'} في اليوم ضمن الاستخدام العادل)` : ''}، والدردشة مع دليلك، ورابط لدعوة أصدقائك`,
    perksNote: (c) => `بحساب مجاني تحصل على ${c}.`,
    joinTitle: 'أنشئ حساباً مجانياً',
    joinBody: (c, left, limit) => `${left > 0 ? `بقي لك ${left === 1 ? 'دليل مجاني واحد' : left === 2 ? 'دليلان مجانيان' : left <= 10 ? `${left} أدلة مجانية` : `${left} دليلاً مجانياً`} دون حساب. ` : limit === 0 ? '' : 'استخدمت أدلتك المجانية. '}بحساب مجاني تحصل على ${c}.`,
    // ادعُ صديقاً (رابط مشاركة فقط — بلا مكافآت)
    referTitle: 'ادعُ صديقاً',
    referSub: 'تعرف من قد يحتاج علّمني؟ شارك رابطك — فهو مجاني لهم أيضاً.',
    referCopy: 'نسخ الرابط',
    referCopied: 'تم النسخ!',
    referJoined: (n) => n === 0 ? 'لم ينضم أحد بعد' : n === 1 ? 'انضم صديق واحد' : n === 2 ? 'انضم صديقان' : n <= 10 ? `انضم ${n} أصدقاء` : `انضم ${n} صديقاً`,
    // Share
    share: 'مشاركة',
    shareCopy: 'نسخ',
    shareTitle: 'احصل على رابط عام لهذا الدليل',
    shareCopied: 'تم نسخ الرابط العام — يمكن لأي شخص فتحه',
    shareFailed: 'تعذّر إنشاء رابط المشاركة. حاول مرة أخرى.',
    shareNote: 'رابط عام',
    // Instant demo
    sampleCta: 'شاهدها تعمل — جرّب محاضرة نموذجية',
    sampleCtaSub: 'بدون ملف. شاهد إنشاء دليل دراسة حقيقي خلال ثوانٍ.',
    sampleName: 'محاضرة نموذجية: البناء الضوئي',
    sampleMsg: 'جارٍ إنشاء دليلك النموذجي…',
    sampleOr: 'أو استخدم ملفك بالأسفل',
    // Landing proof / sample output
    sampleTitle: 'شاهد ما ستحصل عليه',
    sampleSub: 'كل ملف يتحوّل إلى دليل مذاكرة منظّم — نقاط رئيسية وبطاقات وأسئلة تراجع منها فعلاً. إليك مثال حقيقي.',
    steps: [
      { t: 'ارفع محاضرة', s: 'عرض تقديمي أو PDF أو رابط YouTube' },
      { t: 'الذكاء الاصطناعي ينظّمها', s: 'يستخرج ما يهم فعلاً' },
      { t: 'ذاكِر بذكاء', s: 'ملخص وبطاقات واختبار — حمّلها PDF' },
    ],
    sampleTag: 'مثال على الإخراج',
    sampleGuideTitle: 'دورة الخلية',
    sampleKeyLabel: 'النقاط الرئيسية',
    sampleKey: [
      'طوران رئيسيان: الطور البيني (النمو) وطور الانقسام (M).',
      'ترتيب الطور البيني: G1 (نمو) ← S (تضاعف الحمض النووي) ← G2 (تحضير للانقسام).',
      'نقاط التفتيش (G1، G2، M) توقف الدورة عند وجود خطأ — لمنع أخطاء مثل السرطان.',
    ],
    sampleFlashLabel: 'بطاقات تعليمية',
    sampleFlash: [
      { q: 'في أي طور يُنسخ الحمض النووي؟', a: 'طور S' },
      { q: 'ما وظيفة نقاط التفتيش؟', a: 'إيقاف الدورة لاكتشاف الأخطاء وإصلاحها قبل انقسام الخلية' },
    ],
    sampleQuizLabel: 'اختبار',
    sampleQuizQ: 'ما الترتيب الصحيح للطور البيني؟',
    sampleQuizOpts: ['G1 ← S ← G2', 'S ← G1 ← G2', 'G2 ← S ← G1'],
    sampleQuizAnswer: 0,
    trust: ['مجاني · بدون بطاقة', 'تُمسح الملفات خلال 15 دقيقة', 'الإنجليزية والعربية'],
    // الحالة / الاستعادة
    expired: 'منتهي الصلاحية',
    expiredNote: 'انتهت صلاحيته على الخادم — تُحفظ الأدلة 15 دقيقة.',
    restore: 'استعادة (مجاناً)',
    regenerate: 'إعادة الإنشاء',
    retry: 'إعادة المحاولة',
    queuePos: (n) => `أنت في الطابور — الترتيب ${n}`,
    queueWait: 'أنت في الطابور — سنبدأ قريباً',
    reselectFile: 'اختر ملفك مجدداً لإعادة إنشائه.',
    repasteText: 'الصق النص مجدداً لإعادة إنشائه.',
    partialNote: 'تعذّر إنشاء بعض البطاقات أو أسئلة الاختبار.',
    restored: 'تمت استعادة الدليل',
    restoreFailed: 'تعذّرت استعادة الدليل — حاول مجدداً أو أعد إنشاءه.',
    guideExpired: 'انتهت صلاحية هذا الدليل على الخادم.',
    guideExpiredLong: 'انتهت صلاحية هذا الدليل على الخادم (تُحفظ الأدلة 15 دقيقة). استعِده أو أعد إنشاءه لمتابعة المذاكرة.',
    loadFailed: 'تعذّر تحميل الدليل — تحقّق من اتصالك.',
    inAppBanner: 'قد لا يعمل التحميل داخل Instagram/TikTok — افتح alimne.app في Safari أو Chrome (⋯ ← فتح في المتصفح).',
    items: (n) => n === 1 ? 'عنصر واحد' : n === 2 ? 'عنصران' : n <= 10 ? `${n} عناصر` : `${n} عنصراً`,
    readyCount: (n) => `${n} جاهز`,
    starting: 'جارٍ البدء…',
    fetchingTranscript: 'جارٍ جلب نص الفيديو…',
    processingText: 'جارٍ معالجة النص…',
    // شريط الإجراءات + الإشعارات
    pdf: 'PDF', anki: 'Anki', deleteNow: 'احذف الآن', cards: 'البطاقات', quiz: 'اختبار',
    overview: 'نظرة عامة', print: 'طباعة', chat: 'دردشة',
    ankiTip: 'تصدير ملف CSV لـ Anki', deleteTip: 'احذف بياناتي من الخادم الآن', cardsTip: 'بطاقات المراجعة',
    quizTip: 'اختبار', overviewTip: 'نظرة عامة', printTip: 'طباعة / عرض', chatTip: 'اسأل الدليل',
    pdfSaved: 'تم حفظ ملف PDF',
    ankiSaved: 'تم حفظ ملف Anki',
    openingDownload: 'جارٍ بدء التحميل… إن لم يحدث شيء، افتح alimne.app في Safari أو Chrome.',
    noFlashcards: 'لا يحتوي هذا الدليل على بطاقات.',
    downloadFailed: 'فشل التحميل — تحقّق من اتصالك وحاول مجدداً.',
    slowNetwork: 'يستغرق الأمر وقتاً طويلاً — تحقّق من اتصالك وحاول مجدداً.',
    popupBlocked: 'اسمح بالنوافذ المنبثقة لفتح صفحة الطباعة.',
    deleted: 'تم حذف بياناتك من الخادم.',
    deleteFailed: 'تعذّر الحذف — سيُمسح تلقائياً خلال 15 دقيقة.',
    paymentError: 'خطأ في الدفع — حاول مجدداً.',
    billingError: 'خطأ في الفوترة — حاول مجدداً.',
    // الأخطاء
    errNetwork: 'انقطع الاتصال — تحقّق من الإنترنت واضغط «إعادة المحاولة».',
    streamLost: 'انقطع الاتصال قبل اكتمال دليلك — اضغط «إعادة المحاولة».',
    errTooBig: 'حجم الملف أكبر من 50 ميغابايت — اضغطه أو قسّمه.',
    errRateLimit: 'طلبات كثيرة — انتظر دقيقة ثم حاول مجدداً.',
    errUpdating: 'يجري تحديث علّمني — حاول مجدداً بعد دقيقة.',
    errRetry: 'مشكلة مؤقتة — حاول مجدداً بعد لحظات.',
    errGeneric: 'حدث خطأ ما — حاول مجدداً.',
    errNoNotes: 'تعذّر على الذكاء الاصطناعي إعداد الملاحظات الآن — حاول مجدداً.',
    // الاستخدام العادل / الازدحام (الوضع المجاني)
    errFairIp: 'يستخدم الكثير من الطلاب علّمني من شبكتك اليوم، لذلك توقّف مؤقتاً هنا — حاول مجدداً لاحقاً.',
    errFairUser: 'وصلت إلى حدّ الاستخدام العادل لهذا اليوم. يتجدّد خلال 24 ساعة — حاول مجدداً لاحقاً.',
    errBusyToday: 'علّمني مزدحم جداً اليوم — يرجى المحاولة لاحقاً.',
    errBusy: 'كثير من الطلاب يُنشئون أدلتهم الآن — اضغط «إعادة المحاولة» بعد دقيقة.',
    errYtBlocked: 'حظر YouTube هذا الفيديو — جرّب فيديو فيه ترجمة نصية، أو الصق النص في تبويب «لصق نص / رابط».',
    fileTooBig: (n) => `حجم ${n} أكبر من 50 ميغابايت — اضغطه أو قسّمه.`,
    maxFiles: 'يمكنك معالجة 3 ملفات كحد أقصى في كل مرة.',
    unsupportedFile: 'ملف غير مدعوم — استخدم .pptx أو .ppt أو .pdf أو .docx أو .doc أو .txt.',
    // تسجيل الدخول والحساب
    close: 'إغلاق',
    sessionExpired: 'انتهت جلستك — يرجى تسجيل الدخول مجدداً.',
    linkExpired: 'انتهت صلاحية هذا الرابط أو سبق استخدامه. إن كنت سجّلت للتو فقد يكون بريدك مؤكَّداً بالفعل — جرّب تسجيل الدخول بكلمة المرور، أو اطلب رابطاً جديداً.',
    authLinkError: 'لم يكتمل تسجيل الدخول — حاول مجدداً.',
    authUnavailable: 'تسجيل الدخول غير متاح الآن — يرجى إعادة تحميل الصفحة.',
    authTimeout: 'يستغرق الأمر وقتاً طويلاً — تحقّق من اتصالك وحاول مجدداً.',
    emailNotConfirmed: 'يرجى تأكيد بريدك أولاً — ابحث عن رابطنا في صندوق الوارد.',
    resendConfirm: 'إعادة إرسال رسالة التأكيد',
    resent: 'تم الإرسال — تحقّق من صندوق الوارد (ومجلد الرسائل غير المرغوب فيها).',
    emailRateLimit: 'أُرسلت رسائل كثيرة — انتظر بضع دقائق ثم حاول مجدداً.',
    authRateLimit: 'محاولات كثيرة — انتظر دقيقة ثم حاول مجدداً.',
    weakPassword: 'كلمة المرور ضعيفة — استخدم 6 أحرف على الأقل تجمع بين الحروف والأرقام.',
    samePassword: 'اختر كلمة مرور مختلفة عن القديمة.',
    forgotPw: 'نسيت كلمة المرور؟',
    resetSent: (e) => `أرسلنا رابط إعادة تعيين كلمة المرور إلى ${e} — تحقّق من بريدك.`,
    enterEmailFirst: 'أدخل بريدك في الأعلى أولاً.',
    checkInboxTitle: 'تحقّق من بريدك',
    checkInbox: (e) => `أرسلنا رابط تأكيد إلى ${e}. افتحه على هذا الجهاز لإكمال التسجيل.`,
    resendEmail: 'إعادة الإرسال',
    backToSignIn: 'العودة لتسجيل الدخول',
    inAppGoogle: 'تسجيل الدخول عبر Google لا يعمل داخل هذا التطبيق. افتح alimne.app في Safari أو Chrome (⋯ ← فتح في المتصفح)، أو استخدم البريد الإلكتروني بالأسفل.',
    copyLink: 'نسخ الرابط',
    newPwTitle: 'عيّن كلمة مرور جديدة',
    newPwSub: 'اختر كلمة مرور جديدة لحسابك.',
    newPwPh: 'كلمة المرور الجديدة (6 أحرف على الأقل)',
    newPwBtn: 'حفظ كلمة المرور',
    pwUpdated: 'تم تحديث كلمة المرور — أنت مسجّل الدخول الآن.',
    pwTooShort: 'استخدم 6 أحرف على الأقل.',
    accountLoadFailed: 'تعذّر تحميل حسابك.',
    // الدردشة
    chatTitle: 'اسأل الدليل',
    chatIntro: 'اسألني أي شيء — تعريفات، تلميحات، شروحات، نقاط رئيسية.',
    chatPh: 'اكتب سؤالك…',
    chatSend: 'إرسال',
    chatSuggest: ['لخّص النقاط الرئيسية', 'ما المواضيع الأساسية؟', 'على ماذا أركّز للامتحان؟', 'أعطني أهم التعريفات'],
    chatSignIn: 'سجّل الدخول للدردشة مع دليلك',
    chatNoAnswer: 'لا توجد إجابة — حاول مجدداً.',
  }
}

// ── Token-mode copy (ALIMNE_FREE_MODE=0 only) ─────────────────────────────────
// Alimne is free by default. If the owner ever switches the server back to tokens, the
// client follows /api/config (free_mode:false) or the first 402 and merges this pack over T.
// In free mode (the default) none of it is reachable: tFor(lang, true) is T itself.
const LEGACY = {
  en: {
    sub: 'Drop a PowerPoint, PDF, or YouTube lecture — get an exam-ready guide with notes, flashcards, and a practice quiz in seconds. Free to start, no card needed.',
    heroFree: '',
    dropFree: '',
    footerFree: 'Free to try · Files deleted automatically',
    // token mode makes no browser copy for the Google round trip, so it keeps the privacy line it always had
    privacy: 'Your files are processed in memory only — never written to disk or seen by anyone. The server wipes everything automatically within 15 minutes; this tab keeps a copy of your guide until you close it, remove it or tap Delete now. Flash-card progress is saved on this device.',
    trust: ['No sign-up to try', 'Files wiped in 15 min', 'English & العربية'],
    upgradeTitle: "You're out of free guides",
    upgradeSub: "You've used your free guides for now. Go Pro for 30 a month plus priority processing.",
    upgradeFeatures: ['30 guides per month', 'Priority processing', 'All features included'],
    upgradeBtn: 'Go Pro — $2.99 / month',
    upgradeFree: 'Free: 3 study guides a month',
    guidesLeft: 'Guides left this month',
    tokensLeft: 'tokens',
    loginSubSignup: 'Create a free account — 3 more study guides on us',
    freeLeft: (n) => `${n} free ${n === 1 ? 'preview' : 'previews'} left`,
    signInForMore: 'Loved it? Sign up free — 3 more guides on us.',
    emailCaptureTitle: 'Get 3 free study guides',
    emailCaptureSub: "Drop your email and we'll set you up with 3 free study guides a month. No spam.",
    emailPlaceholder: 'you@email.com',
    emailCaptureBtn: 'Continue',
    emailSkip: 'Skip for now',
    referTitle: 'Refer & Earn',
    referSub: 'Share your link. Each person who subscribes earns you 10 free tokens — no limit.',
    referStats: (paid) => paid > 0 ? `${paid} subscriber${paid > 1 ? 's' : ''} · ${paid * 10} tokens earned` : 'No referrals yet',
    usesCredit: 'This uses 1 guide credit. Continue?',
    proUsedUp: "You've used this month's guides — they renew at the start of next month.",
    freeUsedUp: 'Free guides used — subscribe to continue.',
    errNoNotesRefunded: "The AI couldn't build notes for this file right now — your credit was returned, please try again.",
  },
  ar: {
    sub: 'ارفع عرضاً تقديمياً أو PDF أو رابط محاضرة من YouTube — واحصل على دليل جاهز للامتحان مع ملخص وبطاقات وأسئلة مراجعة خلال ثوانٍ. ابدأ مجاناً، بدون بطاقة.',
    heroFree: '',
    dropFree: '',
    footerFree: 'جرّب مجاناً · تُحذف الملفات تلقائياً',
    privacy: 'ملفاتك تُعالَج في الذاكرة فقط — لا تُكتب على القرص ولا يراها أحد. يمسح الخادم كل شيء تلقائياً خلال 15 دقيقة، وتحتفظ هذه النافذة بنسخة من دليلك حتى تغلقها أو تزيله أو تضغط «احذف الآن». ويُحفظ تقدّمك في البطاقات على هذا الجهاز.',
    trust: ['بدون تسجيل للتجربة', 'تُمسح الملفات خلال 15 دقيقة', 'الإنجليزية والعربية'],
    upgradeTitle: 'انتهت أدلتك المجانية',
    upgradeSub: 'استخدمت أدلتك المجانية الآن. اشترك للحصول على 30 دليلاً شهرياً ومعالجة ذات أولوية.',
    upgradeFeatures: ['30 دليلاً شهرياً', 'معالجة ذات أولوية', 'جميع الميزات متاحة'],
    upgradeBtn: 'اشترك — 2.99$ / شهر',
    upgradeFree: 'مجاناً: 3 أدلة دراسة شهرياً',
    guidesLeft: 'الأدلة المتبقية هذا الشهر',
    tokensLeft: 'رموز متبقية',
    loginSubSignup: 'أنشئ حساباً مجانياً — 3 أدلة دراسة إضافية هدية منّا',
    freeLeft: (n) => `${n} ${n === 1 ? 'معاينة' : 'معاينات'} مجانية متبقية`,
    signInForMore: 'أعجبك؟ سجّل مجاناً — 3 أدلة إضافية هدية لك.',
    emailCaptureTitle: 'احصل على 3 أدلة دراسة مجانية',
    emailCaptureSub: 'أدخل بريدك ونجهّز لك 3 أدلة دراسة مجانية شهرياً. بدون إزعاج.',
    emailPlaceholder: 'you@email.com',
    emailCaptureBtn: 'متابعة',
    emailSkip: 'تخطٍّ الآن',
    referTitle: 'أحِل واكسب',
    referSub: 'شارك رابطك. كل شخص يشترك عبر رابطك يمنحك 10 رموز مجانية — بلا حدود.',
    referStats: (paid) => paid > 0 ? `${paid} مشترك · ${paid * 10} رمز مكتسب` : 'لا إحالات بعد',
    usesCredit: 'سيستهلك هذا رصيد دليل واحد. هل تريد المتابعة؟',
    proUsedUp: 'استخدمت أدلة هذا الشهر — تتجدد في بداية الشهر القادم.',
    freeUsedUp: 'استُخدمت الأدلة المجانية — اشترك للمتابعة.',
    errNoNotesRefunded: 'تعذّر على الذكاء الاصطناعي إعداد ملاحظات لهذا الملف الآن — أُعيد إليك رصيدك، حاول مجدداً.',
  },
}

// The language pack for the current mode: free mode is T itself, token mode overlays LEGACY.
const tFor = (lang, freeMode = true) => {
  const base = T[lang] || T.en
  return freeMode ? base : { ...base, ...(LEGACY[lang] || LEGACY.en) }
}

// A whole number >= 1 from /api/config, else null (never trust a missing / odd field)
const posInt = v => (typeof v === 'number' && Number.isFinite(v) && v >= 1) ? Math.floor(v) : null
// A whole number >= 0 (a counter, which may honestly be 0), else null
const countInt = v => (typeof v === 'number' && Number.isFinite(v) && v >= 0) ? Math.floor(v) : null
// A language-pack value that may be a function of a number (free-mode copy) or a plain string (token-mode copy)
const say = (v, ...args) => typeof v === 'function' ? v(...args) : v
// "Why sign in" clause. The account's daily number is quoted only when /api/config really sent one.
const perksOf = (t, fair) => t.perks(fair && fair.user_daily ? fair : null)

// ── Sign-in gate (free mode) ──────────────────────────────────────────────────
// An anonymous device may make ANON_FREE_USES guides (a lifetime allowance, 3 unless the owner
// changes it); after those a free account is required to make more. The server is the judge
// (401 signin_required). The client mirrors the count so it can say how many are left and open
// the sign-in modal instead of sending a request that would only be refused. The sample lecture,
// and viewing / downloading / restoring guides already made, are never gated.
const FREE_USES_DEFAULT = 3
// /api/config → { limit, remaining }. A missing or odd field falls back to the default (3 of 3). A 0 is a real
// answer, never "missing": the owner asks for an account from the very first guide (ANON_FREE_USES=0).
// `remaining` is this DEVICE's own count and nothing else: the client is never told how much its network or
// the whole anonymous pool has left, so it never guesses about them.
const gateFromConfig = (cfg) => {
  const limit = countInt(cfg?.signin_after) ?? countInt(cfg?.anon_free_limit) ?? FREE_USES_DEFAULT
  const left = countInt(cfg?.anon_remaining)
  return { limit, remaining: left === null ? limit : Math.min(left, limit) }
}
// After an anonymous guide is done: the server's own count when the 'done' event carries it, else one less
const gateAfterDone = (gate, ev) => {
  const left = countInt(ev?.anon_remaining)
  return { ...gate, remaining: left === null ? Math.max(0, gate.remaining - 1) : Math.min(left, gate.limit) }
}
// True when a NEW generation must not be sent: signed out, in free mode, nothing left.
// Never while the session is still restoring, and never when sign-in is switched off (no way forward then).
const anonGated = ({ freeMode, authEnabled, authLoading, session, remaining }) =>
  !!(freeMode && authEnabled && !authLoading && !session && remaining <= 0)
// The refusals that mean "sign in to continue": the gate, and what a server from before the gate sent for it
const GATE_CODES = new Set(['signin_required', 'fair_use_device'])
// WHY the server asked for a sign-in (the 401's `reason`): 'device' = this browser's own free guides are used,
// 'network' = the anonymous allowance of this network is used up for today, 'pool' = guides without an account
// are used up for today. A refusal with no reason (a server from before it) was about the device.
const signinReason = (data) => (data?.code === 'signin_required' && typeof data?.reason === 'string' && data.reason) ? data.reason : 'device'
// Only a 'device' refusal is about this browser's own counter. Any other reason leaves the counter as it is, so
// the next try is sent again and the server decides: the client cannot know what a network or the pool has left.
const holdsDeviceCount = (data) => signinReason(data) === 'device'   // includes the older 'fair_use_device' code

// The text for a sign-in refusal. Only 'device' may say "you've used your N free guides" (n = the server's number,
// 0 included). A reason this client does not know shows the server's own sentence instead of a guess.
// When NO guide is free without an account (n = 0) that is the whole answer, whatever the reason: the server
// decides it before it looks at the reason, and so does this. A browser that keeps no device id asks with the
// reason 'network', and "used up on your network" would promise guides that do not exist.
const signinText = (t, reason, n, serverText) => {
  const uses = countInt(n) ?? FREE_USES_DEFAULT
  if (uses === 0) return t.signinRequired(0)
  if (reason === 'network') return t.signinNetwork
  if (reason === 'pool') return t.signinPool
  if (reason && reason !== 'device' && typeof serverText === 'string' && serverText.trim()) return serverText
  return t.signinRequired(uses)
}
// Server refusals that make the rest of a batch pointless: stop it, leave the other files queued
const STOP_CODES = new Set(['signin_required', 'fair_use_device', 'fair_use_ip', 'fair_use_user', 'busy_today', 'busy'])
// An item held for sign-in: only a signed-out visitor is asked (once signed in it is simply ready to run)
const offersSignIn = (item, session) => !!item && GATE_CODES.has(item.errCode) && !session
// Line under a processing item: the queue position (localized, not the server's English) or the stream message
const procLine = (t, item) => item.step === 'queued'
  ? (item.queuePos > 0 ? t.queuePos(item.queuePos) : t.queueWait)
  : (item.msg || t.processing)
const badgeKey = (item, session) => (item.status === 'processing' && item.step === 'queued') ? 'queued'
  : (item.status === 'queued' && offersSignIn(item, session)) ? 'signin' : item.status
// Session-only note that the gate asked this visitor to sign in. Google sign-in leaves the page and
// comes back, so the note (and the link they had typed) survives it. A chosen file or pasted text cannot
// live in sessionStorage: those go through the sign-in stash further down (signinStash).
const GATE_KEY = 'alimne_gate_v1'
const gateNote = {
  save: (o) => { try { sessionStorage.setItem(GATE_KEY, JSON.stringify(o)) } catch { /* best-effort */ } },
  take: () => {
    try {
      const raw = sessionStorage.getItem(GATE_KEY)
      if (!raw) return null
      sessionStorage.removeItem(GATE_KEY)
      const o = JSON.parse(raw)
      return o && typeof o === 'object' ? o : {}
    } catch { return null }
  },
}
const keptLink = v => (typeof v === 'string' && v.length <= 2000) ? v.trim() : ''
// Card inviting an anonymous visitor to create a free account — only after their first real guide
// (the sample demo is not theirs), never in token mode, never once signed in or dismissed.
const showJoinCard = ({ freeMode, authEnabled, authLoading, session, dismissed, queue }) =>
  !!(freeMode && authEnabled && !authLoading && !session && !dismissed &&
    queue.some(i => i.status === 'done' && !i.demo && i.source?.type !== 'sample'))

const STATUS_COLOR = {
  queued:     { bg: 'rgba(79,142,247,0.12)', color: '#4f8ef7',  border: 'rgba(79,142,247,0.3)' },
  processing: { bg: 'rgba(251,191,36,0.12)', color: '#fbbf24',  border: 'rgba(251,191,36,0.3)' },
  done:       { bg: 'rgba(34,197,94,0.12)',  color: '#22c55e',  border: 'rgba(34,197,94,0.3)'  },
  error:      { bg: 'rgba(239,68,68,0.12)',  color: '#ef4444',  border: 'rgba(239,68,68,0.3)'  },
  expired:    { bg: 'rgba(148,163,184,0.12)', color: '#94a3b8', border: 'rgba(148,163,184,0.3)' },
  signin:     { bg: 'rgba(251,191,36,0.12)', color: '#f59e0b',  border: 'rgba(251,191,36,0.35)' },   // held for sign-in (not an error)
}

let _id = 0
const uid = () => ++_id

// ── Supabase — public project values (the same ones /api/config serves) ───────
// Created once at load, so session restore and the OAuth return never wait on
// /api/config. Implicit flow (supabase-js default).
const SB_URL  = 'https://ufwurywcozlpadzaobug.supabase.co'
const SB_ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVmd3VyeXdjb3pscGFkemFvYnVnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc3NDc4MDIsImV4cCI6MjEwMzMyMzgwMn0.mpARaiN5gvZzQN2eoOCtlSOAeNTVLzjB78E-P6vTXXI'
// Read auth errors from the URL BEFORE the client parses it (shown on mount).
const AUTH_URL_ERR = (() => {
  try {
    const q = new URLSearchParams(window.location.search)
    const h = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const g = k => q.get(k) || h.get(k)
    const e = { code: g('error_code'), err: g('error'), desc: g('error_description') }
    return (e.code || e.err || e.desc) ? e : null
  } catch { return null }
})()
const RECOVERY_IN_URL = (() => { try { return /(^#|&)type=recovery(&|$)/.test(window.location.hash) } catch { return false } })()
const sb = (() => { try { return createClient(SB_URL, SB_ANON) } catch (e) { console.error('supabase init', e); return null } })()

// Instagram / Facebook / TikTok / Snapchat / LINE / Android WebViews: Google OAuth
// is blocked and <a download> is usually ignored.
const IN_APP = (() => { try { return /Instagram|FBAN|FBAV|FB_IAB|TikTok|musical_ly|Snapchat|Line\/|; wv\)/i.test(navigator.userAgent || '') } catch { return false } })()
const NAV_AR = (() => { try { return String(navigator.language || '').toLowerCase().startsWith('ar') } catch { return false } })()
const MAX_UPLOAD = 50 * 1024 * 1024
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const isProUser = u => u?.plan ? u.plan === 'pro' : u?.subscription_status === 'active'
// Manage vs Subscribe: a stale period_end can read plan 'free' while Stripe still bills
// (status 'active') — offering Subscribe then would charge twice. `plan` is for the badge.
const hasLiveSub = u => isProUser(u) || u?.subscription_status === 'active'

// localStorage can throw (private mode, blocked site data, in-app browsers).
const ls = {
  get: k => { try { return localStorage.getItem(k) } catch { return null } },
  set: (k, v) => { try { localStorage.setItem(k, v) } catch { /* best-effort */ } },
  del: k => { try { localStorage.removeItem(k) } catch { /* best-effort */ } },
}

const sleep = ms => new Promise(r => setTimeout(r, ms))
// fetch with a timeout (rejects with AbortError)
function fetchT(url, opts = {}, ms = 30000) {
  const c = new AbortController()
  const tm = setTimeout(() => c.abort(), ms)
  return fetch(url, { ...opts, signal: c.signal }).finally(() => clearTimeout(tm))
}

// Filename from Content-Disposition (RFC 5987 first), else the fallback
function filenameFrom(r, fb) {
  const cd = r.headers.get('Content-Disposition') || ''
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i)
  if (star) { try { return decodeURIComponent(star[1]) } catch { /* fall through */ } }
  const plain = cd.match(/filename="?([^";]+)"?/i)
  return plain ? plain[1] : fb
}
// Save a blob through a temporary <a download> in the DOM (iOS reads the URL late → revoke after 60s)
function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name; a.rel = 'noopener'; a.style.display = 'none'
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

// One mapper for request / stream failures → plain-language, localized text
function friendlyErr(t, msg, status, data) {
  const code = data?.code
  // 'your credit was returned' only exists in token mode (LEGACY); free mode never mentions credits
  if (code === 'no_notes') return data?.refunded && t.errNoNotesRefunded ? t.errNoNotesRefunded : t.errNoNotes
  if (code === 'yt_blocked') return t.errYtBlocked
  // Sign-in gate (HTTP 401 signin_required): a free account is needed, and the server says why (reason: device /
  // network / pool), so the text is the true one for that cause. The number is the server's own (free_uses, 0 included).
  if (code === 'signin_required') return signinText(t, data?.reason, data?.free_uses, data?.error)
  // What a server from before the gate sent for the same thing: it could only mean the device's own guides
  if (code === 'fair_use_device') return t.signinRequired(posInt(data?.free_uses) || FREE_USES_DEFAULT)
  // Free-mode fair-use / capacity refusals (HTTP 429 / 503, or an SSE error event with status 200):
  // our own words, ahead of the generic 429 / 503 text below
  if (code === 'fair_use_ip') return t.errFairIp
  if (code === 'fair_use_user') return t.errFairUser
  if (code === 'busy_today') return t.errBusyToday
  if (code === 'busy') return t.errBusy
  if (status === 0) return msg || t.errNetwork
  if (status === 413 || code === 'too_large') return t.errTooBig
  if (status === 429 || code === 'rate_limited') return t.errRateLimit
  if (code === 'retry' || code === 'auth_unavailable') return t.errRetry
  if (status === 502 || status === 503 || status === 504) return t.errUpdating
  if (status >= 500 && (!msg || /^Server error/i.test(msg))) return t.errUpdating
  return msg || t.errGeneric
}

// Supabase auth error → localized text (by error.code, then by message)
const AUTH_ERR_KEYS = {
  invalid_credentials: 'wrongPassword', email_not_confirmed: 'emailNotConfirmed',
  over_email_send_rate_limit: 'emailRateLimit', over_request_rate_limit: 'authRateLimit',
  weak_password: 'weakPassword', user_already_exists: 'accountExists', email_exists: 'accountExists',
  email_address_invalid: 'emailInvalid', same_password: 'samePassword', otp_expired: 'linkExpired',
}
function authErrText(t, err) {
  const k = AUTH_ERR_KEYS[err?.code]
  if (k && t[k]) return t[k]
  const m = String(err?.message || '').toLowerCase()
  if (m.includes('invalid login') || m.includes('credentials')) return t.wrongPassword
  if (m.includes('not confirmed')) return t.emailNotConfirmed
  if (m.includes('already') || m.includes('registered')) return t.accountExists
  if (m.includes('rate limit')) return t.authRateLimit
  if (err?.name === 'AuthRetryableFetchError' || m.includes('fetch') || m.includes('network')) return t.errNetwork
  return t.authError
}

// ── Queue persistence (this tab only) ─────────────────────────────────────────
// Finished guides survive the Google / Stripe round trips and reloads. Never the
// File, a Blob or pasted text.
const QKEY = 'alimne_queue_v1'
const guideOf = d => ({
  title: d?.title || '', subtitle: d?.subtitle || '', sections: d?.sections || [],
  flashcards: d?.flashcards || [], mcqs: d?.mcqs || [], keywords: d?.keywords || [],
  objectives: d?.objectives || [], language: d?.language || 'en',
})
function loadSavedQueue() {
  try {
    const q = JSON.parse(sessionStorage.getItem(QKEY) || '[]')
    if (!Array.isArray(q)) return []
    const out = q.filter(i => i && i.id && i.jobId && (i.status === 'done' || i.status === 'expired')).map(i => {
      let guide = null
      if (i.guideBlob) { try { guide = guideOf(JSON.parse(i.guideBlob).guide) } catch { /* unreadable copy */ } }
      return { ...i, file: null, guide, busy: null, sharing: false, error: null, step: null, msg: null }
    })
    _id = Math.max(_id, ...out.map(i => +i.id || 0))
    return out
  } catch { return [] }
}
// Restore results that will never succeed for this copy → the item really is 'expired'.
// Anything else (offline, 429, 503 busy/updating) is passing: keep the item usable.
const RESTORE_FINAL = new Set(['no_copy', 'bad_request', 'bad_signature', 'too_large', 'rebuild_failed',
  'unavailable', 'http_400', 'http_403', 'http_404', 'http_405', 'http_413'])
// Spaced-repetition progress key: stable across restores (sig), else the job id
const srKeyOf = it => 'sr_' + (it.sig ? String(it.sig).slice(0, 32) : it.jobId)
const pdfNameOf = it => it.filename || (String(it.name || 'study_guide').replace(/\.(pptx?|pdf|docx?|txt)$/i, '') + '_study_guide.pdf')
// Same formula-injection guard as the server's Anki export
const csvCell = v => {
  let s = String(v ?? '')
  if (/^[ \t\r\n]*[=+\-@]/.test(s)) s = "'" + s
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

// ── Sign-in round trip: what was waiting stays in THIS browser ────────────────
// Google sign-in leaves the page and comes back, and a page that leaves forgets its memory: a chosen file or
// pasted text that was waiting (behind the sign-in gate, or simply not generated yet) used to be gone on return.
// So just before the page leaves, the items that were not generated yet are put in IndexedDB (it can hold a
// File), in this browser only. Nothing is sent anywhere: an item is uploaded when the visitor taps Generate,
// exactly as before. The copy
//   * is capped (STASH_MAX_FILES files, about STASH_MAX_BYTES in all; a file left out is counted, and the
//     visitor is told to choose it again);
//   * belongs to the tab that made it (a random claim in sessionStorage, which survives the round trip in the
//     same tab and nothing else): no other tab can take it, including one opened later by someone else at the
//     same computer;
//   * is deleted as soon as it is read back (its files are first copied into the page's memory, see
//     signinStash.take), deleted on sign-out, dropped when the page never left and the visitor went on there,
//     and never used once it is older than STASH_MAX_AGE_MS (any later page load in this browser sweeps it).
// Every touch of IndexedDB and of the browser's storage is wrapped and time-limited: where they are missing,
// blocked or broken (some private modes) nothing is kept and the page behaves as it always did. A browser that
// never made a copy never even opens IndexedDB (STASH_FLAG).
const STASH_DB = 'alimne_signin_stash'
const STASH_STORE = 'pending'
const STASH_TAB_KEY = 'alimne_stash_tab'
const STASH_FLAG = 'alimne_stash_made'
const STASH_MAX_AGE_MS = 30 * 60 * 1000
const STASH_LEAVING_MS = 20 * 1000   // after "Continue with Google": how long the page may still be on its way out
const STASH_MAX_BYTES = 60 * 1024 * 1024
const STASH_MAX_FILES = 3
const STASH_TABS = ['upload', 'youtube', 'text']
const randomId = () => Math.random().toString(36).slice(2) + Date.now().toString(36)

// What to keep: the queue items that were not generated yet (their File, link or pasted text) and what is typed
// in the boxes. Only the source: no job, no status, no guide. → { items, box, skipped }, or null when nothing is
// waiting. `skipped` = the files left out for a cap (the queue takes 3 files of up to 50 MB each, the copy about
// STASH_MAX_BYTES in all): they are counted so the visitor is told to choose them again.
function stashPlan(queue, boxes) {
  const items = []
  let files = 0, bytes = 0, skipped = 0
  for (const it of Array.isArray(queue) ? queue : []) {
    if (!it || it.demo || !['queued', 'error', 'processing'].includes(it.status)) continue
    const src = it.source || (it.file ? { type: 'file' } : null)
    if (!src) continue
    if (src.type === 'file') {
      const size = it.file ? Number(it.file.size) : NaN
      if (!(size >= 0)) continue                     // its File is gone already: there is nothing to keep
      if (files >= STASH_MAX_FILES || bytes + size > STASH_MAX_BYTES) { skipped++; continue }
      files++; bytes += size
      items.push({ kind: 'file', name: String(it.name || it.file.name || ''), file: it.file })
    } else if (src.type === 'youtube') {
      const url = keptLink(src.url)
      if (url) items.push({ kind: 'youtube', url })
    } else if (src.type === 'text') {
      const text = typeof src.text === 'string' ? src.text : '', url = keptLink(src.url)
      if ((!text.trim() && !url) || bytes + text.length * 2 > STASH_MAX_BYTES) continue
      bytes += text.length * 2
      items.push({ kind: 'text', text, url, name: String(src.name || it.name || '') })
    }
  }
  const typed = (typeof boxes?.text === 'string' && boxes.text.trim() && bytes + boxes.text.length * 2 <= STASH_MAX_BYTES) ? boxes.text : ''
  const box = { text: typed, url: keptLink(boxes?.url), yt: keptLink(boxes?.yt), tab: STASH_TABS.includes(boxes?.tab) ? boxes.tab : 'upload' }
  return (items.length || box.text || box.url || box.yt) ? { items, box, skipped } : null
}

// The kept copy → queue items READY to generate (nothing was sent anywhere, so nothing is 'done' and nothing is
// held), the boxes' text, what came back in one word for the toast ('file' | 'files' | 'text' | 'link' |
// 'items', or null for nothing), and `missing`: how many files could NOT be kept (left out of the copy for a
// cap, or unreadable on return). Whatever is not exactly what stashPlan writes is dropped: it is never rendered.
function stashItems(rec) {
  const items = []
  let files = 0, texts = 0, links = 0
  const ready = (extra) => ({ id: uid(), file: null, status: 'queued', jobId: null, error: null, step: null, msg: null, ...extra })
  for (const s of Array.isArray(rec?.items) ? rec.items : []) {
    if (!s || typeof s !== 'object') continue
    if (s.kind === 'file') {
      const f = s.file
      const name = String((f && f.name) || s.name || '')
      if (typeof Blob === 'undefined' || !(f instanceof Blob) || f.size > MAX_UPLOAD || files >= STASH_MAX_FILES ||
          !/\.(pptx?|pdf|docx?|txt)$/i.test(name)) continue
      let file = f
      if (!f.name) { try { file = new File([f], name, { type: f.type || '' }) } catch { continue } }   // a bare Blob came back: give it its name again
      files++
      items.push(ready({ file, name, source: { type: 'file' } }))
    } else if (s.kind === 'youtube') {
      const url = keptLink(s.url)
      if (!url) continue
      links++
      items.push(ready({ name: url, source: { type: 'youtube', url } }))
    } else if (s.kind === 'text') {
      const text = typeof s.text === 'string' ? s.text : '', url = keptLink(s.url)
      if (!text.trim() && !url) continue
      const name = (typeof s.name === 'string' && s.name.trim()) ? s.name.slice(0, 80)
        : url ? url.replace(/^https?:\/\//, '').slice(0, 40) : 'Pasted text'
      if (text.trim()) texts++; else links++
      items.push(ready({ name, source: { type: 'text', url, text, name } }))
    }
  }
  const b = (rec?.box && typeof rec.box === 'object') ? rec.box : {}
  const box = { text: typeof b.text === 'string' ? b.text : '', url: keptLink(b.url), yt: keptLink(b.yt), tab: STASH_TABS.includes(b.tab) ? b.tab : 'upload' }
  if (box.text.trim()) texts++
  else if (box.url || box.yt) links++
  const kind = !(files + texts + links) ? null
    : (files && !texts && !links) ? (files === 1 ? 'file' : 'files')
    : (!files && texts === 1 && !links) ? 'text'
    : (!files && !texts && links === 1) ? 'link' : 'items'
  const missing = Math.min((countInt(rec?.skipped) ?? 0) + (countInt(rec?.lost) ?? 0), 99)
  return { items, box, kind, missing }
}

// The toast after a sign-in that brought something back: what is ready, and, when a file could not be kept, that
// it has to be chosen again. With nothing back it only says "signed in": it never calls a missing file ready.
const stashToast = (t, back) => [back?.kind ? t.stashReady(back.kind) : t.gateCleared, back?.missing > 0 ? t.stashMissing(back.missing) : '']
  .filter(Boolean).join(' ')

// A File as IndexedDB hands it back → the same file held in THIS page's memory, or null when its bytes cannot be
// read (in time, or all of them). Needed before the record is deleted, see signinStash.take.
async function stashFileCopy(f, name, ms = 20000) {
  let timer = null
  try {
    if (typeof Blob === 'undefined' || typeof File === 'undefined' || !(f instanceof Blob) || f.size > MAX_UPLOAD) return null
    const buf = await Promise.race([f.arrayBuffer(), new Promise((_, no) => { timer = setTimeout(() => no(new Error('timeout')), ms) })])
    if (!buf || buf.byteLength !== f.size) return null
    const opts = { type: f.type || '' }
    if (typeof f.lastModified === 'number') opts.lastModified = f.lastModified
    return new File([buf], String(f.name || name || ''), opts)
  } catch { return null }
  finally { clearTimeout(timer) }
}

// One IndexedDB transaction on the stash store. → what `work` reported through its second argument once the
// transaction completed, or undefined when IndexedDB is missing, blocked, too slow (ms) or fails in any way.
function stashDb(mode, work, ms = 4000) {
  return new Promise(resolve => {
    let over = false, timer = null
    const done = (v) => { if (over) return; over = true; clearTimeout(timer); resolve(v) }
    timer = setTimeout(() => done(undefined), ms)
    try {
      const idb = typeof indexedDB !== 'undefined' ? indexedDB : null
      if (!idb) { done(undefined); return }
      const open = idb.open(STASH_DB, 1)
      open.onupgradeneeded = () => { try { open.result.createObjectStore(STASH_STORE) } catch { /* already there */ } }
      open.onerror = open.onblocked = () => done(undefined)
      open.onsuccess = () => {
        const db = open.result
        const close = () => { try { db.close() } catch { /* ignore */ } }
        if (over) { close(); return }               // it answered too late: the caller has moved on
        try {
          let out
          const tx = db.transaction(STASH_STORE, mode)
          tx.oncomplete = () => { close(); done(out) }
          tx.onerror = tx.onabort = () => { close(); done(undefined) }
          work(tx.objectStore(STASH_STORE), (v) => { out = v })
        } catch { close(); done(undefined) }
      }
    } catch { done(undefined) }
  })
}

const signinStash = {
  // This page load. A copy made by this very load is still in memory here, so reading it back only deletes it.
  page: randomId(),
  busy: false,                                       // a take() is running in this page (never two at once)
  // Does this tab hold a claim on a copy? (synchronous and cheap: no IndexedDB)
  claimed: () => { try { return !!sessionStorage.getItem(STASH_TAB_KEY) } catch { return false } },
  // True when there is nothing to look for: this tab holds no claim and no copy was ever made in this browser.
  // Then IndexedDB is not opened at all (most visitors). Storage that cannot be read counts as "look".
  idle: () => {
    if (signinStash.claimed()) return false
    try { return localStorage.getItem(STASH_FLAG) !== '1' } catch { return false }
  },
  // Just before the page leaves for a sign-in. → true when a copy was kept (in this browser, nowhere else).
  save: async (plan, ms = 6000) => {
    if (!plan) return false
    const token = randomId()
    let old = null
    try {
      old = sessionStorage.getItem(STASH_TAB_KEY)
      sessionStorage.setItem(STASH_TAB_KEY, token)
      if (sessionStorage.getItem(STASH_TAB_KEY) !== token) return false
    } catch { return false }                        // no session storage: nothing could claim the copy back, so none is made
    try { localStorage.setItem(STASH_FLAG, '1') } catch { /* then every page load looks, see idle() */ }
    const ok = await stashDb('readwrite', (store, out) => {
      if (old) store.delete(old)                    // this tab's earlier copy, if any: never two for one tab
      store.put({ v: 1, at: Date.now(), page: signinStash.page, items: plan.items, box: plan.box, skipped: plan.skipped || 0 }, token)
      out(true)
    }, ms)
    if (!ok) { try { sessionStorage.removeItem(STASH_TAB_KEY) } catch { /* ignore */ } }
    return !!ok
  },
  // Back on the page. → the copy THIS tab made on an earlier page load, or null. Nothing is ever read and kept:
  // the copy is read, its files are copied into this page's memory, and the record is deleted straight after,
  // in a SECOND transaction. It cannot be the one that reads it: in Safari and in every iOS browser a File read
  // back from IndexedDB is only a pointer to the bytes stored with its record, and it stops being readable the
  // moment that record is deleted (the file would show as queued, and its upload would fail on every try).
  // A file whose bytes cannot be read is left out and counted in `lost`, so the visitor is told to choose it
  // again. A copy older than STASH_MAX_AGE_MS is deleted whoever made it, and never returned.
  take: async (ms = 8000) => {
    if (signinStash.busy) return null                // a read is under way in this page already: it finishes the job
    signinStash.busy = true
    try {
      let token = null
      try { token = sessionStorage.getItem(STASH_TAB_KEY) } catch { /* no claim */ }
      const now = Date.now()
      let rec = null, left = 0
      const ran = await stashDb('readwrite', (store, out) => {
        const cur = store.openCursor()
        cur.onsuccess = () => {
          const c = cur.result
          if (!c) { out(true); return }
          const r = c.value
          const mine = !!token && c.key === token
          const fresh = !!r && typeof r.at === 'number' && now >= r.at && now - r.at <= STASH_MAX_AGE_MS
          const back = mine && fresh && r.page !== signinStash.page   // this tab's, from an earlier page load: it comes back
          if (back) rec = r                          // ...so it stays until its files are in this page's memory
          else if (mine || !fresh) c.delete()
          else left++                                // another tab's, still in its round trip: not ours to touch
          c.continue()
        }
      }, ms)
      let gone = true
      if (ran && rec) {
        const items = []
        let lost = 0
        for (const s of Array.isArray(rec.items) ? rec.items : []) {
          if (!s || s.kind !== 'file') { items.push(s); continue }
          const file = await stashFileCopy(s.file, s.name)
          if (file) items.push({ ...s, file }); else lost++
        }
        rec = { ...rec, items, lost }
        gone = !!(await stashDb('readwrite', (store, out) => { store.delete(token); out(true) }, ms))
      }
      if (token) { try { sessionStorage.removeItem(STASH_TAB_KEY) } catch { /* ignore */ } }
      // the flag stays while a row may be left (another tab's, or one that could not be deleted): a later load sweeps it
      if (ran && !left && gone) { try { localStorage.removeItem(STASH_FLAG) } catch { /* ignore */ } }
      return ran ? rec : null
    } finally { signinStash.busy = false }
  },
  // Sign-out: no copy of anyone's stays in this browser.
  clear: async () => {
    try { sessionStorage.removeItem(STASH_TAB_KEY) } catch { /* ignore */ }
    const ran = await stashDb('readwrite', (store, out) => { store.clear(); out(true) })
    if (ran) { try { localStorage.removeItem(STASH_FLAG) } catch { /* ignore */ } }
  },
}

// ── Toast notifications ────────────────────────────────────────────────────
function ToastContainer() {
  const [toasts, setToasts] = useState([])
  useEffect(() => {
    window._addToast = (msg, type = 'success', ms = 0) => {
      const id = uid()
      setToasts(p => [...p, { id, msg, type }])
      setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), ms > 0 ? ms : type === 'error' ? 5500 : 3000)
    }
    return () => { delete window._addToast }
  }, [])
  if (!toasts.length) return null
  return (
    <div role="status" aria-live="polite" style={{position:'fixed',bottom:'1.5rem',left:16,right:16,zIndex:9999,display:'flex',flexDirection:'column',gap:'0.4rem',alignItems:'center',pointerEvents:'none'}}>
      {toasts.map(t => (
        <div key={t.id} style={{
          background: t.type==='error' ? '#ef4444' : t.type==='info' ? '#4f8ef7' : '#22c55e',
          color:'#fff',padding:'0.5rem 1.1rem',borderRadius:8,fontSize:'0.82rem',fontWeight:600,lineHeight:1.4,
          boxShadow:'0 4px 20px rgba(0,0,0,0.3)',whiteSpace:'normal',maxWidth:'calc(100vw - 32px)',textAlign:'center',
          animation:'toastIn 0.18s ease'
        }}>{t.msg}</div>
      ))}
    </div>
  )
}
const toast = (msg, type, ms) => window._addToast?.(msg, type, ms)   // ms: how long it stays (default by type)

// ── Escape key hook ────────────────────────────────────────────────────────
function useEscapeKey(fn) {
  useEffect(() => {
    const h = e => { if (e.key === 'Escape') fn() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [fn])
}

// Persistent per-device id — lets the backend keep the anonymous free-preview
// quota tied to this device (durable across restarts + network changes) without
// any login. Best-effort: if storage is blocked, we send nothing and the backend
// falls back to its per-IP check.
function getDeviceId() {
  try {
    let d = localStorage.getItem('alimne_device_id')
    if (!d) {
      d = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
            : (Date.now().toString(36) + Math.random().toString(36).slice(2, 14))
      localStorage.setItem('alimne_device_id', d)
    }
    return d
  } catch { return '' }
}

// ── SSE stream helper ─────────────────────────────────────────────────────────
// onError receives (message, httpStatus, rawData). Exactly one terminal callback:
// events after done/error are ignored, and a stream that ends without one reports
// a localized "connection lost" (status 0). Returns the AbortController.
function streamSSE(url, options, onEvent, onError, t = T.en) {
  const ctrl = new AbortController()
  let settled = false
  const fail = (msg, status = 0, data = {}) => { if (settled) return; settled = true; onError(msg, status, data) }
  const handle = part => {
    if (settled) return
    const line = part.replace(/^data:\s*/, '').trim()
    if (!line) return
    let ev
    try { ev = JSON.parse(line) } catch { return }   // keep-alive comments etc.
    if (!ev || typeof ev !== 'object') return
    if (ev.error || ev.step === 'done') settled = true
    try { onEvent(ev) } catch (e) { console.error(e) }
  }
  fetch(url, { ...options, signal: ctrl.signal }).then(async res => {
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      fail(data.error || `Server error ${res.status}`, res.status, data)
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
      parts.forEach(handle)
    }
    if (buf.trim()) handle(buf)
    fail(t.streamLost, 0, { code: 'incomplete' })
  }).catch(() => fail(t.errNetwork, 0, { code: 'network' }))
  return ctrl
}

// Guide for a study modal: the cached copy, else one load via loadGuide().
// → [guide, error ('expired' | 'failed' | null), retry]
function useGuideLoader(initial, loadGuide) {
  const [g, setG] = useState(initial || null)
  const [err, setErr] = useState(null)
  const [n, setN] = useState(0)
  useEffect(() => {
    if (g || !loadGuide) return
    let live = true
    setErr(null)
    loadGuide().then(d => { if (live) setG(d) })
      .catch(e => { if (live) setErr(e?.message === 'expired' ? 'expired' : 'failed') })
    return () => { live = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n])
  return [g, err, () => setN(x => x + 1)]
}

// Study modal fallback: expired → Restore / Regenerate, network → Retry
function GuideUnavailable({ t, err, canRestore, onRecover, onRetry }) {
  const expired = err === 'expired'
  const act = expired ? onRecover : onRetry
  return (
    <div role="alert" style={{padding:'2rem 1.25rem',textAlign:'center',color:'var(--text-secondary)'}}>
      <AlertCircle size={20} style={{marginBottom:8,color: expired ? '#94a3b8' : '#ef4444'}} />
      <div style={{fontSize:'0.86rem',lineHeight:1.55,marginBottom:'1rem'}}>{expired ? t.guideExpiredLong : t.loadFailed}</div>
      {act && (
        <button className="submit-btn" style={{flex:'none',padding:'0.55rem 1.1rem',margin:'0 auto',fontSize:'0.85rem'}} onClick={act}>
          <RotateCcw size={14} /> {expired ? (canRestore ? t.restore : t.regenerate) : t.retry}
        </button>
      )}
    </div>
  )
}

// ── FlashCard Modal ────────────────────────────────────────────────────────────
function FlashCardModal({ jobId, srKey, guide, loadGuide, lang, t, canRestore, onRecover, onClose }) {
  const [g, loadErr, retryLoad] = useGuideLoader(guide, loadGuide)
  const [cards, setCards]       = useState(() => guide ? (guide.flashcards || []) : null)
  const [idx, setIdx]           = useState(0)
  const [flipped, setFlipped]   = useState(false)
  const keyRef = useRef(srKey || `sr_${jobId}`)   // fixed for this session of the modal
  const [known, setKnown]       = useState(() => {
    try { return JSON.parse(localStorage.getItem(keyRef.current) || localStorage.getItem(`sr_${jobId}`) || '{}') || {} } catch { return {} }
  })
  const [reviewMode, setReviewMode] = useState(false)
  const [roundDone, setRoundDone]   = useState(false)
  const [speaking, setSpeaking]     = useState(false)
  const isAr = (g?.language || lang) === 'ar'
  useEffect(() => { if (g && !cards) setCards(g.flashcards || []) }, [g, cards])
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
    ls.set(keyRef.current, JSON.stringify(k))
    setKnown(k)
  }

  // Key "known" by a stable card identity (the question text), NOT array index,
  // so shuffling / review-mode filtering can't misalign the known map.
  const cardKey = (c) => c && c.q

  const activeCards = cards ? (reviewMode
    ? cards.filter(c => !known[cardKey(c)])
    : cards) : []

  const currentCard = activeCards[idx]
  const knownCount  = cards ? cards.filter(c => known[cardKey(c)]).length : 0

  const speak = (text) => {
    if (!window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.onend = () => setSpeaking(false)
    setSpeaking(true)
    window.speechSynthesis.speak(u)
  }

  const mark = (isKnown) => {
    if (!cards || !currentCard) return
    const newKnown = { ...known, [cardKey(currentCard)]: isKnown }
    saveKnown(newKnown)
    window.speechSynthesis?.cancel()
    setSpeaking(false)
    setFlipped(false)
    // In review mode, marking a card "known" removes it from the active list,
    // so the next card slides into the current index — don't advance past it.
    const removed   = reviewMode && isKnown
    const remaining = removed ? activeCards.length - 1 : activeCards.length
    if (idx + (removed ? 0 : 1) >= remaining) {
      setRoundDone(true)
    } else if (!removed) {
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
        {loadErr
          ? <GuideUnavailable t={t} err={loadErr} canRestore={canRestore} onRecover={onRecover} onRetry={retryLoad} />
          : <div style={{padding:'2rem',textAlign:'center',color:'var(--text-secondary)'}}><Loader2 size={20} className="spin" style={{marginBottom:8}}/><div style={{fontSize:'0.82rem'}}>{FL.loading}</div></div>}
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
                    <button onClick={e => { e.stopPropagation(); navigator.clipboard?.writeText(currentCard.a).then(() => toast(t.referCopied), () => {}) }}
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
function QuizModal({ jobId, filename, guide, loadGuide, lang, t, canRestore, onRecover, onClose }) {
  const [g, loadErr, retryLoad] = useGuideLoader(guide, loadGuide)
  const mcqs = g ? (g.mcqs || []) : null
  const [idx, setIdx]         = useState(0)
  const [score, setScore]     = useState(0)
  const [answered, setAnswered] = useState(false)
  const [selected, setSelected] = useState(null)
  const [done, setDone]       = useState(false)
  const [wrongs, setWrongs]   = useState([])
  const isAr = (g?.language || lang) === 'ar'
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
        {loadErr
          ? <GuideUnavailable t={t} err={loadErr} canRestore={canRestore} onRecover={onRecover} onRetry={retryLoad} />
          : <div style={{padding:'2rem',textAlign:'center',color:'var(--text-secondary)'}}><Loader2 size={20} className="spin" style={{marginBottom:8}}/><div style={{fontSize:'0.82rem'}}>{QL.loading}</div></div>}
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
  const [hist, setHist] = useState(() => {
    try { const h = JSON.parse(localStorage.getItem('quizHistory') || '[]'); return Array.isArray(h) ? h : [] } catch { return [] }
  })

  const clearAll = () => {
    ls.del('quizHistory')
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
function OverviewModal({ guide: cached, loadGuide, lang, t, canRestore, onRecover, onClose }) {
  const [guide, loadErr, retryLoad] = useGuideLoader(cached, loadGuide)
  const [openSections, setOpen]   = useState({})

  useEscapeKey(onClose)

  const toggle = (i) => setOpen(s => ({ ...s, [i]: !s[i] }))

  const isAr = (guide?.language || lang) === 'ar'
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
            loadErr
              ? <GuideUnavailable t={t} err={loadErr} canRestore={canRestore} onRecover={onRecover} onRetry={retryLoad} />
              : <div style={{textAlign:'center',padding:'2rem'}}><Loader2 size={20} className="spin" /></div>
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
                              const text = typeof b === 'string' ? b
                                : (b && typeof b === 'object') ? (b.text || b.fact || b.point || JSON.stringify(b))
                                : String(b ?? '')
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
                      const term = (k && typeof k === 'object') ? k.term : k
                      const def  = (k && typeof k === 'object') ? k.definition : ''
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
// `ask(q)` (from App) handles auth refresh + expired-guide restore; it rejects
// with 'handled' when it already opened sign-in, 'expired', or a friendly message.
function ChatModal({ onClose, t, isAr, needsSignIn, onSignIn, ask }) {
  const [msgs, setMsgs] = useState([{ role: 'ai', text: t.chatIntro }])
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
      const a = await ask(q)
      setMsgs(m => [...m, { role: 'ai', text: a || t.chatNoAnswer }])
    } catch (e) {
      if (e?.message !== 'handled') {
        const text = e?.message === 'expired' ? t.guideExpiredLong
          : (e?.name === 'TypeError' || e?.name === 'AbortError') ? t.errNetwork
          : (e?.message || t.errGeneric)
        setMsgs(m => [...m, { role: 'ai', text }])
      }
    }
    setLoading(false)
  }

  const send = () => {
    const q = input.trim()
    if (!q) return
    setInput('')
    sendMsg(q)
  }

  const showSuggestions = msgs.length === 1 && !loading && !needsSignIn

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box chat-box" style={{maxWidth:520,direction:isAr?'rtl':'ltr'}} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span style={{fontWeight:600,color:'var(--text-primary)',display:'flex',alignItems:'center',gap:'0.5rem'}}>
            <MessageSquare size={15} /> {t.chatTitle}
          </span>
          <button className="modal-close" onClick={onClose} aria-label={t.close}><X size={16} /></button>
        </div>
        <div className="chat-msgs">
          {msgs.map((m, i) => (
            <div key={i} className={`chat-msg ${m.role}`}>
              {/* answers come in the guide's language; each message takes its own direction */}
              <div className="chat-bubble" dir="auto" style={{position:'relative'}}>
                {m.text}
                {m.role === 'ai' && i > 0 && (
                  <button onClick={() => navigator.clipboard?.writeText(m.text).then(() => toast(t.referCopied), () => {})}
                    style={{position:'absolute',top:4,insetInlineEnd:4,background:'none',border:'none',cursor:'pointer',color:'var(--text-muted)',padding:3,borderRadius:4,opacity:0.6,lineHeight:1}}>
                    <Copy size={11} />
                  </button>
                )}
              </div>
            </div>
          ))}
          {showSuggestions && (
            <div style={{padding:'0.5rem 0.75rem 0.25rem',display:'flex',flexWrap:'wrap',gap:'0.35rem'}}>
              {t.chatSuggest.map(q => (
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
        {needsSignIn ? (
          <div className="chat-input-row" style={{justifyContent:'center'}}>
            <button className="submit-btn" style={{flex:'none',padding:'0.6rem 1.1rem',fontSize:'0.85rem'}} onClick={onSignIn}>
              <LogIn size={14} /> {t.chatSignIn}
            </button>
          </div>
        ) : (
          <div className="chat-input-row">
            <input
              className="chat-input"
              dir={input ? 'auto' : undefined}
              placeholder={t.chatPh}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && send()}
              autoFocus
            />
            <button className="submit-btn" style={{flex:'none',padding:'0.55rem 1rem',fontSize:'0.85rem'}} onClick={send} disabled={loading}>
              {loading ? <Loader2 size={14} className="spin" /> : t.chatSend}
            </button>
          </div>
        )}
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
const TERMS_EN_TAIL = `3. YOUR FILES AND PRIVACY
• Files you upload are processed entirely in server memory and never written to permanent storage.
• No copy of your document is retained after processing is complete.
• Generated study guides are held in temporary server memory for up to 15 minutes so you can download them, then deleted automatically.
• We do not access, read, or review the content of your files. Your documents are your own.
• Optional sharing: if you click "Share" on a guide, you choose to publish that guide's generated content (not your original file) to a public link that anyone with the URL can view. Only guides you explicitly share are stored; unshared guides remain memory-only and are wiped as above.
• Usage counters: to apply the usage limits we keep a number and timestamps (never your files, text or study guides) in our database (Supabase), against a random device ID kept in your browser, your IP address or your account ID.

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
• Supabase — for authentication and usage counters (subject to Supabase's terms at supabase.com).
• YouTube — for video caption and audio extraction (subject to YouTube's Terms of Service).

8. LIMITATION OF LIABILITY
• The service is provided "as is", without warranties of any kind — express or implied.
• We are not liable for any direct, indirect, incidental, or consequential loss arising from use of this service.
• We do not guarantee uninterrupted uptime, accuracy of AI results, or permanent availability of the service.

9. CHANGES TO TERMS
These terms may be updated at any time without prior notice. Continued use of the service after changes constitutes your acceptance of the revised terms.

10. CONTACT
Questions or concerns: hello@souc.ai`

const TERMS_EN = `TERMS AND CONDITIONS
Alimne (علّمني) — a souc.ai product
Effective: May 2026 · Updated: October 2026

1. ABOUT THIS SERVICE
Alimne is an AI-powered study tool registered under the souc.ai platform. It converts PowerPoint files, PDFs, YouTube videos, and text into structured exam study guides. The service is provided free of charge for educational and personal use, subject to the fair-use limits in section 2.

2. FREE USE, FAIR USE & EXISTING SUBSCRIPTIONS
• Alimne is free to use. No payment, card or paid plan is needed.
• Without an account you can make your first {FREE_GUIDES}. After that, a free account is required to make more guides; creating one costs nothing. The sample lecture, and viewing or downloading the guides you already made, stay open to everyone.
• Fair-use limits apply to accounts: to keep Alimne free and available to everyone, we limit how many guides can be generated each day per account, per network and across the whole service.
• These limits may change at any time, and when Alimne is busy a request may wait in a queue or be asked to try again later.
• If you subscribed before Alimne became free, you can manage or cancel your subscription at any time from Account, via the billing portal. No refunds for partial months.
• Payments for existing subscriptions are processed by Stripe, Inc. and are subject to Stripe's Terms of Service.

${TERMS_EN_TAIL}`

const TERMS_EN_LEGACY = `TERMS AND CONDITIONS
Alimne (علّمني) — a souc.ai product
Effective: May 2026

1. ABOUT THIS SERVICE
Alimne is an AI-powered study tool registered under the souc.ai platform. It converts PowerPoint files, PDFs, YouTube videos, and text into structured exam study guides. The service is provided for educational and personal use on a freemium subscription model.

2. SUBSCRIPTION & BILLING
• Free: 2 anonymous previews (no account needed), then 3 free guides on sign-up and 3 free guides every month.
• Pro plan: $2.99/month (billed via Stripe). Includes 30 guides per month plus priority processing.
• Free and Pro monthly allowances reset at the start of each calendar month.
• Subscriptions can be cancelled anytime via the billing portal. No refunds for partial months.
• Payments are processed by Stripe, Inc. and are subject to Stripe's Terms of Service.

${TERMS_EN_TAIL}`


const TERMS_AR_TAIL = `٣. ملفاتك وخصوصيتك
• تُعالَج الملفات التي ترفعها في ذاكرة الخادم فقط ولا تُكتب على أي تخزين دائم.
• لا تُحتفظ بأي نسخة من مستنداتك بعد اكتمال المعالجة.
• تُحفظ أدلة الدراسة المولَّدة في ذاكرة الخادم المؤقتة لمدة 15 دقيقة للتنزيل ثم تُحذف تلقائياً.
• لا نطّلع على محتوى ملفاتك ولا نراجعها. مستنداتك ملكك وحدك.
• المشاركة الاختيارية: إذا ضغطت «مشاركة» على دليل فأنت تختار نشر المحتوى المولَّد لهذا الدليل (وليس ملفك الأصلي) على رابط عام يمكن لأي شخص يملك الرابط عرضه. لا يُخزَّن إلا الأدلة التي تشاركها صراحةً؛ أما الأدلة غير المشاركة فتبقى في الذاكرة فقط وتُحذف كما سبق.
• عدّادات الاستخدام: لتطبيق حدود الاستخدام نحتفظ برقم وتواريخ فقط (دون أي من ملفاتك أو نصوصك أو أدلتك) في قاعدة بياناتنا (Supabase)، مرتبطة بمعرّف عشوائي لجهازك محفوظ في متصفحك أو بعنوان IP أو بمعرّف حسابك.

٤. إخلاء مسؤولية المحتوى المولَّد بالذكاء الاصطناعي
• تُولَّد أدلة الدراسة بواسطة الذكاء الاصطناعي (Groq API / نماذج Llama وWhisper). قد يحتوي الناتج على أخطاء أو إغفالات.
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
• Supabase — للمصادقة وعدّادات الاستخدام (خاضع لشروط Supabase على supabase.com).
• YouTube — لاستخراج التسميات التوضيحية والصوت (خاضع لشروط خدمة YouTube).

٨. تحديد المسؤولية
• تُقدَّم الخدمة كما هي دون أي ضمانات صريحة أو ضمنية.
• لا نتحمل أي مسؤولية عن أي خسائر مباشرة أو غير مباشرة أو عرضية ناجمة عن استخدام الخدمة.
• لا نضمن استمرارية التشغيل أو دقة نتائج الذكاء الاصطناعي أو التوافر الدائم للخدمة.

٩. التغييرات على الشروط
قد تُحدَّث هذه الشروط في أي وقت دون إشعار مسبق. استمرارك في استخدام الخدمة بعد أي تغيير يعني قبولك للشروط المعدَّلة.

١٠. التواصل
للأسئلة والاستفسارات: hello@souc.ai`

const TERMS_AR = `الشروط والأحكام
Alimne (علّمني) — منتج souc.ai
ساري المفعول: مايو 2026 · آخر تحديث: أكتوبر 2026

١. عن هذه الخدمة
Alimne (علّمني) أداة دراسة مدعومة بالذكاء الاصطناعي مسجّلة تحت منصة souc.ai. تحوّل ملفات PowerPoint وPDF ومقاطع YouTube والنصوص إلى أدلة دراسة منظمة للاختبارات. تُقدَّم الخدمة مجاناً للاستخدام التعليمي والشخصي، وفق حدود الاستخدام العادل الواردة في البند ٢.

٢. الاستخدام المجاني والاستخدام العادل والاشتراكات القائمة
• علّمني مجاني للاستخدام. لا حاجة إلى دفع أو بطاقة أو خطة مدفوعة.
• يمكنك إنشاء {FREE_GUIDES} دون حساب. بعد ذلك يلزم حساب مجاني لإنشاء المزيد من الأدلة، وإنشاء الحساب لا يكلّف شيئاً. أما المحاضرة النموذجية وعرض الأدلة التي أنشأتها أو تنزيلها فتبقى متاحة للجميع.
• تُطبَّق حدود الاستخدام العادل على الحسابات: لإبقاء علّمني مجانياً ومتاحاً للجميع، نضع حداً يومياً لعدد الأدلة التي يمكن إنشاؤها لكل حساب ولكل شبكة وللخدمة ككل.
• قد تتغيّر هذه الحدود في أي وقت، وعندما يكون علّمني مزدحماً قد ينتظر طلبك في طابور أو يُطلب منك المحاولة لاحقاً.
• إذا كنت قد اشتركت قبل أن يصبح علّمني مجانياً، يمكنك إدارة اشتراكك أو إلغاؤه في أي وقت من «حسابك» عبر بوابة الفوترة. لا يوجد استرداد للأشهر الجزئية.
• تُعالَج مدفوعات الاشتراكات القائمة بواسطة Stripe وتخضع لشروط خدمة Stripe.

${TERMS_AR_TAIL}`

const TERMS_AR_LEGACY = `الشروط والأحكام
Alimne (علّمني) — منتج souc.ai
ساري المفعول: مايو 2026

١. عن هذه الخدمة
Alimne (علّمني) أداة دراسة مدعومة بالذكاء الاصطناعي مسجّلة تحت منصة souc.ai. تحوّل ملفات PowerPoint وPDF ومقاطع YouTube والنصوص إلى أدلة دراسة منظمة للاختبارات. تُقدَّم الخدمة للاستخدام التعليمي والشخصي وفق نموذج اشتراك مجاني مدفوع.

٢. الاشتراك والفوترة
• مجاناً: محاولة تجريبية واحدة (بالإضافة إلى معاينة واحدة بدون حساب).
• الخطة الاحترافية: 2.99$ شهرياً (عبر Stripe). تشمل 30 رمزاً شهرياً.
• تُعاد رموز الخطة الاحترافية في بداية كل شهر.
• يمكن إلغاء الاشتراك في أي وقت عبر بوابة الفوترة. لا يوجد استرداد للأشهر الجزئية.
• تُعالَج المدفوعات بواسطة Stripe وتخضع لشروط خدمة Stripe.

${TERMS_AR_TAIL}`


// The account rule when NO guide is free without an account (ANON_FREE_USES=0): it replaces the "first N guides" bullet
const TERMS_EN_RULE_0 = '• A free account is required to make study guides; creating one costs nothing. The sample lecture, and viewing or downloading the guides you already made, stay open to everyone.'
const TERMS_AR_RULE_0 = '• يلزم حساب مجاني لإنشاء أدلة الدراسة، وإنشاء الحساب لا يكلّف شيئاً. أما المحاضرة النموذجية وعرض الأدلة التي أنشأتها أو تنزيلها فتبقى متاحة للجميع.'

// Free mode only (token mode makes no such copy): what the browser keeps for the Google sign-in round trip.
// Shown at the end of section 3 (your files and privacy). It must stay true to signinStash above.
const TERMS_STASH = {
  en: '• Signing in: if a file, link or pasted text is waiting when you leave the page to sign in with Google, it is kept in your own browser only (it is not uploaded until you tap Generate) so that it is still there when you return. That copy is deleted as soon as it is restored, or when you sign out; a copy older than 30 minutes is never used and is deleted the next time Alimne opens in that browser.',
  ar: '• تسجيل الدخول: إذا كان لديك ملف أو رابط أو نص ملصق ينتظر عندما تغادر الصفحة لتسجيل الدخول عبر Google، فإنه يُحفظ في متصفحك فقط (ولا يُرفع قبل أن تضغط «توليد») ليبقى موجوداً عند عودتك. تُحذف هذه النسخة فور استعادتها أو عند تسجيل خروجك، ولا تُستخدم أي نسخة مضى عليها أكثر من 30 دقيقة، بل تُحذف عند فتح علّمني في ذلك المتصفح في المرة التالية.',
}

// The Terms as shown. Free mode names the real number of guides an anonymous visitor may make
// ({FREE_GUIDES} in the text, from /api/config; with 0 the bullet says an account is required) and discloses
// the sign-in copy; token mode (ALIMNE_FREE_MODE=0) is the old text as it was.
const termsText = (lang, freeMode, n) => {
  const isAr = lang === 'ar'
  if (!freeMode) return isAr ? TERMS_AR_LEGACY : TERMS_EN_LEGACY
  const k = countInt(n) ?? FREE_USES_DEFAULT
  const guides = isAr
    ? (k === 1 ? 'دليلك الأول' : k === 2 ? 'أول دليلين' : `أول ${k} ${k <= 10 ? 'أدلة' : 'دليلاً'}`)
    : (k === 1 ? 'guide' : `${k} guides`)
  const section4 = isAr ? '\n\n٤. ' : '\n\n4. '
  return (isAr ? TERMS_AR : TERMS_EN).split('\n')
    .map(line => !line.includes('{FREE_GUIDES}') ? line : k === 0 ? (isAr ? TERMS_AR_RULE_0 : TERMS_EN_RULE_0) : line.replace('{FREE_GUIDES}', guides))
    .join('\n')
    .replace(section4, `\n${isAr ? TERMS_STASH.ar : TERMS_STASH.en}${section4}`)
}

function TermsModal({ lang, onClose, freeMode = true, freeUses = FREE_USES_DEFAULT }) {
  const isAr = lang === 'ar'
  const content = termsText(lang, freeMode, freeUses)
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
// Inline role=alert messages (not toasts), confirm-email panel with resend,
// forgot password, and an in-app-browser notice instead of a Google button that
// can't work there. `gate` (free mode): the sign-in gate opened this modal, so it says why, for as long
// as the modal is open: { reason, uses, text } = the cause ('device' | 'network' | 'pool'), the allowance
// (0 included) and, for a cause this client does not know, the server's own sentence.
// `beforeLeave` runs just before the page leaves for Google (it keeps what was waiting, in this browser);
// `leaveFailed` when the page did not leave after all.
function LoginModal({ onClose, lang, sbClient, initialMode, initialEmail, notice, freeMode = true, fair = null, gate = null, beforeLeave = null, leaveFailed = null }) {
  const t = tFor(lang, freeMode)
  const isAr = lang === 'ar'
  const gateText = freeMode && gate ? signinText(t, gate.reason, gate.uses, gate.text) : null
  const [mode, setMode]         = useState(initialMode === 'signup' ? 'signup' : 'signin')
  const [email, setEmail]       = useState(initialEmail || '')
  const [password, setPassword] = useState('')
  const [busy, setBusy]         = useState(false)
  const [gBusy, setGBusy]       = useState(false)
  const [msg, setMsg]           = useState(notice || null)   // { type: 'error' | 'ok', text }
  const [needConfirm, setNeedConfirm] = useState(false)     // email_not_confirmed → offer resend
  const [sentTo, setSentTo]     = useState('')              // sign-up sent → "check your inbox"
  const [copied, setCopied]     = useState(false)
  const timers = useRef([])
  useEffect(() => () => timers.current.forEach(clearTimeout), [])
  useEscapeKey(onClose)
  const isSignup = mode === 'signup'
  const later = (fn, ms) => { const id = setTimeout(fn, ms); timers.current.push(id); return id }

  // Runs an auth call with a 20s guard so a hung request never leaves the button spinning.
  const guarded = async (fn) => {
    if (!sbClient) { setMsg({ type: 'error', text: t.authUnavailable }); return }
    setBusy(true)
    const tm = later(() => { setBusy(false); setMsg({ type: 'error', text: t.authTimeout }) }, 20000)
    try { await fn() }
    catch (err) { setMsg({ type: 'error', text: authErrText(t, err) }) }
    finally { clearTimeout(tm); setBusy(false) }
  }

  const emailAuth = (e) => {
    e?.preventDefault?.()
    if (busy) return
    const em = email.trim()
    if (!EMAIL_RE.test(em) || password.length < 6) { setMsg({ type: 'error', text: t.authWeak }); return }
    setMsg(null); setNeedConfirm(false)
    return guarded(async () => {
      if (isSignup) {
        const { data, error } = await sbClient.auth.signUp({ email: em, password, options: { emailRedirectTo: window.location.origin } })
        if (error) {
          if (error.code === 'user_already_exists' || error.code === 'email_exists') setMode('signin')
          throw error
        }
        // Email confirmation on + address already registered → a user with no identities
        if (data?.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
          setMode('signin'); setMsg({ type: 'error', text: t.accountExists }); return
        }
        if (!data?.session) { setSentTo(em); return }
        onClose()
      } else {
        const { error } = await sbClient.auth.signInWithPassword({ email: em, password })
        if (error) { if (error.code === 'email_not_confirmed') setNeedConfirm(true); throw error }
        onClose()
      }
    })
  }

  const resend = (em) => guarded(async () => {
    const { error } = await sbClient.auth.resend({ type: 'signup', email: em, options: { emailRedirectTo: window.location.origin } })
    if (error) throw error
    setMsg({ type: 'ok', text: t.resent })
  })

  const forgot = () => {
    if (busy) return
    const em = email.trim()
    if (!EMAIL_RE.test(em)) { setMsg({ type: 'error', text: t.enterEmailFirst }); return }
    setMsg(null); setNeedConfirm(false)
    return guarded(async () => {
      const { error } = await sbClient.auth.resetPasswordForEmail(em, { redirectTo: window.location.origin })
      if (error) throw error
      setMsg({ type: 'ok', text: t.resetSent(em) })
    })
  }

  const google = async () => {
    if (gBusy) return
    if (!sbClient) { setMsg({ type: 'error', text: t.authUnavailable }); return }
    setGBusy(true); setMsg(null)
    const tm = later(() => setGBusy(false), 20000)
    try {
      // The page is about to leave for Google and will forget what it holds: first keep whatever was waiting
      // (a chosen file, pasted text), in this browser only. Best effort and time-limited: it never stops the sign-in.
      try { await beforeLeave?.() } catch { /* the sign-in matters more */ }
      const { error } = await sbClient.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin } })
      if (error) throw error      // success: the browser is on its way to Google
    } catch (err) {
      clearTimeout(tm); setGBusy(false); setMsg({ type: 'error', text: authErrText(t, err) })
      try { leaveFailed?.() } catch { /* ignore */ }   // the page stayed: everything is still in memory, so the copy goes
    }
  }

  const copyLink = async () => {
    try { await navigator.clipboard.writeText(window.location.origin); setCopied(true); later(() => setCopied(false), 2000) }
    catch { setMsg({ type: 'ok', text: window.location.origin }) }   // clipboard blocked → show it to copy by hand
  }

  const inputStyle = {width:'100%', padding:'0.7rem 0.9rem', marginBottom:'0.6rem', borderRadius:10,
    border:'1px solid var(--border, rgba(120,140,180,0.3))', background:'var(--input-bg, rgba(255,255,255,0.04))',
    color:'var(--text-primary)', fontSize:'0.9rem', textAlign: isAr ? 'right' : 'left', direction:'ltr'}
  const linkBtn = {background:'none', border:'none', color:'var(--accent)', fontSize:'0.8rem', cursor:'pointer', padding:'0.25rem', fontFamily:'inherit'}
  const alertBox = msg && (
    <div role="alert" style={{color: msg.type === 'error' ? '#ef4444' : '#22c55e', fontSize:'0.82rem', lineHeight:1.5,
      margin:'0 0 0.7rem', whiteSpace:'normal', textAlign: isAr ? 'right' : 'left', wordBreak:'break-word'}}>{msg.text}</div>
  )
  return (
    <div className="modal-overlay" onClick={onClose} style={{alignItems:'center'}}>
      <div className="modal-box" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}
        style={{maxWidth:380, width:'92vw', direction: isAr ? 'rtl' : 'ltr', padding:'2rem', textAlign:'center', position:'relative', overflowY:'auto'}}>
        <button className="modal-close" onClick={onClose} aria-label={t.close}
          style={{position:'absolute', top:10, insetInlineEnd:10}}><X size={16} /></button>
        <div style={{marginBottom:'1.5rem'}}>
          <div style={{
            width:52, height:52, borderRadius:16, margin:'0 auto 1rem',
            background:'linear-gradient(135deg,var(--navy-600),var(--navy-400))',
            display:'flex', alignItems:'center', justifyContent:'center',
            boxShadow:'0 4px 18px var(--accent-glow)'
          }}>
            <AlimneGlyph size={26} />
          </div>
          <div style={{fontWeight:700, fontSize:'1.15rem', color:'var(--text-primary)', marginBottom:'0.4rem'}}>
            {sentTo ? t.checkInboxTitle : isSignup ? t.loginTitleSignup : t.loginTitle}
          </div>
          {/* Why this modal opened: the free guides are used and a free account is needed to make more */}
          {gateText && !sentTo && (
            <div role="status" style={{display:'flex', alignItems:'flex-start', gap:'0.45rem', margin:'0.2rem 0 0.75rem', padding:'0.65rem 0.8rem',
              borderRadius:10, background:'rgba(251,191,36,0.1)', border:'1px solid rgba(251,191,36,0.4)',
              fontSize:'0.84rem', fontWeight:600, lineHeight:1.5, color:'var(--text-primary)', textAlign: isAr ? 'right' : 'left'}}>
              <LogIn size={15} color="#f59e0b" style={{flexShrink:0, marginTop:2}} />
              <span>{gateText}</span>
            </div>
          )}
          {!sentTo && (
            <div style={{fontSize:'0.82rem', color:'var(--text-muted)', lineHeight:1.55}}>
              {isSignup ? t.loginSubSignup : t.loginSub}
            </div>
          )}
          {/* Why bother (free mode): only things an account really gets — see perksOf() */}
          {!sentTo && freeMode && (
            <div role="note" style={{display:'flex', alignItems:'flex-start', gap:'0.45rem', marginTop:'0.85rem', padding:'0.6rem 0.75rem',
              borderRadius:10, background:'rgba(79,142,247,0.08)', border:'1px solid rgba(79,142,247,0.2)',
              fontSize:'0.78rem', lineHeight:1.5, color:'var(--text-secondary)', textAlign: isAr ? 'right' : 'left'}}>
              <Sparkles size={14} color="var(--accent)" style={{flexShrink:0, marginTop:2}} />
              <span>{t.perksNote(perksOf(t, fair))}</span>
            </div>
          )}
        </div>

        {sentTo ? (
          <div>
            <Mail size={26} color="var(--accent)" style={{marginBottom:'0.6rem'}} />
            <div style={{fontSize:'0.86rem', color:'var(--text-secondary)', lineHeight:1.55, marginBottom:'1rem', wordBreak:'break-word'}}>
              {t.checkInbox(sentTo)}
            </div>
            {alertBox}
            <button className="submit-btn" disabled={busy} onClick={() => resend(sentTo)}
              style={{width:'100%', justifyContent:'center', padding:'0.7rem 1.25rem', fontSize:'0.88rem', marginBottom:'0.6rem', opacity: busy ? 0.7 : 1}}>
              {busy ? <Loader2 size={15} className="spin" /> : <><Mail size={14} /> {t.resendEmail}</>}
            </button>
            <button type="button" style={linkBtn} onClick={() => { setSentTo(''); setMode('signin'); setMsg(null) }}>
              {t.backToSignIn}
            </button>
          </div>
        ) : (
          <>
            {IN_APP && (
              <div role="note" style={{padding:'0.7rem 0.8rem', borderRadius:10, marginBottom:'1rem',
                background:'rgba(251,191,36,0.08)', border:'1px solid rgba(251,191,36,0.3)',
                fontSize:'0.78rem', lineHeight:1.5, color:'var(--text-secondary)', textAlign: isAr ? 'right' : 'left'}}>
                {t.inAppGoogle}
                <button type="button" className="ctrl-btn" onClick={copyLink}
                  style={{marginTop:'0.55rem', width:'100%', justifyContent:'center'}}>
                  {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? t.referCopied : t.copyLink}
                </button>
              </div>
            )}
            <form onSubmit={emailAuth} noValidate>
              <input
                type="email" value={email} onChange={e => setEmail(e.target.value)}
                placeholder={t.emailPh} autoComplete="username" inputMode="email" style={inputStyle}
              />
              <input
                type="password" value={password} onChange={e => setPassword(e.target.value)}
                placeholder={t.passwordPh} autoComplete={isSignup ? 'new-password' : 'current-password'}
                style={{...inputStyle, marginBottom: isSignup ? '0.8rem' : '0.3rem'}}
              />
              {!isSignup && (
                <div style={{textAlign: isAr ? 'left' : 'right', marginBottom:'0.5rem'}}>
                  <button type="button" onClick={forgot} style={{...linkBtn, fontSize:'0.75rem'}}>{t.forgotPw}</button>
                </div>
              )}
              {alertBox}
              {needConfirm && (
                <button type="button" className="ctrl-btn" disabled={busy} onClick={() => resend(email.trim())}
                  style={{width:'100%', justifyContent:'center', marginBottom:'0.7rem'}}>
                  <Mail size={13} /> {t.resendConfirm}
                </button>
              )}
              <button
                type="submit"
                className="submit-btn"
                disabled={busy}
                style={{width:'100%', justifyContent:'center', padding:'0.75rem 1.25rem', fontSize:'0.9rem', marginBottom:'0.75rem', opacity: busy ? 0.7 : 1}}
              >
                {busy ? <Loader2 size={15} className="spin" /> : (isSignup ? t.emailBtnSignup : t.emailBtn)}
              </button>
            </form>
            <button
              type="button"
              onClick={() => { setMode(isSignup ? 'signin' : 'signup'); setMsg(null); setNeedConfirm(false) }}
              style={{...linkBtn, marginBottom:'1rem'}}
            >
              {isSignup ? t.haveAccount : t.noAccount}
            </button>
            {!IN_APP && (
              <>
                <div style={{display:'flex', alignItems:'center', gap:'0.75rem', margin:'0 0 1rem', color:'var(--text-muted)', fontSize:'0.75rem'}}>
                  <span style={{flex:1, height:1, background:'var(--border, rgba(120,140,180,0.25))'}} />
                  {t.orDivider}
                  <span style={{flex:1, height:1, background:'var(--border, rgba(120,140,180,0.25))'}} />
                </div>
                <button
                  type="button"
                  className="submit-btn"
                  disabled={gBusy}
                  style={{width:'100%', justifyContent:'center', padding:'0.75rem 1.25rem', fontSize:'0.9rem', gap:'0.65rem', opacity: gBusy ? 0.7 : 1}}
                  onClick={google}
                >
                  {gBusy ? <Loader2 size={18} className="spin" /> : (
                    /* Google logo */
                    <svg width="18" height="18" viewBox="0 0 48 48" style={{flexShrink:0}}>
                      <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 2.9l5.7-5.7C34.5 6.6 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.6-.4-3.9z"/>
                      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 19 13 24 13c3.1 0 5.8 1.1 8 2.9l5.7-5.7C34.5 6.6 29.6 4 24 4 16.3 4 9.7 8.4 6.3 14.7z"/>
                      <path fill="#4CAF50" d="M24 44c5.4 0 10.3-2 14-5.3l-6.5-5.5C29.6 35 26.9 36 24 36c-5.3 0-9.7-3.3-11.3-8H6.3C9.7 35.6 16.3 40 24 44z"/>
                      <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.3 4.1-4.3 5.5l6.5 5.5C37.2 35.8 44 30.6 44 24c0-1.3-.1-2.6-.4-3.9z"/>
                    </svg>
                  )}
                  {t.loginBtn}
                </button>
              </>
            )}
            <div style={{marginTop:'1rem', fontSize:'0.73rem', color:'var(--text-muted)'}}>
              {isAr
                ? 'بالمتابعة، أنت توافق على شروطنا وأحكامنا'
                : 'By continuing, you agree to our Terms & Conditions'}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Set-new-password Modal (opened by a password-recovery link) ───────────────
function SetPasswordModal({ onClose, lang, sbClient }) {
  const t = T[lang] || T['en']
  const isAr = lang === 'ar'
  const [pw, setPw]     = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg]   = useState(null)
  const [done, setDone] = useState(false)
  useEscapeKey(onClose)
  useEffect(() => { if (!done) return; const id = setTimeout(onClose, 1800); return () => clearTimeout(id) }, [done, onClose])
  const submit = async (e) => {
    e.preventDefault()
    if (busy || done) return
    if (pw.length < 6) { setMsg({ type: 'error', text: t.pwTooShort }); return }
    setBusy(true); setMsg(null)
    const tm = setTimeout(() => { setBusy(false); setMsg({ type: 'error', text: t.authTimeout }) }, 20000)
    try {
      const { error } = await sbClient.auth.updateUser({ password: pw })
      if (error) throw error
      setMsg({ type: 'ok', text: t.pwUpdated }); setDone(true)
    } catch (err) { setMsg({ type: 'error', text: authErrText(t, err) }) }
    finally { clearTimeout(tm); setBusy(false) }
  }
  return (
    <div className="modal-overlay" onClick={onClose} style={{alignItems:'center'}}>
      <div className="modal-box" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}
        style={{maxWidth:380, width:'92vw', direction: isAr ? 'rtl' : 'ltr'}}>
        <div className="modal-header">
          <span style={{fontWeight:700, color:'var(--text-primary)'}}>{t.newPwTitle}</span>
          <button className="modal-close" onClick={onClose} aria-label={t.close}><X size={16} /></button>
        </div>
        <form onSubmit={submit} style={{padding:'1.25rem'}}>
          <div style={{fontSize:'0.84rem', color:'var(--text-muted)', marginBottom:'0.9rem', lineHeight:1.5}}>{t.newPwSub}</div>
          <input type="password" value={pw} autoFocus autoComplete="new-password" placeholder={t.newPwPh}
            onChange={e => { setPw(e.target.value); setMsg(null) }}
            style={{width:'100%', padding:'0.7rem 0.9rem', borderRadius:10, marginBottom:'0.7rem',
              border:'1px solid var(--border, rgba(120,140,180,0.3))', background:'var(--input-bg, rgba(255,255,255,0.04))',
              color:'var(--text-primary)', fontSize:'0.9rem', direction:'ltr', textAlign: isAr ? 'right' : 'left'}} />
          {msg && <div role="alert" style={{color: msg.type === 'error' ? '#ef4444' : '#22c55e', fontSize:'0.82rem', marginBottom:'0.7rem', lineHeight:1.5}}>{msg.text}</div>}
          <button type="submit" className="submit-btn" disabled={busy || done}
            style={{width:'100%', justifyContent:'center', padding:'0.75rem', opacity: busy ? 0.7 : 1}}>
            {busy ? <Loader2 size={15} className="spin" /> : t.newPwBtn}
          </button>
        </form>
      </div>
    </div>
  )
}

// ── Upgrade Modal ──────────────────────────────────────────────────────────────
// Token mode only (ALIMNE_FREE_MODE=0): never rendered in free mode.
function UpgradeModal({ onClose, onUpgrade, onManage, isSubscribed, lang }) {
  const t = tFor(lang, false)
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

// ── Account Modal ──────────────────────────────────────────────────────────────
function AccountModal({ onClose, onManage, onUpgrade, onSignOut, userInfo, isSubscribed, lang, loadErr, onRetry, freeMode = true, fair = null }) {
  const t = tFor(lang, freeMode)
  const isAr = lang === 'ar'
  const status = String(userInfo?.subscription_status || 'free').toLowerCase()
  const liveSub = hasLiveSub(userInfo)
  const statusLabel = liveSub ? t.statusActive
    : status === 'canceled' ? t.statusCanceled
    : (status === 'past_due' || status === 'unpaid') ? t.statusPastDue
    : t.planFree
  const periodEnd = userInfo?.subscription_period_end ? String(userInfo.subscription_period_end).slice(0, 10) : ''
  const canManage = liveSub || !!userInfo?.has_billing
  const billingStatus = liveSub || status === 'canceled' || status === 'past_due' || status === 'unpaid'
  const row = (label, value) => (
    <div style={{
      display:'flex', justifyContent:'space-between', gap:'1rem', padding:'0.55rem 0',
      borderBottom:'1px solid rgba(255,255,255,0.08)', fontSize:'0.86rem'
    }}>
      <span style={{color:'var(--text-muted)'}}>{label}</span>
      <span style={{color:'var(--text-primary)', fontWeight:600}}>{value}</span>
    </div>
  )
  return (
    <div className="modal-overlay" onClick={onClose} style={{alignItems:'center'}}>
      <div className="modal-box" onClick={e => e.stopPropagation()}
        style={{maxWidth:420, width:'92vw', direction: isAr ? 'rtl' : 'ltr'}}>
        <div className="modal-header">
          <span style={{fontWeight:700, color:'var(--text-primary)', display:'flex', alignItems:'center', gap:'0.4rem'}}>
            <User size={15} /> {t.accountTitle}
          </span>
          <button className="modal-close" onClick={onClose} aria-label={t.close}><X size={16} /></button>
        </div>
        <div style={{padding:'1.25rem'}}>
          <div style={{display:'flex', alignItems:'center', gap:'0.75rem', marginBottom:'1rem'}}>
            {userInfo?.avatar_url
              ? <img src={userInfo.avatar_url} alt="" style={{width:40, height:40, borderRadius:'50%', objectFit:'cover'}} />
              : <div style={{width:40, height:40, borderRadius:'50%', display:'grid', placeItems:'center', background:'rgba(79,142,247,0.12)'}}><User size={18} /></div>}
            <div style={{minWidth:0}}>
              {userInfo?.name && <div style={{fontWeight:700, color:'var(--text-primary)'}}>{userInfo.name}</div>}
              <div dir="ltr" style={{fontSize:'0.82rem', color:'var(--text-muted)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
                {userInfo?.email}
              </div>
            </div>
          </div>
          {loadErr && (
            <div role="alert" style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:'0.5rem',
              padding:'0.55rem 0.7rem', marginBottom:'0.6rem', borderRadius:9, fontSize:'0.8rem', color:'#ef4444',
              background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.25)'}}>
              <span>{t.accountLoadFailed}</span>
              <button className="ctrl-btn" style={{padding:'0.25rem 0.6rem', fontSize:'0.75rem', flexShrink:0}} onClick={onRetry}>
                <RotateCcw size={12} /> {t.retry}
              </button>
            </div>
          )}
          {row(t.accountPlan, isSubscribed ? t.planPro : t.planFree)}
          {/* free mode: a status row only where billing is involved (otherwise it just repeats "Free") */}
          {(!freeMode || billingStatus) && row(t.accountStatus, statusLabel)}
          {isSubscribed && periodEnd && row(t.renewsOn, periodEnd)}
          {freeMode
            ? (fair?.user_daily ? row(t.accountAllowance, t.accountPerDay(fair.user_daily)) : null)
            : row(t.guidesLeft, userInfo?.tokens_remaining ?? '…')}
          <div style={{marginTop:'1.25rem', display:'flex', flexDirection:'column', gap:'0.6rem'}}>
            {/* people who still pay are told plainly, and can cancel */}
            {freeMode && liveSub && (
              <div style={{fontSize:'0.8rem', color:'var(--text-secondary)', lineHeight:1.55, textAlign:'center'}}>{t.accountFreeNote}</div>
            )}
            {canManage && (
              <button className="submit-btn" style={{width:'100%', justifyContent:'center', padding:'0.75rem'}} onClick={onManage}>
                {t.manageBtn}
              </button>
            )}
            {!freeMode && !liveSub && (
              <button className="submit-btn" style={{width:'100%', justifyContent:'center', padding:'0.75rem'}} onClick={onUpgrade}>
                <Sparkles size={15} /> {t.upgradeBtn}
              </button>
            )}
            {canManage && (
              <div style={{fontSize:'0.75rem', color:'var(--text-muted)', textAlign:'center'}}>{t.manageNote}</div>
            )}
            <button className="ctrl-btn" style={{width:'100%', justifyContent:'center', padding:'0.6rem', marginTop:'0.25rem'}} onClick={onSignOut}>
              <LogOut size={14} /> {t.signOut}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


// ── Email Capture Modal (shown before the paywall) ──────────────────────────────
// Token mode only (ALIMNE_FREE_MODE=0): its one trigger is the 402 signin_for_more.
function EmailCaptureModal({ onClose, onSubmit, onSkip, lang }) {
  const t = tFor(lang, false)
  const isAr = lang === 'ar'
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const submit = async (e) => {
    e.preventDefault()
    const v = email.trim()
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) { setErr(t.emailInvalid); return }
    setBusy(true); setErr('')
    try { await onSubmit(v) }
    catch { setErr(t.emailInvalid) }
    finally { setBusy(false) }
  }
  return (
    <div className="modal-overlay" onClick={onClose} style={{alignItems:'center'}}>
      <div className="modal-box" onClick={e => e.stopPropagation()}
        style={{maxWidth:400, width:'92vw', direction: isAr ? 'rtl' : 'ltr'}}>
        <div className="modal-header">
          <span style={{fontWeight:700, color:'var(--text-primary)', display:'flex', alignItems:'center', gap:'0.4rem'}}>
            <Mail size={15} color="var(--accent)" /> {t.emailCaptureTitle}
          </span>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>
        <form onSubmit={submit} style={{padding:'1.25rem'}}>
          <div style={{fontSize:'0.86rem', color:'var(--text-muted)', marginBottom:'1rem', lineHeight:1.5}}>{t.emailCaptureSub}</div>
          <input type="email" value={email} autoFocus required inputMode="email"
            onChange={e => { setEmail(e.target.value); setErr('') }}
            placeholder={t.emailPlaceholder}
            style={{width:'100%', padding:'0.7rem 0.9rem', borderRadius:10,
              border:'1px solid var(--border)', background:'rgba(255,255,255,0.03)',
              color:'var(--text-primary)', fontSize:'0.9rem', marginBottom: err ? '0.4rem' : '1rem',
              direction:'ltr', textAlign: isAr ? 'right' : 'left'}} />
          {err && <div style={{color:'#f87171', fontSize:'0.78rem', marginBottom:'0.8rem'}}>{err}</div>}
          <button type="submit" className="submit-btn" disabled={busy}
            style={{width:'100%', justifyContent:'center', padding:'0.75rem'}}>
            {busy ? '…' : (<><Sparkles size={15} /> {t.emailCaptureBtn}</>)}
          </button>
          <div style={{textAlign:'center', marginTop:'0.75rem'}}>
            <button type="button" onClick={onSkip}
              style={{background:'none', border:'none', color:'var(--text-muted)', fontSize:'0.75rem', cursor:'pointer', textDecoration:'underline'}}>
              {t.emailSkip}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}


// ── Nav counter for a signed-out visitor (free mode) ───────────────────────────
// "N free guides left", or "Sign in to continue — free" at 0. On a phone the nav hides its
// labels (.ctrl-label), so the bare number stays visible there (.gate-short).
function AnonCounter({ t, left, onClick }) {
  const n = left > 0 ? Math.floor(left) : 0
  const text = n > 0 ? t.anonLeft(n) : t.anonNone
  return (
    <button className="ctrl-btn" onClick={onClick} title={text} aria-label={text}
      style={{cursor:'pointer', borderColor: n > 0 ? 'rgba(34,197,94,0.3)' : 'rgba(251,191,36,0.5)', color: n > 0 ? '#22c55e' : '#fbbf24'}}>
      <Zap size={12} />
      <span className="gate-short" aria-hidden="true">{n}</span>
      <span className="ctrl-label"> {text}</span>
    </button>
  )
}

// ── Join card: after an anonymous visitor's first guide (free mode) ────────────
// Non-blocking and dismissible. It says how many free guides are left without an account and
// names only what an account really adds: more guides, Chat (needs an account) and the invite link.
function JoinCard({ t, isAr, fair, left = 0, limit, onJoin, onDismiss }) {
  return (
    <div className="glass" role="region" aria-label={t.joinTitle}
      style={{marginTop:'1rem', padding:'0.95rem 1.15rem', position:'relative', direction: isAr ? 'rtl' : 'ltr',
        border:'1px solid rgba(79,142,247,0.28)'}}>
      <button className="modal-close" onClick={onDismiss} aria-label={t.close}
        style={{position:'absolute', top:8, insetInlineEnd:8}}><X size={15} /></button>
      <div style={{display:'flex', alignItems:'center', gap:'0.45rem', marginBottom:'0.4rem', paddingInlineEnd:'1.8rem'}}>
        <Sparkles size={15} color="var(--accent)" />
        <span style={{fontWeight:700, fontSize:'0.9rem', color:'var(--text-primary)'}}>{t.joinTitle}</span>
      </div>
      <div style={{fontSize:'0.8rem', color:'var(--text-secondary)', lineHeight:1.55, marginBottom:'0.75rem', paddingInlineEnd:'1.8rem'}}>
        {t.joinBody(perksOf(t, fair), left, limit)}
      </div>
      <button className="submit-btn" style={{flex:'none', padding:'0.55rem 1.1rem', fontSize:'0.85rem'}} onClick={onJoin}>
        <LogIn size={14} /> {t.emailBtnSignup}
      </button>
    </div>
  )
}

// ── Invite a friend (signed in) ────────────────────────────────────────────────
// Free mode: a plain share link plus how many friends joined (the stats endpoint's `total`).
// Token mode keeps the old reward copy.
function ReferralCard({ t, isAr, freeMode, link, stats, copied, onCopy }) {
  const joined = freeMode && stats && typeof stats.total === 'number' ? stats.total : null
  return (
    <div className="glass" style={{marginTop:'1rem', padding:'1rem 1.25rem', direction: isAr ? 'rtl' : 'ltr'}}>
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'0.55rem', flexWrap:'wrap', gap:'0.4rem'}}>
        <div style={{display:'flex', alignItems:'center', gap:'0.45rem'}}>
          <Gift size={14} color="#fbbf24" />
          <span style={{fontWeight:700, fontSize:'0.88rem', color:'var(--text-primary)'}}>{t.referTitle}</span>
        </div>
        {freeMode ? (joined !== null && (
          <span style={{fontSize:'0.73rem', color: joined > 0 ? '#22c55e' : 'var(--text-muted)', fontWeight:500}}>{t.referJoined(joined)}</span>
        )) : (stats && (
          <span style={{fontSize:'0.73rem', color: stats.paid > 0 ? '#22c55e' : 'var(--text-muted)', fontWeight:500}}>{t.referStats(stats.paid)}</span>
        ))}
      </div>
      <div style={{fontSize:'0.78rem', color:'var(--text-muted)', marginBottom:'0.7rem', lineHeight:1.55}}>{t.referSub}</div>
      <div style={{display:'flex', gap:'0.5rem', alignItems:'center'}}>
        <input readOnly dir="ltr" value={link}
          style={{flex:1, minWidth:0, padding:'0.45rem 0.75rem', borderRadius:8,
            border:'1px solid var(--glass-border)', background:'var(--glass-light)',
            color:'var(--text-secondary)', fontSize:'0.78rem', fontFamily:'inherit', outline:'none', cursor:'text'}}
          onClick={e => e.target.select()} />
        <button className="ctrl-btn" style={copied ? {borderColor:'rgba(34,197,94,0.4)', color:'#22c55e'} : {}} onClick={onCopy}>
          {copied ? <CheckCircle2 size={13} /> : <Copy size={13} />}
          <span className="ctrl-label"> {copied ? t.referCopied : t.referCopy}</span>
        </button>
      </div>
    </div>
  )
}

// ── Main App ───────────────────────────────────────────────────────────────────
export default function App() {
  const [theme, setTheme]   = useState(() => ls.get('alimne_theme') === 'light' ? 'light' : 'dark')
  const [lang, setLang]     = useState(() => { const v = ls.get('alimne_lang'); return v === 'en' || v === 'ar' ? v : 'auto' })
  const [queue, setQueue]   = useState(loadSavedQueue)
  const [drag, setDrag]     = useState(false)
  const [running, setRunning] = useState(false)

  const [inputTab, setInputTab] = useState('upload')
  const [ytUrl, setYtUrl]     = useState('')
  const [pasteText, setPasteText] = useState('')
  const [pasteUrl, setPasteUrl]   = useState('')

  // Modals
  const [detail, setDetail] = useState('standard')
  const [summaryOnly, setSummaryOnly] = useState(false)
  const [includeQuiz, setIncludeQuiz] = useState(true)

  // Modals (they hold a queue item id)
  const [flashModal, setFlashModal] = useState(null)
  const [quizModal, setQuizModal]   = useState(null)
  const [chatModal, setChatModal]   = useState(null)
  const [mindmapModal, setMindmapModal] = useState(null)
  const [showHistory, setShowHistory]   = useState(false)
  const [showTerms, setShowTerms]       = useState(false)

  // Auth
  const [session, setSession]         = useState(null)
  const [userInfo, setUserInfo]       = useState(null)
  const [userInfoErr, setUserInfoErr] = useState(false)
  const [authEnabled, setAuthEnabled] = useState(true)   // production default until /api/config says otherwise
  const [showLogin, setShowLogin]     = useState(false)
  const [loginMode, setLoginMode]     = useState('signin')
  const [loginNotice, setLoginNotice] = useState(null)
  const [loginKey, setLoginKey]       = useState(0)
  const [showSetPw, setShowSetPw]     = useState(false)
  const [showUpgrade, setShowUpgrade] = useState(false)
  const [showAccount, setShowAccount] = useState(false)
  const [showEmailCapture, setShowEmailCapture] = useState(false)
  const [emailCaptured, setEmailCaptured] = useState(() => !!ls.get('alimne_lead'))
  const [authLoading, setAuthLoading] = useState(!!sb)
  const [anonInfo, setAnonInfo]       = useState(null)  // {limit, remaining} for signed-out users (token mode only)
  // Free mode is the default: /api/config only has to say free_mode:false to bring the token UI back
  const [freeMode, setFreeMode]       = useState(true)
  const [fair, setFair]               = useState(null)  // {device_daily, user_daily} from /api/config
  const [joinDismissed, setJoinDismissed] = useState(() => ls.get('alimne_join_dismissed') === '1')
  // Sign-in gate (free mode): { limit, remaining } = the guides this anonymous device may make / still has.
  // 3 of 3 until /api/config answers. Only ever shown to, and enforced on, a signed-out visitor.
  const [anonGate, setAnonGate]       = useState(() => gateFromConfig(null))
  const [loginGate, setLoginGate]     = useState(null)  // set when the gate opened the sign-in modal: { reason, uses, text } for its notice
  // The nav counter waits for a real number (from /api/config, a finished guide or a refusal) so a device
  // with none left is never shown "3 free guides left" for a moment. If /api/config never answers, the default shows.
  const [gateKnown, setGateKnown]     = useState(false)

  const openLogin = (mode = 'signin', notice = null, gate = null) => {
    setLoginMode(mode); setLoginNotice(notice); setLoginGate(gate); setLoginKey(k => k + 1); setShowLogin(true)
  }

  // Referral
  const [refStats, setRefStats]     = useState(null)
  const [copied, setCopied]         = useState(false)

  const inputRef = useRef()
  // UI strings + direction only; the API still receives `lang` unchanged ('auto' included).
  // Only the user (chooseLang) ever changes `lang` — never a guide's detected language.
  const uiLang = lang === 'auto' ? (NAV_AR ? 'ar' : 'en') : lang
  const t = useMemo(() => tFor(uiLang, freeMode), [uiLang, freeMode])
  const isAr = uiLang === 'ar'

  // Refs for async flows that outlive a render (a batch can run for minutes)
  const sessionRef  = useRef(null)
  const userInfoRef = useRef(userInfo); userInfoRef.current = userInfo
  const queueRef    = useRef(queue);    queueRef.current = queue
  const tRef        = useRef(t);        tRef.current = t
  const langRef     = useRef(uiLang);   langRef.current = uiLang
  const freeRef     = useRef(freeMode); freeRef.current = freeMode
  const gateRef     = useRef(anonGate)   // written by setGate() in step with the state, so a running batch reads the count just set
  const gateAsked   = useRef(false)      // the gate opened the sign-in modal in this page (see afterSignIn)
  const cfgSeq      = useRef(0)
  const lastUid     = useRef(null)
  const meSeq       = useRef(0)
  const rehydrating = useRef({})
  const savedQ      = useRef('')
  // What is typed in the boxes right now (for the copy kept across the Google sign-in, see stashForSignIn)
  const boxesRef    = useRef(null);     boxesRef.current = { text: pasteText, url: pasteUrl, yt: ytUrl, tab: inputTab }
  const stashRestore = useRef(null)      // promise of what this page load brought back from a sign-in round trip (read once)
  const stashedAt    = useRef(0)         // when THIS page kept a copy for a sign-in it was about to leave for (0 = never)
  const loadDone     = useRef(false)     // the session restore of this page load has answered
  const atLoadSignIn = useRef(false)     // the current sign-in is the one the page loaded with (the return from Google)

  const setGate = fn => { const next = fn(gateRef.current); gateRef.current = next; setAnonGate(next); setGateKnown(true) }
  // What this page itself can say when it asks for a sign-in: its own device counter, or, for a browser that
  // keeps no device id (its number is then the allowance of its network), the network's.
  const ownReason = () => getDeviceId() ? 'device' : 'network'
  // The sign-in modal, in sign-up mode, saying why. `n`, `reason` and `text` are the server's when it refused.
  const openGate = (n, reason, text) => {
    gateAsked.current = true
    gateNote.save({ tab: inputTab, yt: keptLink(ytUrl), url: keptLink(pasteUrl) })
    openLogin('signup', null, { reason: reason || ownReason(), uses: countInt(n) ?? gateRef.current.limit, text: text || null })
  }
  // → true when a new generation must NOT be sent (signed out, no free guides left): the modal opens instead.
  // Only this device's own counter is known here. Whether its network or the anonymous pool still has room is
  // for the server to say: such a refusal never empties the counter, so the next try is sent again.
  const gateBlocks = () => {
    if (!anonGated({ freeMode: freeRef.current, authEnabled, authLoading, session: sessionRef.current, remaining: gateRef.current.remaining })) return false
    // A browser that keeps no device id has no counter of its own (unless no guide is free at all): send, and let the server answer
    if (gateRef.current.limit > 0 && !getDeviceId()) return false
    openGate()
    return true
  }
  // "Create a free account" from the nav counter / the join card: plain sign-up while guides are left, with the reason at 0
  const openSignUp = () => { if (gateRef.current.remaining > 0) openLogin('signup'); else openGate() }

  const quizHistory = (() => { try { return JSON.parse(localStorage.getItem('quizHistory') || '[]') } catch { return [] } })()

  const chooseLang = v => { setLang(v); ls.set('alimne_lang', v) }   // explicit choices only
  useEffect(() => { ls.set('alimne_theme', theme) }, [theme])

  // Keep finished guides for this tab (whitelisted fields; drop the oldest copies past ~2 MB)
  useEffect(() => {
    try {
      const rows = queue.filter(i => (i.status === 'done' || i.status === 'expired') && i.jobId)
        .map(({ id, name, status, jobId, shareUrl, counts, source, guideBlob, sig, filename }) => {
          const src = source ? { ...source } : undefined
          if (src) delete src.text                              // pasted text stays in memory only
          return { id, name, status, jobId, shareUrl, counts, source: src, guideBlob, sig, filename }
        })
      let s = JSON.stringify(rows)
      for (let k = 0; s.length > 2e6 && k < rows.length; k++) {
        rows[k] = { ...rows[k], guideBlob: undefined, sig: undefined }
        s = JSON.stringify(rows)
      }
      if (s !== savedQ.current) { sessionStorage.setItem(QKEY, s); savedQ.current = s }
    } catch { /* storage blocked or full */ }
  }, [queue])

  // ── Capture referral code from URL ────────────────────────────────────────
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search)
      const ref = params.get('ref')
      if (!ref) return
      ls.set('alimne_ref', ref.toUpperCase())
      params.delete('ref')
      const qs = params.toString()
      window.history.replaceState(window.history.state, '', window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash)
    } catch { /* ignore */ }
  }, [])

  // ── OAuth / email-link errors come back in the URL: explain, reopen sign-in, clean the URL
  useEffect(() => {
    const e = AUTH_URL_ERR
    if (!e) return
    const expired = e.code === 'otp_expired' || /expired|invalid/i.test(e.desc || '')
    openLogin('signin', { type: 'error', text: expired ? t.linkExpired : t.authLinkError })
    try {
      const q = new URLSearchParams(window.location.search)
      ;['error', 'error_code', 'error_description'].forEach(k => q.delete(k))
      const qs = q.toString()
      const hash = /(^#|&)(error|error_code|error_description)=/.test(window.location.hash) ? '' : window.location.hash
      window.history.replaceState(window.history.state, '', window.location.pathname + (qs ? `?${qs}` : '') + hash)
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── /api/config: free_mode + fair-use numbers, auth_enabled, the sign-in gate's numbers (free mode:
  //    anon_free_limit / anon_remaining / signin_after) and, in token mode, the anon preview counters.
  //    Retried with backoff; if it never loads, auth stays enabled (the Supabase client doesn't
  //    depend on it), the client stays in free mode, its default, and the gate starts at 3 of 3
  //    (the server still refuses when the real count is lower). Read again after sign-out, when the
  //    anonymous allowance matters again. A newer call supersedes an older one.
  const loadConfig = async (tries = 4) => {
    const seq = ++cfgSeq.current
    const live = () => seq === cfgSeq.current
    for (let i = 0; i < tries && live(); i++) {
      try {
        const r = await fetchT('/api/config', { headers: { 'X-Device-Id': getDeviceId() } }, 8000)
        if (!r.ok) throw new Error(`config ${r.status}`)
        const cfg = await r.json()
        if (!live()) return
        setAuthEnabled(cfg.auth_enabled !== false)
        setFreeMode(cfg.free_mode !== false)
        if (cfg.fair_use && typeof cfg.fair_use === 'object')
          setFair({ device_daily: posInt(cfg.fair_use.device_daily), user_daily: posInt(cfg.fair_use.user_daily) })
        if (cfg.free_mode !== false) setGate(() => gateFromConfig(cfg))
        if (cfg.anon_free_limit !== undefined)
          setAnonInfo({ limit: cfg.anon_free_limit, remaining: cfg.anon_remaining ?? cfg.anon_free_limit })
        return
      } catch { if (i < tries - 1 && live()) await sleep([1000, 3000, 9000][i] || 9000) }
    }
    if (live()) setGateKnown(true)   // no answer: show the default count (the server still decides)
  }
  useEffect(() => {
    loadConfig()
    return () => { cfgSeq.current++ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Auth state: everything is driven by the listener ───────────────────────
  useEffect(() => {
    if (!sb) return
    let live = true
    const { data: { subscription } } = sb.auth.onAuthStateChange((event, sess) => {
      if (!live) return
      sessionRef.current = sess
      setSession(sess)
      if (event === 'INITIAL_SESSION') setAuthLoading(false)
      if (event === 'PASSWORD_RECOVERY' || (event === 'INITIAL_SESSION' && sess && RECOVERY_IN_URL)) setShowSetPw(true)
      const id = sess?.user?.id || null
      if (id && id !== lastUid.current) {
        lastUid.current = id
        // the session this page LOADED with (the return from Google) vs a sign-in made later in the page
        atLoadSignIn.current = !loadDone.current
        // outside the auth lock: calling supabase inside this callback can deadlock
        setTimeout(() => { fetchUserInfo(); fetchRefStats(); afterSignIn() }, 0)
      } else if (!id) {
        const wasSignedIn = !!lastUid.current   // signed out somewhere else (another tab): signOut() below clears it first
        lastUid.current = null; meSeq.current++
        setUserInfo(null); setUserInfoErr(false); setRefStats(null)
        if (wasSignedIn && freeRef.current) setTimeout(() => loadConfig(2), 0)
      }
      if (event === 'INITIAL_SESSION') loadDone.current = true
      if (event === 'SIGNED_IN' && sess) setTimeout(applyReferral, 0)
    })
    sb.auth.getSession()
      .then(({ error }) => { if (error) console.warn('auth restore:', error.message) })
      .catch(() => {})
      .finally(() => {
        if (live) setAuthLoading(false)
        setTimeout(() => { loadDone.current = true }, 5000)   // INITIAL_SESSION normally says so first; this is the net under it
      })
    return () => { live = false; subscription.unsubscribe() }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── The sign-in round trip: what was waiting when this tab left for Google comes back ──────────
  // Back on the page (signed in, or not: a visitor who cancels at Google gets the file back too): the copy this
  // tab kept is read, held in memory and deleted (signinStash.take), its items go back in the queue READY to
  // generate, and typed text goes back in its box. → { kind, missing } for the toast (what came back in one
  // word, and how many files could not be kept and must be chosen again), or null when there is nothing to say.
  // A browser with no copy to look for never opens IndexedDB (signinStash.idle).
  const restoreStash = async () => {
    if (signinStash.idle()) return null
    if (!signinStash.claimed()) { signinStash.take(); return null }   // nothing of this tab's: only sweep old copies, in the background
    const back = stashItems(await signinStash.take())
    if (!back.kind && !back.missing) return null
    if (back.items.length) setQueue(prev => [...prev, ...back.items])
    if (back.box.text) setPasteText(v => v || back.box.text)
    if (back.box.url) setPasteUrl(v => v || back.box.url)
    if (back.box.yt) setYtUrl(v => v || back.box.yt)
    // show where it is: the queue (with its Generate button, and where a missing file is chosen again), else
    // the box the text or link was typed in
    if (back.items.length || !back.kind) setInputTab('upload')
    else setInputTab((back.box.tab === 'youtube' && back.box.yt) ? 'youtube' : (back.box.text || back.box.url) ? 'text' : 'youtube')
    return { kind: back.kind, missing: back.missing }
  }
  // Just before the page leaves for a full-page sign-in (Google): keep what was waiting, in this browser only.
  // Best effort and time-limited: it can never stop the sign-in. Token mode keeps its old behaviour (no copy).
  const stashForSignIn = async () => {
    if (!freeRef.current) return false
    try {
      const kept = await signinStash.save(stashPlan(queueRef.current, boxesRef.current))
      if (kept) stashedAt.current = Date.now()
      return kept
    } catch { return false }
  }
  // The page did not leave after all (the sign-in could not start): everything is still in memory, so the copy goes
  const dropStash = () => { if (!signinStash.idle()) signinStash.take() }
  // The same, when the page was meant to leave and the visitor went on in it instead (Stop or Esc while Google was
  // loading, then a guide made or an item removed): the copy no longer matches the list, and a reload within its
  // 30 minutes must not bring back a file that is already done or gone. Only a tab that holds a claim has a copy.
  // `auto` = not the visitor's own tap (a guide that finishes, the next file of a running batch): in the first
  // seconds after the copy was made the browser may simply still be on its way to Google, and those prove nothing.
  const dropOwnStash = (auto = false) => {
    if (auto && Date.now() - stashedAt.current < STASH_LEAVING_MS) return
    if (signinStash.claimed()) signinStash.take()
  }
  useEffect(() => {
    if (!stashRestore.current) stashRestore.current = restoreStash()
    // Back from the browser's back/forward cache: the very same page, its memory intact. take() then only deletes.
    const onShow = (e) => { if (e.persisted) restoreStash() }
    window.addEventListener('pageshow', onShow)
    return () => window.removeEventListener('pageshow', onShow)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Fresh auth per request: getSession() waits for the restore and refreshes a stale token.
  const authHeaders = async () => {
    const h = { 'X-Device-Id': getDeviceId() }
    let s = sessionRef.current
    if (sb) {
      try {
        const r = await Promise.race([sb.auth.getSession(), sleep(10000).then(() => 'timeout')])
        // {session:null, error} = the refresh failed (often a network blip): keep the last
        // token → the server answers 401 token_expired and the refresh+retry path runs,
        // instead of a signed-in user silently going out anonymous.
        if (r !== 'timeout') s = r?.data?.session || (r?.error ? s : null)
      } catch { /* keep the last known session */ }
    }
    if (s?.access_token) h.Authorization = `Bearer ${s.access_token}`
    return h
  }

  // → 'ok' | 'network' (keep the session, report offline) | 'failed' (session is dead)
  const tryRefresh = async () => {
    if (!sb) return 'failed'
    try {
      const { data, error } = await sb.auth.refreshSession()
      if (!error && data?.session) return 'ok'
      if (error && (error.name === 'AuthRetryableFetchError' || !error.status || error.status >= 500)) return 'network'
      return 'failed'
    } catch { return 'network' }
  }

  // Local sign-out (this device only). If the network call fails, clear the stored session and reload.
  const signOut = async () => {
    meSeq.current++; lastUid.current = null; sessionRef.current = null
    // nothing kept for a sign-in round trip outlives a sign-out (a browser that never made a copy has none to delete)
    stashRestore.current = null
    if (!signinStash.idle()) signinStash.clear()
    let error = null
    try { if (sb) error = (await sb.auth.signOut({ scope: 'local' })).error } catch (e) { error = e }
    setSession(null); setUserInfo(null); setUserInfoErr(false); setRefStats(null)
    if (error) {
      try { Object.keys(localStorage).filter(k => k.startsWith('sb-') && k.endsWith('-auth-token')).forEach(k => localStorage.removeItem(k)) } catch { /* ignore */ }
      window.location.reload()
      return
    }
    // Signed out (free mode): the anonymous allowance applies again, so read how much of it this device has left
    if (freeRef.current) loadConfig(2)
  }
  // Explicit sign-out also clears this tab's guides (shared / library computers)
  const userSignOut = async () => {
    setShowAccount(false)
    setQueue(q => q.filter(i => i.status === 'processing'))
    try { sessionStorage.removeItem(QKEY) } catch { /* ignore */ }
    await signOut()
  }
  const expireSession = async () => {
    await signOut()
    openLogin('signin', { type: 'error', text: tRef.current.sessionExpired })
  }

  // /api/auth/me — checks r.ok, refreshes once on 401, retries 5xx/network twice,
  // keeps the previous userInfo on failure and ignores stale / post-sign-out replies.
  const fetchUserInfo = async () => {
    const seq = ++meSeq.current
    const stale = () => seq !== meSeq.current || !sessionRef.current
    setUserInfoErr(false)
    for (let attempt = 0; attempt < 3; attempt++) {
      if (stale()) return
      const h = await authHeaders()
      if (!h.Authorization || stale()) return
      let r = null
      try { r = await fetchT('/api/auth/me', { headers: h }, 10000) } catch { /* network */ }
      if (stale()) return
      if (r && r.status === 401) {
        if (attempt === 0 && (await tryRefresh()) === 'ok') continue
        break
      }
      if (r && r.ok) {
        const d = await r.json().catch(() => null)
        if (stale()) return
        if (d && !d.error) {
          setUserInfo(d); setUserInfoErr(false)
          if (d.free_mode === true) setFreeMode(true)   // the server is in free mode (config may have been missed or stale)
          return
        }
      }
      if (attempt < 2) await sleep(1500 * (attempt + 1))
    }
    if (!stale()) setUserInfoErr(true)
  }

  const fetchRefStats = async () => {
    try {
      const h = await authHeaders()
      if (!h.Authorization) return
      const r = await fetchT('/api/referral/stats', { headers: h }, 10000)
      if (!r.ok) return
      const d = await r.json()
      if (sessionRef.current) setRefStats(d)
    } catch { /* non-critical */ }
  }

  // Referral code stored from ?ref= — removed only once the server accepted or rejected it
  const applyReferral = async () => {
    const code = ls.get('alimne_ref')
    if (!code) return
    try {
      const h = await authHeaders()
      if (!h.Authorization) return
      const r = await fetchT('/api/referral/apply', {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...h }, body: JSON.stringify({ code })
      }, 15000)
      const d = await r.json().catch(() => ({}))
      if (r.ok && (d.success || d.reason === 'invalid_code')) ls.del('alimne_ref')
    } catch { /* retry on the next sign-in */ }
  }

  // A sign-in clears the gate: held items are simply ready to run again. When the gate had asked for
  // this sign-in, its modal closes and a short toast says to carry on. Google sign-in leaves the page
  // and comes back, so then only the note in sessionStorage says the gate had asked; it also gives
  // back the link the visitor had typed. A chosen file or pasted text comes back through the sign-in
  // stash (restoreStash, at page load): when it did, the toast says so and what to tap.
  const afterSignIn = async () => {
    const note = gateNote.take()
    setQueue(prev => prev.some(i => GATE_CODES.has(i.errCode))
      ? prev.map(i => GATE_CODES.has(i.errCode) ? { ...i, errCode: null, gateReason: null } : i) : prev)
    // What this page load brought back, for the sign-in the page loaded with only (the return from Google).
    // A sign-in made later in the page has nothing new to announce: it reads as before.
    const pending = stashRestore.current
    const atLoad = atLoadSignIn.current
    stashRestore.current = null
    const back = (pending && atLoad) ? await pending : null
    // Signed in without the page ever leaving (email and password, or back from a Google page that was never
    // completed): whatever was kept for a round trip is still in memory here, so the copy has no use left
    if (!atLoad) dropStash()
    if (!back && !note && !gateAsked.current) return
    if (note && !gateAsked.current) {
      const yt = keptLink(note.yt), url = keptLink(note.url)
      if (yt) setYtUrl(v => v || yt)
      if (url) setPasteUrl(v => v || url)
      if (!back && ((note.tab === 'youtube' && yt) || (note.tab === 'text' && url))) setInputTab(note.tab)
    }
    gateAsked.current = false
    setShowLogin(false); setLoginNotice(null); setLoginGate(null)
    // "You're signed in. Your file is ready — tap Generate." (+ "One file could not be kept — please choose it again.")
    if (back) toast(stashToast(tRef.current, back), back.missing ? 'info' : 'success', back.missing ? 12000 : 9000)
    else toast(tRef.current.gateCleared, 'success')
  }

  // Back from Stripe Checkout (?sub=success): confirm, then re-read the plan a
  // few times — the webhook that activates Pro can land a few seconds later.
  useEffect(() => {
    if (!session?.user?.id) return
    let params
    try { params = new URLSearchParams(window.location.search) } catch { return }
    if (params.get('sub') !== 'success') return
    toast(t.subSuccess, 'success')
    const timers = [2500, 7000, 15000].map(ms => setTimeout(() => fetchUserInfo(), ms))
    params.delete('sub')
    const qs = params.toString()
    try { window.history.replaceState(null, '', window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash) } catch { /* ignore */ }
    return () => timers.forEach(clearTimeout)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.id])

  const copyReferral = (code) => {
    const link = `${window.location.origin}?ref=${code}`
    // clipboard missing / blocked → show the link in a toast so it can still be copied by hand
    Promise.resolve().then(() => navigator.clipboard.writeText(link)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => toast(link, 'info'))
  }

  // The dismissal is remembered on this device (ls = localStorage in try/catch; blocked storage just means "this visit")
  const dismissJoin = () => { ls.set('alimne_join_dismissed', '1'); setJoinDismissed(true) }

  // Authenticated JSON call: fresh token, one silent refresh + retry on 401
  const authedFetch = async (url, opts = {}, ms = 20000) => {
    for (let attempt = 0; attempt < 2; attempt++) {
      let r
      try { r = await fetchT(url, { ...opts, headers: { ...(opts.headers || {}), ...(await authHeaders()) } }, ms) }
      catch { return { status: 0, d: {} } }
      const d = await r.json().catch(() => ({}))
      if (r.status === 401 && attempt === 0 && sessionRef.current) {
        const rf = await tryRefresh()
        if (rf === 'ok') continue
        if (rf === 'failed') { await expireSession(); return { status: 401, d, handled: true } }
        return { status: 0, d: {} }
      }
      return { status: r.status, ok: r.ok, d }
    }
    return { status: 401, d: {} }
  }

  const goToStripe = async (path, failText) => {
    const { status, ok, d, handled } = await authedFetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({})
    })
    if (ok && d.url) { window.location.href = d.url; return }
    if (handled) return
    if (status === 401) { openLogin('signin'); return }
    // The server turned free mode on while this tab still showed the old upgrade UI → follow it
    if (status === 410 || d?.code === 'free_now') { setFreeMode(true); setShowUpgrade(false); toast(T[langRef.current]?.freeNow || T.en.freeNow, 'info'); return }
    toast(friendlyErr(t, status ? (d.error || failText) : '', status, d), 'error')
  }
  const handleCheckout      = () => goToStripe('/api/stripe/checkout', t.paymentError)
  const handleManageBilling = () => goToStripe('/api/stripe/portal', t.billingError)

  // Email capture at the paywall → store the lead, then send them to sign-up/subscribe.
  const submitLead = async (email) => {
    try {
      await fetch('/api/lead', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, source: 'paywall' })
      })
      ls.set('alimne_lead', email)
    } catch { /* best-effort — never trap the visitor */ }
    setEmailCaptured(true)
    setShowEmailCapture(false)
    openLogin('signup')
  }
  const skipLead = () => { setShowEmailCapture(false); openLogin('signup') }

  const updateItem = (id, patch) =>
    setQueue(prev => prev.map(i => i.id === id ? { ...i, ...patch } : i))
  // Patch only while the item still points at `jobId` (a regenerate/restore may have replaced it)
  const updateItemJob = (id, jobId, patch) =>
    setQueue(prev => prev.map(i => i.id === id && i.jobId === jobId ? { ...i, ...patch } : i))
  const latestItem = id => queueRef.current.find(i => i.id === id)
  const canRestore = it => !!(it && it.guideBlob && it.sig)

  // The server says a free account is needed to make more guides (401 signin_required, or the device
  // refusal of a server from before the gate). Not an error: the item waits exactly as it was (its
  // upload, link or text untouched) and the sign-in modal opens with the server's own cause.
  // Only a refusal about THIS device's guides empties the local counter. When the cause is the network or the
  // anonymous pool the device still has its guides (the server gave the unit back), so the counter stays and the
  // next try is sent again: the client never blocks for something it cannot know.
  const holdForSignIn = (id, data) => {
    const n = countInt(data?.free_uses)
    const reason = signinReason(data)
    setGate(g => {
      const limit = n ?? g.limit
      return holdsDeviceCount(data) ? { limit, remaining: 0 } : { limit, remaining: Math.min(g.remaining, limit) }
    })
    if (id) updateItem(id, { status: 'queued', error: null, errCode: 'signin_required', gateReason: reason, step: null, msg: null, queuePos: 0 })
    openGate(n, reason, typeof data?.error === 'string' ? data.error : null)
  }

  // 401 / 402 that a token refresh can't fix. A 402 only exists in token mode (ALIMNE_FREE_MODE=0).
  const handleAuthError = (status, data, id) => {
    const tt = tRef.current
    const code = data?.code
    if (status === 401) {
      if (!sessionRef.current && GATE_CODES.has(code)) { holdForSignIn(id, data); return true }
      if (sessionRef.current) { expireSession(); if (id) updateItem(id, { status: 'error', error: tt.sessionExpired, step: null }) }
      else { openLogin('signin'); if (id) updateItem(id, { status: 'error', error: tt.loginTitle, step: null }) }
      return true
    }
    if (status === 402) {
      // We believed the server was in free mode (default / stale config) but it is charging tokens:
      // follow it into the token flow, with the token copy, so the item is never left without a way forward.
      if (freeRef.current) { freeRef.current = false; setFreeMode(false) }
      const lt = tFor(langRef.current, false)
      // Anonymous visitor out of free previews → invite sign-up (free tokens).
      // Signed-in user out of tokens → show the upgrade / subscribe modal.
      if (code === 'signin_for_more') {
        if (!sessionRef.current) setAnonInfo(a => a ? { ...a, remaining: data?.tokens_remaining ?? 0 } : a)
        if (emailCaptured || ls.get('alimne_lead')) openLogin('signup')
        else setShowEmailCapture(true)
        if (id) updateItem(id, { status: 'error', error: lt.signInForMore, step: null })
      } else {
        setShowUpgrade(true)
        if (id) updateItem(id, { status: 'error', error: hasLiveSub(userInfoRef.current) ? lt.proUsedUp : lt.freeUsedUp, step: null })
      }
      return true
    }
    return false
  }

  const addFiles = useCallback(fileList => {
    const tt = tRef.current
    const all = Array.from(fileList || [])
    const typed = all.filter(f => /\.(pptx?|pdf|docx?|txt)$/i.test(f.name))
    if (typed.length < all.length) toast(tt.unsupportedFile, 'error')
    const valid = typed.filter(f => {
      if (f.size > MAX_UPLOAD) { toast(tt.fileTooBig(f.name), 'error'); return false }
      return true
    })
    if (!valid.length) return
    // Up to 3 files waiting/processing at a time (finished guides don't count)
    const active = queueRef.current.filter(i => i.status !== 'done' && i.status !== 'expired').length
    const room = Math.max(0, 3 - active)
    if (valid.length > room) toast(tt.maxFiles, 'error')
    const add = valid.slice(0, room).map(f => ({ id: uid(), file: f, name: f.name, status: 'queued', jobId: null, error: null, step: null, msg: null, source: { type: 'file' } }))
    if (add.length) setQueue(prev => [...prev, ...add])
  }, [])

  const onDrop = e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }
  const onDragOver = e => { e.preventDefault(); setDrag(true) }
  const onDragLeave = () => setDrag(false)

  const removeItem = id => { dropOwnStash(); setQueue(prev => prev.filter(i => i.id !== id)) }
  const clearAll   = () => { dropOwnStash(); setQueue([]) }

  // ── Guide cache + recovery ─────────────────────────────────────────────────
  const applyGuideResp = (id, jobId, d) => {
    const patch = { guide: guideOf(d) }
    if (typeof d.guide_blob === 'string' && d.sig) { patch.guideBlob = d.guide_blob; patch.sig = d.sig }
    if (d.filename) patch.filename = d.filename
    updateItemJob(id, jobId, patch)
  }

  // Restore an expired guide from the signed copy this tab holds — free, no credit.
  // → { jobId } | { code }
  const rehydrate = (it) => {
    if (!canRestore(it)) return Promise.resolve({ code: 'no_copy' })
    if (rehydrating.current[it.id]) return rehydrating.current[it.id]
    const p = (async () => {
      try {
        const headers = { 'Content-Type': 'application/json', ...(await authHeaders()) }
        const r = await fetchT('/api/rehydrate', { method: 'POST', headers, body: JSON.stringify({ guide_blob: it.guideBlob, sig: it.sig }) }, 30000)
        const d = await r.json().catch(() => ({}))
        if (r.ok && d.job_id) {
          updateItem(it.id, { jobId: d.job_id, status: 'done', error: null, ...(d.filename ? { filename: d.filename } : {}) })
          return { jobId: d.job_id }
        }
        // a copy the server can never accept → stop offering Restore
        if (r.status === 400 || r.status === 403 || r.status === 413) updateItem(it.id, { guideBlob: null, sig: null })
        return { code: d.code || `http_${r.status}` }
      } catch { return { code: 'network' } }
      finally { delete rehydrating.current[it.id] }
    })()
    rehydrating.current[it.id] = p
    return p
  }

  // Fetch a job-backed endpoint for a queue item. A 404 'expired' is healed from the
  // signed copy (/api/rehydrate) and retried once; otherwise the item becomes 'expired'.
  // A passing restore failure (offline, 429, 503) leaves it 'done' so the cached study
  // tools stay usable. → { r, jobId }; throws Error('expired'), Error('restore_failed')
  // (with .code) or the fetch error (AbortError on timeout).
  const jobFetch = async (item, pathFn, opts = {}, ms = 30000) => {
    const cur = latestItem(item.id) || item
    let jobId = cur.jobId
    for (let attempt = 0; attempt < 2; attempt++) {
      const r = await fetchT(pathFn(jobId), opts, ms)
      if (r.status !== 404) return { r, jobId }
      const d = await r.clone().json().catch(() => ({}))
      if (d.code === 'no_flashcards') return { r, jobId }
      if (attempt > 0) break
      const re = await rehydrate(latestItem(item.id) || cur)
      if (!re.jobId) {
        if (!RESTORE_FINAL.has(re.code)) throw Object.assign(new Error('restore_failed'), { code: re.code })
        break
      }
      jobId = re.jobId
    }
    updateItem(item.id, { status: 'expired', busy: null, sharing: false })
    throw new Error('expired')
  }

  const prefetchPdf = async (id, jobId) => {
    try {
      const r = await fetchT(`/api/download/${jobId}`, {}, 30000)
      if (!r.ok) return
      const blob = await r.blob()
      updateItemJob(id, jobId, { pdfBlob: blob, pdfName: filenameFrom(r, null) })
    } catch { /* the tap falls back to a normal download */ }
  }

  // Once per finished guide: keep a copy (+ its signature) so study modes and
  // restores work after the 15-minute server window. In-app browsers also get the PDF.
  const cacheGuide = async (id, jobId) => {
    try {
      const r = await fetchT(`/api/guide/${jobId}`, {}, 20000)
      if (r.ok) applyGuideResp(id, jobId, await r.json())
    } catch { /* modals fetch on demand */ }
    // only where a file share sheet can take it (Android WebViews have none → https download)
    if (IN_APP && typeof navigator.canShare === 'function') prefetchPdf(id, jobId)
  }

  const loadGuide = async (id) => {
    const cur = latestItem(id)
    if (!cur?.jobId) throw new Error('expired')
    if (cur.guide) return cur.guide
    const { r, jobId } = await jobFetch(cur, j => `/api/guide/${j}`, {}, 20000)
    if (!r.ok) throw new Error('failed')
    const d = await r.json()
    applyGuideResp(id, jobId, d)
    return guideOf(d)
  }

  // ── Generation (file / YouTube / text / sample) over SSE ──────────────────
  const streamP = (url, opts, onEvent) => new Promise(resolve => {
    streamSSE(url, opts,
      ev => {
        try { onEvent(ev) }
        finally {
          if (ev.error) resolve({ ok: false, msg: ev.error, status: 200, data: ev })
          else if (ev.step === 'done') resolve({ ok: true })
        }
      },
      (msg, status, data) => resolve({ ok: false, msg, status, data }),
      tRef.current)
  })

  // The language a stream reports for its guide is deliberately NOT fed back into `lang`:
  // in Auto it would flip the whole UI and force that language on every later upload.
  // A guide's own direction comes from guide.language in the views that show it.
  const onGenEvent = (id, ev, hadBearer, demo) => {
    if (ev.error) return
    if (ev.step === 'done') {
      const counts = { sections: ev.sections, keywords: ev.keywords, flashcards: ev.flashcards, mcqs: ev.mcqs }
      updateItem(id, { status: 'done', jobId: ev.job_id, step: 'done', msg: null, error: null, counts, partial: !!ev.partial,
        guide: null, guideBlob: null, sig: null, filename: null, pdfBlob: null, pdfName: null, shareUrl: null, busy: null })
      // Token balance: token mode only. Free mode reports none (omitted or null) and shows none.
      if (!demo && !freeRef.current && ev.tokens_remaining != null) {
        // only a request that carried a Bearer token reports the account balance
        if (hadBearer) setUserInfo(u => u ? { ...u, tokens_remaining: ev.tokens_remaining } : u)
        else if (!sessionRef.current) setAnonInfo(a => a ? { ...a, remaining: ev.tokens_remaining } : a)
        else fetchUserInfo()
      }
      // Sign-in gate: an anonymous guide used one of the free ones (the sample never does). The server's
      // count when the event carries it (anon_remaining), else one less.
      if (!demo && freeRef.current && !hadBearer) setGate(g => gateAfterDone(g, ev))
      if (!demo) dropOwnStash(true)   // made here: a copy kept for a sign-in this page never left for is stale now
      if (ev.job_id) cacheGuide(id, ev.job_id)
    } else if (ev.step === 'queued') {
      // Waiting for a free generation slot: not an error. The line shows the position, localized.
      const pos = Math.floor(Number(ev.position))
      updateItem(id, { step: 'queued', msg: null, queuePos: pos > 0 ? pos : 0 })
    } else {
      updateItem(id, { step: ev.step, msg: ev.msg })
    }
  }

  // One generation for item `id`: fresh auth per attempt, one silent refresh + retry
  // on an auth failure. → 'done' | 'error' | 'auth' | 'stop' ('auth' / 'stop' = stop the batch:
  // sign-in is needed, or the server refused for fair use / is busy, so the rest would be refused too)
  // `auto`: not started by the visitor's own tap (the next file of a running batch), see dropOwnStash.
  const runGeneration = async (id, url, makeOpts, demo = false, auto = false) => {
    if (!demo) dropOwnStash(auto)   // this page is making a guide: a copy kept for a sign-in it never left for is stale now
    for (let attempt = 0; attempt < 2; attempt++) {
      const headers = demo ? {} : await authHeaders()
      const hadBearer = !!headers.Authorization
      const r = await streamP(url, makeOpts(headers), ev => onGenEvent(id, ev, hadBearer, demo))
      if (r.ok) return 'done'
      const tt = tRef.current
      const code = r.data?.code
      if (!demo && attempt === 0 && sessionRef.current &&
          (r.status === 401 || (r.status === 402 && code === 'signin_for_more'))) {
        const rf = await tryRefresh()
        if (rf === 'ok') { updateItem(id, { status: 'processing', error: null, errCode: null, step: 'extract', msg: tt.starting }); continue }
        if (rf === 'failed') { await expireSession(); updateItem(id, { status: 'error', error: tt.sessionExpired, step: null }); return 'auth' }
        updateItem(id, { status: 'error', error: tt.errNetwork, step: null }); return 'auth'
      }
      if (!demo && (r.status === 401 || r.status === 402)) { handleAuthError(r.status, r.data, id); return 'auth' }
      // The same sign-in refusal by another road (429 fair_use_device from a server before the gate, or
      // inside the stream): hold the item and open the sign-in modal, exactly as for the 401
      if (!demo && !sessionRef.current && GATE_CODES.has(code)) { holdForSignIn(id, r.data); return 'auth' }
      // Per-item error with its server code: the card offers Retry
      updateItem(id, { status: 'error', error: friendlyErr(tt, r.msg, r.status, r.data), errCode: code || null, step: null })
      return !demo && STOP_CODES.has(code) ? 'stop' : 'error'
    }
    return 'error'
  }

  const genOpts = () => ({ language: lang, detail, mode: summaryOnly ? 'summary' : 'full', quiz: includeQuiz })

  const runFile = (id, file, auto = false) => {
    const o = genOpts()
    updateItem(id, { status: 'processing', error: null, errCode: null, step: 'extract', msg: t.starting })
    return runGeneration(id, '/api/summarize-stream', headers => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('language', o.language)
      fd.append('detail', o.detail)
      fd.append('mode', o.mode)
      fd.append('quiz', o.quiz ? 'true' : 'false')
      return { method: 'POST', body: fd, headers }
    }, false, auto)
  }

  // ── File processing with SSE ───────────────────────────────────────────────
  const processAll = async () => {
    if (running) return
    const pending = queueRef.current.filter(i => i.file && (i.status === 'queued' || i.status === 'error'))
    if (!pending.length) return
    if (gateBlocks()) return   // signed out with no free guides left: the sign-in modal opens, the files stay queued
    setRunning(true)
    try {
      for (const [n, item] of pending.entries()) {
        if (n > 0 && gateBlocks()) break   // the file before this one used the last free guide: stop here, send nothing
        const res = await runFile(item.id, item.file, n > 0)   // only the first file is the visitor's own tap
        if (res === 'auth' || res === 'stop') break   // sign-in needed / fair-use or busy refusal: leave the rest queued
      }
    } finally {
      setRunning(false)
    }
  }

  // ── YouTube SSE ────────────────────────────────────────────────────────────
  const runYoutube = async (id, url) => {
    const o = genOpts()
    setRunning(true)
    updateItem(id, { status: 'processing', error: null, errCode: null, step: 'extract', msg: t.fetchingTranscript })
    try {
      return await runGeneration(id, '/api/youtube', headers => ({
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify({ url, ...o })
      }))
    } finally { setRunning(false) }
  }
  const processYoutube = () => {
    const url = ytUrl.trim()
    if (!url || running) return
    if (gateBlocks()) return   // nothing is sent or queued: the link stays in its box for after the sign-in
    const id = uid()
    setQueue(prev => [...prev, { id, file: null, name: url, status: 'processing', jobId: null, error: null, step: 'extract', msg: t.fetchingTranscript, source: { type: 'youtube', url } }])
    setInputTab('upload')
    runYoutube(id, url).then(res => { if (res === 'done') setYtUrl(v => v.trim() === url ? '' : v) })
  }

  // ── Paste text / URL SSE ───────────────────────────────────────────────────
  const runText = async (id, src) => {
    const o = genOpts()
    setRunning(true)
    updateItem(id, { status: 'processing', error: null, errCode: null, step: 'extract', msg: t.processingText })
    try {
      return await runGeneration(id, '/api/summarize-text', headers => ({
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify({ text: src.text || '', url: src.url || '', language: o.language, filename: src.name, detail: o.detail, mode: o.mode, quiz: o.quiz })
      }))
    } finally { setRunning(false) }
  }
  const processText = () => {
    const text = pasteText.trim()
    const url  = pasteUrl.trim()
    if ((!text && !url) || running) return
    if (gateBlocks()) return   // nothing is sent or queued: the text / link stays in its box for after the sign-in
    const name = url ? url.replace(/^https?:\/\//, '').slice(0, 40) : 'Pasted text'
    const id = uid()
    const src = { type: 'text', url, text, name }   // `text` is never persisted
    setQueue(prev => [...prev, { id, file: null, name, status: 'processing', jobId: null, error: null, step: 'extract', msg: t.processingText, source: src }])
    setInputTab('upload')
    runText(id, src).then(res => {
      if (res !== 'done') return
      setPasteText(v => v.trim() === text ? '' : v)
      setPasteUrl(v => v.trim() === url ? '' : v)
    })
  }

  // ── Zero-friction demo: one tap → a real guide on a sample lecture (no file,
  //    no credit). The activation unlock for visitors with nothing to upload. ──
  const runSample = async (id, sLang) => {
    setRunning(true)
    updateItem(id, { status: 'processing', error: null, errCode: null, step: 'extract', msg: t.sampleMsg })
    try {
      // demo spends no preview — anonymous on purpose, doesn't touch token state
      return await runGeneration(id, '/api/summarize-text', () => ({
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ demo: true, language: sLang })
      }), true)
    } finally { setRunning(false) }
  }
  const startSample = () => {
    if (running) return
    setInputTab('upload')
    const sLang = isAr ? 'ar' : 'en'
    const id = uid()
    setQueue(prev => [...prev, { id, file: null, name: t.sampleName, status: 'processing', jobId: null, error: null, step: 'extract', msg: t.sampleMsg, demo: true, source: { type: 'sample', lang: sLang } }])
    runSample(id, sLang)
  }

  // Expired / failed item → Restore (free) when this tab holds a signed copy, else Regenerate
  const restoreItem = async (item) => {
    const cur = latestItem(item.id) || item
    if (cur.busy) return
    updateItem(cur.id, { busy: 'restore' })
    const res = await rehydrate(cur)
    updateItem(cur.id, { busy: null })
    if (res.jobId) toast(t.restored, 'success')
    else toast(res.code === 'rate_limited' || res.code === 'http_429' ? t.errRateLimit : res.code === 'network' ? t.errNetwork : t.restoreFailed, 'error')
  }
  const regenerate = async (item) => {
    const cur = latestItem(item.id) || item
    const src = cur.source || (cur.file ? { type: 'file' } : null)
    if (running || !src) return
    if (src.type === 'file' && !cur.file) { toast(t.reselectFile, 'info'); return }
    if (src.type === 'text' && !src.text && !src.url) { toast(t.repasteText, 'info'); return }
    if (src.type !== 'sample' && gateBlocks()) return   // a new guide needs a free account now; the sample never does
    if (src.type !== 'sample' && !freeMode && !window.confirm(t.usesCredit)) return   // token mode only: a retry spends a credit
    updateItem(cur.id, { guide: null, guideBlob: null, sig: null, pdfBlob: null, shareUrl: null, partial: false })
    if (src.type === 'file') {
      setRunning(true)
      try { await runFile(cur.id, cur.file) } finally { setRunning(false) }
    }
    else if (src.type === 'youtube') await runYoutube(cur.id, src.url)
    else if (src.type === 'text') await runText(cur.id, src)
    else if (src.type === 'sample') await runSample(cur.id, src.lang === 'ar' ? 'ar' : 'en')
  }
  const recoverItem = (item) => canRestore(latestItem(item.id) || item) ? restoreItem(item) : regenerate(item)

  // ── Downloads / study actions ──────────────────────────────────────────────
  const reqErr = (e, fallback) => e?.message === 'expired' ? t.guideExpired
    : e?.message === 'restore_failed' ? (e.code === 'rate_limited' || e.code === 'http_429' ? t.errRateLimit
      : e.code === 'network' ? t.errNetwork : t.errRetry)
    : e?.name === 'AbortError' ? t.slowNetwork
    : e?.name === 'TypeError' ? t.errNetwork
    : fallback

  // In-app browsers drop blob: downloads (Android WebView's DownloadListener only takes
  // http/https), so hand them the real https URL once jobFetch knows the job is alive.
  // The queue survives in sessionStorage if the WebView navigates away.
  const inAppDownload = (path) => { window.location.href = path; toast(t.openingDownload, 'info') }

  const downloadPDF = async (item) => {
    const cur = latestItem(item.id) || item
    if (!cur.jobId || cur.busy) return
    // In-app: the prefetched PDF goes to the share sheet, synchronously inside the tap
    // (Safari rejects share() after an await). No share sheet → the https download below.
    if (IN_APP && cur.pdfBlob) {
      try {
        const file = new File([cur.pdfBlob], cur.pdfName || pdfNameOf(cur), { type: 'application/pdf' })
        if (navigator.canShare?.({ files: [file] })) { navigator.share({ files: [file] }).catch(() => {}); return }
      } catch { /* fall through to the https download */ }
    }
    updateItem(cur.id, { busy: 'pdf' })
    try {
      if (IN_APP) {
        // HEAD: check (and heal) the job without pulling the PDF twice
        const { r, jobId } = await jobFetch(cur, id => `/api/download/${id}`, { method: 'HEAD' })
        if (!r.ok) throw new Error('failed')
        inAppDownload(`/api/download/${jobId}`)
        return
      }
      const { r } = await jobFetch(cur, id => `/api/download/${id}`)
      if (!r.ok) throw new Error('failed')
      const blob = await r.blob()
      if (!blob.size || /json|html/i.test(blob.type || '')) throw new Error('failed')
      saveBlob(blob, filenameFrom(r, pdfNameOf(cur)))
      toast(t.pdfSaved, 'success')
    } catch (e) {
      toast(reqErr(e, t.downloadFailed), 'error')
    } finally { updateItem(cur.id, { busy: null }) }
  }

  // Anki CSV from this tab's cached cards (same columns + escaping as the server)
  const localAnki = (it) => {
    const cards = (it?.guide?.flashcards || []).filter(c => c && typeof c === 'object')
    if (!cards.length) return false
    const csv = [['front', 'back'], ...cards.map(c => [c.q, c.a])].map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n'
    saveBlob(new Blob([csv], { type: 'text/csv;charset=utf-8' }), pdfNameOf(it).replace(/\.pdf$/i, '') + '_anki.csv')
    return true
  }
  const downloadAnki = async (item) => {
    const cur = latestItem(item.id) || item
    if (!cur.jobId || cur.busy) return
    updateItem(cur.id, { busy: 'anki' })
    try {
      const { r, jobId } = await jobFetch(cur, id => `/api/export/anki/${id}`)
      if (r.status === 404) { toast(t.noFlashcards, 'info'); return }   // job alive, no cards (summary only)
      if (!r.ok) throw new Error('failed')
      if (IN_APP) { inAppDownload(`/api/export/anki/${jobId}`); return }   // blob: links are dropped in-app
      const blob = await r.blob()
      saveBlob(blob, filenameFrom(r, pdfNameOf(cur).replace(/\.pdf$/i, '') + '_anki.csv'))
      toast(t.ankiSaved, 'success')
    } catch (e) {
      // server copy gone or offline, but this tab still has the cards → build the CSV here
      // (not in-app: a blob: save is dropped there)
      if (!IN_APP && localAnki(latestItem(cur.id) || cur)) toast(t.ankiSaved, 'success')
      else toast(reqErr(e, t.downloadFailed), 'error')
    } finally { updateItem(cur.id, { busy: null }) }
  }

  const shareGuide = async (item) => {
    const cur = latestItem(item.id) || item
    if (!cur.jobId || cur.sharing) return
    if (cur.shareUrl) {            // already shared — just copy again
      try { await navigator.clipboard.writeText(cur.shareUrl) } catch { /* shown below the item */ }
      toast(t.shareCopied, 'info')
      return
    }
    updateItem(cur.id, { sharing: true })
    try {
      const headers = { 'Content-Type': 'application/json', ...(await authHeaders()) }
      const { r } = await jobFetch(cur, id => `/api/share/${id}`, { method: 'POST', headers })
      const d = await r.json().catch(() => ({}))
      if (!r.ok || !d.url) throw Object.assign(new Error('share_failed'), { status: r.status, data: d })
      updateItem(cur.id, { sharing: false, shareUrl: d.url })
      try { await navigator.clipboard.writeText(d.url) } catch { /* shown below the item */ }
      toast(t.shareCopied, 'info')
    } catch (e) {
      updateItem(cur.id, { sharing: false })
      toast(e.status ? friendlyErr(t, t.shareFailed, e.status, e.data) : reqErr(e, t.shareFailed), 'error')
    }
  }

  const deleteNow = async (item) => {
    const cur = latestItem(item.id) || item
    if (!cur.jobId || cur.busy) return
    updateItem(cur.id, { busy: 'delete' })
    let ok = false
    try {
      const r = await fetchT(`/api/delete/${cur.jobId}`, { method: 'POST', headers: await authHeaders() }, 15000)
      ok = r.ok
    } catch { /* reported below */ }
    if (!ok) { updateItem(cur.id, { busy: null }); toast(t.deleteFailed, 'error'); return }
    ls.del(`sr_${cur.jobId}`); ls.del(srKeyOf(cur))
    setQueue(prev => prev.filter(q => q.id !== cur.id))     // also drops this tab's copy
    toast(t.deleted, 'success')
  }

  const openPrint = async (item) => {
    const cur = latestItem(item.id) || item
    if (!cur.jobId) return
    const w = window.open('', '_blank')   // opened inside the tap so iOS doesn't block it as a pop-up
    try { w?.document.write('<p style="font-family:sans-serif;padding:2rem;color:#888">…</p>') } catch { /* ignore */ }
    try {
      const { r, jobId } = await jobFetch(cur, id => `/api/view/md/${id}`, { method: 'HEAD' }, 20000)
      if (!r.ok) throw new Error('failed')
      const url = `/api/view/md/${jobId}`
      if (w && !w.closed) w.location.href = url
      else if (!window.open(url, '_blank')) toast(t.popupBlocked, 'error')
    } catch (e) {
      try { w?.close() } catch { /* ignore */ }
      toast(reqErr(e, t.loadFailed), 'error')
    }
  }

  // Chat — fresh token, refresh once on 401, transparent restore on an expired guide
  const askGuide = async (id, q) => {
    for (let attempt = 0; attempt < 2; attempt++) {
      const cur = latestItem(id)
      if (!cur?.jobId) throw new Error('expired')
      // Auto: the guide's language, or 'auto' so the server reads it off the stored
      // guide (cur.guide is only a best-effort cache) - never the UI's language.
      const language = lang === 'auto' ? (cur.guide?.language || 'auto') : lang
      const headers = { 'Content-Type': 'application/json', ...(await authHeaders()) }
      const { r } = await jobFetch(cur, j => `/api/chat/${j}`, { method: 'POST', headers, body: JSON.stringify({ question: q, language }) }, 60000)
        .catch(e => { throw e?.message === 'restore_failed' ? new Error(reqErr(e, t.errRetry)) : e })
      const d = await r.json().catch(() => ({}))
      if (r.ok) return d.answer || t.chatNoAnswer
      if (r.status === 401) {
        if (attempt === 0 && sessionRef.current) {
          const rf = await tryRefresh()
          if (rf === 'ok') continue
          if (rf === 'failed') { setChatModal(null); await expireSession(); throw new Error('handled') }
          throw new Error(t.errNetwork)
        }
        setChatModal(null); handleAuthError(401, d, null); throw new Error('handled')
      }
      throw new Error(friendlyErr(t, d.error, r.status, d))
    }
    throw new Error(t.errGeneric)
  }

  const doneCount    = queue.filter(i => i.status === 'done').length
  const pendingCount = queue.filter(i => i.file && (i.status === 'queued' || i.status === 'error')).length
  const hasQueue     = queue.length > 0
  const hasHistory   = quizHistory.length > 0
  const isSubscribed = isProUser(userInfo)
  const liveSub      = hasLiveSub(userInfo)
  // Free-mode lines that quote the number of guides an anonymous visitor gets (token mode: '' → not shown).
  // A signed-in user is not told about "then a free sign-in": the dropzone shows the plain fair-use line.
  const heroLine     = say(t.heroFree, anonGate.limit)
  const dropLine     = freeMode && session ? t.dropFreeUser : say(t.dropFree, anonGate.limit)

  const flashItem = flashModal ? queue.find(i => i.id === flashModal) : null
  const quizItem  = quizModal ? queue.find(i => i.id === quizModal) : null
  const chatItem  = chatModal ? queue.find(i => i.id === chatModal) : null
  const viewItem  = mindmapModal ? queue.find(i => i.id === mindmapModal) : null
  const studyProps = (it, close) => ({
    guide: it.guide, loadGuide: () => loadGuide(it.id), lang: uiLang, t,
    canRestore: canRestore(it), onRecover: () => { close(); recoverItem(it) }, onClose: close,
  })

  return (
    <div data-theme={theme} dir={isAr ? 'rtl' : 'ltr'}>
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
                {authEnabled && authLoading && (
                  <span className="ctrl-btn" aria-hidden="true" style={{opacity:0.6,cursor:'default'}}>
                    <Loader2 size={13} className="spin" />
                  </span>
                )}
                {authEnabled && !authLoading && (
                  session ? (
                    <>
                      {/* Retry when the account couldn't load; the token counter exists in token mode only */}
                      {userInfoErr && !userInfo ? (
                        <button className="ctrl-btn" onClick={() => fetchUserInfo()} title={`${t.accountLoadFailed} ${t.retry}`}
                          style={{borderColor:'rgba(239,68,68,0.4)',color:'#ef4444'}}>
                          <AlertCircle size={12} /><span className="ctrl-label"> {t.retry}</span>
                        </button>
                      ) : !freeMode && (() => {
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
                      {/* User avatar → account panel (plan, billing, sign out) */}
                      <button className="ctrl-btn"
                        onClick={() => { fetchUserInfo(); setShowAccount(true) }}
                        title={`${userInfo?.name || userInfo?.email || ''} — ${t.accountTitle}`}>
                        {userInfo?.avatar_url
                          ? <img src={userInfo.avatar_url} alt="" style={{width:18,height:18,borderRadius:'50%',objectFit:'cover'}} />
                          : <User size={13} />}
                        {userInfo?.name && <span className="ctrl-label"> {String(userInfo.name).split(' ')[0]}</span>}
                      </button>
                    </>
                  ) : (
                    <>
                      {/* Anonymous free-preview counter (token mode only) */}
                      {!freeMode && anonInfo && anonInfo.limit > 0 && (
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
                      {/* Free mode: the guides left before a free account is needed. It opens sign-up; at 0 with the reason. */}
                      {freeMode && gateKnown && <AnonCounter t={t} left={anonGate.remaining} onClick={openSignUp} />}
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

                <button className="ctrl-btn" onClick={() => chooseLang(lang === 'en' ? 'ar' : lang === 'ar' ? 'auto' : 'en')}>
                  <Globe size={13} /><span className="ctrl-label">{lang === 'en' ? ' عربي' : lang === 'ar' ? ' Auto' : ' EN'}</span>
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

            {/* In-app browsers (Instagram / TikTok …): downloads are unreliable there */}
            {IN_APP && (
              <div role="note" style={{display:'flex',alignItems:'flex-start',gap:'0.5rem',margin:'0 0 1rem',padding:'0.6rem 0.85rem',
                borderRadius:10,background:'rgba(251,191,36,0.1)',border:'1px solid rgba(251,191,36,0.35)',
                color:'#f59e0b',fontSize:'0.8rem',lineHeight:1.45}}>
                <AlertCircle size={14} style={{flexShrink:0,marginTop:2}} />
                <span>{t.inAppBanner}</span>
              </div>
            )}

            {/* Hero */}
            <div className="hero">
              <div className="hero-badge"><Sparkles size={12} />{t.badge}</div>
              <h1>{t.h1a} <span>{t.h1b}</span></h1>
              <p>{t.sub}</p>
              {heroLine && (
                <p style={{marginTop:'0.6rem', fontWeight:700, fontSize:'0.95rem', color:'var(--privacy-text, #16a34a)'}}>{heroLine}</p>
              )}
            </div>

            {/* Instant demo — zero-friction activation CTA (first screen only).
                Most real visitors are on phones with no file to upload; this lets
                them see a real guide build in one tap. */}
            {!hasQueue && (
              <div style={{textAlign:'center', margin:'0 auto 1.2rem', maxWidth:'440px'}}>
                <button onClick={startSample} disabled={running}
                  style={{
                    display:'inline-flex', alignItems:'center', justifyContent:'center', gap:'0.5rem',
                    width:'100%', padding:'0.95rem 1.4rem', borderRadius:'13px', border:'none',
                    cursor: running ? 'default' : 'pointer', opacity: running ? 0.65 : 1,
                    background:'linear-gradient(100deg, var(--accent), #8b5cf6)', color:'#fff',
                    fontWeight:800, fontSize:'1rem', fontFamily:'inherit',
                    boxShadow:'0 12px 26px -12px rgba(79,142,247,0.65)',
                  }}>
                  <Sparkles size={17} /> {t.sampleCta}
                </button>
                <div style={{fontSize:'0.82rem', color:'var(--text-muted)', marginTop:'0.55rem', lineHeight:1.4}}>{t.sampleCtaSub}</div>
                <div style={{fontSize:'0.72rem', color:'var(--text-muted)', marginTop:'0.7rem', opacity:0.7, textTransform:'uppercase', letterSpacing:'0.06em'}}>{t.sampleOr}</div>
              </div>
            )}

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
                    onChange={e => { addFiles(e.target.files); e.target.value = '' }} style={{display:'none'}} />
                  <div className="drop-icon"><Upload size={22} /></div>
                  <div className="drop-title">{t.dropTitle}</div>
                  <div className="drop-sub">{t.dropSub}</div>
                  {dropLine && (
                    <div className="drop-sub" style={{marginTop:'0.4rem', fontWeight:600, color:'var(--privacy-text, #16a34a)'}}>{dropLine}</div>
                  )}
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
                      disabled={!ytUrl.trim() || running}>
                      {running ? <Loader2 size={15} className="spin" /> : <Youtube size={15} />}<span className="tab-label"> {t.ytBtn}</span>
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
                      disabled={(!pasteText.trim() && !pasteUrl.trim()) || running}>
                      {running ? <Loader2 size={15} className="spin" /> : <Type size={15} />}<span className="tab-label"> {t.textBtn}</span>
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

              {/* Output mode: full guide (flashcards, optional quiz) or summary only */}
              <div style={{display:'flex',alignItems:'center',gap:'0.55rem',marginTop:'0.6rem',flexWrap:'wrap'}}>
                <span style={{fontSize:'0.73rem',color:'var(--text-muted)',fontWeight:500,flexShrink:0}}>Output:</span>
                <button
                  className={`detail-tab${!summaryOnly ? ' active' : ''}`}
                  style={{fontSize:'0.73rem',padding:'0.28rem 0.6rem'}}
                  onClick={() => setSummaryOnly(false)}>
                  {isAr ? 'دليل كامل' : 'Full guide'}
                </button>
                <button
                  className={`detail-tab${summaryOnly ? ' active' : ''}`}
                  style={{fontSize:'0.73rem',padding:'0.28rem 0.6rem'}}
                  onClick={() => setSummaryOnly(true)}>
                  {isAr ? 'ملخّص فقط' : 'Summary only'}
                </button>
                {!summaryOnly && (
                  <label style={{display:'flex',alignItems:'center',gap:'0.35rem',fontSize:'0.73rem',color:'var(--text-muted)',cursor:'pointer',marginInlineStart:'0.25rem'}}>
                    <input type="checkbox" checked={includeQuiz} onChange={e => setIncludeQuiz(e.target.checked)} />
                    {isAr ? 'اختبار تدريبي' : 'Practice quiz'}
                  </label>
                )}
              </div>

              {/* Language + Generate All row (only for upload tab) */}
              {inputTab === 'upload' && (
                <div className="options-row" style={{marginTop:'0.65rem'}}>
                  <select className="lang-select" value={lang} onChange={e => chooseLang(e.target.value)}>
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
                direction: isAr ? 'rtl' : 'ltr',
              }}>
                <ShieldCheck size={14} style={{flexShrink:0, marginTop:'1px'}} />
                <span>{t.privacy}</span>
              </div>
            </div>

            {/* Proof / sample output — first-visit only, builds trust before upload */}
            {!hasQueue && (
              <div style={{ marginTop:'2.2rem', direction: isAr ? 'rtl' : 'ltr' }}>
                <div style={{textAlign:'center', marginBottom:'1.2rem'}}>
                  <h2 style={{fontSize:'1.35rem', fontWeight:800, color:'var(--text-primary)', margin:'0 0 0.35rem'}}>{t.sampleTitle}</h2>
                  <p style={{fontSize:'0.9rem', color:'var(--text-muted)', maxWidth:'620px', margin:'0 auto', lineHeight:1.55}}>{t.sampleSub}</p>
                </div>

                {/* How it works — 3 steps */}
                <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))', gap:'0.7rem', marginBottom:'1.1rem'}}>
                  {t.steps.map((st, i) => (
                    <div key={i} className="glass" style={{padding:'0.9rem 1rem', display:'flex', gap:'0.7rem', alignItems:'flex-start'}}>
                      <div style={{flexShrink:0, width:26, height:26, borderRadius:8, display:'grid', placeItems:'center',
                        background:'rgba(79,142,247,0.14)', color:'#4f8ef7', fontWeight:800, fontSize:'0.82rem'}}>{i + 1}</div>
                      <div>
                        <div style={{fontWeight:700, fontSize:'0.86rem', color:'var(--text-primary)'}}>{st.t}</div>
                        <div style={{fontSize:'0.76rem', color:'var(--text-muted)', marginTop:'0.15rem', lineHeight:1.4}}>{st.s}</div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Sample guide card */}
                <div className="glass" style={{padding:'1.15rem 1.3rem'}}>
                  <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:'0.5rem', marginBottom:'0.8rem', flexWrap:'wrap'}}>
                    <span style={{fontWeight:800, fontSize:'1.02rem', color:'var(--text-primary)'}}>{t.sampleGuideTitle}</span>
                    <span style={{fontSize:'0.62rem', fontWeight:800, letterSpacing:'0.06em', padding:'0.2rem 0.5rem', borderRadius:6,
                      background:'rgba(139,92,246,0.14)', color:'#8b5cf6'}}>{t.sampleTag}</span>
                  </div>

                  {/* Key points */}
                  <div style={{fontSize:'0.72rem', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.05em', color:'var(--text-muted)', marginBottom:'0.4rem'}}>{t.sampleKeyLabel}</div>
                  <ul style={{margin:'0 0 1rem', paddingInlineStart:'1.1rem', display:'flex', flexDirection:'column', gap:'0.3rem'}}>
                    {t.sampleKey.map((k, i) => (
                      <li key={i} style={{fontSize:'0.83rem', color:'var(--text-secondary)', lineHeight:1.5}}>{k}</li>
                    ))}
                  </ul>

                  {/* Flashcards + Quiz two-column on wide screens */}
                  <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(230px, 1fr))', gap:'0.8rem'}}>
                    <div>
                      <div style={{fontSize:'0.72rem', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.05em', color:'var(--text-muted)', marginBottom:'0.4rem'}}>{t.sampleFlashLabel}</div>
                      <div style={{display:'flex', flexDirection:'column', gap:'0.45rem'}}>
                        {t.sampleFlash.map((f, i) => (
                          <div key={i} style={{padding:'0.55rem 0.7rem', borderRadius:9, background:'var(--glass-light)', border:'1px solid var(--glass-border)'}}>
                            <div style={{fontSize:'0.8rem', fontWeight:700, color:'var(--text-primary)'}}>{f.q}</div>
                            <div style={{fontSize:'0.78rem', color:'#22c55e', marginTop:'0.2rem'}}>{f.a}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div style={{fontSize:'0.72rem', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.05em', color:'var(--text-muted)', marginBottom:'0.4rem'}}>{t.sampleQuizLabel}</div>
                      <div style={{padding:'0.55rem 0.7rem', borderRadius:9, background:'var(--glass-light)', border:'1px solid var(--glass-border)'}}>
                        <div style={{fontSize:'0.8rem', fontWeight:700, color:'var(--text-primary)', marginBottom:'0.45rem'}}>{t.sampleQuizQ}</div>
                        <div style={{display:'flex', flexDirection:'column', gap:'0.3rem'}}>
                          {t.sampleQuizOpts.map((opt, i) => {
                            const correct = i === t.sampleQuizAnswer
                            return (
                              <div key={i} style={{display:'flex', alignItems:'center', gap:'0.45rem', fontSize:'0.78rem',
                                color: correct ? '#22c55e' : 'var(--text-secondary)', fontWeight: correct ? 700 : 500}}>
                                {correct ? <CheckCircle2 size={14} /> : <span style={{width:14, height:14, borderRadius:'50%', border:'1.5px solid var(--glass-border)', flexShrink:0}} />}
                                <span>{opt}</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Honest trust strip */}
                <div style={{display:'flex', flexWrap:'wrap', justifyContent:'center', gap:'0.4rem 1.2rem', marginTop:'1rem'}}>
                  {t.trust.map((tr, i) => (
                    <span key={i} style={{display:'inline-flex', alignItems:'center', gap:'0.35rem', fontSize:'0.78rem', color:'var(--text-muted)'}}>
                      <ShieldCheck size={13} style={{color:'#22c55e'}} />{tr}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Invite a friend — visible only when signed in */}
            {session && userInfo?.referral_code && (
              <ReferralCard t={t} isAr={isAr} freeMode={freeMode} stats={refStats} copied={copied}
                link={`${window.location.origin}?ref=${userInfo.referral_code}`}
                onCopy={() => copyReferral(userInfo.referral_code)} />
            )}

            {/* Queue */}
            {hasQueue && (
              <div className="glass" style={{marginTop:'1rem',overflow:'hidden'}}>
                {/* Header */}
                <div className="queue-header">
                  <div style={{display:'flex',alignItems:'center',gap:'0.45rem',fontWeight:600,fontSize:'0.88rem',color:'var(--text-primary)'}}>
                    <Files size={15} />
                    {t.items(queue.length)}
                    {doneCount > 0 && <span style={{fontSize:'0.76rem',color:'#22c55e',fontWeight:500}}>· {t.readyCount(doneCount)}</span>}
                  </div>
                  <div className="queue-header-actions" style={{display:'flex',gap:'0.35rem'}}>
                    {inputTab === 'upload' && (
                      <button className="ctrl-btn" onClick={() => inputRef.current?.click()}>
                        <Upload size={12} /><span className="ctrl-label"> {t.addMore}</span>
                      </button>
                    )}
                    {!running && (
                      <button className="ctrl-btn" onClick={clearAll}>
                        <X size={12} /><span className="ctrl-label"> {t.clearAll}</span>
                      </button>
                    )}
                  </div>
                </div>

                {/* Items */}
                {queue.map((item, i) => {
                  const badge = badgeKey(item, session)
                  const sc = STATUS_COLOR[badge] || STATUS_COLOR.queued
                  const failed = item.status === 'expired' || item.status === 'error'
                  const src = item.source || (item.file ? { type: 'file' } : null)
                  // held for sign-in (the free guides are used): not an error, its file / link / text is still here
                  const held = offersSignIn(item, session)
                  // a link or pasted text waiting to run (it was held, the visitor has signed in): files use Generate All
                  const readySrc = item.status === 'queued' && !held && !!src && src.type !== 'file' && src.type !== 'sample'
                  const restorable = canRestore(item)
                  const regenHint = src?.type === 'file' && !item.file ? t.reselectFile
                    : src?.type === 'text' && !src.text && !src.url ? t.repasteText : null
                  const hint = failed && !restorable && regenHint
                  const canRegen = failed && !!src && !regenHint
                  const cachedStudy = item.status === 'expired' && !!item.guide   // works without the server
                  return (
                    <div key={item.id} className="queue-item"
                      style={{background: i % 2 === 0 ? 'transparent' : 'var(--glass-light)'}}>

                      {/* Main info row */}
                      <div className="queue-item-main">
                        <div className="queue-icon">
                          {item.status === 'processing' ? <Loader2 size={15} className="spin" />
                            : held                      ? <LogIn size={15} color="var(--accent)" />
                            : item.status === 'done'    ? <CheckCircle2 size={15} color="#22c55e" />
                            : item.status === 'error'   ? <AlertCircle size={15} color="#ef4444" />
                            : item.status === 'expired' ? <AlertCircle size={15} color="#94a3b8" />
                            : <FileText size={15} />}
                        </div>

                        <div style={{flex:1,minWidth:0}}>
                          {/* own script decides the direction (an Arabic file name stays RTL in an English UI); aligned with the row */}
                          <div className="queue-name" dir="auto" style={{textAlign: isAr ? 'right' : 'left'}}>{item.name}</div>
                          {item.error && <div style={{fontSize:'0.72rem',color:'#ef4444',marginTop:2}}>{item.error}</div>}
                          {/* held for sign-in: a plain (not red) line and the button that opens the sign-in modal with the reason */}
                          {held && (<>
                            <div style={{fontSize:'0.72rem',color:'var(--accent)',fontWeight:600,marginTop:2}}>{t.signInToContinue}</div>
                            <button className="ctrl-btn" onClick={() => openGate(undefined, item.gateReason)}
                              style={{marginTop:6, borderColor:'var(--accent)', color:'var(--accent)'}}>
                              <LogIn size={12} /><span> {t.signInFreeCta}</span>
                            </button>
                          </>)}
                          {item.status === 'expired' && <div style={{fontSize:'0.72rem',color:'var(--text-muted)',marginTop:2}}>{t.expiredNote}</div>}
                          {hint && <div style={{fontSize:'0.72rem',color:'var(--text-muted)',marginTop:2}}>{hint}</div>}
                          {item.status === 'done' && item.partial && <div style={{fontSize:'0.72rem',color:'#fbbf24',marginTop:2}}>{t.partialNote}</div>}
                          {item.status === 'processing' && (
                            <div style={{fontSize:'0.72rem',color:'var(--text-muted)',marginTop:2}}>{procLine(t, item)}</div>
                          )}
                        </div>

                        <div className="queue-status-badge"
                          style={{background:sc.bg,color:sc.color,border:`1px solid ${sc.border}`}}>
                          {badge === 'signin' ? t.signIn : (t[badge] || item.status)}
                        </div>

                        {!running && (
                          <button className="ctrl-btn" onClick={() => removeItem(item.id)} aria-label={t.close}
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
                          <button className="action-btn primary" title={t.download} onClick={() => downloadPDF(item)}
                            disabled={!!item.busy} style={item.busy === 'pdf' ? {opacity:0.7} : undefined}>
                            {item.busy === 'pdf' ? <Loader2 size={12} className="spin" /> : <Download size={12} />}<span className="action-label"> {t.pdf}</span>
                          </button>
                          <button className="action-btn" title={t.shareTitle}
                            style={item.shareUrl ? {borderColor:'rgba(34,197,94,0.4)', color:'#22c55e'} : {}}
                            onClick={() => shareGuide(item)} disabled={item.sharing}>
                            {item.sharing ? <Loader2 size={12} className="spin" /> : item.shareUrl ? <Check size={12} /> : <Share2 size={12} />}
                            <span className="action-label"> {item.shareUrl ? t.shareCopy : t.share}</span>
                          </button>
                          {item.counts?.flashcards !== 0 && (
                            <button className="action-btn" title={t.ankiTip} onClick={() => downloadAnki(item)} disabled={!!item.busy}>
                              {item.busy === 'anki' ? <Loader2 size={12} className="spin" /> : <Download size={12} />}<span className="action-label"> {t.anki}</span>
                            </button>
                          )}
                          <button className="action-btn" title={t.deleteTip} onClick={() => deleteNow(item)} disabled={!!item.busy}>
                            {item.busy === 'delete' ? <Loader2 size={12} className="spin" /> : <X size={12} />}<span className="action-label"> {t.deleteNow}</span>
                          </button>
                          <button className="action-btn" title={t.cardsTip} onClick={() => setFlashModal(item.id)}>
                            <Brain size={12} /><span className="action-label"> {t.cards}</span>
                          </button>
                          <button className="action-btn" title={t.quizTip} onClick={() => setQuizModal(item.id)}>
                            <ClipboardList size={12} /><span className="action-label"> {t.quiz}</span>
                          </button>
                          <button className="action-btn" title={t.overviewTip} onClick={() => setMindmapModal(item.id)}>
                            <Map size={12} /><span className="action-label"> {t.overview}</span>
                          </button>
                          <button className="action-btn" title={t.printTip} onClick={() => openPrint(item)}>
                            <Printer size={12} /><span className="action-label"> {t.print}</span>
                          </button>
                          <button className="action-btn" title={t.chatTip} onClick={() => setChatModal(item.id)}>
                            <MessageSquare size={12} /><span className="action-label"> {t.chat}</span>
                          </button>
                        </div>
                      )}

                      {/* Recovery (expired / failed items): Restore is free; Regenerate re-runs the source
                          (also offered beside Restore, so a copy that won't restore is never a dead end) */}
                      {failed && (restorable || canRegen || cachedStudy) && (
                        <div className="action-row">
                          {restorable && (
                            <button className="action-btn primary" onClick={() => restoreItem(item)} disabled={!!item.busy}>
                              {item.busy === 'restore' ? <Loader2 size={12} className="spin" /> : <RotateCcw size={12} />}
                              <span className="action-label"> {t.restore}</span>
                            </button>
                          )}
                          {canRegen && (
                            <button className={restorable ? 'action-btn' : 'action-btn primary'} onClick={() => regenerate(item)}
                              disabled={running || !!item.busy} style={running ? {opacity:0.6} : undefined}>
                              <RotateCcw size={12} /><span className="action-label"> {item.status === 'expired' ? t.regenerate : t.retry}</span>
                            </button>
                          )}
                          {cachedStudy && (<>
                            <button className="action-btn" title={t.cardsTip} onClick={() => setFlashModal(item.id)}>
                              <Brain size={12} /><span className="action-label"> {t.cards}</span>
                            </button>
                            <button className="action-btn" title={t.quizTip} onClick={() => setQuizModal(item.id)}>
                              <ClipboardList size={12} /><span className="action-label"> {t.quiz}</span>
                            </button>
                            <button className="action-btn" title={t.overviewTip} onClick={() => setMindmapModal(item.id)}>
                              <Map size={12} /><span className="action-label"> {t.overview}</span>
                            </button>
                          </>)}
                        </div>
                      )}

                      {/* A link / pasted text that was held for sign-in and can run now: one tap, nothing to type again */}
                      {readySrc && (
                        <div className="action-row">
                          <button className="action-btn primary" onClick={() => regenerate(item)}
                            disabled={running || !!item.busy} style={running ? {opacity:0.6} : undefined}>
                            <Sparkles size={12} /><span className="action-label"> {t.generateNow}</span>
                          </button>
                        </div>
                      )}

                      {/* Public share link (shown after sharing) */}
                      {item.status === 'done' && item.shareUrl && (
                        <div style={{
                          margin:'0 1.2rem 0.9rem', padding:'0.55rem 0.7rem', borderRadius:9,
                          background:'var(--glass-light)', border:'1px solid var(--glass-border)',
                          display:'flex', alignItems:'center', gap:'0.5rem',
                          direction: isAr ? 'rtl' : 'ltr',
                        }}>
                          <Share2 size={13} style={{color:'#22c55e', flexShrink:0}} />
                          <input readOnly value={item.shareUrl}
                            onClick={e => e.target.select()}
                            style={{flex:1, minWidth:0, background:'transparent', border:'none', outline:'none',
                              color:'var(--text-secondary)', fontSize:'0.78rem', fontFamily:'inherit', cursor:'text'}} />
                          <span style={{fontSize:'0.7rem', color:'var(--text-muted)', flexShrink:0}}>{t.shareNote}</span>
                          <button className="ctrl-btn" style={{padding:'0.3rem 0.5rem', flexShrink:0}}
                            onClick={() => shareGuide(item)}>
                            <Copy size={12} /><span className="ctrl-label"> {t.shareCopy}</span>
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {/* After a visitor's first real guide: a quiet, dismissible invitation to create a free account */}
            {showJoinCard({ freeMode, authEnabled, authLoading, session, dismissed: joinDismissed, queue }) && (
              <JoinCard t={t} isAr={isAr} fair={fair} left={anonGate.remaining} limit={anonGate.limit} onJoin={openSignUp} onDismiss={dismissJoin} />
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
        <footer className="site-footer" style={{ direction: isAr ? 'rtl' : 'ltr' }}>
          <div style={{marginBottom:'0.6rem'}}>
            © 2026 Alimne &nbsp;·&nbsp;
            <button onClick={() => setShowTerms(true)} className="footer-terms-btn">
              {isAr ? 'الشروط والأحكام' : 'Terms & Conditions'}
            </button>
            &nbsp;·&nbsp;
            <a href="/privacy" className="footer-terms-btn" style={{textDecoration:'none'}}>
              {isAr ? 'سياسة الخصوصية' : 'Privacy Policy'}
            </a>
            &nbsp;·&nbsp;
            {t.footerFree}
          </div>
          <a
            href="https://souc.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="souc-pill"
          >
            <span style={{fontSize:'0.6rem', opacity:0.7}}>⚡</span>
            {isAr ? 'مدعوم من souc.ai' : 'Powered by souc.ai'}
          </a>
        </footer>
      </div>

      {/* ── Modals ── */}
      {flashItem && (
        <FlashCardModal key={flashItem.id} jobId={flashItem.jobId} srKey={srKeyOf(flashItem)}
          {...studyProps(flashItem, () => setFlashModal(null))} />
      )}
      {quizItem && (
        <QuizModal key={quizItem.id} jobId={quizItem.jobId} filename={quizItem.name}
          {...studyProps(quizItem, () => setQuizModal(null))} />
      )}
      {viewItem && <OverviewModal key={viewItem.id} {...studyProps(viewItem, () => setMindmapModal(null))} />}
      {chatItem && (
        <ChatModal key={chatItem.id} t={t} isAr={isAr}
          needsSignIn={authEnabled && !authLoading && !session}
          onSignIn={() => { setChatModal(null); openLogin('signin') }}
          ask={q => askGuide(chatItem.id, q)}
          onClose={() => setChatModal(null)} />
      )}
      {showHistory  && <HistoryModal onClose={() => setShowHistory(false)} />}
      {showTerms    && <TermsModal lang={uiLang} freeMode={freeMode} freeUses={anonGate.limit} onClose={() => setShowTerms(false)} />}
      {showLogin    && (
        <LoginModal key={loginKey} onClose={() => { setShowLogin(false); setLoginNotice(null); setLoginGate(null) }}
          lang={uiLang} sbClient={sb} initialMode={loginMode} freeMode={freeMode} fair={fair} gate={loginGate}
          beforeLeave={stashForSignIn} leaveFailed={dropStash}
          initialEmail={ls.get('alimne_lead') || ''} notice={loginNotice} />
      )}
      {showSetPw && sb && <SetPasswordModal onClose={() => setShowSetPw(false)} lang={uiLang} sbClient={sb} />}
      {!freeMode && showUpgrade && (
        <UpgradeModal
          onClose={() => setShowUpgrade(false)}
          onUpgrade={handleCheckout}
          onManage={handleManageBilling}
          isSubscribed={liveSub}
          lang={uiLang}
        />
      )}
      {showAccount && session && (
        <AccountModal
          onClose={() => setShowAccount(false)}
          onManage={handleManageBilling}
          onUpgrade={() => { setShowAccount(false); handleCheckout() }}
          onSignOut={userSignOut}
          userInfo={userInfo}
          isSubscribed={isSubscribed}
          lang={uiLang}
          loadErr={userInfoErr}
          onRetry={() => fetchUserInfo()}
          freeMode={freeMode}
          fair={fair}
        />
      )}
      {!freeMode && showEmailCapture && (
        <EmailCaptureModal
          onClose={() => setShowEmailCapture(false)}
          onSubmit={submitLead}
          onSkip={skipLead}
          lang={uiLang}
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
        .action-btn:disabled { cursor: default; }
        /* nav counter: the bare number shows only where the nav hides its labels (phones) */
        .gate-short { display: none; font-weight: 700; }
        @media (max-width: 600px) { .gate-short { display: inline; } }
        @media print {
          .nav, button, .modal-overlay { display: none !important; }
        }
      `}</style>
    </div>
  )
}
