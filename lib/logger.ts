export type LogLevel = 'info' | 'warn' | 'error' | 'debug' | 'alert' | 'trade' | 'binance' | 'orderFlow' | 'network';

class Logger {
  private formatTime(): string {
    return new Date().toISOString();
  }

  private print(level: LogLevel, color: string, message: string, data?: any) {
    const time = this.formatTime();
    const prefix = `%c[${time}] [${level.toUpperCase()}]`;
    const style = `color: ${color}; font-weight: bold;`;
    
    if (data) {
      console.log(prefix + ` ${message}`, style, data);
    } else {
      console.log(prefix + ` ${message}`, style);
    }
  }

  info(message: string, data?: any) {
    this.print('info', '#3b82f6', message, data); // Blue
  }

  warn(message: string, data?: any) {
    this.print('warn', '#eab308', message, data); // Yellow
  }

  error(message: string, data?: any) {
    this.print('error', '#ef4444', message, data); // Red
  }

  debug(message: string, data?: any) {
    this.print('debug', '#8b5cf6', message, data); // Purple
  }

  alert(message: string, data?: any) {
    this.print('alert', '#f97316', message, data); // Orange
  }

  trade(action: string, data: any) {
    this.print('trade', '#22c55e', `TRADE EXECUTED: ${action.toUpperCase()}`, data); // Green
  }

  metrics(data: any) {
    this.print('info', '#06b6d4', 'PERIODIC METRICS EXTRACT', data); // Cyan
  }

  binance(message: string, data?: any) {
    this.print('binance', '#F3BA2F', message, data); // Binance Yellow
  }

  orderFlow(message: string, data?: any) {
    this.print('orderFlow', '#f97316', message, data); // Orange
  }

  network(message: string, data?: any) {
    this.print('network', '#14b8a6', message, data); // Teal
  }
}

export const logger = new Logger();
