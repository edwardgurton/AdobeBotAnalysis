// RateLimitManager.js - Centralized rate limiting with deadlock prevention
class RateLimitManager {
    constructor() {
        this.pauseUntil = 0;
        this.requestQueue = [];
        this.processing = false;
        this.activeRequests = 0;
        this.maxConcurrentRequests = 12; // Adobe's limit
        
        // Sliding window rate limiting: 12 requests per 6 seconds
        this.requestTimestamps = [];
        this.maxRequestsPerWindow = 12;
        this.windowSizeMs = 6000; // 6 seconds
        
        // Deadlock prevention
        this.lastProcessingTime = 0;
        this.processingTimeoutMs = 30000; // 30 seconds
        this.deadlockCheckInterval = null;
        
        // Start deadlock monitoring
        this.startDeadlockMonitoring();
    }

    // Monitor for deadlocks and force recovery
    startDeadlockMonitoring() {
        this.deadlockCheckInterval = setInterval(() => {
            const now = Date.now();
            const timeSinceLastProcessing = now - this.lastProcessingTime;
            
            // Check if we have a queue but haven't processed anything recently
            if (this.requestQueue.length > 0 && 
                this.processing && 
                timeSinceLastProcessing > this.processingTimeoutMs) {
                
                console.log(`🚨 DEADLOCK DETECTED! Queue: ${this.requestQueue.length}, Processing: ${this.processing}, Last activity: ${Math.round(timeSinceLastProcessing/1000)}s ago`);
                console.log(`🔧 Forcing recovery...`);
                
                // Force reset the processing flag
                this.processing = false;
                
                // Trigger queue processing
                setTimeout(() => this.processQueue(), 100);
            }
        }, 10000); // Check every 10 seconds
    }

    async executeRequest(requestFn, maxRetries = 3, requestId = 'Unknown') {
        return new Promise((resolve, reject) => {
            this.requestQueue.push({ 
                requestFn, 
                resolve, 
                reject, 
                retries: 0, 
                maxRetries,
                requestId,
                queuedAt: Date.now()
            });
            this.processQueue();
        });
    }

    // Check if we can send a request based on sliding window rate limit
    canSendRequest() {
        const now = Date.now();
        const windowStart = now - this.windowSizeMs;
        
        // Remove timestamps outside the current window
        this.requestTimestamps = this.requestTimestamps.filter(timestamp => timestamp > windowStart);
        
        // Check if we're under the rate limit
        return this.requestTimestamps.length < this.maxRequestsPerWindow;
    }
    
    // Calculate how long to wait until we can send the next request
    getWaitTimeForRateLimit() {
        if (this.requestTimestamps.length === 0) return 0;
        
        const now = Date.now();
        const oldestInWindow = this.requestTimestamps[0];
        const timeUntilOldestExpires = (oldestInWindow + this.windowSizeMs) - now;
        
        return Math.max(0, timeUntilOldestExpires);
    }

    async processQueue() {
        if (this.processing) {
            // Update last processing time even if we're already processing
            this.lastProcessingTime = Date.now();
            return;
        }
        
        this.processing = true;
        this.lastProcessingTime = Date.now();

        try {
            while (this.requestQueue.length > 0) {
                this.lastProcessingTime = Date.now(); // Update activity timestamp
                
                const now = Date.now();
                
                // Check global pause BEFORE processing any requests
                if (now < this.pauseUntil) {
                    const waitTime = this.pauseUntil - now;
                    console.log(`⏸️  Global pause active. Waiting ${Math.round(waitTime/1000)}s...`);
                    await new Promise(resolve => setTimeout(resolve, Math.min(waitTime, 5000))); // Max 5s wait per iteration
                    continue; // Recheck the pause after waiting
                }

                // Check concurrent request limit
                if (this.activeRequests >= this.maxConcurrentRequests) {
                    await new Promise(resolve => setTimeout(resolve, 100));
                    continue;
                }

                // Check sliding window rate limit
                if (!this.canSendRequest()) {
                    const waitTime = this.getWaitTimeForRateLimit();
                    if (waitTime > 0) {
                        console.log(`🕒 Rate limit: waiting ${Math.round(waitTime/1000)}s (${this.requestTimestamps.length}/${this.maxRequestsPerWindow} requests in last ${this.windowSizeMs/1000}s)`);
                        await new Promise(resolve => setTimeout(resolve, Math.min(waitTime, 5000))); // Max 5s wait per iteration
                        continue;
                    }
                }

                const requestItem = this.requestQueue.shift();
                if (!requestItem) continue; // Safety check
                
                this.activeRequests++;
                
                // Record the timestamp for rate limiting
                this.requestTimestamps.push(Date.now());
                
                // Don't await here - let it run in background but handle the result
                this.handleSingleRequest(requestItem).catch(error => {
                    console.error(`🚨 Unhandled error in handleSingleRequest:`, error);
                    this.activeRequests--; // Ensure we decrement on unhandled errors
                });
                
                // Small stagger between requests
                await new Promise(resolve => setTimeout(resolve, 50));
            }
        } catch (error) {
            console.error(`🚨 Error in processQueue:`, error);
        } finally {
            this.processing = false;
            this.lastProcessingTime = Date.now();
        }
        
        // Continue processing if there are more items in queue
        if (this.requestQueue.length > 0) {
            setTimeout(() => this.processQueue(), 100);
        }
    }

  async handleSingleRequest(requestItem) {
    const { requestFn, resolve, reject, retries, maxRetries, requestId, queuedAt } = requestItem;
    
    try {
        // Log if request has been waiting a long time
        const waitTime = Date.now() - queuedAt;
        if (waitTime > 30000) { // More than 30 seconds
            console.log(`⏰ Long-waiting request finally processing: ${requestId} (waited ${Math.round(waitTime/1000)}s)`);
        }
        
        // Double-check pause status right before making the request
        const now = Date.now();
        if (now < this.pauseUntil) {
            // If we're paused, put the request back in the queue
            this.activeRequests--;
            requestItem.retries = retries; // Don't increment retry count for pause
            this.requestQueue.unshift(requestItem);
            return;
        }

        const result = await requestFn();
        this.activeRequests--;
        
        // Log successful completion, especially for retried requests
        if (retries > 0) {
            console.log(`✅ Request SUCCESS after ${retries} retries: ${requestId}`);
        }
        
        resolve(result);
    } catch (error) {
        this.activeRequests--;
        
        // Handle rate limit errors (429)
        if (error.response && error.response.status === 429) {
            // Set global pause for 10 seconds from NOW
            const pauseDuration = 10000; // 10 seconds
            this.pauseUntil = Date.now() + pauseDuration;
            console.log(`🚫 Rate limit hit! Global pause until ${new Date(this.pauseUntil).toLocaleTimeString()}`);
            
            if (retries < maxRetries) {
                // Retry the request - put it back at the front of the queue
                requestItem.retries = retries + 1;
                console.log(`🔄 RETRYING (${retries + 1}/${maxRetries}) after 429 error: ${requestId}`);
                this.requestQueue.unshift(requestItem);
                
                // Trigger processing after a brief delay
                setTimeout(() => this.processQueue(), 1000);
            } else {
                console.error(`❌ MAX RETRIES EXCEEDED after 429 errors: ${requestId}`);
                reject(new Error(`Max retries exceeded after 429 rate limit errors for: ${requestId}`));
            }
        }
        // Handle server errors (500, 502, 503)
        else if (error.response && [500, 502, 503].includes(error.response.status)) {
            const statusCode = error.response.status;
            const errorType = {
                500: 'Internal Server Error',
                502: 'Bad Gateway',
                503: 'Service Unavailable'
            }[statusCode];
            
            if (retries < maxRetries) {
                // Retry the request after a short delay
                requestItem.retries = retries + 1;
                console.log(`🔄 RETRYING (${retries + 1}/${maxRetries}) after ${statusCode} ${errorType}: ${requestId}`);
                
                // Add a brief delay before retrying (2-5 seconds, with exponential backoff)
                const backoffDelay = Math.min(2000 * Math.pow(1.5, retries), 5000); // 2s, 3s, 4.5s, 5s max
                console.log(`⏳ Waiting ${Math.round(backoffDelay/1000)}s before retrying ${statusCode} error...`);
                
                setTimeout(() => {
                    this.requestQueue.unshift(requestItem);
                    this.processQueue();
                }, backoffDelay);
            } else {
                console.error(`❌ MAX RETRIES EXCEEDED after ${statusCode} errors: ${requestId}`);
                reject(new Error(`Max retries exceeded after ${statusCode} ${errorType} errors for: ${requestId}`));
            }
        }
        // Handle other errors (don't retry)
        else {
            console.error(`❌ Request FAILED (non-retryable error): ${requestId}`, error.message);
            reject(error);
        }
    }
}

    // Method to manually trigger a pause (useful for testing or external triggers)
    setPause(durationMs = 10000) {
        this.pauseUntil = Date.now() + durationMs;
        console.log(`⏸️  Manual pause set until ${new Date(this.pauseUntil).toLocaleTimeString()}`);
    }

    // Method to clear the pause
    clearPause() {
        this.pauseUntil = 0;
        console.log(`▶️  Pause cleared, resuming requests`);
    }

    // Method to force queue processing (useful for debugging)
    forceProcessQueue() {
        console.log(`🔧 Forcing queue processing...`);
        this.processing = false;
        setTimeout(() => this.processQueue(), 100);
    }

    getStatus() {
        const now = Date.now();
        const isPaused = now < this.pauseUntil;
        const windowStart = now - this.windowSizeMs;
        const recentRequests = this.requestTimestamps.filter(timestamp => timestamp > windowStart).length;
        const timeSinceLastProcessing = now - this.lastProcessingTime;
        
        return {
            queueLength: this.requestQueue.length,
            activeRequests: this.activeRequests,
            isPaused: isPaused,
            pauseUntil: isPaused ? new Date(this.pauseUntil).toLocaleTimeString() : null,
            pauseTimeRemaining: isPaused ? Math.round((this.pauseUntil - now) / 1000) : 0,
            processing: this.processing,
            timeSinceLastActivity: Math.round(timeSinceLastProcessing / 1000),
            rateLimit: {
                requestsInWindow: recentRequests,
                maxRequestsPerWindow: this.maxRequestsPerWindow,
                windowSizeSeconds: this.windowSizeMs / 1000,
                canSendNow: this.canSendRequest(),
                waitTimeMs: this.getWaitTimeForRateLimit()
            }
        };
    }

    // Clean up method
    destroy() {
        if (this.deadlockCheckInterval) {
            clearInterval(this.deadlockCheckInterval);
        }
    }
}

// Create singleton instance
const rateLimitManager = new RateLimitManager();

module.exports = rateLimitManager;