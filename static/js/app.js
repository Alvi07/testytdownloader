/**
 * ProStream - Advanced Media Downloader Client Application
 * Complete with Google reCAPTCHA Enterprise Integration
 */

document.addEventListener('DOMContentLoaded', () => {
    // =========================================================================
    // DOM Elements
    // =========================================================================
    const downloadForm = document.getElementById('downloadForm');
    const videoUrlInput = document.getElementById('videoUrlInput');
    const pasteBtn = document.getElementById('pasteBtn');
    const clearBtn = document.getElementById('clearBtn');
    const submitBtn = document.getElementById('submitBtn');
    const btnSpinner = document.getElementById('btnSpinner');
    const btnText = submitBtn.querySelector('.btn-text');
    const btnArrow = submitBtn.querySelector('.btn-arrow');
    
    // Skeleton & Result Sections
    const skeletonLoader = document.getElementById('skeletonLoader');
    const resultSection = document.getElementById('resultSection');
    
    // Media Info Preview
    const videoThumb = document.getElementById('videoThumb');
    const videoDuration = document.getElementById('videoDuration');
    const videoTitle = document.getElementById('videoTitle');
    const videoChannel = document.getElementById('videoChannel');
    const videoViews = document.getElementById('videoViews');
    
    // Format Selection Tabs & Grids
    const formatTabs = document.querySelectorAll('.format-tab');
    const videoFormatsGrid = document.getElementById('videoFormatsGrid');
    const audioFormatsGrid = document.getElementById('audioFormatsGrid');
    const selectedFormatLabel = document.getElementById('selectedFormatLabel');
    const startDownloadBtn = document.getElementById('startDownloadBtn');
    
    // Progress Box
    const downloadProgressBox = document.getElementById('downloadProgressBox');
    const progressBarFill = document.getElementById('progressBarFill');
    const progressPercent = document.getElementById('progressPercent');
    const progressStatusText = document.getElementById('progressStatusText');
    
    // History Drawer
    const historyToggleBtn = document.getElementById('historyToggleBtn');
    const historyDrawer = document.getElementById('historyDrawer');
    const historyOverlay = document.getElementById('historyOverlay');
    const closeHistoryBtn = document.getElementById('closeHistoryBtn');
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');
    const historyList = document.getElementById('historyList');
    const historyBadge = document.getElementById('historyBadge');
    
    // Toast Container
    const toastContainer = document.getElementById('toastContainer');
    
    // FAQ Items
    const faqItems = document.querySelectorAll('.faq-item');

    // =========================================================================
    // State Variables
    // =========================================================================
    let currentVideoData = null;
    let selectedFormat = {
        type: 'video',
        quality: '720p',
        label: '720p HD (MP4)'
    };
    let downloadHistory = JSON.parse(localStorage.getItem('prostream_history') || '[]');
    let isProcessing = false;

    // =========================================================================
    // Initialize
    // =========================================================================
    updateHistoryUI();

    // =========================================================================
    // reCAPTCHA Token Generation
    // COMMENTED for local/dev — uncomment original block for production
    // =========================================================================
    // const RECAPTCHA_SITE_KEY = "6LdZC6UtAAAAANXdxkFgR8kytF7NunawaiLYZMtQ";
    //
    // /**
    //  * Generate reCAPTCHA Enterprise token
    //  * @param {string} action - Action name (download, info, etc.)
    //  * @returns {Promise<string>} reCAPTCHA token
    //  */
    // async function getRecaptchaToken(action = 'download') {
    //     try {
    //         // Wait for reCAPTCHA to be ready
    //         await new Promise((resolve) => {
    //             if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {
    //                 grecaptcha.enterprise.ready(resolve);
    //             } else {
    //                 // Fallback: wait for script to load
    //                 const checkReady = () => {
    //                     if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {
    //                         grecaptcha.enterprise.ready(resolve);
    //                     } else {
    //                         setTimeout(checkReady, 100);
    //                     }
    //                 };
    //                 checkReady();
    //             }
    //         });
    //
    //         // Execute reCAPTCHA
    //         const token = await grecaptcha.enterprise.execute(
    //             RECAPTCHA_SITE_KEY,
    //             { action: action }
    //         );
    //
    //         if (!token) {
    //             throw new Error('reCAPTCHA token was not generated.');
    //         }
    //
    //         return token;
    //     } catch (error) {
    //         console.error('reCAPTCHA Enterprise error:', error);
    //         throw new Error('Security verification failed. Please refresh and try again.');
    //     }
    // }

    // Local/dev stub — reCAPTCHA disabled (original above is preserved as comments)
    async function getRecaptchaToken(action = 'download') {
        return null;
    }

    // =========================================================================
    // URL Input & Clipboard Handlers
    // =========================================================================
    videoUrlInput.addEventListener('input', () => {
        if (videoUrlInput.value.trim().length > 0) {
            clearBtn.classList.remove('hidden');
        } else {
            clearBtn.classList.add('hidden');
        }
    });

    clearBtn.addEventListener('click', () => {
        videoUrlInput.value = '';
        clearBtn.classList.add('hidden');
        videoUrlInput.focus();
    });

    pasteBtn.addEventListener('click', async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text && text.trim()) {
                videoUrlInput.value = text.trim();
                clearBtn.classList.remove('hidden');
                showToast('Pasted URL from clipboard!', 'success');
                // Auto trigger analyze if valid URL
                if (text.startsWith('http')) {
                    downloadForm.dispatchEvent(new Event('submit'));
                }
            } else {
                showToast('Clipboard is empty', 'error');
            }
        } catch (err) {
            showToast('Unable to read clipboard. Please paste manually.', 'error');
        }
    });

    // =========================================================================
    // Video Analysis with reCAPTCHA
    // =========================================================================
    downloadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (isProcessing) return;
        
        const url = videoUrlInput.value.trim();

        if (!url) {
            showToast('Please enter a video URL.', 'error');
            return;
        }

        // Show loading state
        setAnalyzeLoading(true);
        resultSection.classList.add('hidden');
        skeletonLoader.classList.remove('hidden');

        try {
            // STEP 1: Get reCAPTCHA token
            // COMMENTED original: const recaptchaToken = await getRecaptchaToken('info');
            const recaptchaToken = await getRecaptchaToken('info'); // local stub → null
            
            // STEP 2: Send request with token
            const response = await fetch('/api/info', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ 
                    url: url
                    // , recaptcha_token: recaptchaToken  // COMMENTED for local/dev
                })
            });

            const result = await response.json();

            // STEP 3: Handle responses
            if (response.status === 403) {
                throw new Error(result.detail || 'Security verification failed. Please try again.');
            }
            
            if (response.status === 429) {
                throw new Error('Too many requests. Please wait a moment.');
            }

            if (!response.ok) {
                throw new Error(result.detail || 'Failed to analyze video.');
            }

            if (!result.success) {
                throw new Error(result.detail || 'Video analysis failed.');
            }

            currentVideoData = result.data;
            renderVideoDetails(currentVideoData);
            skeletonLoader.classList.add('hidden');
            resultSection.classList.remove('hidden');
            
            resultSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            showToast('Video details loaded successfully!', 'success');
            
        } catch (error) {
            skeletonLoader.classList.add('hidden');
            showToast(error.message, 'error');
            
            // Reset reCAPTCHA on error (COMMENTED for local/dev)
            // resetRecaptcha();
        } finally {
            setAnalyzeLoading(false);
        }
    });

    function setAnalyzeLoading(isLoading) {
        isProcessing = isLoading;
        if (isLoading) {
            submitBtn.disabled = true;
            btnSpinner.classList.remove('hidden');
            btnArrow.classList.add('hidden');
            btnText.textContent = 'Analyzing...';
        } else {
            submitBtn.disabled = false;
            btnSpinner.classList.add('hidden');
            btnArrow.classList.remove('hidden');
            btnText.textContent = 'Analyze Video';
        }
    }

    // COMMENTED for local/dev — uncomment for production
    // function resetRecaptcha() {
    //     try {
    //         if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {
    //             grecaptcha.enterprise.reset();
    //         }
    //     } catch (e) {
    //         // Silent fail - not critical
    //     }
    // }
    function resetRecaptcha() {
        // Local/dev stub — reCAPTCHA disabled
    }

    // =========================================================================
    // Render Video Details & Formats
    // =========================================================================
    function renderVideoDetails(data) {
        videoThumb.src = data.thumbnail || 'https://via.placeholder.com/640x360?text=No+Thumbnail';
        videoDuration.textContent = data.duration_formatted || '00:00';
        videoTitle.textContent = data.title || 'Untitled Video';
        videoChannel.textContent = data.uploader || 'Creator';
        videoViews.textContent = `${data.view_count_formatted || '0'} views`;

        // Render Video Formats
        videoFormatsGrid.innerHTML = '';
        const videoOptions = data.video_options || [];
        
        videoOptions.forEach((opt, index) => {
            const card = document.createElement('div');
            card.className = `format-card ${index === 0 ? 'selected' : ''}`;
            card.dataset.type = 'video';
            // Backend video options use resolution (720p), not format_key
            const q = opt.resolution || opt.format_key || '720p';
            card.dataset.quality = q;
            card.dataset.label = `${q} (${(opt.ext || 'mp4').toUpperCase()})`;

            card.innerHTML = `
                <div class="format-header">
                    <span class="format-res">${q}</span>
                    <span class="format-pill ${opt.height >= 720 ? 'highlight' : ''}">${opt.quality_tag || 'HD'}</span>
                </div>
                <div class="format-size">${opt.filesize_formatted || 'N/A'}</div>
            `;

            card.addEventListener('click', () => selectFormatCard(card));
            videoFormatsGrid.appendChild(card);
        });

        // Render Audio Formats
        audioFormatsGrid.innerHTML = '';
        const audioOptions = data.audio_options || [];

        audioOptions.forEach((opt) => {
            const card = document.createElement('div');
            card.className = 'format-card';
            card.dataset.type = 'audio';
            card.dataset.quality = opt.format_key;
            card.dataset.label = `${opt.title} (${opt.ext.toUpperCase()})`;
            card.dataset.formatKey = opt.format_key;

            card.innerHTML = `
                <div class="format-header">
                    <span class="format-res">${opt.ext.toUpperCase()}</span>
                    <span class="format-pill highlight">${opt.bitrate}</span>
                </div>
                <div class="format-size">${opt.filesize_formatted || 'N/A'}</div>
            `;

            card.addEventListener('click', () => selectFormatCard(card));
            audioFormatsGrid.appendChild(card);
        });

        // Set default selection to highest quality video
        if (videoOptions.length > 0) {
            const defaultQ = videoOptions[0].resolution || '720p';
            selectedFormat = {
                type: 'video',
                quality: defaultQ,
                label: `${defaultQ} (MP4)`
            };
            selectedFormatLabel.textContent = selectedFormat.label;
        }

        // Reset format tabs to Video
        formatTabs.forEach(tab => {
            if (tab.dataset.type === 'video') tab.classList.add('active');
            else tab.classList.remove('active');
        });
        videoFormatsGrid.classList.remove('hidden');
        audioFormatsGrid.classList.add('hidden');
    }

    // Format Tab Switching
    formatTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            formatTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            const type = tab.dataset.type;
            if (type === 'video') {
                videoFormatsGrid.classList.remove('hidden');
                audioFormatsGrid.classList.add('hidden');
                const firstCard = videoFormatsGrid.querySelector('.format-card');
                if (firstCard) selectFormatCard(firstCard);
            } else {
                videoFormatsGrid.classList.add('hidden');
                audioFormatsGrid.classList.remove('hidden');
                const firstCard = audioFormatsGrid.querySelector('.format-card');
                if (firstCard) selectFormatCard(firstCard);
            }
        });
    });

    function selectFormatCard(card) {
        document.querySelectorAll('.format-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');

        const q = card.dataset.quality || (card.dataset.type === 'audio' ? 'm4a_best' : '720p');
        selectedFormat = {
            type: card.dataset.type || 'video',
            quality: q,
            label: card.dataset.label || `${q} (MP4)`
        };
        selectedFormatLabel.textContent = selectedFormat.label;
    }

    // =========================================================================
    // Download Execution with reCAPTCHA
    // =========================================================================
    startDownloadBtn.addEventListener('click', async () => {
        if (!currentVideoData || isProcessing) return;

        isProcessing = true;
        startDownloadBtn.disabled = true;
        downloadProgressBox.classList.remove('hidden');
        progressBarFill.style.width = '0%';
        progressPercent.textContent = '0%';
        progressStatusText.innerHTML = '<i class="fa-solid fa-shield-halved fa-spin"></i> Security verification...';

        try {
            // STEP 1: Get fresh reCAPTCHA token for download
            // COMMENTED original: const recaptchaToken = await getRecaptchaToken('download');
            const recaptchaToken = await getRecaptchaToken('download'); // local stub → null
            
            // STEP 2: Update progress
            progressStatusText.innerHTML = '<i class="fa-solid fa-gear fa-spin"></i> Preparing download...';
            progressBarFill.style.width = '30%';
            progressPercent.textContent = '30%';

            // STEP 3: Backend uses GET /api/download?url=&format_type=&quality=
            // (Old POST + JSON body caused 405 Method Not Allowed)
            const params = new URLSearchParams({
                url: currentVideoData.webpage_url,
                format_type: selectedFormat.type || 'video',
                quality: (selectedFormat.quality && selectedFormat.quality !== 'undefined')
                    ? selectedFormat.quality
                    : (selectedFormat.type === 'audio' ? 'm4a_best' : '720p')
            });

            progressStatusText.innerHTML = '<i class="fa-solid fa-cloud-arrow-down fa-spin"></i> Downloading file...';
            progressBarFill.style.width = '60%';
            progressPercent.textContent = '60%';

            const response = await fetch(`/api/download?${params.toString()}`, {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            // STEP 4: Handle error responses (JSON from FastAPI)
            if (!response.ok) {
                let detail = 'Download failed.';
                try {
                    const errBody = await response.json();
                    detail = errBody.detail || detail;
                } catch (_) {
                    // non-JSON error body
                }
                if (response.status === 403) {
                    throw new Error(detail || 'Security check failed. Please try again.');
                }
                throw new Error(detail);
            }

            // STEP 5: Always save as a local file (direct yt-dlp OR proxied Invidious stream)
            progressStatusText.innerHTML = '<i class="fa-solid fa-floppy-disk fa-spin"></i> Saving to device...';
            progressBarFill.style.width = '85%';
            progressPercent.textContent = '85%';

            const blob = await response.blob();
            if (!blob || blob.size < 1024) {
                // Tiny/empty body usually means an HTML error page leaked through
                throw new Error('Download file was empty. Please try another quality.');
            }

            let filename = 'download.mp4';
            const disposition = response.headers.get('Content-Disposition') || '';
            const filenameStar = disposition.match(/filename\*=UTF-8''([^;]+)/i);
            const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
            if (filenameStar && filenameStar[1]) {
                try {
                    filename = decodeURIComponent(filenameStar[1]);
                } catch (_) {
                    filename = filenameStar[1];
                }
            } else if (filenameMatch && filenameMatch[1]) {
                filename = filenameMatch[1];
            } else {
                const ext = selectedFormat.type === 'audio' ? 'mp3' : 'mp4';
                filename = `${(currentVideoData.title || 'video').slice(0, 80)}.${ext}`;
            }

            const mode = response.headers.get('X-Download-Mode') || 'direct';
            const provider = response.headers.get('X-Download-Provider') || '';

            progressStatusText.innerHTML = '<i class="fa-solid fa-circle-check" style="color: #10b981;"></i> Saved! Check your Downloads folder.';
            progressBarFill.style.width = '100%';
            progressPercent.textContent = '100%';

            const blobUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = blobUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);

            showToast(
                provider
                    ? `Saved: ${filename} (via ${provider})`
                    : `Saved to Downloads: ${filename}`,
                'success'
            );

            // Save to history
            saveToHistory({
                title: currentVideoData.title,
                thumbnail: currentVideoData.thumbnail,
                url: currentVideoData.webpage_url,
                format: selectedFormat.label,
                timestamp: new Date().toLocaleString()
            });

            setTimeout(() => {
                startDownloadBtn.disabled = false;
                downloadProgressBox.classList.add('hidden');
                isProcessing = false;
            }, 3000);

            // keep mode referenced for debugging
            console.log('Download complete:', { mode, provider, filename, bytes: blob.size });
            return;

        } catch (err) {
            progressStatusText.innerHTML = `<i class="fa-solid fa-circle-exclamation" style="color: #ef4444;"></i> ${err.message}`;
            progressBarFill.style.width = '100%';
            progressPercent.textContent = 'Failed';
            
            showToast(err.message, 'error');
            
            setTimeout(() => {
                startDownloadBtn.disabled = false;
                downloadProgressBox.classList.add('hidden');
                isProcessing = false;
            }, 3000);
            
            // Reset reCAPTCHA on error (COMMENTED for local/dev)
            // resetRecaptcha();
        }
    });

    // =========================================================================
    // History Drawer & LocalStorage Manager
    // =========================================================================
    function saveToHistory(item) {
        // Prevent duplicate URLs in recent items
        downloadHistory = [item, ...downloadHistory.filter(h => h.url !== item.url)].slice(0, 20);
        localStorage.setItem('prostream_history', JSON.stringify(downloadHistory));
        updateHistoryUI();
    }

    function updateHistoryUI() {
        historyBadge.textContent = downloadHistory.length;
        
        if (downloadHistory.length === 0) {
            historyList.innerHTML = `
                <div class="history-empty">
                    <i class="fa-solid fa-inbox"></i>
                    <p>No recent downloads found.</p>
                </div>
            `;
            return;
        }

        historyList.innerHTML = downloadHistory.map((item, idx) => `
            <div class="history-card">
                <img src="${item.thumbnail || 'https://via.placeholder.com/120x68'}" alt="" class="history-thumb">
                <div class="history-info">
                    <div class="history-item-title" title="${item.title}">${item.title || 'Untitled'}</div>
                    <div class="history-item-meta">
                        <span>${item.format || 'Unknown format'}</span> • <span>${item.timestamp || 'Recently'}</span>
                    </div>
                </div>
                <button class="history-item-action" onclick="window.reloadHistoryItem('${encodeURIComponent(item.url)}')" title="Analyze again">
                    <i class="fa-solid fa-rotate-right"></i>
                </button>
            </div>
        `).join('');
    }

    // Make function globally accessible for inline onclick
    window.reloadHistoryItem = (encodedUrl) => {
        const url = decodeURIComponent(encodedUrl);
        videoUrlInput.value = url;
        clearBtn.classList.remove('hidden');
        historyDrawer.classList.remove('open');
        downloadForm.dispatchEvent(new Event('submit'));
    };

    historyToggleBtn.addEventListener('click', () => {
        historyDrawer.classList.add('open');
        updateHistoryUI(); // Refresh on open
    });
    
    closeHistoryBtn.addEventListener('click', () => historyDrawer.classList.remove('open'));
    historyOverlay.addEventListener('click', () => historyDrawer.classList.remove('open'));

    clearHistoryBtn.addEventListener('click', () => {
        if (confirm('Are you sure you want to clear all download history?')) {
            downloadHistory = [];
            localStorage.removeItem('prostream_history');
            updateHistoryUI();
            showToast('Download history cleared.', 'success');
        }
    });

    // =========================================================================
    // FAQ Accordion
    // =========================================================================
    faqItems.forEach(item => {
        const questionBtn = item.querySelector('.faq-question');
        questionBtn.addEventListener('click', () => {
            const isActive = item.classList.contains('active');
            faqItems.forEach(i => i.classList.remove('active'));
            if (!isActive) item.classList.add('active');
        });
    });

    // =========================================================================
    // Toast Notification System
    // =========================================================================
    function showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const icon = type === 'success' ? 'fa-circle-check' : type === 'warning' ? 'fa-triangle-exclamation' : 'fa-circle-exclamation';
        toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;

        toastContainer.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        });

        // Auto dismiss
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-20px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // =========================================================================
    // Keyboard Shortcuts
    // =========================================================================
    document.addEventListener('keydown', (e) => {
        // Ctrl+Enter or Cmd+Enter to submit
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            if (document.activeElement === videoUrlInput) {
                downloadForm.dispatchEvent(new Event('submit'));
            }
        }
        
        // Escape key to close history
        if (e.key === 'Escape') {
            historyDrawer.classList.remove('open');
        }
    });

    // =========================================================================
    // Console Help
    // =========================================================================
    console.log('%c🚀 ProStream Media Downloader', 'font-size:20px; font-weight:bold; color:#6C63FF;');
    console.log('%cDownload videos from YouTube, Instagram, TikTok and more!', 'font-size:14px; color:#888;');
    // console.log('%c🔒 Protected with Google reCAPTCHA Enterprise', 'font-size:12px; color:#34A853;');
});