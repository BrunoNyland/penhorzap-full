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
                <div class="message-text-wrapper flex justify-between align-start gap-2">
                  <div class="message-text" [innerHTML]="formatarMensagem(turn.texto)"></div>
                  @if (turn.direcao === 'out' && turn.debug?.raw_prompt) {
                    <button type="button" class="btn-prompt-debug" (click)="abrirModalPrompt(turn.debug)" title="Ver Prompt/Resposta da IA">
                      <app-icon name="file-text" [size]="16"></app-icon>
                    </button>
                  }
                </div>
                
                <!-- Debug Parameters under Gemini response -->
                @if (turn.direcao === 'out' && turn.debug) {
                  <div class="debug-panel margin-top-sm">
                    <div class="debug-title flex align-center justify-between gap-2">
                      <div class="flex align-center gap-2">
                        <app-icon name="settings" [size]="14"></app-icon>
                        <span>Depuração da IA</span>
                      </div>
                      @if (turn.debug.raw_prompt) {
                        <button type="button" class="btn-ver-prompt" (click)="abrirModalPrompt(turn.debug)">
                          <app-icon name="file-text" [size]="12"></app-icon> Ver Prompt/Response IA
                        </button>
                      }
                    </div>
                    <ul class="debug-details">
                      <li>
                        Ações:
                        @if (turn.debug.acoes?.length > 0) {
                          <span class="acoes-chips">
                            @for (acao of turn.debug.acoes; track acao) {
                              <span class="badge badge-info">{{ acao }}</span>
                            }
                          </span>
                        } @else {
                          <span class="badge">nenhuma</span>
                        }
                      </li>
                      <li>Encaminhar p/ Humano: <span class="badge" [ngClass]="turn.debug.precisa_humano ? 'badge-warning' : 'badge-success'">{{ turn.debug.precisa_humano ? 'SIM' : 'NÃO' }}</span></li>
                      <li>Draft pronto: <span class="badge" [ngClass]="turn.debug.pronto_para_criar_solicitacao ? 'badge-success' : 'badge-danger'">{{ turn.debug.pronto_para_criar_solicitacao ? 'SIM' : 'NÃO' }}</span></li>
                      @if (turn.debug.duvidas_sem_faq?.length > 0) {
                        <li>
                          <strong>Dúvidas sem FAQ:</strong>
                          <pre class="debug-code">{{ turn.debug.duvidas_sem_faq | json }}</pre>
                        </li>
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
            <textarea 
              placeholder="Digite a mensagem de teste..." 
              [(ngModel)]="msgInput"
              name="msg"
              [disabled]="sending()"
              (keydown)="onKeydown($event)"
              rows="1"
            ></textarea>
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

    <!-- Prompt/Response Viewer Modal -->
    @if (modalPromptAberto() && activeDebugData()) {
      <div class="modal-overlay" (click)="fecharModalPrompt()">
        <div class="modal-content modal-prompt fade-in" (click)="$event.stopPropagation()">
          <div class="modal-header flex justify-between align-center border-bottom padding-bottom-sm">
            <h3 class="flex align-center gap-2">
              <app-icon name="file-text" [size]="18"></app-icon>
              <span>Prompt & Resposta do Gemini</span>
            </h3>
            <button type="button" class="clear-file" style="font-size: 24px; cursor: pointer; border: none; background: transparent; color: var(--text-primary);" (click)="fecharModalPrompt()">×</button>
          </div>
          
          <div class="modal-body-scroll margin-top" style="max-height: 60vh; overflow-y: auto; display: flex; flex-direction: column; gap: 16px;">
            <div>
              <h4 style="margin-bottom: 6px; color: var(--color-accent);">Prompt Enviado (System Instruction & Contents)</h4>
              <pre class="debug-code-modal">{{ activeDebugData().raw_prompt }}</pre>
            </div>
            
            <div>
              <h4 style="margin-bottom: 6px; color: #58a6ff;">Resposta Recebida (JSON)</h4>
              <pre class="debug-code-modal">{{ activeDebugData().raw_response }}</pre>
            </div>
          </div>
          
          <div class="modal-footer margin-top flex justify-end" style="border-top: 1px solid var(--border-color); padding-top: 12px; margin-top: 16px;">
            <button type="button" class="btn btn-secondary" (click)="fecharModalPrompt()">Fechar</button>
          </div>
        </div>
      </div>
    }
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
    .message-text {
      white-space: pre-wrap;
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
    .chat-input-row textarea {
      flex: 1;
      resize: none;
      min-height: 38px;
      max-height: 120px;
      font-family: inherit;
      font-size: 14px;
      padding: 8px 12px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-color);
      background-color: var(--bg-secondary);
      color: var(--text-primary);
      outline: none;
    }
    .chat-input-row textarea:focus {
      border-color: var(--color-accent);
    }
    .chat-input-row button {
      height: 38px;
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
    .acoes-chips {
      display: inline-flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-left: 4px;
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

    @media (max-width: 639px) {
      .simulator-layout {
        flex-direction: column;
        height: auto;
        gap: 16px;
      }
      .context-panel {
        width: 100%;
        flex-shrink: 1;
        padding: 14px;
      }
      .chat-panel {
        padding: 16px;
        min-height: 65vh;
      }
      .messages-viewport {
        max-height: 55vh;
      }
      .message-balloon {
        max-width: 90%;
      }
    }
    
    .btn-prompt-debug {
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      padding: 2px 6px;
      border-radius: var(--radius-sm);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s ease;
    }
    .btn-prompt-debug:hover {
      color: var(--color-accent);
      background-color: var(--bg-secondary);
    }
    .btn-ver-prompt {
      background: #21262d;
      border: 1px solid #30363d;
      color: #c9d1d9;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 11px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s ease;
    }
    .btn-ver-prompt:hover {
      background-color: #30363d;
      border-color: #8b949e;
      color: #f0f6fc;
    }
    .modal-prompt {
      max-width: 850px !important;
      width: 90% !important;
    }
    .debug-code-modal {
      background-color: #0d1117;
      color: #c9d1d9;
      padding: 12px;
      border-radius: 6px;
      border: 1px solid #30363d;
      font-family: monospace;
      font-size: 12px;
      overflow-x: auto;
      max-height: 280px;
      white-space: pre-wrap;
      word-wrap: break-word;
      margin: 0;
    }
    .message-text-wrapper {
      width: 100%;
    }
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

  modalPromptAberto = signal(false);
  activeDebugData = signal<any | null>(null);

  abrirModalPrompt(debugData: any): void {
    this.activeDebugData.set(debugData);
    this.modalPromptAberto.set(true);
  }

  fecharModalPrompt(): void {
    this.modalPromptAberto.set(false);
    this.activeDebugData.set(null);
  }

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

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.enviarMensagem();
    }
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

  formatarMensagem(texto: string): string {
    if (!texto) return '';
    // Escapa HTML para prevenir XSS
    let html = texto
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Formatação estilo WhatsApp: *texto* em negrito e _texto_ em itálico
    html = html
      .replace(/(?:\*)([^\s*]|[^\s*](?:[^*]*?[^\s*])?)(?:\*)/g, '<strong>$1</strong>')
      .replace(/(?:_)([^\s_]|[^\s_](?:[^_]*?[^\s_])?)(?:_)/g, '<em>$1</em>')
      .replace(/\n/g, '<br>');

    return html;
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
