import { Component, inject, signal, computed, OnInit, AfterViewChecked, ViewChild, ElementRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgClass, JsonPipe } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { IconComponent } from '../../shared/icon/icon.component';

@Component({
  selector: 'app-simulator',
  standalone: true,
  imports: [FormsModule, NgClass, JsonPipe, IconComponent],
  template: `
    <div class="simulator-layout">
      <!-- Left Panel: Context Selection -->
      <div class="context-panel card">
        <h2>Simulador IA</h2>
        <p class="text-muted">Testar intenções e o System Prompt em tempo real.</p>

        <!-- Selected customer context -->
        <div class="selected-context-box card margin-top">
          <h4>Contexto de Cliente</h4>
          @if (selectedCliente()) {
            <div class="cliente-context-badge flex justify-between align-center margin-top-xs">
              <div>
                <strong>{{ selectedCliente().nome }}</strong>
                <br/><span class="text-muted text-small">CPF: {{ selectedCliente().cpf }}</span>
              </div>
              <button class="clear-file" (click)="removerCliente()">×</button>
            </div>
            <p class="text-small text-muted margin-top-sm">
              <app-icon name="check" [size]="14"></app-icon> O Gemini receberá a lista de contratos ativos deste cliente para simular as regras de negócio.
            </p>
          } @else {
            <p class="text-small text-muted margin-top-xs">Simulando como <strong>contato desconhecido</strong>.</p>
            
            <div class="search-box-group margin-top-sm">
              <label>Vincular Cliente para Teste</label>
              <input 
                type="text" 
                placeholder="Buscar cliente por CPF ou Nome..." 
                [(ngModel)]="searchQuery"
                (ngModelChange)="buscarClientes()"
              />
              
              @if (searchResults().length > 0) {
                <div class="results-popover">
                  @for (c of searchResults(); track c.cpf) {
                    <div class="popover-item" (click)="selecionarCliente(c.cpf)">
                      <strong>{{ c.nome }}</strong> ({{ c.cpf }})
                    </div>
                  }
                </div>
              }
            </div>
          }
        </div>

        <button class="btn btn-secondary width-100 margin-top" (click)="reiniciarChat()">
          <app-icon name="refresh-cw" [size]="14"></app-icon> Reiniciar Simulação
        </button>
      </div>

      <!-- Right Panel: Chat Interface -->
      <div class="chat-panel card">
        <div class="chat-header border-bottom padding-bottom-sm">
          <h3>Chat de Simulação</h3>
          <p class="text-muted text-small">As mensagens são temporárias (salvas apenas na sessão).</p>
        </div>

        <!-- Chat History viewport -->
        <div class="messages-viewport" #messagesContainer>
          @for (turn of turnos(); track idx; let idx = $index) {
            <div class="message-wrapper" [class.incoming]="turn.direcao === 'in'">
              <div class="message-balloon">
                <div class="message-text">{{ turn.texto }}</div>
                
                <!-- Debug Parameters under Gemini response -->
                @if (turn.direcao === 'out' && turn.debug) {
                  <div class="debug-panel margin-top-sm">
                    <div class="debug-title flex align-center gap-2">
                      <app-icon name="settings" [size]="14"></app-icon>
                      <span>Depuração da IA</span>
                    </div>
                    <ul class="debug-details">
                      <li>Intenção: <strong class="badge badge-info">{{ turn.debug.tipo_intencao }}</strong></li>
                      <li>Encaminhar p/ Humano: <span class="badge" [ngClass]="turn.debug.precisa_humano ? 'badge-warning' : 'badge-success'">{{ turn.debug.precisa_humano ? 'SIM' : 'NÃO' }}</span></li>
                      <li>Draft pronto: <span class="badge" [ngClass]="turn.debug.pronto_para_criar_solicitacao ? 'badge-success' : 'badge-danger'">{{ turn.debug.pronto_para_criar_solicitacao ? 'SIM' : 'NÃO' }}</span></li>
                      @if (turn.debug.cpf_extraido) {
                        <li>CPF extraído: <code>{{ turn.debug.cpf_extraido }}</code></li>
                      }
                      @if (turn.debug.solicitacoes?.length > 0) {
                        <li>
                          <strong>Solicitações Draft:</strong>
                          <pre class="debug-code">{{ turn.debug.solicitacoes | json }}</pre>
                        </li>
                      }
                    </ul>
                  </div>
                }
              </div>
            </div>
          } @empty {
            <div class="chat-empty-state">
              <p>Envie uma mensagem abaixo para iniciar a conversa com a IA.</p>
              <p class="text-muted text-small italic">Exemplo: "Gostaria de ver meu boleto de quitação"</p>
            </div>
          }
        </div>

        <!-- Chat Input field -->
        <div class="chat-input-row">
          <form (ngSubmit)="enviarMensagem()" class="flex gap-2">
            <input 
              type="text" 
              placeholder="Digite a mensagem de teste..." 
              [(ngModel)]="msgInput"
              name="msg"
              [disabled]="sending()"
              autocomplete="off"
            />
            <button 
              type="submit" 
              class="btn btn-primary"
              [disabled]="sending() || !msgInput.trim()"
            >
              {{ sending() ? '...' : 'Enviar' }}
            </button>
          </form>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .simulator-layout {
      display: flex;
      gap: 24px;
      height: calc(100vh - 120px);
    }
    .context-panel {
      width: 300px;
      flex-shrink: 0;
      padding: 16px;
      display: flex;
      flex-direction: column;
    }
    .chat-panel {
      flex: 1;
      display: flex;
      flex-direction: column;
      padding: 24px;
    }
    .margin-top { margin-top: 18px; }
    .margin-top-xs { margin-top: 6px; }
    .margin-top-sm { margin-top: 10px; }
    .margin-bottom-sm { margin-bottom: 12px; }
    .width-100 { width: 100%; }
    
    .border-bottom {
      border-bottom: 1px solid var(--border-color);
    }
    .padding-bottom-sm {
      padding-bottom: 12px;
    }
    .selected-context-box {
      background-color: var(--bg-surface);
      border-color: var(--border-color);
      padding: 14px;
    }
    .cliente-context-badge {
      background-color: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      padding: 8px 12px;
    }
    .search-box-group {
      position: relative;
    }
    .search-box-group label {
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
      display: block;
      margin-bottom: 4px;
    }
    .results-popover {
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      background-color: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      max-height: 150px;
      overflow-y: auto;
      z-index: 10;
      box-shadow: var(--shadow-lg);
    }
    .popover-item {
      padding: 8px 12px;
      cursor: pointer;
      font-size: 13px;
      border-bottom: 1px solid var(--border-color);
    }
    .popover-item:last-child {
      border-bottom: none;
    }
    .popover-item:hover {
      background-color: var(--bg-surface);
    }
    
    .messages-viewport {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      background-color: var(--bg-primary);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin: 18px 0;
    }
    .chat-empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      flex: 1;
      color: var(--text-muted);
      gap: 8px;
    }
    .message-wrapper {
      display: flex;
      width: 100%;
    }
    .message-wrapper.incoming {
      justify-content: flex-start;
    }
    .message-wrapper:not(.incoming) {
      justify-content: flex-end;
    }
    .message-balloon {
      max-width: 80%;
      padding: 10px 14px;
      border-radius: var(--radius-md);
      font-size: 14px;
      line-height: 1.4;
    }
    .message-wrapper.incoming .message-balloon {
      background-color: var(--color-accent);
      color: white;
      border-bottom-left-radius: 2px;
    }
    .message-wrapper:not(.incoming) .message-balloon {
      background-color: var(--bg-surface);
      color: var(--text-primary);
      border-bottom-right-radius: 2px;
      border: 1px solid var(--border-color);
    }
    
    .chat-input-row {
      margin-top: auto;
    }

    /* Debugger styling */
    .debug-panel {
      background-color: #0d1117;
      border: 1px solid #30363d;
      border-radius: var(--radius-sm);
      padding: 10px;
      margin-top: 8px;
      color: #8b949e;
      font-size: 12px;
    }
    .debug-title {
      font-weight: 600;
      color: #58a6ff;
      border-bottom: 1px solid #21262d;
      padding-bottom: 4px;
      margin-bottom: 6px;
    }
    .debug-details {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .debug-code {
      background-color: #161b22;
      padding: 6px;
      border-radius: 4px;
      font-family: monospace;
      font-size: 11px;
      overflow-x: auto;
      max-height: 100px;
      color: #ff7b72;
      margin-top: 4px;
    }
    .text-small { font-size: 12px; }
    .italic { font-style: italic; }
  `]
})
export class SimulatorComponent implements OnInit, AfterViewChecked {
  private apiService = inject(ApiService);

  @ViewChild('messagesContainer') private messagesContainer!: ElementRef;

  turnos = signal<any[]>([]);
  selectedCliente = signal<any | null>(null);

  searchQuery = '';
  searchResults = signal<any[]>([]);
  
  msgInput = '';
  sending = signal(false);

  ngOnInit(): void {
    this.fetchSimulatorState();
  }

  ngAfterViewChecked(): void {
    this.scrollToBottom();
  }

  fetchSimulatorState(): void {
    this.apiService.getSimulatorState().subscribe({
      next: (res) => {
        this.selectedCliente.set(res.cliente);
        this.turnos.set(res.turnos || []);
      }
    });
  }

  buscarClientes(): void {
    if (this.searchQuery.trim().length < 2) {
      this.searchResults.set([]);
      return;
    }
    this.apiService.getClientes({ q: this.searchQuery }).subscribe({
      next: (data) => {
        this.searchResults.set(data.slice(0, 5));
      }
    });
  }

  selecionarCliente(cpf: string): void {
    this.apiService.postSimulatorAction({ acao: 'selecionar_cliente', cpf }).subscribe({
      next: (res) => {
        this.selectedCliente.set(res.cliente);
        this.turnos.set(res.turnos || []);
        this.searchQuery = '';
        this.searchResults.set([]);
      }
    });
  }

  removerCliente(): void {
    this.apiService.postSimulatorAction({ acao: 'remover_cliente' }).subscribe({
      next: (res) => {
        this.selectedCliente.set(null);
        this.turnos.set(res.turnos || []);
      }
    });
  }

  enviarMensagem(): void {
    const text = this.msgInput.trim();
    if (!text || this.sending()) return;

    this.msgInput = '';
    this.sending.set(true);

    // Optimistic user bubble append
    this.turnos.update(list => [...list, { direcao: 'in', texto: text }]);

    this.apiService.postSimulatorAction({ acao: 'enviar', mensagem: text }).subscribe({
      next: (res) => {
        this.turnos.set(res.turnos || []);
        this.sending.set(false);
      },
      error: () => {
        this.sending.set(false);
      }
    });
  }

  reiniciarChat(): void {
    this.apiService.postSimulatorAction({ acao: 'reiniciar' }).subscribe({
      next: (res) => {
        this.turnos.set(res.turnos || []);
      }
    });
  }

  private scrollToBottom(): void {
    try {
      this.messagesContainer.nativeElement.scrollTop = this.messagesContainer.nativeElement.scrollHeight;
    } catch {}
  }
}
