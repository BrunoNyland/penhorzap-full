import { Component, inject, signal, OnInit, OnDestroy } from '@angular/core';
import { NgClass } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { IconComponent } from '../../shared/icon/icon.component';

@Component({
  selector: 'app-whatsapp',
  standalone: true,
  imports: [NgClass, IconComponent],
  template: `
    <div class="whatsapp-wrapper">
      <div class="whatsapp-header">
        <h1>Conexão WhatsApp (Evolution API)</h1>
        <p class="text-muted">Monitore a integridade da instância e ative o robô de inteligência artificial.</p>
      </div>

      <div class="grid-2 margin-top">
        <!-- Status Card -->
        <div class="card status-card">
          <h2>Estado da Instância</h2>
          
          <div class="status-indicator-box flex align-center margin-top gap-4">
            <span class="status-dot" [ngClass]="state().state"></span>
            <div>
              <h3>{{ getConnectionStateDisplay(state().state) }}</h3>
              <p class="text-muted text-small">Código técnico: {{ state().state || 'carregando...' }}</p>
            </div>
          </div>

          <div class="bot-control-box card margin-top">
            <h4>Processador Inteligente (Bot)</h4>
            <p class="text-muted text-small margin-top-xs">
              Quando ativado, o robô consome as mensagens recebidas e responde de acordo com as instruções.
            </p>
            <div class="flex justify-between align-center margin-top">
              <strong>Status do Bot:</strong>
              <button 
                class="btn" 
                [class.btn-primary]="!state().bot_ativo" 
                [class.btn-danger]="state().bot_ativo"
                (click)="toggleBot()"
              >
                @if (state().bot_ativo) {
                  <app-icon name="stop-circle" [size]="14"></app-icon> Desativar Robô
                } @else {
                  <app-icon name="zap" [size]="14"></app-icon> Ativar Robô
                }
              </button>
            </div>
          </div>
        </div>

        <!-- Connection Screen (QR Code or Success) -->
        <div class="card qrcode-card flex align-center justify-center">
          @if (loadingState()) {
            <div class="placeholder-box">
              <div class="spinner"></div>
              <p class="margin-top-sm">Consultando estado...</p>
            </div>
          } @else if (state().state === 'open') {
            <div class="success-box text-center">
              <div class="success-icon"><app-icon name="check" [size]="36"></app-icon></div>
              <h3>Instância Conectada!</h3>
              <p class="text-muted text-small margin-top-xs">Tudo pronto. O bot está escutando eventos de mensagens no WhatsApp do estabelecimento.</p>
            </div>
          } @else if (state().qrcode_base64) {
            <div class="qr-box text-center">
              <h3>Leia o QR Code</h3>
              <p class="text-muted text-small margin-top-xs">Abra o WhatsApp no seu telefone > Aparelhos conectados > Conectar um aparelho.</p>
              
              <div class="qr-image-wrapper margin-top">
                <img [src]="state().qrcode_base64" alt="WhatsApp QR Code" />
              </div>
              
              <p class="text-muted text-small margin-top-sm italic">
                O código atualiza sozinho. Mantenha esta tela aberta.
              </p>
            </div>
          } @else {
            <div class="placeholder-box text-center">
              <div class="spinner"></div>
              <h3>Aguardando QR Code...</h3>
              <p class="text-muted text-small margin-top-xs">Se o código demorar para aparecer, verifique o docker da Evolution API.</p>
            </div>
          }
        </div>
      </div>
    </div>
  `,
  styles: [`
    .whatsapp-wrapper {
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .whatsapp-header h1 {
      font-size: 26px;
      font-weight: 700;
    }
    .margin-top { margin-top: 18px; }
    .margin-top-xs { margin-top: 6px; }
    .margin-top-sm { margin-top: 10px; }
    .grid-2 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 24px;
    }
    .status-card {
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .status-indicator-box {
      background-color: var(--bg-primary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-md);
      padding: 20px;
    }
    .status-dot {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background-color: var(--text-muted);
      display: inline-block;
      box-shadow: 0 0 0 4px rgba(0, 0, 0, 0.1);
      animation: pulse 2s infinite;
    }
    .status-dot.open {
      background-color: var(--color-success);
      box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.2);
    }
    .status-dot.connecting {
      background-color: var(--color-warning);
      box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.2);
    }
    .status-dot.close, .status-dot.refused {
      background-color: var(--color-danger);
      box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.2);
    }
    @keyframes pulse {
      0% { transform: scale(0.95); opacity: 0.8; }
      50% { transform: scale(1.05); opacity: 1; }
      100% { transform: scale(0.95); opacity: 0.8; }
    }
    .bot-control-box {
      background-color: var(--bg-surface);
      border-color: var(--border-color);
      padding: 16px;
    }
    .qrcode-card {
      min-height: 400px;
    }
    .success-box .success-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--color-success);
      background-color: var(--color-success-bg);
      width: 80px;
      height: 80px;
      border-radius: 50%;
      margin: 0 auto 16px;
    }
    .qr-image-wrapper {
      background-color: white;
      padding: 16px;
      border-radius: var(--radius-md);
      display: inline-block;
    }
    .qr-image-wrapper img {
      max-width: 250px;
      width: 100%;
      display: block;
    }
    .italic { font-style: italic; }
    .text-small { font-size: 12px; }
  `]
})
export class WhatsappComponent implements OnInit, OnDestroy {
  private apiService = inject(ApiService);

  state = signal<any>({ state: 'loading', bot_ativo: false });
  loadingState = signal(false);

  private pollInterval: any;

  ngOnInit(): void {
    this.fetchState();
    // Poll the status every 5 seconds
    this.pollInterval = setInterval(() => {
      this.fetchState(true);
    }, 5000);
  }

  ngOnDestroy(): void {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
    }
  }

  fetchState(silent = false): void {
    if (!silent) this.loadingState.set(true);
    this.apiService.getWhatsappState().subscribe({
      next: (res) => {
        this.state.set(res);
        this.loadingState.set(false);
      },
      error: () => {
        this.state.set({ state: 'error', bot_ativo: false });
        this.loadingState.set(false);
      }
    });
  }

  toggleBot(): void {
    this.apiService.toggleWhatsappBot().subscribe({
      next: (res) => {
        this.state.set(res);
      }
    });
  }

  getConnectionStateDisplay(state: string): string {
    const states: { [key: string]: string } = {
      open: 'Conectado (WhatsApp Web Ativo)',
      connecting: 'Conectando...',
      close: 'Desconectado',
      loading: 'Carregando...',
      error: 'Erro de comunicação backend'
    };
    return states[state] || 'Aparelho Desconectado';
  }
}
