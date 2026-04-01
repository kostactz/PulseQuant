export interface Intent {
  action: 'PLACE_ORDER' | 'CANCEL_ORDER';
  symbol: string;
  clientOrderId: string;
  side?: 'BUY' | 'SELL';
  quantity?: number;
  price?: number;
  type?: string;
  timeInForce?: string;
  retryCount?: number;
}

export type ExecuteIntentFn = (intent: Intent) => Promise<void>;

import { logger } from '../logger';

export class OrderManager {
  private cancelQueue: Intent[] = [];
  private placeQueue: Intent[] = [];
  
  // Token Bucket config (e.g., Binance Testnet defaults)
  private tokens: number;
  private maxTokens: number;
  private refillRate: number; // tokens per second
  private lastRefill: number;
  
  private isProcessing: boolean = false;
  private executeIntentFn: ExecuteIntentFn;
  private onOrderRejected?: (intent: Intent, reason: string) => void;
  private loopInterval: NodeJS.Timeout | null = null;
  private _stopped: boolean = true;

  constructor(executeIntentFn: ExecuteIntentFn, maxTokens = 40, refillRate = 20, onOrderRejected?: (intent: Intent, reason: string) => void) {
    this.executeIntentFn = executeIntentFn;
    this.maxTokens = maxTokens;
    this.tokens = maxTokens;
    this.refillRate = refillRate;
    this.lastRefill = Date.now();
    this.onOrderRejected = onOrderRejected;
  }

  public enqueueIntent(intent: Intent) {
    logger.orderFlow('ENQUEUED', intent);
    intent.retryCount = intent.retryCount || 0;
    if (intent.action === 'CANCEL_ORDER') {
      this.cancelQueue.push(intent);
      if (!this._stopped) {
        void this.processQueues().catch((err) => {
          logger.error?.('Failed to process queues in enqueueIntent', err);
        });
      }
    } else {
      this.placeQueue.push(intent);
      if (!this._stopped) {
        void this.processQueues().catch((err) => {
          logger.error?.('Failed to process queues in enqueueIntent', err);
        });
      }
    }
  }

  public startLoop() {
    if (!this._stopped) return;
    this._stopped = false;
    
    // Run the loop every 50ms to check queues
    this.loopInterval = setInterval(() => {
      this.processQueues();
    }, 50);
  }

  public stopLoop() {
    this._stopped = true;
    if (this.loopInterval) {
      clearInterval(this.loopInterval);
      this.loopInterval = null;
    }
  }

  private refillTokens() {
    const now = Date.now();
    const elapsedSec = (now - this.lastRefill) / 1000;
    const tokensToAdd = elapsedSec * this.refillRate;
    
    if (tokensToAdd > 0) {
      this.tokens = Math.min(this.maxTokens, this.tokens + tokensToAdd);
      this.lastRefill = now;
    }
  }

  private async processQueues() {
    if (this.isProcessing) return;
    this.isProcessing = true;

    try {
      this.refillTokens();

      while (this.tokens >= 1) {
        let intentToProcess: Intent | undefined;

        // Prioritize CANCELs
        if (this.cancelQueue.length > 0) {
          intentToProcess = this.cancelQueue.shift();
        } else if (this.placeQueue.length > 0) {
          intentToProcess = this.placeQueue.shift();
        }

        if (!intentToProcess) break; // Queues are empty

        this.tokens -= 1;

        try {
          logger.orderFlow('DISPATCHING', intentToProcess);
          await this.executeIntentFn(intentToProcess);
        } catch (error: any) {
          logger.error('Error executing intent', { intent: intentToProcess, error: error?.message });
          
          // Basic exponential backoff & retry
          if (intentToProcess.retryCount! < 3) {
            intentToProcess.retryCount!++;
            const backoffMs = Math.pow(2, intentToProcess.retryCount!) * 200;
            
            logger.warn('ORDER_RETRY', { attempt: intentToProcess.retryCount, max: 3, backoff: backoffMs });

            setTimeout(() => {
              // Re-enqueue for later
              this.enqueueIntent(intentToProcess!);
            }, backoffMs);
          } else {
            logger.error('ORDER_DROPPED', intentToProcess);
            if (this.onOrderRejected) {
              this.onOrderRejected(intentToProcess, error?.message || 'Max retries reached');
            }
          }
        }

        // Small delay between subsequent requests to be kind to the network stack
        await new Promise(res => setTimeout(res, 20));
        this.refillTokens();
      }
    } finally {
      this.isProcessing = false;
    }
  }
}
