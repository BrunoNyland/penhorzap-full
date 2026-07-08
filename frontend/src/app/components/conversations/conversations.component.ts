import { Component, inject, signal, computed, OnInit, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePipe, NgClass } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { IconComponent } from '../../shared/icon/icon.component';

@Component({
  selector: 'app-conversations',
  standalone: true,
  imports: [FormsModule, DatePipe, NgClass, IconComponent],
  template: `
    <div class="conversa-layout">
      <!-- Left Panel: Chat List -->
      <div class="chat-list-panel card">
        <div class="panel-header">
          <h2>Atendimentos</h2>
          <p class="text-muted">Filtragem e controle de revisão humana</p>
          
          <div class="filter-controls margin-top-sm">
            <input 
              type="text" 
              placeholder="Buscar por JID, CPF ou Nome..." 
              [(ngModel)]="searchQuery" 
              (ngModelChange)="loadConversas()"
            />
            
            <div class="grid-2 margin-top-sm">
              <select [(ngModel)]="filterEstado" (change)="loadConversas()">
                <option value="">Todos os Estados</option>
                <option value="nova">Nova</option>
                <option value="aguardando_verificacao">Aguardando Verificação</option>
                <option value="verificada">Verificada</option>
                <option value="intencao_capturada">Intenção Capturada</option>
                <option value="aguardando_boleto">Aguardando Boleto</option>
                <option value="boleto_enviado">Boleto Enviado</option>
                <option value="encerrada">Encerrada</option>
              </select>
              
              <button 
                class="btn btn-secondary btn-small" 
                [class.btn-active]="filterRevisao() === '1'"
                (click)="toggleRevisaoFilter()"
              >
                <app-icon name="flag" [size]="14"></app-icon> Só Revisão
              </button>
            </div>
          </div>
        </div>

        <div class="chat-items-list margin-top">
          @if (loadingChats()) {
            <div class="list-placeholder">
              <div class="spinner spinner-small"></div>
              <span>Carregando conversas...</span>
            </div>
          } @else {
            @for (chat of conversas(); track chat.id) {
              <div 
                class="chat-item" 
                [class.active]="selectedChatId() === chat.id" 
                [class.needs-review]="chat.precisa_revisao_humana"
                (click)="selectChat(chat.id)"
              >
                <div class="chat-item-header flex justify-between">
                  <strong>{{ chat.nome_salvo || formatJid(chat.remote_jid) }}</strong>
                  <span class="chat-time">{{ formatTime(chat.ultima_interacao) }}</span>
                </div>
                <div class="chat-item-body flex justify-between align-center margin-top-xs">
                  <span class="chat-jid text-muted">{{ chat.cliente_nome || formatJid(chat.remote_jid) }}</span>
                  <span class="badge" [ngClass]="getStateBadgeClass(chat.estado)">
                    {{ getStateDisplay(chat.estado) }}
                  </span>
                </div>
                @if (chat.precisa_revisao_humana) {
                  <span class="review-indicator"><app-icon name="flag" [size]="12"></app-icon> Precisa Revisão</span>
                }
              </div>
            } @empty {
              <p class="text-muted text-center" style="padding: 24px;">Nenhuma conversa localizada.</p>
            }
          }
        </div>
      </div>

      <!-- Right Panel: Message Details -->
      <div class="chat-details-panel card">
        @if (loadingDetails()) {
          <div class="details-placeholder">
            <div class="spinner"></div>
            <p>Carregando histórico do chat...</p>
          </div>
        } @else if (activeChat()) {
          <!-- Chat Header -->
          <div class="detail-header flex align-center justify-between">
            <div>
              <h3>{{ activeChat().nome_salvo || activeChat().remote_jid }}</h3>
              <p class="text-muted">
                JID: <strong>{{ activeChat().remote_jid }}</strong> • Estado: 
                <span class="badge" [ngClass]="getStateBadgeClass(activeChat().estado)">
                  {{ getStateDisplay(activeChat().estado) }}
                </span>
              </p>
              @if (activeChat().cliente) {
                <p class="text-muted text-small">
                  Cliente: <strong>{{ activeChat().cliente.nome }}</strong> (CPF: {{ activeChat().cliente.cpf }})
                </p>
              }
            </div>
            
            <div class="flex gap-2">
              <button 
                class="btn" 
                [class.btn-danger]="!activeChat().precisa_revisao_humana" 
                [class.btn-secondary]="activeChat().precisa_revisao_humana"
                (click)="toggleRevisao(activeChat().id)"
              >
                @if (activeChat().precisa_revisao_humana) {
                  <app-icon name="check" [size]="14"></app-icon> Concluir Revisão
                } @else {
                  <app-icon name="flag" [size]="14"></app-icon> Marcar para Revisão
                }
              </button>
            </div>
          </div>

          <!-- Message History -->
          <div class="messages-viewport" #messagesContainer>
            @for (msg of activeChat().mensagens; track msg.id) {
              <div class="message-wrapper" [class.incoming]="msg.direcao === 'in'">
                <div class="message-balloon">
                  <div class="message-text">{{ msg.texto }}</div>
                  <div class="message-time text-muted">{{ msg.criado_em | date:'HH:mm' }}</div>
                </div>
              </div>
            } @empty {
              <p class="text-muted text-center" style="padding: 48px;">Histórico de mensagens vazio.</p>
            }
          </div>

          <!-- Solicitacoes & Boleto Upload Section -->
          <div class="solicitacoes-section">
            <h4>Solicitações neste atendimento</h4>
            
            <div class="solicitacoes-list margin-top-xs">
              @for (sol of activeChat().solicitacoes; track sol.id) {
                <div class="sol-card card">
                  <div class="sol-header flex justify-between align-center">
                    <strong>Solicitação #{{ sol.id }} - {{ getSolTipoDisplay(sol.tipo) }}</strong>
                    <span class="badge" [ngClass]="getSolStatusBadgeClass(sol.status)">
                      {{ getSolStatusDisplay(sol.status) }}
                    </span>
                  </div>
                  
                  <div class="sol-body margin-top-xs">
                    <p class="text-muted text-small">
                      Tipo: {{ sol.escopo === 'todos' ? 'Todos os contratos' : 'Contratos específicos' }}
                      • Criado em: {{ sol.criado_em | date:'dd/MM/yyyy HH:mm' }}
                    </p>
                    
                    @if (sol.precisa_humano) {
                      <div class="badge badge-warning margin-top-xs">IA encaminhou para operador</div>
                    }

                    <!-- Listed Boletos -->
                    @if (sol.boletos && sol.boletos.length > 0) {
                      <div class="boletos-list margin-top-xs">
                        <strong>Boletos Enviados:</strong>
                        <ul>
                          @for (bol of sol.boletos; track bol.id) {
                            <li>
                              <app-icon name="file-text" [size]="14"></app-icon> <a [href]="bol.arquivo" target="_blank" class="text-success">Ver PDF</a>
                              @if (bol.linha_digitavel) {
                                <br/><code class="text-small">{{ bol.linha_digitavel }}</code>
                              }
                            </li>
                          }
                        </ul>
                      </div>
                    }

                    <!-- Upload Form (visible only if status is PENDENTE) -->
                    @if (sol.status === 'pendente') {
                      <div class="upload-boleto-form card margin-top">
                        <h5 class="flex align-center gap-2"><app-icon name="send" [size]="14"></app-icon> Enviar Boleto para o Cliente</h5>
                        <form (ngSubmit)="enviarBoleto(sol.id)">
                          <div class="grid-2 margin-top-xs">
                            <div class="form-group">
                              <label>Arquivo PDF do Boleto</label>
                              <input 
                                type="file" 
                                accept="application/pdf" 
                                required
                                (change)="onBoletoFileSelected($event, sol.id)"
                              />
                            </div>
                            <div class="form-group">
                              <label>Linha Digitável (Opcional)</label>
                              <input 
                                type="text" 
                                placeholder="Digite a linha digitável..."
                                [(ngModel)]="boletoLinhas[sol.id]"
                                name="linha_digitavel"
                              />
                            </div>
                          </div>
                          <button 
                            type="submit" 
                            class="btn btn-primary btn-small margin-top-xs"
                            [disabled]="uploadingBoletoId() === sol.id || !boletoFiles[sol.id]"
                          >
                            {{ uploadingBoletoId() === sol.id ? 'Processando...' : 'Enviar Boleto ao WhatsApp' }}
                          </button>
                        </form>
                      </div>
                    }
                  </div>
                </div>
              } @empty {
                <p class="text-muted text-small">Nenhuma solicitação financeira criada pelo robô para este cliente.</p>
              }
            </div>
          </div>
        } @else {
          <div class="details-placeholder">
            <p>Selecione um atendimento na lista lateral para visualizar a conversa</p>
          </div>
        }
      </div>
    </div>
  `,
  styles: [`
    .conversa-layout {
      display: flex;
      gap: 24px;
      height: calc(100vh - 120px);
    }
    .chat-list-panel {
      width: 320px;
      display: flex;
      flex-direction: column;
      padding: 16px;
      flex-shrink: 0;
    }
    .chat-details-panel {
      flex: 1;
      display: flex;
      flex-direction: column;
      padding: 24px;
      overflow-y: auto;
    }
    .panel-header h2 {
      font-size: 20px;
      margin-bottom: 2px;
    }
    .margin-top-xs { margin-top: 6px; }
    .margin-top-sm { margin-top: 10px; }
    .btn-active {
      background-color: var(--color-danger);
      color: white;
      border-color: var(--color-danger);
    }
    .chat-items-list {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .chat-item {
      padding: 12px;
      border: 1px solid var(--border-color);
      border-radius: var(--radius-sm);
      cursor: pointer;
      transition: all var(--transition-fast);
      background-color: var(--bg-primary);
      position: relative;
    }
    .chat-item:hover {
      border-color: var(--color-accent);
    }
    .chat-item.active {
      border-color: var(--color-accent);
      background-color: var(--bg-surface);
    }
    .chat-item.needs-review {
      border-left: 4px solid var(--color-danger);
    }
    .chat-time {
      font-size: 11px;
      color: var(--text-muted);
    }
    .chat-jid {
      font-size: 12px;
      max-width: 170px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .review-indicator {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      color: var(--color-danger);
      font-weight: 600;
      margin-top: 4px;
    }
    .list-placeholder, .details-placeholder {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      flex: 1;
      color: var(--text-muted);
      gap: 12px;
    }
    .detail-header {
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border-color);
    }
    .detail-header h3 {
      font-size: 20px;
    }
    .messages-viewport {
      flex: 1;
      min-height: 250px;
      max-height: 450px;
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
      max-width: 75%;
      padding: 10px 14px;
      border-radius: var(--radius-md);
      font-size: 14px;
      line-height: 1.4;
      position: relative;
    }
    .message-wrapper.incoming .message-balloon {
      background-color: var(--bg-surface);
      color: var(--text-primary);
      border-bottom-left-radius: 2px;
    }
    .message-wrapper:not(.incoming) .message-balloon {
      background-color: var(--color-accent);
      color: white;
      border-bottom-right-radius: 2px;
    }
    .message-time {
      font-size: 10px;
      text-align: right;
      margin-top: 4px;
    }
    .message-wrapper:not(.incoming) .message-time {
      color: rgba(255, 255, 255, 0.7);
    }
    .solicitacoes-section {
      border-top: 1px solid var(--border-color);
      padding-top: 18px;
    }
    .sol-card {
      background-color: var(--bg-primary);
      border-color: var(--border-color);
      padding: 16px;
      margin-bottom: 12px;
    }
    .upload-boleto-form {
      background-color: var(--bg-secondary);
      border: 1px solid var(--border-color);
      padding: 16px;
    }
    .upload-boleto-form h5 {
      font-size: 13px;
      font-weight: 600;
    }
    .boletos-list ul {
      padding-left: 20px;
      margin-top: 4px;
    }
    .spinner-small {
      width: 20px;
      height: 20px;
      border-width: 2px;
    }
  `]
})
export class ConversationsComponent implements OnInit, OnDestroy {
  private apiService = inject(ApiService);

  conversas = signal<any[]>([]);
  activeChat = signal<any | null>(null);

  loadingChats = signal(false);
  loadingDetails = signal(false);
  uploadingBoletoId = signal<number | null>(null);

  searchQuery = '';
  filterEstado = '';
  filterRevisao = signal<'0' | '1'>('0');

  // Boleto upload form state helper maps
  boletoFiles: { [solicitacaoId: number]: File } = {};
  boletoLinhas: { [solicitacaoId: number]: string } = {};

  selectedChatId = signal<number | null>(null);
  private pollingInterval: any;

  ngOnInit(): void {
    this.loadConversas();
    // Setup polling every 8 seconds to fetch new incoming messages dynamically
    this.pollingInterval = setInterval(() => {
      this.loadConversas(true);
      if (this.selectedChatId()) {
        this.loadActiveChatDetails(this.selectedChatId()!, true);
      }
    }, 8000);
  }

  ngOnDestroy(): void {
    if (this.pollingInterval) {
      clearInterval(this.pollingInterval);
    }
  }

  loadConversas(silent = false): void {
    if (!silent) this.loadingChats.set(true);
    this.apiService.getConversas({
      estado: this.filterEstado,
      revisao: this.filterRevisao(),
      q: this.searchQuery
    }).subscribe({
      next: (data) => {
        this.conversas.set(data);
        this.loadingChats.set(false);
      },
      error: () => this.loadingChats.set(false)
    });
  }

  toggleRevisaoFilter(): void {
    this.filterRevisao.update(v => v === '0' ? '1' : '0');
    this.loadConversas();
  }

  selectChat(id: number): void {
    this.selectedChatId.set(id);
    this.loadActiveChatDetails(id);
  }

  loadActiveChatDetails(id: number, silent = false): void {
    if (!silent) this.loadingDetails.set(true);
    this.apiService.getConversa(id).subscribe({
      next: (data) => {
        this.activeChat.set(data);
        this.loadingDetails.set(false);
      },
      error: () => this.loadingDetails.set(false)
    });
  }

  toggleRevisao(id: number): void {
    this.apiService.toggleConversaRevisao(id).subscribe({
      next: (res) => {
        if (this.activeChat() && this.activeChat().id === id) {
          this.activeChat.update(chat => ({ ...chat, precisa_revisao_humana: res.precisa_revisao_humana }));
        }
        // Refresh conversations list to update indicators
        this.loadConversas(true);
      }
    });
  }

  onBoletoFileSelected(event: any, solicitacaoId: number): void {
    const file = event.target.files[0];
    if (file) {
      this.boletoFiles[solicitacaoId] = file;
    }
  }

  enviarBoleto(solicitacaoId: number): void {
    const file = this.boletoFiles[solicitacaoId];
    if (!file) return;

    this.uploadingBoletoId.set(solicitacaoId);
    
    const formData = new FormData();
    formData.append('arquivo', file);
    if (this.boletoLinhas[solicitacaoId]) {
      formData.append('linha_digitavel', this.boletoLinhas[solicitacaoId]);
    }

    this.apiService.uploadBoleto(solicitacaoId, formData).subscribe({
      next: () => {
        this.uploadingBoletoId.set(null);
        // Clear form values
        delete this.boletoFiles[solicitacaoId];
        delete this.boletoLinhas[solicitacaoId];
        // Reload details to show the updated status & boleto list
        if (this.selectedChatId()) {
          this.loadActiveChatDetails(this.selectedChatId()!);
        }
      },
      error: () => {
        this.uploadingBoletoId.set(null);
      }
    });
  }

  // --- Display Formatters ---
  formatJid(jid: string): string {
    if (!jid) return '';
    return jid.split('@')[0];
  }

  formatTime(dateStr: string): string {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }

  getStateDisplay(state: string): string {
    const states: { [key: string]: string } = {
      nova: 'Nova',
      aguardando_verificacao: 'Verificação Pendente',
      verificada: 'Verificada',
      intencao_capturada: 'Intenção Capturada',
      aguardando_boleto: 'Aguardando Boleto',
      boleto_enviado: 'Boleto Enviado',
      encerrada: 'Encerrada'
    };
    return states[state] || state;
  }

  getStateBadgeClass(state: string): string {
    const classes: { [key: string]: string } = {
      nova: 'badge-info',
      aguardando_verificacao: 'badge-warning',
      verificada: 'badge-success',
      intencao_capturada: 'badge-info',
      aguardando_boleto: 'badge-warning',
      boleto_enviado: 'badge-success',
      encerrada: 'badge-danger'
    };
    return classes[state] || 'badge-info';
  }

  getSolTipoDisplay(tipo: string): string {
    const tipos: { [key: string]: string } = {
      quitar: 'Quitar Contrato',
      amortizar: 'Amortizar',
      renovar: 'Renovar',
      parcela: 'Parcela',
      segunda_via: '2ª Via de Boleto',
      duvida: 'Dúvida Geral'
    };
    return tipos[tipo] || tipo;
  }

  getSolStatusDisplay(status: string): string {
    const statuses: { [key: string]: string } = {
      pendente: 'Pendente Operador',
      boleto_enviado: 'Boleto Enviado',
      concluida: 'Concluída'
    };
    return statuses[status] || status;
  }

  getSolStatusBadgeClass(status: string): string {
    const classes: { [key: string]: string } = {
      pendente: 'badge-warning',
      boleto_enviado: 'badge-info',
      concluida: 'badge-success'
    };
    return classes[status] || 'badge-info';
  }
}
