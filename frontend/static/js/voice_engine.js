/**
 * AgenticLiner - Web Speech Voice Engine
 * Pillar 1: Speech-to-Text (STT) & Text-to-Speech (TTS) Controller
 * Zero-dependency native browser Speech Recognition and Speech Synthesis.
 */

class WebSpeechVoiceEngine {
    constructor(options = {}) {
        this.inputSelector = options.inputSelector || '#agentPrompt';
        this.btnSelector = options.btnSelector || '#btnVoiceInput';
        this.iconSelector = options.iconSelector || '#micIcon';
        this.bannerSelector = options.bannerSelector || '#voiceStatusBanner';
        this.statusTextSelector = options.statusTextSelector || '#voiceStatusText';
        this.stateBadgeSelector = options.stateBadgeSelector || '#voiceStateBadge';
        this.ttsToggleSelector = options.ttsToggleSelector || '#toggleVoiceFeedback';
        this.ttsIconSelector = options.ttsIconSelector || '#ttsIcon';
        this.ttsLabelSelector = options.ttsLabelSelector || '#ttsLabel';

        this.lang = options.lang || 'en-IN'; // Indian English handles Hindi phonetics cleanly
        this.isListening = false;
        this.isProcessing = false;
        this.recognition = null;
        this.isTTSEnabled = localStorage.getItem('agenticliner_tts_enabled') !== 'false';
        this.baseTextBeforeSpeech = '';

        this.initVoiceEngine();
    }

    /**
     * Checks browser support and initializes Web Speech Recognition
     */
    initVoiceEngine() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (!SpeechRecognition) {
            console.warn('[VoiceEngine] Web Speech API is not supported in this browser.');
            this.handleUnsupported();
            return;
        }

        try {
            this.recognition = new SpeechRecognition();
            this.recognition.continuous = true;
            this.recognition.interimResults = true;
            this.recognition.lang = this.lang;
            this.recognition.maxAlternatives = 1;

            this.bindEvents();
            this.updateTTSUI();
        } catch (err) {
            console.error('[VoiceEngine] Initialization error:', err);
        }
    }

    /**
     * Bind UI event listeners and recognition callbacks
     */
    bindEvents() {
        const micBtn = document.querySelector(this.btnSelector);
        if (micBtn) {
            micBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleSpeechRecognition();
            });
        }

        const ttsToggle = document.querySelector(this.ttsToggleSelector);
        if (ttsToggle) {
            ttsToggle.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleTTS();
            });
        }

        if (!this.recognition) return;

        this.recognition.onstart = () => this.onSpeechStart();
        this.recognition.onresult = (event) => this.onSpeechResult(event);
        this.recognition.onend = () => this.onSpeechEnd();
        this.recognition.onerror = (event) => this.onSpeechError(event);
    }

    /**
     * Toggles speech recognition listening state
     */
    toggleSpeechRecognition() {
        if (!this.recognition) {
            alert('Voice input is not supported in this browser. Please use Chrome, Edge, or Brave.');
            return;
        }

        if (this.isListening) {
            this.stopSpeechRecognition();
        } else {
            this.startSpeechRecognition();
        }
    }

    startSpeechRecognition() {
        try {
            if (window.speechSynthesis && window.speechSynthesis.speaking) {
                window.speechSynthesis.cancel();
            }
            if (window._activeVoiceEngine && window._activeVoiceEngine !== this) {
                window._activeVoiceEngine.stopSpeechRecognition();
            }
            window._activeVoiceEngine = this;

            const inputEl = document.querySelector(this.inputSelector);
            this.baseTextBeforeSpeech = inputEl ? inputEl.value.trim() : '';
            this.shouldStayListening = true;
            this.recognition.start();
        } catch (err) {
            console.warn('[VoiceEngine] Start error or already started:', err);
        }
    }

    stopSpeechRecognition() {
        this.shouldStayListening = false;
        this.isListening = false;
        try {
            if (window._activeVoiceEngine === this) {
                window._activeVoiceEngine = null;
            }
            this.recognition.stop();
        } catch (err) {
            console.warn('[VoiceEngine] Stop error:', err);
        }
        this.setButtonState('idle');
        this.showBanner(false);
        this.updateBadge('Ready', 'bg-light text-secondary border');
    }

    /**
     * Handler when microphone starts listening
     */
    onSpeechStart() {
        // OpenAI-Style Full-Duplex Barge-In:
        // Cancel agent speech immediately when user starts speaking
        if (window.speechSynthesis && window.speechSynthesis.speaking) {
            window.speechSynthesis.cancel();
        }

        this.isListening = true;
        this.shouldStayListening = true;
        this.setButtonState('listening');
        if (window.voiceOrb) window.voiceOrb.setState('listening');
        this.showBanner(true, 'Listening... Bolna shuru karein (Aap English ya Hindi me bol sakte hain)...');
        this.updateBadge('Listening...', 'bg-danger text-white');
    }

    /**
     * Handler for real-time speech results streaming into the textarea
     */
    onSpeechResult(event) {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                finalTranscript += transcript;
            } else {
                interimTranscript += transcript;
            }
        }

        const inputEl = document.querySelector(this.inputSelector);
        if (inputEl) {
            const prefix = this.baseTextBeforeSpeech ? this.baseTextBeforeSpeech + ' ' : '';
            const currentSpeech = (finalTranscript || interimTranscript).trim();
            inputEl.value = prefix + currentSpeech;
            // Auto-scroll textarea to end
            inputEl.scrollTop = inputEl.scrollHeight;
        }

        if (finalTranscript && typeof this.onConfirmationCallback === 'function') {
            const cb = this.onConfirmationCallback;
            this.onConfirmationCallback = null;
            cb(finalTranscript.trim());
        }
    }

    /**
     * Handler when microphone recording ends
     */
    onSpeechEnd() {
        if (this.shouldStayListening && this.isListening) {
            try {
                this.recognition.start();
                return;
            } catch (err) {
                console.log('[VoiceEngine] Keepalive restart notice:', err);
            }
        }

        this.isListening = false;
        this.shouldStayListening = false;
        this.setButtonState('idle');
        if (window.voiceOrb && window.voiceOrb.state !== 'speaking' && window.voiceOrb.state !== 'confirmed') {
            window.voiceOrb.setState('idle');
        }
        this.showBanner(false);
        this.updateBadge('Ready', 'bg-light text-secondary border');

        const inputEl = document.querySelector(this.inputSelector);
        if (inputEl && inputEl.value.trim()) {
            inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            inputEl.focus();
        }
    }

    /**
     * Handler for speech recognition errors
     */
    onSpeechError(event) {
        console.warn('[VoiceEngine] Error occurred:', event.error);

        if (event.error === 'no-speech') {
            // User briefly paused; keep mic active
            return;
        }

        this.isListening = false;
        this.shouldStayListening = false;

        if (event.error === 'not-allowed') {
            this.setButtonState('denied');
            this.updateBadge('Permission Denied', 'bg-warning text-dark border');
            this.showBanner(true, 'Microphone permission blocked. Please allow mic in your browser address bar.');
            setTimeout(() => this.showBanner(false), 6000);
        } else if (event.error === 'network') {
            this.setButtonState('idle');
            this.updateBadge('Network Error', 'bg-danger text-white border');
            this.showBanner(true, 'Speech recognition network service unavailable. You can type directly into the box.');
            setTimeout(() => {
                this.showBanner(false);
                this.updateBadge('Ready', 'bg-light text-secondary border');
            }, 6000);
        } else if (event.error === 'audio-capture') {
            this.setButtonState('denied');
            this.updateBadge('No Mic Detected', 'bg-warning text-dark border');
            this.showBanner(true, 'No microphone found on system. Please connect a microphone or type your brief.');
            setTimeout(() => this.showBanner(false), 5000);
        } else {
            this.setButtonState('idle');
            this.showBanner(false);
            this.updateBadge('Ready', 'bg-light text-secondary border');
        }
    }

    /**
     * Sets the visual state of the microphone button (4 states)
     * @param {'idle'|'listening'|'processing'|'denied'} state
     */
    setButtonState(state) {
        const btn = document.querySelector(this.btnSelector);
        const icon = document.querySelector(this.iconSelector);
        if (!btn) return;

        btn.classList.remove('state-idle', 'state-listening', 'state-processing', 'state-denied');

        if (state === 'listening') {
            btn.classList.add('state-listening');
            btn.title = 'Listening... Click to stop';
            if (icon) icon.className = 'bi bi-soundwave';
        } else if (state === 'processing') {
            btn.classList.add('state-processing');
            btn.title = 'Finalizing text...';
            if (icon) icon.className = 'spinner-border spinner-border-sm';
        } else if (state === 'denied') {
            btn.classList.add('state-denied');
            btn.title = 'Microphone blocked in browser';
            if (icon) icon.className = 'bi bi-mic-mute-fill';
        } else {
            btn.classList.add('state-idle');
            btn.title = 'Click to Speak / Bol kar batayein';
            if (icon) icon.className = 'bi bi-mic-fill';
        }
    }

    /**
     * Shows or hides the live speech banner
     */
    showBanner(show, message) {
        const banner = document.querySelector(this.bannerSelector);
        const statusText = document.querySelector(this.statusTextSelector);
        if (!banner) return;

        if (show) {
            banner.classList.remove('d-none');
            if (statusText && message) statusText.textContent = message;
        } else {
            banner.classList.add('d-none');
        }
    }

    /**
     * Updates the status badge
     */
    updateBadge(text, classNames) {
        const badge = document.querySelector(this.stateBadgeSelector);
        if (!badge) return;
        badge.textContent = text;
        badge.className = `badge ${classNames}`;
    }

    /**
     * Handles unsupported browsers
     */
    handleUnsupported() {
        const btn = document.querySelector(this.btnSelector);
        if (btn) {
            btn.classList.add('state-denied');
            btn.title = 'Speech recognition not supported in this browser';
            btn.disabled = true;
        }
    }

    /**
     * Toggles assistant voice output (TTS)
     */
    toggleTTS() {
        this.isTTSEnabled = !this.isTTSEnabled;
        localStorage.setItem('agenticliner_tts_enabled', this.isTTSEnabled ? 'true' : 'false');
        this.updateTTSUI();

        if (this.isTTSEnabled) {
            this.speakAssistantVoice('Voice audio is now enabled.');
        } else {
            if (window.speechSynthesis) window.speechSynthesis.cancel();
        }
    }

    /**
     * Updates the TTS toggle button UI
     */
    updateTTSUI() {
        const icon = document.querySelector(this.ttsIconSelector);
        const label = document.querySelector(this.ttsLabelSelector);

        if (this.isTTSEnabled) {
            if (icon) icon.className = 'bi bi-volume-up-fill text-primary';
            if (label) {
                label.textContent = 'Voice Audio ON';
                label.className = 'small text-primary fw-semibold';
            }
        } else {
            if (icon) icon.className = 'bi bi-volume-mute-fill text-muted';
            if (label) {
                label.textContent = 'Voice Audio MUTE';
                label.className = 'small text-muted';
            }
        }
    }

    /**
     * Speaks assistant voice using window.speechSynthesis
     * @param {string} text
     * @param {Function} onComplete
     */
    speakAssistantVoice(text, onComplete) {
        if (!this.isTTSEnabled || !window.speechSynthesis || !text) {
            if (onComplete) onComplete();
            return;
        }

        try {
            window.speechSynthesis.cancel(); // Stop any pending speech

            const utterance = new SpeechSynthesisUtterance(text);
            utterance.rate = 1.0;
            utterance.pitch = 1.0;

            // Find an Indian English / Hindi voice if available
            const voices = window.speechSynthesis.getVoices();
            const preferredVoice = voices.find(v => v.lang.includes('en-IN') || v.lang.includes('hi-IN')) ||
                                   voices.find(v => v.lang.includes('en-US')) ||
                                   voices[0];

            if (preferredVoice) {
                utterance.voice = preferredVoice;
            }

            if (window.voiceOrb) window.voiceOrb.setState('speaking');

            const wrappedComplete = () => {
                if (window.voiceOrb && window.voiceOrb.state !== 'confirmed') {
                    window.voiceOrb.setState('idle');
                }
                if (onComplete) onComplete();
            };

            utterance.onend = wrappedComplete;
            utterance.onerror = wrappedComplete;

            window.speechSynthesis.speak(utterance);
        } catch (err) {
            console.warn('[VoiceEngine] TTS error:', err);
            if (window.voiceOrb) window.voiceOrb.setState('idle');
            if (onComplete) onComplete();
        }
    }

    /**
     * Primed single-turn confirmation listener (ChatGPT Realtime style)
     */
    listenForConfirmation(callback) {
        this.onConfirmationCallback = callback;
        if (!this.isListening) {
            this.startSpeechRecognition();
        }
    }

    /**
     * Sub-50ms Fast-Path Intent Recognition (Client-side helper)
     */
    classifyFastIntent(text) {
        const clean = (text || '').trim().toLowerCase();
        const confirmPatterns = /\b(yes|yep|yeah|yup|sure|confirm|confirmed|book\s*it|lock\s*it|go\s*ahead|proceed|done|perfect|looks\s*good|all\s*good|fine|ok|okay|haan?|ha|hnn|kar\s*do|kardo|kar\s*dijiye|lock\s*karo|lock\s*kar\s*do|theek\s*hai|thik\s*hai|sahi\s*hai|chalo|pakka|final\s*karo|final\s*hai|book\s*karo|book\s*kar\s*do|chalega)\b/i;
        const cancelPatterns = /\b(no|nope|cancel|stop|abort|don'?t\s*book|nevermind|wait|hold\s*on|hold\s*up|nahi|na|mat\s*karna|mat\s*karo|ruko|ruk\s*jao|rok\s*do|cancel\s*karo|rehne\s*do|chhod\s*do|nahi\s*chahiye)\b/i;

        if (cancelPatterns.test(clean)) return { intent: 'cancel', text: clean };
        if (confirmPatterns.test(clean)) return { intent: 'confirm', text: clean };
        return { intent: 'delta', text: clean };
    }
}

/**
 * ChatGPT-Style Interactive Voice Orb Controller
 * Renders and animates fluid neon sphere across 5 distinct states:
 * 'idle', 'listening', 'thinking', 'speaking', 'confirmed'
 */
class VoiceOrbController {
    constructor(elementId = 'chatgptVoiceOrb') {
        this.elementId = elementId;
        this.state = 'idle';
        this.init();
    }

    init() {
        this.el = document.getElementById(this.elementId);
        if (this.el) {
            this.setState('idle');
        }
    }

    setState(newState) {
        this.state = newState;
        this.el = document.getElementById(this.elementId);
        if (!this.el) return;

        this.el.classList.remove('orb-idle', 'orb-listening', 'orb-thinking', 'orb-speaking', 'orb-confirmed');
        this.el.classList.add(`orb-${newState}`);

        const label = document.getElementById('voiceOrbStatusLabel');
        if (label) {
            const labels = {
                idle: 'Voice Assistant Ready',
                listening: 'Listening to your reply...',
                thinking: 'Thinking Fast...',
                speaking: 'Speaking Summary...',
                confirmed: 'Booking Confirmed!'
            };
            label.textContent = labels[newState] || newState;
        }
    }
}

// Global initialization helpers
window.WebSpeechVoiceEngine = WebSpeechVoiceEngine;
window.VoiceOrbController = VoiceOrbController;
window.voiceOrb = new VoiceOrbController('chatgptVoiceOrb');

