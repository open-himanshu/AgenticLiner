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
            this.recognition.continuous = false;
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
            micBtn.addEventListener('click', () => this.toggleSpeechRecognition());
        }

        const ttsToggle = document.querySelector(this.ttsToggleSelector);
        if (ttsToggle) {
            ttsToggle.addEventListener('click', () => this.toggleTTS());
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
            const inputEl = document.querySelector(this.inputSelector);
            this.baseTextBeforeSpeech = inputEl ? inputEl.value.trim() : '';
            this.recognition.start();
        } catch (err) {
            console.warn('[VoiceEngine] Start error or already started:', err);
        }
    }

    stopSpeechRecognition() {
        try {
            this.recognition.stop();
        } catch (err) {
            console.warn('[VoiceEngine] Stop error:', err);
        }
    }

    /**
     * Handler when microphone starts listening
     */
    onSpeechStart() {
        this.isListening = true;
        this.setButtonState('listening');
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
    }

    /**
     * Handler when microphone recording ends
     */
    onSpeechEnd() {
        this.isListening = false;
        this.setButtonState('idle');
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
        this.isListening = false;

        if (event.error === 'not-allowed') {
            this.setButtonState('denied');
            this.updateBadge('Permission Denied', 'bg-warning text-dark border');
            this.showBanner(true, 'Microphone permission blocked. Please allow mic in your browser address bar.');
            setTimeout(() => this.showBanner(false), 6000);
        } else if (event.error === 'no-speech') {
            this.setButtonState('idle');
            this.showBanner(false);
            this.updateBadge('Idle', 'bg-light text-secondary border');
        } else {
            this.setButtonState('idle');
            this.showBanner(false);
            this.updateBadge('Idle', 'bg-light text-secondary border');
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

            if (onComplete) {
                utterance.onend = onComplete;
                utterance.onerror = onComplete;
            }

            window.speechSynthesis.speak(utterance);
        } catch (err) {
            console.warn('[VoiceEngine] TTS error:', err);
            if (onComplete) onComplete();
        }
    }
}

// Global initialization helper
window.WebSpeechVoiceEngine = WebSpeechVoiceEngine;
